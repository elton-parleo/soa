// C1/C2: non-run-derived marketing prose for the report page. The
// walkthrough/TrueSync CTAs used to link out to WALKTHROUGH_URL/
// FULL_ANALYSIS_URL/TRUESYNC_URL (publicUrls.js) — leadgen session
// replaced every one of those links with RequestFormModal, so those
// constants are gone; see lite/demoRequestCtas.js for the CTA copy.

export const EDITORIAL_QUOTE = 'The shelf is now an algorithm. Most of your value is still invisible to it.'

// Exposure-model fix (this session): the model line under the exposure
// figure, and the read-only assumption rows in ADJUST ASSUMPTIONS. It
// lives here, not in ExposureSection.jsx, for the same reason every
// other block on this page does — the component renders copy, it never
// authors it.
//
// The old line claimed "the invisibility factor comes from your True
// Value result" while the code was actually feeding it the VISIBILITY
// pillar. This wording describes what is now genuinely computed,
// including the substitution channel and the cap. `body` is a function
// because one clause is conditional: a row with no True Value pillar
// (legacy scorer_version) models maximum gap, and the reader has to be
// told that rather than shown a number implying it was measured.
// The ranked-fixes "not ranked in this sample" strip. The base line was
// a literal in FixesTable.jsx; it moves here because this session adds a
// conditional clause to it.
//
// Why the clause: the report shows two point totals that use the same
// arithmetic over the same dimensions — the section title's "N moves
// recover up to M points" (the VISIBLE rows) and the headline finding's
// "worth up to K points" (the whole TrueSync pool). They can legitimately
// differ when a TrueSync dimension ranks outside the visible top two,
// and that is honest — but silently. When the pool is larger than what
// the visible rows account for, the strip now says how much of it is
// sitting in the unranked remainder, so a reader can reconcile the two
// numbers instead of guessing at the discrepancy. Below 1 point the
// clause is noise, so it doesn't render.
export const FIXES_REMAINING_STRIP = {
  minTrueSyncRemainder: 1,
  line: ({ remainingCount, trueSyncRemainder }) => (
    `${remainingCount} MORE FIXES IDENTIFIED, NOT RANKED IN THIS SAMPLE`
    + (trueSyncRemainder >= 1
      ? ` · INCLUDING UP TO ${Math.round(trueSyncRemainder * 10) / 10} MORE TRUESYNC POINTS`
      : '')
  ),
}

export const EXPOSURE_MODEL_COPY = {
  lead: 'The model:',
  body: ({ revenueLabel, aiSharePct, measured }) => (
    `revenue × AI-assisted share × a value-invisibility factor derived from your True Value result`
    + `, including a substitution allowance for answers where an agent quotes a competitor's price or deal in your place`
    + ` — capped so exposure never exceeds your AI-assisted revenue. `
    + `${revenueLabel} annual revenue, ${aiSharePct}% AI-assisted share. `
    + (measured
      ? ''
      : 'This run has no True Value pillar to read, so the figure assumes your value is fully invisible. ')
    + 'Modeled, not measured — the Full Analysis replaces it with measured price gaps.'
  ),
  // Read-only in ADJUST ASSUMPTIONS, deliberately not a slider: it is a
  // modeling constant, and a per-report knob would make every report's
  // number incomparable to every other.
  substitutionAssumption: '1.5× substitution allowance',
  substitutionAssumptionNote: 'MODELING CONSTANT · NOT ADJUSTABLE',
}

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
// Blocked-run vendor attribution (this session): seven of the 22 stores
// in the 30-day review 403'd their homepage, and the report told every
// one of them the same thing — "security tools like Cloudflare" — whether
// or not that was the tool actually refusing us. The scan has known the
// vendor all along (fetcher.py's _edge_vendor_hint, rolled up per run by
// engine.py's block_evidence); it just never reached the page.
//
// `name` is what the reader's own team calls it. `setting` is the
// specific control that opens the door, so the message they forward
// lands on something actionable rather than "please allow AI crawlers".
// Keys are apps/pipeline/scan/fetcher.py's EDGE_VENDOR_MARKERS vendor
// ids, one-for-one; "shopify" is not here and never will be — it
// fingerprints a store platform, not a wall.
//
// This changes what the report CALLS the wall. It never changes a score:
// the vendor is evidence, and evidence is not points.
export const EDGE_VENDOR_COPY = {
  cloudflare: {
    name: 'Cloudflare',
    setting: 'In Cloudflare this is the Bot Fight Mode / Super Bot Fight Mode setting, plus the Verified Bots allowlist and any custom firewall rule that filters on how a reader identifies itself.',
  },
  akamai: {
    name: 'Akamai',
    setting: 'In Akamai this is Bot Manager — the bot category actions and the allowlist of known, declared bots.',
  },
  datadome: {
    name: 'DataDome',
    setting: 'In DataDome this is your bot-protection policy and its allowlist of verified crawlers.',
  },
  human_px: {
    name: 'HUMAN (PerimeterX)',
    setting: 'In HUMAN / PerimeterX this is the Bot Defender enforcement policy and its allowlist of known good bots.',
  },
  imperva: {
    name: 'Imperva',
    setting: 'In Imperva this is the Advanced Bot Protection policy and its list of permitted declared bots.',
  },
}

// The neutral wording for a run where nothing was recognized — the
// same shape as a named vendor, never a hedge bolted on at render time.
export const EDGE_VENDOR_UNKNOWN_COPY = {
  clause: "most bot-blocking is a default setting in a security or CDN product, switched on to stop scrapers, that also blocks the AI assistants your shoppers are using. Your marketing team almost never knows it's on",
  setting: "Whoever manages your website security can allow verified AI shopping agents in minutes. Ask them to permit traffic from OpenAI, Google, Anthropic, and Perplexity's published crawlers — and to allow readers that verify themselves cryptographically, which is how we identify ourselves too.",
}

export function edgeVendorCopy(vendor) {
  return EDGE_VENDOR_COPY[vendor] || null
}

// The middle clause of FAILURE_POINT_COPY.blocked.body — "whose fault
// this isn't", named when we know the name.
function _blockedVendorClause(edgeVendor) {
  const v = edgeVendorCopy(edgeVendor)
  if (!v) return EDGE_VENDOR_UNKNOWN_COPY.clause
  return (
    `this is ${v.name}'s bot protection turning away a reader that announced who it was, and it is almost `
    + 'always a default setting switched on to stop scrapers — one that also blocks the AI assistants your '
    + "shoppers are using. Your marketing team almost never knows it's on"
  )
}

export const FAILURE_POINT_COPY = {
  no_product_pages_found: {
    heading: "Your catalog isn't discoverable to a reader that follows the rules",
    body: "We read your sitemaps this run but couldn't locate product pages to sample from them.",
    explanation: 'This usually means product links are rendered by JavaScript after the page loads, or your sitemaps index editorial and collection pages instead of individual SKUs.',
    fixFraming: 'make your product pages discoverable',
  },
  // body/fixFraming take (bannerFacts, edgeVendor) — edgeVendor is
  // report.scan.edge_vendor, null when this run's fetches carried no
  // recognized fingerprint. Both surfaces that render this (the
  // DiscoveryFinding section and DegradedRunBanner) pass it, so the two
  // can never disagree about whose wall this is.
  blocked: {
    heading: 'Your site turned our reader away at the door.',
    body: (bannerFacts, edgeVendor) => `We visited your site the way an AI shopping agent does — announcing who we are, following the rules in your robots.txt, and asking politely for a few product pages. Your site ${_blockedRefusalPhrase(bannerFacts)}. This usually isn't a deliberate choice: ${_blockedVendorClause(edgeVendor)}.`,
    fixFraming: (_bannerFacts, edgeVendor) => {
      const v = edgeVendorCopy(edgeVendor)
      return 'The fix is a settings change, not a project. '
        + (v ? `${v.setting} Ask whoever manages it to permit traffic from OpenAI, Google, Anthropic, and Perplexity's published crawlers — and to allow readers that verify themselves cryptographically, which is how we identify ourselves too.`
             : EDGE_VENDOR_UNKNOWN_COPY.setting)
    },
  },
  // Unreachable-host follow-up (Lululemon, request 138): every request
  // this run — robots.txt, the sitemap, the store root — timed out
  // without an answer, while ChatGPT opened the same homepage fine. The
  // old report said "your site doesn't declare a sitemap", which was
  // never checked. This is the blocked family (a wall on readers like
  // ours, just a silent one), so it reads like `blocked` and names the
  // vendor the same way when DNS recognized one.
  unreachable: {
    heading: 'Your site never answered our reader.',
    body: (_bannerFacts, edgeVendor) => `We visited your site the way an AI shopping agent does — announcing who we are and following the rules in your robots.txt. No response came back: every request, including the one for your robots.txt, was held open until we gave up. This usually isn't a deliberate choice: ${_blockedVendorClause(edgeVendor)}.`,
    fixFraming: (bannerFacts, edgeVendor) => FAILURE_POINT_COPY.blocked.fixFraming(bannerFacts, edgeVendor),
  },
  partial: {
    heading: 'Too few product pages came through to score your catalog',
    body: 'We reached some of your product pages this run, but not enough to score the dimensions that depend on them.',
    explanation: 'A thin sample like this can come from rate limiting, timeouts, or pages that fetched but never parsed cleanly.',
    fixFraming: 'get more product pages through cleanly',
  },
}

// Discovery follow-up (Part 4): one entry per apps/pipeline/scan/
// discovery_outcome.py code, read by DiscoveryFinding.jsx whenever
// report.scan.discovery_outcome is present (older reports without it
// fall back to FAILURE_POINT_COPY above, keyed by the coarser 3-bucket
// failurePoint). `body` is deliberately NOT duplicated here — the
// outcome's own `summary` field is already first-person, fact-grounded
// prose generated from this exact run (see discovery_outcome.py), so
// DiscoveryFinding renders it directly instead of a second, static
// copy of the same claim that could drift from the real trace.
//
// Plain-verb register throughout, same reader as FAILURE_POINT_COPY:
// never "blocked" for a code that's our own reader's limitation
// (product_sitemap_unrecognized, sitemap_children_unprobed,
// sitemaps_non_catalog, homepage_no_links, rescue_tiers_skipped,
// no_sitemap, unknown) — "blocked" is reserved for the codes where the
// site itself genuinely turned us away (product_pages_refused,
// sitemaps_refused, sitemaps_robots_disallowed, short_circuited).
export const DISCOVERY_OUTCOME_COPY = {
  product_pages_read: {
    heading: 'We read some of your product pages, but not enough to score everything',
    explanation: 'A thin sample like this can come from rate limiting, timeouts, or pages that fetched but never parsed cleanly.',
    fixFraming: 'get more product pages through cleanly',
  },
  product_pages_refused: {
    heading: 'Your site refused our reader on every product page we found',
    explanation: "This usually comes from a bot-blocking rule triggering on our reader specifically, not a deliberate choice by your team.",
    fixFraming: 'allow verified AI reader traffic through to your product pages',
  },
  // Product-candidate verification: Walmart's shape. The pages opened
  // fine — they just weren't product pages — so this must never read
  // as a refusal or as a network problem.
  product_candidates_not_products: {
    heading: "We opened the pages your catalog pointed us to, and none of them carried product details",
    explanation: 'Each one loaded normally but had no product markup on it — a category or landing page, or a version of the page served without its product details.',
    fixFraming: 'make sure the page an identified reader gets is the same product page a shopper gets, with its price and availability in the markup',
  },
  product_pages_unreadable: {
    heading: 'We found your product pages, but none of them could be read',
    explanation: 'A network error or timeout kept every page from loading — not a refusal.',
    fixFraming: 'check that your product pages load reliably for readers outside your own network',
  },
  short_circuited: {
    heading: 'Your site turned our reader away before we could look any further',
    explanation: 'Both your robots.txt and your store root refused us, so we stopped rather than keep probing a site that had already said no.',
    fixFraming: 'allow verified AI reader traffic in your robots.txt and at your store root',
  },
  // Walled-site runtime: the Warby Parker shape — robots.txt served,
  // HTML and the catalog behind a wall. Deliberately does NOT read as
  // "you blocked us everywhere": the rules file came through fine, and
  // saying otherwise would be wrong in a way the site's own operator
  // would immediately catch.
  homepage_and_sitemap_refused: {
    heading: 'Your rules file came through, but your store pages and sitemap did not',
    explanation: 'Your robots.txt was served normally, while your store root and your first declared sitemap both refused our reader — so we stopped rather than keep asking a wall the same question.',
    fixFraming: 'allow verified AI reader traffic through to your store pages and your sitemaps, not just your robots.txt',
  },
  sitemaps_refused: {
    heading: 'Your site refused every sitemap request we made',
    explanation: 'We found your sitemap(s), but every request for one came back refused rather than served.',
    fixFraming: 'allow verified AI reader traffic through to your sitemaps',
  },
  sitemaps_robots_disallowed: {
    heading: 'Your robots.txt disallows every sitemap you declare',
    explanation: "Your homepage links didn't lead to a product page either, so we had nowhere else to look.",
    fixFraming: 'allow readers like ours to fetch your declared sitemaps in robots.txt',
  },
  no_sitemap: {
    heading: "We couldn't find a sitemap for your site",
    explanation: 'Neither your robots.txt nor the default /sitemap.xml location pointed us to one.',
    fixFraming: 'add a sitemap and declare it in robots.txt',
  },
  product_sitemap_unrecognized: {
    heading: "We read a sitemap that looks like your catalog, but couldn't recognize its product pages",
    explanation: "Its URLs use a shape our reader doesn't recognize, and a page sample of it found no product markup either.",
    fixFraming: 'use a recognizable URL pattern for product pages, or add product markup we can detect',
  },
  sitemap_children_unprobed: {
    heading: 'Your sitemap index lists more product-shaped sitemaps than we had budget to read this run',
    explanation: 'We ran out of budget before reaching every catalog-shaped sitemap your index declares.',
    fixFraming: 'put your product sitemap earlier in your sitemap index, or trim non-catalog sitemaps out of it',
  },
  sitemaps_non_catalog: {
    heading: 'We read your sitemaps and checked your homepage, but found nothing that looked like a product catalog',
    explanation: 'Every sitemap and link we checked turned up editorial or navigational pages, not products.',
    fixFraming: 'add product pages to a sitemap so a reader can find your catalog',
  },
  homepage_no_links: {
    heading: "Your site has no sitemap, and your homepage's own links didn't lead anywhere we could follow",
    explanation: 'Without a sitemap or homepage links to products or categories, we had nothing left to follow.',
    fixFraming: 'add a sitemap, or link to your product and category pages from your homepage',
  },
  rescue_tiers_skipped: {
    heading: "We ran out of budget before trying every option we had left",
    explanation: "One or more of our fallback discovery options never got to run this pass.",
    fixFraming: 'make your product pages reachable earlier in a scan — for example, via a sitemap or homepage links',
  },
  unknown: {
    heading: "We couldn't determine why your product pages weren't found this run",
    explanation: "Nothing in this run's trace matched a pattern we recognize — worth a second look on our end.",
    fixFraming: 'get in touch so we can dig into this run directly',
  },
}

// Blocked-run evidence (this session): the fetch probe promoted out of
// a trailing clause on the banner and into a fact of its own. On Vans
// and Warby Parker the probe came back quoted_price on the SAME audit
// whose crawl was refused at the door — ChatGPT read a price off a page
// our reader could not open. On Adidas, NAPA, and Vans' second run it
// came back could_not_access, which corroborates the block rather than
// contradicting it. Both are worth a reader's attention; neither is
// worth a single point, and this never touches one.
//
// Every line here is scoped to what the probe actually established.
// "ChatGPT read a price" is a claim about one page at one moment, not
// about every agent or every page, and nothing here says otherwise.
export const FETCH_PROBE_EVIDENCE_COPY = {
  label: 'WHAT CHATGPT SAW',
  quoted_price: ({ kindPhrase, price }) => (
    price
      ? `We asked ChatGPT to open ${kindPhrase} itself. It opened, and it quoted ${price}.`
      : `We asked ChatGPT to open ${kindPhrase} itself. It opened, and it quoted a price.`
  ),
  opened_no_price: ({ kindPhrase }) => (
    `We asked ChatGPT to open ${kindPhrase} itself. It opened, though it didn't quote a price.`
  ),
  could_not_access: ({ kindPhrase }) => (
    `We asked ChatGPT to open ${kindPhrase} itself. It couldn't access it either.`
  ),
  // The caveat under the fact, so "ChatGPT got in" is never read as
  // "the wall is only a problem for you".
  quoted_price_note: 'The wall is on readers like ours, not on every reader — but the setting that produced it is the same one an agent hits when it is not on the allowlist.',
  could_not_access_note: 'Two independent readers, the same refusal.',
}

// The accessibility tile's headline on a blocked run, replacing the
// generic "Couldn't be measured this run" whenever the probe has
// something concrete to say about the same wall. Never a score change —
// the tile's number is untouched.
export const BLOCKED_ACCESSIBILITY_HEADLINE = {
  quoted_price: 'Our reader was refused; ChatGPT read a price',
  opened_no_price: 'Our reader was refused; ChatGPT got in',
  could_not_access: "Our reader was refused; ChatGPT couldn't get in either",
}

// Non-commerce report (this session): emcube, marketlytics and
// wealthsimple were all correctly typed brand_only by
// apps/pipeline/scan/site_typing.py, scored 10-22, and were then
// rendered as failing STORES — three pillars, a composite out of 100,
// a "Not agent-ready" chip and a ranked list of store fixes for a site
// with no storefront. The typing was right; the report just never saw
// it, because site_type was not on the row at all.
//
// What this variant does NOT do is change a single score. The
// True Value dimensions still carry the numbers the scorer computed
// (price_truth_seen and friends score 0 at coverage='full' on a
// brand-only site — re-coding them to 'na' would move applicable_max
// and the composite, which is a methodology change and out of scope
// here). This is presentation: the report stops asserting a verdict
// about a storefront that does not exist, and says plainly why the
// store-side pillars are blank.
export const BRAND_ONLY_COPY = {
  statusChip: 'Non-store site',
  scoreLabel: 'visibility',
  heroNote: "We didn't find a storefront on this site — no cart, no product pages, no commerce markup. Visibility is the pillar that still applies; the store-side pillars need a storefront URL to measure.",
  accessibilityNote: 'Agent Access and Protocol & Feed apply to any site. Catalog Context reads product pages, which this site does not appear to have.',
  trueValueHeading: 'Not applicable to a non-store site',
  trueValueBody: "True Value measures whether your price, member value and deals survive into an agent's answer. There is no catalog here for that to apply to. If you do sell somewhere else, point the audit at that storefront's URL and this pillar fills in.",
  railNote: 'NON-STORE SITE',
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

// Unreachable-host follow-up: the trace steps an unreachable run can
// state. robots.txt never answered either, so discovery_trace carries
// robots_ok: null and that step doesn't render at all.
export const UNREACHABLE_STEP_COPY = {
  homepage: {
    good: 'Asked for your homepage and got it.',
    bad: 'Asked for your homepage. No answer came back before we gave up.',
  },
  productPages: {
    good: 'Asked for product pages and got them.',
    bad: 'Never got far enough to ask for a product page — nothing answered.',
  },
}

// Manufacturer sites (Clorox, request 146): real product pages with
// Product markup and GTINs, and no Offer anywhere, because the brand
// sells through retailers. Price truth and deal citability are correct
// zeros — but the report used to ask Clorox to publish prices it has no
// way to publish. Same discipline as BRAND_ONLY_COPY: presentation only.
// Every stored score, and the composite, stay exactly as scored; the
// three offer-bearing True Value rows say why they don't apply, and
// their ranked fixes point at the channel that does carry the offer.
export const MANUFACTURER_COPY = {
  dimensionNote: 'not applicable to a manufacturer site — offers live at your retailers',
  trueValueNote: "Your product pages carry product details but no prices — shoppers are sent to your retailers to buy. Price, member value and deals are read where your offers actually live, so this run doesn't hold them against your own site.",
  // The ranked-fix text for price_truth / member_value / deal_citability.
  fixHuman: 'Get your product data — GTINs, names and current offers — into the retailer and marketplace feeds agents read, so the price an agent quotes for your product is the one your retailers actually charge.',
}
export const MANUFACTURER_NA_DIMENSION_CODES = ['price_truth', 'member_value', 'deal_citability']

function _resolveBody(body, bannerFacts, edgeVendor) {
  return typeof body === 'function' ? body(bannerFacts, edgeVendor) : body
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
