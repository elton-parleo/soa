/**
 * Analytics session: the complete, closed set of events this product
 * emits, and the exact props each one carries. track() (analytics.js)
 * validates every call against this registry and drops anything not
 * listed here — an unknown event or an unlisted prop never reaches
 * PostHog. This is the single place that answers "what do we track,
 * and why" — every event maps to one of four questions (see
 * docs/analytics.md):
 *   Q1 funnel:      landing_viewed -> audit_submitted -> email_captured
 *                    -> report_viewed(owner) -> demo_request_submitted
 *   Q2 engagement:   section_viewed / section_expanded, correlated with
 *                    demo_request_submitted
 *   Q3 share loop:   share_copied -> report_viewed(visitor) ->
 *                    audit_submitted
 *   Q4 read quality: report_viewed.state (scored/partial/blocked) vs
 *                    demo_request_submitted
 *   Q5 FA share loop: the same report_viewed event, reused for Full
 *                    Analysis's shareable reports (components/
 *                    FullAnalysisReport.jsx) — report_type distinguishes
 *                    the two products in one funnel rather than forking
 *                    a second event; viewer is owner|visitor exactly as
 *                    above, just determined by real auth state instead
 *                    of lite's localStorage-ownership heuristic (Full
 *                    Analysis has an authenticated view to check
 *                    against, lite never does).
 *
 * Deliberately closed: no prop here ever carries an email, name,
 * company, message, or any other form value — every event about a
 * form action (email capture, demo request) carries only the fact
 * that it happened, never what was typed. The run token
 * (report_token) is the one allowed pseudonymous id, since it's
 * already the report's own public handle (anyone with the link has
 * it); brand_name is allowed since it's already on the page.
 */

export const EVENTS = {
  // Landing
  LANDING_VIEWED: 'landing_viewed',
  AUDIT_SUBMITTED: 'audit_submitted',
  SAMPLE_REPORT_CLICKED: 'sample_report_clicked',
  ESTIMATOR_INTERACTED: 'estimator_interacted',
  // Status
  STATUS_VIEWED: 'status_viewed',
  EMAIL_CAPTURED: 'email_captured',
  // Report
  REPORT_VIEWED: 'report_viewed',
  SECTION_VIEWED: 'section_viewed',
  SECTION_EXPANDED: 'section_expanded',
  SHARE_COPIED: 'share_copied',
  CTA_CLICKED: 'cta_clicked',
  ADJUST_ASSUMPTIONS_USED: 'adjust_assumptions_used',
  // "From the transcript" widget's inner "Show the full answer" toggle —
  // deliberately a separate event from section_expanded (which the
  // outer transcript section already gets for free via ReportSection/
  // SectionCollapseButton): this one measures whether readers go past
  // the preview into the full verbatim answer, not a generic section
  // open.
  TRANSCRIPT_ANSWER_EXPANDED: 'transcript_answer_expanded',
  // Full Analysis's transcript browsing (2c/2d) — moving off the
  // curated pick, via prev/next or the query picker. Lite never fires
  // this (single curated pick only, no browsing UI mounted there yet —
  // see TranscriptPicker.jsx's own docstring).
  TRANSCRIPT_NAVIGATED: 'transcript_navigated',
  // Shared (landing + report — the modal fires the same event either way)
  DEMO_REQUEST_SUBMITTED: 'demo_request_submitted',
}

// ─── Emitted, but NOT to PostHog ──────────────────────────────────────
//
// audit_score_rendered
//   Destination: the OpenAI (ChatGPT Ads) Measurement Pixel, via
//   lite/openaiPixel.js — never posthog.capture(), and therefore
//   deliberately absent from EVENTS and EVENT_REGISTRY above (track()
//   would drop it, which is the correct behavior: it is not ours to
//   send to PostHog).
//
//   It is recorded here anyway so that THIS FILE remains the one
//   complete answer to "what does this app emit, and where does it
//   go" — an ad conversion that existed only inside a component's
//   useEffect would be exactly the kind of untracked emission this
//   registry exists to prevent.
//
//   Fires: once per token per browser session, from the report_viewed
//   effect in report/LiteFullReportV4.jsx, when a numeric
//   report.composite has rendered AND isTokenOwned(token) — i.e. the
//   browser that commissioned the run is looking at its own finished
//   score. A withheld composite never fires it; a share-link visitor
//   never fires it.
//
//   Payload: custom_event_name + an event_id of
//   `audit_score_rendered:{token}` for server-side dedupe. No amount,
//   currency, plan_id or contents — this is a free diagnostic with no
//   transaction attached. The run token is the only identifier, on
//   the same grounds report_token is allowed above: it is already the
//   report's own public handle.
//
//   See docs/analytics.md ("The OpenAI ad-conversion pixel").

// event name -> array of allowed prop keys. A key not listed here is
// dropped by track(); an event name not listed here is dropped whole.
export const EVENT_REGISTRY = {
  [EVENTS.LANDING_VIEWED]: ['src'],
  [EVENTS.AUDIT_SUBMITTED]: [],
  [EVENTS.SAMPLE_REPORT_CLICKED]: ['placement'],
  [EVENTS.ESTIMATOR_INTERACTED]: [],
  [EVENTS.STATUS_VIEWED]: [],
  [EVENTS.EMAIL_CAPTURED]: [],
  [EVENTS.REPORT_VIEWED]: ['state', 'viewer', 'src', 'report_type'],
  [EVENTS.SECTION_VIEWED]: ['section'],
  [EVENTS.SECTION_EXPANDED]: ['section', 'control'],
  [EVENTS.SHARE_COPIED]: ['placement'],
  [EVENTS.CTA_CLICKED]: ['cta', 'placement'],
  [EVENTS.ADJUST_ASSUMPTIONS_USED]: [],
  [EVENTS.TRANSCRIPT_ANSWER_EXPANDED]: [],
  // direction ('prev'|'next') and picker (true) are mutually exclusive
  // — exactly one is present per call, describing HOW the navigation
  // happened; position/platform/narrative_case describe WHERE it
  // landed. No query/response text ever, per this file's own rule.
  [EVENTS.TRANSCRIPT_NAVIGATED]: ['direction', 'picker', 'position', 'platform', 'narrative_case'],
  // Union of the landing call (source only) and the report call
  // (source + brand_name + report_token) — the report-only props are
  // simply absent on a landing-fired call.
  [EVENTS.DEMO_REQUEST_SUBMITTED]: ['source', 'brand_name', 'report_token'],
}
