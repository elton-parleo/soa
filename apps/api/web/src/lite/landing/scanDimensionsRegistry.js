/**
 * Hand-maintained JS mirror of soa_shared/scan_dimensions.py's v4
 * registry — same convention as liteTheme.jsx's STAGE_ORDER mirroring
 * soa_shared/constants.py's QUERY_STAGES. There is no build-time bridge
 * from the Python registry to the web bundle in this codebase; keeping
 * this file's values in sync with the Python source is enforced by
 * scanDimensionsRegistry.test.js's pillar-total/dimension-weight/
 * SCORER_VERSION assertions (mirroring apps/pipeline/tests/
 * test_scan_dimensions_parity.py's own numbers by hand), not by codegen.
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

export const SCORER_VERSION = '5'

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

// Stage 26: the equation tab bar's one-line question per pillar (the
// mock's "are you mentioned?" etc.) — marketing copy, not derived from
// anything scoring-related, so it lives alongside PILLAR_NAMES rather
// than on each Dimension.
export const PILLAR_QUESTIONS = {
  [PILLAR_VISIBILITY]: 'are you mentioned?',
  [PILLAR_ACCESSIBILITY]: 'can agents read you?',
  [PILLAR_TRUE_VALUE]: 'is your value shown?',
}

// code -> { code, name, pillar, weight, seenMax, saidMax, oneLiner,
// leftLabel, chips, rightLabel, visualKind, visualParams, scoredCaption }
// — seenMax/saidMax are null for pillars with no seen/said split
// (visibility, accessibility) and for value_protocols' said half
// specifically (it has a seen half but no said half at all —
// encode-only), exactly like Python's Dimension.seen_max/said_max.
//
// Stage 26 (exhibit-tabs methodology rebuild): oneLiner/chips/
// scoredCaption/visualKind+params are this section's expanded-row detail
// copy, populated verbatim from the mock (design-refs/methodology-v4-
// exhibit-tabs-mock.html) — replaces the earlier whatItIs/howMeasured/
// howScored 3-microsection deck (unused now; nothing else read those
// fields). scoredCaption is an ordered array of {text, bold} segments so
// the component never hand-assembles bold/plain copy itself. chips
// entries are plain strings, except price_truth's one advisory entry
// ({label, advisory: true}) for the dashed warn-styled chip.
// visualKind is one of 'meter' | 'ladder' | 'pips' | 'grid' | 'duo' |
// 'none' — 'none' means the right cell is caption-only (agent_access,
// protocol_feed, value_protocols all have no scored-side graphic).
export const DIMENSIONS = [
  {
    code: 'share_of_mentions', name: 'Share of Mentions', pillar: PILLAR_VISIBILITY,
    weight: 22, seenMax: null, saidMax: null,
    oneLiner: 'your share of all brand mentions',
    leftLabel: 'HOW WE MEASURE',
    chips: [`${LITE_QUERY_COUNT} shopper questions`, 'every brand counted', 'your share'],
    rightLabel: "HOW IT'S SCORED",
    visualKind: 'meter',
    visualParams: { fillPct: 70, tickPct: 70, tickLabel: '50% SHARE' },
    scoredCaption: [
      { text: 'Bigger share, more points. ', bold: false },
      { text: '50% share = all 22.', bold: true },
    ],
  },
  {
    code: 'recommendation_strength', name: 'Recommendation Strength', pillar: PILLAR_VISIBILITY,
    weight: 10, seenMax: null, saidMax: null,
    oneLiner: 'top pick, or just listed',
    leftLabel: 'HOW WE MEASURE',
    chips: ['where you appear', "how strongly you're recommended"],
    rightLabel: "HOW IT'S SCORED",
    visualKind: 'ladder',
    visualParams: {
      bands: [
        { label: '1st + endorsed', value: '10/10', hot: true },
        { label: 'listed', value: '5', hot: false },
        { label: 'absent', value: '0', hot: false },
      ],
    },
    scoredCaption: [
      { text: "More points when you're the first, strongest pick.", bold: true },
    ],
  },
  {
    code: 'agent_access', name: 'Agent Access', pillar: PILLAR_ACCESSIBILITY,
    weight: 5, seenMax: null, saidMax: null,
    oneLiner: 'can agents reach your site',
    leftLabel: 'THE CHECKS',
    chips: [],
    rightLabel: "HOW IT'S SCORED",
    visualKind: 'pips',
    visualParams: {
      pips: [
        { label: 'robots', ok: true },
        { label: 'no blocks', ok: true },
        { label: 'sitemap', ok: false },
      ],
    },
    scoredCaption: [
      { text: 'Each check passed earns points.', bold: true },
      { text: ' 2 of 3 = 3/5.', bold: false },
    ],
  },
  {
    code: 'catalog_context', name: 'Catalog & Context', pillar: PILLAR_ACCESSIBILITY,
    weight: 8, seenMax: null, saidMax: null,
    oneLiner: 'can agents read your products',
    leftLabel: 'WHAT WE CHECK',
    chips: ['product data', 'price + availability', 'product IDs (GTIN)', 'shipping info'],
    rightLabel: "HOW IT'S SCORED",
    visualKind: 'grid',
    visualParams: { total: 4, ok: 3 },
    scoredCaption: [
      { text: 'Points per readable product page.', bold: true },
      { text: ' 3 of 4 = 6/8.', bold: false },
    ],
  },
  {
    code: 'protocol_feed', name: 'Protocol & Feed Presence', pillar: PILLAR_ACCESSIBILITY,
    weight: 5, seenMax: null, saidMax: null,
    oneLiner: 'listed where agents look',
    leftLabel: 'WHAT WE CHECK',
    chips: ['llms.txt', 'MCP', 'UCP profile'],
    rightLabel: "HOW IT'S SCORED",
    visualKind: 'none',
    visualParams: null,
    scoredCaption: [
      { text: 'Points for each one present.', bold: true },
      { text: ' Feeds are checked in the full analysis.', bold: false },
    ],
  },
  {
    code: 'price_truth', name: 'Price Truth', pillar: PILLAR_TRUE_VALUE,
    weight: 16, seenMax: 7, saidMax: 9,
    oneLiner: 'do agents know your price',
    leftLabel: 'WHAT WE CHECK',
    chips: [
      'price in your code', 'code matches page price', 'price hidden behind login',
      { label: 'fake sale prices · flagged', advisory: true },
    ],
    rightLabel: 'SCORED ON BOTH SIDES',
    visualKind: 'duo',
    visualParams: { leftPct: 100, rightPct: 57, leftLabel: 'ON YOUR SITE · 7', rightLabel: 'IN ANSWERS · 9' },
    scoredCaption: [
      { text: 'A readable price — ', bold: false },
      { text: 'and answers that actually say it.', bold: true },
    ],
  },
  {
    code: 'member_value', name: 'Member Value', pillar: PILLAR_TRUE_VALUE,
    weight: 8, seenMax: 5, saidMax: 3,
    oneLiner: 'do agents mention member perks',
    leftLabel: 'WHAT WE CHECK',
    chips: ['findable loyalty page', 'member price in your code', 'code that parses cleanly'],
    rightLabel: 'SCORED ON BOTH SIDES',
    visualKind: 'duo',
    visualParams: { leftPct: 100, rightPct: 40, leftLabel: 'ON YOUR SITE · 5', rightLabel: 'IN ANSWERS · 3' },
    scoredCaption: [
      { text: 'No loyalty program? This one is skipped', bold: true },
      { text: ' and your score adjusts — we check first.', bold: false },
    ],
  },
  {
    code: 'deal_citability', name: 'Deal Citability', pillar: PILLAR_TRUE_VALUE,
    weight: 12, seenMax: 7, saidMax: 5,
    oneLiner: 'do your deals get mentioned',
    leftLabel: 'WHAT WE CHECK',
    chips: ['clear discount amount', 'not expired', 'codes agents can use'],
    rightLabel: 'SCORED ON BOTH SIDES',
    visualKind: 'ladder',
    visualParams: {
      bands: [
        { label: '0 cited', value: '0', hot: false },
        { label: '1', value: '40%', hot: true },
        { label: '2–3', value: '70%', hot: true },
        { label: '4+', value: '100%', hot: true },
      ],
    },
    scoredCaption: [
      { text: 'Deals in your code — ', bold: false },
      { text: 'and cited when shoppers are ready to buy.', bold: true },
    ],
  },
  {
    code: 'value_protocols', name: 'Value Protocols', pillar: PILLAR_TRUE_VALUE,
    // Encode-only: a real seen half (crawl-derived declaration checks,
    // seenMax === weight) with NO said half at all — agents don't state
    // in an answer whether a store "declares" a checkout protocol, so
    // there is nothing to cite (Part 3, V1; Part 6, A1's single-wing
    // butterfly render).
    weight: 14, seenMax: 14, saidMax: null,
    oneLiner: 'is value wired into agent checkout',
    siteOnly: true,
    leftLabel: 'WHAT WE CHECK',
    // Stage 26 (B5): "checkout discount capability" — the mock's own
    // chip literally reads "checkout discount support", but B5's wording
    // discipline (this dimension only ever says a store "declares" a
    // capability, never that it "supports" one) takes precedence over
    // verbatim-copying that one chip.
    //
    // Re-weighting session (Part 1): the manifest-shape check split into
    // two (resolves + current version), reflected here as one added chip
    // rather than two — this list is landing-page illustrative copy, not
    // the report's own check labels (those come from soa_shared.scan_
    // dimensions.Dimension.how_measured, served by the API).
    chips: ['manifest resolves + version current', 'UCP discounts', 'loyalty extension', 'ACP promotions'],
    rightLabel: "HOW IT'S SCORED",
    visualKind: 'none',
    visualParams: null,
    scoredCaption: [
      { text: "This one never shows up in answers — it works at checkout.", bold: true },
      { text: ' We score what your store declares; the full analysis tests what works.', bold: false },
    ],
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
