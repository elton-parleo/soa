/**
 * The OpenAI (ChatGPT Ads) Measurement Pixel's identity and debug flag.
 * Deliberately its own file with zero Vite-specific syntax (no
 * import.meta.env) — exactly the same reasoning as
 * audit-host.constants.js: vite.config.js's static-head plugin reads
 * these at BUILD time to write the loader into audit.html and
 * audit-report.html, and openaiPixel.js reads them from the CLIENT
 * bundle. One literal, two consumers, no chance of the two HTML
 * documents drifting apart or the runtime module measuring against a
 * different property than the one the loader initialized.
 *
 * The ID is a public, client-side measurement id (it ships in the
 * served HTML of every audit page by design) — not a secret, and not
 * an env var for that reason.
 */
export const OPENAI_PIXEL_ID = 'UGrzczfCw4YFL1c76AUUoH'

/**
 * SDK-side verbose logging. Stays true for the initial rollout so the
 * conversion can be verified in a real browser console; flip to false
 * once the event is confirmed live.
 */
export const OPENAI_PIXEL_DEBUG = false
