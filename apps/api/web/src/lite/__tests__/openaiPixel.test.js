/**
 * openaiPixel.js — the one module allowed to touch window.oaiq.
 *
 * The contract under test is narrow but load-bearing: the exact four
 * arguments the SDK receives, the once-per-token-per-session guard,
 * and the two ways this can be asked to run in a browser that can't
 * cooperate — no SDK at all, and storage that throws. Both must
 * degrade rather than break, in opposite directions: no SDK means
 * send nothing, broken storage means send anyway (an under-count is
 * worse than a duplicate the event_id will collapse server-side).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import { isOpenAIPixelAvailable, trackAuditScoreRendered, withOppref } from '../openaiPixel.js'

function expectedArgs(token) {
  return [
    'measure',
    'custom',
    { type: 'custom' },
    { custom_event_name: 'audit_score_rendered', event_id: `audit_score_rendered:${token}` },
  ]
}

describe('trackAuditScoreRendered — the conversion payload', () => {
  beforeEach(() => {
    sessionStorage.clear()
    window.oaiq = vi.fn()
  })
  afterEach(() => {
    delete window.oaiq
  })

  it('fires once with the exact four arguments and returns true', () => {
    expect(trackAuditScoreRendered('tok-a')).toBe(true)
    expect(window.oaiq).toHaveBeenCalledTimes(1)
    expect(window.oaiq).toHaveBeenCalledWith(...expectedArgs('tok-a'))
  })

  it('carries no amount/currency/plan_id/contents and no user object', () => {
    trackAuditScoreRendered('tok-a')
    const [, , context, data] = window.oaiq.mock.calls[0]
    expect(context).toEqual({ type: 'custom' })
    expect(Object.keys(data).sort()).toEqual(['custom_event_name', 'event_id'])
    for (const banned of ['amount', 'currency', 'plan_id', 'contents', 'user']) {
      expect(data).not.toHaveProperty(banned)
      expect(context).not.toHaveProperty(banned)
    }
  })

  it('a second call for the same token does not fire and returns false', () => {
    expect(trackAuditScoreRendered('tok-a')).toBe(true)
    expect(trackAuditScoreRendered('tok-a')).toBe(false)
    expect(trackAuditScoreRendered('tok-a')).toBe(false)
    expect(window.oaiq).toHaveBeenCalledTimes(1)
  })

  it('a different token fires — the guard is per token, not global', () => {
    expect(trackAuditScoreRendered('tok-a')).toBe(true)
    expect(trackAuditScoreRendered('tok-b')).toBe(true)
    expect(window.oaiq).toHaveBeenCalledTimes(2)
    expect(window.oaiq).toHaveBeenNthCalledWith(2, ...expectedArgs('tok-b'))
  })

  it('an empty token fires nothing and returns false', () => {
    expect(trackAuditScoreRendered('')).toBe(false)
    expect(trackAuditScoreRendered(null)).toBe(false)
    expect(trackAuditScoreRendered(undefined)).toBe(false)
    expect(window.oaiq).not.toHaveBeenCalled()
  })
})

describe('trackAuditScoreRendered — no SDK on the page', () => {
  beforeEach(() => {
    sessionStorage.clear()
    delete window.oaiq
  })

  it('returns false, throws nothing, and writes nothing to storage', () => {
    expect(isOpenAIPixelAvailable()).toBe(false)
    let result
    expect(() => {
      result = trackAuditScoreRendered('tok-blocked')
    }).not.toThrow()
    expect(result).toBe(false)
    expect(sessionStorage.length).toBe(0)
  })

  // An ad blocker can leave a non-callable window.oaiq behind; the
  // gate is typeof === 'function', not mere presence.
  it('a non-callable window.oaiq is treated as unavailable', () => {
    window.oaiq = { q: [] }
    expect(isOpenAIPixelAvailable()).toBe(false)
    expect(trackAuditScoreRendered('tok-stub')).toBe(false)
    expect(sessionStorage.length).toBe(0)
    delete window.oaiq
  })

  it('the guard is not consumed while the SDK is missing — a later load still fires', () => {
    expect(trackAuditScoreRendered('tok-late')).toBe(false)
    window.oaiq = vi.fn()
    expect(trackAuditScoreRendered('tok-late')).toBe(true)
    expect(window.oaiq).toHaveBeenCalledTimes(1)
    delete window.oaiq
  })
})

describe('trackAuditScoreRendered — sessionStorage throwing', () => {
  let getItemSpy
  let setItemSpy

  beforeEach(() => {
    sessionStorage.clear()
    window.oaiq = vi.fn()
    getItemSpy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage blocked')
    })
    setItemSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage blocked')
    })
  })
  afterEach(() => {
    getItemSpy.mockRestore()
    setItemSpy.mockRestore()
    delete window.oaiq
  })

  it('still fires exactly once per call and throws nothing', () => {
    let first
    let second
    expect(() => {
      first = trackAuditScoreRendered('tok-nostorage')
    }).not.toThrow()
    expect(() => {
      second = trackAuditScoreRendered('tok-nostorage')
    }).not.toThrow()

    expect(first).toBe(true)
    expect(second).toBe(true)
    expect(window.oaiq).toHaveBeenCalledTimes(2)
    // Both calls carry the same event_id, so OpenAI collapses them
    // server-side — the storage guard is not the only line of defense.
    expect(window.oaiq).toHaveBeenNthCalledWith(1, ...expectedArgs('tok-nostorage'))
    expect(window.oaiq).toHaveBeenNthCalledWith(2, ...expectedArgs('tok-nostorage'))
  })
})

describe('trackAuditScoreRendered — the SDK itself throwing', () => {
  beforeEach(() => {
    sessionStorage.clear()
    window.oaiq = vi.fn(() => {
      throw new Error('partially loaded SDK')
    })
  })
  afterEach(() => {
    delete window.oaiq
  })

  it('returns false without throwing, and does not burn the guard', () => {
    let result
    expect(() => {
      result = trackAuditScoreRendered('tok-throws')
    }).not.toThrow()
    expect(result).toBe(false)
    expect(sessionStorage.getItem('oaiq:audit_score_rendered:tok-throws')).toBeNull()
  })
})

describe('withOppref', () => {
  afterEach(() => {
    window.history.replaceState(null, '', '/')
  })

  it('appends oppref from the current URL', () => {
    window.history.replaceState(null, '', '/audit.html?oppref=xyz')
    expect(withOppref('/r/abc')).toBe('/r/abc?oppref=xyz')
  })

  it('returns the bare path when the URL carries no oppref', () => {
    window.history.replaceState(null, '', '/audit.html')
    expect(withOppref('/r/abc')).toBe('/r/abc')
  })

  it('returns the bare path when oppref is present but empty', () => {
    window.history.replaceState(null, '', '/audit.html?oppref=')
    expect(withOppref('/r/abc')).toBe('/r/abc')
  })

  it('carries ONLY oppref — never src or any other param', () => {
    window.history.replaceState(null, '', '/audit.html?oppref=xyz&src=email&utm_source=ads')
    expect(withOppref('/r/abc')).toBe('/r/abc?oppref=xyz')
  })

  it('url-encodes the value rather than pasting it into the path raw', () => {
    window.history.replaceState(null, '', '/audit.html?oppref=' + encodeURIComponent('a b&c=d'))
    expect(withOppref('/r/abc')).toBe(`/r/abc?oppref=${encodeURIComponent('a b&c=d')}`)
  })

  it('joins with & when the path already has a query string', () => {
    window.history.replaceState(null, '', '/audit.html?oppref=xyz')
    expect(withOppref('/r/abc?foo=1')).toBe('/r/abc?foo=1&oppref=xyz')
  })
})
