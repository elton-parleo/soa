/**
 * Single source of truth for the audit host's <head> metadata copy —
 * imported by BOTH the client-side effect (LandingPage.jsx's
 * useLandingMeta, LiteWidget.jsx's report/status head) and the
 * build-time static-head Vite plugin (vite.config.js), so the
 * prerendered HTML and the client's runtime <head> mutations can never
 * disagree (S1/S2). Deliberately plain JS — no import.meta.env, no
 * React — so vite.config.js (a Node/ESM context, not a Vite-transformed
 * app module) can import it directly.
 */
export const LANDING_META_TITLE = 'Parleo Audit — how AI shopping agents see your store'
export const LANDING_META_DESCRIPTION =
  'A free audit of what agentic shoppers actually see when they read your store: pricing, membership terms, and structured data.'

// The neutral title for /r/{token} and /s/{id} documents (S3) — never
// the landing title, and never brand-specific: a shared report link
// must not unfurl like marketing content for the audit tool itself.
export const REPORT_META_TITLE = 'Parleo Audit'

// S4: no share image asset exists in this repo yet. A single named
// constant so adding one later is a one-line change — every consumer
// must treat null as "omit the tag entirely," never fabricate a path
// that would just 404 on every unfurl.
export const OG_IMAGE_URL = null
