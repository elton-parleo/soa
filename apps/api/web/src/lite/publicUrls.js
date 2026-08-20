/**
 * Single source for the public audit tool's canonical address — every
 * absolute URL the product emits (report-link email, Copy-link button,
 * OG/share URLs, SAMPLE_REPORT_URL) must be built from this constant
 * rather than window.location.origin or a hardcoded string, so they
 * stay correct regardless of which host happens to be serving the page
 * that builds them (e.g. the /lite embed still runs on
 * soa-app.parleo.io, but the links it produces must always point at
 * the canonical audit address).
 *
 * Cutover: that address is now https://parleo.io/audit — a base URL
 * with a path, not a bare origin. audit.parleo.io 308s to it and
 * serves nothing itself.
 *
 * This file is also the single source for the audit surface's
 * same-origin PREFIX, which is a different question from the canonical
 * address: the surface is served under /audit/ by the soa-audit
 * project (VITE_BASE_PATH=/audit/) and at the root by any build
 * without it. auditPath() builds those same-origin paths and
 * stripAuditBase() reads them back; both are identities when the base
 * is '/'.
 */
import { DEFAULT_PUBLIC_AUDIT_BASE_URL, normalizeBasePath } from './audit-host.constants.js'

export const PUBLIC_AUDIT_BASE_URL = (
  import.meta.env.VITE_PUBLIC_AUDIT_BASE_URL || DEFAULT_PUBLIC_AUDIT_BASE_URL
).replace(/\/$/, '')

export const PUBLIC_AUDIT_HOSTNAME = new URL(PUBLIC_AUDIT_BASE_URL).hostname

// The canonical address as DISPLAY text — scheme stripped, no trailing
// slash: 'parleo.io/audit'. The landing's mock browser chrome
// (Hero.jsx, SampleReportSection.jsx) and the footer label print this
// instead of a literal.
//
// It exists because three hardcoded copies of the old address are
// exactly what went stale at the cutover: the code that BUILT urls all
// moved with one constant, and the strings that merely SHOWED the
// address did not. Anything that displays the address is a consumer of
// the same single source now.
export const PUBLIC_AUDIT_DISPLAY = PUBLIC_AUDIT_BASE_URL.replace(/^https?:\/\//, '')

// The path prefix this bundle is served under, with exactly one
// leading and one trailing slash: '/' under the existing project's
// build, '/audit/' under a VITE_BASE_PATH=/audit/ build. Vite hands it
// to the client as import.meta.env.BASE_URL; normalizeBasePath is the
// same helper vite.config.js used to produce it, so the two can't
// disagree about shape.
export const AUDIT_BASE_PATH = normalizeBasePath(import.meta.env.BASE_URL)

// True when this bundle WAS BUILT as the audit surface, independent of
// what host is serving it. That's the whole point: the prefixed build
// is reached through parleo.io (proxied), through its own
// *.vercel.app URL, and through preview URLs, none of which share a
// hostname the bundle could recognize.
export const IS_AUDIT_BUILD = import.meta.env.VITE_AUDIT_BUILD === '1'

export function reportUrl(token) {
  return `${PUBLIC_AUDIT_BASE_URL}/r/${encodeURIComponent(token)}`
}

/**
 * Joins a root-relative audit path ('/', '/r/x', '/s/x') onto
 * AUDIT_BASE_PATH without doubling the slash between them. Every
 * same-origin navigation on the audit surface goes through this:
 * auditPath('/r/abc') is '/r/abc' under the default build and
 * '/audit/r/abc' under the prefixed one.
 */
export function auditPath(relPath) {
  const rel = String(relPath ?? '/')
  const suffix = rel.startsWith('/') ? rel : `/${rel}`
  // AUDIT_BASE_PATH always ends in '/', and suffix always starts with
  // one — drop the base's so '/audit/' + '/' is '/audit/', not
  // '/audit//'.
  return `${AUDIT_BASE_PATH.slice(0, -1)}${suffix}`
}

/**
 * The inverse: turns a real window.location.pathname back into the
 * root-relative path the route matching in App.jsx is written against.
 * Both '/audit' and '/audit/' read as '/', so the landing resolves
 * with or without the trailing slash.
 *
 * A path that isn't under the base at all is returned unchanged (so
 * '/auditorium' stays '/auditorium' and falls through to not-found
 * rather than being mangled into a route).
 */
export function stripAuditBase(pathname) {
  const path = typeof pathname === 'string' && pathname ? pathname : '/'
  if (AUDIT_BASE_PATH === '/') return path
  const bare = AUDIT_BASE_PATH.slice(0, -1) // '/audit'
  if (path === bare || path === AUDIT_BASE_PATH) return '/'
  if (path.startsWith(AUDIT_BASE_PATH)) return path.slice(bare.length)
  return path
}

// True when this page is the public audit surface. Decided at BUILD
// time first — a VITE_AUDIT_BUILD=1 bundle is the audit tool wherever
// it is served from, which is what makes parleo.io/audit, the
// project's own *.vercel.app URL, and preview URLs all behave the same.
//
// The hostname fallback is kept, but after the cutover its only job is
// to answer FALSE. PUBLIC_AUDIT_HOSTNAME is now 'parleo.io' (the
// canonical base URL's host), and the default build is served on
// soa-app.parleo.io — the authed dashboard, the /lite embed,
// /report/{token}, /fa/{token}, /bots — so the comparison is false
// there and those routes keep their own behavior. audit.parleo.io no
// longer reaches this branch at all: vercel.json 308s every path on
// that host before the bundle is ever served. The fallback stays
// because it is what makes that "false" explicit rather than
// accidental, and because a bundle built without the flag must never
// claim to be the audit surface just because it happens to load.
export function isAuditHost() {
  if (IS_AUDIT_BUILD) return true
  return typeof window !== 'undefined' && window.location.hostname === PUBLIC_AUDIT_HOSTNAME
}

// Every chrome placement of the Wordmark (nav/rail/footer — see
// WordmarkLink.jsx) links here, never a literal per call site.
export const PARLEO_HOME_URL = 'https://parleo.io'

// The demo-request modal's submission backend (demoRequestApi.js) —
// leads go straight to Formspree, no public demo-request API route
// or soa_demo_requests table in this app. Restrict allowed submission
// domains in the Formspree dashboard (ops step, not code).
export const FORMSPREE_DEMO_ENDPOINT = 'https://formspree.io/f/xyklyajq'
