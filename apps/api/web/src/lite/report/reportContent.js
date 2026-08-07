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

// Blocked-run copy pass: the run's own refusal status and attempt
// count, written in words rather than jargon ("refused every request
// (403)" rather than "403-refused") — the one place FAILURE_POINT_COPY.
// blocked.body needs live substitution, so it's a function instead of
// a plain string like its sibling entries below.
function _blockedRefusalPhrase(bannerFacts) {
  const refusal = bannerFacts?.refusal
  const code = refusal === '403' || refusal === '429' ? ` (${refusal})` : ''
  const n = bannerFacts?.attempts
  const attemptsPhrase = n ? `, across ${n} attempt${n === 1 ? '' : 's'}` : ''
  return `refused every request${code} before serving a page${attemptsPhrase}`
}

// Partial-read report state (Part 3c): one entry per failure-point
// shape (reportDerive.js's partialReadFailurePoint). Never hardcoded
// prose in DiscoveryFinding.jsx — the component only reads this table.
//
// Blocked-run copy pass: the blocked entry is written for the report's
// actual reader — a marketing or ecommerce lead, not the engineer who
// configured the CDN. Plain language throughout: what happened, whose
// fault it isn't, who to ask. `body` is a function here (bannerFacts)
// => string) since it's the one entry that interpolates live run facts;
// DegradedRunBanner's top-of-report summary reads the same function,
// so the two surfaces can never drift on wording. `fixFraming` is the
// action line, rendered both in this section's closing note and as the
// matching ranked-fix's description (FixesTable.jsx).
export const FAILURE_POINT_COPY = {
  no_product_pages_found: {
    heading: "Your catalog isn't discoverable to a reader that follows the rules",
    body: "We read your sitemaps this run but couldn't locate product pages to sample from them.",
    explanation: 'This usually means product links are rendered by JavaScript after the page loads, or your sitemaps index editorial and collection pages instead of individual SKUs.',
    fixFraming: 'make your product pages discoverable',
  },
  blocked: {
    heading: 'Your site turned our reader away at the door.',
    body: (bannerFacts) => `We visited your site the way an AI shopping agent does — announcing who we are, following the rules in your robots.txt, and asking politely for a few product pages. Your site ${_blockedRefusalPhrase(bannerFacts)}. This usually isn't a deliberate choice: most bot-blocking is a default setting in security tools like Cloudflare, switched on to stop scrapers, that also blocks the AI assistants your shoppers are using. Your marketing team almost never knows it's on.`,
    fixFraming: "The fix is a settings change, not a project. Whoever manages your website security can allow verified AI shopping agents in minutes. Ask them to permit traffic from OpenAI, Google, Anthropic, and Perplexity's published crawlers — and to allow readers that verify themselves cryptographically, which is how we identify ourselves too.",
  },
  partial: {
    heading: 'Too few product pages came through to score your catalog',
    body: 'We reached some of your product pages this run, but not enough to score the dimensions that depend on them.',
    explanation: 'A thin sample like this can come from rate limiting, timeouts, or pages that fetched but never parsed cleanly.',
    fixFraming: 'get more product pages through cleanly',
  },
}

// Part 2c: the four-step discovery trace's blocked-path wording — the
// same plain-verbs register as the rest of this entry (reading the
// site's rules, asking for pages, being refused), never the generic
// step text the other two failure points still use. Only the steps
// the blocked path actually produces facts for are here; DiscoveryFinding.jsx
// falls back to the shared generic wording for any step this doesn't cover.
export const BLOCKED_STEP_COPY = {
  robots: {
    good: "Read your site's rules for readers like ours — nothing there said no.",
    bad: "Turned away before we could even read your site's rules.",
  },
  homepage: {
    good: 'Asked for your homepage and got it.',
    bad: 'Asked for your homepage and were turned away.',
  },
  productPages: {
    good: 'Asked for product pages and got them.',
    bad: 'Asked for product pages and were refused every time.',
  },
}

function _resolveBody(body, bannerFacts) {
  return typeof body === 'function' ? body(bannerFacts) : body
}
export { _resolveBody as resolveFailurePointBody }

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
