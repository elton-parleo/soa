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

describe('vercel.json — audit.parleo.io is now redirects only', () => {
  const AUDIT_HOST_ROUTE = findRoute((r) => r.has?.some((h) => h.type === 'host' && h.value === 'audit.parleo.io'))

  it('has exactly one rule for the retired host, and it is a 308', () => {
    const hostRoutes = VERCEL_JSON.routes.filter((r) => r.has?.some((h) => h.value === 'audit.parleo.io'))
    expect(hostRoutes).toHaveLength(1)
    expect(hostRoutes[0].status).toBe(308)
    expect(hostRoutes[0].headers.Location).toBe('https://parleo.io/audit/$1')
    // A redirect, never content: the retired host must not serve a
    // document of its own any more, or two addresses would render the
    // same page and split their ranking.
    expect(hostRoutes[0].dest).toBeUndefined()
  })

  it('matches every path on that host — no carve-outs', () => {
    const re = new RegExp(AUDIT_HOST_ROUTE.src)
    for (const p of ['/', '/r/abc', '/s/run-1', '/robots.txt', '/sitemap.xml', '/favicon.svg', '/lite', '/anything']) {
      expect(re.test(p)).toBe(true)
    }
  })

  // The /api route is deliberately ahead of the redirect, so a client
  // still calling the API on the old host keeps working rather than
  // being bounced to a marketing URL that cannot answer it.
  it('sits after the /api function route so the API still answers there', () => {
    const apiIdx = VERCEL_JSON.routes.findIndex((r) => r.dest === '/api/index.py')
    const redirectIdx = VERCEL_JSON.routes.indexOf(AUDIT_HOST_ROUTE)
    expect(apiIdx).toBeGreaterThanOrEqual(0)
    expect(apiIdx).toBeLessThan(redirectIdx)
  })

  it('sits before handle:filesystem, so the host never serves a real file', () => {
    const filesystemIdx = VERCEL_JSON.routes.findIndex((r) => r.handle === 'filesystem')
    expect(VERCEL_JSON.routes.indexOf(AUDIT_HOST_ROUTE)).toBeLessThan(filesystemIdx)
  })

  it('leaves no audit.parleo.io rule that serves content or 404s', () => {
    for (const route of VERCEL_JSON.routes) {
      if (!route.has?.some((h) => h.value === 'audit.parleo.io')) continue
      expect(route.status).toBe(308)
    }
  })
})

describe('vercel.json — the /audit prefix serves the surface (unchanged)', () => {
  it('S1: serves the landing from its own audit.html document, not index.html', () => {
    const landingRoute = findRoute((r) => r.dest === '/audit.html')
    expect(landingRoute).toBeDefined()
    expect(new RegExp(landingRoute.src).test('/audit/')).toBe(true)
    expect(new RegExp(landingRoute.src).test('/audit')).toBe(true)
    expect(new RegExp(landingRoute.src).test('/audit/r/abc123')).toBe(false)
    expect(new RegExp(landingRoute.src).test('/audit/bots')).toBe(false)
  })

  it('S3: serves /audit/r/ and /audit/s/ from their own audit-report.html document', () => {
    const reportRoute = findRoute((r) => r.dest === '/audit-report.html')
    expect(reportRoute).toBeDefined()
    expect(new RegExp(reportRoute.src).test('/audit/r/abc123')).toBe(true)
    expect(new RegExp(reportRoute.src).test('/audit/s/abc123')).toBe(true)
    expect(new RegExp(reportRoute.src).test('/audit/')).toBe(false)
    expect(new RegExp(reportRoute.src).test('/audit/lite')).toBe(false)
  })

  it('serves audit-specific robots.txt and sitemap.xml under the prefix', () => {
    const robots = findRoute((r) => r.dest === '/audit-robots.txt')
    const sitemap = findRoute((r) => r.dest === '/audit-sitemap.xml')
    expect(new RegExp(robots.src).test('/audit/robots.txt')).toBe(true)
    expect(new RegExp(sitemap.src).test('/audit/sitemap.xml')).toBe(true)
  })

  it('places handle:filesystem before the trailing audit 404, so real assets are served first', () => {
    const filesystemIdx = VERCEL_JSON.routes.findIndex((r) => r.handle === 'filesystem')
    const trailing404Idx = VERCEL_JSON.routes.findIndex(
      (r, i) => i > filesystemIdx && r.status === 404 && new RegExp(r.src).test('/audit/x'),
    )
    expect(filesystemIdx).toBeGreaterThanOrEqual(0)
    expect(trailing404Idx).toBeGreaterThan(filesystemIdx)
  })

  // Part 2b: favicon.svg/apple-touch-icon.png/etc. are host-agnostic
  // real files — no route ahead of handle:filesystem should intercept
  // them on the hosts that serve content, so filesystem's plain
  // passthrough is what serves them. The audit.parleo.io 308 is
  // excluded by inspection, not by accident: it matches every path,
  // which is the point, and it only applies to the retired host.
  it('no content-host route before handle:filesystem intercepts the favicon paths', () => {
    const filesystemIdx = VERCEL_JSON.routes.findIndex((r) => r.handle === 'filesystem')
    const preFilesystemRoutes = VERCEL_JSON.routes.slice(0, filesystemIdx)
    const faviconPaths = ['/favicon.svg', '/favicon-32.png', '/favicon-16.png', '/apple-touch-icon.png', '/site.webmanifest']
    for (const route of preFilesystemRoutes) {
      if (!route.src) continue
      if (route.has?.some((h) => h.value === 'audit.parleo.io')) continue
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

    if (route.status) {
      const location = route.headers?.Location
      if (location) {
        return `${route.status} ${location.replace(/\$(\d)/g, (_, i) => m[Number(i)] ?? '')}`
      }
      return String(route.status)
    }
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

  // Cutover: the retired host used to serve the audit tool itself.
  // Every one of those paths is now a 308 to the matching
  // parleo.io/audit address, and nothing on that host serves content
  // or 404s any more — an unknown path redirects too and meets the
  // real 404 that parleo.io/audit already returns.
  it.each([
    ['/', 'https://parleo.io/audit/'],
    ['/r/abc123', 'https://parleo.io/audit/r/abc123'],
    ['/s/run-1', 'https://parleo.io/audit/s/run-1'],
    ['/robots.txt', 'https://parleo.io/audit/robots.txt'],
    ['/sitemap.xml', 'https://parleo.io/audit/sitemap.xml'],
    ['/favicon.svg', 'https://parleo.io/audit/favicon.svg'],
    ['/lite', 'https://parleo.io/audit/lite'],
    ['/scan', 'https://parleo.io/audit/scan'],
    ['/anything/at/all', 'https://parleo.io/audit/anything/at/all'],
  ])('308s audit.parleo.io%s to %s', (p, location) => {
    expect(serve(p, 'audit.parleo.io', opts)).toBe(`308 ${location}`)
  })

  it('never serves content or a 404 on the retired host', () => {
    for (const p of ['/', '/r/abc', '/lite', '/scan', '/favicon.svg', '/nothing']) {
      const result = serve(p, 'audit.parleo.io', opts)
      expect(result.startsWith('308 https://parleo.io/audit/')).toBe(true)
    }
  })

  // Deliberately ahead of the redirect: a client still calling the API
  // on the old host keeps getting a real answer instead of being
  // bounced to a marketing URL that cannot serve it.
  it('keeps the API answering on the retired host', () => {
    expect(serve('/api/public/soa-lite', 'audit.parleo.io', opts)).toBe('function')
    expect(serve('/api/public/soa-lite/abc/status', 'audit.parleo.io', opts)).toBe('function')
  })

  // The redirect carries a host condition, so it must be invisible
  // everywhere else. This is the assertion that would catch it losing
  // that condition and swallowing the whole site.
  it('does not touch any other host', () => {
    for (const p of ['/', '/lite', '/report/tok', '/favicon.svg']) {
      expect(serve(p, 'soa-app.parleo.io', opts)).not.toMatch(/^308/)
      expect(serve(p, NEW_PROJECT, opts)).not.toMatch(/^308/)
    }
  })

  it('leaves the marketing/authed host exactly as it was', () => {
    for (const p of ['/', '/lite', '/bots', '/report/tok', '/fa/tok']) {
      expect(serve(p, 'soa-app.parleo.io', opts)).toBe('file:/index.html')
    }
    expect(serve('/favicon.svg', 'soa-app.parleo.io', opts)).toBe('file:/favicon.svg')
    expect(serve('/scan', 'soa-app.parleo.io', opts)).toBe('404')
  })
})
