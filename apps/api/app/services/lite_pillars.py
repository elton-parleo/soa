"""
lite_pillars.py — pure scoring for the v3 Agent Scan dimensions that are
derived from the 12-query coded/metrics data (soa_coded_mentions,
soa_price_observations via MetricsCalculator), not from the crawl.

These dimensions don't exist inside apps/pipeline/scan/scorer.py's
crawl-only engine — that module never sees mention/metrics data — so
they're scored here, where apps/api/app/routers/public_lite.py already
joins both data sources to build the report. Weights/bands/opportunity
sets all come from soa_shared/scan_dimensions.py; nothing here is a
second definition of the rubric.

Pure functions: no DB access. Callers pass in values already fetched
from overall_metrics (the same dict build_entity_metrics produces —
no second counting path, same convention as lite_visibility.py and
lite_incentive_citation.py).
"""
from typing import Dict, List, Optional

from soa_shared.scan_dimensions import (
    DIMENSIONS_BY_CODE,
    MIN_OPPORTUNITY_SET_MENTIONS,
    PILLAR_WEIGHTS,
    PURCHASE_INTENT_STAGES,
    apply_count_band,
    apply_rate_band,
    compute_composite,
    dimension_max,
)

from app.services.lite_crosswalk import LOYALTY_DEAL_TYPES, RunSignal


def score_share_of_mentions(som_pct: Optional[float], total_mentions: int) -> Dict:
    """
    Stage 16 (Part 2, V1): points = round(min(som_pct, 50) / 50 * 25).
    Holding half of all mentions is dominance and earns full marks —
    calibrated and confirmed against real lite-run som distribution
    (median 60%, meaning most runs already clear this cap — the
    dimension is intentionally easy to ace; True Value is where the
    real differentiation lives).

    Zero-mention primary scores 0, not N/A — absence from every answer
    IS the visibility failure this dimension exists to catch (V3).
    """
    weight = DIMENSIONS_BY_CODE["share_of_mentions"].weight
    if not total_mentions or som_pct is None:
        return {
            "code": "share_of_mentions", "earned": 0.0, "max": weight,
            "evidence": ["not mentioned in any of the 12 queries"],
        }
    capped = min(som_pct, 50.0)
    earned = round(capped / 50.0 * weight)
    return {
        "code": "share_of_mentions", "earned": earned, "max": weight,
        "evidence": [f"{som_pct:.1f}% share of mentions across all tracked brands"],
    }


def score_recommendation_strength(rsi_score: Optional[float], total_mentions: int) -> Dict:
    """
    Stage 16 (Part 2, V2): a linear rescale of rsi_score's own bounded
    range [-1, +3] — the same Primary=+3/Positive=+1/Neutral=0/
    Negative=-1 per-mention weights MetricsCalculator already uses —
    onto [0, 15]. No new strength metric invented; this only rescales
    what the calculator computes.

    Zero-mention primary scores 0 (rsi_score is None with zero
    mentions — MetricsCalculator's total_mentions guard — an absence,
    not an undefined/N/A case, per V3).
    """
    weight = DIMENSIONS_BY_CODE["recommendation_strength"].weight
    if not total_mentions or rsi_score is None:
        return {
            "code": "recommendation_strength", "earned": 0.0, "max": weight,
            "evidence": ["not mentioned in any of the 12 queries"],
        }
    raw = (rsi_score + 1.0) / 4.0 * weight
    earned = max(0, min(weight, round(raw)))
    return {
        "code": "recommendation_strength", "earned": earned, "max": weight,
        "evidence": [f"rsi_score {rsi_score:.2f} (scale -1 to +3)"],
    }


# ─── True Value 'said' sub-lenses (Stage 16, Part 3 T2) ──────────────────
#
# Each said sub-lens is a citation-rate/count OUTCOME over the primary
# entity's own mentions — did the answer actually state the thing, not
# just whether the store's pages encode it (that's 'seen', scorer.py).
# All three read the SAME List[RunSignal] the crosswalk already builds
# via public_lite.py::_fetch_run_signals (apps/api/app/services/
# lite_crosswalk.py) — no second query, no second counting path.
#
# <2 mentions in the sub-lens's own opportunity set -> N/A (not zero):
# too thin a sample to judge an outcome, as opposed to V1/V2's zero-
# mention primary case, where absence itself IS the failure being
# measured. Callers rescale the dimension onto its seen half when said
# is N/A (see soa_shared.scan_dimensions.dimension_max).
#
# Stage 7 discipline: PURCHASE_INTENT_STAGES is used only to FILTER
# signals server-side here — no stage name or stage-sliced count is
# ever placed in a returned dict's evidence/keys.

def _na_said_result(code: str, weight: float) -> Dict:
    return {
        "code": code, "earned": 0.0, "max": weight, "na": True,
        "evidence": ["fewer than 2 mentions in the relevant opportunity set"],
    }


def score_price_truth_said(run_signals: List[RunSignal]) -> Dict:
    """
    Opportunity set: all mentions of the primary entity. Citation =
    RunSignal.primary_price_quoted (the same 'any stated/net price
    observed' signal apps/api/app/services/lite_crosswalk.py already
    uses for V1 linking — not a second definition).
    """
    weight = DIMENSIONS_BY_CODE["price_truth"].said_max
    mentions = [s for s in run_signals if s.primary_mentioned]
    total = len(mentions)
    if total < MIN_OPPORTUNITY_SET_MENTIONS:
        return _na_said_result("price_truth_said", weight)

    cited = sum(1 for s in mentions if s.primary_price_quoted)
    rate_pct = cited / total * 100
    earned = round(apply_rate_band(rate_pct) * weight)
    return {
        "code": "price_truth_said", "earned": earned, "max": weight, "na": False,
        "evidence": [f"{cited}/{total} mentions ({rate_pct:.0f}%) cited a price"],
    }


def score_member_value_said(run_signals: List[RunSignal]) -> Dict:
    """
    Opportunity set: purchase-intent-stage mentions of the primary
    entity only (Part 0 Q1 calibration — member-typed citations
    concentrate there). Citation = primary_member_price_claimed OR
    primary_deal_types intersecting LOYALTY_DEAL_TYPES
    (lite_crosswalk.py's own {member_price, loyalty_points} set —
    reused, not redefined) OR primary_member_value_cited (Part 5's
    coding extension — soa_coded_mentions.member_value_cited, a
    broader signal that also catches vague program-existence mentions
    the other two intentionally exclude).
    """
    weight = DIMENSIONS_BY_CODE["member_value"].said_max
    mentions = [
        s for s in run_signals
        if s.primary_mentioned and s.stage in PURCHASE_INTENT_STAGES
    ]
    total = len(mentions)
    if total < MIN_OPPORTUNITY_SET_MENTIONS:
        return _na_said_result("member_value_said", weight)

    cited = sum(
        1 for s in mentions
        if s.primary_member_price_claimed
        or s.primary_member_value_cited
        or (LOYALTY_DEAL_TYPES & set(s.primary_deal_types))
    )
    rate_pct = cited / total * 100
    earned = round(apply_rate_band(rate_pct) * weight)
    return {
        "code": "member_value_said", "earned": earned, "max": weight, "na": False,
        "evidence": [f"{cited}/{total} purchase-intent mentions ({rate_pct:.0f}%) cited member value"],
    }


def score_deal_citability_said(run_signals: List[RunSignal]) -> Dict:
    """
    Opportunity set: purchase-intent-stage mentions of the primary
    entity only (same Part 0 calibration as member_value.said).
    Citation = primary_deal_cited (the same existing field
    deal_citation_rate is built from — not a new definition).
    """
    weight = DIMENSIONS_BY_CODE["deal_citability"].said_max
    mentions = [
        s for s in run_signals
        if s.primary_mentioned and s.stage in PURCHASE_INTENT_STAGES
    ]
    total = len(mentions)
    if total < MIN_OPPORTUNITY_SET_MENTIONS:
        return _na_said_result("deal_citability_said", weight)

    cited = sum(1 for s in mentions if s.primary_deal_cited)
    earned = round(apply_count_band(cited) * weight)
    return {
        "code": "deal_citability_said", "earned": earned, "max": weight, "na": False,
        "evidence": [f"{cited} of {total} purchase-intent mentions cited a deal"],
    }


# ─── member_value applicability (Stage 16, Part 4, P3) ───────────────────

def member_value_applicable(probe_result: Optional[str], seen_score: float) -> bool:
    """
    Whether the member_value dimension is scored at all this scan, vs.
    excluded entirely (N/A, Part 4 P4 — the whole-rubric /81
    normalization already built in soa_shared.scan_dimensions.
    applicable_max/compute_composite, not reimplemented here).

    Applicable when EITHER signal found a program: the membership probe
    said 'yes' (apps/pipeline/generation/membership_probe.py — a single
    out-of-band OpenAI call, metrically invisible), OR the crawl itself
    earned real credit (score_member_value_seen's score > 0 — a
    fetchable loyalty page, program terms, or member-price encoding).
    seen_score alone, NOT coverage, is the right crawl signal here:
    T1's merge (score_member_value_seen) always contributes loyalty-
    surface evidence and so its coverage is never 'na' even with zero
    credit earned (an un-findable loyalty page still scores 0 at
    coverage='full') — 'na' can't distinguish "found nothing" from
    "found something," only score can.

    Only excluded when BOTH come back empty: probe not 'yes' (an
    'unknown' probe result does NOT count as evidence — it's an
    abstention, not a finding) and the crawl earned zero credit. This
    is the case a bare "score 0" would otherwise misrepresent as
    "confirmed no program" when neither source actually confirmed
    anything.
    """
    return probe_result == "yes" or (seen_score or 0) > 0


# ─── Pillar/composite assembly (Stage 16, Part 7) ────────────────────────
#
# build_pillars_payload is the ONE place visibility/accessibility/true_
# value/composite are computed for scorer_version "3" — apps/api/app/
# routers/public_lite.py calls this once per report/teaser request and
# both responses render subsets of the same numbers; there is no second,
# ad-hoc blend anywhere else (Part 7's "ONE composite function").

_ACCESSIBILITY_CODES = ("agent_access", "catalog_context", "protocol_feed")
_TRUE_VALUE_CODES = ("price_truth", "member_value", "deal_citability")


def _crawl_dim_row(code: str, crawl_dimensions: Dict[str, dict]) -> Dict:
    d = crawl_dimensions.get(code) or {}
    coverage = d.get("coverage") or "full"
    return {
        "code": code, "name": DIMENSIONS_BY_CODE[code].name,
        "earned": d.get("score") or 0.0, "max": d.get("max") or 0.0,
        "na": coverage == "na", "evidence": d.get("evidence") or [],
        "seen": None, "said": None,
    }


def _mention_dim_row(result: Dict) -> Dict:
    return {
        "code": result["code"], "name": DIMENSIONS_BY_CODE[result["code"]].name,
        "earned": result["earned"], "max": result["max"],
        "na": False, "evidence": result.get("evidence") or [],
        "seen": None, "said": None,
    }


def _sub_lens(earned: float, max_: float, na: bool, evidence: List[str]) -> Dict:
    return {"earned": earned, "max": max_, "na": na, "evidence": evidence}


def _pillar(earned: float, applicable_max: float, dimensions: List[Dict]) -> Dict:
    score = round(earned / applicable_max * 100) if applicable_max else 0
    return {"score": score, "max": 100.0, "dimensions": dimensions}


def build_pillars_payload(
    *,
    som_pct: Optional[float],
    rsi_score: Optional[float],
    total_mentions: int,
    crawl_dimensions: Dict[str, dict],
    run_signals: List[RunSignal],
    membership_probe_result: Optional[str],
) -> Dict:
    """
    Assembles the full v3 pillar/composite payload from already-fetched
    primitives — no DB access. crawl_dimensions is the scan row's
    decoded `dimensions` dict (engine.py's output: agent_access,
    catalog_context, protocol_feed, price_truth_seen, member_value_seen,
    deal_citability_seen, each {score, max, coverage, evidence, ...}).
    run_signals is the same List[RunSignal] the crosswalk already builds
    (apps/api/app/routers/public_lite.py::_fetch_run_signals) — no
    second query.

    Returns {"visibility", "accessibility", "true_value" (each a
    {score, max, dimensions}), "composite", "member_value_na"}.
    """
    # ── Visibility: share_of_mentions + recommendation_strength ──
    som_result = score_share_of_mentions(som_pct, total_mentions)
    rsi_result = score_recommendation_strength(rsi_score, total_mentions)
    visibility_earned = som_result["earned"] + rsi_result["earned"]
    visibility_dims = [_mention_dim_row(som_result), _mention_dim_row(rsi_result)]

    # ── Accessibility: agent_access + catalog_context + protocol_feed ──
    # protocol_feed is the only one of the three that can ever go 'na'
    # (brand-only sites, Stage 10 D5); excluded from both sums, not
    # scored as zero, same na-exclusion convention as engine.py's own
    # crawl-only total.
    accessibility_earned = 0.0
    accessibility_applicable_max = 0.0
    accessibility_dims = []
    for code in _ACCESSIBILITY_CODES:
        row = _crawl_dim_row(code, crawl_dimensions)
        if not row["na"]:
            accessibility_earned += row["earned"]
            accessibility_applicable_max += row["max"]
        accessibility_dims.append(row)

    # ── True Value: price_truth, member_value, deal_citability ──
    # Each combines its crawl-derived 'seen' half (engine.py) with its
    # mention-derived 'said' half (scored above) via dimension_max's
    # na-rescale when said's own opportunity set is too thin (T2).
    # member_value additionally has a whole-dimension P3 applicability
    # gate (probe result OR crawl credit) — excluded entirely, not just
    # rescaled onto seen, when neither signal found a program (P4).
    said_by_code = {
        "price_truth": score_price_truth_said(run_signals),
        "member_value": score_member_value_said(run_signals),
        "deal_citability": score_deal_citability_said(run_signals),
    }
    member_value_seen = crawl_dimensions.get("member_value_seen") or {}
    member_value_na = not member_value_applicable(
        membership_probe_result, member_value_seen.get("score") or 0.0,
    )

    true_value_earned = 0.0
    true_value_applicable_max = 0.0
    true_value_dims = []
    for code in _TRUE_VALUE_CODES:
        dim = DIMENSIONS_BY_CODE[code]
        seen = crawl_dimensions.get(f"{code}_seen") or {}
        said = said_by_code[code]
        seen_row = _sub_lens(
            seen.get("score") or 0.0, seen.get("max") or 0.0,
            (seen.get("coverage") or "full") == "na", seen.get("evidence") or [],
        )
        said_row = _sub_lens(said["earned"], said["max"], said["na"], said.get("evidence") or [])

        if code == "member_value" and member_value_na:
            true_value_dims.append({
                "code": code, "name": dim.name, "earned": 0.0, "max": 0.0,
                "na": True, "evidence": [], "seen": seen_row, "said": said_row,
            })
            continue

        dim_max = dimension_max(dim, said_na=said["na"])
        earned = (seen.get("score") or 0.0) + (0.0 if said["na"] else said["earned"])
        true_value_earned += earned
        true_value_applicable_max += dim_max
        true_value_dims.append({
            "code": code, "name": dim.name, "earned": earned, "max": dim_max,
            "na": False, "evidence": [], "seen": seen_row, "said": said_row,
        })

    total_earned = visibility_earned + accessibility_earned + true_value_earned
    composite = compute_composite(total_earned, member_value_na=member_value_na)

    return {
        "visibility": _pillar(visibility_earned, PILLAR_WEIGHTS["visibility"], visibility_dims),
        "accessibility": _pillar(accessibility_earned, accessibility_applicable_max, accessibility_dims),
        "true_value": _pillar(true_value_earned, true_value_applicable_max, true_value_dims),
        "composite": composite,
        "member_value_na": member_value_na,
    }
