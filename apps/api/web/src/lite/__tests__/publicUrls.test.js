/**
 * parleo.io/audit migration: the audit surface's same-origin prefix.
 *
 * Every assertion here is run against BOTH base values, because the
 * whole design rests on the prefixed build being the only thing that
 * changes: under the existing project's build (base '/') auditPath and
 * stripAuditBase must be exact identities, or the audit.parleo.io
 * surface would change behavior the moment this code shipped.
 *
 * import.meta.env is read at module-eval time, so each variant stubs
 * the env and re-imports rather than trying to mutate a live binding.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'

import { DEFAULT_PUBLIC_AUDIT_BASE_URL } from '../audit-host.constants.js'

async function loadPublicUrls(env = {}) {
  vi.resetModules()
  for (const [key, value] of Object.entries(env)) {
    vi.stubEnv(key, value)
  }
  return import('../publicUrls.js')
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('AUDIT_BASE_PATH — normalized from import.meta.env.BASE_URL', () => {
  it("is '/' under the default build", async () => {
    const { AUDIT_BASE_PATH } = await loadPublicUrls()
    expect(AUDIT_BASE_PATH).toBe('/')
  })

  it("is '/audit/' under a VITE_BASE_PATH=/audit/ build", async () => {
    const { AUDIT_BASE_PATH } = await loadPublicUrls({ BASE_URL: '/audit/' })
    expect(AUDIT_BASE_PATH).toBe('/audit/')
  })

  it('normalizes a base that arrives without its slashes', async () => {
    const { AUDIT_BASE_PATH } = await loadPublicUrls({ BASE_URL: 'audit' })
    expect(AUDIT_BASE_PATH).toBe('/audit/')
  })
})

describe('auditPath', () => {
  it('is the identity under the default build', async () => {
    const { auditPath } = await loadPublicUrls()
    expect(auditPath('/')).toBe('/')
    expect(auditPath('/r/abc')).toBe('/r/abc')
    expect(auditPath('/s/run-1')).toBe('/s/run-1')
  })

  it('prefixes the base without doubling the slash', async () => {
    const { auditPath } = await loadPublicUrls({ BASE_URL: '/audit/' })
    expect(auditPath('/')).toBe('/audit/')
    expect(auditPath('/r/abc')).toBe('/audit/r/abc')
    expect(auditPath('/s/run-1')).toBe('/audit/s/run-1')
    expect(auditPath('/r/abc')).not.toContain('//')
  })

  // withOppref (openaiPixel.js) appends its query string to whatever
  // auditPath produced, so the query has to survive the join intact
  // when a caller passes one through the other way round.
  it('leaves a query string on the path alone', async () => {
    const { auditPath } = await loadPublicUrls({ BASE_URL: '/audit/' })
    expect(auditPath('/r/abc?oppref=xyz')).toBe('/audit/r/abc?oppref=xyz')
  })
})

describe('stripAuditBase', () => {
  it('is the identity under the default build', async () => {
    const { stripAuditBase } = await loadPublicUrls()
    expect(stripAuditBase('/')).toBe('/')
    expect(stripAuditBase('/r/abc')).toBe('/r/abc')
    expect(stripAuditBase('/s/run-1')).toBe('/s/run-1')
    expect(stripAuditBase('/lite')).toBe('/lite')
  })

  it("reads '/audit' and '/audit/' both as the landing", async () => {
    const { stripAuditBase } = await loadPublicUrls({ BASE_URL: '/audit/' })
    expect(stripAuditBase('/audit')).toBe('/')
    expect(stripAuditBase('/audit/')).toBe('/')
  })

  it('strips the prefix off report and status paths', async () => {
    const { stripAuditBase } = await loadPublicUrls({ BASE_URL: '/audit/' })
    expect(stripAuditBase('/audit/r/abc')).toBe('/r/abc')
    expect(stripAuditBase('/audit/s/run-1')).toBe('/s/run-1')
  })

  it('round-trips with auditPath', async () => {
    const { auditPath, stripAuditBase } = await loadPublicUrls({ BASE_URL: '/audit/' })
    for (const p of ['/', '/r/abc', '/s/run-1']) {
      expect(stripAuditBase(auditPath(p))).toBe(p)
    }
  })

  // The prefix is a path segment, not a string prefix: '/auditorium'
  // must not be mangled into a route, it must fall through to the
  // not-found state like any other unknown path (H1).
  it('leaves a path that only looks like the base alone', async () => {
    const { stripAuditBase } = await loadPublicUrls({ BASE_URL: '/audit/' })
    expect(stripAuditBase('/auditorium')).toBe('/auditorium')
    expect(stripAuditBase('/lite')).toBe('/lite')
  })
})

describe('isAuditHost — build time first, hostname second', () => {
  it('is true under VITE_AUDIT_BUILD=1 whatever the hostname says', async () => {
    // jsdom serves these tests from localhost, and the audit origin
    // here is a different host entirely — so the only thing that can
    // make this true is the build flag.
    const { isAuditHost, IS_AUDIT_BUILD } = await loadPublicUrls({
      VITE_AUDIT_BUILD: '1',
      VITE_PUBLIC_AUDIT_BASE_URL: 'https://parleo.io/audit',
    })
    expect(IS_AUDIT_BUILD).toBe(true)
    expect(window.location.hostname).not.toBe('parleo.io')
    expect(isAuditHost()).toBe(true)
  })

  it('still answers by hostname when the flag is unset', async () => {
    const { isAuditHost, IS_AUDIT_BUILD, PUBLIC_AUDIT_HOSTNAME } = await loadPublicUrls({
      VITE_PUBLIC_AUDIT_BASE_URL: `http://${window.location.hostname}:8000`,
    })
    expect(IS_AUDIT_BUILD).toBe(false)
    expect(PUBLIC_AUDIT_HOSTNAME).toBe(window.location.hostname)
    expect(isAuditHost()).toBe(true)
  })

  it('is false off the audit host with the flag unset', async () => {
    const { isAuditHost } = await loadPublicUrls({
      VITE_PUBLIC_AUDIT_BASE_URL: 'https://audit.parleo.io',
    })
    expect(window.location.hostname).not.toBe('audit.parleo.io')
    expect(isAuditHost()).toBe(false)
  })
})

// Cutover: parleo.io/audit is the canonical address, and the literal
// that says so is the single most consequential line in this change —
// it is what the worker email, the Copy-link button, every canonical
// tag and the OG image all resolve through when no override is set.
//
// It needs its own test precisely because the repo's dev convention
// sets VITE_PUBLIC_AUDIT_BASE_URL (see web/.env.local), which
// overrides the default and would otherwise hide a regression here
// behind a green suite. Clearing the override to '' rather than
// reading the ambient env is what makes these assertions say the same
// thing on every machine.
describe('cutover — the canonical audit address', () => {
  const CANONICAL = 'https://parleo.io/audit'

  it('is the literal default, with no trailing slash', () => {
    expect(DEFAULT_PUBLIC_AUDIT_BASE_URL).toBe(CANONICAL)
  })

  it('is what PUBLIC_AUDIT_BASE_URL resolves to when nothing overrides it', async () => {
    const { PUBLIC_AUDIT_BASE_URL } = await loadPublicUrls({ VITE_PUBLIC_AUDIT_BASE_URL: '' })
    expect(PUBLIC_AUDIT_BASE_URL).toBe(CANONICAL)
  })

  it('puts report links under the /audit path, not at a bare origin', async () => {
    const { reportUrl } = await loadPublicUrls({ VITE_PUBLIC_AUDIT_BASE_URL: '' })
    expect(reportUrl('tok123')).toBe('https://parleo.io/audit/r/tok123')
    expect(reportUrl('a b&c')).toBe(`https://parleo.io/audit/r/${encodeURIComponent('a b&c')}`)
  })

  // A consequence, not a goal: the base URL now carries a path, so the
  // hostname derived from it is the marketing host. isAuditHost()'s
  // fallback is kept (a bundle without the build flag must never claim
  // to be the audit surface), but its job is now to answer false on
  // soa-app.parleo.io — audit.parleo.io never reaches it, because
  // vercel.json 308s that host before the bundle is served.
  // Anything that DISPLAYS the address is a consumer of the same
  // single source now. Three hardcoded copies of the old address are
  // what went stale at the cutover: the code that built URLs all moved
  // with one constant, and the strings that merely showed it did not.
  it('exposes the address as display text, scheme stripped', async () => {
    const { PUBLIC_AUDIT_DISPLAY } = await loadPublicUrls({ VITE_PUBLIC_AUDIT_BASE_URL: '' })
    expect(PUBLIC_AUDIT_DISPLAY).toBe('parleo.io/audit')
  })

  it('strips the scheme whatever the override is', async () => {
    const { PUBLIC_AUDIT_DISPLAY } = await loadPublicUrls({
      VITE_PUBLIC_AUDIT_BASE_URL: 'http://audit.localhost:8000',
    })
    expect(PUBLIC_AUDIT_DISPLAY).toBe('audit.localhost:8000')
  })

  it('leaves PUBLIC_AUDIT_HOSTNAME as the marketing host', async () => {
    const { PUBLIC_AUDIT_HOSTNAME } = await loadPublicUrls({ VITE_PUBLIC_AUDIT_BASE_URL: '' })
    expect(PUBLIC_AUDIT_HOSTNAME).toBe('parleo.io')
  })

  it('does not make the default build claim to be the audit surface', async () => {
    const { isAuditHost } = await loadPublicUrls({ VITE_PUBLIC_AUDIT_BASE_URL: '' })
    // jsdom serves these from localhost — i.e. neither parleo.io nor
    // soa-app.parleo.io, which is the point: without the build flag,
    // nothing but an exact hostname match may return true.
    expect(window.location.hostname).not.toBe('parleo.io')
    expect(isAuditHost()).toBe(false)
  })

  it('still yields root-relative navigation under the default build', async () => {
    // The canonical address has a path now; the SAME-ORIGIN prefix is a
    // separate question and is still driven by BASE_URL alone.
    const { auditPath, AUDIT_BASE_PATH } = await loadPublicUrls({ VITE_PUBLIC_AUDIT_BASE_URL: '' })
    expect(AUDIT_BASE_PATH).toBe('/')
    expect(auditPath('/r/abc')).toBe('/r/abc')
  })
})
