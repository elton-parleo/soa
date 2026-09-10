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
