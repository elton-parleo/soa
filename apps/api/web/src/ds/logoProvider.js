/**
 * Logo feature, Part 3b: owns third-party logo API URL construction — the
 * one thing BrandLogo needs to swap providers (e.g. Brandfetch) later
 * without touching the fallback chain itself. Default provider is
 * logo.dev, keyed by domain; the token is logo.dev's publishable key,
 * safe to ship in client code, read from VITE_LOGO_DEV_TOKEN.
 *
 * When the env var is absent the provider tier is skipped entirely (the
 * BrandLogo chain goes src → favicon → monogram) — the report must
 * render fine with no token configured, so this only warns once at
 * module load, never throws.
 */
const LOGO_DEV_TOKEN = import.meta.env.VITE_LOGO_DEV_TOKEN

if (!LOGO_DEV_TOKEN) {
  console.warn(
    '[logoProvider] VITE_LOGO_DEV_TOKEN not set — competitor logos fall back ' +
    'to the favicon service and monogram tiers only.'
  )
}

export const LOGO_PROVIDER_CONFIGURED = Boolean(LOGO_DEV_TOKEN)

/** null when there's no domain to key off of, or no token configured. */
export function logoProviderUrl(domain, size) {
  if (!domain || !LOGO_DEV_TOKEN) return null
  return `https://img.logo.dev/${domain}?token=${LOGO_DEV_TOKEN}&size=${size}`
}
