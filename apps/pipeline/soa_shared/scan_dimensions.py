"""
scan_dimensions.py — Stage 25: SCORER_VERSION "4", the three-pillar
Agent Scan rubric. Single source of truth for pillar/dimension
structure, weights, the seen/said split on True Value dimensions, band
tables, opportunity sets, the lite study's query-count constant, and
the verdict gate's thresholds. Consumed by apps/pipeline/scan/scorer.py
(crawl-derived dimensions), apps/api/app/services/ pure scoring modules
(mention/citation-derived dimensions), apps/api/app/routers/
public_lite.py (report/teaser assembly), and the report/landing
widgets.

Replaces SCORER_VERSION "3" (Stage 16) as the basis for NEW scans. v3's
public-contract fields stay serialized (additive-only, rule 6) but
nothing new is computed from them going forward; a v3-scored row now
falls through to the same honest "previous methodology" fallback v1/v2
rows already used (see public_lite.py's version gate).

Pillars (sum to TOTAL_MAX):
  visibility (40)     — share_of_mentions 25, recommendation_strength 15
  accessibility (20)  — agent_access 6, catalog_context 8, protocol_feed 6
  true_value (40)     — price_truth 12 (seen 5 / said 7),
                         member_value 15 (seen 9 / said 6),
                         deal_citability 6 (seen 4 / said 2),
                         value_protocols 7 (seen 7 — encode-only, no
                           said half at all: agents don't state whether
                           a store "declares UCP" in an answer, so
                           there is nothing to cite)

Composite = a straight sum of pillar points, rescaled onto 100 (or onto
applicable_max when member_value is N/A — Part 4, P4). No blending
layer: v2's 0.6*visibility + 0.4*accessibility composite is gone.

Which half of the stack computes which dimension:
  - agent_access, catalog_context, protocol_feed, value_protocols, and
    the *_seen halves of price_truth/member_value/deal_citability are
    crawl-derived — computed by apps/pipeline/scan/scorer.py from
    fetched page data (T1: same check logic, rescaled onto the new
    seen_max values for the three that carry one over from v3).
  - share_of_mentions, recommendation_strength, and the *_said halves
    are derived from the 24-query coded/metrics data (soa_coded_
    mentions, soa_price_observations via MetricsCalculator) — that
    data doesn't exist inside the crawl-only scan engine, so these are
    computed where the lite report already joins both data sources:
    apps/api/app/services/ pure modules, called from public_lite.py.

Each Dimension additionally carries three free-text detail fields
(what_it_is / how_measured / how_scored) — the methodology section's
expanded-row copy (apps/api/web/src/lite/landing/AnatomyOfAnAnswer.jsx),
mirrored by hand into apps/api/web/src/lite/landing/
scanDimensionsRegistry.js exactly like every other field here (no
codegen bridge; kept in sync by AnatomyOfAnAnswer.test.jsx's parity
assertions). These fields never affect scoring.
"""
from dataclasses import dataclass
from typing import Optional, Tuple

from soa_shared.constants import QUERY_STAGES

SCORER_VERSION = "4"

# ── Lite study query count (Part 4, Q4) ─────────────────────────────────
# The ONE constant every lite surface (worker, evidence copy, report
# stamps, the manifest, landing copy) reads instead of a literal query
# count — grep-kill every literal "12"/"24" in lite code and copy.
LITE_QUERIES_PER_STAGE = 6
LITE_QUERY_COUNT = LITE_QUERIES_PER_STAGE * len(QUERY_STAGES)

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

# Count bands (deal_citability.said) — Stage 25 (Part 4, Q3): recalibrated
# for the 24-query study's doubled purchase-intent opportunity set (12
# queries, up from 6). 0 -> 0%; exactly 1 -> 40%; 2-3 -> 70%; 4+ -> 100%
# of the sub-lens's max.
COUNT_BAND_TABLE: Tuple[Tuple[Optional[int], float], ...] = (
    (0, 0.0),
    (1, 0.40),
    (3, 0.70),
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
    # Stage 25 (Part 1, R1): free-text methodology-section copy — never
    # consumed by scoring, only by the landing page's detail panel.
    what_it_is: str = ""
    how_measured: Tuple[str, ...] = ()
    how_scored: str = ""

    @property
    def has_seen_said_split(self) -> bool:
        return self.seen_max is not None and self.said_max is not None


DIMENSIONS: Tuple[Dimension, ...] = (
    Dimension(
        code="share_of_mentions", name="Share of Mentions",
        pillar=PILLAR_VISIBILITY, weight=25,
        what_it_is="Your share of every brand mention across the answers.",
        how_measured=(
            f"{LITE_QUERY_COUNT} shopper questions on ChatGPT",
            "every brand mention coded",
            "your mentions vs the field",
        ),
        how_scored="Linear — half of all mentions earns full marks.",
    ),
    Dimension(
        code="recommendation_strength", name="Recommendation Strength",
        pillar=PILLAR_VISIBILITY, weight=15,
        what_it_is="How you're mentioned — the pick, or one of a list.",
        how_measured=(
            "position in the answer",
            "endorsement language",
        ),
        how_scored="Banded from mention position and strength.",
    ),
    Dimension(
        code="agent_access", name="Agent Access",
        pillar=PILLAR_ACCESSIBILITY, weight=6,
        what_it_is="Can agents get in at all.",
        how_measured=(
            "robots.txt allows product paths",
            "no bot-blocks",
            "sitemap resolves",
        ),
        how_scored="Pass/fail checks, summed.",
    ),
    Dimension(
        code="catalog_context", name="Catalog & Context",
        pillar=PILLAR_ACCESSIBILITY, weight=8,
        what_it_is="Can agents parse what you sell.",
        how_measured=(
            "Product + Offer structured data on product pages",
            "name, price, availability complete",
            "GTIN/brand identifiers consistent",
        ),
        how_scored="Share of sampled pages passing; identifiers weighted.",
    ),
    Dimension(
        code="protocol_feed", name="Protocol & Feed Presence",
        pillar=PILLAR_ACCESSIBILITY, weight=6,
        what_it_is="Are you present on the channels agents query.",
        how_measured=(
            "llms.txt",
            "MCP declaration",
            "a UCP profile exists",
        ),
        how_scored="Presence checks; feed participation is verified in the full analysis.",
    ),
    Dimension(
        code="price_truth", name="Price Truth",
        pillar=PILLAR_TRUE_VALUE, weight=12,
        seen_max=5, said_max=7,
        said_opportunity_set=OPPORTUNITY_SET_ALL_MENTIONS,
        said_band_type=BAND_TYPE_RATE,
        what_it_is="Can agents state your real price.",
        how_measured=(
            "machine-readable price and currency on offers",
            "promotions as data, not banner images",
            "the structured price agrees with the price on the page",
        ),
        how_scored="Encoding checks plus how often answers that name you state your price. A price behind sign-in doesn't exist to an agent.",
    ),
    Dimension(
        code="member_value", name="Member Value",
        pillar=PILLAR_TRUE_VALUE, weight=15,
        seen_max=9, said_max=6,
        said_opportunity_set=OPPORTUNITY_SET_PURCHASE_INTENT,
        said_band_type=BAND_TYPE_RATE,
        what_it_is="Can agents see what members get — and do they say it.",
        how_measured=(
            "a loyalty page agents can find and read",
            "member prices attached to product offers",
            "markup valid enough that strict parsers keep it",
        ),
        how_scored="Encoding checks plus how often answers credit you with member value. Skipped and rescaled only when no program exists.",
    ),
    Dimension(
        code="deal_citability", name="Deal Citability",
        pillar=PILLAR_TRUE_VALUE, weight=6,
        seen_max=4, said_max=2,
        said_opportunity_set=OPPORTUNITY_SET_PURCHASE_INTENT,
        said_band_type=BAND_TYPE_COUNT,
        what_it_is="Do live promotions survive into answers.",
        how_measured=(
            "deals in markup that are concrete (amount stated)",
            "active (validity date, not expired)",
            "actionable (eligibility or code readable)",
        ),
        how_scored="Encoding checks plus deal citations on purchase-intent questions. No published deals scores zero, not exempt.",
    ),
    Dimension(
        code="value_protocols", name="Value Protocols",
        pillar=PILLAR_TRUE_VALUE, weight=7,
        # Encode-only: a seen half (crawl-derived declaration checks)
        # with NO said half at all — agents don't state in an answer
        # whether a store "declares" a checkout protocol, so there is
        # nothing to cite (Part 3, V1; Part 6, A1's single-wing render).
        seen_max=7, said_max=None,
        what_it_is="Can your value execute inside agent checkout — not just be described.",
        how_measured=(
            "UCP discount capability declared",
            "loyalty or member extension declared",
            "ACP promotions declared",
            "declared versions current and schemas resolving",
        ),
        how_scored="Declaration checks — we score what a store declares, the full analysis verifies what works. This one doesn't appear in the sentence — it executes at checkout.",
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
    (returns weight) for dimensions with no seen/said split at all —
    including Stage 25's value_protocols, which has a seen half but no
    said half, so said_na is meaningless for it and this correctly
    falls through to returning the full weight unconditionally.
    """
    if not dimension.has_seen_said_split:
        return dimension.weight
    return dimension.seen_max if said_na else dimension.weight


# ── Composite (Stage 16, Part 4 P4 / Part 7 A3) ─────────────────────────

def applicable_max(member_value_na: bool) -> float:
    """
    TOTAL_MAX (100), or TOTAL_MAX minus member_value's full weight when
    member_value is N/A (Part 4, P4 — Visibility 40 + Accessibility 20
    + Price Truth 12 + Deal Citability 6 + Value Protocols 7 = 85) —
    derived from the registry weights, never hard-coded, so a weight
    change moves this number automatically (see the perturbation test).
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


# ── Verdict gate (Stage 25, Part 5, G1) ─────────────────────────────────
# A pass/fail gate, deliberately independent of the composite's straight-
# sum weighting: interpretability is the point of a plain sum, so the
# JUDGMENT ("is this store actually agent-ready?") lives here instead —
# a high composite built entirely on Visibility with zero True Value
# still reads NOT AGENT-READY. Both thresholds are registry-defined so
# they move together with any future rebalancing, never hard-coded at
# the call site.
VERDICT_COMPOSITE_THRESHOLD = 60
VERDICT_TRUE_VALUE_RATIO_THRESHOLD = 0.25

VERDICT_AGENT_READY = "AGENT-READY"
VERDICT_NOT_AGENT_READY = "NOT AGENT-READY"


def compute_verdict(composite: float, true_value_earned: float, true_value_applicable_max: float) -> str:
    """
    VERDICT_AGENT_READY requires BOTH: composite >= VERDICT_COMPOSITE_
    THRESHOLD AND true_value_earned / true_value_applicable_max >=
    VERDICT_TRUE_VALUE_RATIO_THRESHOLD. true_value_applicable_max <= 0
    (should not happen in practice — True Value always has at least
    Price Truth + Deal Citability + Value Protocols applicable) is
    treated as a failing ratio, never a division error.
    """
    if composite is None or composite < VERDICT_COMPOSITE_THRESHOLD:
        return VERDICT_NOT_AGENT_READY
    if not true_value_applicable_max or true_value_applicable_max <= 0:
        return VERDICT_NOT_AGENT_READY
    tv_ratio = (true_value_earned or 0.0) / true_value_applicable_max
    if tv_ratio < VERDICT_TRUE_VALUE_RATIO_THRESHOLD:
        return VERDICT_NOT_AGENT_READY
    return VERDICT_AGENT_READY
