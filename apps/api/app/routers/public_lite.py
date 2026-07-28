"""
Public, unauthenticated API for SoA Lite — the marketing-site lead-gen
widget. Mounted at /api/public in app.py WITHOUT the verify_token
dependency the other routers get; nothing in this file may import or
depend on app.auth.

soa_lite_requests.token is the only key a caller ever presents — never
cycle_id, entity_id, organization_id, or the row's own id. Every response
shape here is a PUBLIC CONTRACT the widget depends on directly (see the
docstring block in schemas.py above PublicLiteSubmitRequest).

State machine (written by apps/pipeline/worker.py::process_lite_requests
and _sweep_lite_completions): pending -> identifying_competitors ->
generating -> running -> complete | failed. The full set of valid values
is LITE_STATUSES (soa_shared/models/soa_models.py), enforced by
ck_soa_lite_requests_status. This router only ever reads that machine
(GET endpoints) or performs the two writes visitors are allowed to
trigger themselves: creating a request (POST) and attaching an email to
unlock the report (PATCH) — it never advances the pipeline state itself.
"""
import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from soa_shared.database import engine, session_factory
from soa_shared.models.soa_models import LITE_STATUS_PENDING
from soa_shared.org_helpers import get_or_create_leadgen_org
from app.routers.metrics import build_entity_metrics
from app.services.lite_crosswalk import RunSignal, link_dimensions, link_incentive_citation
from app.services.lite_incentive_citation import build_incentive_citation_payload
from app.services.lite_pillars import build_pillars_payload, member_value_applicable
from app.services.lite_visibility import build_visibility_payload
from app.schemas import (
    EntityMetrics,
    PublicLiteEmailRequest,
    PublicLiteEntityMetrics,
    PublicLiteProgress,
    PublicLiteReportResponse,
    PublicLiteScan,
    PublicLiteScanDimension,
    PublicLiteScanFamily,
    PublicLiteStatusResponse,
    PublicLiteSubmitRequest,
    PublicLiteSubmitResponse,
    PublicLiteTeaserEntity,
    PublicLiteTeaserResponse,
)

log = logging.getLogger(__name__)
router = APIRouter()

CAPTCHA_SECRET = os.getenv("CAPTCHA_SECRET", "")
CAPTCHA_VERIFY_URL = os.getenv("CAPTCHA_VERIFY_URL", "")

RATE_LIMIT_PER_IP_HOUR = 3
RATE_LIMIT_PER_IP_DAY = 10
GLOBAL_RATE_LIMIT_PER_HOUR = 20


# ─── Captcha ─────────────────────────────────────────────────────────────

def _verify_captcha(token: str) -> bool:
    """
    Provider-agnostic: reCAPTCHA (v2/v3), hCaptcha, and Cloudflare Turnstile
    all accept POST {secret, response} and return JSON {success: bool,
    ...} from their siteverify endpoint — point CAPTCHA_VERIFY_URL at
    whichever one is in use. If either env var is unset (e.g. local dev),
    verification is skipped but logged loudly so it's never silently
    bypassed somewhere that matters.
    """
    if not CAPTCHA_SECRET or not CAPTCHA_VERIFY_URL:
        log.warning(
            "[public_lite] CAPTCHA_SECRET/CAPTCHA_VERIFY_URL not set — "
            "skipping captcha verification. This must not happen in production."
        )
        return True
    try:
        resp = httpx.post(
            CAPTCHA_VERIFY_URL,
            data={"secret": CAPTCHA_SECRET, "response": token},
            timeout=10,
        )
        resp.raise_for_status()
        return bool(resp.json().get("success"))
    except Exception as e:
        log.error(f"[public_lite] Captcha verification error: {e}")
        return False


# ─── Rate limiting ───────────────────────────────────────────────────────

def _get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _hash_ip(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()


def _rate_limited(retry_after: int, detail: str) -> HTTPException:
    return HTTPException(
        status_code=429, detail=detail, headers={"Retry-After": str(retry_after)},
    )


def _enforce_rate_limits(conn, ip_hash: str, now: datetime) -> None:
    """
    Cutoffs are computed here in Python and bound as params rather than
    written as `NOW() - INTERVAL '...'` in SQL — avoids app/DB clock-skew
    ambiguity and keeps this portable/testable against SQLite. Counts
    include every row regardless of status: even a failed or still-running
    request already cost a rate-limit slot (and, for anything past
    'generating', real LLM spend).
    """
    hour_count = conn.execute(text("""
        SELECT COUNT(*) FROM soa_lite_requests WHERE ip_hash = :h AND created_at > :cutoff
    """), {"h": ip_hash, "cutoff": now - timedelta(hours=1)}).scalar()
    if hour_count >= RATE_LIMIT_PER_IP_HOUR:
        raise _rate_limited(3600, "Too many SoA Lite requests from this IP — try again in an hour.")

    day_count = conn.execute(text("""
        SELECT COUNT(*) FROM soa_lite_requests WHERE ip_hash = :h AND created_at > :cutoff
    """), {"h": ip_hash, "cutoff": now - timedelta(days=1)}).scalar()
    if day_count >= RATE_LIMIT_PER_IP_DAY:
        raise _rate_limited(86400, "Daily SoA Lite request limit reached for this IP — try again tomorrow.")

    global_count = conn.execute(text("""
        SELECT COUNT(*) FROM soa_lite_requests WHERE created_at > :cutoff
    """), {"cutoff": now - timedelta(hours=1)}).scalar()
    if global_count >= GLOBAL_RATE_LIMIT_PER_HOUR:
        raise _rate_limited(3600, "SoA Lite is at capacity right now — please try again shortly.")


# ─── Phase derivation ────────────────────────────────────────────────────

@dataclass
class _LiveProgressCounts:
    """
    Stage 12 (P1): soa_cycles.completed_runs is written exactly ONCE, at
    the very end of the Runner stage (see RunOrchestrator._finalize_cycle)
    — never incrementally — which is why the status page used to sit at
    "0 of 12" the entire time queries were actually running, then jump
    straight to done. Each of the 12 runs IS persisted individually as it
    completes (RunOrchestrator._upsert_run writes to soa_runs immediately),
    so progress is derived here by counting those rows live instead —
    a pure read, so there's no crash-consistency risk of its own: a
    worker restart mid-phase can't double-count or regress a count that's
    never written incrementally in the first place.
    """
    resolved_runs: int   # success + error + timeout — "attempted", regardless of outcome
    success_runs: int    # only successes are eligible for coding
    coded_runs: int      # distinct soa_runs.id with at least one soa_coded_mentions row


def _fetch_live_progress_counts(conn, cycle_id: int) -> _LiveProgressCounts:
    """SUM(CASE WHEN...) rather than Postgres-only FILTER(WHERE...) so this
    runs identically against SQLite in tests."""
    row = conn.execute(text("""
        SELECT
            SUM(CASE WHEN status IN ('success', 'error', 'timeout') THEN 1 ELSE 0 END),
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END)
        FROM soa_runs WHERE cycle_id = :cid
    """), {"cid": cycle_id}).fetchone()
    resolved_runs = int(row[0] or 0) if row else 0
    success_runs = int(row[1] or 0) if row else 0

    coded_runs = 0
    if success_runs:
        coded_row = conn.execute(text("""
            SELECT COUNT(DISTINCT cm.run_id)
            FROM soa_coded_mentions cm
            JOIN soa_runs r ON r.id = cm.run_id
            WHERE r.cycle_id = :cid
        """), {"cid": cycle_id}).fetchone()
        coded_runs = int(coded_row[0] or 0) if coded_row else 0

    return _LiveProgressCounts(resolved_runs=resolved_runs, success_runs=success_runs, coded_runs=coded_runs)


def _derive_phase(lite_status, cycle_status, total_runs_planned, live_counts: "_LiveProgressCounts | None"):
    """
    Maps (lite_status, cycle_status, total_runs_planned, live_counts) to
    the public phase enum: queued -> generating_queries -> running ->
    coding -> metrics -> complete (or failed at any point). live_counts is
    None whenever there's no cycle yet to count against (see
    _fetch_live_progress_counts) — callers only compute it when cycle_id
    is set. The Agent Scan is intentionally NOT one of these phases: it
    runs in parallel and is already surfaced on its own scan_status field
    (rule 7 — never blocks the report), so folding it into this sequence
    would misrepresent it as a blocking stage.

    Stage 14 (P1): this dispatch is exhaustive over every value in
    LITE_STATUSES (soa_shared/models/soa_models.py) — every non-'running'
    status gets its own explicit branch above, and anything that isn't
    'running' either falls through to the guard just below rather than
    being silently treated as if it were. Before this stage, an
    unmapped status (e.g. 'identifying_competitors' during the window
    where the DB constraint didn't yet allow it) would fall all the way
    through to the cycle-status logic and be guessed at as 'running' —
    logged and safely degraded here instead.

    Returns (phase: str, progress: PublicLiteProgress | None).
    """
    if lite_status == 'pending':
        return 'queued', None
    if lite_status == 'identifying_competitors':
        return 'identifying_competitors', None
    if lite_status == 'generating':
        return 'generating_queries', None
    if lite_status == 'complete':
        return 'complete', None
    if lite_status == 'failed':
        return 'failed', None
    if lite_status != 'running':
        log.error(f"[lite] _derive_phase: unexpected lite_status {lite_status!r} — degrading to 'running'")
        return 'running', None

    # lite_status == 'running' — cycle_id is set; derive from the cycle.
    # cycle_status can briefly lag lite_status right after
    # _sweep_lite_completions runs (same poll loop, but not the same
    # instant) — handled defensively below rather than assumed impossible.
    if cycle_status in (None, 'planned'):
        return 'queued', None
    if cycle_status == 'failed':
        return 'failed', None
    if cycle_status == 'complete':
        return 'complete', None

    if not total_runs_planned or live_counts is None:
        return 'running', None

    progress = PublicLiteProgress(completed_runs=live_counts.resolved_runs, total_runs=total_runs_planned)

    if live_counts.resolved_runs < total_runs_planned:
        return 'running', progress
    if live_counts.success_runs > 0 and live_counts.coded_runs < live_counts.success_runs:
        return 'coding', progress
    # Every resolved run that could be coded, is — either genuinely in
    # Metrics now, or the cycle just hasn't flipped to 'complete' yet
    # (the brief window before _sweep_lite_completions catches up).
    return 'metrics', progress


# ─── Agent Scan shaping ──────────────────────────────────────────────────

# Stage 19 (R4): lite_crosswalk.py still reasons in v1/v2 dimension
# codes (its rules predate the v3 registry) — this maps its output onto
# the v3 dimension a visitor actually sees a chip on. Reflects the same
# conceptual regrouping the v3 registry itself made (V1 Offer
# Legibility -> price_truth; V2 Loyalty Surface + V3 Member Value ->
# member_value; V4 Value Rails + V5 Offer Integrity -> deal_citability;
# F1/F2 map straight across). Not exhaustive over every old code —
# F3 never appears in link_dimensions()' output today.
_CROSSWALK_CODE_TO_V3 = {
    "F1": "agent_access", "F2": "catalog_context",
    "V1": "price_truth", "V2": "member_value", "V3": "member_value",
    "V4": "deal_citability", "V5": "deal_citability",
}


def _attach_v3_linked_reasons(pillars_payload: dict | None, linked: dict) -> None:
    """Mutates pillars_payload in place, adding a {"reason": ...} onto
    the matching v3 dimension row — same {"reason": ...} shape
    _build_scan_payload already puts on v1/v2 rows, so the widget's
    existing chip-rendering logic needs no new shape to handle. Never
    fires on an 'na' dimension (R4) since there's no fixable/citable
    gap to explain there."""
    if not pillars_payload or not linked:
        return
    v3_linked: dict = {}
    for old_code, reason in linked.items():
        v3_code = _CROSSWALK_CODE_TO_V3.get(old_code)
        if v3_code:
            v3_linked.setdefault(v3_code, reason)
    if not v3_linked:
        return
    for pillar_key in ("accessibility", "true_value"):
        for dim in pillars_payload[pillar_key]["dimensions"]:
            if dim["code"] in v3_linked and not dim["na"]:
                dim["linked"] = {"reason": v3_linked[dim["code"]]}


DIMENSION_ORDER = ("F1", "F2", "F3", "V1", "V2", "V3", "V4", "V5")
DIMENSION_NAMES = {
    "F1": "Agent Access",
    "F2": "Catalog Context",
    "F3": "Protocol & Feed Presence",  # was "Transaction Rails" (Stage 10, scorer_version "2")
    "V1": "Offer Legibility",
    "V2": "Loyalty Surface",
    "V3": "Member Value",
    "V4": "Value Rails",
    "V5": "Offer Integrity",
}
FOUNDATION_CODES = {"F1", "F2", "F3"}
FOUNDATION_MAX = 35
VALUE_MAX = 65
FREE_FIX_RANK = 3  # top 3 opportunities (by score gap) get their fix text for free


def _decode_json_field(value, default):
    """JSON columns come back already-decoded via psycopg2; defensively
    handle a driver (or SQLite test) that returns the raw string instead —
    same idiom as worker.py::process_lite_requests."""
    if isinstance(value, str):
        return json.loads(value) if value else default
    return value if value is not None else default


def _fetch_scan_row(conn, lite_request_id: int):
    return conn.execute(text("""
        SELECT status, total_score, integrity_capped, dimensions, pages_fetched, membership_probe
        FROM soa_lite_scan_results
        WHERE lite_request_id = :rid
    """), {"rid": lite_request_id}).fetchone()


def _fetch_run_signals(conn, cycle_id: int, primary_entity_id: int) -> list:
    """
    One RunSignal (apps/api/app/services/lite_crosswalk.py) per successful
    run in the cycle. Every query joins through r.cycle_id/r.id rather
    than an explicit run-id list, so this reads identically against
    SQLite (tests) and Postgres (production) — no IN-list expansion.
    """
    run_rows = conn.execute(text("""
        SELECT r.id, q.stage
        FROM soa_runs r
        JOIN soa_queries q ON q.id = r.query_id
        WHERE r.cycle_id = :cid AND r.status = 'success'
    """), {"cid": cycle_id}).fetchall()
    if not run_rows:
        return []
    stage_by_run = {row[0]: row[1] for row in run_rows}

    primary_rows = conn.execute(text("""
        SELECT r.id, cm.mentioned, cm.deal_cited, cm.deal_types, cm.member_value_cited
        FROM soa_runs r
        LEFT JOIN soa_coded_mentions cm ON cm.run_id = r.id AND cm.entity_id = :eid
        WHERE r.cycle_id = :cid AND r.status = 'success'
    """), {"cid": cycle_id, "eid": primary_entity_id}).fetchall()
    primary_by_run = {row[0]: (row[1], row[2], row[3], row[4]) for row in primary_rows}

    price_rows = conn.execute(text("""
        SELECT r.id,
               MAX(CASE WHEN po.stated_price IS NOT NULL OR po.claimed_net_price IS NOT NULL THEN 1 ELSE 0 END),
               MAX(CASE WHEN po.member_price_claimed THEN 1 ELSE 0 END)
        FROM soa_runs r
        LEFT JOIN soa_price_observations po ON po.run_id = r.id AND po.entity_id = :eid
        WHERE r.cycle_id = :cid AND r.status = 'success'
        GROUP BY r.id
    """), {"cid": cycle_id, "eid": primary_entity_id}).fetchall()
    price_by_run = {row[0]: (bool(row[1]), bool(row[2])) for row in price_rows}

    competitor_rows = conn.execute(text("""
        SELECT r.id,
               MAX(CASE WHEN cm.mentioned THEN 1 ELSE 0 END),
               MAX(CASE WHEN cm.mentioned AND cm.deal_cited THEN 1 ELSE 0 END)
        FROM soa_runs r
        JOIN soa_cycle_entities ce ON ce.cycle_id = r.cycle_id AND ce.role = 'competitor'
        LEFT JOIN soa_coded_mentions cm ON cm.run_id = r.id AND cm.entity_id = ce.entity_id
        WHERE r.cycle_id = :cid AND r.status = 'success'
        GROUP BY r.id
    """), {"cid": cycle_id}).fetchall()
    competitor_by_run = {row[0]: (bool(row[1]), bool(row[2])) for row in competitor_rows}

    signals = []
    for run_id, stage in stage_by_run.items():
        mentioned, deal_cited, deal_types, member_value_cited = primary_by_run.get(
            run_id, (False, False, None, False),
        )
        deal_types = _decode_json_field(deal_types, [])
        price_quoted, member_price_claimed = price_by_run.get(run_id, (False, False))
        competitor_mentioned, competitor_deal_cited = competitor_by_run.get(run_id, (False, False))

        signals.append(RunSignal(
            stage=stage,
            primary_mentioned=bool(mentioned),
            primary_deal_cited=bool(deal_cited),
            primary_deal_types=tuple(deal_types or []),
            primary_price_quoted=price_quoted,
            primary_member_price_claimed=member_price_claimed,
            primary_member_value_cited=bool(member_value_cited),
            competitor_mentioned=competitor_mentioned,
            competitor_deal_cited=competitor_deal_cited,
        ))
    return signals


def _build_scan_payload(scan_row, linked: dict) -> dict | None:
    """
    Shapes one soa_lite_scan_results row into the public 'scan' object.
    Never blocks the report (rule 7): any non-'complete' status — or no
    row at all — degrades to a status-only/absent object rather than
    raising or omitting the honest status badge.

    Stage 10 (A2): a dimension's 'coverage' is 'na' when it's inapplicable
    to this site type (Stage 10 D5) — those dimensions are excluded from
    fix-ranking and from each family's applicable_max entirely, not
    scored as zero. A pre-Stage-10 row has no coverage/deferred_items/
    cap_basis/scorer_version keys at all; every one of those defaults to
    its Stage-1 meaning ('full' coverage, scorer_version "1") so an old
    row renders exactly as it always has, no crash, no stray tags.

    Family `max` stays the nominal 35/65 always (rule 6 — an existing
    field's meaning never changes); `applicable_max` is the new, additive
    ceiling to use instead when something in that family is 'na' (W2).
    subtotal itself is left as the raw sum over applicable dimensions
    (not independently re-projected onto /35) so it always reads
    correctly against whichever denominator the UI chooses.
    """
    if not scan_row:
        return None

    status, total_score, integrity_capped, dimensions, pages_fetched, _membership_probe = scan_row
    pages_fetched = _decode_json_field(pages_fetched, [])

    if status != 'complete':
        return PublicLiteScan(
            status=status,
            total_score=total_score,
            integrity_capped=bool(integrity_capped),
            pages_fetched=pages_fetched,
        ).model_dump()

    dimensions = _decode_json_field(dimensions, {})
    scorer_version = dimensions.get('scorer_version') or '1'

    def _coverage(code: str) -> str:
        return dimensions.get(code, {}).get('coverage') or 'full'

    applicable_codes = [c for c in DIMENSION_ORDER if _coverage(c) != 'na']

    # Rank by opportunity size (max - score) descending — biggest gaps
    # first — deterministic tiebreak by code. 'na' dimensions have no
    # fixable gap and are excluded entirely so they can't crowd a real
    # dimension out of the free top-3 (Stage 10). Only the top
    # FREE_FIX_RANK dimensions' fix text is given away free; the rest
    # are locked.
    ranked_codes = sorted(
        applicable_codes,
        key=lambda code: (
            -(dimensions.get(code, {}).get('max', 0) - dimensions.get(code, {}).get('score', 0)),
            code,
        ),
    )
    rank_by_code = {code: i + 1 for i, code in enumerate(ranked_codes)}

    dim_rows = []
    foundation_subtotal = 0.0
    value_subtotal = 0.0
    foundation_applicable_max = 0.0
    value_applicable_max = 0.0
    for code in DIMENSION_ORDER:
        d = dimensions.get(code, {})
        score = d.get('score', 0)
        max_ = d.get('max', 0)
        fix = d.get('fix')
        evidence = d.get('evidence', [])
        coverage = _coverage(code)
        is_applicable = coverage != 'na'

        rank = rank_by_code.get(code)
        locked = fix is not None and rank is not None and rank > FREE_FIX_RANK
        if locked:
            fix = None

        if is_applicable:
            if code in FOUNDATION_CODES:
                foundation_subtotal += score
                foundation_applicable_max += max_
            else:
                value_subtotal += score
                value_applicable_max += max_

        reason = linked.get(code)
        dim_rows.append(PublicLiteScanDimension(
            code=code,
            name=DIMENSION_NAMES[code],
            score=score,
            max=max_,
            evidence=evidence,
            fix=fix,
            locked=locked,
            linked={"reason": reason} if reason else None,
            coverage=coverage,
            deferred_items=d.get('deferred_items') or [],
            cap_basis=d.get('cap_basis') or [],
        ).model_dump())

    return PublicLiteScan(
        status=status,
        total_score=total_score,
        integrity_capped=bool(integrity_capped),
        scorer_version=scorer_version,
        foundation=PublicLiteScanFamily(
            subtotal=round(foundation_subtotal, 1), max=FOUNDATION_MAX,
            applicable_max=round(foundation_applicable_max, 1),
        ).model_dump(),
        value=PublicLiteScanFamily(
            subtotal=round(value_subtotal, 1), max=VALUE_MAX,
            applicable_max=round(value_applicable_max, 1),
        ).model_dump(),
        dimensions=dim_rows,
        pages_fetched=pages_fetched,
    ).model_dump()


# ─── Report shaping ──────────────────────────────────────────────────────

def _fetch_metrics_rows(conn, cycle_id: int):
    """
    Same column order (indices 0-11) as soa_dashboard_summary, so
    build_entity_metrics (app/routers/metrics.py) works unchanged — see
    that function's docstring. role/comparison_code are appended after,
    used here for grouping/ordering only; comparison_code is never
    returned to the caller.

    Only the 'overall' slice is fetched — per-stage rows are no longer
    assembled into the public payload at all (Stage 7, G1: stage-level
    mention data is paid-diagnostic material and must never reach this
    router's response). soa_metrics_results still has 'stage' rows for
    every cycle; a future internal-only table can query them directly
    without this router touching them.
    """
    return conn.execute(text("""
        SELECT
          e.slug, e.name, mr.slice_type, mr.slice_value,
          mr.total_runs, mr.total_mentions, mr.mention_rate, mr.soa_pct,
          mr.position_index, mr.rsi_score, mr.deal_citation_rate, mr.platform_dist_index,
          ce.role, ce.comparison_code
        FROM soa_metrics_results mr
        JOIN soa_entities e ON e.id = mr.entity_id
        JOIN soa_cycle_entities ce
          ON ce.cycle_id = mr.cycle_id AND ce.entity_id = mr.entity_id
        WHERE mr.cycle_id = :cid
          AND mr.slice_type = 'overall'
        ORDER BY ce.comparison_code, mr.slice_value
    """), {"cid": cycle_id}).fetchall()


def _build_report_payload(conn, lite_request_id: int, cycle_id: int, email: str | None) -> dict:
    rows = _fetch_metrics_rows(conn, cycle_id)

    entity_info: dict = {}    # comparison_code -> {"name":, "role":} (internal grouping key only)
    overall_metrics: dict = {}
    # Stage 8 (A1): the raw, unnormalized 0.0-1.0 deal_citation_rate
    # (row[10]) — kept separate from overall_metrics' *100-normalized
    # copy (build_entity_metrics' 'deal_citation_rate') because
    # lite_incentive_citation.py needs the un-rounded-to-1dp original to
    # recover deal_cited_count exactly. Instrument itself (row[10]'s
    # source column) is unmodified this stage.
    raw_deal_citation_rate: dict = {}
    primary_code = None

    for row in rows:
        name, role, comp_code = row[1], row[12], row[13]
        entity_info.setdefault(comp_code, {"name": name, "role": role})
        if role == 'primary':
            primary_code = comp_code
        overall_metrics[comp_code] = build_entity_metrics(row)
        raw_deal_citation_rate[comp_code] = row[10]

    scan_row = _fetch_scan_row(conn, lite_request_id)
    scan_status = scan_row[0] if scan_row else None
    scan_complete = bool(scan_row and scan_row[0] == 'complete')
    dimensions_raw = _decode_json_field(scan_row[3], {}) if scan_complete else {}
    scorer_version = dimensions_raw.get('scorer_version') or '1'

    # Stage 13 (W4/W5): drives the widget's solo-comparison fallback and
    # the "auto-selected by ChatGPT" methodology stamp.
    competitor_source_row = conn.execute(text("""
        SELECT competitor_source FROM soa_lite_requests WHERE id = :rid
    """), {"rid": lite_request_id}).fetchone()
    competitor_source = competitor_source_row[0] if competitor_source_row else None

    # Stage 16 (Part 7): primary_entity_id/run_signals are fetched once,
    # ahead of the teaser/report branch, because BOTH need them for a
    # scorer_version "3" pillars computation (not just the crosswalk
    # 'linked' step below, which reuses the same run_signals — no
    # second query).
    primary_entity_id = None
    if primary_code:
        primary_entity_row = conn.execute(text("""
            SELECT entity_id FROM soa_cycle_entities WHERE cycle_id = :cid AND role = 'primary'
        """), {"cid": cycle_id}).fetchone()
        primary_entity_id = primary_entity_row[0] if primary_entity_row else None

    run_signals: list = []
    if scan_complete and primary_entity_id is not None:
        run_signals = _fetch_run_signals(conn, cycle_id, primary_entity_id)

    # Stage 16 (Part 7): the ONE composite function — a scorer_version
    # "3" scan computes visibility/accessibility/composite from the
    # registry-driven pillars breakdown (build_pillars_payload); every
    # other case (older scan, no scan, no primary entity) falls back to
    # the pre-Stage-16 formula byte-identically, so historical rows keep
    # rendering exactly as they always have (Stage 10 W6 precedent).
    pillars_payload = None
    if scan_complete and scorer_version == "3" and primary_entity_id is not None:
        primary_metrics = overall_metrics.get(primary_code) or {}
        membership_probe = _decode_json_field(scan_row[5], {})
        pillars_payload = build_pillars_payload(
            som_pct=primary_metrics.get("som"),
            rsi_score=primary_metrics.get("rsi"),
            total_mentions=primary_metrics.get("total_mentions") or 0,
            crawl_dimensions=dimensions_raw,
            run_signals=run_signals,
            membership_probe_result=membership_probe.get("result"),
            membership_probe_evidence=membership_probe.get("raw_evidence"),
        )

    if pillars_payload is not None:
        visibility = pillars_payload["visibility"]["score"]
        accessibility = pillars_payload["accessibility"]["score"]
        composite = pillars_payload["composite"]
    else:
        # visibility reuses the same share-of-voice metric already
        # computed for the report (build_entity_metrics' 'som') — no
        # second metrics path. Already stage-agnostic (only ever reads
        # the 'overall' slice), so no rebasing was needed for Stage 7 (A2).
        visibility = overall_metrics.get(primary_code, {}).get("som") if primary_code else None
        accessibility = scan_row[1] if scan_complete else None
        composite = None
        if visibility is not None:
            composite = (
                round(0.6 * visibility + 0.4 * accessibility)
                if accessibility is not None
                else visibility
            )

    if not email:
        overall = [
            PublicLiteTeaserEntity(
                name=info["name"],
                role=info["role"],
                som=overall_metrics.get(code, {}).get("som"),
            ).model_dump()
            for code, info in entity_info.items()
        ]
        return PublicLiteTeaserResponse(
            status="complete", locked=True, overall=overall,
            visibility=visibility, accessibility=accessibility, composite=composite,
            scan_status=scan_status, competitor_source=competitor_source,
            scorer_version=scorer_version,
        ).model_dump()

    overall = [
        PublicLiteEntityMetrics(
            name=info["name"],
            role=info["role"],
            metrics=EntityMetrics(**overall_metrics.get(code, {})),
        ).model_dump()
        for code, info in entity_info.items()
    ]

    # Stage 7 (A1): reshapes the SAME overall_metrics values already
    # built above — mentioned_queries/mentions both read total_mentions
    # (mention_rate's numerator and share_of_mentions' numerator are the
    # same count in this system; see lite_visibility.py's docstring) —
    # no second counting path.
    visibility_entities = [
        {
            "name": info["name"],
            "is_primary": info["role"] == "primary",
            "mentioned_queries": overall_metrics.get(code, {}).get("total_mentions") or 0,
            "total_queries": overall_metrics.get(code, {}).get("total_runs") or 0,
            "mentions": overall_metrics.get(code, {}).get("total_mentions") or 0,
        }
        for code, info in entity_info.items()
    ]
    visibility_breakdown = build_visibility_payload(visibility_entities)

    # Stage 8 (A1): incentive_citation reshapes the same overall_metrics
    # rows above (no second query) — deal_citation_rate is a pre-existing,
    # already-computed column (H1: the coding/metrics instrument is
    # frozen this stage).
    incentive_citation_entities = [
        {
            "name": info["name"],
            "is_primary": info["role"] == "primary",
            "mentions": overall_metrics.get(code, {}).get("total_mentions") or 0,
            "deal_citation_rate_raw": raw_deal_citation_rate.get(code),
        }
        for code, info in entity_info.items()
    ]
    incentive_citation = build_incentive_citation_payload(incentive_citation_entities)
    visibility_breakdown["incentive_citation"] = incentive_citation

    # Stage 16 (Part 7): reuses dimensions_raw/run_signals/primary_
    # entity_id already fetched above for the pillars computation — no
    # second query for either.
    linked: dict = {}
    if scan_complete and primary_entity_id is not None:
        linked = link_dimensions(run_signals, dimensions_raw)

        # Stage 8 (A4): merged via setdefault so an existing Stage-7
        # rule's reason on V2/V3 always wins if one already fired.
        for code, reason in link_incentive_citation(incentive_citation, dimensions_raw).items():
            linked.setdefault(code, reason)

    _attach_v3_linked_reasons(pillars_payload, linked)
    scan_payload = _build_scan_payload(scan_row, linked)

    return PublicLiteReportResponse(
        status="complete", locked=False, overall=overall, by_stage=None,
        scan=scan_payload,
        visibility=visibility, accessibility=accessibility, composite=composite,
        scan_status=scan_status,
        visibility_breakdown=visibility_breakdown,
        competitor_source=competitor_source,
        pillars=pillars_payload,
    ).model_dump()


# ─── POST /api/public/soa-lite ───────────────────────────────────────────

@router.post("/soa-lite", response_model=PublicLiteSubmitResponse, status_code=201)
def submit_lite_request(data: PublicLiteSubmitRequest, request: Request):
    if not _verify_captcha(data.captcha_token):
        raise HTTPException(status_code=400, detail="Captcha verification failed.")

    ip_hash = _hash_ip(_get_client_ip(request))
    now = datetime.now(timezone.utc)

    with engine.connect() as conn:
        _enforce_rate_limits(conn, ip_hash, now)

    with session_factory() as session:
        org_id = get_or_create_leadgen_org(session)
        session.commit()

    token = uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO soa_lite_requests
              (token, brand_name, competitor_names, store_url, status, ip_hash, organization_id)
            VALUES
              (:token, :brand, :competitors, :store_url, :status, :ip_hash, :org_id)
        """), {
            "token":       token,
            "brand":       data.brand_name,
            "competitors": json.dumps(data.competitor_names),
            "store_url":   data.store_url,
            "status":      LITE_STATUS_PENDING,
            "ip_hash":     ip_hash,
            "org_id":      org_id,
        })

    return PublicLiteSubmitResponse(token=token, status="pending")


# ─── GET /api/public/soa-lite/{token}/status ─────────────────────────────

_SCAN_TERMINAL_STATUSES = ("complete", "blocked", "failed", "skipped")


def _derive_membership_check(scan_status: str | None, dimensions_raw: dict, probe_result: str | None) -> str | None:
    """
    "pending" | "applies" | "na" for the run-manifest's membership-check
    row (Stage 20). Mirrors member_value_applicable() (app.services.
    lite_pillars — reused, never a second definition of applicability).

    probe_result is None exactly when soa_lite_scan_results.
    membership_probe hasn't been written yet (probe_membership() itself
    always returns a real {result: ...} dict, never leaves this
    ambiguous — see apps/pipeline/generation/membership_probe.py) — that
    case always stays "pending", distinct from a returned 'unknown'.

    "applies" fires the instant the probe says 'yes', independent of
    the scan (a probe finding alone is sufficient — see
    member_value_applicable's own docstring). Otherwise stays "pending"
    until the scan ALSO reaches a terminal status: member_value's
    crawl-side credit isn't known before then, and resolving to "na"
    early could be reversed once the crawl finds a loyalty page.
    """
    if probe_result is None:
        return "pending"
    if probe_result == "yes":
        return "applies"
    if scan_status not in _SCAN_TERMINAL_STATUSES:
        return "pending"
    seen = dimensions_raw.get("member_value_seen") or {}
    return "applies" if member_value_applicable(probe_result, seen.get("score") or 0.0) else "na"


@router.get("/soa-lite/{token}/status", response_model=PublicLiteStatusResponse)
def get_lite_status(token: str):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT lr.status, c.id, c.status, c.total_runs_planned, sr.status,
                   lr.competitor_names, lr.competitor_source,
                   sr.dimensions, sr.pages_fetched, sr.membership_probe
            FROM soa_lite_requests lr
            LEFT JOIN soa_cycles c ON c.id = lr.cycle_id
            LEFT JOIN soa_lite_scan_results sr ON sr.lite_request_id = lr.id
            WHERE lr.token = :token
        """), {"token": token}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Not found.")

        (lite_status, cycle_id, cycle_status, total_runs_planned, scan_status,
         competitor_names, competitor_source,
         dimensions_raw, pages_fetched_raw, membership_probe_raw) = row
        live_counts = _fetch_live_progress_counts(conn, cycle_id) if cycle_id else None

    phase, progress = _derive_phase(lite_status, cycle_status, total_runs_planned, live_counts)

    pages_fetched = _decode_json_field(pages_fetched_raw, None)
    scan_pages_read = len(pages_fetched) if pages_fetched is not None else None
    probe_result = _decode_json_field(membership_probe_raw, {}).get("result")
    membership_check = _derive_membership_check(
        scan_status, _decode_json_field(dimensions_raw, {}), probe_result,
    )

    return PublicLiteStatusResponse(
        status=lite_status, phase=phase, progress=progress, scan_status=scan_status,
        competitors=_decode_json_field(competitor_names, None), competitor_source=competitor_source,
        membership_check=membership_check, scan_pages_read=scan_pages_read,
    )


# ─── GET /api/public/soa-lite/{token}/report ─────────────────────────────

@router.get("/soa-lite/{token}/report", response_model=None)
def get_lite_report(token: str):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT id, status, email, cycle_id FROM soa_lite_requests WHERE token = :token
        """), {"token": token}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Not found.")

        lite_request_id, lite_status, email, cycle_id = row
        if lite_status != 'complete':
            raise HTTPException(status_code=409, detail="Report is not ready yet.")

        return _build_report_payload(conn, lite_request_id, cycle_id, email)


# ─── PATCH /api/public/soa-lite/{token}/email ────────────────────────────

@router.patch("/soa-lite/{token}/email", response_model=None)
def set_lite_email(token: str, data: PublicLiteEmailRequest):
    """
    Always stores the email, even if the report isn't ready yet — capturing
    the lead is the priority, and the report will already be unlocked once
    the widget later calls GET /report. Returns the full report inline only
    when already complete (saves the widget a round trip); otherwise
    returns the same {status, phase} shape as GET /status.
    """
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT lr.id, lr.status, lr.cycle_id, c.status, c.total_runs_planned,
                   lr.competitor_names, lr.competitor_source
            FROM soa_lite_requests lr
            LEFT JOIN soa_cycles c ON c.id = lr.cycle_id
            WHERE lr.token = :token
        """), {"token": token}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Not found.")

        (lite_request_id, lite_status, cycle_id, cycle_status, total_runs_planned,
         competitor_names, competitor_source) = row

        conn.execute(text("""
            UPDATE soa_lite_requests SET email = :email, updated_at = NOW() WHERE token = :token
        """), {"email": data.email, "token": token})

        if lite_status != 'complete':
            live_counts = _fetch_live_progress_counts(conn, cycle_id) if cycle_id else None
            phase, progress = _derive_phase(lite_status, cycle_status, total_runs_planned, live_counts)
            return PublicLiteStatusResponse(
                status=lite_status, phase=phase, progress=progress,
                competitors=_decode_json_field(competitor_names, None), competitor_source=competitor_source,
            ).model_dump()

        return _build_report_payload(conn, lite_request_id, cycle_id, data.email)
