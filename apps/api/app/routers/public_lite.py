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

# Phase 3a (Full Analysis coexistence): report assembly itself lives in
# cycle_scoring.py now, parameterized by cycle_id — this router is a
# thin caller that resolves lite_request_id -> its own scan_row and
# adds the one lite-only field (competitor_source) the shared service
# deliberately doesn't know about. decode_json_field/build_scan_payload
# are aliased back to their old names — every other call site below
# (get_lite_status, set_lite_email) is unchanged.
from app.services.cycle_scoring import (
    build_cycle_report,
    build_scan_payload as _build_scan_payload,
    decode_json_field as _decode_json_field,
)
from app.services.lite_pillars import member_value_applicable
from app.schemas import (
    PublicLiteEmailRequest,
    PublicLiteProgress,
    PublicLiteStatusResponse,
    PublicLiteSubmitRequest,
    PublicLiteSubmitResponse,
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
#
# The v1/v2/v3 dimension registry, the crosswalk-to-v3 linked-reasons
# attachment, and the scan-row shaping function all moved to
# app/services/cycle_scoring.py (Phase 3a) — decode_json_field and
# build_scan_payload are imported above (aliased to their old names);
# nothing below this point redefines them.


def _fetch_scan_row(conn, lite_request_id: int):
    return conn.execute(text("""
        SELECT status, total_score, integrity_capped, dimensions, pages_fetched,
               membership_probe, revenue_probe, fetch_probe, input_url
        FROM soa_lite_scan_results
        WHERE lite_request_id = :rid
    """), {"rid": lite_request_id}).fetchone()


def _build_report_payload(conn, lite_request_id: int, cycle_id: int) -> dict:
    """
    Phase 3a (Full Analysis coexistence): thin wrapper over
    app/services/cycle_scoring.py::build_cycle_report — resolves this
    lite request's own scan row (1:1 via lite_request_id) and stamps
    the one lite-only field (competitor_source) the shared, cycle-
    parameterized service deliberately doesn't carry.
    """
    scan_row = _fetch_scan_row(conn, lite_request_id)
    report = build_cycle_report(conn, cycle_id, scan_row)

    if report.get("status") == "complete":
        # Stage 13 (W4/W5): drives the widget's solo-comparison fallback
        # and the "auto-selected by ChatGPT" methodology stamp.
        competitor_source_row = conn.execute(text("""
            SELECT competitor_source FROM soa_lite_requests WHERE id = :rid
        """), {"rid": lite_request_id}).fetchone()
        report["competitor_source"] = competitor_source_row[0] if competitor_source_row else None

    return report


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
    # Part 1 (E1): the run-manifest's very first event, written directly
    # here rather than through apps/pipeline's lite_events.emit_event —
    # apps/api never imports apps/pipeline (the two communicate only
    # through Postgres; see this file's module docstring), and this is
    # the row's first-ever write, so there's no concurrent writer that
    # could already hold a copy of `events` to race against — unlike
    # every later append, which all happen worker-side via emit_event's
    # read-modify-write.
    initial_events = json.dumps([{
        "seq": 1,
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "state",
        "task": "run",
        "text": "queued",
    }])
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO soa_lite_requests
              (token, brand_name, competitor_names, store_url, status, ip_hash, organization_id, events)
            VALUES
              (:token, :brand, :competitors, :store_url, :status, :ip_hash, :org_id, :events)
        """), {
            "token":       token,
            "brand":       data.brand_name,
            "competitors": json.dumps(data.competitor_names),
            "store_url":   data.store_url,
            "status":      LITE_STATUS_PENDING,
            "ip_hash":     ip_hash,
            "org_id":      org_id,
            "events":      initial_events,
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
            SELECT lr.id, lr.status, c.id, c.status, c.total_runs_planned, sr.status,
                   lr.competitor_names, lr.competitor_source, lr.events,
                   sr.dimensions, sr.pages_fetched, sr.membership_probe
            FROM soa_lite_requests lr
            LEFT JOIN soa_cycles c ON c.id = lr.cycle_id
            LEFT JOIN soa_lite_scan_results sr ON sr.lite_request_id = lr.id
            WHERE lr.token = :token
        """), {"token": token}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Not found.")

        (lite_request_id, lite_status, cycle_id, cycle_status, total_runs_planned, scan_status,
         competitor_names, competitor_source, events_raw,
         dimensions_raw, pages_fetched_raw, membership_probe_raw) = row
        live_counts = _fetch_live_progress_counts(conn, cycle_id) if cycle_id else None

        # Part 1 (P4): reuses _build_scan_payload (same function
        # get_lite_report calls) so the status page's terminal banner is
        # computed identically to the report's — never a second,
        # divergent definition of degraded_reason/degraded_banner_facts.
        scan_row = _fetch_scan_row(conn, lite_request_id)

    phase, progress = _derive_phase(lite_status, cycle_status, total_runs_planned, live_counts)

    pages_fetched = _decode_json_field(pages_fetched_raw, None)
    scan_pages_read = len(pages_fetched) if pages_fetched is not None else None
    probe_result = _decode_json_field(membership_probe_raw, {}).get("result")
    membership_check = _derive_membership_check(
        scan_status, _decode_json_field(dimensions_raw, {}), probe_result,
    )

    scan_payload = _build_scan_payload(scan_row, {})

    return PublicLiteStatusResponse(
        status=lite_status, phase=phase, progress=progress, scan_status=scan_status,
        competitors=_decode_json_field(competitor_names, None), competitor_source=competitor_source,
        membership_check=membership_check, scan_pages_read=scan_pages_read,
        events=_decode_json_field(events_raw, []),
        degraded_reason=(scan_payload or {}).get('degraded_reason'),
        degraded_banner_facts=(scan_payload or {}).get('degraded_banner_facts'),
    )


# ─── GET /api/public/soa-lite/{token}/report ─────────────────────────────

@router.get("/soa-lite/{token}/report", response_model=None)
def get_lite_report(token: str):
    # Report redesign (Part 8, E1): a valid, complete token always renders
    # the full report — never gated on whether an email is on file. See
    # set_lite_email below for the (unchanged) notification-capture path.
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT id, status, cycle_id FROM soa_lite_requests WHERE token = :token
        """), {"token": token}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Not found.")

        lite_request_id, lite_status, cycle_id = row
        if lite_status != 'complete':
            raise HTTPException(status_code=409, detail="Report is not ready yet.")

        return _build_report_payload(conn, lite_request_id, cycle_id)


# ─── PATCH /api/public/soa-lite/{token}/email ────────────────────────────

@router.patch("/soa-lite/{token}/email", response_model=None)
def set_lite_email(token: str, data: PublicLiteEmailRequest):
    """
    Always stores the email, even if the report isn't ready yet — this is
    a notification-capture address only (Part 8, E2): the report itself is
    never gated on it (see get_lite_report). Returns the full report
    inline only when already complete (saves the widget a round trip);
    otherwise returns the same {status, phase} shape as GET /status.
    """
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT lr.id, lr.status, lr.cycle_id, c.status, c.total_runs_planned,
                   lr.competitor_names, lr.competitor_source, lr.events
            FROM soa_lite_requests lr
            LEFT JOIN soa_cycles c ON c.id = lr.cycle_id
            WHERE lr.token = :token
        """), {"token": token}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Not found.")

        (lite_request_id, lite_status, cycle_id, cycle_status, total_runs_planned,
         competitor_names, competitor_source, events_raw) = row

        conn.execute(text("""
            UPDATE soa_lite_requests SET email = :email, updated_at = NOW() WHERE token = :token
        """), {"email": data.email, "token": token})

        if lite_status != 'complete':
            live_counts = _fetch_live_progress_counts(conn, cycle_id) if cycle_id else None
            phase, progress = _derive_phase(lite_status, cycle_status, total_runs_planned, live_counts)
            # Part 1 (P6): same additive events/degraded fields as GET
            # /status — attaching an email mid-run must not change the
            # shape of what the widget already reads from this response.
            scan_row = _fetch_scan_row(conn, lite_request_id)
            scan_payload = _build_scan_payload(scan_row, {})
            return PublicLiteStatusResponse(
                status=lite_status, phase=phase, progress=progress,
                competitors=_decode_json_field(competitor_names, None), competitor_source=competitor_source,
                events=_decode_json_field(events_raw, []),
                degraded_reason=(scan_payload or {}).get('degraded_reason'),
                degraded_banner_facts=(scan_payload or {}).get('degraded_banner_facts'),
            ).model_dump()

        return _build_report_payload(conn, lite_request_id, cycle_id)
