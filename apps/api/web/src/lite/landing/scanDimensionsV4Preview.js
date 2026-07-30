/**
 * v4 PREVIEW — marketing surface only; the scorer is v3. Delete this
 * module and point the section at soa_shared/scan_dimensions when the
 * v4 scoring stage lands (see AnatomyOfAnAnswer.test.jsx's skipped
 * parity test, which flips to active — and becomes the enforcement —
 * the moment SCORER_VERSION === '4').
 *
 * Same shape/convention as scanDimensionsRegistry.js (the real, v3,
 * hand-maintained mirror of soa_shared/scan_dimensions.py): plain,
 * mutable-for-tests data, not frozen, so a test can perturb a
 * DIMENSIONS_BY_CODE entry and assert the rendered value moves.
 *
 * ONLY apps/api/web/src/lite/landing/AnatomyOfAnAnswer.jsx may import
 * this module (enforced by an import-guard test) — it is a preview of
 * a framework that does not score anything yet, and must never leak
 * into report rendering, which stays on the real v3 registry.
 *
 * Each dimension additionally carries three detail fields (Part 1),
 * rendered by the methodology section's L1 expanded panel:
 *   whatItIs   — one sentence
 *   howMeasured — 2-4 short check strings
 *   howScored  — one plain-language line. For the three True Value
 *     dimensions with a seen/said split, the SEEN n · SAID n numbers
 *     themselves are rendered separately from seenMax/saidMax (never
 *     baked into this string) so perturbing those fields still moves
 *     the rendered split, same discipline as the weight/pts flags.
 */

export const PILLAR_VISIBILITY = 'visibility'
export const PILLAR_ACCESSIBILITY = 'accessibility'
export const PILLAR_TRUE_VALUE = 'true_value'

export const PILLAR_ORDER = [PILLAR_VISIBILITY, PILLAR_ACCESSIBILITY, PILLAR_TRUE_VALUE]

export const PILLAR_NAMES = {
  [PILLAR_VISIBILITY]: 'Visibility',
  [PILLAR_ACCESSIBILITY]: 'Accessibility',
  [PILLAR_TRUE_VALUE]: 'True Value',
}

export const DIMENSIONS = [
  {
    code: 'share_of_mentions', name: 'Share of Mentions', pillar: PILLAR_VISIBILITY,
    weight: 25, seenMax: null, saidMax: null,
    whatItIs: 'Your share of every brand mention across the answers.',
    howMeasured: [
      '12 shopper questions on ChatGPT',
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
    weight: 7, seenMax: null, saidMax: null,
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
