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
  // Shared (landing + report — the modal fires the same event either way)
  DEMO_REQUEST_SUBMITTED: 'demo_request_submitted',
}

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
  // Union of the landing call (source only) and the report call
  // (source + brand_name + report_token) — the report-only props are
  // simply absent on a landing-fired call.
  [EVENTS.DEMO_REQUEST_SUBMITTED]: ['source', 'brand_name', 'report_token'],
}
