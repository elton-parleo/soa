/**
 * L3: static marketing content for the V4 landing page — sample-card
 * numbers, field-evidence cases, proof-band logo lists, provenance
 * lines. The sample-card numbers (SAMPLE_OFFERS, SAMPLE_PILLAR_ITEMS)
 * and SAMPLE_REPORT_URL's token are the real values of a live Allbirds
 * run scored under SCORER_VERSION 5 (audit.parleo.io/r/
 * b41eb69930a14d97b2a7e7a306a17440), fetched from the public report
 * API and transcribed here as-is — not placeholders, not rescaled.
 * SAMPLE_REPORT_SCORER_VERSION records which SCORER_VERSION that run
 * was scored under, so a test can catch the next re-weighting before
 * this page quietly starts linking an expired report again.
 *
 * Deliberately excludes the mock's dead data (never referenced by any
 * rendered tag in its own template): previewPillars, previewFixes,
 * heroQuery/heroReasoning/heroFooter/heroItems (all AgentAnswer-only,
 * and AgentAnswer is deferred this session), and agents (defined but
 * never rendered in the marquee, only merchants/rails are).
 */
import { reportUrl } from '../publicUrls.js'
import { LITE_QUERY_COUNT } from './scanDimensionsRegistry.js'

// The version SAMPLE_REPORT_URL's run was scored under — a re-weighting
// that bumps SCORER_VERSION retires old reports (Part 4) rather than
// migrating them, so this sample goes stale the same way; see the test
// asserting this equals the live SCORER_VERSION.
export const SAMPLE_REPORT_SCORER_VERSION = '5'

// B3: no dedicated sample-report route exists yet — points at a real,
// complete report already in the database.
export const SAMPLE_REPORT_URL = reportUrl('b41eb69930a14d97b2a7e7a306a17440')

// Sample report card (Hero, right column) — the run's own real
// OfferFeed rows, verbatim from the report API.
export const SAMPLE_OFFERS = [
  { name: 'List price', value: '$110.00', channel: 'schema.org', eligibility: '16 of 16 offers', freshness: 'live', readable: 'partial' },
  { name: 'Availability', value: 'InStock', channel: 'schema.org', eligibility: '16 of 16 offers', freshness: 'live', readable: 'seen' },
  { name: 'Shipping', value: 'free shipping', channel: 'page copy', eligibility: 'text only, no structured threshold', freshness: 'live', readable: 'partial' },
  { name: 'Member price', value: 'N/A', channel: 'none found', eligibility: '0 of 67 products', freshness: 'stale', readable: 'invisible' },
  { name: 'Deals and promos', value: 'Not encoded', channel: 'none', eligibility: '0 of 67 products', freshness: 'stale', readable: 'partial' },
  { name: 'Checkout value', value: 'Nothing declared', channel: 'UCP / ACP', eligibility: 'no declaration found', freshness: 'stale', readable: 'invisible' },
]

// MetricRow items — sample report card. Real earned/max per pillar;
// subs are the run's own generated_headlines where the report shows
// one, the registry default headline otherwise.
export const SAMPLE_PILLAR_ITEMS = [
  { value: 25, suffix: '/32', label: 'Visibility', sub: 'Agents know who you are' },
  { value: 14, suffix: '/18', label: 'Accessibility', sub: "Agents can knock, but can't read much" },
  { value: 15, suffix: '/50', label: 'True Value', sub: 'Your prices are not machine-readable, while deal details appear on 2/2 pages.', accent: true },
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
