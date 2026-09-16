/**
 * devWarn.js — Part 2c. IS_DEV is read once at module-eval time (same
 * pattern as lite/analytics.js's own IS_DEV), so testing both the dev
 * and "production" branches needs vi.resetModules() + a fresh dynamic
 * import per test, matching analytics.test.js's established pattern —
 * a plain re-render can't observe a change to an already-cached
 * module-level constant.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

beforeEach(() => {
  vi.resetModules()
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
})

describe('logAntiSpamGateTripped', () => {
  it('logs the exact expected line, naming the reason, in dev', async () => {
    vi.stubEnv('DEV', true)
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { logAntiSpamGateTripped } = await import('../devWarn.js')

    logAntiSpamGateTripped('honeypot')

    expect(warnSpy).toHaveBeenCalledWith('demo form: anti-spam gate tripped — no request sent; reason: honeypot')
  })

  it('names too_fast too', async () => {
    vi.stubEnv('DEV', true)
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { logAntiSpamGateTripped } = await import('../devWarn.js')

    logAntiSpamGateTripped('too_fast')

    expect(warnSpy).toHaveBeenCalledWith('demo form: anti-spam gate tripped — no request sent; reason: too_fast')
  })

  it('stays silent in production — the indistinguishability from a real success is deliberate', async () => {
    vi.stubEnv('DEV', false)
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { logAntiSpamGateTripped } = await import('../devWarn.js')

    logAntiSpamGateTripped('honeypot')

    expect(warnSpy).not.toHaveBeenCalled()
  })
})
