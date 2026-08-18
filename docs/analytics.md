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
