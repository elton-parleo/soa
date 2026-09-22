"""
lite_requests.py — the internal Audits list: an authenticated, read-only
view over soa_lite_requests (every audit submitted through the public
audit tool) and the lead email captured on its status page.

READ-ONLY. Nothing in this module writes to any table. The public lane
(app/routers/public_lite.py), the worker, and the pipeline are untouched
by it; this router only reads rows they produce.

─── Why this router is deliberately org-UNSCOPED ────────────────────────

Every other authed router filters `WHERE organization_id = :org_id` off
current_user['organization_id']. Doing that here would return zero rows,
always: app/org_context.py resolves (and auto-provisions) a signed-in
user into the organization named 'Parleo', whereas every lite request
lives under the separate 'Parleo Lead Gen' organization
(soa_shared/org_helpers.py) — the two never coincide.

So this router scopes its DATA to the Lead Gen org, resolved by name,
and relies on verify_token alone as the access gate — applied in app.py
the same way it is for every other authed router. This is the same
deliberate departure cycles.py::check_cycle_code documents for its own
unscoped SELECT: auth is required, but the organization_id filter would
be wrong rather than merely redundant.

The org is resolved with a read-only SELECT, NOT with
org_helpers.get_or_create_leadgen_org — that helper creates the org when
it is missing, and this feature writes nothing. A missing org simply
yields an empty page.
"""
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from soa_shared.database import engine
from soa_shared.models.soa_models import (
    LITE_STATUS_COMPLETE,
    LITE_STATUS_FAILED,
    LITE_STATUS_GENERATING,
    LITE_STATUS_IDENTIFYING_COMPETITORS,
    LITE_STATUS_PENDING,
    LITE_STATUS_RUNNING,
    LITE_STATUSES,
)
# Imported for the org NAME only — the helper itself creates rows; see
# this module's docstring.
from soa_shared.org_helpers import LEADGEN_ORG_NAME
from app.services.cycle_scoring import build_cycle_report, decode_json_field
from app.services.lite_score_batch import (
    SCORE_AVAILABLE,
    SCORE_EXPIRED,
    SCORE_NOT_MEASURABLE,
    SCORE_PARTIAL_READ,
    SCORE_PENDING,
    SCORE_UNAVAILABLE,
    degraded_reason_for,
    pillar_breakdown,
    score_cycles,
)

log = logging.getLogger(__name__)

router = APIRouter()

# The four non-terminal statuses, behind the `in_progress` pseudo-value
# the list filter and the summary strip both use.
LITE_IN_PROGRESS_STATUSES = (
    LITE_STATUS_PENDING,
    LITE_STATUS_IDENTIFYING_COMPETITORS,
    LITE_STATUS_GENERATING,
    LITE_STATUS_RUNNING,
)

STATUS_FILTER_IN_PROGRESS = "in_progress"
COMPETITOR_SOURCES = ("generated", "manual", "mixed", "none")

SORT_CREATED_DESC = "created_at_desc"
SORT_CREATED_ASC = "created_at_asc"
_SORT_SQL = {
    SORT_CREATED_DESC: "lr.created_at DESC, lr.id DESC",
    SORT_CREATED_ASC: "lr.created_at ASC, lr.id ASC",
}

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25

# Event-log task ids this router reasons about. apps/api never imports
# apps/pipeline (the two communicate only through Postgres — see
# public_lite.py's module docstring), so these string literals are a
# deliberate, manually-synced copy of apps/pipeline/lite_events.py's
# TASK registry, the same precedent LiteProgress.jsx already follows.
# Only the ids are copied; every piece of DISPLAY text this router
# returns comes from the event's own `text` field, never from a second
# copy of that file's TASKS dict.
_TASK_QUERIES = "queries"
_TASK_REPORT = "report"
_KIND_DONE = "done"
_KIND_STATE = "state"

# Strict formats emitted by runners/run_orchestrator.py for the queries
# task. Anything else — a reworded message, a future format — falls back
# to null rather than guessing at a progress figure.
_QUERIES_PROGRESS_RE = re.compile(r"^q(\d+)/(\d+) answered$")
_QUERIES_DONE_RE = re.compile(r"^All (\d+) answers collected$")


# ─── Response models ─────────────────────────────────────────────────────
# Defined here rather than in app/schemas.py, following truesync.py's
# precedent for a self-contained internal router.


class LiteRequestListItem(BaseModel):
    id: int
    token: str
    brand_name: Optional[str] = None
    store_url: Optional[str] = None
    email: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    competitor_names: Optional[List[str]] = None
    competitor_source: Optional[str] = None
    manual_competitor_count: Optional[int] = None
    study_type: Optional[str] = None
    cycle_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    report_email_sent_at: Optional[datetime] = None
    lead_notified_at: Optional[datetime] = None

    # Derived from the events log.
    current_task: Optional[str] = None
    current_task_text: Optional[str] = None
    queries_done: Optional[int] = None
    queries_total: Optional[int] = None
    duration_seconds: Optional[float] = None
    duration_is_estimate: bool = False

    # soa_lite_scan_results, 1:1.
    scan_status: Optional[str] = None
    scan_total_score: Optional[int] = None
    scan_integrity_capped: Optional[bool] = None
    scan_pages_fetched_count: Optional[int] = None

    # soa_cycles continuation, via source_lite_request_id.
    continuation_cycle_id: Optional[int] = None
    continuation_cycle_code: Optional[str] = None
    continuation_cycle_status: Optional[str] = None

    # Score.
    composite_score: Optional[float] = None
    scorer_version: Optional[str] = None
    score_state: str = SCORE_UNAVAILABLE
    # Why the crawl came up short this run, when it did — the same
    # string the public status page and report show. Non-null exactly
    # when score_state is 'partial_read'.
    degraded_reason: Optional[str] = None

    # ip_hash is deliberately absent from this model — see the module
    # docstring and test_lite_requests.py's leak tests.


class LiteRequestSummary(BaseModel):
    audits_count: int = 0
    leads_count: int = 0
    in_progress_count: int = 0
    failed_count: int = 0
    continuation_count: int = 0


class LiteRequestListResponse(BaseModel):
    items: List[LiteRequestListItem]
    total_count: int
    page: int
    page_size: int
    summary: LiteRequestSummary


class LiteRequestEvent(BaseModel):
    seq: Optional[int] = None
    ts: Optional[str] = None
    kind: Optional[str] = None
    task: Optional[str] = None
    text: Optional[str] = None
    chips: Optional[List[str]] = None


class LiteRequestPillar(BaseModel):
    score: Optional[float] = None
    earned: Optional[float] = None
    applicable_max: Optional[float] = None


class LiteRequestDetail(LiteRequestListItem):
    events: List[LiteRequestEvent] = []
    brand_entity_id: Optional[int] = None
    competitor_entity_ids: Optional[List[int]] = None
    # First 4 and last 4 characters only — enough to correlate a row
    # with a rate-limit hit, never enough to reverse or to re-identify.
    ip_hash_truncated: Optional[str] = None
    study_series_id: Optional[str] = None
    # Visibility / Accessibility / True Value, each with the raw earned
    # and applicable max behind its normalized 0-100 score.
    pillars: Optional[Dict[str, LiteRequestPillar]] = None
    # build_pillars_payload's own state — 'scored', 'composite_withheld'
    # (an accessibility dimension went unmeasured) or 'unverified' (a
    # True Value encode wing was blocked). Tells apart the two reasons a
    # complete row can still report score_state 'unavailable'.
    pillars_state: Optional[str] = None
    # Discovery follow-up (Part 3): dimensions["discovery_outcome"]
    # (apps/pipeline/scan/discovery_outcome.py) verbatim — code + first-
    # person summary + the sitemaps/tiers/example URLs this run actually
    # saw, so a zero-PDP row can be triaged from this page without
    # opening the raw dimensions JSON. Recorded on every scan going
    # forward, complete or degraded; null for a row scanned before this
    # stage, or with no scan row at all.
    discovery_outcome: Optional[dict] = None
    # Non-commerce report (this session): dimensions["site_type"] —
    # "commerce_normal" | "commerce_discovery_failure" | "brand_only"
    # (apps/pipeline/scan/site_typing.py). Triage-critical on this page:
    # a brand_only row scoring 10-22 is a correct reading of a
    # non-store site, not a broken crawl, and the two were
    # indistinguishable here before. Null for a degraded run (which
    # never types the site) or a row scanned before this stage.
    site_type: Optional[str] = None
    # Scan reuse (this session): dimensions["reused_from_scan_id"] /
    # ["reused_at"] when this row's crawl data was copied from a recent
    # scan of the same host instead of re-crawling it (see
    # apps/pipeline/worker.py). Both null on an ordinary run.
    reused_from_scan_id: Optional[int] = None
    reused_at: Optional[str] = None


# ─── Derivations from the events log ─────────────────────────────────────


def _decode_events(raw) -> list:
    """psycopg2 decodes JSON natively; SQLite hands back a string."""
    value = decode_json_field(raw, [])
    return value if isinstance(value, list) else []


def latest_state_or_done(events: list) -> tuple:
    """
    (task, text) of the most recent state- or done-kind event, which is
    what the status column's second line renders while a run is in
    flight. Pre-events rows (the `events` column defaults to '[]') and
    rows carrying only log-kind events both yield (None, None).

    state events always carry the task id 'run' (lite_events.RUN_TASK) —
    returned as-is, per spec.
    """
    latest = None
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("kind") not in (_KIND_STATE, _KIND_DONE):
            continue
        if latest is None or (event.get("seq") or 0) >= (latest.get("seq") or 0):
            latest = event
    if latest is None:
        return None, None
    return latest.get("task"), latest.get("text")


def parse_queries_progress(events: list) -> tuple:
    """
    (queries_done, queries_total) parsed from the queries task's own
    event text — the only place this progress exists. It is NOT carried
    in `chips`: the only chips anything emits are competitor names and
    a pass-2 price-observation count.

    Both emitted formats are matched, strictly and anchored:
      "q7/24 answered"            (kind=log,  in flight)
      "All 24 answers collected"  (kind=done, finished -> done == total)

    Any other text yields (None, None) rather than a guessed number.
    The last matching event wins, so a completed run reports its done
    event rather than the last in-flight tick.
    """
    done = total = None
    for event in sorted(
        (e for e in events if isinstance(e, dict) and e.get("task") == _TASK_QUERIES),
        key=lambda e: e.get("seq") or 0,
    ):
        event_text = event.get("text")
        if not isinstance(event_text, str):
            continue
        match = _QUERIES_PROGRESS_RE.match(event_text)
        if match:
            done, total = int(match.group(1)), int(match.group(2))
            continue
        match = _QUERIES_DONE_RE.match(event_text)
        if match:
            total = int(match.group(1))
            done = total
    return done, total


def _report_done_ts(events: list) -> Optional[datetime]:
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("kind") == _KIND_DONE and event.get("task") == _TASK_REPORT:
            return _parse_ts(event.get("ts"))
    return None


def _parse_ts(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    try:
        return _as_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """
    Naive timestamps (SQLite, and Postgres columns read back without a
    tz) are treated as UTC — everything in this system is written with
    NOW()/datetime.now(timezone.utc).
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def compute_duration(created_at, updated_at, events: list) -> tuple:
    """
    (duration_seconds, duration_is_estimate).

    Exact when the report task's done-event is present — that event's ts
    is the real end of the run. Otherwise updated_at stands in, which is
    an ESTIMATE: updated_at also moves on a later email PATCH, so it
    over-reports a run whose visitor left their address afterwards.
    Null when neither is available (a row the worker has not touched
    yet never has updated_at set at all).
    """
    started = _parse_ts(created_at)
    if started is None:
        return None, False

    ended = _report_done_ts(events)
    if ended is not None:
        return max((ended - started).total_seconds(), 0.0), False

    ended = _parse_ts(updated_at)
    if ended is not None:
        return max((ended - started).total_seconds(), 0.0), True

    return None, False


def truncate_ip_hash(value) -> Optional[str]:
    """First 4 and last 4 characters. Anything too short to truncate
    meaningfully is withheld entirely rather than echoed."""
    if not value or not isinstance(value, str):
        return None
    if len(value) <= 8:
        return None
    return f"{value[:4]}…{value[-4:]}"


def manual_competitor_count(names: Optional[list], source: Optional[str]) -> Optional[int]:
    """
    How many of competitor_names the visitor typed themselves.

    select_competitors (apps/pipeline/generation/competitor_generator.py)
    keeps manual names first, in order, then tops up from generated
    candidates — so the manual entries are always a prefix of the list.
    The COUNT of that prefix is not persisted anywhere, though, and
    manual names can be dropped on the way in (blank, absurd length, or
    a case-insensitive duplicate of the brand or of each other). So it
    is only exactly recoverable when the source tells us the split:

      None       pre-competitor-stage — the column still holds exactly
                 what the visitor submitted, so all of them
      'manual'   every entry is visitor-entered
      'generated' / 'none'  none are
      'mixed'    UNKNOWN — somewhere between 1 and len-1. Returns None;
                 the UI shows the bare source tag for these.
    """
    if source == "mixed":
        return None
    if source in ("generated", "none"):
        return 0
    if source is None or source == "manual":
        return len(names or [])
    return None


def _decode_name_list(raw) -> Optional[list]:
    value = decode_json_field(raw, None)
    return value if isinstance(value, list) else None


# ─── Filters ─────────────────────────────────────────────────────────────


def _leadgen_org_id(conn) -> Optional[int]:
    row = conn.execute(
        text("SELECT id FROM organizations WHERE name = :name"),
        {"name": LEADGEN_ORG_NAME},
    ).fetchone()
    return row[0] if row else None


def _build_filters(
    org_id: int,
    q: Optional[str],
    status: Optional[str],
    leads_only: bool,
    competitor_source: Optional[str],
    created_after: Optional[datetime],
    created_before: Optional[datetime],
) -> tuple:
    """(where_sql, params) — shared verbatim by the page query and the
    summary, so the summary always describes exactly the filtered set
    the rows came from."""
    clauses = ["lr.organization_id = :org_id"]
    params = {"org_id": org_id}

    if q:
        clauses.append(
            "(LOWER(COALESCE(lr.brand_name, '')) LIKE :q"
            " OR LOWER(COALESCE(lr.email, '')) LIKE :q"
            " OR LOWER(COALESCE(lr.token, '')) LIKE :q"
            " OR LOWER(COALESCE(lr.store_url, '')) LIKE :q)"
        )
        params["q"] = f"%{q.strip().lower()}%"

    if status == STATUS_FILTER_IN_PROGRESS:
        placeholders = ", ".join(f":ip{i}" for i in range(len(LITE_IN_PROGRESS_STATUSES)))
        clauses.append(f"lr.status IN ({placeholders})")
        params.update({f"ip{i}": s for i, s in enumerate(LITE_IN_PROGRESS_STATUSES)})
    elif status:
        clauses.append("lr.status = :status")
        params["status"] = status

    if leads_only:
        clauses.append("lr.email IS NOT NULL")

    if competitor_source:
        clauses.append("lr.competitor_source = :competitor_source")
        params["competitor_source"] = competitor_source

    if created_after:
        clauses.append("lr.created_at >= :created_after")
        params["created_after"] = created_after
    if created_before:
        clauses.append("lr.created_at <= :created_before")
        params["created_before"] = created_before

    return " AND ".join(clauses), params


# ─── Row shaping ─────────────────────────────────────────────────────────

# Column order of the scan columns below, matching public_lite.py::
# _fetch_scan_row exactly so the tuple can be handed straight to
# lite_score_batch.score_cycles (and, for detail, to build_cycle_report).
_SCAN_COLUMNS = """
    sr.status, sr.total_score, sr.integrity_capped, sr.dimensions,
    sr.pages_fetched, sr.membership_probe, sr.revenue_probe,
    sr.fetch_probe, sr.input_url
"""

_ROW_COLUMNS = f"""
    lr.id, lr.token, lr.brand_name, lr.store_url, lr.email, lr.status,
    lr.error_message, lr.competitor_names, lr.competitor_source,
    lr.study_type, lr.cycle_id, lr.created_at, lr.updated_at,
    lr.report_email_sent_at, lr.lead_notified_at, lr.events,
    {_SCAN_COLUMNS},
    cc.id, cc.cycle_code, cc.status
"""

# MIN(id) rather than "any match": deterministic when a lite request
# somehow has more than one continuation cycle, and the first one is the
# one the audit actually led to.
_CONTINUATION_JOIN = """
    LEFT JOIN soa_cycles cc ON cc.id = (
        SELECT MIN(c2.id) FROM soa_cycles c2
        WHERE c2.source_lite_request_id = lr.id
    )
"""

_SCAN_JOIN = "LEFT JOIN soa_lite_scan_results sr ON sr.lite_request_id = lr.id"

_SCAN_SLICE = slice(16, 25)
_CONTINUATION_SLICE = slice(25, 28)


def _shape_row(row) -> dict:
    """The list-item fields that come straight from the row, before the
    score is overlaid."""
    events = _decode_events(row[15])
    competitor_names = _decode_name_list(row[7])
    competitor_source = row[8]
    current_task, current_task_text = latest_state_or_done(events)
    queries_done, queries_total = parse_queries_progress(events)
    duration_seconds, duration_is_estimate = compute_duration(row[11], row[12], events)

    scan = row[_SCAN_SLICE]
    pages_fetched = decode_json_field(scan[4], None)
    continuation = row[_CONTINUATION_SLICE]

    # Pure over the scan row already in hand — no query, and the same
    # function (and therefore the same wording) the public status page
    # and report use. Populated only for a scan that reached a
    # non-'complete' terminal state; null everywhere else.
    degraded_reason = degraded_reason_for(scan)

    return {
        "id": row[0],
        "token": row[1],
        "brand_name": row[2],
        "store_url": row[3],
        "email": row[4],
        "status": row[5],
        "error_message": row[6],
        "competitor_names": competitor_names,
        "competitor_source": competitor_source,
        "manual_competitor_count": manual_competitor_count(competitor_names, competitor_source),
        "study_type": row[9],
        "cycle_id": row[10],
        "created_at": row[11],
        "updated_at": row[12],
        "report_email_sent_at": row[13],
        "lead_notified_at": row[14],
        "current_task": current_task,
        "current_task_text": current_task_text,
        "queries_done": queries_done,
        "queries_total": queries_total,
        "duration_seconds": duration_seconds,
        "duration_is_estimate": duration_is_estimate,
        "scan_status": scan[0],
        "scan_total_score": scan[1],
        "scan_integrity_capped": bool(scan[2]) if scan[2] is not None else None,
        # No pages_fetched_count column exists — the array's length is
        # the count, exactly as the public status page derives it.
        # Null (not 0) when there is no scan row at all.
        "scan_pages_fetched_count": len(pages_fetched) if isinstance(pages_fetched, list) else None,
        "continuation_cycle_id": continuation[0],
        "continuation_cycle_code": continuation[1],
        "continuation_cycle_status": continuation[2],
        "degraded_reason": degraded_reason,
    }


def _score_state_for(status: str, scored: Optional[dict], degraded_reason: Optional[str]) -> dict:
    """
    Overlays the request's own status onto what the scorer found. An
    in-progress row has no score yet by definition; a failed row never
    will. Only a row past both of those gates reports what the scorer
    actually returned.

    degraded_reason rides along on every terminal row that has one, even
    where the request's own status wins the score_state — a failed row
    whose crawl was blocked should still be able to SAY the crawl was
    blocked in the drawer.
    """
    if status in LITE_IN_PROGRESS_STATUSES:
        return {
            "composite_score": None,
            "scorer_version": None,
            "score_state": SCORE_PENDING,
            "degraded_reason": None,
        }
    if status == LITE_STATUS_FAILED:
        return {
            "composite_score": None,
            "scorer_version": (scored or {}).get("scorer_version"),
            "score_state": SCORE_NOT_MEASURABLE,
            "degraded_reason": degraded_reason,
        }
    if not scored:
        return {
            "composite_score": None,
            "scorer_version": None,
            "score_state": SCORE_PARTIAL_READ if degraded_reason else SCORE_UNAVAILABLE,
            "degraded_reason": degraded_reason,
        }
    return {
        "composite_score": scored.get("composite_score"),
        "scorer_version": scored.get("scorer_version"),
        "score_state": scored.get("score_state", SCORE_UNAVAILABLE),
        "degraded_reason": degraded_reason,
    }


# ─── GET /api/lite-requests ──────────────────────────────────────────────


@router.get("/lite-requests", response_model=LiteRequestListResponse)
def list_lite_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    q: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    leads_only: bool = Query(False),
    competitor_source: Optional[str] = Query(None),
    created_after: Optional[datetime] = Query(None),
    created_before: Optional[datetime] = Query(None),
    sort: str = Query(SORT_CREATED_DESC),
):
    if status is not None and status != STATUS_FILTER_IN_PROGRESS and status not in LITE_STATUSES:
        raise HTTPException(status_code=422, detail=f"Unknown status filter: {status}")
    if competitor_source is not None and competitor_source not in COMPETITOR_SOURCES:
        raise HTTPException(
            status_code=422, detail=f"Unknown competitor_source filter: {competitor_source}",
        )
    if sort not in _SORT_SQL:
        raise HTTPException(status_code=422, detail=f"Unknown sort: {sort}")

    empty = LiteRequestListResponse(
        items=[], total_count=0, page=page, page_size=page_size, summary=LiteRequestSummary(),
    )

    with engine.connect() as conn:
        org_id = _leadgen_org_id(conn)
        if org_id is None:
            # Nothing has ever created the Lead Gen org in this database
            # — an empty list, not an error, and emphatically not a
            # write. See the module docstring.
            log.warning("[lite_requests] organization %r not found — returning an empty page", LEADGEN_ORG_NAME)
            return empty

        where_sql, params = _build_filters(
            org_id, q, status, leads_only, competitor_source, created_after, created_before,
        )

        in_progress_placeholders = ", ".join(
            f":sip{i}" for i in range(len(LITE_IN_PROGRESS_STATUSES))
        )
        summary_params = dict(params)
        summary_params.update({f"sip{i}": s for i, s in enumerate(LITE_IN_PROGRESS_STATUSES)})
        summary_params["failed_status"] = LITE_STATUS_FAILED

        summary_row = conn.execute(text(f"""
            SELECT
              COUNT(*),
              SUM(CASE WHEN lr.email IS NOT NULL THEN 1 ELSE 0 END),
              SUM(CASE WHEN lr.status IN ({in_progress_placeholders}) THEN 1 ELSE 0 END),
              SUM(CASE WHEN lr.status = :failed_status THEN 1 ELSE 0 END),
              SUM(CASE WHEN EXISTS (
                    SELECT 1 FROM soa_cycles c2 WHERE c2.source_lite_request_id = lr.id
                  ) THEN 1 ELSE 0 END)
            FROM soa_lite_requests lr
            WHERE {where_sql}
        """), summary_params).fetchone()

        total_count = summary_row[0] or 0
        summary = LiteRequestSummary(
            audits_count=total_count,
            leads_count=summary_row[1] or 0,
            in_progress_count=summary_row[2] or 0,
            failed_count=summary_row[3] or 0,
            continuation_count=summary_row[4] or 0,
        )

        if total_count == 0:
            return LiteRequestListResponse(
                items=[], total_count=0, page=page, page_size=page_size, summary=summary,
            )

        page_params = dict(params)
        page_params["limit"] = page_size
        page_params["offset"] = (page - 1) * page_size

        rows = conn.execute(text(f"""
            SELECT {_ROW_COLUMNS}
            FROM soa_lite_requests lr
            {_SCAN_JOIN}
            {_CONTINUATION_JOIN}
            WHERE {where_sql}
            ORDER BY {_SORT_SQL[sort]}
            LIMIT :limit OFFSET :offset
        """), page_params).fetchall()

        shaped = [_shape_row(row) for row in rows]

        # One batched scoring pass for the whole page — six queries,
        # regardless of how many rows are on it. See
        # app/services/lite_score_batch.py. Only complete rows are
        # scored at all: _score_state_for overrides in-progress rows to
        # 'pending' and failed ones to 'not_measurable' regardless of
        # what the scorer would say, so scoring them would be pure work.
        scan_row_by_cycle_id = {
            row[10]: tuple(row[_SCAN_SLICE])
            for row in rows
            if row[10] is not None and row[5] == LITE_STATUS_COMPLETE
        }
        scored_by_cycle = score_cycles(conn, scan_row_by_cycle_id) if scan_row_by_cycle_id else {}

    for item in shaped:
        item.update(_score_state_for(
            item["status"], scored_by_cycle.get(item["cycle_id"]), item["degraded_reason"],
        ))

    return LiteRequestListResponse(
        items=[LiteRequestListItem(**item) for item in shaped],
        total_count=total_count,
        page=page,
        page_size=page_size,
        summary=summary,
    )


# ─── GET /api/lite-requests/{lite_request_id} ────────────────────────────


@router.get("/lite-requests/{lite_request_id}", response_model=LiteRequestDetail)
def get_lite_request(lite_request_id: int):
    with engine.connect() as conn:
        org_id = _leadgen_org_id(conn)
        if org_id is None:
            raise HTTPException(status_code=404, detail="Not found.")

        row = conn.execute(text(f"""
            SELECT {_ROW_COLUMNS},
                   lr.brand_entity_id, lr.competitor_entity_ids, lr.ip_hash,
                   cc.study_series_id
            FROM soa_lite_requests lr
            {_SCAN_JOIN}
            {_CONTINUATION_JOIN}
            WHERE lr.id = :id AND lr.organization_id = :org_id
        """), {"id": lite_request_id, "org_id": org_id}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Not found.")

        item = _shape_row(row)
        events = _decode_events(row[15])

        # _ROW_COLUMNS ends at index 27 (the continuation slice); the
        # detail-only columns appended to that SELECT start at 28.
        competitor_entity_ids = decode_json_field(row[29], None)
        item.update({
            "events": events,
            "brand_entity_id": row[28],
            "competitor_entity_ids": (
                competitor_entity_ids if isinstance(competitor_entity_ids, list) else None
            ),
            "ip_hash_truncated": truncate_ip_hash(row[30]),
            "study_series_id": row[31],
        })
        # Discovery follow-up (Part 3): read straight off the scan row's
        # own dimensions column (index 19 — _SCAN_COLUMNS' 4th entry,
        # sr.dimensions, offset by _SCAN_SLICE's start of 16) —
        # independent of the pillars-building branch below, so it's
        # populated for a degraded (blocked/failed) row too, not only a
        # complete one.
        scan_dimensions = decode_json_field(row[19], {}) or {}
        item["discovery_outcome"] = scan_dimensions.get("discovery_outcome")
        # Same read, same column, same "triage without opening the raw
        # JSON" rationale as discovery_outcome above.
        item["site_type"] = scan_dimensions.get("site_type")
        item["reused_from_scan_id"] = scan_dimensions.get("reused_from_scan_id")
        item["reused_at"] = scan_dimensions.get("reused_at")

        # Detail is one row, so the plain per-cycle path is used here —
        # the same build_cycle_report the public report calls, with no
        # second definition of anything. ~7 queries for one row is fine;
        # the batched path exists for the 25-row list, not for this.
        pillars = None
        scored = None
        if item["cycle_id"] is not None and item["status"] == LITE_STATUS_COMPLETE:
            scan_row = tuple(row[_SCAN_SLICE])
            try:
                report = build_cycle_report(conn, item["cycle_id"], scan_row)
            except Exception:
                log.exception(
                    "[lite_requests] report build failed for lite request %s", lite_request_id,
                )
                report = None

            if report is not None and report.get("status") == "expired":
                scored = {
                    "composite_score": None,
                    "scorer_version": (
                        decode_json_field(scan_row[3], {}) or {}
                    ).get("scorer_version"),
                    "score_state": SCORE_EXPIRED,
                }
            elif report is not None:
                pillars = report.get("pillars")
                composite = report.get("composite")
                if item["degraded_reason"]:
                    state = SCORE_PARTIAL_READ
                elif composite is not None:
                    state = SCORE_AVAILABLE
                else:
                    state = SCORE_UNAVAILABLE
                scored = {
                    "composite_score": composite,
                    "scorer_version": (
                        decode_json_field(scan_row[3], {}) or {}
                    ).get("scorer_version") or "1",
                    "score_state": state,
                }

    item.update(_score_state_for(item["status"], scored, item["degraded_reason"]))
    item["pillars"] = pillar_breakdown(pillars)
    item["pillars_state"] = (pillars or {}).get("state")

    return LiteRequestDetail(**item)
