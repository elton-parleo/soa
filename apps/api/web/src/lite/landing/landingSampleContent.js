/**
 * L3: static marketing content for the V4 landing page — sample-card
 * numbers, field-evidence cases, proof-band logo lists, provenance
 * lines. Ported verbatim from the mock's renderVals() data block
 * (design-refs/20260405_Audit SOA Front-end/Audit Landing.dc.html),
 * from the same Allbirds sample run referenced throughout that mock
 * and the report mock (Audit Report.dc.html) — originally 40/100,
 * Visibility 25/40, Accessibility 8/20, True Value 7/40.
 *
 * Re-weighting session: SAMPLE_PILLAR_ITEMS below is a PLACEHOLDER —
 * proportionally rescaled onto the new maxes (32/18/50) from the
 * original ratios, not a real number. The original Allbirds run was
 * scored under an earlier SCORER_VERSION, so SAMPLE_REPORT_URL's own
 * token now serves the "this report has expired" state (Part 4) rather
 * than a real report — both need a fresh run against the current model
 * post-deploy: re-run the sample brand, point SAMPLE_REPORT_URL at the
 * new token, and replace these placeholder numbers with its real ones.
 *
 * Deliberately excludes the mock's dead data (never referenced by any
 * rendered tag in its own template): previewPillars, previewFixes,
 * heroQuery/heroReasoning/heroFooter/heroItems (all AgentAnswer-only,
 * and AgentAnswer is deferred this session), and agents (defined but
 * never rendered in the marquee, only merchants/rails are).
 */
import { reportUrl } from '../publicUrls.js'
import { LITE_QUERY_COUNT } from './scanDimensionsRegistry.js'

// B3: no dedicated sample-report route exists yet — points at a real,
// complete report already in the database (the Allbirds run generated
// during an earlier stage's live verification). Re-weighting session:
// this run predates the current SCORER_VERSION, so as of this deploy
// the link now serves the expired-report state (Part 4) — needs
// re-pointing at a fresh run, see the module docstring above.
export const SAMPLE_REPORT_URL = reportUrl('1710d72d74ee4a2ea6c9884c72cc96e2')

// Sample report card (Hero, right column) — the mock's illustrative
// preview OfferFeed, distinct from the report's own live-run OfferFeed.
export const SAMPLE_OFFERS = [
  { name: 'List price', value: '$105.00', channel: 'schema.org', eligibility: '1 of 4 pages', freshness: 'live', readable: 'seen' },
  { name: 'Free shipping', value: 'Text only', channel: 'page copy', eligibility: 'no structured threshold', freshness: 'live', readable: 'partial' },
  { name: 'Member price', value: 'N/A', channel: 'none found', eligibility: 'no loyalty program', freshness: 'stale', readable: 'invisible' },
  { name: 'Deals and promos', value: 'Not encoded', channel: 'none', eligibility: '0 of 4 pages', freshness: 'stale', readable: 'invisible' },
  { name: 'Checkout value', value: 'Nothing declared', channel: 'UCP / ACP', eligibility: 'no declaration found', freshness: 'stale', readable: 'invisible' },
]

// MetricRow items — sample report card. Placeholder values, proportionally
// rescaled from the original run's ratios onto the new maxes — see the
// module docstring; needs a real re-run to replace these.
export const SAMPLE_PILLAR_ITEMS = [
  { value: 20, suffix: '/32', label: 'Visibility', sub: 'Agents know who you are' },
  { value: 7, suffix: '/18', label: 'Accessibility', sub: 'Little of your catalog is readable' },
  { value: 9, suffix: '/50', label: 'True Value', sub: 'Only Parleo measures this', accent: true },
]

// Proof band — LogoMarquee items
export const PROOF_MERCHANTS = ['Allbirds', 'Brooklinen', 'Nike', 'Nordstrom', 'Target', 'Ulta', 'Best Buy', 'Lululemon', 'REI', 'Sephora', 'Patagonia', 'Dyson']
export const PROOF_RAILS = ['MCP', 'ACP', 'UCP', 'OpenAPI', 'AP2', 'Visa', 'Mastercard']

// Field evidence — Case 01 (Brooklinen, member-price incentive-sync gap)
export const CASE_01 = {
  brand: 'Brooklinen',
  domain: 'brooklinen.com',
  eyebrow: 'CHATGPT · BEDDING QUERY · OUR SCAN',
  quote: 'Brooklinen’s Luxe set is $269… members pay $228.65 — never mentioned.',
  quoted: {
    productLabel: 'Luxe Core Sheet Set · queen',
    stickerPrice: '$269.00',
  },
  memberPrice: {
    label: 'Funded, live, and in the loyalty terms',
    price: '$228.65',
    delta: '$40 UNDER THE QUOTE',
  },
  finding: 'The member price exists. The agent can\'t see it.',
  findingBody: 'Shoppers get quoted $40 above the price this brand already funds.',
  linkLabel: 'AN INCENTIVE-SYNC GAP — THE FIRST THING TRUESYNC CLOSES',
}

// Field evidence — Case 02 (razor category, deal-citation rate)
export const CASE_02 = {
  eyebrow: 'CHATGPT · GROOMING CATEGORY · OUR SCANS',
  statValue: '3.2%',
  statCaption: 'THE BEST DEAL-CITATION RATE OF ANY RAZOR BRAND WE SCANNED',
  headline: 'Across every razor brand we scanned, the best deal-citation rate was 3.2% of mentions.',
  surfacedLabel: 'PROMOTIONS SURFACED IN',
  surfacedValue: '1 OF EVERY 31 MENTIONS',
  surfacedTotal: 31,
  surfacedFilled: 1,
  bandCaption: 'EVERY OTHER BRAND IN THE CATEGORY DID WORSE',
  finding: 'Deals are funded — but not encoded.',
  findingBody: 'The winner\'s promotions surfaced in 1 of every 31 mentions; everyone else did worse.',
  linkLabel: 'UN-ENCODED VALUE CAN\'T BE CITED — THE SYNC PROBLEM AGAIN',
}

export const FIELD_EVIDENCE_PROVENANCE = ['FROM OUR OWN AUDIT RUNS', 'SAMPLES, NOT A CATEGORY STUDY', 'RUN YOUR AUDIT TO SEE YOUR NUMBERS']
export const GROUNDED_PROVENANCE = [`${LITE_QUERY_COUNT} queries`, 'ChatGPT only', 'deterministic']
