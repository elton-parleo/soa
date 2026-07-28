/**
 * Hand-maintained JS mirror of soa_shared/scan_dimensions.py's v3
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
 */

export const SCORER_VERSION = '3'

export const PILLAR_VISIBILITY = 'visibility'
export const PILLAR_ACCESSIBILITY = 'accessibility'
export const PILLAR_TRUE_VALUE = 'true_value'

export const PILLAR_ORDER = [PILLAR_VISIBILITY, PILLAR_ACCESSIBILITY, PILLAR_TRUE_VALUE]

export const PILLAR_NAMES = {
  [PILLAR_VISIBILITY]: 'Visibility',
  [PILLAR_ACCESSIBILITY]: 'Accessibility',
  [PILLAR_TRUE_VALUE]: 'True Value',
}

// code -> { code, name, pillar, weight, seenMax, saidMax } — seenMax/
// saidMax are null for pillars with no seen/said split (visibility,
// accessibility), exactly like Python's Dimension.seen_max/said_max.
export const DIMENSIONS = [
  { code: 'share_of_mentions', name: 'Share of Mentions', pillar: PILLAR_VISIBILITY, weight: 25, seenMax: null, saidMax: null },
  { code: 'recommendation_strength', name: 'Recommendation Strength', pillar: PILLAR_VISIBILITY, weight: 15, seenMax: null, saidMax: null },
  { code: 'agent_access', name: 'Agent Access', pillar: PILLAR_ACCESSIBILITY, weight: 6, seenMax: null, saidMax: null },
  { code: 'catalog_context', name: 'Catalog & Context', pillar: PILLAR_ACCESSIBILITY, weight: 8, seenMax: null, saidMax: null },
  { code: 'protocol_feed', name: 'Protocol & Feed Presence', pillar: PILLAR_ACCESSIBILITY, weight: 6, seenMax: null, saidMax: null },
  { code: 'price_truth', name: 'Price Truth', pillar: PILLAR_TRUE_VALUE, weight: 14, seenMax: 6, saidMax: 8 },
  { code: 'member_value', name: 'Member Value', pillar: PILLAR_TRUE_VALUE, weight: 19, seenMax: 12, saidMax: 7 },
  { code: 'deal_citability', name: 'Deal Citability', pillar: PILLAR_TRUE_VALUE, weight: 7, seenMax: 4, saidMax: 3 },
]

export const DIMENSIONS_BY_CODE = Object.fromEntries(DIMENSIONS.map((d) => [d.code, d]))

export const PILLAR_WEIGHTS = Object.fromEntries(
  PILLAR_ORDER.map((pillar) => [
    pillar,
    DIMENSIONS.filter((d) => d.pillar === pillar).reduce((sum, d) => sum + d.weight, 0),
  ]),
)

export const TOTAL_MAX = Object.values(PILLAR_WEIGHTS).reduce((sum, w) => sum + w, 0)
