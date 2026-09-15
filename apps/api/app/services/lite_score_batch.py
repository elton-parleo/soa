"""
lite_score_batch.py — the Agentic Value Score for MANY lite requests at
once, for the internal Audits list (app/routers/lite_requests.py).

Why this exists: app/services/cycle_scoring.py::build_cycle_report is
parameterized by a single cycle_id and issues six queries per call
(metrics, primary entity, and _fetch_run_signals' four). Rendering a
25-row page through it would be 150 round trips. This module issues
the same six queries ONCE for the whole page instead — six per page
rather than six per row, whatever the row count.

What it deliberately does NOT do is re-implement any scoring. The
per-cycle primitives are gathered in bulk here, then handed to the SAME
lite_pillars.build_pillars_payload the public report calls, and the
same composite branching build_cycle_report uses is mirrored below
line-for-line (with the source's own comments cited). The guard against
this mirror drifting is tests/test_lite_score_batch_parity.py, which
runs BOTH paths over every cycle in the report test fixtures and asserts
the composite and all three pillar values are identical. If you change
build_cycle_report's composite branching, that test fails here — fix
both or neither.

cycle_scoring.py itself is untouched by this module: the public report
path (get_lite_report) keeps its exact current behavior, and this
internal, authenticated list is never in that code path.
"""
import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy import bindparam, text

from soa_shared.scan_dimensions import PILLAR_WEIGHTS, SCORER_VERSION
from app.routers.metrics import build_entity_metrics
from app.services.cycle_scoring import FIRST_PILLARS_SCORER_VERSION, decode_json_field
from app.services.lite_crosswalk import RunSignal
from app.services.lite_pillars import build_pillars_payload

log = logging.getLogger(__name__)

# score_state — the five states the Audits list's Score cell renders.
# Deliberately richer than "composite is null": an in-progress row, a
# failed row, a row retired by a scorer_version bump, and a complete row
# whose composite the scorer itself withheld are four genuinely
# different things, and collapsing them into one "—" would hide the
# third and fourth from whoever is triaging the list.
SCORE_AVAILABLE = "available"
SCORE_PENDING = "pending"
SCORE_NOT_MEASURABLE = "not_measurable"
SCORE_EXPIRED = "expired"
SCORE_UNAVAILABLE = "unavailable"

# Mirrors build_cycle_report's own scan-status gates.
_SCORABLE_SCAN_STATUSES = ("complete", "blocked", "failed")

_PILLAR_KEYS = ("visibility", "accessibility", "true_value")


def _expanding(sql: str, ids: List[int]):
    """
    IN-list binding that reads identically against SQLite (tests) and
    Postgres (production) — the same portability constraint
    _fetch_run_signals documents for its own joins, met here with
    SQLAlchemy's expanding bindparam rather than string interpolation.
    """
    return text(sql).bindparams(bindparam("cids", expanding=True)), {"cids": list(ids)}


# ─── Bulk primitive fetches (six queries, page-sized not row-sized) ──────


def _fetch_metrics_rows_batch(conn, cycle_ids: List[int]) -> Dict[int, list]:
    """
    cycle_scoring._fetch_metrics_rows, widened by one column (cycle_id,
    prepended) and one WHERE clause. Column order 0-11 is otherwise
    preserved exactly, because build_entity_metrics reads it
    positionally — see that function's docstring. role/comparison_code/
    website_url stay at the end, shifted by the prepended column.
    """
    stmt, params = _expanding("""
        SELECT
          mr.cycle_id,
          e.slug, e.name, mr.slice_type, mr.slice_value,
          mr.total_runs, mr.total_mentions, mr.mention_rate, mr.soa_pct,
          mr.position_index, mr.rsi_score, mr.deal_citation_rate, mr.platform_dist_index,
          ce.role, ce.comparison_code, e.website_url
        FROM soa_metrics_results mr
        JOIN soa_entities e ON e.id = mr.entity_id
        JOIN soa_cycle_entities ce
          ON ce.cycle_id = mr.cycle_id AND ce.entity_id = mr.entity_id
        WHERE mr.cycle_id IN :cids
          AND mr.slice_type = 'overall'
        ORDER BY ce.comparison_code, mr.slice_value
    """, cycle_ids)

    by_cycle: Dict[int, list] = {}
    for row in conn.execute(stmt, params).fetchall():
        # Strip the prepended cycle_id so each grouped row is byte-
        # identical to what _fetch_metrics_rows hands build_entity_metrics.
        by_cycle.setdefault(row[0], []).append(tuple(row[1:]))
    return by_cycle


def _fetch_primary_entity_ids(conn, cycle_ids: List[int]) -> Dict[int, int]:
    stmt, params = _expanding("""
        SELECT cycle_id, entity_id
        FROM soa_cycle_entities
        WHERE cycle_id IN :cids AND role = 'primary'
    """, cycle_ids)
    return {row[0]: row[1] for row in conn.execute(stmt, params).fetchall()}


def _fetch_run_signals_batch(conn, cycle_ids: List[int]) -> Dict[int, List[RunSignal]]:
    """
    cycle_scoring._fetch_run_signals' four queries, widened across
    cycles. The per-cycle :eid parameter is replaced by a join through
    soa_cycle_entities (role='primary'), which resolves each run's own
    cycle's primary entity — the same entity the single-cycle version
    is handed by its caller, just looked up in-query so one statement
    can span many cycles. Everything else (the success-only filter, the
    separate pass2_coded join that distinguishes "coded, no price
    stated" from "pass 2 never ran", the competitor aggregation) is
    unchanged.
    """
    if not cycle_ids:
        return {}

    stmt, params = _expanding("""
        SELECT r.cycle_id, r.id, q.stage
        FROM soa_runs r
        JOIN soa_queries q ON q.id = r.query_id
        WHERE r.cycle_id IN :cids AND r.status = 'success'
    """, cycle_ids)
    run_rows = conn.execute(stmt, params).fetchall()
    if not run_rows:
        return {}

    stage_by_run: Dict[int, Tuple[int, str]] = {row[1]: (row[0], row[2]) for row in run_rows}

    stmt, params = _expanding("""
        SELECT r.id, cm.mentioned, cm.deal_cited, cm.deal_types, cm.member_value_cited
        FROM soa_runs r
        JOIN soa_cycle_entities pce ON pce.cycle_id = r.cycle_id AND pce.role = 'primary'
        LEFT JOIN soa_coded_mentions cm ON cm.run_id = r.id AND cm.entity_id = pce.entity_id
        WHERE r.cycle_id IN :cids AND r.status = 'success'
    """, cycle_ids)
    primary_by_run = {
        row[0]: (row[1], row[2], row[3], row[4])
        for row in conn.execute(stmt, params).fetchall()
    }

    stmt, params = _expanding("""
        SELECT r.id,
               MAX(CASE WHEN po.stated_price IS NOT NULL OR po.claimed_net_price IS NOT NULL THEN 1 ELSE 0 END),
               MAX(CASE WHEN po.member_price_claimed THEN 1 ELSE 0 END),
               MAX(CASE WHEN log.id IS NOT NULL THEN 1 ELSE 0 END)
        FROM soa_runs r
        JOIN soa_cycle_entities pce ON pce.cycle_id = r.cycle_id AND pce.role = 'primary'
        LEFT JOIN soa_price_observations po ON po.run_id = r.id AND po.entity_id = pce.entity_id
        LEFT JOIN soa_pass2_coding_log log ON log.run_id = r.id AND log.coding_pass_version = 2
        WHERE r.cycle_id IN :cids AND r.status = 'success'
        GROUP BY r.id
    """, cycle_ids)
    price_by_run = {
        row[0]: (bool(row[1]), bool(row[2]), bool(row[3]))
        for row in conn.execute(stmt, params).fetchall()
    }

    stmt, params = _expanding("""
        SELECT r.id,
               MAX(CASE WHEN cm.mentioned THEN 1 ELSE 0 END),
               MAX(CASE WHEN cm.mentioned AND cm.deal_cited THEN 1 ELSE 0 END)
        FROM soa_runs r
        JOIN soa_cycle_entities ce ON ce.cycle_id = r.cycle_id AND ce.role = 'competitor'
        LEFT JOIN soa_coded_mentions cm ON cm.run_id = r.id AND cm.entity_id = ce.entity_id
        WHERE r.cycle_id IN :cids AND r.status = 'success'
        GROUP BY r.id
    """, cycle_ids)
    competitor_by_run = {
        row[0]: (bool(row[1]), bool(row[2]))
        for row in conn.execute(stmt, params).fetchall()
    }

    signals_by_cycle: Dict[int, List[RunSignal]] = {}
    for run_id, (cycle_id, stage) in stage_by_run.items():
        mentioned, deal_cited, deal_types, member_value_cited = primary_by_run.get(
            run_id, (False, False, None, False),
        )
        deal_types = decode_json_field(deal_types, [])
        price_quoted, member_price_claimed, pass2_coded = price_by_run.get(run_id, (False, False, False))
        competitor_mentioned, competitor_deal_cited = competitor_by_run.get(run_id, (False, False))

        signals_by_cycle.setdefault(cycle_id, []).append(RunSignal(
            stage=stage,
            primary_mentioned=bool(mentioned),
            primary_deal_cited=bool(deal_cited),
            primary_deal_types=tuple(deal_types or []),
            primary_price_quoted=price_quoted,
            primary_member_price_claimed=member_price_claimed,
            primary_member_value_cited=bool(member_value_cited),
            pass2_coded=pass2_coded,
            competitor_mentioned=competitor_mentioned,
            competitor_deal_cited=competitor_deal_cited,
        ))
    return signals_by_cycle


# ─── Pillar breakdown ────────────────────────────────────────────────────


def pillar_breakdown(pillars_payload: Optional[dict]) -> Optional[dict]:
    """
    Recovers the raw earned / applicable-max figures behind each
    pillar's normalized 0-100 score, for the drawer's "21 / 32" display.

    build_pillars_payload's _pillar() returns only {score (0-100), max
    (always literally 100), dimensions}; the raw locals it divided are
    not in the payload. They are recoverable from the dimension rows by
    applying the SAME exclusion rule each pillar's own accumulation
    loop used: skip rows flagged na or blocked. Visibility is the one
    exception — _pillar is handed the fixed PILLAR_WEIGHTS['visibility']
    as its denominator rather than a sum over dimensions, so that
    constant is used here too.

    test_lite_score_batch_parity.py asserts the invariant that makes
    this derivation trustworthy: round(earned / applicable_max * 100)
    equals the payload's own score, for every pillar of every fixture.
    """
    if not pillars_payload:
        return None

    out = {}
    for key in _PILLAR_KEYS:
        pillar = pillars_payload.get(key) or {}
        dims = pillar.get("dimensions") or []
        counted = [d for d in dims if not d.get("na") and not d.get("blocked")]
        earned = sum(d.get("earned") or 0.0 for d in counted)
        applicable_max = (
            float(PILLAR_WEIGHTS["visibility"]) if key == "visibility"
            else sum(d.get("max") or 0.0 for d in counted)
        )
        out[key] = {
            "score": pillar.get("score"),
            "earned": round(earned, 2),
            "applicable_max": round(applicable_max, 2),
        }
    return out


# ─── The composite, per cycle ────────────────────────────────────────────


def _score_one(scan_row, metrics_rows: list, primary_entity_id: Optional[int],
               run_signals: List[RunSignal]) -> dict:
    """
    Mirrors build_cycle_report's composite branching exactly, over
    already-fetched primitives. Every comment below cites the decision
    it is reproducing; see this module's docstring for the parity test
    that holds the two in lockstep.
    """
    overall_metrics: dict = {}
    primary_code = None
    for row in metrics_rows:
        role, comp_code = row[12], row[13]
        if role == 'primary':
            primary_code = comp_code
        overall_metrics[comp_code] = build_entity_metrics(row)

    scan_complete = bool(scan_row and scan_row[0] == 'complete')
    scan_scorable = bool(scan_row and scan_row[0] in _SCORABLE_SCAN_STATUSES)
    dimensions_raw = decode_json_field(scan_row[3], {}) if scan_scorable else {}
    scorer_version = dimensions_raw.get('scorer_version') or '1'

    # Re-weighting session (Part 4): a scan scored under an earlier
    # PILLARS-CAPABLE version carries earned points computed against OLD
    # dimension maxes — retired to "expired" rather than re-rendered.
    # Pre-pillars versions ("1"/"2"/"3") were never pillars-shaped and
    # keep using the historical fallback below, unaffected.
    try:
        is_stale_pillars_version = (
            int(scorer_version) >= FIRST_PILLARS_SCORER_VERSION
            and scorer_version != SCORER_VERSION
        )
    except (TypeError, ValueError):
        is_stale_pillars_version = False

    if scan_scorable and is_stale_pillars_version:
        return {
            "composite_score": None,
            "scorer_version": scorer_version,
            "score_state": SCORE_EXPIRED,
            "pillars": None,
        }

    pillars_payload = None
    if scan_scorable and scorer_version == SCORER_VERSION and primary_entity_id is not None:
        primary_metrics = overall_metrics.get(primary_code) or {}
        membership_probe = decode_json_field(scan_row[5], {})
        fetch_probe = decode_json_field(scan_row[7], {}) if scan_row else {}
        pillars_payload = build_pillars_payload(
            som_pct=primary_metrics.get("som"),
            rsi_score=primary_metrics.get("rsi"),
            total_mentions=primary_metrics.get("total_mentions") or 0,
            crawl_dimensions=dimensions_raw,
            run_signals=run_signals,
            membership_probe_result=membership_probe.get("result"),
            membership_probe_evidence=membership_probe.get("raw_evidence"),
            fetch_probe_result=fetch_probe or None,
        )

    if pillars_payload is not None:
        composite = pillars_payload["composite"]
    else:
        # The pre-Stage-16 formula, byte-identical, so historical rows
        # score exactly as the public report scores them.
        visibility = overall_metrics.get(primary_code, {}).get("som") if primary_code else None
        accessibility = scan_row[1] if scan_complete else None
        composite = None
        if visibility is not None:
            composite = (
                round(0.6 * visibility + 0.4 * accessibility)
                if accessibility is not None
                else visibility
            )

    return {
        "composite_score": composite,
        "scorer_version": scorer_version,
        # composite is None at the CURRENT scorer version whenever
        # build_pillars_payload withheld it (state 'composite_withheld'
        # — an accessibility dimension went unmeasured this run — or
        # 'unverified' — a True Value encode wing was blocked). That is
        # a real, honest "we could not score this", distinct from a row
        # that simply has no scan or no primary entity, but both are
        # 'unavailable' to the list; pillars_state below tells them
        # apart in the detail drawer.
        "score_state": SCORE_AVAILABLE if composite is not None else SCORE_UNAVAILABLE,
        "pillars": pillars_payload,
    }


def score_cycles(conn, scan_row_by_cycle_id: Dict[int, tuple]) -> Dict[int, dict]:
    """
    Scores every cycle in scan_row_by_cycle_id with six queries total,
    independent of how many cycles are passed.

    scan_row_by_cycle_id maps cycle_id -> that request's
    soa_lite_scan_results row (or None), in public_lite._fetch_scan_row's
    exact column order: status, total_score, integrity_capped,
    dimensions, pages_fetched, membership_probe, revenue_probe,
    fetch_probe, input_url.

    Returns cycle_id -> {composite_score, scorer_version, score_state,
    pillars}. Callers overlay the request-status-derived states
    (pending / not_measurable) themselves — this function only knows
    about scan and scorer facts.
    """
    cycle_ids = [cid for cid in scan_row_by_cycle_id if cid is not None]
    if not cycle_ids:
        return {}

    metrics_by_cycle = _fetch_metrics_rows_batch(conn, cycle_ids)
    primary_by_cycle = _fetch_primary_entity_ids(conn, cycle_ids)

    # Only cycles that could actually reach build_pillars_payload need
    # run signals — the same `scan_scorable and primary_entity_id is not
    # None` gate build_cycle_report applies before calling
    # _fetch_run_signals, hoisted here so a page of failed or scan-less
    # rows costs nothing.
    signal_cycle_ids = [
        cid for cid in cycle_ids
        if primary_by_cycle.get(cid) is not None
        and (scan_row_by_cycle_id.get(cid) or (None,))[0] in _SCORABLE_SCAN_STATUSES
    ]
    signals_by_cycle = _fetch_run_signals_batch(conn, signal_cycle_ids) if signal_cycle_ids else {}

    out: Dict[int, dict] = {}
    for cycle_id in cycle_ids:
        try:
            out[cycle_id] = _score_one(
                scan_row_by_cycle_id.get(cycle_id),
                metrics_by_cycle.get(cycle_id, []),
                primary_by_cycle.get(cycle_id),
                signals_by_cycle.get(cycle_id, []),
            )
        except Exception:
            # One malformed row must never 500 a whole page of the
            # internal list. Logged loudly, rendered as unavailable.
            log.exception("[lite_score_batch] scoring failed for cycle %s", cycle_id)
            out[cycle_id] = {
                "composite_score": None,
                "scorer_version": None,
                "score_state": SCORE_UNAVAILABLE,
                "pillars": None,
            }
    return out
