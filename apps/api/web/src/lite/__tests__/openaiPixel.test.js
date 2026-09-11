/**
 * openaiPixel.js — the one module allowed to touch window.oaiq.
 *
 * Three STANDARD OpenAI conversions, each with the same contract: the
 * exact arguments the SDK receives, a once-per-key-per-session guard,
 * and two ways a browser can refuse to cooperate — no SDK at all, and
 * storage that throws. Those two degrade in OPPOSITE directions on
 * purpose: no SDK means send nothing, broken storage means send
 * anyway (an under-count is worse than a duplicate the event_id will
 * collapse server-side).
 *
 * The payload shapes are OpenAI's, not ours, so they are asserted
 * literally rather than built from helpers — a test that constructed
 * the expected object the same way the source does would pass through
 * any shared mistake.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import {
  isOpenAIPixelAvailable,
  newRequestId,
  trackAppointmentScheduled,
  trackLeadCreated,
  trackReportContentsViewed,
  withOppref,
} from '../openaiPixel.js'

// One row per event: how it is called, the exact four arguments it
// must produce, and the guard key it must claim. Every shared
// behavior below is driven off this table so a fourth event cannot be
// added later without also being held to all of it.
const EVENTS = [
  {
    name: 'lead_created',
    call: (key) => trackLeadCreated(key),
    keyA: 'tok-a',
    keyB: 'tok-b',
    guard: (key) => `oaiq:lead_created:${key}`,
    args: (key) => [
      'measure',
      'lead_created',
      { type: 'customer_action' },
      { event_id: `lead_created:${key}` },
    ],
  },
  {
    name: 'appointment_scheduled',
    call: (key) => trackAppointmentScheduled({ reportToken: key }),
    keyA: 'tok-a',
    keyB: 'tok-b',
    guard: (key) => `oaiq:appointment_scheduled:${key}`,
    args: (key) => [
      'measure',
      'appointment_scheduled',
      { type: 'customer_action' },
      { event_id: `appointment_scheduled:${key}` },
    ],
  },
  {
    name: 'contents_viewed',
    call: (key) => trackReportContentsViewed({ token: key, brandName: 'Allbirds' }),
    keyA: 'tok-a',
    keyB: 'tok-b',
    guard: (key) => `oaiq:contents_viewed:${key}`,
    args: (key) => [
      'measure',
      'contents_viewed',
      { type: 'contents', contents: [{ id: key, name: 'Allbirds', content_type: 'report' }] },
      { event_id: `contents_viewed:${key}` },
    ],
  },
]

describe.each(EVENTS)('$name — payload and guard', (evt) => {
  beforeEach(() => {
    sessionStorage.clear()
    window.oaiq = vi.fn()
  })
  afterEach(() => {
    delete window.oaiq
  })

  it('fires once with the exact four arguments and returns true', () => {
    expect(evt.call(evt.keyA)).toBe(true)
    expect(window.oaiq).toHaveBeenCalledTimes(1)
    expect(window.oaiq).toHaveBeenCalledWith(...evt.args(evt.keyA))
    expect(sessionStorage.getItem(evt.guard(evt.keyA))).toBe('1')
  })

  it('a second call with the same key returns false and does not fire', () => {
    expect(evt.call(evt.keyA)).toBe(true)
    expect(evt.call(evt.keyA)).toBe(false)
    expect(evt.call(evt.keyA)).toBe(false)
    expect(window.oaiq).toHaveBeenCalledTimes(1)
  })

  it('a different key fires — the guard is per key, not global', () => {
    expect(evt.call(evt.keyA)).toBe(true)
    expect(evt.call(evt.keyB)).toBe(true)
    expect(window.oaiq).toHaveBeenCalledTimes(2)
    expect(window.oaiq).toHaveBeenNthCalledWith(2, ...evt.args(evt.keyB))
  })

  // custom_event_name is valid only for custom events; none of these
  // three may carry it, and none may carry money fields.
  it('carries no custom_event_name, amount, currency, plan_id or user', () => {
    evt.call(evt.keyA)
    const [, , data, options] = window.oaiq.mock.calls[0]
    expect(Object.keys(options)).toEqual(['event_id'])
    for (const banned of ['custom_event_name', 'amount', 'currency', 'plan_id', 'user']) {
      expect(data).not.toHaveProperty(banned)
      expect(options).not.toHaveProperty(banned)
    }
  })

  it('an empty key fires nothing and returns false', () => {
    expect(evt.call('')).toBe(false)
    expect(evt.call(null)).toBe(false)
    expect(evt.call(undefined)).toBe(false)
    expect(window.oaiq).not.toHaveBeenCalled()
  })
})

describe.each(EVENTS)('$name — no SDK on the page', (evt) => {
  beforeEach(() => {
    sessionStorage.clear()
    delete window.oaiq
  })

  it('returns false, throws nothing, and writes nothing to storage', () => {
    expect(isOpenAIPixelAvailable()).toBe(false)
    let result
    expect(() => {
      result = evt.call(evt.keyA)
    }).not.toThrow()
    expect(result).toBe(false)
    expect(sessionStorage.length).toBe(0)
  })

  // An ad blocker can leave a non-callable window.oaiq behind; the
  // gate is typeof === 'function', not mere presence.
  it('a non-callable window.oaiq is treated as unavailable', () => {
    window.oaiq = { q: [] }
    expect(isOpenAIPixelAvailable()).toBe(false)
    expect(evt.call(evt.keyA)).toBe(false)
    expect(sessionStorage.length).toBe(0)
    delete window.oaiq
  })

  it('the guard is not consumed while the SDK is missing — a later load still fires', () => {
    expect(evt.call(evt.keyA)).toBe(false)
    window.oaiq = vi.fn()
    expect(evt.call(evt.keyA)).toBe(true)
    expect(window.oaiq).toHaveBeenCalledTimes(1)
    delete window.oaiq
  })
})

describe.each(EVENTS)('$name — sessionStorage throwing', (evt) => {
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
      first = evt.call(evt.keyA)
    }).not.toThrow()
    expect(() => {
      second = evt.call(evt.keyA)
    }).not.toThrow()

    expect(first).toBe(true)
    expect(second).toBe(true)
    expect(window.oaiq).toHaveBeenCalledTimes(2)
    // Both carry the same event_id, so OpenAI collapses them
    // server-side — the storage guard is not the only line of defense.
    expect(window.oaiq).toHaveBeenNthCalledWith(1, ...evt.args(evt.keyA))
    expect(window.oaiq).toHaveBeenNthCalledWith(2, ...evt.args(evt.keyA))
  })
})

describe.each(EVENTS)('$name — the SDK itself throwing', (evt) => {
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
      result = evt.call(evt.keyA)
    }).not.toThrow()
    expect(result).toBe(false)
    expect(sessionStorage.getItem(evt.guard(evt.keyA))).toBeNull()
  })
})

// The demo modal opens from report surfaces (token present) and from
// the landing page (nothing durable to key on), so which id becomes
// the dedup key is the one piece of logic this event has beyond the
// shared contract above.
describe('trackAppointmentScheduled — which id becomes the dedup key', () => {
  beforeEach(() => {
    sessionStorage.clear()
    window.oaiq = vi.fn()
  })
  afterEach(() => {
    delete window.oaiq
  })

  it('with reportToken set, requestId is ignored entirely', () => {
    expect(trackAppointmentScheduled({ reportToken: 'tok-r', requestId: 'req-1' })).toBe(true)
    expect(window.oaiq).toHaveBeenCalledWith(
      'measure',
      'appointment_scheduled',
      { type: 'customer_action' },
      { event_id: 'appointment_scheduled:tok-r' },
    )
    expect(sessionStorage.getItem('oaiq:appointment_scheduled:tok-r')).toBe('1')
    expect(sessionStorage.getItem('oaiq:appointment_scheduled:req-1')).toBeNull()

    // A different requestId on the same report is still the same
    // report's conversion — it must not slip past the guard.
    expect(trackAppointmentScheduled({ reportToken: 'tok-r', requestId: 'req-2' })).toBe(false)
    expect(window.oaiq).toHaveBeenCalledTimes(1)
  })

  it('with no reportToken, requestId is the key', () => {
    expect(trackAppointmentScheduled({ requestId: 'req-1' })).toBe(true)
    expect(window.oaiq).toHaveBeenCalledWith(
      'measure',
      'appointment_scheduled',
      { type: 'customer_action' },
      { event_id: 'appointment_scheduled:req-1' },
    )
    expect(sessionStorage.getItem('oaiq:appointment_scheduled:req-1')).toBe('1')
    expect(trackAppointmentScheduled({ requestId: 'req-1' })).toBe(false)
    // A genuinely separate landing submission gets its own id, so it
    // is its own conversion.
    expect(trackAppointmentScheduled({ requestId: 'req-2' })).toBe(true)
    expect(window.oaiq).toHaveBeenCalledTimes(2)
  })

  it('with neither id, nothing fires', () => {
    expect(trackAppointmentScheduled({})).toBe(false)
    expect(trackAppointmentScheduled()).toBe(false)
    expect(window.oaiq).not.toHaveBeenCalled()
  })
})

describe('trackReportContentsViewed — the contents item', () => {
  beforeEach(() => {
    sessionStorage.clear()
    window.oaiq = vi.fn()
  })
  afterEach(() => {
    delete window.oaiq
  })

  it('carries exactly id, name and content_type — no other field', () => {
    trackReportContentsViewed({ token: 'tok-a', brandName: 'Allbirds' })
    const [, , data] = window.oaiq.mock.calls[0]
    expect(Object.keys(data).sort()).toEqual(['contents', 'type'])
    expect(data.contents).toHaveLength(1)
    expect(Object.keys(data.contents[0]).sort()).toEqual(['content_type', 'id', 'name'])
  })

  it('falls back to a neutral name when the brand is unknown', () => {
    trackReportContentsViewed({ token: 'tok-a' })
    const [, , data] = window.oaiq.mock.calls[0]
    expect(data.contents[0].name).toBe('audit report')
  })
})

describe('newRequestId', () => {
  it('returns a distinct non-empty string each call', () => {
    const a = newRequestId()
    const b = newRequestId()
    expect(typeof a).toBe('string')
    expect(a.length).toBeGreaterThan(0)
    expect(a).not.toBe(b)
  })

  it('falls back without crypto.randomUUID', () => {
    const spy = vi.spyOn(crypto, 'randomUUID').mockImplementation(() => {
      throw new Error('unavailable')
    })
    let id
    expect(() => {
      id = newRequestId()
    }).not.toThrow()
    expect(typeof id).toBe('string')
    expect(id.length).toBeGreaterThan(0)
    spy.mockRestore()
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
