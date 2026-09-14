/**
 * The audit surface's build-time identity constants. Deliberately its
 * own file with zero Vite-specific syntax (no import.meta.env) —
 * publicUrls.js reads it for the CLIENT bundle (via import.meta.env),
 * and vite.config.js reads it for the BUILD process (via loadEnv()).
 * Both resolve the same override vars, VITE_PUBLIC_AUDIT_BASE_URL and
 * VITE_BASE_PATH, through their own appropriate mechanism; this file
 * is what keeps the fallback value — and the normalization rule —
 * from drifting between the two.
 */

/**
 * The single literal default for the audit tool's public address.
 *
 * Cutover: this is now parleo.io/audit, the canonical home. It is a
 * base URL WITH A PATH, not a bare origin — everything downstream
 * appends to it (`${base}/r/{token}`, `${base}/og/...`), which was
 * already true when it was a bare origin, so nothing had to change to
 * accommodate the path. What DID change as a consequence:
 * PUBLIC_AUDIT_HOSTNAME (publicUrls.js) is now 'parleo.io' rather than
 * 'audit.parleo.io' — see the note on isAuditHost().
 *
 * audit.parleo.io still exists, but it no longer serves this bundle:
 * vercel.json 308s every path on that host to the matching
 * parleo.io/audit path.
 */
export const DEFAULT_PUBLIC_AUDIT_BASE_URL = 'https://parleo.io/audit'

/**
 * Normalizes a base path to exactly one leading and one trailing
 * slash, so '/audit', 'audit/', and '//audit//' all mean the same
 * thing and an unset value means the root.
 *
 * vite.config.js runs this over VITE_BASE_PATH to produce Vite's
 * `base`; publicUrls.js runs it again over the import.meta.env
 * .BASE_URL that reaches the client, so both halves of the app agree
 * on the shape of the prefix every audit URL is built from.
 */
export function normalizeBasePath(value) {
  const trimmed = String(value || '').trim()
  if (!trimmed) return '/'
  return `/${trimmed.replace(/^\/+/, '').replace(/\/+$/, '')}/`.replace(/^\/\/+/, '/')
}
