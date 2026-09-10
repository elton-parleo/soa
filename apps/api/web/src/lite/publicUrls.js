/**
 * Stage: audit.parleo.io migration (U1-U3). Single source for the
 * public audit tool's origin — every absolute URL the product emits
 * (report-link email, Copy-link button, OG/share URLs, SAMPLE_REPORT_URL)
 * must be built from this constant rather than window.location.origin
 * or a hardcoded string, so they stay correct regardless of which host
 * happens to be serving the page that builds them (e.g. the /lite embed
 * still runs on the marketing host, but the links it produces must
 * always point at the audit host).
 *
 * parleo.io/audit migration: the same file is also the single source
 * for the audit surface's same-origin PREFIX. The tool is moving to a
 * subpath of the marketing site, served by a second Vercel project
 * built from this repo with VITE_BASE_PATH=/audit/ behind a proxy, so
 * a client-side navigation to the landing or a report is no longer
 * necessarily rooted at '/'. auditPath() builds those paths and
 * stripAuditBase() reads them back; both are identities under the
 * default build, which is why the existing project's behavior is
 * untouched.
 */
import { DEFAULT_PUBLIC_AUDIT_BASE_URL, normalizeBasePath } from './audit-host.constants.js'

export const PUBLIC_AUDIT_BASE_URL = (
  import.meta.env.VITE_PUBLIC_AUDIT_BASE_URL || DEFAULT_PUBLIC_AUDIT_BASE_URL
).replace(/\/$/, '')

export const PUBLIC_AUDIT_HOSTNAME = new URL(PUBLIC_AUDIT_BASE_URL).hostname

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
// project's own *.vercel.app URL, and preview URLs all behave the same
// — and by hostname second, because the existing project keeps serving
// audit.parleo.io by host until that host is retired. Used by
// components that render on both the audit surface and the marketing
// host's /lite embed to pick the right same-origin path prefix for
// client-side navigation (see auditPath above).
export function isAuditHost() {
  if (IS_AUDIT_BUILD) return true
  return typeof window !== 'undefined' && window.location.hostname === PUBLIC_AUDIT_HOSTNAME
}

// Every chrome placement of the Wordmark (nav/rail/footer — see
// WordmarkLink.jsx) links here, never a literal per call site.
export const PARLEO_HOME_URL = 'https://parleo.io'
