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
and _sweep_lite_completions): pending -> generating -> running -> complete
| failed. This router only ever reads that machine (GET endpoints) or
performs the two writes visitors are allowed to trigger themselves:
creating a request (POST) and attaching an email to unlock the report
(PATCH) — it never advances the pipeline state itself.
"""
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from soa_shared.database import engine, session_factory
from soa_shared.org_helpers import get_or_create_leadgen_org
from app.routers.metrics import build_entity_metrics
from app.services.lite_crosswalk import RunSignal, link_dimensions, link_incentive_citation
from app.services.lite_incentive_citation import build_incentive_citation_payload
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
RATE_LIMIT_PER_IP_DAY = 5
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

def _derive_phase(lite_status, cycle_status, completed_runs, total_runs_planned):
    """
    Maps (lite_status, cycle_status, completed_runs, total_runs_planned)
    to the public phase enum. completed_runs is only written once, at the
    end of the Runner stage (see RunOrchestrator._finalize_cycle) — not
    incrementally — and stays at that value through Coding/Metrics while
    cycle_status remains 'running' the whole time. So
    completed_runs >= total_runs_planned while still 'running' reliably
    means "runs done, coding/metrics still in progress" -> 'analyzing'.
    Returns (phase: str, progress: PublicLiteProgress | None).
    """
    if lite_status == 'pending':
        return 'queued', None
    if lite_status == 'generating':
        return 'generating_queries', None
    if lite_status == 'complete':
        return 'complete', None
    if lite_status == 'failed':
        return 'failed', None

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

    progress = None
    if total_runs_planned:
        progress = PublicLiteProgress(
            completed_runs=completed_runs or 0, total_runs=total_runs_planned,
        )
        if (completed_runs or 0) >= total_runs_planned:
            return 'analyzing', progress
    return 'running', progress


# ─── Agent Scan shaping ──────────────────────────────────────────────────

DIMENSION_ORDER = ("F1", "F2", "F3", "V1", "V2", "V3", "V4", "V5")
DIMENSION_NAMES = {
    "F1": "Agent Access",
    "F2": "Catalog Context",
    "F3": "Transaction Rails",
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
        SELECT status, total_score, integrity_capped, dimensions, pages_fetched
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
        SELECT r.id, cm.mentioned, cm.deal_cited, cm.deal_types
        FROM soa_runs r
        LEFT JOIN soa_coded_mentions cm ON cm.run_id = r.id AND cm.entity_id = :eid
        WHERE r.cycle_id = :cid AND r.status = 'success'
    """), {"cid": cycle_id, "eid": primary_entity_id}).fetchall()
    primary_by_run = {row[0]: (row[1], row[2], row[3]) for row in primary_rows}

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
        mentioned, deal_cited, deal_types = primary_by_run.get(run_id, (False, False, None))
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
    """
    if not scan_row:
        return None

    status, total_score, integrity_capped, dimensions, pages_fetched = scan_row
    pages_fetched = _decode_json_field(pages_fetched, [])

    if status != 'complete':
        return PublicLiteScan(
            status=status,
            total_score=total_score,
            integrity_capped=bool(integrity_capped),
            pages_fetched=pages_fetched,
        ).model_dump()

    dimensions = _decode_json_field(dimensions, {})

    # Rank by opportunity size (max - score) descending — biggest gaps
    # first — deterministic tiebreak by code. Only the top FREE_FIX_RANK
    # dimensions' fix text is given away free; the rest are locked.
    ranked_codes = sorted(
        DIMENSION_ORDER,
        key=lambda code: (
            -(dimensions.get(code, {}).get('max', 0) - dimensions.get(code, {}).get('score', 0)),
            code,
        ),
    )
    rank_by_code = {code: i + 1 for i, code in enumerate(ranked_codes)}

    dim_rows = []
    foundation_subtotal = 0.0
    value_subtotal = 0.0
    for code in DIMENSION_ORDER:
        d = dimensions.get(code, {})
        score = d.get('score', 0)
        max_ = d.get('max', 0)
        fix = d.get('fix')
        evidence = d.get('evidence', [])

        locked = fix is not None and rank_by_code[code] > FREE_FIX_RANK
        if locked:
            fix = None

        if code in FOUNDATION_CODES:
            foundation_subtotal += score
        else:
            value_subtotal += score

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
        ).model_dump())

    return PublicLiteScan(
        status=status,
        total_score=total_score,
        integrity_capped=bool(integrity_capped),
        foundation=PublicLiteScanFamily(subtotal=round(foundation_subtotal, 1), max=FOUNDATION_MAX).model_dump(),
        value=PublicLiteScanFamily(subtotal=round(value_subtotal, 1), max=VALUE_MAX).model_dump(),
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

    # visibility reuses the same share-of-voice metric already computed
    # for the report (build_entity_metrics' 'som') — no second metrics
    # path. Already stage-agnostic (only ever reads the 'overall' slice),
    # so no rebasing was needed for Stage 7 (A2).
    visibility = overall_metrics.get(primary_code, {}).get("som") if primary_code else None

    scan_row = _fetch_scan_row(conn, lite_request_id)
    scan_status = scan_row[0] if scan_row else None
    accessibility = scan_row[1] if scan_row and scan_row[0] == 'complete' else None

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
            scan_status=scan_status,
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

    linked: dict = {}
    if scan_row and scan_row[0] == 'complete':
        primary_entity_row = conn.execute(text("""
            SELECT entity_id FROM soa_cycle_entities WHERE cycle_id = :cid AND role = 'primary'
        """), {"cid": cycle_id}).fetchone()
        if primary_entity_row:
            dimensions_raw = _decode_json_field(scan_row[3], {})
            run_signals = _fetch_run_signals(conn, cycle_id, primary_entity_row[0])
            linked = link_dimensions(run_signals, dimensions_raw)

            # Stage 8 (A4): merged via setdefault so an existing Stage-7
            # rule's reason on V2/V3 always wins if one already fired.
            for code, reason in link_incentive_citation(incentive_citation, dimensions_raw).items():
                linked.setdefault(code, reason)

    scan_payload = _build_scan_payload(scan_row, linked)

    return PublicLiteReportResponse(
        status="complete", locked=False, overall=overall, by_stage=None,
        scan=scan_payload,
        visibility=visibility, accessibility=accessibility, composite=composite,
        scan_status=scan_status,
        visibility_breakdown=visibility_breakdown,
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
              (:token, :brand, :competitors, :store_url, 'pending', :ip_hash, :org_id)
        """), {
            "token":       token,
            "brand":       data.brand_name,
            "competitors": json.dumps(data.competitor_names),
            "store_url":   data.store_url,
            "ip_hash":     ip_hash,
            "org_id":      org_id,
        })

    return PublicLiteSubmitResponse(token=token, status="pending")


# ─── GET /api/public/soa-lite/{token}/status ─────────────────────────────

@router.get("/soa-lite/{token}/status", response_model=PublicLiteStatusResponse)
def get_lite_status(token: str):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT lr.status, c.status, c.completed_runs, c.total_runs_planned, sr.status
            FROM soa_lite_requests lr
            LEFT JOIN soa_cycles c ON c.id = lr.cycle_id
            LEFT JOIN soa_lite_scan_results sr ON sr.lite_request_id = lr.id
            WHERE lr.token = :token
        """), {"token": token}).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Not found.")

    lite_status, cycle_status, completed_runs, total_runs_planned, scan_status = row
    phase, progress = _derive_phase(lite_status, cycle_status, completed_runs, total_runs_planned)

    return PublicLiteStatusResponse(status=lite_status, phase=phase, progress=progress, scan_status=scan_status)


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
            SELECT lr.id, lr.status, lr.cycle_id, c.status, c.completed_runs, c.total_runs_planned
            FROM soa_lite_requests lr
            LEFT JOIN soa_cycles c ON c.id = lr.cycle_id
            WHERE lr.token = :token
        """), {"token": token}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Not found.")

        lite_request_id, lite_status, cycle_id, cycle_status, completed_runs, total_runs_planned = row

        conn.execute(text("""
            UPDATE soa_lite_requests SET email = :email, updated_at = NOW() WHERE token = :token
        """), {"email": data.email, "token": token})

        if lite_status != 'complete':
            phase, progress = _derive_phase(lite_status, cycle_status, completed_runs, total_runs_planned)
            return PublicLiteStatusResponse(status=lite_status, phase=phase, progress=progress).model_dump()

        return _build_report_payload(conn, lite_request_id, cycle_id, data.email)
