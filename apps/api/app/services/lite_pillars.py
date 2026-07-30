"""
lite_pillars.py — pure scoring for the v3 Agent Scan dimensions that are
derived from the LITE_QUERY_COUNT-query coded/metrics data
(soa_coded_mentions, soa_price_observations via MetricsCalculator), not
from the crawl.

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
    LITE_QUERY_COUNT,
    MIN_OPPORTUNITY_SET_MENTIONS,
    PILLAR_WEIGHTS,
    PURCHASE_INTENT_STAGES,
    apply_count_band,
    apply_rate_band,
    compute_composite,
    compute_verdict,
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
            "evidence": [f"not mentioned in any of the {LITE_QUERY_COUNT} queries"],
        }
    capped = min(som_pct, 50.0)
    earned = round(capped / 50.0 * weight)
    return {
        "code": "share_of_mentions", "earned": earned, "max": weight,
        "evidence": [f"{som_pct:.1f}% share of mentions across all tracked brands"],
    }


def _recommendation_strength_band(ratio: float) -> str:
    """
    Stage 21 (bug fix 2): plain-language, user-facing line — the raw
    rsi_score and its internal -1..+3 scale must never reach a visitor
    (a grep test over rendered report output asserts neither "rsi" nor
    "scale" ever appears). Banded off the dimension's own earned/max
    ratio, the same number the report already shows the visitor
    alongside this line, not a second, invisible metric.
    """
    if ratio >= 0.75:
        return "Consistently the top pick."
    if ratio >= 0.4:
        return "Often listed, rarely singled out as the pick."
    if ratio > 0:
        return "Mentioned, but rarely recommended outright."
    return "Named, but never actually recommended."


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
            "evidence": [f"not mentioned in any of the {LITE_QUERY_COUNT} queries"],
        }
    raw = (rsi_score + 1.0) / 4.0 * weight
    earned = max(0, min(weight, round(raw)))
    return {
        "code": "recommendation_strength", "earned": earned, "max": weight,
        "evidence": [_recommendation_strength_band(earned / weight if weight else 0)],
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
# The three True Value dimensions with a real seen/said split — Stage 25
# adds a 4th True Value dimension, value_protocols, which is encode-only
# (a seen half, no said half at all) and is therefore built separately,
# after this loop, rather than folded into it (see build_pillars_payload).
_TRUE_VALUE_SPLIT_CODES = ("price_truth", "member_value", "deal_citability")
_VALUE_PROTOCOLS_CODE = "value_protocols"

# Top FREE_FIX_RANK dimensions by opportunity size (max - earned) across
# the combined accessibility + True Value pool keep their fix text; the
# rest are nulled and locked=True — the same top-3-free-by-gap convention
# public_lite.py::_build_scan_payload already uses for v1/v2 rows, now
# the v3 report's only source of fix text (see build_pillars_payload's
# docstring — scan.dimensions is v1/v2-keyed and unusable for a v3 row).
FREE_FIX_RANK = 3


def _rank_and_lock_fixes(dims: List[Dict]) -> None:
    """Mutates dims in place: na rows are never ranked (no fixable gap,
    same as public_lite.py's applicable_codes exclusion); non-na rows
    outside the top FREE_FIX_RANK by gap have their fix nulled and
    locked set — paid-diagnostic fix text never leaves the process for
    a locked dimension."""
    ranked = sorted(
        (d for d in dims if not d["na"]),
        key=lambda d: (-(d["max"] - d["earned"]), d["code"]),
    )
    free_codes = {d["code"] for d in ranked[:FREE_FIX_RANK]}
    for d in dims:
        if d["na"]:
            d["locked"] = False
            continue
        d["locked"] = d["code"] not in free_codes
        if d["locked"]:
            d["fix"] = None


# Part 3 (F1): the free report's ranked-fixes list gives away only the
# top 2 (tightened from the pre-existing FREE_FIX_RANK=3 used above for
# pillars.*.dimensions[].fix/locked, which stays unchanged for rule-6
# back-compat — nothing currently reads it except the fixes list itself,
# which now reads _build_fixes_section's output instead).
FREE_FIX_VISIBLE_RANK = 2


def _build_fixes_section(dims: List[Dict]) -> Dict:
    """
    Builds the report's `fixes` field: {visible: [...], remaining_count}.
    This is a SEPARATE, purely additive payload field from `dims` itself
    — `dims` (accessibility_dims + true_value_dims) keeps carrying every
    dimension's earned/max/evidence unconditionally, because the True
    Value butterfly and Accessibility tiles need real scores for all 6
    dimensions regardless of fix-lock status. Only THIS field enforces
    the "top 2 fixes free, rest is a bare count" rule — ranks beyond
    FREE_FIX_VISIBLE_RANK never have their code/name/impact serialized
    anywhere in it (Part 3's leak test).

    Same ranking rule as _rank_and_lock_fixes (opportunity size, max -
    earned, descending; deterministic tiebreak by code), but additionally
    excludes any dimension with no fix_human at all — a dimension already
    scoring its full max has nothing to fix and must not count toward
    remaining_count or occupy a free slot.
    """
    ranked = sorted(
        (d for d in dims if not d["na"] and d.get("fix_human")),
        key=lambda d: (-(d["max"] - d["earned"]), d["code"]),
    )
    visible = [
        {
            "code": d["code"], "name": d["name"],
            "fix_human": d["fix_human"],
            "impact": round(d["max"] - d["earned"], 1),
        }
        for d in ranked[:FREE_FIX_VISIBLE_RANK]
    ]
    return {
        "visible": visible,
        "remaining_count": max(0, len(ranked) - FREE_FIX_VISIBLE_RANK),
    }


def _crawl_dim_row(code: str, crawl_dimensions: Dict[str, dict]) -> Dict:
    d = crawl_dimensions.get(code) or {}
    coverage = d.get("coverage") or "full"
    return {
        "code": code, "name": DIMENSIONS_BY_CODE[code].name,
        "earned": d.get("score") or 0.0, "max": d.get("max") or 0.0,
        "na": coverage == "na", "evidence": d.get("evidence") or [],
        "seen": None, "said": None,
        "fix": d.get("fix"), "fix_human": d.get("fix_human"), "locked": False,
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
    membership_probe_evidence: Optional[str] = None,
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
    for code in _TRUE_VALUE_SPLIT_CODES:
        dim = DIMENSIONS_BY_CODE[code]
        seen = crawl_dimensions.get(f"{code}_seen") or {}
        said = said_by_code[code]
        seen_row = _sub_lens(
            seen.get("score") or 0.0, seen.get("max") or 0.0,
            (seen.get("coverage") or "full") == "na", seen.get("evidence") or [],
        )
        said_row = _sub_lens(said["earned"], said["max"], said["na"], said.get("evidence") or [])

        if code == "member_value" and member_value_na:
            # Stage 19 (R2): the probe's own verbatim answer, quoted
            # as-is — the report's only evidence for an otherwise
            # silent exclusion. Omitted (not a fabricated "no evidence
            # found") when the probe never ran or returned nothing.
            na_evidence = [f"probe: '{membership_probe_evidence}'"] if membership_probe_evidence else []
            true_value_dims.append({
                "code": code, "name": dim.name, "earned": 0.0, "max": 0.0,
                "na": True, "evidence": na_evidence, "seen": seen_row, "said": said_row,
                "fix": None, "fix_human": None, "locked": False,
            })
            continue

        if code == "member_value" and membership_probe_result == "yes" and not (seen.get("score") or 0):
            # Stage 21 (bug fix 3): the probe found a program but the
            # crawl found no surface to encode it — surface BOTH signals
            # on the applicable path. Stage 19 only threaded the probe's
            # evidence into the na branch above; the applicable path's
            # seen evidence was crawl-only, silently dropping the very
            # signal that made this dimension applicable in the first
            # place.
            probe_note = "program exists (probe) · not discoverable on site"
            seen_row = _sub_lens(
                seen_row["earned"], seen_row["max"], seen_row["na"],
                [probe_note] + seen_row["evidence"],
            )

        dim_max = dimension_max(dim, said_na=said["na"])
        earned = (seen.get("score") or 0.0) + (0.0 if said["na"] else said["earned"])
        true_value_earned += earned
        true_value_applicable_max += dim_max
        true_value_dims.append({
            "code": code, "name": dim.name, "earned": earned, "max": dim_max,
            "na": False, "evidence": [], "seen": seen_row, "said": said_row,
            "fix": seen.get("fix"), "fix_human": seen.get("fix_human"), "locked": False,
        })

    # Value Protocols (Stage 25, Part 1/3): encode-only — a seen half,
    # no said half at all, because an agent's answer has no way to state
    # whether a store "declares" a checkout protocol (Part 6, A1's
    # single-wing butterfly render). Built separately from the loop
    # above rather than folded in: `said` stays a real Python None (not
    # a _sub_lens with na=True), matching the schema's already-optional
    # `said` field, and there is no member_value-style na branch — V1
    # is explicit that absence scores 0, it never excludes this
    # dimension from the pillar the way member_value can be excluded.
    vp_dim = DIMENSIONS_BY_CODE[_VALUE_PROTOCOLS_CODE]
    vp_seen = crawl_dimensions.get(f"{_VALUE_PROTOCOLS_CODE}_seen") or {}
    vp_seen_row = _sub_lens(
        vp_seen.get("score") or 0.0, vp_seen.get("max") or 0.0,
        (vp_seen.get("coverage") or "full") == "na", vp_seen.get("evidence") or [],
    )
    vp_earned = vp_seen.get("score") or 0.0
    vp_max = dimension_max(vp_dim)  # no said/split -> always the full weight
    true_value_earned += vp_earned
    true_value_applicable_max += vp_max
    true_value_dims.append({
        "code": _VALUE_PROTOCOLS_CODE, "name": vp_dim.name, "earned": vp_earned, "max": vp_max,
        "na": False, "evidence": [], "seen": vp_seen_row, "said": None,
        "fix": vp_seen.get("fix"), "fix_human": vp_seen.get("fix_human"), "locked": False,
    })

    # Fix text only exists on the 7 crawl-derived dimensions above
    # (accessibility's 3 + True Value's 4 seen-halves) — visibility's
    # mention-derived dimensions have nothing crawl-fixable to offer, so
    # they're outside the ranking pool entirely (see _rank_and_lock_fixes).
    fixable_dims = accessibility_dims + true_value_dims
    _rank_and_lock_fixes(fixable_dims)
    fixes = _build_fixes_section(fixable_dims)

    total_earned = visibility_earned + accessibility_earned + true_value_earned
    composite = compute_composite(total_earned, member_value_na=member_value_na)

    # Stage 25 (Part 5, G1): the verdict gate — deliberately independent
    # of the composite's straight-sum weighting. Uses True Value's own
    # applicable_max (already na-aware: excludes member_value's weight
    # when it's N/A), so a legitimately program-less store is judged on
    # the value dimensions that actually apply to it, same discipline as
    # the composite's own /85 rescale.
    verdict = compute_verdict(composite, true_value_earned, true_value_applicable_max)

    return {
        "visibility": _pillar(visibility_earned, PILLAR_WEIGHTS["visibility"], visibility_dims),
        "accessibility": _pillar(accessibility_earned, accessibility_applicable_max, accessibility_dims),
        "true_value": _pillar(true_value_earned, true_value_applicable_max, true_value_dims),
        "composite": composite,
        "member_value_na": member_value_na,
        "fixes": fixes,
        "verdict": verdict,
    }
