/**
 * analytics.js — the one module allowed to import posthog-js. Covers
 * the dark-ships-without-a-key contract, registry enforcement (unknown
 * event/prop dropped, dev-only console.error), captureSrcParam's
 * read-store-strip behavior, and the owner/visitor token helpers.
 * posthog.capture/register are spied on the real posthog-js module
 * (not mocked at import level) so these tests exercise the actual
 * init() gate, not a stand-in.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import posthog from 'posthog-js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

describe('analytics.js — dark-ships without VITE_POSTHOG_KEY', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.stubEnv('VITE_POSTHOG_KEY', '')
  })
  afterEach(() => vi.unstubAllEnvs())

  it('does not call posthog.init when the key is unset', async () => {
    const initSpy = vi.spyOn(posthog, 'init')
    await import('../analytics.js')
    expect(initSpy).not.toHaveBeenCalled()
  })

  it('track() is a silent no-op — no posthog.capture call, no throw', async () => {
    const captureSpy = vi.spyOn(posthog, 'capture')
    const { track } = await import('../analytics.js')
    expect(() => track('landing_viewed', { src: 'direct' })).not.toThrow()
    expect(captureSpy).not.toHaveBeenCalled()
  })

  it('identifyReport() is a silent no-op', async () => {
    const registerSpy = vi.spyOn(posthog, 'register')
    const { identifyReport } = await import('../analytics.js')
    expect(() => identifyReport('tok123')).not.toThrow()
    expect(registerSpy).not.toHaveBeenCalled()
  })
})

describe('analytics.js — track() enforces the registry', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.stubEnv('VITE_POSTHOG_KEY', 'test-key-123')
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  it('sends a known event with only its allowed props', async () => {
    const captureSpy = vi.spyOn(posthog, 'capture').mockImplementation(() => {})
    const { track } = await import('../analytics.js')
    track('share_copied', { placement: 'desktop_rail' })
    expect(captureSpy).toHaveBeenCalledWith('share_copied', { placement: 'desktop_rail' })
  })

  it('drops an unknown event entirely — no posthog.capture call', async () => {
    const captureSpy = vi.spyOn(posthog, 'capture').mockImplementation(() => {})
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { track } = await import('../analytics.js')
    track('totally_made_up_event', { foo: 'bar' })
    expect(captureSpy).not.toHaveBeenCalled()
    errorSpy.mockRestore()
  })

  it('drops an unlisted prop but still sends the event with the allowed props', async () => {
    const captureSpy = vi.spyOn(posthog, 'capture').mockImplementation(() => {})
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { track } = await import('../analytics.js')
    track('share_copied', { placement: 'desktop_rail', email: 'visitor@example.com' })
    expect(captureSpy).toHaveBeenCalledWith('share_copied', { placement: 'desktop_rail' })
    errorSpy.mockRestore()
  })

  it('never sends an email/name/company/message prop even if a caller passes one', async () => {
    const captureSpy = vi.spyOn(posthog, 'capture').mockImplementation(() => {})
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const { track } = await import('../analytics.js')
    track('demo_request_submitted', { source: 'truesync', email: 'x@y.com', name: 'Jane', company: 'Acme', message: 'hi' })
    const sentProps = captureSpy.mock.calls[0][1]
    expect(sentProps).toEqual({ source: 'truesync' })
  })

  it('drops undefined-valued props without sending them', async () => {
    const captureSpy = vi.spyOn(posthog, 'capture').mockImplementation(() => {})
    const { track } = await import('../analytics.js')
    track('demo_request_submitted', { source: 'landing_truesync', brand_name: undefined, report_token: undefined })
    expect(captureSpy).toHaveBeenCalledWith('demo_request_submitted', { source: 'landing_truesync' })
  })
})

describe('captureSrcParam()', () => {
  beforeEach(() => {
    vi.resetModules()
    sessionStorage.clear()
  })
  afterEach(() => {
    window.history.replaceState(null, '', '/')
  })

  it('reads ?src=, stores it, and strips it from the address bar', async () => {
    window.history.replaceState(null, '', '/r/tok123?src=email')
    const { captureSrcParam } = await import('../analytics.js')
    const src = captureSrcParam()
    expect(src).toBe('email')
    expect(window.location.search).toBe('')
    expect(window.location.pathname).toBe('/r/tok123')
    expect(sessionStorage.getItem('soaLiteSrc')).toBe('email')
  })

  it('preserves other query params while stripping only src', async () => {
    window.history.replaceState(null, '', '/r/tok123?src=email&foo=bar')
    const { captureSrcParam } = await import('../analytics.js')
    captureSrcParam()
    expect(window.location.search).toBe('?foo=bar')
  })

  it('falls back to the stored value on a later call with no ?src=', async () => {
    window.history.replaceState(null, '', '/r/tok123?src=email')
    const mod = await import('../analytics.js')
    mod.captureSrcParam()

    window.history.replaceState(null, '', '/r/tok123')
    expect(mod.captureSrcParam()).toBe('email')
  })

  // Pins the behavior the OpenAI pixel's oppref handling depends on:
  // captureSrcParam deletes ONLY src, so an ad-click parameter sitting
  // beside it on a report URL survives into the address bar untouched.
  // This is why openaiPixel.js needs no cooperation from this module —
  // if someone ever "tidied" this into a whitelist-and-rebuild, the
  // pixel would silently lose attribution and this test would fail
  // first.
  it('leaves ?oppref= in the address bar while stripping src', async () => {
    window.history.replaceState(null, '', '/r/tok123?oppref=abc&src=email')
    const { captureSrcParam } = await import('../analytics.js')
    expect(captureSrcParam()).toBe('email')
    expect(window.location.search).toBe('?oppref=abc')
    expect(window.location.pathname).toBe('/r/tok123')
  })

  it('returns "direct" when no src param was ever seen this session', async () => {
    window.history.replaceState(null, '', '/')
    const { captureSrcParam } = await import('../analytics.js')
    expect(captureSrcParam()).toBe('direct')
  })
})

describe('recordOwnedToken / isTokenOwned', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
  })

  it('a token is not owned until recorded', async () => {
    const { isTokenOwned } = await import('../analytics.js')
    expect(isTokenOwned('tok-a')).toBe(false)
  })

  it('recordOwnedToken makes a later isTokenOwned check true', async () => {
    const { recordOwnedToken, isTokenOwned } = await import('../analytics.js')
    recordOwnedToken('tok-a')
    expect(isTokenOwned('tok-a')).toBe(true)
    expect(isTokenOwned('tok-b')).toBe(false)
  })

  it('caps the owned-tokens list so it cannot grow unbounded', async () => {
    const { recordOwnedToken, isTokenOwned } = await import('../analytics.js')
    for (let i = 0; i < 25; i++) recordOwnedToken(`tok-${i}`)
    expect(isTokenOwned('tok-0')).toBe(false) // evicted
    expect(isTokenOwned('tok-24')).toBe(true) // most recent kept
  })

  it('never throws on corrupt localStorage content', async () => {
    localStorage.setItem('soaLiteOwnedTokens', 'not json')
    const { recordOwnedToken, isTokenOwned } = await import('../analytics.js')
    expect(() => recordOwnedToken('tok-a')).not.toThrow()
    expect(() => isTokenOwned('tok-a')).not.toThrow()
  })
})

describe('EVENT_REGISTRY — no PII prop is ever declared allowed', () => {
  it('no event\'s allowed-prop list contains email/name/company/message', async () => {
    const { EVENT_REGISTRY } = await import('../analyticsEvents.js')
    const banned = ['email', 'name', 'company', 'message']
    for (const [event, props] of Object.entries(EVENT_REGISTRY)) {
      for (const banned_prop of banned) {
        expect(props, `${event} must not allow "${banned_prop}"`).not.toContain(banned_prop)
      }
    }
  })
})

describe('posthog-js import boundary', () => {
  it('no file other than analytics.js imports posthog-js', () => {
    const srcRoot = path.join(__dirname, '../..')
    const offenders = []
    function walk(dir) {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.name === 'node_modules' || entry.name === 'dist') continue
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
          walk(full)
        } else if (/\.(js|jsx)$/.test(entry.name) && !/\.test\.(js|jsx)$/.test(entry.name) && !dir.includes('__tests__')) {
          const rel = path.relative(srcRoot, full)
          if (rel === 'lite/analytics.js') continue
          const src = fs.readFileSync(full, 'utf8')
          if (/from ['"]posthog-js['"]/.test(src) || /require\(['"]posthog-js['"]\)/.test(src)) {
            offenders.push(rel)
          }
        }
      }
    }
    walk(srcRoot)
    expect(offenders).toEqual([])
  })
})

// The same boundary as posthog-js above, for the ad-measurement SDK:
// openaiPixel.js is the one module in src/ allowed to reference oaiq,
// so every rule about when the conversion may fire (owner-only,
// numeric composite, once per session) lives in one reviewable place
// and no component can reach past it. The inline SDK loader is
// written by vite.config.js, which is outside src/ and therefore
// outside this walk by construction.
describe('OpenAI pixel (oaiq) boundary', () => {
  it('no file under src other than openaiPixel.js references oaiq', () => {
    const srcRoot = path.join(__dirname, '../..')
    const offenders = []
    function walk(dir) {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.name === 'node_modules' || entry.name === 'dist') continue
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
          walk(full)
        } else if (/\.(js|jsx)$/.test(entry.name) && !/\.test\.(js|jsx)$/.test(entry.name) && !dir.includes('__tests__')) {
          const rel = path.relative(srcRoot, full)
          if (rel === 'lite/openaiPixel.js') continue
          if (/oaiq/i.test(fs.readFileSync(full, 'utf8'))) offenders.push(rel)
        }
      }
    }
    walk(srcRoot)
    expect(offenders).toEqual([])
  })
})
