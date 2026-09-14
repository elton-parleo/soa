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
 * THREE STANDARD events, matching the conversions already defined on
 * this pixel in Ads Manager. Standard names carry meaning for
 * conversion reporting and campaign optimization in a way a custom
 * name cannot, which is why the earlier one-off custom event was
 * retired rather than kept alongside them:
 *
 *   lead_created          — the status page's email capture succeeded.
 *                           The first moment we have a person rather
 *                           than a store URL.
 *   appointment_scheduled — a demo request succeeded.
 *   contents_viewed       — the report rendered for its owner.
 *
 * contents_viewed deliberately includes PARTIAL reads. The earlier
 * "numeric composite only" gate is gone: a partial read is still a
 * viewed report, and withholding the conversion for it was measuring
 * our scoring confidence rather than the visitor's experience.
 *
 * Payload shapes come from OpenAI's supported-events reference and
 * are not ours to improvise:
 *   - lead_created / appointment_scheduled use the customer_action
 *     shape — exactly { type: 'customer_action' }, no amount, no
 *     currency. Neither is a transaction; inventing a value would be
 *     inventing data.
 *   - contents_viewed uses the contents shape, with only id, name and
 *     content_type per item. No amount, no currency.
 *   - custom_event_name is valid ONLY for custom events, so none of
 *     these three carry it.
 *   - Every call passes an options object holding event_id and
 *     nothing else, for server-side dedup.
 *
 * No user object on init, and no PII in any event. The only
 * identifiers that travel are the run token — already the report's
 * own public handle, anyone with the link has it, the same reasoning
 * that lets analyticsEvents.js allow report_token — and, for a
 * landing-page demo request that has no token, a random per-submission
 * id that identifies nothing but the submission itself. An email
 * address is never sent, including by lead_created, whose whole
 * subject is that one was captured.
 */
import { OPENAI_PIXEL_ID } from './openaiPixel.constants.js'

/** Re-exported so the pixel's identity has one import path for app code. */
export { OPENAI_PIXEL_ID }


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
 * sessionStorage, NOT localStorage, and that is a deliberate
 * attribution choice rather than an oversight. localStorage would
 * mean a key fires its conversion exactly once ever, on any device
 * that browser syncs; sessionStorage means one tab-session fires
 * once, and a genuinely new session can attribute again if the ad
 * platform's click window still covers it. Within a session it is
 * airtight, which is the case that actually matters: a reload, a
 * back-navigation, or a React remount never double-counts. The
 * event_id on every call is the belt to this file's braces — OpenAI
 * dedupes server-side on the first event per key, so even cleared
 * storage or a second device collapses to one conversion.
 *
 * Sends `sendFn()` at most once per `guardKey` per browser session.
 * Returns true when the event actually went out, false otherwise
 * (already sent this session, or no SDK) — the return value exists so
 * tests and callers can assert on the decision rather than infer it.
 *
 * Every storage access is wrapped, and a browser with storage blocked
 * still sends: an under-count is worse than a duplicate the event_id
 * will collapse anyway. Nothing here ever throws into a render path,
 * including a partially-loaded SDK whose own call throws.
 */
function sendOnce(guardKey, sendFn) {
  if (!guardKey) return false
  if (!isOpenAIPixelAvailable()) return false

  try {
    if (sessionStorage.getItem(guardKey)) return false
  } catch (_) {
    // Storage unreadable — fall through and send. See above.
  }

  try {
    sendFn()
  } catch (_) {
    // A broken/partially-loaded SDK must not take the page down, and
    // must not burn the guard either — a later retry should still be
    // able to send.
    return false
  }

  try {
    sessionStorage.setItem(guardKey, '1')
  } catch (_) {}

  return true
}

/**
 * lead_created — the status page's email capture succeeded for this
 * run. Fired from LiteProgress.jsx's success path only, never from
 * its catch.
 *
 * The email itself is never sent. What converts is that a person
 * exists behind this run, not who they are; the run token is the
 * identifier, exactly as it is everywhere else in this file.
 */
export function trackLeadCreated(token) {
  if (!token) return false
  return sendOnce(`oaiq:lead_created:${token}`, () => {
    window.oaiq(
      'measure',
      'lead_created',
      { type: 'customer_action' },
      { event_id: `lead_created:${token}` },
    )
  })
}

/**
 * appointment_scheduled — a demo request succeeded.
 *
 * The modal opens from two kinds of surface: report pages, which have
 * a run token, and the landing page, which has nothing durable to key
 * on. So the dedup key is reportToken when there is one, and
 * otherwise a requestId the CALLER generates once per submission (see
 * newRequestId) — generating it here would defeat the purpose, since
 * a fresh id per call would make the guard unable to recognise a
 * repeat.
 *
 * A landing-page requestId identifies nothing but that one
 * submission: it is random, is never stored beyond the guard key, and
 * is not joinable to anything.
 */
export function trackAppointmentScheduled({ reportToken, requestId } = {}) {
  const key = reportToken || requestId
  if (!key) return false
  return sendOnce(`oaiq:appointment_scheduled:${key}`, () => {
    window.oaiq(
      'measure',
      'appointment_scheduled',
      { type: 'customer_action' },
      { event_id: `appointment_scheduled:${key}` },
    )
  })
}

/**
 * contents_viewed — the report rendered for the browser that
 * commissioned it.
 *
 * Includes partial reads on purpose. A share-link visitor never fires
 * it; that gate lives at the call site in LiteFullReportV4.jsx, next
 * to the ownership signal that answers it.
 *
 * content_type is 'report'. OpenAI's reference does not enumerate the
 * allowed values, so if the SDK's debug output ever rejects it, 'page'
 * is the fallback to try.
 */
export function trackReportContentsViewed({ token, brandName } = {}) {
  if (!token) return false
  return sendOnce(`oaiq:contents_viewed:${token}`, () => {
    window.oaiq(
      'measure',
      'contents_viewed',
      {
        type: 'contents',
        contents: [{ id: token, name: brandName || 'audit report', content_type: 'report' }],
      },
      { event_id: `contents_viewed:${token}` },
    )
  })
}

/**
 * A random id for ONE demo-request submission, used as the dedup key
 * when there is no run token to key on (the landing page's modal).
 * Generated by the caller at the top of its submit handler so it
 * stays stable across that submission's retries within the handler.
 *
 * crypto.randomUUID is absent in some older Safari and in
 * non-secure-origin contexts, and the whole call is wrapped because a
 * missing crypto must not break a demo request — the fallback is not
 * cryptographically random, and does not need to be: this id is a
 * dedup key, never a secret or a credential.
 */
export function newRequestId() {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
  } catch (_) {}
  return `${Date.now()}-${Math.random()}`
}
