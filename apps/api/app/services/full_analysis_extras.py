"""
full_analysis_extras.py — Full Analysis coexistence, Phase 4 backend:
the report-copy assembly layer cycle_scoring_full.py's own docstring
anticipated ("checks[]/fixes/exposure_reasons... built on top of this
function's output, not duplicated into it"). Everything here is built
ON TOP of build_full_cycle_report's pillars/scan output — nothing here
re-scores anything; every number is a group-by or a lookup over rows
soa_shared/scan_dimensions.py, lite_pillars.py, or the crawl already
produced.

Platform-crawler mapping note: apps/pipeline/scan/agent_access_matrix.
py's AGENT_CRAWLERS (user_agent -> platform) is pipeline-only code —
apps/api never imports apps/pipeline. This module doesn't need to: the
agent-access MATRIX RESULT (not the mapping code) is already stored,
computed once at crawl time, in dimensions_raw['agent_access_matrix']
(same list build_scan_payload already surfaces as PublicLiteScan.
agent_access_matrix) — a plain list of dicts, i.e. DATA, not a shared-
package dependency. _PLATFORM_TO_CRAWLER_AGENT below is the one new,
small, presentation-only mapping this module needs: which crawler
user_agent row in that stored list corresponds to which QUERY platform
(soa_runs.platform's 'chatgpt'/'gemini'/'claude'/'perplexity' values).
"""
from typing import Dict, List, Optional

from sqlalchemy import text

from soa_shared.scan_dimensions import (
    DIMENSIONS_BY_CODE,
    MIN_OPPORTUNITY_SET_MENTIONS,
    PURCHASE_INTENT_STAGES,
)
from app.services.cycle_scoring import decode_json_field
from app.services.cycle_scoring_full import recommendation_strength_band_label
from app.services.lite_visibility import build_visibility_payload

# ─── Platform display + crawler mapping ───────────────────────────────────

# soa_runs.platform's real, DB-constrained value set (ck_soa_runs_platform)
# — 'copilot' is not a real run platform in this system (never offered by
# NewCycleFlow's DEPTH_PRESETS), so it never appears here or in a matrix
# row; a matrix row only ever exists for a platform the cycle actually ran.
PLATFORM_DISPLAY_NAMES = {
    "chatgpt": "ChatGPT",
    "gemini": "Gemini",
    "gemini_grounded": "Gemini (grounded)",
    "claude": "Claude",
    "perplexity": "Perplexity",
}

# Which crawler user_agent (from the stored agent_access_matrix list) best
# represents "can this platform's agent open the page live" for a given
# query platform. OpenAI has three crawler UAs in AGENT_CRAWLERS (GPTBot
# = model training, OAI-SearchBot = search index, ChatGPT-User = on-
# demand user fetches) — ChatGPT-User is the one closest to what a live
# ChatGPT answer actually does, so that's the one this module reads;
# GPTBot/OAI-SearchBot are deliberately not consulted here.
_PLATFORM_TO_CRAWLER_AGENT = {
    "chatgpt": "ChatGPT-User",
    "claude": "ClaudeBot",
    "perplexity": "PerplexityBot",
    "gemini": "Google-Extended",
    "gemini_grounded": "Google-Extended",
}

_AGENT_ACCESS_UNKNOWN = "unknown"


def _envelope(value: Optional[float], numerator: Optional[float], denominator: Optional[float], state: str) -> Dict:
    return {"value": value, "numerator": numerator, "denominator": denominator, "state": state}


def _rate_envelope(numerator: int, denominator: int) -> Dict:
    if denominator < MIN_OPPORTUNITY_SET_MENTIONS:
        return _envelope(None, numerator, denominator, "na")
    if denominator == 0:
        return _envelope(None, numerator, denominator, "not_measured")
    return _envelope(round(100 * numerator / denominator, 1), numerator, denominator, "measured")


def _agent_access_state(agent_access_matrix: Optional[List[dict]], run_platform: str) -> str:
    """
    ADMITTED/BLOCKED/UNKNOWN for one query platform's crawler, read from
    the crawl's own already-computed agent_access_matrix (never a second
    robots.txt evaluation). 'unknown' both when the platform has no
    known crawler UA (e.g. a future platform not yet in AGENT_CRAWLERS)
    and when the crawl itself never resolved robots.txt (the stored
    row's own product_pages='unknown').
    """
    agent_ua = _PLATFORM_TO_CRAWLER_AGENT.get(run_platform)
    if not agent_ua or not agent_access_matrix:
        return _AGENT_ACCESS_UNKNOWN
    row = next((r for r in agent_access_matrix if r.get("agent") == agent_ua), None)
    if not row:
        return _AGENT_ACCESS_UNKNOWN
    return row.get("product_pages") or _AGENT_ACCESS_UNKNOWN


# ─── 1a: platform matrix ───────────────────────────────────────────────────

def _fetch_platform_signals(conn, cycle_id: int, primary_entity_id: int) -> Dict[str, Dict]:
    """
    One row per platform the cycle actually ran (never a fixed 5-row
    list — a platform NewCycleFlow never offered, e.g. 'copilot', simply
    never appears). Every count here is a straight group-by over
    soa_coded_mentions/soa_price_observations/soa_incentive_scores
    joined through soa_runs.platform — no second counting path.
    """
    rows = conn.execute(text("""
        SELECT
          r.platform,
          COUNT(DISTINCT r.id) AS total_runs,
          SUM(CASE WHEN cm.entity_id = :pid AND cm.mentioned THEN 1 ELSE 0 END) AS primary_mentions,
          SUM(CASE WHEN cm.mentioned THEN 1 ELSE 0 END) AS all_mentions,
          SUM(CASE WHEN cm.entity_id = :pid AND cm.mentioned AND cm.strength = 'Primary' THEN 1 ELSE 0 END) AS primary_named_pick
        FROM soa_runs r
        JOIN soa_coded_mentions cm ON cm.run_id = r.id
        WHERE r.cycle_id = :cid AND r.status = 'success'
        GROUP BY r.platform
    """), {"cid": cycle_id, "pid": primary_entity_id}).fetchall()

    signals: Dict[str, Dict] = {}
    for platform, total_runs, primary_mentions, all_mentions, primary_named_pick in rows:
        signals[platform] = {
            "total_runs": total_runs or 0,
            "primary_mentions": primary_mentions or 0,
            "all_mentions": all_mentions or 0,
            "primary_named_pick": primary_named_pick or 0,
        }

    stage_placeholders = ",".join(f":stage{i}" for i in range(len(PURCHASE_INTENT_STAGES)))
    stage_params = {f"stage{i}": s for i, s in enumerate(PURCHASE_INTENT_STAGES)}
    deal_rows = conn.execute(text(f"""
        SELECT
          r.platform,
          SUM(CASE WHEN cm.mentioned THEN 1 ELSE 0 END) AS opportunity_mentions,
          SUM(CASE WHEN cm.mentioned AND cm.deal_cited THEN 1 ELSE 0 END) AS deal_cited_mentions
        FROM soa_runs r
        JOIN soa_queries q ON q.id = r.query_id
        JOIN soa_coded_mentions cm ON cm.run_id = r.id AND cm.entity_id = :pid
        WHERE r.cycle_id = :cid AND r.status = 'success' AND q.stage IN ({stage_placeholders})
        GROUP BY r.platform
    """), {"cid": cycle_id, "pid": primary_entity_id, **stage_params}).fetchall()
    for platform, opp_mentions, deal_cited in deal_rows:
        signals.setdefault(platform, {}).update({
            "deal_opportunity_mentions": opp_mentions or 0,
            "deal_cited_mentions": deal_cited or 0,
        })

    price_rows = conn.execute(text("""
        SELECT r.platform,
               SUM(CASE WHEN s.net_price_accuracy IS NOT NULL THEN 1 ELSE 0 END) AS measured,
               SUM(CASE WHEN s.net_price_accuracy THEN 1 ELSE 0 END) AS accurate
        FROM soa_incentive_scores s
        JOIN soa_runs r ON r.id = s.run_id
        WHERE r.cycle_id = :cid AND s.entity_id = :pid
          AND s.scoring_grain = 'observation' AND s.status = 'scored'
          AND s.measurement_status = 'measured'
        GROUP BY r.platform
    """), {"cid": cycle_id, "pid": primary_entity_id}).fetchall()
    for platform, measured, accurate in price_rows:
        signals.setdefault(platform, {}).update({
            "price_measured": measured or 0,
            "price_accurate": accurate or 0,
        })

    member_rows = conn.execute(text("""
        SELECT r.platform,
               SUM(CASE WHEN cm.member_value_cited THEN 1 ELSE 0 END) AS cited,
               SUM(CASE WHEN cm.member_value_cited AND po.member_price_claimed THEN 1 ELSE 0 END) AS cited_with_price
        FROM soa_runs r
        JOIN soa_coded_mentions cm ON cm.run_id = r.id AND cm.entity_id = :pid
        LEFT JOIN soa_price_observations po ON po.run_id = r.id AND po.entity_id = :pid
        WHERE r.cycle_id = :cid AND r.status = 'success'
        GROUP BY r.platform
    """), {"cid": cycle_id, "pid": primary_entity_id}).fetchall()
    for platform, cited, cited_with_price in member_rows:
        signals.setdefault(platform, {}).update({
            "member_cited": cited or 0,
            "member_cited_with_price": cited_with_price or 0,
        })

    return signals


def build_platform_matrix(conn, cycle_id: int, primary_entity_id: int, dimensions_raw: dict) -> List[Dict]:
    """
    1a: one row per platform the cycle ran — share_of_mentions,
    rec-strength band, agent access (crawl-time matrix, not re-fetched),
    price-truth accuracy (Deal Engine ground truth, soa_incentive_
    scores), deal citability rate, and member-value citation state.
    Every field is a group-by/lookup over stored rows; nothing here is
    estimated or hardcoded.
    """
    signals = _fetch_platform_signals(conn, cycle_id, primary_entity_id)
    agent_access_matrix = dimensions_raw.get("agent_access_matrix")

    matrix = []
    for platform in sorted(signals.keys()):
        s = signals[platform]
        total_runs = s.get("total_runs", 0)
        all_mentions = s.get("all_mentions", 0)
        primary_mentions = s.get("primary_mentions", 0)
        share_of_mentions = _envelope(
            round(100 * primary_mentions / all_mentions, 1) if all_mentions else None,
            primary_mentions, all_mentions,
            "measured" if all_mentions else "not_measured",
        )
        # Rec-strength band, a per-platform proxy built from real per-
        # platform data (soa_coded_mentions.strength/mentioned) — NOT
        # score_recommendation_strength_full's rsi_score, which
        # soa_metrics_results only computes per-overall/per-stage slice,
        # never per-platform. 0 = named/endorsed at least once on this
        # platform, 1 = mentioned but never the named pick, 2 = never
        # mentioned this platform at all.
        if primary_mentions == 0:
            your_band = 2
        elif s.get("primary_named_pick", 0) > 0:
            your_band = 0
        else:
            your_band = 1

        matrix.append({
            "platform": platform,
            "platform_name": PLATFORM_DISPLAY_NAMES.get(platform, platform),
            "total_runs": total_runs,
            "share_of_mentions": share_of_mentions,
            "recommendation_strength_band": recommendation_strength_band_label(your_band),
            "agent_access": _agent_access_state(agent_access_matrix, platform),
            "price_truth_said": _rate_envelope(s.get("price_accurate", 0), s.get("price_measured", 0)),
            "deal_citability": _rate_envelope(s.get("deal_cited_mentions", 0), s.get("deal_opportunity_mentions", 0)),
            "member_value": (
                "cited_with_price" if s.get("member_cited_with_price", 0) > 0
                else "cited_no_price" if s.get("member_cited", 0) > 0
                else "never_cited"
            ),
        })
    return matrix


# ─── 1b: competitor visibility (overall + by_stage) ───────────────────────

def _fetch_stage_visibility_rows(conn, cycle_id: int):
    """
    soa_metrics_results DOES carry slice_type='stage' rows for every
    cycle (cycle_scoring.py's _fetch_metrics_rows deliberately narrows
    to 'overall' only, for the PUBLIC lite endpoint — Stage 7, G1: stage
    data is paid-diagnostic material that must never reach that public
    router). full_analysis.py is authenticated/internal, so it reads
    'stage' rows directly rather than reusing that narrowed helper.
    """
    return conn.execute(text("""
        SELECT e.name, ce.role, mr.slice_value, mr.total_mentions
        FROM soa_metrics_results mr
        JOIN soa_entities e ON e.id = mr.entity_id
        JOIN soa_cycle_entities ce ON ce.cycle_id = mr.cycle_id AND ce.entity_id = mr.entity_id
        WHERE mr.cycle_id = :cid AND mr.slice_type = 'stage'
        ORDER BY mr.slice_value, ce.comparison_code
    """), {"cid": cycle_id}).fetchall()


def build_competitor_set(conn, cycle_id: int, overall_entity_info: Dict[str, Dict], overall_metrics: Dict[str, Dict]) -> Dict:
    """
    1b: per-entity name/is_primary/mentions/share, overall AND per
    funnel stage — reuses lite_visibility.py's already-pure
    build_visibility_payload (same share_of_mentions math lite's
    report uses) once for 'overall' and once per distinct stage value,
    rather than a second share-of-voice formula.
    """
    overall_entities = [
        {
            "name": info["name"], "is_primary": info["role"] == "primary",
            "mentioned_queries": overall_metrics.get(code, {}).get("total_mentions") or 0,
            "total_queries": overall_metrics.get(code, {}).get("total_runs") or 0,
            "mentions": overall_metrics.get(code, {}).get("total_mentions") or 0,
        }
        for code, info in overall_entity_info.items()
    ]
    overall_visibility = build_visibility_payload(overall_entities)

    stage_rows = _fetch_stage_visibility_rows(conn, cycle_id)
    by_stage_raw: Dict[str, List[dict]] = {}
    for name, role, stage, total_mentions in stage_rows:
        by_stage_raw.setdefault(stage, []).append({
            "name": name, "is_primary": role == "primary",
            "mentioned_queries": total_mentions or 0, "total_queries": total_mentions or 0,
            "mentions": total_mentions or 0,
        })

    by_stage = {
        stage: build_visibility_payload(entities)["share_of_mentions"]
        for stage, entities in by_stage_raw.items()
    }

    return {
        "overall": overall_visibility["share_of_mentions"],
        "by_stage": by_stage,
    }


# 1e note: ranked fixes moved to cycle_scoring_full.py::
# _build_full_fixes_section, attached as pillars['fixes'] — discovered,
# while wiring Phase 2, that the shipped FixesTable.jsx reads
# report.pillars.fixes = {visible: [{code, name, fix_human, impact,
# fix_owner}], remaining_count}, not a standalone top-level list. Per
# the "shipped audit report beats the mock" precedence rule, the real
# consuming component's shape wins — this module no longer builds
# fixes at all, so FixesTable can be reused directly with zero forking.


# ─── 1g: evidence exemplar ─────────────────────────────────────────────────

def select_evidence_exemplar(conn, cycle_id: int, primary_entity_id: int) -> Optional[Dict]:
    """
    1g: the single worst-offender coded answer — price-inaccurate AND
    with uncited eligible offers, highest price delta — selected
    deterministically (largest |gap| first, run_id tiebreak) so the
    same cycle always surfaces the same exemplar. None when no run
    qualifies (never a fabricated example).
    """
    rows = conn.execute(text("""
        SELECT
          r.id, r.platform, q.stage, q.persona, q.query_text,
          cm.evidence,
          s.stated_price, s.ground_truth_true_cost,
          s.ground_truth_applied_deals, s.ground_truth_available_deals
        FROM soa_incentive_scores s
        JOIN soa_runs r ON r.id = s.run_id
        JOIN soa_queries q ON q.id = r.query_id
        LEFT JOIN soa_coded_mentions cm ON cm.run_id = r.id AND cm.entity_id = :pid
        WHERE r.cycle_id = :cid AND s.entity_id = :pid
          AND s.scoring_grain = 'observation' AND s.status = 'scored'
          AND s.measurement_status = 'measured'
          AND s.net_price_accuracy = 0
          AND s.stated_price IS NOT NULL AND s.ground_truth_true_cost IS NOT NULL
          AND s.ground_truth_true_cost > 0
    """), {"cid": cycle_id, "pid": primary_entity_id}).fetchall()

    if not rows:
        return None

    def _gap(row):
        stated, truth = row[6], row[7]
        return abs(stated - truth) / truth

    best = max(rows, key=lambda r: (_gap(r), -r[0]))
    (run_id, platform, stage, persona, query_text, mention_evidence,
     stated_price, ground_truth_true_cost, _applied_deals, available_deals) = best
    gap_pct = round(100 * (stated_price - ground_truth_true_cost) / ground_truth_true_cost, 1)
    # ground_truth_available_deals is a JSON column — comes back already
    # decoded via psycopg2, but as a raw string over a plain-text driver
    # (SQLite tests) or a JSON column type without auto-adaptation; same
    # idiom as every other JSON column this codebase reads via raw SQL
    # (decode_json_field, cycle_scoring.py). A bare len() on the raw
    # string would silently count characters, not offers.
    uncited_offers = len(decode_json_field(available_deals, []) or [])

    return {
        "run_id": run_id,
        "platform": platform,
        "stage": stage,
        "persona": persona,
        "query_text": query_text,
        "answer_excerpt": mention_evidence,
        "price_observation": {
            "stated_price": stated_price,
            "ground_truth_true_cost": ground_truth_true_cost,
            "delta_pct": gap_pct,
            "accurate": False,
        },
        "uncited_eligible_offers": uncited_offers,
    }


# ─── 1h: what-if share (optional) ──────────────────────────────────────────

def build_what_if(competitor_set: Dict, primary_entity_id: Optional[int] = None) -> Optional[Dict]:
    """
    1h: the illustrative Ready-to-Buy-stage share extension the audit's
    flat what-if uses, ported to the stage-driven graph — only rendered
    when the Ready to Buy stage has real by_stage data to extend from;
    omitted (never a fabricated hatch) otherwise.
    """
    ready_rows = competitor_set.get("by_stage", {}).get("Ready to Buy")
    if not ready_rows:
        return None
    primary_row = next((r for r in ready_rows if r.get("is_primary")), None)
    if not primary_row:
        return None
    # Same flat extension the audit's what-if uses: a fixed illustrative
    # points-of-share bump, clearly tagged ILLUSTRATIVE — not a forecast,
    # not derived from a second model.
    ILLUSTRATIVE_SHARE_LIFT_PCT = 9.0
    return {
        "stage": "Ready to Buy",
        "current_share_pct": primary_row.get("share_pct"),
        "illustrative_share_pct": round((primary_row.get("share_pct") or 0) + ILLUSTRATIVE_SHARE_LIFT_PCT, 1),
        "illustrative": True,
    }
