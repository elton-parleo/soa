/**
 * audit.parleo.io migration (H1/H2). vercel.json can't be exercised by
 * an actual Vercel edge in this suite, so these tests assert its
 * structure directly: the host-conditional rules exist, are ordered so
 * real static assets (the audit host's own JS/CSS bundle) are served
 * before the audit-host catch-all 404, and /scan is hard-removed with
 * no dest/redirect.
 *
 * parleo.io/audit migration: structural assertions stop being enough
 * for the prefixed rules, because what matters there is what a whole
 * ORDERED table does to a path — a rewrite that fires too early
 * silently disarms the 404 that was supposed to follow it. The last
 * block below runs the real route list against a real request path
 * instead, twice, under both readings of what Vercel does with a
 * rewritten path after handle:filesystem. Every guarantee asserted
 * there has to hold under BOTH, which is what makes it safe to ship
 * without a deploy to check against.
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
    // Both files are now reachable two ways — by host on
    // audit.parleo.io, and by prefix under /audit/ — so these look up
    // the host-conditioned rule specifically rather than "the route
    // whose dest is this file".
    const robots = findRoute((r) => r.dest === '/audit-robots.txt' && r.has)
    const sitemap = findRoute((r) => r.dest === '/audit-sitemap.xml' && r.has)
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

  // Part 2b: favicon.svg/apple-touch-icon.png/etc. are host-agnostic
  // real files (unlike robots.txt/sitemap.xml, which need a per-host
  // dest rewrite because the audit host serves *different* content
  // under those names) — no route ahead of handle:filesystem should
  // match them, so filesystem's plain passthrough is what serves them.
  it('no route before handle:filesystem intercepts the favicon paths', () => {
    const filesystemIdx = VERCEL_JSON.routes.findIndex((r) => r.handle === 'filesystem')
    const preFilesystemRoutes = VERCEL_JSON.routes.slice(0, filesystemIdx)
    const faviconPaths = ['/favicon.svg', '/favicon-32.png', '/favicon-16.png', '/apple-touch-icon.png', '/site.webmanifest']
    for (const route of preFilesystemRoutes) {
      if (!route.src) continue
      const re = new RegExp(route.src)
      for (const p of faviconPaths) {
        expect(re.test(p)).toBe(false)
      }
    }
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

// ─── Whole-table routing simulation (parleo.io/audit) ────────────────
//
// Deliberately small and dumb: walk the routes in order, honour `has`
// host conditions, apply `dest` rewrites, stop on a `status`. The one
// genuinely uncertain bit of Vercel semantics is whether the routes
// AFTER handle:filesystem see the rewritten path or the original
// request path, so `carryRewrite` models both and every expectation is
// asserted against each. If a future edit only holds under one
// reading, this fails rather than shipping a status code we guessed at.
const DIST_FILES = new Set([
  '/index.html', '/audit.html', '/audit-report.html',
  '/assets/main-abc123.js', '/assets/main-abc123.css',
  '/favicon.svg', '/favicon-16.png', '/favicon-32.png',
  '/apple-touch-icon.png', '/icon-192.png', '/icon-512.png',
  '/site.webmanifest', '/og/audit-landing.png',
  '/robots.txt', '/audit-robots.txt', '/audit-sitemap.xml',
])

function serve(reqPath, host, { carryRewrite }) {
  let current = reqPath
  let missPhase = false

  for (const route of VERCEL_JSON.routes) {
    if (route.handle === 'filesystem') {
      if (DIST_FILES.has(current)) return `file:${current}`
      missPhase = true
      continue
    }
    if (route.has && !route.has.every((h) => h.type === 'host' && h.value === host)) continue

    const subject = missPhase && !carryRewrite ? reqPath : current
    const m = new RegExp(route.src).exec(subject)
    if (!m) continue

    if (route.status) return String(route.status)
    if (route.dest) {
      if (route.dest === '/api/index.py') return 'function'
      current = route.dest.replace(/\$(\d)/g, (_, i) => m[Number(i)] ?? '')
      if (missPhase) return `file:${current}`
    }
  }
  return `file:${current}`
}

const SEMANTICS = [
  ['a rewrite carries into the miss phase', { carryRewrite: true }],
  ['the original path survives into the miss phase', { carryRewrite: false }],
]

describe.each(SEMANTICS)('routing simulation — %s', (_label, opts) => {
  const NEW_PROJECT = 'audit-project.vercel.app'

  it('serves the landing at /audit, with or without the trailing slash', () => {
    expect(serve('/audit/', NEW_PROJECT, opts)).toBe('file:/audit.html')
    expect(serve('/audit', NEW_PROJECT, opts)).toBe('file:/audit.html')
  })

  it('serves /audit/r/ and /audit/s/ from the report document', () => {
    expect(serve('/audit/r/abc123', NEW_PROJECT, opts)).toBe('file:/audit-report.html')
    expect(serve('/audit/s/run-1', NEW_PROJECT, opts)).toBe('file:/audit-report.html')
  })

  // The asset rewrite sits after the two HTML rules precisely so it can
  // never capture a report path; this is that ordering, exercised.
  it.each([
    ['/audit/assets/main-abc123.js', '/assets/main-abc123.js'],
    ['/audit/assets/main-abc123.css', '/assets/main-abc123.css'],
    ['/audit/og/audit-landing.png', '/og/audit-landing.png'],
    ['/audit/favicon.svg', '/favicon.svg'],
    ['/audit/favicon-16.png', '/favicon-16.png'],
    ['/audit/apple-touch-icon.png', '/apple-touch-icon.png'],
    ['/audit/icon-192.png', '/icon-192.png'],
    ['/audit/site.webmanifest', '/site.webmanifest'],
    ['/audit/robots.txt', '/audit-robots.txt'],
    ['/audit/sitemap.xml', '/audit-sitemap.xml'],
  ])('resolves %s to the real file %s', (requested, served) => {
    expect(serve(requested, NEW_PROJECT, opts)).toBe(`file:${served}`)
  })

  // H1 under the prefix. This is the assertion the extension-scoped
  // rewrite exists for: a broad ^/audit/(.*)$ rewrite would turn
  // /audit/nothing into /nothing before the 404 rule could see it, and
  // the SPA catch-all would answer 200 with the dashboard document.
  it.each([
    '/audit/nothing',
    '/audit/lite',
    '/audit/bots',
    '/audit/r',
    '/audit/deep/unknown/path',
  ])('404s %s — never the SPA catch-all', (p) => {
    expect(serve(p, NEW_PROJECT, opts)).toBe('404')
  })

  it('never lets an unknown audit path reach index.html', () => {
    for (const p of ['/audit/nothing', '/audit/x/y', '/audit/report']) {
      expect(serve(p, NEW_PROJECT, opts)).not.toBe('file:/index.html')
    }
  })

  it('keeps /api same-origin and ahead of everything', () => {
    expect(serve('/api/public/soa-lite', NEW_PROJECT, opts)).toBe('function')
    // The one /audit-shaped API path in the bundle.
    expect(serve('/api/full-analysis/audit/tok', 'soa-app.parleo.io', opts)).toBe('function')
  })

  it('leaves the audit.parleo.io host rules exactly as they were', () => {
    expect(serve('/', 'audit.parleo.io', opts)).toBe('file:/audit.html')
    expect(serve('/r/abc123', 'audit.parleo.io', opts)).toBe('file:/audit-report.html')
    expect(serve('/s/run-1', 'audit.parleo.io', opts)).toBe('file:/audit-report.html')
    expect(serve('/robots.txt', 'audit.parleo.io', opts)).toBe('file:/audit-robots.txt')
    expect(serve('/sitemap.xml', 'audit.parleo.io', opts)).toBe('file:/audit-sitemap.xml')
    expect(serve('/favicon.svg', 'audit.parleo.io', opts)).toBe('file:/favicon.svg')
    expect(serve('/lite', 'audit.parleo.io', opts)).toBe('404')
    expect(serve('/scan', 'audit.parleo.io', opts)).toBe('404')
  })

  it('leaves the marketing/authed host exactly as it was', () => {
    for (const p of ['/', '/lite', '/bots', '/report/tok', '/fa/tok']) {
      expect(serve(p, 'soa-app.parleo.io', opts)).toBe('file:/index.html')
    }
    expect(serve('/favicon.svg', 'soa-app.parleo.io', opts)).toBe('file:/favicon.svg')
    expect(serve('/scan', 'soa-app.parleo.io', opts)).toBe('404')
  })
})
