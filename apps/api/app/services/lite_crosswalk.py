"""
lite_crosswalk.py — deterministic linker from a SoA Lite report's
query-level signals (for the PRIMARY entity only) to Agent Scan
dimension codes.

Pure function: no DB access, no LLM calls. apps/api/app/routers/
public_lite.py queries soa_runs/soa_queries/soa_coded_mentions/
soa_price_observations for the cycle, shapes the results into
RunSignal objects, and calls link_dimensions() alongside the scan's
already-computed dimension scores.
"""
from dataclasses import dataclass
from typing import Dict

RESEARCH_COMPARISON_STAGES = ("Research", "Comparison")
LOYALTY_DEAL_TYPES = {"loyalty_points", "member_price"}

ABSENCE_THRESHOLD = 0.5   # >= 50% of research+comparison queries absent
GAP_THRESHOLD = 0.5       # scan dimension scoring below 50% of its max counts as "gap"


@dataclass
class RunSignal:
    """One successful run's coded outcome, primary entity always in
    scope and a competitor's outcome included only when this cycle has
    one mentioned in this run."""
    stage: str
    primary_mentioned: bool = False
    primary_deal_cited: bool = False
    primary_deal_types: tuple = ()
    primary_price_quoted: bool = False           # any stated/net price observed for primary
    primary_member_price_claimed: bool = False
    primary_member_value_cited: bool = False      # Stage 16 (Part 5): soa_coded_mentions.member_value_cited
    competitor_mentioned: bool = False
    competitor_deal_cited: bool = False


def _dimension_gap_below_half(scan_dimensions: Dict[str, dict], code: str) -> bool:
    """
    Stage 10 (A3): a dimension marked coverage='na' can never be "gapped"
    — it's excluded from scoring entirely, not scored low, so V2/V3-
    linking rules must treat it as "cannot link" rather than reading its
    (nominal, non-excluded) max/score as a real deficiency.
    """
    dim = scan_dimensions.get(code)
    if not dim or not dim.get("max"):
        return False
    if dim.get("coverage") == "na":
        return False
    return dim.get("score", 0) < GAP_THRESHOLD * dim["max"]


def link_dimensions(run_signals: list, scan_dimensions: Dict[str, dict]) -> Dict[str, str]:
    """
    Returns {dimension_code: reason} for every dimension linked by at
    least one rule. Deterministic — same inputs always produce the same
    output. run_signals: list[RunSignal]. scan_dimensions: the
    ScanResult.dimensions dict ({code: {"score", "max", ...}}).
    """
    linked: Dict[str, str] = {}

    # The rule still computes over stage-tagged run_signals (funnel stage
    # data is legitimate server-side signal) — only the emitted display
    # string is de-staged, since linked reasons surface in the public
    # report and per-stage detail is now paid-diagnostic material.
    research_comparison = [r for r in run_signals if r.stage in RESEARCH_COMPARISON_STAGES]
    if research_comparison:
        absent_count = sum(1 for r in research_comparison if not r.primary_mentioned)
        if (absent_count / len(research_comparison)) >= ABSENCE_THRESHOLD:
            linked.setdefault("F1", "absent from most answers")
            linked.setdefault("F2", "absent from most answers")

    mentioned_runs = [r for r in run_signals if r.primary_mentioned]
    if mentioned_runs and not any(r.primary_price_quoted for r in mentioned_runs):
        linked.setdefault("V1", "mentioned but no price surfaced")

    if any(r.primary_price_quoted for r in run_signals) and _dimension_gap_below_half(scan_dimensions, "V3"):
        linked.setdefault("V3", "list price quoted")

    loyalty_mentioned = any(
        r.primary_member_price_claimed or bool(LOYALTY_DEAL_TYPES.intersection(r.primary_deal_types))
        for r in run_signals
    )
    # "never mentioned" is a negative condition — vacuously true with zero
    # runs, so it must require at least one run to actually judge, same as
    # every other rule here reasoning over "in any answer".
    if run_signals and not loyalty_mentioned and _dimension_gap_below_half(scan_dimensions, "V2"):
        linked.setdefault("V2", "loyalty program never mentioned")

    any_competitor_deal = any(r.competitor_mentioned and r.competitor_deal_cited for r in run_signals)
    primary_never_deal = not any(r.primary_deal_cited for r in run_signals)
    if any_competitor_deal and primary_never_deal:
        linked.setdefault("V4", "competitor cited with deal, primary never is")
        linked.setdefault("V5", "competitor cited with deal, primary never is")

    return linked


TRAILING_RIVAL_THRESHOLD = 25  # points; primary must trail EVERY rival with a defined rate by at least this much
ZERO_RATE_MIN_MENTIONS = 2     # a rate of 0 with only 1 mention is too thin a sample to link


def link_incentive_citation(incentive_citation: list, scan_dimensions: Dict[str, dict]) -> Dict[str, str]:
    """
    Stage 8 (A4): the primary's incentive-citation rate is 0 (with
    ZERO_RATE_MIN_MENTIONS+ mentions) — or trails every rival that has a
    defined rate by TRAILING_RIVAL_THRESHOLD+ points — AND the scan's V2
    or V3 dimension is scoring below half its max -> link the
    lower-scoring of V2/V3. Returns at most one {code: reason} entry, in
    the same {dimension_code: reason} shape as link_dimensions() so the
    caller can merge them (see apps/api/app/routers/public_lite.py).

    incentive_citation: the same list serialized into the public
    payload (apps/api/app/services/lite_incentive_citation.py's output:
    [{entity, is_primary, mentions, cited_answers, rate_pct}, ...]) —
    reused, not recomputed. Rivals with rate_pct=None (zero mentions)
    are excluded from the "every rival" trailing check — an undefined
    rate can't be "beaten by 25 points".
    """
    primary = next((e for e in incentive_citation if e.get("is_primary")), None)
    if not primary or primary.get("rate_pct") is None:
        return {}

    rivals_with_rate = [
        e for e in incentive_citation if not e.get("is_primary") and e.get("rate_pct") is not None
    ]

    zero_condition = primary["rate_pct"] == 0 and primary["mentions"] >= ZERO_RATE_MIN_MENTIONS
    trailing_condition = bool(rivals_with_rate) and all(
        r["rate_pct"] >= primary["rate_pct"] + TRAILING_RIVAL_THRESHOLD for r in rivals_with_rate
    )
    if not (zero_condition or trailing_condition):
        return {}

    v2_gap = _dimension_gap_below_half(scan_dimensions, "V2")
    v3_gap = _dimension_gap_below_half(scan_dimensions, "V3")
    if not (v2_gap or v3_gap):
        return {}

    candidates = [code for code, has_gap in (("V2", v2_gap), ("V3", v3_gap)) if has_gap]
    # Lower-scoring of the two — deterministic tiebreak by code when scores tie.
    target = min(candidates, key=lambda c: (scan_dimensions.get(c, {}).get("score", 0), c))

    reason = "value never cited" if zero_condition else "value rarely cited"
    return {target: reason}
