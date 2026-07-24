"""
lite_incentive_citation.py — pure shaping of a SoA Lite report's already-
computed deal_citation_rate (soa_metrics_results, 'overall' slice) into
the public visibility_breakdown.incentive_citation array.

Pure function: no DB access. apps/api/app/routers/public_lite.py builds
the `entities` input from the same overall_metrics rows it already
fetches — no second counting path, no coding-layer change (see Stage 8:
the deal_cited rubric and deal_citation_rate formula are frozen; this
module only consumes them).

deal_citation_rate is CONDITIONAL, not unconditional: of the answers
that mention the entity, the share whose mention carried a concrete,
currently-active, attributed incentive per the pass-1 coding rubric
(apps/pipeline/parser/prompts.py, DEAL CITATION RULES — program
existence and permanent policies do NOT qualify). It is null, not 0,
when the entity has zero mentions — an undefined rate, not a zero one.
"""
from typing import Dict, List, Optional


def build_incentive_citation_payload(entities: List[Dict]) -> List[Dict]:
    """
    entities: [{"name": str, "is_primary": bool, "mentions": int,
                "deal_citation_rate_raw": float | None}, ...]

    deal_citation_rate_raw is the UNNORMALIZED 0.0-1.0 value stored to 4
    decimal places in soa_metrics_results.deal_citation_rate (already
    None when the entity has zero mentions — see calculator.py Metric 5's
    total_mentions guard) — NOT app/routers/metrics.py's normalize_metric()
    output, so cited_answers recovers the pipeline's original
    deal_cited_count exactly at lite's <=12-mentions-per-slice scale (see
    test_lite_incentive_citation.py for the rounding-exactness proof).

    Returns entities in the order given — callers pass entity_info's
    already primary-first iteration order (same convention as
    lite_visibility.py), so no re-sorting happens here.
    """
    result = []
    for e in entities:
        raw: Optional[float] = e["deal_citation_rate_raw"]
        has_rate = raw is not None
        result.append({
            "entity": e["name"],
            "is_primary": e["is_primary"],
            "mentions": e["mentions"],
            "cited_answers": round(raw * e["mentions"]) if has_rate else None,
            "rate_pct": round(raw * 100, 1) if has_rate else None,
        })
    return result
