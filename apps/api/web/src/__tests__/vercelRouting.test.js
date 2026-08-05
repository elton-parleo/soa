/**
 * audit.parleo.io migration (H1/H2). vercel.json can't be exercised by
 * an actual Vercel edge in this suite, so these tests assert its
 * structure directly: the host-conditional rules exist, are ordered so
 * real static assets (the audit host's own JS/CSS bundle) are served
 * before the audit-host catch-all 404, and /scan is hard-removed with
 * no dest/redirect.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const VERCEL_JSON = JSON.parse(
  fs.readFileSync(path.join(__dirname, '../../../vercel.json'), 'utf8'),
)

function findRoute(predicate) {
  return VERCEL_JSON.routes.find(predicate)
}

describe('vercel.json — audit.parleo.io host routing (H1)', () => {
  it('has host-conditional rules for the audit host, not a redirect', () => {
    const audit404 = findRoute((r) => r.status === 404 && r.has?.some((h) => h.type === 'host' && h.value === 'audit.parleo.io'))
    expect(audit404).toBeDefined()
    expect(audit404.dest).toBeUndefined() // a real 404, no fallback content
  })

  it('S1: serves the landing page from its own audit.html document, not index.html', () => {
    const landingRoute = findRoute((r) => r.has?.some((h) => h.type === 'host' && h.value === 'audit.parleo.io') && r.dest === '/audit.html')
    expect(landingRoute).toBeDefined()
    expect(new RegExp(landingRoute.src).test('/')).toBe(true)
    expect(new RegExp(landingRoute.src).test('/r/abc123')).toBe(false)
    expect(new RegExp(landingRoute.src).test('/bots')).toBe(false)
  })

  it('S3: serves /r/ and /s/ from their own audit-report.html document, not audit.html or index.html', () => {
    const reportRoute = findRoute((r) => r.has?.some((h) => h.type === 'host' && h.value === 'audit.parleo.io') && r.dest === '/audit-report.html')
    expect(reportRoute).toBeDefined()
    expect(new RegExp(reportRoute.src).test('/r/abc123')).toBe(true)
    expect(new RegExp(reportRoute.src).test('/s/abc123')).toBe(true)
    expect(new RegExp(reportRoute.src).test('/')).toBe(false)
    expect(new RegExp(reportRoute.src).test('/lite')).toBe(false)
  })

  it('serves audit-specific robots.txt and sitemap.xml, not the main-host files', () => {
    const robots = findRoute((r) => r.dest === '/audit-robots.txt')
    const sitemap = findRoute((r) => r.dest === '/audit-sitemap.xml')
    expect(robots?.has?.some((h) => h.value === 'audit.parleo.io')).toBe(true)
    expect(sitemap?.has?.some((h) => h.value === 'audit.parleo.io')).toBe(true)
  })

  it('places handle:filesystem before the audit-host 404 catch-all, so real static assets are served first', () => {
    const filesystemIdx = VERCEL_JSON.routes.findIndex((r) => r.handle === 'filesystem')
    const audit404Idx = VERCEL_JSON.routes.findIndex(
      (r) => r.status === 404 && r.has?.some((h) => h.value === 'audit.parleo.io'),
    )
    expect(filesystemIdx).toBeGreaterThanOrEqual(0)
    expect(filesystemIdx).toBeLessThan(audit404Idx)
  })
})

describe('vercel.json — /scan hard removal (H2)', () => {
  it('returns a bare 404 for /scan on any host — no dest, no redirect', () => {
    // Distinct from the audit-host catch-all (also status:404, but
    // scoped with `has: host`) — this one must apply host-agnostically.
    const scanRoute = findRoute((r) => r.status === 404 && !r.has && new RegExp(r.src || '').test('/scan'))
    expect(scanRoute).toBeDefined()
    expect(scanRoute.dest).toBeUndefined()
    expect(new RegExp(scanRoute.src).test('/scan/anything')).toBe(true)
  })

  it('grep-assert: no /scan route dest remains registered anywhere in vercel.json', () => {
    const serialized = JSON.stringify(VERCEL_JSON)
    expect(serialized).not.toMatch(/"dest"\s*:\s*"\/scan/)
  })
})
