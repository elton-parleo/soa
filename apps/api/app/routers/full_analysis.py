"""
Full Analysis coexistence, Phase 2: the small, additive endpoints
NewCycleFlow needs that don't belong in the classic wizard's surface —
continuation-mode audit resolve, competitor auto-suggestion, and crawl
launch. Authenticated (mounted with verify_token in app.py, same as
cycles.py) — unlike public_lite.py, which is intentionally public.

Cycle creation itself still posts to the existing POST /api/cycles
(cycles.py) unchanged; this router only prepares its inputs and, after
launch, attaches a crawl to the new cycle_id.
"""
import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from soa_shared.database import engine
from app.auth import get_current_user
from app.routers.public_lite import _build_report_payload
from app.schemas import (
    AuditCompetitor,
    AuditContinuationResponse,
    LaunchCrawlRequest,
    LaunchCrawlResponse,
    SuggestCompetitorsRequest,
    SuggestCompetitorsResponse,
    SuggestedCompetitor,
)
from app.services.competitor_suggestion import (
    generate_competitors,
    select_competitors,
)

log = logging.getLogger(__name__)
router = APIRouter()


def _decode_json_field(value, default):
    """JSON columns come back already-decoded via psycopg2; defensively
    handle a driver (or SQLite test) that returns the raw string instead —
    same idiom as public_lite.py."""
    if isinstance(value, str):
        return json.loads(value) if value else default
    return value if value is not None else default


@router.get("/full-analysis/audit/{token}", response_model=AuditContinuationResponse)
def get_audit_continuation(
    token: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Resolves an audit's brand/competitors/category/composite/date for
    NewCycleFlow's continuation-mode step 1 confirmation card. Any
    authenticated user may resolve any token — soa_lite_requests all
    live under the single 'Parleo Lead Gen' organization (leads, not
    customer accounts), so there is no per-org ownership to check here,
    unlike soa_cycles.
    """
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT lr.id, lr.status, lr.cycle_id, lr.brand_name, lr.brand_entity_id,
                   lr.competitor_entity_ids, lr.competitor_names, lr.store_url,
                   lr.created_at, e.category
            FROM soa_lite_requests lr
            LEFT JOIN soa_entities e ON e.id = lr.brand_entity_id
            WHERE lr.token = :token
        """), {"token": token}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Audit not found.")

        (lite_request_id, status, cycle_id, brand_name, brand_entity_id,
         competitor_entity_ids, competitor_names, store_url, created_at, category) = row

        if status != "complete" or cycle_id is None:
            raise HTTPException(status_code=409, detail="This audit hasn't finished running yet.")

        report = _build_report_payload(conn, lite_request_id, cycle_id)

    competitor_entity_ids = _decode_json_field(competitor_entity_ids, [])
    competitor_names = _decode_json_field(competitor_names, [])
    competitors = [
        AuditCompetitor(
            name=name,
            entity_id=competitor_entity_ids[i] if i < len(competitor_entity_ids) else None,
        )
        for i, name in enumerate(competitor_names)
    ]

    return AuditContinuationResponse(
        lite_request_id=lite_request_id,
        cycle_id=cycle_id,
        brand_name=brand_name,
        brand_entity_id=brand_entity_id,
        category=category,
        competitors=competitors,
        composite=report.get("composite"),
        verdict=(report.get("pillars") or {}).get("verdict"),
        audited_at=str(created_at)[:10] if created_at else None,
        store_url=store_url,
        store_domain=report.get("store_domain"),
    )


@router.post("/full-analysis/suggest-competitors", response_model=SuggestCompetitorsResponse)
def suggest_competitors(
    data: SuggestCompetitorsRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Step 1's auto-suggest chips. Never errors out to the caller — a
    missing/failing OpenAI call degrades to whatever manual_names were
    already typed (or an empty list), same never-throw contract as
    apps/pipeline's worker-side competitor generation.
    """
    api_key = os.environ.get("OPEN_AI_API_KEY")
    candidates = []
    if api_key:
        candidates = generate_competitors(
            data.brand_name, api_key,
            store_url=data.store_url, category_hint=data.category_hint,
        )
    else:
        log.warning("[full-analysis] OPEN_AI_API_KEY not set — competitor suggestion degraded to manual-only")

    final, source = select_competitors(data.manual_names or [], candidates, data.brand_name)
    return SuggestCompetitorsResponse(
        competitors=[SuggestedCompetitor(name=c["name"], domain=c["domain"]) for c in final],
        source=source,
    )


@router.post("/full-analysis/launch-crawl", response_model=LaunchCrawlResponse, status_code=201)
def launch_crawl(
    data: LaunchCrawlRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Step 3's launch action, second half: queues a fresh crawl against
    the new cycle (Phase 1's soa_lite_scan_results.cycle_id) — always a
    NEW scan row, never a reuse of the audit's own crawl, even in
    continuation mode (the report's continuation banner shows the
    audit's crawl only as a delta reference, never as this cycle's
    measured data). Picked up by apps/pipeline/worker.py::
    process_cycle_crawls, the same poll-loop pattern every other
    pipeline stage uses.
    """
    org_id = current_user["organization_id"]
    with engine.begin() as conn:
        cycle = conn.execute(text("""
            SELECT id FROM soa_cycles WHERE id = :cid AND organization_id = :org_id
        """), {"cid": data.cycle_id, "org_id": org_id}).fetchone()
        if not cycle:
            raise HTTPException(status_code=404, detail=f"Cycle {data.cycle_id} not found.")

        row = conn.execute(text("""
            INSERT INTO soa_lite_scan_results (cycle_id, input_url, status)
            VALUES (:cycle_id, :store_url, 'pending')
            RETURNING id
        """), {"cycle_id": data.cycle_id, "store_url": data.store_url}).fetchone()

    return LaunchCrawlResponse(scan_id=row[0], cycle_id=data.cycle_id, status="pending")
