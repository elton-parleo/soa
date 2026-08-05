/**
 * The single literal default for the audit host's origin. Deliberately
 * its own file with zero Vite-specific syntax (no import.meta.env) —
 * publicUrls.js reads it for the CLIENT bundle (via import.meta.env),
 * and vite.config.js's static-head plugin reads it for the BUILD
 * process (via loadEnv()). Both resolve the same override var,
 * VITE_PUBLIC_AUDIT_BASE_URL, through their own appropriate mechanism;
 * this file is what keeps the fallback value itself from drifting
 * between the two.
 */
export const DEFAULT_PUBLIC_AUDIT_BASE_URL = 'https://audit.parleo.io'
