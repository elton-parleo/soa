/**
 * Leadgen session: single source mapping each "Book your walkthrough" /
 * "Talk to us about TrueSync" CTA to the copy RequestFormModal shows
 * and the `source` value the API stores — so a report-side CTA and the
 * landing's TrueSync CTA can point at the same underlying offer
 * (TrueSync) while still being distinguishable in soa_demo_requests by
 * where the lead actually came from.
 */
export const DEMO_REQUEST_CTAS = {
  full_analysis_walkthrough: {
    eyebrow: 'BOOK YOUR WALKTHROUGH',
    title: "Let's walk through your audit together.",
    messagePlaceholder: 'Anything you want us to focus on in the read-out?',
    source: 'full_analysis_walkthrough',
  },
  truesync: {
    eyebrow: 'TRUESYNC',
    title: "Let's stop the leak.",
    messagePlaceholder: 'Tell us about your loyalty program and deals…',
    source: 'truesync',
  },
  landing_truesync: {
    eyebrow: 'TRUESYNC',
    title: "Let's stop the leak.",
    messagePlaceholder: 'Tell us about your loyalty program and deals…',
    source: 'landing_truesync',
  },
}
