"""
cycle_scoring_full.py — Full Analysis coexistence, Phase 3b: full-cycle
scoring under FULL_CYCLE_SCORER_VERSION.

Reuses the SAME pillar/dimension registry (weights, seen/said splits,
opportunity sets) as v5/lite — scan_dimensions.py is not reweighted by
this phase, only extended (FULL_CYCLE_SCORER_VERSION, DEAL_CITABILITY_
RATE_BAND_TABLE). Reuses app/services/lite_pillars.py's already
volume-invariant pure functions wherever they already are one
(score_price_truth_said, score_member_value_said, member_value_
applicable, and every crawl-derived seen-half row — a store's site
doesn't encode more/less structured data because a study ran more
queries against it). Writes NEW code only where lite's own functions
are NOT volume-invariant:

  - deal_citability.said: lite's score_deal_citability_said uses
    apply_count_band/COUNT_BAND_TABLE — a raw citation COUNT calibrated
    for the ~12-query lite purchase-intent volume, which trivially
    saturates at full-cycle volume (routinely hundreds of purchase-
    intent mentions). score_deal_citability_said_full rebands the SAME
    opportunity set as a RATE instead (apply_deal_citability_rate_band).
  - Evidence copy: lite's share_of_mentions/recommendation_strength
    evidence strings hardcode LITE_QUERY_COUNT ("not mentioned in any
    of the {LITE_QUERY_COUNT} queries") — score_share_of_mentions_full/
    score_recommendation_strength_full are the same scoring formula
    with evidence text built from the cycle's own actual total_queries.

Never mutates soa_shared/scan_dimensions.py's v5 tables or lite_pillars.
py's functions — this module is purely additive, a second consumer of
the same registry, not a replacement for the first.
"""
from typing import Dict, List, Optional

from sqlalchemy import text

from soa_shared.scan_dimensions import (
    DIMENSIONS_BY_CODE,
    FULL_CYCLE_SCORER_VERSION,
    MIN_OPPORTUNITY_SET_MENTIONS,
    PURCHASE_INTENT_STAGES,
    apply_deal_citability_rate_band,
    compute_composite,
    compute_verdict,
    dimension_max,
)

from app.services.exposure_reasons import select_exposure_reasons
from app.services.lite_crosswalk import RunSignal
from app.services.lite_pillars import (
    _ACCESSIBILITY_CODES,
    _TRUE_VALUE_SPLIT_CODES,
    _VALUE_PROTOCOLS_CODE,
    _crawl_dim_row,
    _dim_by_code,
    _pillar,
    _sub_lens,
    member_value_applicable,
    score_member_value_said,
    score_price_truth_said,
)
from app.services.cycle_scoring import decode_json_field, _fetch_run_signals, _fetch_metrics_rows
from app.routers.metrics import build_entity_metrics

# ─── Recommendation-strength band labels ──────────────────────────────────
#
# No short label for score_recommendation_strength_full's your_band (0/1/
# 2) exists anywhere in the shipped audit today — _recommendation_
# strength_band (lite_pillars.py) returns a full evidence SENTENCE, and
# the landing page's static scanDimensionsRegistry.js illustrates the
# same 3-rung ladder with its own wording ('1st + endorsed' / 'listed' /
# 'absent'). The platform matrix (1a) needs a short label per row, so
# this reuses that existing vocabulary rather than inventing new copy —
# same band semantics (your_band), just the shortest existing phrasing.
REC_STRENGTH_BAND_LABELS = ("1st + endorsed", "Listed", "Absent")


def recommendation_strength_band_label(your_band: int) -> str:
    return REC_STRENGTH_BAND_LABELS[your_band] if 0 <= your_band < len(REC_STRENGTH_BAND_LABELS) else "Absent"

# ─── Envelope shape (data-structure backlog item 6) ──────────────────────
#
# {value, numerator, denominator, state} — implemented in THIS service's
# output layer only. lite_pillars.py's {earned, max, na, evidence, ...}
# shape is untouched; envelope() below is a presentation-layer wrapper
# the full-cycle report applies on top of the same underlying said-
# sub-lens results, not a second scoring definition.
STATE_MEASURED = "measured"
STATE_NOT_MEASURED = "not_measured"
STATE_NA = "na"


def envelope(value: Optional[float], numerator: Optional[float], denominator: Optional[float], state: str) -> Dict:
    return {"value": value, "numerator": numerator, "denominator": denominator, "state": state}


def said_result_to_envelope(said_result: Dict) -> Dict:
    """
    Wraps a said sub-lens result (score_price_truth_said/score_member_
    value_said/score_deal_citability_said_full's return shape — {earned,
    max, na, evidence, cited, total, ...}) into the envelope shape.
    not_evaluated (Part 1, P4's "predates coding" case) and na (too few
    mentions) both map to state=na — the envelope's job is honest
    measurability, not distinguishing WHY something wasn't measured
    (evidence[0] still carries that detail for copy to read).
    """
    if said_result.get("na"):
        return envelope(None, said_result.get("cited"), said_result.get("total"), STATE_NA)
    total = said_result.get("total")
    if not total:
        return envelope(None, said_result.get("cited"), total, STATE_NOT_MEASURED)
    cited = said_result.get("cited")
    rate_pct = round(100 * cited / total, 1) if total else None
    return envelope(rate_pct, cited, total, STATE_MEASURED)


# ─── Visibility (evidence copy uses real run counts, not LITE_QUERY_COUNT) ──

def score_share_of_mentions_full(som_pct: Optional[float], total_mentions: int, total_queries: int) -> Dict:
    """Same formula as lite_pillars.score_share_of_mentions (points =
    round(min(som_pct, 50) / 50 * weight)) — only the evidence string's
    query count differs (the cycle's own total_queries, not the fixed
    LITE_QUERY_COUNT lite always runs)."""
    weight = DIMENSIONS_BY_CODE["share_of_mentions"].weight
    if not total_mentions or som_pct is None:
        return {
            "code": "share_of_mentions", "earned": 0.0, "max": weight,
            "evidence": [f"not mentioned in any of the {total_queries} queries"],
            "your_value": 0.0,
        }
    capped = min(som_pct, 50.0)
    earned = round(capped / 50.0 * weight)
    return {
        "code": "share_of_mentions", "earned": earned, "max": weight,
        "evidence": [f"{som_pct:.1f}% share of mentions across all tracked brands"],
        "your_value": round(som_pct, 1),
    }


def score_recommendation_strength_full(rsi_score: Optional[float], total_mentions: int, total_queries: int) -> Dict:
    """Same formula as lite_pillars.score_recommendation_strength — only
    the zero-mention evidence string's query count differs."""
    from app.services.lite_pillars import _recommendation_strength_band

    weight = DIMENSIONS_BY_CODE["recommendation_strength"].weight
    if not total_mentions or rsi_score is None:
        return {
            "code": "recommendation_strength", "earned": 0.0, "max": weight,
            "evidence": [f"not mentioned in any of the {total_queries} queries"],
            "your_band": 2,
        }
    raw = (rsi_score + 1.0) / 4.0 * weight
    earned = max(0, min(weight, round(raw)))
    return {
        "code": "recommendation_strength", "earned": earned, "max": weight,
        "evidence": [_recommendation_strength_band(earned / weight if weight else 0)],
        "your_band": 0 if earned >= weight else (1 if earned > 0 else 2),
    }


# ─── True Value: deal_citability.said, rate-banded ───────────────────────

def score_deal_citability_said_full(run_signals: List[RunSignal]) -> Dict:
    """
    Full-cycle counterpart to lite_pillars.score_deal_citability_said —
    SAME opportunity set (purchase-intent-stage mentions of the primary
    entity), SAME MIN_OPPORTUNITY_SET_MENTIONS gate, but bands the
    result as a RATE (apply_deal_citability_rate_band) instead of a raw
    count, so a full cycle's much larger purchase-intent mention volume
    doesn't trivially saturate the count table's 4+-citations-is-max
    ceiling.
    """
    weight = DIMENSIONS_BY_CODE["deal_citability"].said_max
    mentions = [
        s for s in run_signals
        if s.primary_mentioned and s.stage in PURCHASE_INTENT_STAGES
    ]
    total = len(mentions)
    if total < MIN_OPPORTUNITY_SET_MENTIONS:
        return {
            "code": "deal_citability_said", "earned": 0.0, "max": weight, "na": True,
            "evidence": ["fewer than 2 mentions in the relevant opportunity set"],
        }

    cited = sum(1 for s in mentions if s.primary_deal_cited)
    rate_pct = cited / total * 100
    earned = round(apply_deal_citability_rate_band(rate_pct) * weight)
    return {
        "code": "deal_citability_said", "earned": earned, "max": weight, "na": False,
        "evidence": [f"{cited}/{total} purchase-intent mentions ({rate_pct:.0f}%) cited a deal"],
        "your_value": round(rate_pct, 1), "cited": cited, "total": total,
    }


# ─── Pillar/composite assembly ────────────────────────────────────────────
#
# Deliberately a separate assembly from lite_pillars.build_pillars_payload
# rather than a parameterized variant of it (Phase 3, invariant 4: the
# lite path must stay behavior-preserving with zero risk of regression —
# see cycle_scoring.py's Phase 3a extraction and its snapshot-parity
# tests). Reuses that module's small structural helpers (_crawl_dim_row,
# _sub_lens, _pillar, member_value_applicable) and its two already
# volume-invariant said scorers (price_truth, member_value) — only
# deal_citability's said scoring and the visibility dims' evidence text
# are genuinely new here. Skips checks[]/fixes/exposure_reasons — that
# report-copy layer is Phase 4's concern, built on top of this function's
# output, not duplicated into it.

def build_full_cycle_pillars(
    *,
    som_pct: Optional[float],
    rsi_score: Optional[float],
    total_mentions: int,
    total_queries: int,
    crawl_dimensions: Dict[str, dict],
    run_signals: List[RunSignal],
    membership_probe_result: Optional[str],
) -> Dict:
    """
    Full-cycle counterpart to build_pillars_payload — same registry,
    same pillar/dimension structure, envelope-wrapped said sub-lenses
    (data-structure backlog item 6). Returns {"visibility",
    "accessibility", "true_value" (each {score, max, dimensions}),
    "composite", "verdict", "member_value_na", "scorer_version"}.
    """
    som_result = score_share_of_mentions_full(som_pct, total_mentions, total_queries)
    rsi_result = score_recommendation_strength_full(rsi_score, total_mentions, total_queries)
    visibility_earned = som_result["earned"] + rsi_result["earned"]
    visibility_dims = [
        {"code": r["code"], "name": DIMENSIONS_BY_CODE[r["code"]].name, "earned": r["earned"], "max": r["max"],
         "na": False, "evidence": r["evidence"]}
        for r in (som_result, rsi_result)
    ]

    accessibility_earned = 0.0
    accessibility_applicable_max = 0.0
    accessibility_dims = []
    for code in _ACCESSIBILITY_CODES:
        row = _crawl_dim_row(code, crawl_dimensions)
        if not row["na"] and not row["blocked"]:
            accessibility_earned += row["earned"]
            accessibility_applicable_max += row["max"]
        accessibility_dims.append(row)

    said_by_code = {
        "price_truth": score_price_truth_said(run_signals),
        "member_value": score_member_value_said(run_signals),
        "deal_citability": score_deal_citability_said_full(run_signals),
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
        seen_row = _sub_lens(seen.get("score") or 0.0, seen.get("max") or 0.0, (seen.get("coverage") or "full") == "na", seen.get("evidence") or [])
        said_row = _sub_lens(said["earned"], said["max"], said["na"], said.get("evidence") or [], extra=said)
        said_envelope = said_result_to_envelope(said)

        if code == "member_value" and member_value_na:
            true_value_dims.append({
                "code": code, "name": dim.name, "earned": 0.0, "max": 0.0, "na": True,
                "seen": seen_row, "said": said_row, "said_envelope": said_envelope,
            })
            continue

        dim_max = dimension_max(dim, said_na=said["na"])
        earned = (seen.get("score") or 0.0) + (0.0 if said["na"] else said["earned"])
        true_value_earned += earned
        true_value_applicable_max += dim_max
        true_value_dims.append({
            "code": code, "name": dim.name, "earned": earned, "max": dim_max, "na": False,
            "seen": seen_row, "said": said_row, "said_envelope": said_envelope,
        })

    vp_dim = DIMENSIONS_BY_CODE[_VALUE_PROTOCOLS_CODE]
    vp_seen = crawl_dimensions.get(f"{_VALUE_PROTOCOLS_CODE}_seen") or {}
    vp_earned = vp_seen.get("score") or 0.0
    vp_max = dimension_max(vp_dim)
    vp_seen_row = _sub_lens(vp_earned, vp_max, False, vp_seen.get("evidence") or [])
    true_value_earned += vp_earned
    true_value_applicable_max += vp_max
    true_value_dims.append({
        "code": _VALUE_PROTOCOLS_CODE, "name": vp_dim.name, "earned": vp_earned, "max": vp_max,
        "na": False, "seen": vp_seen_row, "said": None,
    })

    total_earned = visibility_earned + accessibility_earned + true_value_earned
    composite = compute_composite(total_earned, member_value_na=member_value_na)
    verdict = compute_verdict(composite, true_value_earned, true_value_applicable_max)

    # Same table-driven exposure reasons lite_pillars.py computes,
    # ported wholesale from its exposure_reasons_ctx construction — the
    # underlying sub-lenses (true_value_dims' seen/said, accessibility_
    # dims, som_result) have the identical shape here, so this is not a
    # second scoring pass, just the same ctx assembled from this
    # function's own already-computed rows.
    exposure_reasons_ctx = {
        "price_truth_seen": _dim_by_code(true_value_dims, "price_truth")["seen"],
        "price_truth_said": _dim_by_code(true_value_dims, "price_truth")["said"],
        "member_value_applicable": not member_value_na,
        "member_value_seen": _dim_by_code(true_value_dims, "member_value")["seen"],
        "member_value_said": _dim_by_code(true_value_dims, "member_value")["said"],
        "deal_citability_seen": _dim_by_code(true_value_dims, "deal_citability")["seen"],
        "deal_citability_said": _dim_by_code(true_value_dims, "deal_citability")["said"],
        "value_protocols": vp_seen_row,
        "catalog_context": _dim_by_code(accessibility_dims, "catalog_context"),
        "agent_access": _dim_by_code(accessibility_dims, "agent_access"),
        "visibility": {
            "earned": som_result["earned"], "max": som_result["max"], "na": False,
            "som_pct": som_pct if som_pct is not None else 0.0, "total_mentions": total_mentions,
        },
    }
    exposure_reasons = select_exposure_reasons(exposure_reasons_ctx)

    return {
        "visibility": _pillar(visibility_earned, DIMENSIONS_BY_CODE["share_of_mentions"].weight + DIMENSIONS_BY_CODE["recommendation_strength"].weight, visibility_dims),
        "accessibility": _pillar(accessibility_earned, accessibility_applicable_max, accessibility_dims),
        "true_value": _pillar(true_value_earned, true_value_applicable_max, true_value_dims),
        "composite": composite,
        "verdict": verdict,
        "member_value_na": member_value_na,
        "scorer_version": FULL_CYCLE_SCORER_VERSION,
        "exposure_reasons": exposure_reasons,
    }


def build_full_cycle_report(conn, cycle_id: int) -> dict:
    """
    Top-level assembly for a Full Analysis report. Fetches its own scan
    row keyed by cycle_id (Phase 1's soa_lite_scan_results.cycle_id,
    Phase 2's launch-crawl always writes a fresh row here) rather than
    lite_request_id — this is the "future full-cycle caller" cycle_
    scoring.py's own docstring anticipates. Render-gate (Phase 4): a
    cycle with no crawl row, or one not yet complete, has nothing to
    score — callers should fall back to the classic MetricsDashboard
    report in that case (see this function's `status` field).
    """
    scan_row = conn.execute(text("""
        SELECT status, total_score, integrity_capped, dimensions, pages_fetched,
               membership_probe, revenue_probe, fetch_probe, input_url
        FROM soa_lite_scan_results
        WHERE cycle_id = :cid
        ORDER BY id DESC
        LIMIT 1
    """), {"cid": cycle_id}).fetchone()

    if not scan_row or scan_row[0] != "complete":
        return {"status": "not_scored", "cycle_id": cycle_id}

    dimensions_raw = decode_json_field(scan_row[3], {})

    rows = _fetch_metrics_rows(conn, cycle_id)
    overall_metrics: Dict = {}
    # comp_code -> {"name", "role"} — the report-copy layer (full_
    # analysis_extras.py, Phase 4) needs this for competitor_set's
    # overall visibility rows; returned below rather than re-queried.
    overall_entity_info: Dict = {}
    primary_code = None
    total_queries = 0
    for row in rows:
        name, comp_code, role = row[1], row[13], row[12]
        if role == "primary":
            primary_code = comp_code
        overall_entity_info[comp_code] = {"name": name, "role": role}
        overall_metrics[comp_code] = build_entity_metrics(row)
        total_queries = max(total_queries, overall_metrics[comp_code].get("total_runs") or 0)

    if primary_code is None:
        return {"status": "not_scored", "cycle_id": cycle_id}

    primary_entity_row = conn.execute(text("""
        SELECT entity_id FROM soa_cycle_entities WHERE cycle_id = :cid AND role = 'primary'
    """), {"cid": cycle_id}).fetchone()
    primary_entity_id = primary_entity_row[0] if primary_entity_row else None
    run_signals = _fetch_run_signals(conn, cycle_id, primary_entity_id) if primary_entity_id is not None else []

    primary_metrics = overall_metrics.get(primary_code) or {}
    membership_probe = decode_json_field(scan_row[5], {})
    revenue_probe = decode_json_field(scan_row[6], {})

    pillars = build_full_cycle_pillars(
        som_pct=primary_metrics.get("som"),
        rsi_score=primary_metrics.get("rsi"),
        total_mentions=primary_metrics.get("total_mentions") or 0,
        total_queries=total_queries,
        crawl_dimensions=dimensions_raw,
        run_signals=run_signals,
        membership_probe_result=membership_probe.get("result"),
    )

    return {
        "status": "complete",
        "cycle_id": cycle_id,
        "pillars": pillars,
        "scorer_version": FULL_CYCLE_SCORER_VERSION,
        "total_queries": total_queries,
        # Report-copy layer inputs (Phase 4, full_analysis_extras.py) —
        # already fetched above for pillars scoring, returned rather
        # than re-queried by the router.
        "dimensions_raw": dimensions_raw,
        "primary_entity_id": primary_entity_id,
        "overall_entity_info": overall_entity_info,
        "overall_metrics": overall_metrics,
        "revenue_estimate_usd": revenue_probe.get("annual_revenue_usd"),
        "pages_fetched": decode_json_field(scan_row[4], []),
        "scan_row": scan_row,
    }
