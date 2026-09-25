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
 *
 * The run token now sits on the funnel's SPINE events directly —
 * audit_submitted, status_viewed, email_captured — not only on
 * report-page events. identifyReport() registers it as a
 * super-property from the moment a submit is accepted, so in practice
 * it arrives both ways; passing it explicitly as well is what makes a
 * cold-loaded status page, whose register() call and whose event fire
 * in the same mount, join reliably. One id name, report_token, the
 * same one soa_lite_requests.token carries — a second name for the
 * same value would fork every join in PostHog.
 *
 * audit_submitted also allows oppref and utm_source. Neither is a
 * person: oppref is an ad-click code minted by the ad platform and
 * utm_source is a campaign source, both of which arrive in the
 * landing URL and describe where a click came from. They are here so
 * the paid funnel can be read at its narrowest step — submission —
 * rather than only at the landing view, which is the one place they
 * were visible before.
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
// Four STANDARD OpenAI (ChatGPT Ads) Measurement Pixel conversions,
// emitted by lite/openaiPixel.js — never posthog.capture(), and
// therefore deliberately absent from EVENTS and EVENT_REGISTRY above
// (track() would drop them, which is correct: they are not ours to
// send to PostHog). Standard names, not custom ones, because only
// those carry meaning for conversion reporting and campaign
// optimization in Ads Manager.
//
//   registration_completed An audit submit was accepted; the run
//                          exists (LiteForm.jsx, accept path only).
//                          The high-volume signal. Fires for every
//                          accepted submit, re-runs included, since
//                          each mints its own token. No form value
//                          is sent.
//   lead_created           The status page's email capture succeeded
//                          (LiteProgress.jsx, success path only).
//                          The first moment a run has a person behind
//                          it rather than a store URL. The address
//                          itself is never sent.
//   appointment_scheduled  A demo request succeeded
//                          (useDemoRequestModal.js, ok-only branch —
//                          never on a honeypot trip or a 422).
//   contents_viewed        The report rendered for its owner
//                          (report/LiteFullReportV4.jsx, gated on
//                          isTokenOwned). Partial reads included: a
//                          partial read is still a viewed report.
//                          A share-link visitor never fires it.
//
// Each is sent at most once per key per browser SESSION, and carries
// an event_id so OpenAI dedupes server-side on the first event per
// key. The key is the run token, except for a demo request from the
// landing page, which has no token and uses a random per-submission
// id instead. No amount, currency, or PII on any of them.
//
// They are listed here, in the registry's own file, so THIS FILE
// remains the one complete answer to "what does this app emit, and
// where does it go" — ad conversions that existed only inside
// component effects would be exactly the kind of untracked emission
// this registry exists to prevent.
//
// See docs/analytics.md ("The OpenAI ad-conversion pixel").

// event name -> array of allowed prop keys. A key not listed here is
// dropped by track(); an event name not listed here is dropped whole.
export const EVENT_REGISTRY = {
  [EVENTS.LANDING_VIEWED]: ['src'],
  [EVENTS.AUDIT_SUBMITTED]: ['report_token', 'target_domain', 'oppref', 'utm_source', 'src'],
  [EVENTS.SAMPLE_REPORT_CLICKED]: ['placement'],
  [EVENTS.ESTIMATOR_INTERACTED]: [],
  [EVENTS.STATUS_VIEWED]: ['report_token'],
  [EVENTS.EMAIL_CAPTURED]: ['report_token'],
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
