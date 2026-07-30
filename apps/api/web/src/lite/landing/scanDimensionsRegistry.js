/**
 * Hand-maintained JS mirror of soa_shared/scan_dimensions.py's v4
 * registry — same convention as liteTheme.jsx's STAGE_ORDER mirroring
 * soa_shared/constants.py's QUERY_STAGES. There is no build-time bridge
 * from the Python registry to the web bundle in this codebase; keeping
 * this file's values in sync with the Python source is enforced by
 * tests/AnatomyOfAnAnswer.test.jsx's pillar-total/SCORER_VERSION
 * assertions, not by codegen.
 *
 * Exported as plain, mutable-for-tests data (not frozen) so a test can
 * substitute a perturbed DIMENSIONS_BY_CODE entry and assert the
 * rendered flag moves — same "perturbation proves it's data-driven, not
 * hard-coded" discipline as the Python parity tests.
 *
 * Stage 25: this is now the ONLY dimension registry the methodology
 * section imports — the marketing-only preview module
 * (scanDimensionsV4Preview.js) is deleted; landing and scorer cannot
 * disagree from this commit on. whatItIs/howMeasured/howScored are the
 * methodology section's expanded-row detail copy, mirrored verbatim
 * from soa_shared/scan_dimensions.py's Dimension.what_it_is/
 * how_measured/how_scored — never consumed by scoring.
 */

export const SCORER_VERSION = '4'

export const LITE_QUERY_COUNT = 24

export const PILLAR_VISIBILITY = 'visibility'
export const PILLAR_ACCESSIBILITY = 'accessibility'
export const PILLAR_TRUE_VALUE = 'true_value'

export const PILLAR_ORDER = [PILLAR_VISIBILITY, PILLAR_ACCESSIBILITY, PILLAR_TRUE_VALUE]

export const PILLAR_NAMES = {
  [PILLAR_VISIBILITY]: 'Visibility',
  [PILLAR_ACCESSIBILITY]: 'Accessibility',
  [PILLAR_TRUE_VALUE]: 'True Value',
}

// code -> { code, name, pillar, weight, seenMax, saidMax, whatItIs,
// howMeasured, howScored } — seenMax/saidMax are null for pillars with
// no seen/said split (visibility, accessibility) and for value_
// protocols' said half specifically (it has a seen half but no said
// half at all — encode-only), exactly like Python's Dimension.seen_max/
// said_max.
export const DIMENSIONS = [
  {
    code: 'share_of_mentions', name: 'Share of Mentions', pillar: PILLAR_VISIBILITY,
    weight: 25, seenMax: null, saidMax: null,
    whatItIs: 'Your share of every brand mention across the answers.',
    howMeasured: [
      `${LITE_QUERY_COUNT} shopper questions on ChatGPT`,
      'every brand mention coded',
      'your mentions vs the field',
    ],
    howScored: 'Linear — half of all mentions earns full marks.',
  },
  {
    code: 'recommendation_strength', name: 'Recommendation Strength', pillar: PILLAR_VISIBILITY,
    weight: 15, seenMax: null, saidMax: null,
    whatItIs: "How you're mentioned — the pick, or one of a list.",
    howMeasured: [
      'position in the answer',
      'endorsement language',
    ],
    howScored: 'Banded from mention position and strength.',
  },
  {
    code: 'agent_access', name: 'Agent Access', pillar: PILLAR_ACCESSIBILITY,
    weight: 6, seenMax: null, saidMax: null,
    whatItIs: 'Can agents get in at all.',
    howMeasured: [
      'robots.txt allows product paths',
      'no bot-blocks',
      'sitemap resolves',
    ],
    howScored: 'Pass/fail checks, summed.',
  },
  {
    code: 'catalog_context', name: 'Catalog & Context', pillar: PILLAR_ACCESSIBILITY,
    weight: 8, seenMax: null, saidMax: null,
    whatItIs: 'Can agents parse what you sell.',
    howMeasured: [
      'Product + Offer structured data on product pages',
      'name, price, availability complete',
      'GTIN/brand identifiers consistent',
    ],
    howScored: 'Share of sampled pages passing; identifiers weighted.',
  },
  {
    code: 'protocol_feed', name: 'Protocol & Feed Presence', pillar: PILLAR_ACCESSIBILITY,
    weight: 6, seenMax: null, saidMax: null,
    whatItIs: 'Are you present on the channels agents query.',
    howMeasured: [
      'llms.txt',
      'MCP declaration',
      'a UCP profile exists',
    ],
    howScored: 'Presence checks; feed participation is verified in the full analysis.',
  },
  {
    code: 'price_truth', name: 'Price Truth', pillar: PILLAR_TRUE_VALUE,
    weight: 12, seenMax: 5, saidMax: 7,
    whatItIs: 'Can agents state your real price.',
    howMeasured: [
      'machine-readable price and currency on offers',
      'promotions as data, not banner images',
      'the structured price agrees with the price on the page',
    ],
    howScored: "Encoding checks plus how often answers that name you state your price. A price behind sign-in doesn't exist to an agent.",
  },
  {
    code: 'member_value', name: 'Member Value', pillar: PILLAR_TRUE_VALUE,
    weight: 15, seenMax: 9, saidMax: 6,
    whatItIs: 'Can agents see what members get — and do they say it.',
    howMeasured: [
      'a loyalty page agents can find and read',
      'member prices attached to product offers',
      'markup valid enough that strict parsers keep it',
    ],
    howScored: 'Encoding checks plus how often answers credit you with member value. Skipped and rescaled only when no program exists.',
  },
  {
    code: 'deal_citability', name: 'Deal Citability', pillar: PILLAR_TRUE_VALUE,
    weight: 6, seenMax: 4, saidMax: 2,
    whatItIs: 'Do live promotions survive into answers.',
    howMeasured: [
      'deals in markup that are concrete (amount stated)',
      'active (validity date, not expired)',
      'actionable (eligibility or code readable)',
    ],
    howScored: 'Encoding checks plus deal citations on purchase-intent questions. No published deals scores zero, not exempt.',
  },
  {
    code: 'value_protocols', name: 'Value Protocols', pillar: PILLAR_TRUE_VALUE,
    // Encode-only: a real seen half (crawl-derived declaration checks,
    // seenMax === weight) with NO said half at all — agents don't state
    // in an answer whether a store "declares" a checkout protocol, so
    // there is nothing to cite (Part 3, V1; Part 6, A1's single-wing
    // butterfly render).
    weight: 7, seenMax: 7, saidMax: null,
    whatItIs: 'Can your value execute inside agent checkout — not just be described.',
    howMeasured: [
      'UCP discount capability declared',
      'loyalty or member extension declared',
      'ACP promotions declared',
      'declared versions current and schemas resolving',
    ],
    howScored: "Declaration checks — we score what a store declares, the full analysis verifies what works. This one doesn't appear in the sentence — it executes at checkout.",
  },
]

export const DIMENSIONS_BY_CODE = Object.fromEntries(DIMENSIONS.map((d) => [d.code, d]))

export const PILLAR_WEIGHTS = Object.fromEntries(
  PILLAR_ORDER.map((pillar) => [
    pillar,
    DIMENSIONS.filter((d) => d.pillar === pillar).reduce((sum, d) => sum + d.weight, 0),
  ]),
)

export const TOTAL_MAX = Object.values(PILLAR_WEIGHTS).reduce((sum, w) => sum + w, 0)

// ── Verdict gate (Stage 25, Part 5, G1) ─────────────────────────────────
export const VERDICT_COMPOSITE_THRESHOLD = 60
export const VERDICT_TRUE_VALUE_RATIO_THRESHOLD = 0.25
export const VERDICT_AGENT_READY = 'AGENT-READY'
export const VERDICT_NOT_AGENT_READY = 'NOT AGENT-READY'
