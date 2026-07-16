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
from app.schemas import (
    EntityMetrics,
    PublicLiteEmailRequest,
    PublicLiteEntityMetrics,
    PublicLiteProgress,
    PublicLiteReportResponse,
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


# ─── Report shaping ──────────────────────────────────────────────────────

def _fetch_metrics_rows(conn, cycle_id: int):
    """
    Same column order (indices 0-11) as soa_dashboard_summary, so
    build_entity_metrics (app/routers/metrics.py) works unchanged — see
    that function's docstring. role/comparison_code are appended after,
    used here for grouping/ordering only; comparison_code is never
    returned to the caller.
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
          AND mr.slice_type IN ('overall', 'stage')
        ORDER BY ce.comparison_code, mr.slice_type, mr.slice_value
    """), {"cid": cycle_id}).fetchall()


def _build_report_payload(conn, cycle_id: int, email: str | None) -> dict:
    rows = _fetch_metrics_rows(conn, cycle_id)

    entity_info: dict = {}    # comparison_code -> {"name":, "role":} (internal grouping key only)
    overall_metrics: dict = {}
    by_stage: dict = {}

    for row in rows:
        name, role, comp_code = row[1], row[12], row[13]
        entity_info.setdefault(comp_code, {"name": name, "role": role})

        metrics_dict = build_entity_metrics(row)
        if row[2] == 'overall':
            overall_metrics[comp_code] = metrics_dict
        elif row[2] == 'stage':
            by_stage.setdefault(row[3], {})[comp_code] = metrics_dict

    if not email:
        overall = [
            PublicLiteTeaserEntity(
                name=info["name"],
                role=info["role"],
                som=overall_metrics.get(code, {}).get("som"),
            ).model_dump()
            for code, info in entity_info.items()
        ]
        return PublicLiteTeaserResponse(status="complete", locked=True, overall=overall).model_dump()

    overall = [
        PublicLiteEntityMetrics(
            name=info["name"],
            role=info["role"],
            metrics=EntityMetrics(**overall_metrics.get(code, {})),
        ).model_dump()
        for code, info in entity_info.items()
    ]
    by_stage_public = {
        stage: [
            PublicLiteEntityMetrics(
                name=entity_info[code]["name"],
                role=entity_info[code]["role"],
                metrics=EntityMetrics(**m),
            ).model_dump()
            for code, m in stage_metrics.items()
        ]
        for stage, stage_metrics in by_stage.items()
    }
    return PublicLiteReportResponse(
        status="complete", locked=False, overall=overall, by_stage=by_stage_public,
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
              (token, brand_name, competitor_names, status, ip_hash, organization_id)
            VALUES
              (:token, :brand, :competitors, 'pending', :ip_hash, :org_id)
        """), {
            "token":       token,
            "brand":       data.brand_name,
            "competitors": json.dumps(data.competitor_names),
            "ip_hash":     ip_hash,
            "org_id":      org_id,
        })

    return PublicLiteSubmitResponse(token=token, status="pending")


# ─── GET /api/public/soa-lite/{token}/status ─────────────────────────────

@router.get("/soa-lite/{token}/status", response_model=PublicLiteStatusResponse)
def get_lite_status(token: str):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT lr.status, c.status, c.completed_runs, c.total_runs_planned
            FROM soa_lite_requests lr
            LEFT JOIN soa_cycles c ON c.id = lr.cycle_id
            WHERE lr.token = :token
        """), {"token": token}).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Not found.")

    lite_status, cycle_status, completed_runs, total_runs_planned = row
    phase, progress = _derive_phase(lite_status, cycle_status, completed_runs, total_runs_planned)

    return PublicLiteStatusResponse(status=lite_status, phase=phase, progress=progress)


# ─── GET /api/public/soa-lite/{token}/report ─────────────────────────────

@router.get("/soa-lite/{token}/report", response_model=None)
def get_lite_report(token: str):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT status, email, cycle_id FROM soa_lite_requests WHERE token = :token
        """), {"token": token}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Not found.")

        lite_status, email, cycle_id = row
        if lite_status != 'complete':
            raise HTTPException(status_code=409, detail="Report is not ready yet.")

        return _build_report_payload(conn, cycle_id, email)


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
            SELECT lr.status, lr.cycle_id, c.status, c.completed_runs, c.total_runs_planned
            FROM soa_lite_requests lr
            LEFT JOIN soa_cycles c ON c.id = lr.cycle_id
            WHERE lr.token = :token
        """), {"token": token}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Not found.")

        lite_status, cycle_id, cycle_status, completed_runs, total_runs_planned = row

        conn.execute(text("""
            UPDATE soa_lite_requests SET email = :email, updated_at = NOW() WHERE token = :token
        """), {"email": data.email, "token": token})

        if lite_status != 'complete':
            phase, progress = _derive_phase(lite_status, cycle_status, completed_runs, total_runs_planned)
            return PublicLiteStatusResponse(status=lite_status, phase=phase, progress=progress).model_dump()

        return _build_report_payload(conn, cycle_id, data.email)
