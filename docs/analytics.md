# Product analytics — audit landing, status, and report

PostHog, explicit events only. Client events measure behavior; the
database is already ground truth for submissions, emails, and demo
requests. The two join later by the run token (`report_token`, a
PostHog super-property set once per report load via
`identifyReport(token)` in [`analytics.js`](../apps/api/web/src/lite/analytics.js)).

Owned by one module, [`apps/api/web/src/lite/analytics.js`](../apps/api/web/src/lite/analytics.js),
which is the only file in the frontend allowed to import `posthog-js`
directly. The registry of every trackable event and its allowed props
lives in [`apps/api/web/src/lite/analyticsEvents.js`](../apps/api/web/src/lite/analyticsEvents.js) —
`track()` drops anything not in it. No event carries email, name,
company, message, or any other form value; those actions are tracked
as bare facts (`audit_submitted`, `email_captured`) with no payload.

## The four questions

1. **Funnel truth.** Visit → audit submitted → email captured → report
   opened → demo requested. Where does the funnel actually leak?
2. **Report engagement.** Which report sections get read, and does
   reading them correlate with a demo request?
3. **The share loop.** Shares → visitor report views → visitor-run
   audits. Is the report itself acquiring new visitors?
4. **Read quality vs. conversion.** Do partial-read and blocked
   reports convert worse than fully scored ones?

## Event schema

| Event | Props | Fired when |
|---|---|---|
| `landing_viewed` | `src` | Landing page mounts. `src` from `captureSrcParam()`, defaults to `direct`. |
| `audit_submitted` | — | Intake accepted (200 from submit) — the funnel's spine. |
| `sample_report_clicked` | `placement` | A "see a sample report" link is clicked (`nav`, `hero`, `sample_section`, `final_cta`). |
| `estimator_interacted` | — | First interaction with the landing revenue/AI-share sliders, once per session. |
| `demo_request_submitted` | `source`, `brand_name`, `report_token` | The demo request modal gets a 200. `brand_name`/`report_token` only present when fired from a report page; never fires on a honeypot trip. |
| `status_viewed` | — | Status page mounts. |
| `email_captured` | — | Email successfully saved on the status page (fact only, no address). |
| `report_viewed` | `state`, `viewer`, `src`, `report_type` | Report page mounts. `state` is `scored`\|`partial`\|`blocked`\|`expired`. `viewer` is `owner`\|`visitor` (lite: does this browser hold the token from its own submission? Full Analysis: is this the authenticated owner's own view, via real auth state). `src` from `captureSrcParam()`. `report_type` is absent for lite, `full_analysis` for [`FullAnalysisReport.jsx`](../apps/api/web/src/components/FullAnalysisReport.jsx) — same event/props, shared across both products rather than a second event. |
| `section_viewed` | `section` | A report section is ≥50% visible for a continuous 1s, once per section per load. |
| `section_expanded` | `section`, `control` | A collapsible panel or top-level section opens (closed→open only). Instrumented once inside the shared `useCollapsible` hook and `SectionCollapseButton`, not per call site. |
| `transcript_answer_expanded` | — | The "From the transcript" widget's "Show the full answer" toggle opens (closed→open only). Separate from `section_expanded` — measures reading past the preview into the full verbatim answer, not the outer section collapsing (which already fires `section_expanded` via `ReportSection`/`SectionCollapseButton`). No response text in the payload, ever. |
| `share_copied` | `placement` | The share link is successfully copied (`desktop_rail`, `mobile_summary`, `mobile_sticky_bar` for lite; `full_analysis_owner` for the Full Analysis report's Share control). |
| `cta_clicked` | `cta`, `placement` | A report CTA is clicked. `cta` is `walkthrough`\|`truesync`\|`run_your_free_audit`\|`rerun`. |
| `adjust_assumptions_used` | — | The exposure section's revenue/AI-share inputs are touched, once per load. |

## Day-one insights to build in PostHog

1. **Core funnel** — `landing_viewed` → `audit_submitted` →
   `email_captured` → `report_viewed` (filtered `viewer = owner`) →
   `demo_request_submitted`.
2. **Report engagement → demo, by read state** — the same
   `report_viewed` → `demo_request_submitted` funnel, broken down by
   `report_viewed.state` (`scored` vs `partial` vs `blocked`), to test
   whether a degraded read converts worse than a clean score.
3. **Share loop** — `share_copied` → `report_viewed` (filtered
   `viewer = visitor`) → `audit_submitted`, to measure the viral
   coefficient of a shared report.
4. **Engagement depth vs. conversion** — `section_viewed` ranked by
   volume, and `section_expanded` ranked by volume, each correlated
   against `demo_request_submitted` to see which sections' readers
   actually convert.

## Reading the numbers

- **Persistence is `memory`, not cookie-based** — deliberate, so a
  report a merchant forwards to their CMO never triggers a consent
  banner. The trade-off: a repeat visit in a new tab/session counts as
  a new visitor. Unique-visitor counts here are **per-session**, not
  per-person — don't read them as deduplicated humans.
- **Session replay sampling is a PostHog project setting, not a code
  flag.** `analytics.js` enables recording (`disable_session_recording:
  false`, inputs and text masked) but the *sample rate* (start at 20%)
  is configured in the PostHog dashboard under Settings → Session
  Replay → ingestion controls, not in the init call.
- **`?src=email`** is appended to the report-ready email's link
  (`apps/pipeline/worker.py`) and captured client-side, then stripped
  from the address bar via `history.replaceState` so a copied-from-
  the-bar link stays canonical (no lingering `?src=email` from a
  re-share). The share button builds its URL independently and never
  carries `src`.

## The OpenAI ad-conversion pixel

Separate system, separate destination. The OpenAI (ChatGPT Ads)
Measurement Pixel is **not** PostHog and does not go through `track()`
— these events are deliberately absent from `EVENT_REGISTRY`, and are
documented in a comment block in
[`analyticsEvents.js`](../apps/api/web/src/lite/analyticsEvents.js) so
that file stays the complete list of what this app emits and where it
goes.

Three **standard** OpenAI events, matching the conversions defined on
this pixel in Ads Manager. Standard names carry meaning for conversion
reporting and campaign optimization in a way a custom name cannot,
which is why the earlier one-off custom event was retired rather than
kept alongside them.

| Event | Shape | Fired when | Dedup key |
|---|---|---|---|
| `lead_created` | `{ type: 'customer_action' }` | The status page's email capture succeeded ([`LiteProgress.jsx`](../apps/api/web/src/lite/LiteProgress.jsx), success path only). The first moment a run has a person behind it rather than a store URL. | run token |
| `appointment_scheduled` | `{ type: 'customer_action' }` | A demo request succeeded ([`useDemoRequestModal.js`](../apps/api/web/src/lite/useDemoRequestModal.js), ok-only branch — never on a honeypot trip or a 422). | run token, or a random per-submission id when the modal opened from the landing page |
| `contents_viewed` | `{ type: 'contents', contents: [{ id, name, content_type }] }` | The report rendered for its owner ([`LiteFullReportV4.jsx`](../apps/api/web/src/lite/report/LiteFullReportV4.jsx), gated on `isTokenOwned`). | run token |

- **Once per key per browser session.** A `sessionStorage` key
  (`oaiq:{event}:{key}`) stops a reload or remount re-firing within a
  session; the `event_id` on every call lets OpenAI collapse
  duplicates server-side on the first event per key. `sessionStorage`
  rather than `localStorage` is deliberate — a genuinely new session
  may attribute again if the click window still covers it.
- **`contents_viewed` includes partial reads.** An earlier version
  required a numeric composite, which withheld the conversion for
  every partial read — that measured our scoring confidence rather
  than the visitor's experience. A partial read is still a viewed
  report. A share-link visitor is still not a conversion.
- **Owned by one module**,
  [`apps/api/web/src/lite/openaiPixel.js`](../apps/api/web/src/lite/openaiPixel.js),
  the only file allowed to touch `window.oaiq` — same grep-enforced
  boundary as `analytics.js` and `posthog-js`. The SDK loader itself is
  inline in the served HTML of both audit documents, written in at
  build time by `vite.config.js` from
  [`openaiPixel.constants.js`](../apps/api/web/src/lite/openaiPixel.constants.js),
  because the `oaiq` queue must exist before the async SDK arrives.
- **Both audit documents carry it, including `/r/` and `/s/`.** This is
  the one explicit exception to the rule that the report document
  carries no tracker (the landing's outreach-attribution pixel is still
  landing-only, and the build test still asserts it). `contents_viewed`
  can only be observed where the report renders.
- **No transaction data, no PII.** No `amount`, `currency`, `plan_id`,
  or `contents` on the two `customer_action` events; `contents_viewed`
  carries only `id`, `name` and `content_type` per item. No `user`
  object on init. `custom_event_name` is valid only for custom events
  and none of these carry it. `lead_created` never sends the email
  address it is about — the run token is the identifier, on the same
  grounds `report_token` is allowed above.
- **Audit submit is not a conversion** in this mapping.
  `audit_submitted` stays a PostHog-only event.
- **`?oppref=`** is captured by the SDK on init and persisted in a
  first-party `__oppref` cookie on the audit host, so it already
  survives client-side navigation. `withOppref()` additionally carries
  it through our `pushState` paths (landing submit, report re-run) so
  the address bar keeps it. Only `oppref`, and only on those two
  navigations — share links, the Copy-link button, the report-ready
  email, and `reportUrl()` all keep producing the bare canonical URL.
- **Verbose SDK logging** is on (`OPENAI_PIXEL_DEBUG = true`). Flip
  that one constant to `false` once the conversions are confirmed live.
