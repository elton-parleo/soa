/**
 * Stage: audit.parleo.io migration (U1-U3). Single source for the
 * public audit tool's origin — every absolute URL the product emits
 * (report-link email, Copy-link button, OG/share URLs, SAMPLE_REPORT_URL)
 * must be built from this constant rather than window.location.origin
 * or a hardcoded string, so they stay correct regardless of which host
 * happens to be serving the page that builds them (e.g. the /lite embed
 * still runs on the marketing host, but the links it produces must
 * always point at the audit host).
 */
import { DEFAULT_PUBLIC_AUDIT_BASE_URL } from './audit-host.constants.js'

export const PUBLIC_AUDIT_BASE_URL = (
  import.meta.env.VITE_PUBLIC_AUDIT_BASE_URL || DEFAULT_PUBLIC_AUDIT_BASE_URL
).replace(/\/$/, '')

export const PUBLIC_AUDIT_HOSTNAME = new URL(PUBLIC_AUDIT_BASE_URL).hostname

export function reportUrl(token) {
  return `${PUBLIC_AUDIT_BASE_URL}/r/${encodeURIComponent(token)}`
}

// True when the page is currently being served from the audit host
// itself — used by components that render on both the audit host
// (/r/, /s/, /) and the marketing host's /lite embed to pick the right
// same-origin path prefix for client-side navigation.
export function isAuditHost() {
  return typeof window !== 'undefined' && window.location.hostname === PUBLIC_AUDIT_HOSTNAME
}
