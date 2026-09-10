/**
 * OpenAI (ChatGPT Ads) Measurement Pixel — the ONE module in this app
 * allowed to touch window.oaiq (grep-tested, see analytics.test.js's
 * "OpenAI pixel boundary" block). Exactly the same discipline as
 * analytics.js and posthog-js, and for the same reason: every rule
 * about when this conversion may fire lives in one file, so no
 * component can reach for window.oaiq() directly and bypass them.
 *
 * The SDK itself is NOT loaded here. It's an inline loader in the
 * served HTML of both audit documents, written in at build time by
 * vite.config.js's auditHeadPlugin from openaiPixel.constants.js —
 * the queue has to exist before the async SDK arrives, which a module
 * in the app bundle is far too late to guarantee. This file only
 * *uses* the global that loader defines, and degrades to a silent
 * no-op when it isn't there (ad blocker, SDK request failed, SSR/test
 * environment with no such global).
 *
 * What we measure, and what we deliberately don't:
 *   - ONE custom conversion, audit_score_rendered, meaning "an audit
 *     this browser itself commissioned finished and put a real
 *     numeric composite score on screen". Not a pageview, not a
 *     submit, not a completed run — a *rendered score*, which is the
 *     first moment the visitor has received the thing the ad promised.
 *   - No amount, currency, plan_id, or contents. This is a free
 *     diagnostic with no transaction attached; inventing a value
 *     would be inventing data.
 *   - No user object on init, and no PII in the event. The only
 *     identifier that travels is the run token, which is already the
 *     report's own public handle (anyone with the link has it) — the
 *     same reasoning that lets analyticsEvents.js allow report_token.
 */
import { OPENAI_PIXEL_ID } from './openaiPixel.constants.js'

/** Re-exported so the pixel's identity has one import path for app code. */
export { OPENAI_PIXEL_ID }

const AUDIT_SCORE_RENDERED = 'audit_score_rendered'

/**
 * sessionStorage, NOT localStorage, and that is a deliberate
 * attribution choice rather than an oversight. localStorage would
 * mean a token fires its conversion exactly once ever, on any device
 * that browser syncs; sessionStorage means one tab-session of one
 * report fires once, and a genuinely new session on the same report
 * can attribute again if the ad platform's click window still covers
 * it. Within a session it is airtight, which is the case that
 * actually matters: a reload, a back-navigation, or a React remount
 * of the same report never double-counts. The event_id below is the
 * belt to this file's braces — OpenAI dedupes server-side on the
 * first event per key, so even a cleared storage or a second device
 * collapses to one conversion.
 */
const GUARD_PREFIX = 'oaiq:audit_score_rendered:'

/**
 * True only when the inline loader actually ran and defined the
 * queue. Never throws — callers use it as a plain gate, and every
 * environment where it's false (tests, SSR, a blocked SDK) must stay
 * a silent no-op rather than a crash on a report page.
 */
export function isOpenAIPixelAvailable() {
  return typeof window !== 'undefined' && typeof window.oaiq === 'function'
}

/**
 * Appends the current URL's ?oppref= to a client-side navigation
 * path, when one is present.
 *
 * The SDK captures oppref on init and persists it in a first-party
 * __oppref cookie on the audit host, so attribution already survives
 * a client-side route change — this is NOT a second storage
 * mechanism, and deliberately isn't one. What it fixes is narrower:
 * our pushState navigations build bare paths (`/r/${token}`), so the
 * address bar silently loses the parameter the moment a run starts.
 * A user who then copies that URL, or reloads into a browser where
 * the cookie didn't stick, has lost the attribution for no reason.
 * Carrying it forward in the path costs nothing and closes that gap.
 *
 * Carries oppref and nothing else — not src (analytics.js
 * deliberately strips that so a copied link stays canonical), not any
 * other parameter. Absent or empty oppref returns the path untouched,
 * so the canonical bare URL remains the default everywhere else:
 * share links, the Copy-link button, the report-ready email, and
 * publicUrls.js's reportUrl() all build their own URLs and never come
 * through here.
 */
export function withOppref(path) {
  if (typeof window === 'undefined') return path

  let oppref = null
  try {
    oppref = new URL(window.location.href).searchParams.get('oppref')
  } catch (_) {
    // A URL jsdom/an exotic embed can't parse — attribution is not
    // worth breaking a navigation over.
    return path
  }

  if (!oppref) return path
  return `${path}${path.includes('?') ? '&' : '?'}oppref=${encodeURIComponent(oppref)}`
}

/**
 * Fires the audit_score_rendered conversion for `token`, at most once
 * per token per browser session. Returns true when the event was
 * actually sent, false otherwise (already sent this session, no
 * token, or no SDK) — the return value exists so tests can assert on
 * the decision rather than inferring it from a spy.
 *
 * Caller-side conditions (a numeric composite is on screen, and this
 * browser owns the run) live at the single call site in
 * LiteFullReportV4.jsx, next to the report data that answers them.
 * What lives here is everything that must hold no matter who calls:
 * the SDK gate, the once-per-session guard, and the exact payload.
 *
 * Every storage access is wrapped: a browser with storage blocked
 * still fires the conversion (an under-count is worse than a
 * possible double-count the event_id will collapse anyway) and never
 * throws into a render path.
 */
export function trackAuditScoreRendered(token) {
  if (!token) return false
  if (!isOpenAIPixelAvailable()) return false

  const guardKey = `${GUARD_PREFIX}${token}`
  try {
    if (sessionStorage.getItem(guardKey)) return false
  } catch (_) {
    // Storage unreadable — fall through and fire. See above.
  }

  try {
    window.oaiq(
      'measure',
      'custom',
      { type: 'custom' },
      { custom_event_name: AUDIT_SCORE_RENDERED, event_id: `${AUDIT_SCORE_RENDERED}:${token}` },
    )
  } catch (_) {
    // A broken/partially-loaded SDK must not take the report down.
    return false
  }

  try {
    sessionStorage.setItem(guardKey, '1')
  } catch (_) {}

  return true
}
