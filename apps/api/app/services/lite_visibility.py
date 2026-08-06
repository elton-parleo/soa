"""
lite_visibility.py — pure shaping of a SoA Lite report's already-computed
entity metrics (soa_metrics_results, 'overall' slice) into the public
visibility_breakdown object (mention_rate + share_of_mentions + totals).

Pure function: no DB access. apps/api/app/routers/public_lite.py builds
the `entities` input from the same overall_metrics dict it already
fetches via app/routers/metrics.py::build_entity_metrics — no second
counting path.

mentioned_queries vs mentions: soa_coded_mentions has a UNIQUE(run_id,
entity_id) constraint and a single boolean `mentioned` column — there is
no data source in this system for "mentioned N times within one answer".
So mentioned_queries (mention_rate's numerator: # of queries whose
answer named the entity at least once) and mentions (share_of_mentions'
numerator: total mention count across all answers) are numerically
identical for every entity today. They are still threaded through as
two independently-named inputs/outputs rather than one shared value, so
the rate and share math can never be silently cross-wired — see
test_lite_visibility.py for a fixture that exercises them as genuinely
different numbers.
"""
from typing import Dict, List


def build_visibility_payload(entities: List[Dict]) -> Dict:
    """
    entities: [{"name": str, "is_primary": bool, "mentioned_queries": int,
                "total_queries": int, "mentions": int, "domain": Optional[str]}, ...]

    Logo feature, Part 2b: domain is optional (absent entries default to
    None via .get below) and additive — it only ever flows onto share_
    of_mentions rows (the SoAIndex table's own rows), not mention_rate,
    since only that table renders a per-entity logo avatar.

    mention_rate[i].rate_pct = mentioned_queries / total_queries * 100
    share_of_mentions[i].share_pct = mentions / sum(all mentions) * 100
      (shares sum to ~100 across every tracked entity, primary + rivals;
      0.0 for every entity when the total is 0 — never NaN/division error)
    totals.total_queries is the plan's query count, read from the first
    entity (every entity in a cycle is evaluated against the same query
    set, so this is uniform in practice).
    """
    total_mentions_all = sum(e["mentions"] for e in entities)
    total_queries = entities[0]["total_queries"] if entities else 0

    mention_rate = [
        {
            "entity": e["name"],
            "is_primary": e["is_primary"],
            "mentioned_queries": e["mentioned_queries"],
            "total_queries": e["total_queries"],
            "rate_pct": (
                round(100 * e["mentioned_queries"] / e["total_queries"], 1)
                if e["total_queries"] else 0.0
            ),
        }
        for e in entities
    ]
    share_of_mentions = [
        {
            "entity": e["name"],
            "is_primary": e["is_primary"],
            "mentions": e["mentions"],
            "share_pct": (
                round(100 * e["mentions"] / total_mentions_all, 1)
                if total_mentions_all else 0.0
            ),
            "domain": e.get("domain"),
        }
        for e in entities
    ]

    return {
        "mention_rate": mention_rate,
        "share_of_mentions": share_of_mentions,
        "totals": {"total_mentions": total_mentions_all, "total_queries": total_queries},
    }
