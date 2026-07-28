"""
scan_dimensions.py — Stage 16: SCORER_VERSION "3", the three-pillar
Agent Scan rubric. Single source of truth for pillar/dimension
structure, weights, the seen/said split on True Value dimensions, band
tables, and opportunity sets. Consumed by apps/pipeline/scan/scorer.py
(crawl-derived dimensions), apps/api/app/services/ pure scoring modules
(mention/citation-derived dimensions), apps/api/app/routers/
public_lite.py (report/teaser assembly), and the report/landing
widgets.

Replaces the two-family (Foundation/Value) v2 rubric (scorer_version
"2") entirely as the basis for NEW scans. v2's public-contract fields
stay serialized (additive-only, rule 6) but nothing new is computed
from them going forward — see PART 6/7 of the Stage 16 brief.

Pillars (sum to TOTAL_MAX):
  visibility (40)     — share_of_mentions 25, recommendation_strength 15
  accessibility (20)  — agent_access 6, catalog_context 8, protocol_feed 6
  true_value (40)     — price_truth 14 (seen 6 / said 8),
                         member_value 19 (seen 12 / said 7),
                         deal_citability 7 (seen 4 / said 3)

Composite = a straight sum of pillar points, rescaled onto 100 (or onto
applicable_max when member_value is N/A — Part 4, P4). No blending
layer: v2's 0.6*visibility + 0.4*accessibility composite is gone.

Which half of the stack computes which dimension:
  - agent_access, catalog_context, protocol_feed, and the *_seen halves
    of price_truth/member_value/deal_citability are crawl-derived —
    computed by apps/pipeline/scan/scorer.py from fetched page data,
    exactly like v2's dimension functions (T1: same check logic,
    rescaled onto the new seen_max values).
  - share_of_mentions, recommendation_strength, and the *_said halves
    are derived from the 12-query coded/metrics data (soa_coded_
    mentions, soa_price_observations via MetricsCalculator) — that
    data doesn't exist inside the crawl-only scan engine, so these are
    computed where the lite report already joins both data sources:
    apps/api/app/services/ pure modules, called from public_lite.py.
"""
from dataclasses import dataclass
from typing import Optional, Tuple

SCORER_VERSION = "3"

# ── Pillars ────────────────────────────────────────────────────────────

PILLAR_VISIBILITY = "visibility"
PILLAR_ACCESSIBILITY = "accessibility"
PILLAR_TRUE_VALUE = "true_value"

PILLAR_ORDER: Tuple[str, ...] = (PILLAR_VISIBILITY, PILLAR_ACCESSIBILITY, PILLAR_TRUE_VALUE)

PILLAR_NAMES = {
    PILLAR_VISIBILITY: "Visibility",
    PILLAR_ACCESSIBILITY: "Accessibility",
    PILLAR_TRUE_VALUE: "True Value",
}

# ── Opportunity sets (Stage 16, Part 0 calibration) ─────────────────────
# Deal and member-typed citations both concentrate overwhelmingly in the
# purchase-intent stages — measured against production data:
#   deal_citation_rate:       Comparison 2.06%, Ready to Buy 6.12%
#                              vs. Awareness 0.94%, Research 0.31%
#   member-typed citations:   59 of 63 (94%) fall in Comparison + Ready
#                              to Buy across full SoA cycles
# price_truth.said stays on ALL_MENTIONS — price citation isn't
# purchase-stage-gated the way deal/member-value citation is.
#
# Stage 7 discipline: 'purchase_intent' resolves to the underlying stage
# names below server-side only (in the scoring code that computes the
# opportunity-set mention count) — it is never itself emitted as a
# stage name, and no stage-sliced value ever reaches a payload or copy.
OPPORTUNITY_SET_ALL_MENTIONS = "all_mentions"
OPPORTUNITY_SET_PURCHASE_INTENT = "purchase_intent"

PURCHASE_INTENT_STAGES: Tuple[str, ...] = ("Comparison", "Ready to Buy")

# Fewer than this many mentions in a said sub-lens's opportunity set ->
# that sub-lens is N/A and the dimension rescales onto its seen half.
MIN_OPPORTUNITY_SET_MENTIONS = 2

# ── Band tables ──────────────────────────────────────────────────────────
# Rate bands (price_truth.said, member_value.said): rate is a 0-100
# citation-rate percentage. 0 -> 0%; (0,25] -> 40%; (25,50] -> 70%;
# (50,100] -> 100% of the sub-lens's max.
RATE_BAND_TABLE: Tuple[Tuple[Optional[float], float], ...] = (
    (0, 0.0),
    (25, 0.40),
    (50, 0.70),
    (None, 1.0),
)

# Count bands (deal_citability.said): 0 -> 0%; exactly 1 -> 60%;
# 2+ -> 100% of the sub-lens's max.
COUNT_BAND_TABLE: Tuple[Tuple[Optional[int], float], ...] = (
    (0, 0.0),
    (1, 0.60),
    (None, 1.0),
)

BAND_TYPE_RATE = "rate"
BAND_TYPE_COUNT = "count"


def apply_rate_band(rate_pct: Optional[float]) -> float:
    """
    Fraction (0.0-1.0) of a said sub-lens's max earned for a citation
    rate expressed as a 0-100 percentage, per RATE_BAND_TABLE. Never
    raises — None/negative input is treated as 0.
    """
    rate_pct = rate_pct or 0.0
    if rate_pct <= 0:
        return RATE_BAND_TABLE[0][1]
    for upper, fraction in RATE_BAND_TABLE:
        if upper is None or rate_pct <= upper:
            return fraction
    return RATE_BAND_TABLE[-1][1]


def apply_count_band(count: Optional[int]) -> float:
    """
    Fraction (0.0-1.0) of a said sub-lens's max earned for a citation
    count, per COUNT_BAND_TABLE. Never raises.
    """
    count = count or 0
    if count <= 0:
        return COUNT_BAND_TABLE[0][1]
    for upper, fraction in COUNT_BAND_TABLE:
        if upper is None or count <= upper:
            return fraction
    return COUNT_BAND_TABLE[-1][1]


# ── Dimensions ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Dimension:
    code: str
    name: str
    pillar: str
    weight: float
    seen_max: Optional[float] = None
    said_max: Optional[float] = None
    said_opportunity_set: Optional[str] = None
    said_band_type: Optional[str] = None

    @property
    def has_seen_said_split(self) -> bool:
        return self.seen_max is not None and self.said_max is not None


DIMENSIONS: Tuple[Dimension, ...] = (
    Dimension(
        code="share_of_mentions", name="Share of Mentions",
        pillar=PILLAR_VISIBILITY, weight=25,
    ),
    Dimension(
        code="recommendation_strength", name="Recommendation Strength",
        pillar=PILLAR_VISIBILITY, weight=15,
    ),
    Dimension(
        code="agent_access", name="Agent Access",
        pillar=PILLAR_ACCESSIBILITY, weight=6,
    ),
    Dimension(
        code="catalog_context", name="Catalog & Context",
        pillar=PILLAR_ACCESSIBILITY, weight=8,
    ),
    Dimension(
        code="protocol_feed", name="Protocol & Feed Presence",
        pillar=PILLAR_ACCESSIBILITY, weight=6,
    ),
    Dimension(
        code="price_truth", name="Price Truth",
        pillar=PILLAR_TRUE_VALUE, weight=14,
        seen_max=6, said_max=8,
        said_opportunity_set=OPPORTUNITY_SET_ALL_MENTIONS,
        said_band_type=BAND_TYPE_RATE,
    ),
    Dimension(
        code="member_value", name="Member Value",
        pillar=PILLAR_TRUE_VALUE, weight=19,
        seen_max=12, said_max=7,
        said_opportunity_set=OPPORTUNITY_SET_PURCHASE_INTENT,
        said_band_type=BAND_TYPE_RATE,
    ),
    Dimension(
        code="deal_citability", name="Deal Citability",
        pillar=PILLAR_TRUE_VALUE, weight=7,
        seen_max=4, said_max=3,
        said_opportunity_set=OPPORTUNITY_SET_PURCHASE_INTENT,
        said_band_type=BAND_TYPE_COUNT,
    ),
)

DIMENSION_ORDER: Tuple[str, ...] = tuple(d.code for d in DIMENSIONS)
DIMENSIONS_BY_CODE = {d.code: d for d in DIMENSIONS}

PILLAR_WEIGHTS = {
    pillar: sum(d.weight for d in DIMENSIONS if d.pillar == pillar)
    for pillar in PILLAR_ORDER
}
TOTAL_MAX = sum(PILLAR_WEIGHTS.values())

MEMBER_VALUE_CODE = "member_value"


# ── Seen/said combination (Stage 16, Part 3 T2) ─────────────────────────

def dimension_max(dimension: Dimension, said_na: bool = False) -> float:
    """
    The points-max a seen/said-split True Value dimension contributes
    to the composite this scan. Normally its full weight (seen_max +
    said_max); when the said (outcome) sub-lens is N/A — its
    opportunity-set mention count fell below MIN_OPPORTUNITY_SET_
    MENTIONS — the dimension rescales onto its seen half only, the same
    na-rescale idea as Part 4's whole-rubric member_value exclusion
    (applicable_max below), just scoped to one dimension. A no-op
    (returns weight) for dimensions with no seen/said split at all.
    """
    if not dimension.has_seen_said_split:
        return dimension.weight
    return dimension.seen_max if said_na else dimension.weight


# ── Composite (Stage 16, Part 4 P4 / Part 7 A3) ─────────────────────────

def applicable_max(member_value_na: bool) -> float:
    """
    TOTAL_MAX (100), or TOTAL_MAX minus member_value's full weight when
    member_value is N/A (Part 4, P4 — Visibility 40 + Accessibility 20
    + Price Truth 14 + Deal Citability 7 = 81) — derived from the
    registry weights, never hard-coded, so a weight change moves this
    number automatically (see the perturbation test).
    """
    if not member_value_na:
        return TOTAL_MAX
    return TOTAL_MAX - DIMENSIONS_BY_CODE[MEMBER_VALUE_CODE].weight


def compute_composite(total_earned: float, member_value_na: bool = False) -> int:
    """
    THE single composite function (Part 7, A3) — teaser, report, email,
    and any exposure math all consume this, never their own inline
    blend. total_earned is the caller's sum of every SCORED (non-N/A)
    dimension's earned points; this only handles the final rescale onto
    0-100. No 0.6/0.4 visibility/accessibility blend — a straight sum.
    """
    basis = applicable_max(member_value_na)
    if basis <= 0:
        return 0
    return round(total_earned / basis * 100)
