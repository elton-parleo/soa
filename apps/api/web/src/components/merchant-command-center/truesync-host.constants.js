/**
 * The single literal default for the TrueSync API's origin. Same shape
 * and same reason as lite/audit-host.constants.js: a plain module with
 * no Vite-specific syntax, so the value itself can't drift between the
 * client bundle (truesyncApi.js, via import.meta.env) and anything
 * build-side that later needs it.
 *
 * Override with VITE_TRUESYNC_API_BASE. This is a READ base only — the
 * page's mutations are same-origin against this app's own proxy
 * (apps/api/app/routers/truesync.py), which holds the admin key.
 */
export const DEFAULT_TRUESYNC_API_BASE = 'https://api.parleo.io'
