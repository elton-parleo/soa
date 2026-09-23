/**
 * Single source for the Full Analysis public share link's own origin —
 * mirrors lite/publicUrls.js's PUBLIC_AUDIT_BASE_URL pattern. Unlike
 * lite (embedded on multiple hosts: the marketing site's /lite iframe
 * AND the dedicated audit.parleo.io host), the authed SoA app and its
 * /fa/{token} public route are served from the exact same single
 * origin — but the copied URL still isn't built from window.location:
 * env-driven keeps a local/preview deployment's own origin from ever
 * silently ending up in a link someone forwards.
 */
const DEFAULT_PUBLIC_APP_BASE_URL = 'https://soa-app.parleo.io'

export const PUBLIC_APP_BASE_URL = (
  import.meta.env.VITE_PUBLIC_APP_BASE_URL || DEFAULT_PUBLIC_APP_BASE_URL
).replace(/\/$/, '')

export function fullAnalysisReportUrl(token) {
  return `${PUBLIC_APP_BASE_URL}/fa/${encodeURIComponent(token)}`
}
