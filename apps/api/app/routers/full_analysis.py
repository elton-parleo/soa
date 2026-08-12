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
    FullAnalysisContinuation,
    FullAnalysisReportResponse,
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
from app.services.cycle_scoring import build_scan_payload
from app.services.cycle_scoring_full import build_full_cycle_report
from app.services.full_analysis_extras import (
    build_competitor_set,
    build_platform_matrix,
    build_what_if,
    select_evidence_exemplar,
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
    missing OpenAI key degrades to whatever manual_names were already
    typed (or an empty list), same never-throw contract as apps/pipeline's
    worker-side competitor generation. Unlike before, that degradation is
    now reported explicitly (status='degraded') rather than an empty
    success response the client can't tell apart from "brand genuinely
    has no competitors" — see SuggestCompetitorsResponse. reason is a
    fixed enum string, never the env var name or any backend internals.
    """
    api_key = os.environ.get("OPEN_AI_API_KEY")
    candidates = []
    degraded = not api_key
    if api_key:
        candidates = generate_competitors(
            data.brand_name, api_key,
            store_url=data.store_url, category_hint=data.category_hint,
        )
    else:
        log.warning("[full-analysis] OPEN_AI_API_KEY not set — competitor suggestion degraded to manual-only")

    final, source = select_competitors(data.manual_names or [], candidates, data.brand_name)
    return SuggestCompetitorsResponse(
        status="degraded" if degraded else "ok",
        reason="suggestions_unavailable" if degraded else None,
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


# 1f: per-pillar deltas are comparable only where both the lite and
# full-cycle scorers use the exact same formula/band table. true_value
# is NOT comparable — deal_citability rebands as a RATE at full-cycle
# volume specifically because lite's count band trivially saturates
# there (cycle_scoring_full.py's own module docstring); a point-for-
# point True Value delta would silently compare two different rulers.
# visibility/accessibility reuse the identical scoring path in both.
_PILLAR_DELTA_COMPARABLE = {"visibility": True, "accessibility": True, "true_value": False}


def _compute_pillar_deltas(audit_pillars: dict, full_pillars: dict) -> list[dict]:
    """
    Pure (1f): both the lite and full-cycle pillars dicts share the
    exact same shape (both built via lite_pillars.py::_pillar) —
    {"score": 0-100 normalized, "max": 100.0, "dimensions": [...]} — so
    audit_score/full_score here are already on the same 0-100 scale the
    top-level composite comparison always relied on, nothing new to
    normalize. comparable=False on a dimension whose full-cycle rescore
    isn't apples-to-apples (see _PILLAR_DELTA_COMPARABLE) — the
    frontend shows direction/"rescored at full scale" there instead of
    a numeric delta.
    """
    deltas = []
    for key in ("visibility", "accessibility", "true_value"):
        audit_score = (audit_pillars.get(key) or {}).get("score")
        full_score = (full_pillars.get(key) or {}).get("score")
        comparable = _PILLAR_DELTA_COMPARABLE[key] and audit_score is not None and full_score is not None
        deltas.append({
            "pillar": key,
            "audit_score": audit_score,
            "full_score": full_score,
            "delta": (full_score - audit_score) if comparable else None,
            "comparable": comparable,
        })
    return deltas


def _build_continuation(conn, source_lite_request_id: int, full_pillars: dict) -> FullAnalysisContinuation | None:
    """
    Phase 4 report header, item 2: the audit's own composite/verdict/
    date for the continuation banner's "your audit scored X" line, plus
    (1f) a per-pillar delta (_compute_pillar_deltas) when the audit
    itself reached pillars-shaped scoring.
    """
    row = conn.execute(text("""
        SELECT lr.id, lr.cycle_id, lr.status, lr.created_at, c.platforms, c.runs_per_query
        FROM soa_lite_requests lr
        LEFT JOIN soa_cycles c ON c.id = lr.cycle_id
        WHERE lr.id = :rid
    """), {"rid": source_lite_request_id}).fetchone()
    if not row:
        return None
    lite_request_id, audit_cycle_id, status, created_at, platforms_raw, runs_per_query = row

    audit_composite = None
    audit_verdict = None
    pillar_deltas = None
    if status == "complete" and audit_cycle_id is not None:
        audit_report = _build_report_payload(conn, lite_request_id, audit_cycle_id)
        audit_composite = audit_report.get("composite")
        audit_pillars = audit_report.get("pillars")
        audit_verdict = (audit_pillars or {}).get("verdict")
        if audit_pillars:
            pillar_deltas = _compute_pillar_deltas(audit_pillars, full_pillars)

    platforms = _decode_json_field(platforms_raw, [])
    platforms_note = (
        f"{', '.join(platforms) if platforms else 'the audited platform'} × {runs_per_query or 1} runs/query"
    )

    return FullAnalysisContinuation(
        source_lite_request_id=source_lite_request_id,
        audit_composite=audit_composite,
        audit_verdict=audit_verdict,
        audit_date=str(created_at)[:10] if created_at else None,
        audit_platforms_note=platforms_note,
        pillar_deltas=pillar_deltas,
    )


@router.get("/full-analysis/report/{cycle_code}", response_model=FullAnalysisReportResponse)
def get_full_analysis_report(
    cycle_code: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Phase 4 render-gate: resolves for a cycle only when it has an
    attached crawl AND a current-scorer-version score (build_full_cycle_
    report's own status=='complete' check) — otherwise rendered=False,
    and the frontend falls back to the classic MetricsDashboard for the
    same cycle_code. Never a partial/degraded Full Analysis render.
    """
    org_id = current_user["organization_id"]
    with engine.connect() as conn:
        cycle = conn.execute(text("""
            SELECT id, source_lite_request_id FROM soa_cycles
            WHERE cycle_code = :code AND organization_id = :org_id
        """), {"code": cycle_code, "org_id": org_id}).fetchone()
        if not cycle:
            raise HTTPException(status_code=404, detail=f"Cycle '{cycle_code}' not found.")
        cycle_id, source_lite_request_id = cycle

        report = build_full_cycle_report(conn, cycle_id)

        if report["status"] != "complete":
            return FullAnalysisReportResponse(
                cycle_code=cycle_code, rendered=False,
                reason="no crawl attached yet" if report["status"] == "not_scored" else report["status"],
            )

        continuation = (
            _build_continuation(conn, source_lite_request_id, report["pillars"])
            if source_lite_request_id is not None else None
        )

        dimensions_raw = report["dimensions_raw"]
        primary_entity_id = report["primary_entity_id"]

        # 1d: discovery/parsed-page/value-signals — the SAME shape build_
        # scan_payload already builds for lite (pages_fetched, agent_
        # access_matrix, discovery_trace). linked={} deliberately: the
        # v1/v2 dimension-code "linked reasons" crosswalk is a lite-
        # report-specific concern (cycle_scoring.py's _attach_v3_linked_
        # reasons handles the v3+ equivalent on `pillars` directly,
        # which this report doesn't yet do either) — out of Phase 1's
        # scope, and scan.dimensions isn't the primary source a v4-
        # shaped report reads from anyway (pillars is).
        scan_payload = build_scan_payload(report["scan_row"], {})

        platform_matrix = (
            build_platform_matrix(conn, cycle_id, primary_entity_id, dimensions_raw)
            if primary_entity_id is not None else []
        )
        competitor_set = (
            build_competitor_set(conn, cycle_id, report["overall_entity_info"], report["overall_metrics"])
            if primary_entity_id is not None else None
        )
        # Ranked fixes live on report["pillars"]["fixes"] (cycle_scoring_
        # full.py::_build_full_fixes_section) — the shape FixesTable.jsx
        # actually reads, not a second top-level field.
        evidence = (
            select_evidence_exemplar(conn, cycle_id, primary_entity_id)
            if primary_entity_id is not None else None
        )
        what_if = build_what_if(competitor_set) if competitor_set else None

    return FullAnalysisReportResponse(
        cycle_code=cycle_code, rendered=True,
        composite=report["pillars"]["composite"],
        verdict=report["pillars"]["verdict"],
        scorer_version=report["scorer_version"],
        total_queries=report["total_queries"],
        pillars=report["pillars"],
        continuation=continuation,
        platform_matrix=platform_matrix,
        competitor_set=competitor_set,
        scan=scan_payload,
        offers=dimensions_raw.get("offers"),
        product_image_url=dimensions_raw.get("product_image_url"),
        product_name=dimensions_raw.get("product_name"),
        revenue_estimate_usd=report["revenue_estimate_usd"],
        evidence=evidence,
        what_if=what_if,
    )
