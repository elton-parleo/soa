from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List
from sqlalchemy import text
from datetime import date
import json
import soa_shared.config as config
from soa_shared.database import engine, session_factory
from soa_shared.models.soa_models import SoaCycle, SoaScopeSku, SoaTruecostSnapshot
from soa_shared.scope_resolution import materialize_and_freeze
from soa_shared.cycle_creation import create_cycle_with_comparison_set
from app.auth import get_current_user
from app.schemas import (
    CreateCycleRequest,
    CycleStatusResponse,
    CycleCheckResponse,
    CycleTruecostSnapshotsResponse,
    PATTERN_DISPLAY,
    ScopeTiersResponse,
    TierOption,
    TruecostSkuRow,
    TruecostTierResult,
)
from clients.deal_engine_client import DealEngineClient

router = APIRouter()


@router.get("/cycles/check", response_model=CycleCheckResponse)
def check_cycle_code(
    code: str = Query(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Checks if a cycle_code is available. Cycle codes are globally unique
    (DB UNIQUE constraint), so this check is intentionally unscoped —
    two orgs cannot share the same cycle_code. Auth is required for
    consistency, but the SELECT does not filter by organization_id.
    """
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT 1 FROM soa_cycles WHERE cycle_code = :code
        """), {"code": code}).fetchone()
    return CycleCheckResponse(available=row is None, cycle_code=code)


@router.post("/cycles", response_model=CycleStatusResponse, status_code=201)
def create_cycle(
    data: CreateCycleRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Creates a new cycle and its comparison set in the database with
    status='planned'.

    The pipeline worker in apps/pipeline/ polls for status='planned' and
    executes the cycle. This endpoint returns immediately without running
    anything.
    """
    org_id  = current_user['organization_id']
    user_id = current_user['user_id']
    is_truecost = data.cycle_mode == "truecost"

    with engine.begin() as conn:

        # 1. Check code availability (global — cycle_code is globally unique)
        exists = conn.execute(text("""
            SELECT 1 FROM soa_cycles WHERE cycle_code = :code
        """), {"code": data.cycle_code}).fetchone()
        if exists:
            raise HTTPException(
                status_code=409,
                detail=f"Cycle code '{data.cycle_code}' is already taken.",
            )

        if is_truecost:
            # truecost cycles don't run LLM queries — no study_pattern/
            # query-count lookup, no platforms/runs_per_query. soa_cycles.
            # study_type/study_pattern are NOT NULL with no DB-level
            # default on a raw-SQL insert, so we stamp harmless constants;
            # they're never read for cycle_mode='truecost'.
            study_pattern = "retailer"
            total_runs = None
            platforms_json = None
            runs_per_query = None
        else:
            # 2. Detect study_pattern — scoped to caller's org
            patterns = conn.execute(text("""
                SELECT DISTINCT study_pattern
                FROM soa_queries
                WHERE study_type = :st
                  AND status = 'Active'
                  AND organization_id = :org_id
            """), {"st": data.study_type, "org_id": org_id}).fetchall()

            if not patterns:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"No active queries found for study_type "
                        f"'{data.study_type}'."
                    ),
                )

            pattern_values = [r[0] for r in patterns]
            study_pattern = "mixed" if len(pattern_values) > 1 else pattern_values[0]

            # 3. Count queries — scoped to caller's org
            query_count = conn.execute(text("""
                SELECT COUNT(*) FROM soa_queries
                WHERE study_type = :st
                  AND status = 'Active'
                  AND organization_id = :org_id
            """), {"st": data.study_type, "org_id": org_id}).scalar()

            total_runs = (
                query_count * len(data.platforms) * data.runs_per_query
            )
            platforms_json = json.dumps(data.platforms)
            runs_per_query = data.runs_per_query

        # 4-5. Create cycle (stamp organization_id and created_by) plus its
        # comparison set — shared with the SoA Lite worker, see
        # soa_shared/cycle_creation.py.
        cycle_id, created_at = create_cycle_with_comparison_set(
            conn,
            cycle_code=data.cycle_code,
            study_type=data.study_type if not is_truecost else "truecost",
            study_pattern=study_pattern,
            cycle_mode=data.cycle_mode,
            truecost_tiers=json.dumps(data.truecost_tiers) if data.truecost_tiers is not None else None,
            total_runs_planned=total_runs,
            start_date=date.today(),
            platforms=platforms_json,
            runs_per_query=runs_per_query,
            organization_id=org_id,
            created_by=user_id,
            notes=data.notes,
            comparison_set=[
                {"entity_id": ce.entity_id, "comparison_code": ce.comparison_code, "role": ce.role}
                for ce in data.comparison_set
            ],
        )

    # 6. Scope snapshot — only when PLANNED_CYCLE_SCOPE_RESYNC is off.
    # With it on (default), the Planned cycle inherits live from entity
    # templates until it starts running (see scope_resolution.py); no rows
    # are written here. Separate small ORM transaction since the insert
    # above is raw SQL/Core. truecost cycles always freeze at sweep start
    # (run_truecost_sweep calls materialize_and_freeze itself), so this is
    # skipped for them regardless of the resync flag.
    if not is_truecost and not config.PLANNED_CYCLE_SCOPE_RESYNC:
        with session_factory() as session:
            cycle_obj = session.get(SoaCycle, cycle_id)
            if cycle_obj is not None:
                materialize_and_freeze(cycle_obj, session, freeze=False)
                session.commit()

    return CycleStatusResponse(
        cycle_code=data.cycle_code,
        status="planned",
        cycle_mode=data.cycle_mode,
        study_type=None if is_truecost else data.study_type,
        study_pattern=None if is_truecost else study_pattern,
        total_runs_planned=total_runs,
        completed_runs=0,
        created_at=str(created_at) if created_at else None,
        platforms=data.platforms,
        runs_per_query=data.runs_per_query,
        truecost_tiers=data.truecost_tiers,
        id=cycle_id,
    )


@router.get("/cycles", response_model=list[CycleStatusResponse])
def list_cycles(
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user['organization_id']
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
              cycle_code, status, study_type, study_pattern,
              total_runs_planned, completed_runs, created_at,
              updated_at, platforms, runs_per_query, id,
              cycle_mode, truecost_tiers
            FROM soa_cycles
            WHERE organization_id = :org_id
            ORDER BY created_at DESC
        """), {"org_id": org_id}).fetchall()
    return [_row_to_cycle(r) for r in rows]


@router.get("/cycles/{cycle_code}", response_model=CycleStatusResponse)
def get_cycle(
    cycle_code: str,
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user['organization_id']
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT
              cycle_code, status, study_type, study_pattern,
              total_runs_planned, completed_runs, created_at,
              updated_at, platforms, runs_per_query, id,
              cycle_mode, truecost_tiers
            FROM soa_cycles
            WHERE cycle_code = :code
              AND organization_id = :org_id
        """), {"code": cycle_code, "org_id": org_id}).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Cycle '{cycle_code}' not found",
        )
    return _row_to_cycle(row)


@router.get(
    "/cycles/{cycle_code}/truecost-snapshots",
    response_model=CycleTruecostSnapshotsResponse,
)
def get_cycle_truecost_snapshots(
    cycle_code: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Returns a cycle's captured soa_truecost_snapshots as a SKU x retailer x
    tier grid — one row per scope SKU, each carrying its swept tier results
    (listed_price, true_cost, total_savings, applied_deals, status,
    captured_at). When more than one tier was swept for a SKU,
    member_vs_baseline_delta gives each non-baseline tier's true_cost
    savings vs the non-member baseline (positive = cheaper as a member).

    Read-only — never triggers a sweep. Only meaningful for cycles with
    cycle_mode='truecost'; returns an empty grid for any other cycle (no
    error, since soa_truecost_snapshots is simply empty for them).
    """
    org_id = current_user["organization_id"]
    with session_factory() as session:
        cycle = (
            session.query(SoaCycle)
            .filter_by(cycle_code=cycle_code, organization_id=org_id)
            .first()
        )
        if cycle is None:
            raise HTTPException(status_code=404, detail=f"Cycle '{cycle_code}' not found")

        snapshots = (
            session.query(SoaTruecostSnapshot)
            .filter_by(cycle_id=cycle.id)
            .order_by(SoaTruecostSnapshot.scope_sku_id, SoaTruecostSnapshot.id)
            .all()
        )

        scope_sku_ids = {s.scope_sku_id for s in snapshots}
        scope_skus_by_id = {
            sku.id: sku
            for sku in session.query(SoaScopeSku).filter(SoaScopeSku.id.in_(scope_sku_ids)).all()
        } if scope_sku_ids else {}

        rows_by_sku: dict[int, TruecostSkuRow] = {}
        for snap in snapshots:
            row = rows_by_sku.get(snap.scope_sku_id)
            if row is None:
                sku = scope_skus_by_id.get(snap.scope_sku_id)
                row = TruecostSkuRow(
                    scope_sku_id=snap.scope_sku_id,
                    entity_id=snap.entity_id,
                    merchant_slug=snap.merchant_slug,
                    brand=snap.brand,
                    category=snap.category,
                    display_name=sku.display_name if sku else None,
                    dealengine_listing_id=snap.dealengine_listing_id,
                    tiers=[],
                )
                rows_by_sku[snap.scope_sku_id] = row

            row.tiers.append(
                TruecostTierResult(
                    user_tier_name=snap.user_tier_name,
                    listed_price=float(snap.listed_price) if snap.listed_price is not None else None,
                    currency=snap.currency,
                    true_cost=float(snap.true_cost) if snap.true_cost is not None else None,
                    total_savings=float(snap.total_savings) if snap.total_savings is not None else None,
                    total_points_earned=snap.total_points_earned,
                    applied_deals=snap.applied_deals,
                    available_deals=snap.available_deals,
                    confidence=snap.confidence,
                    price_was_refreshed=snap.price_was_refreshed,
                    price_refreshed_at=str(snap.price_refreshed_at)[:19] if snap.price_refreshed_at else None,
                    status=snap.status,
                    error_message=snap.error_message,
                    captured_at=str(snap.captured_at)[:19] if snap.captured_at else None,
                )
            )

        for row in rows_by_sku.values():
            if len(row.tiers) <= 1:
                continue
            baseline = next((t for t in row.tiers if t.user_tier_name is None), None)
            if baseline is None or baseline.status != "captured" or baseline.true_cost is None:
                continue
            for tier in row.tiers:
                if tier.user_tier_name is None or tier.status != "captured" or tier.true_cost is None:
                    continue
                row.member_vs_baseline_delta[tier.user_tier_name] = round(
                    baseline.true_cost - tier.true_cost, 2
                )

        return CycleTruecostSnapshotsResponse(
            cycle_id=cycle.id,
            cycle_code=cycle.cycle_code,
            skus=list(rows_by_sku.values()),
        )


@router.post("/cycles/{cycle_code}/resume")
def resume_cycle(
    cycle_code: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Resume a failed cycle by setting its status back to 'planned'.
    The pipeline worker polls for 'planned' cycles every 30s and
    will pick it up automatically.

    Only cycles with status 'failed' can be resumed. Returns 409 if
    the cycle is not in failed state. Returns 404 if the cycle does
    not exist or belongs to a different organization (avoids leaking
    existence of other orgs' cycles via status-code differences).
    """
    org_id = current_user['organization_id']

    with engine.connect() as conn:
        # Fetch without org filter first — used to distinguish 404 vs 409
        row = conn.execute(text("""
            SELECT id, status, organization_id
            FROM soa_cycles
            WHERE cycle_code = :code
        """), {"code": cycle_code}).fetchone()

        if not row:
            # Cycle doesn't exist at all
            raise HTTPException(
                status_code=404,
                detail=f"Cycle '{cycle_code}' not found.",
            )

        _cycle_id, current_status, cycle_org_id = row[0], row[1], row[2]

        if cycle_org_id != org_id:
            # Cycle exists but belongs to another org — return 404, not 403,
            # to avoid leaking existence of other orgs' data
            raise HTTPException(
                status_code=404,
                detail=f"Cycle '{cycle_code}' not found.",
            )

        if current_status != 'failed':
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cycle is '{current_status}'"
                    f" — only failed cycles can be resumed."
                ),
            )

        # Set status back to planned — include org_id in WHERE for safety
        conn.execute(text("""
            UPDATE soa_cycles
            SET
              status = 'planned',
              updated_at = NOW()
            WHERE cycle_code = :code
              AND organization_id = :org_id
        """), {"code": cycle_code, "org_id": org_id})
        conn.commit()

    return {
        "cycle_code": cycle_code,
        "status":     "planned",
        "message":    (
            "Cycle queued for retry. "
            "The pipeline worker will "
            "pick it up within 30 seconds."
        ),
    }


@router.get("/cycles/{cycle_code}/runs")
def get_cycle_runs(
    cycle_code:   str,
    platform:     Optional[str] = None,
    stage:        Optional[str] = None,
    entity:       Optional[str] = None,
    deal_cited:   Optional[bool] = None,
    needs_review: Optional[bool] = None,
    limit:        int = 200,
    offset:       int = 0,
    current_user: dict = Depends(get_current_user),
):
    with engine.connect() as conn:
        conditions = ["c.cycle_code = :cycle_code"]
        params: dict = {"cycle_code": cycle_code}

        if platform and platform != "all":
            conditions.append("r.platform = :platform")
            params["platform"] = platform

        if stage and stage != "all":
            conditions.append("q.stage = :stage")
            params["stage"] = stage

        if entity:
            conditions.append("LOWER(q.query_text) LIKE :entity")
            params["entity"] = f"%{entity.lower()}%"

        if deal_cited is not None:
            conditions.append(
                "EXISTS (SELECT 1 FROM soa_coded_mentions cm2"
                " WHERE cm2.run_id = r.id AND cm2.deal_cited = :dc)"
            )
            params["dc"] = deal_cited

        if needs_review is not None:
            conditions.append(
                "EXISTS (SELECT 1 FROM soa_coded_mentions cm3"
                " WHERE cm3.run_id = r.id AND cm3.needs_review = :nr)"
            )
            params["nr"] = needs_review

        where = " AND ".join(conditions)

        rows = conn.execute(text(f"""
            SELECT
              r.id            AS run_id,
              q.query_code,
              r.platform,
              r.run_number,
              c.runs_per_query,
              r.raw_response,
              r.status,
              r.created_at,
              q.query_text,
              q.stage,
              q.category
            FROM soa_runs r
            JOIN soa_cycles c ON c.id = r.cycle_id
            LEFT JOIN soa_queries q ON q.id = r.query_id
            WHERE {where}
            ORDER BY q.query_code, r.run_number
            LIMIT :limit OFFSET :offset
        """), {**params, "limit": limit, "offset": offset}).fetchall()

        count_row = conn.execute(text(f"""
            SELECT COUNT(*)
            FROM soa_runs r
            JOIN soa_cycles c ON c.id = r.cycle_id
            LEFT JOIN soa_queries q ON q.id = r.query_id
            WHERE {where}
        """), params).fetchone()
        total = count_row[0] if count_row else 0

    return {
        "cycle_code": cycle_code,
        "total": total,
        "runs": [
            {
                "run_id":        row[0],
                "query_code":    row[1],
                "platform":      row[2],
                "run_number":    row[3],
                "runs_per_query": row[4] or 5,
                "raw_response":  row[5],
                "status":        row[6],
                "created_at": str(row[7])[:19] if row[7] else None,
                "query_text":    row[8],
                "stage":         row[9],
                "category":      row[10],
            }
            for row in rows
        ],
    }


@router.get("/cycles/{cycle_code}/runs/{run_id}/mentions")
def get_run_mentions(
    cycle_code: str,
    run_id:     int,
    current_user: dict = Depends(get_current_user),
):
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
              cm.id,
              ce.comparison_code,
              e.name        AS entity_name,
              cm.position,
              cm.strength,
              cm.deal_cited,
              cm.confidence,
              cm.needs_review,
              ce.role
            FROM soa_coded_mentions cm
            JOIN soa_cycles c ON c.cycle_code = :cycle_code
            LEFT JOIN soa_cycle_entities ce
              ON ce.cycle_id = c.id
              AND ce.entity_id = cm.entity_id
            LEFT JOIN soa_entities e ON e.id = cm.entity_id
            WHERE cm.run_id = :run_id
            ORDER BY cm.position NULLS LAST, ce.comparison_code
        """), {"run_id": run_id, "cycle_code": cycle_code}).fetchall()

    return {
        "run_id": run_id,
        "mentions": [
            {
                "id":               row[0],
                "comparison_code":  row[1],
                "entity_name":      row[2],
                "position":         row[3],
                "strength_label":   row[4],
                "deal_cited":       row[5],
                "confidence_score": row[6],
                "needs_review":     row[7],
                "role":             row[8],
            }
            for row in rows
        ],
    }


@router.patch("/cycles/{cycle_code}/runs/{run_id}/mentions")
def update_run_mentions(
    cycle_code: str,
    run_id:     int,
    updates:    List[dict],
    current_user: dict = Depends(get_current_user),
):
    """
    Batch updates coded mentions for one run. Each item must have
    'comparison_code' identifying which row to update. Only provided
    fields are written. Sets override_flag = TRUE on any updated row.

    Maps frontend field names to actual DB column names:
      strength_label   → strength
      confidence_score → confidence
    Looks up entity_id via soa_cycle_entities using comparison_code.
    """
    if not updates:
        return {"updated": 0}

    updated_count = 0

    with engine.connect() as conn:
        for item in updates:
            code = item.get('comparison_code')
            if not code:
                continue

            set_parts = [
                "override_flag = TRUE",
                "updated_at = NOW()",
            ]
            params: dict = {"run_id": run_id, "code": code, "cycle_code": cycle_code}

            # Map frontend key → actual DB column name
            field_map = {
                "mentioned":        "mentioned",
                "strength_label":   "strength",
                "position":         "position",
                "deal_cited":       "deal_cited",
                "confidence_score": "confidence",
            }

            for key, col in field_map.items():
                if key in item:
                    set_parts.append(f"{col} = :{key}")
                    params[key] = item[key]

            if len(set_parts) <= 2:
                continue

            set_clause = ", ".join(set_parts)

            result = conn.execute(text(f"""
                UPDATE soa_coded_mentions
                SET {set_clause}
                WHERE run_id = :run_id
                  AND entity_id = (
                      SELECT ce.entity_id
                      FROM soa_cycle_entities ce
                      JOIN soa_cycles c ON c.id = ce.cycle_id
                      WHERE c.cycle_code = :cycle_code
                        AND ce.comparison_code = :code
                  )
            """), params)
            updated_count += result.rowcount or 0

        conn.commit()

    return {"updated": updated_count}


def _row_to_cycle(row) -> CycleStatusResponse:
    cycle_mode = row[11] if len(row) > 11 and row[11] else "query"
    truecost_tiers = row[12] if len(row) > 12 else None
    if isinstance(truecost_tiers, str):
        truecost_tiers = json.loads(truecost_tiers)
    return CycleStatusResponse(
        cycle_code=row[0],
        status=row[1],
        cycle_mode=cycle_mode,
        study_type=row[2],
        study_pattern=row[3],
        total_runs_planned=row[4],
        completed_runs=row[5] or 0,
        created_at=str(row[6])[:19] if row[6] else None,
        updated_at=str(row[7])[:19] if row[7] else None,
        platforms=json.loads(row[8]) if isinstance(row[8], str) else row[8],
        runs_per_query=row[9],
        truecost_tiers=truecost_tiers,
        id=row[10] if len(row) > 10 else None,
    )
