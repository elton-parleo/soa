/**
 * Leadgen session: single source mapping each "Book your walkthrough" /
 * "Talk to us about TrueSync" CTA to the copy RequestFormModal shows,
 * the `source` value that identifies where the lead came from, and the
 * `subject` line Formspree's notification email carries (demoRequestApi.js's
 * `_subject` field) — so a report-side CTA and the landing's TrueSync
 * CTA can point at the same underlying offer (TrueSync) while still
 * being distinguishable both in the submission's `source` and at a
 * glance in the inbox.
 */
export const DEMO_REQUEST_CTAS = {
  full_analysis_walkthrough: {
    eyebrow: 'BOOK YOUR WALKTHROUGH',
    title: "Let's walk through your audit together.",
    messagePlaceholder: 'Anything you want us to focus on in the read-out?',
    source: 'full_analysis_walkthrough',
    subject: 'Demo request — walkthrough',
  },
  truesync: {
    eyebrow: 'TRUESYNC',
    title: "Let's stop the leak.",
    messagePlaceholder: 'Tell us about your loyalty program and deals…',
    source: 'truesync',
    subject: 'Demo request — TrueSync',
  },
  landing_truesync: {
    eyebrow: 'TRUESYNC',
    title: "Let's stop the leak.",
    messagePlaceholder: 'Tell us about your loyalty program and deals…',
    source: 'landing_truesync',
    subject: 'Demo request — TrueSync',
  },
}
