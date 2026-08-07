// C1/C2: non-run-derived marketing prose for the report page, plus the
// renamed CTA family (Full Analysis / Book your walkthrough) reused
// from the same single source as the landing page.
export { FULL_ANALYSIS_URL, WALKTHROUGH_URL, TRUESYNC_URL } from '../publicUrls.js'

export const EDITORIAL_QUOTE = 'The shelf is now an algorithm. Most of your value is still invisible to it.'

export const FUNNEL_GATE_COPY = {
  eyebrow: 'NOT IN THIS SAMPLE',
  title: 'Where you disappear in the funnel',
  body: 'Stage-by-stage mention rates, from awareness to ready-to-buy.',
  ctaHeading: 'Go deeper than the sample',
  ctaBody: 'The Full Analysis is free and custom to your store: Gemini, Perplexity, and Claude on the same questions, a category study at thousands of queries instead of your sample, and SKU-level price accuracy across your catalog. We run it, then walk you through the results live.',
  ctaFooter: 'TAKES ONE CALL TO SCOPE · READ-OUT IN DAYS · NO INTEGRATION, NO OBLIGATION',
}

export const TRUESYNC_BAND_COPY = {
  title: 'Encoded, declared, and kept in sync',
  body: 'TrueSync encodes your member value and deals, declares them to the checkout standards agents use (Google’s UCP, OpenAI’s ACP), and keeps them current as offers change.',
}

export const CLOSING_FORK_COPY = {
  fullAnalysisTitle: 'Go deeper than the sample',
  fullAnalysisBody: 'The Full Analysis is free and custom to your store: Gemini, Perplexity, and Claude on the same questions, a category study at thousands of queries instead of your sample, and SKU-level price accuracy across your catalog. We run it, then walk you through the results live.',
  trueSyncTitle: 'Stop the leak',
  trueSyncBody: 'The audit measures four gap areas. Parleo fixes two of them directly.',
  steps: [
    { title: 'Encode', body: 'Member value and deals, in markup agents can read.' },
    { title: 'Declare', body: 'Value capabilities in UCP and ACP agent checkout.' },
    { title: 'Stay in sync', body: 'Updated as offers change, no drift back to zero.' },
  ],
}

export const GROUNDED_COPY = {
  measured: 'Every number here is measured. The audit reads the open standards agents actually read (schema.org, UCP, ACP) and scores them deterministically, so you can inspect every point.',
  keepThem: 'Already running Profound or Bluelight? Keep them. They track whether agents mention you. This audit measures whether your real price and value survive when they do.',
}

// Partial-read report state (Part 3c): one entry per failure-point
// shape (reportDerive.js's partialReadFailurePoint). Never hardcoded
// prose in DiscoveryFinding.jsx — the component only reads this table.
export const FAILURE_POINT_COPY = {
  no_product_pages_found: {
    heading: "Your catalog isn't discoverable to a reader that follows the rules",
    body: "We read your sitemaps this run but couldn't locate product pages to sample from them.",
    explanation: 'This usually means product links are rendered by JavaScript after the page loads, or your sitemaps index editorial and collection pages instead of individual SKUs.',
    fixFraming: 'make your product pages discoverable',
  },
  blocked: {
    heading: 'Your edge refuses identified readers before they can look',
    body: 'Your site blocked or rate-limited our identified reader on every page we tried this run.',
    explanation: 'An edge this strict is worth verifying against the agents you actually care about — not just our reader.',
    fixFraming: 'allow verified agent traffic',
  },
  partial: {
    heading: 'Too few product pages came through to score your catalog',
    body: 'We reached some of your product pages this run, but not enough to score the dimensions that depend on them.',
    explanation: 'A thin sample like this can come from rate limiting, timeouts, or pages that fetched but never parsed cleanly.',
    fixFraming: 'get more product pages through cleanly',
  },
}

// Part 3d: DegradedRunBanner's compact partial-read summary line — the
// causal explanation itself lives only in FAILURE_POINT_COPY /
// DiscoveryFinding (grep-tested: appears once per report), this is
// just the pointer down to it.
export const PARTIAL_READ_BANNER_COPY = {
  summary: "This run measured Visibility in full and most of Accessibility — it couldn't reach enough product pages to complete the read.",
  linkLabel: 'Why we stopped short',
}

// Part 5b: the ungated "what a complete read adds" band — copy only,
// never the gating logic (that lives in whether CompleteReadBand
// renders at all, gated on isPartialRead, not on Full Analysis).
export const COMPLETE_READ_BAND_COPY = {
  eyebrow: 'NOT MEASURED THIS RUN · NOT GATED',
  title: 'What a complete read adds',
  body: "These aren't behind the Full Analysis — they're waiting on fix 01. Re-run the free audit afterward and they fill in automatically.",
  tiles: [
    { title: 'Your page, as parsed', body: 'What an agent actually reads on your product page.' },
    { title: 'Six value signals', body: 'Price truth and deal citability, scored from your own markup.' },
    { title: 'Price truth, both sides', body: 'What your site states next to what agents actually quote.' },
    { title: 'A full score and verdict', body: 'A real composite and an agent-ready verdict, not withheld.' },
  ],
}
