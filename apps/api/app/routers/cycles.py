from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List
from sqlalchemy import text
from datetime import date
import json
import soa_shared.config as config
from soa_shared.database import engine, session_factory
from soa_shared.models.soa_models import SoaCycle
from soa_shared.scope_resolution import materialize_and_freeze
from app.auth import get_current_user
from app.schemas import (
    CreateCycleRequest,
    CycleStatusResponse,
    CycleCheckResponse,
    PATTERN_DISPLAY,
)

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

        # 4. Create cycle — stamp organization_id and created_by
        cycle_row = conn.execute(text("""
            INSERT INTO soa_cycles (
                cycle_code, study_type, study_pattern, status,
                total_runs_planned, completed_runs, start_date, notes,
                platforms, runs_per_query,
                organization_id, created_by
            ) VALUES (
                :code, :st, :sp, 'planned', :total, 0, :today, :notes,
                :platforms, :runs_per_query,
                :org_id, :user_id
            )
            RETURNING id, created_at
        """), {
            "code":          data.cycle_code,
            "st":            data.study_type,
            "sp":            study_pattern,
            "total":         total_runs,
            "today":         date.today(),
            "notes":         data.notes,
            "platforms":     json.dumps(data.platforms),
            "runs_per_query": data.runs_per_query,
            "org_id":        org_id,
            "user_id":       user_id,
        }).fetchone()

        cycle_id   = cycle_row[0]
        created_at = cycle_row[1]

        # 5. Create comparison set
        for ce in data.comparison_set:
            conn.execute(text("""
                INSERT INTO soa_cycle_entities
                  (cycle_id, entity_id, comparison_code, role)
                VALUES
                  (:cid, :eid, :code, :role)
            """), {
                "cid":  cycle_id,
                "eid":  ce.entity_id,
                "code": ce.comparison_code,
                "role": ce.role,
            })

    # 6. Scope snapshot — only when PLANNED_CYCLE_SCOPE_RESYNC is off.
    # With it on (default), the Planned cycle inherits live from entity
    # templates until it starts running (see scope_resolution.py); no rows
    # are written here. Separate small ORM transaction since the insert
    # above is raw SQL/Core.
    if not config.PLANNED_CYCLE_SCOPE_RESYNC:
        with session_factory() as session:
            cycle_obj = session.get(SoaCycle, cycle_id)
            if cycle_obj is not None:
                materialize_and_freeze(cycle_obj, session, freeze=False)
                session.commit()

    return CycleStatusResponse(
        cycle_code=data.cycle_code,
        status="planned",
        study_type=data.study_type,
        study_pattern=study_pattern,
        total_runs_planned=total_runs,
        completed_runs=0,
        created_at=str(created_at) if created_at else None,
        platforms=data.platforms,
        runs_per_query=data.runs_per_query,
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
              updated_at, platforms, runs_per_query, id
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
              updated_at, platforms, runs_per_query, id
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
    return CycleStatusResponse(
        cycle_code=row[0],
        status=row[1],
        study_type=row[2],
        study_pattern=row[3],
        total_runs_planned=row[4] or 0,
        completed_runs=row[5] or 0,
        created_at=str(row[6])[:19] if row[6] else None,
        updated_at=str(row[7])[:19] if row[7] else None,
        platforms=json.loads(row[8]) if isinstance(row[8], str) else row[8],
        runs_per_query=row[9],
        id=row[10] if len(row) > 10 else None,
    )
