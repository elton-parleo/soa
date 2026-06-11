from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from datetime import date
import json
from soa_shared.database import engine
from app.schemas import (
    CreateCycleRequest,
    CycleStatusResponse,
    CycleCheckResponse,
    PATTERN_DISPLAY,
)

router = APIRouter()


@router.get("/cycles/check", response_model=CycleCheckResponse)
def check_cycle_code(code: str = Query(...)):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT 1 FROM soa_cycles WHERE cycle_code = :code
        """), {"code": code}).fetchone()
    return CycleCheckResponse(available=row is None, cycle_code=code)


@router.post("/cycles", response_model=CycleStatusResponse, status_code=201)
def create_cycle(data: CreateCycleRequest):
    """
    Creates a new cycle and its comparison set in the database with
    status='planned'.

    The pipeline worker in apps/pipeline/ polls for status='planned' and
    executes the cycle. This endpoint returns immediately without running
    anything.
    """
    with engine.begin() as conn:

        # 1. Check code availability
        exists = conn.execute(text("""
            SELECT 1 FROM soa_cycles WHERE cycle_code = :code
        """), {"code": data.cycle_code}).fetchone()
        if exists:
            raise HTTPException(
                status_code=409,
                detail=f"Cycle code '{data.cycle_code}' is already taken.",
            )

        # 2. Detect study_pattern
        patterns = conn.execute(text("""
            SELECT DISTINCT study_pattern
            FROM soa_queries
            WHERE study_type = :st AND status = 'Active'
        """), {"st": data.study_type}).fetchall()

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

        # 3. Count queries
        query_count = conn.execute(text("""
            SELECT COUNT(*) FROM soa_queries
            WHERE study_type = :st AND status = 'Active'
        """), {"st": data.study_type}).scalar()

        total_runs = (
            query_count * len(data.platforms) * data.runs_per_query
        )

        # 4. Create cycle
        cycle_row = conn.execute(text("""
            INSERT INTO soa_cycles (
                cycle_code, study_type, study_pattern, status,
                total_runs_planned, completed_runs, start_date, notes,
                platforms, runs_per_query
            ) VALUES (
                :code, :st, :sp, 'planned', :total, 0, :today, :notes,
                :platforms, :runs_per_query
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
    )


@router.get("/cycles", response_model=list[CycleStatusResponse])
def list_cycles():
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
              cycle_code, status, study_type, study_pattern,
              total_runs_planned, completed_runs, created_at,
              updated_at, platforms, runs_per_query
            FROM soa_cycles
            ORDER BY created_at DESC
        """)).fetchall()
    return [_row_to_cycle(r) for r in rows]


@router.get("/cycles/{cycle_code}", response_model=CycleStatusResponse)
def get_cycle(cycle_code: str):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT
              cycle_code, status, study_type, study_pattern,
              total_runs_planned, completed_runs, created_at,
              updated_at, platforms, runs_per_query
            FROM soa_cycles
            WHERE cycle_code = :code
        """), {"code": cycle_code}).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Cycle '{cycle_code}' not found",
        )
    return _row_to_cycle(row)


@router.post("/cycles/{cycle_code}/resume")
def resume_cycle(cycle_code: str):
    """
    Resume a failed cycle by setting its status back to 'planned'.
    The pipeline worker polls for 'planned' cycles every 30s and
    will pick it up automatically.

    Only cycles with status 'failed' can be resumed. Returns 409 if
    the cycle is not in failed state.
    """
    with engine.connect() as conn:
        # Check current status
        row = conn.execute(text("""
            SELECT id, status
            FROM soa_cycles
            WHERE cycle_code = :code
        """), {"code": cycle_code}).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Cycle '{cycle_code}' not found.",
            )

        current_status = row[1]
        if current_status != 'failed':
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cycle is '{current_status}'"
                    f" — only failed cycles can be resumed."
                ),
            )

        # Set status back to planned and update timestamp
        conn.execute(text("""
            UPDATE soa_cycles
            SET
              status = 'planned',
              updated_at = NOW()
            WHERE cycle_code = :code
        """), {"code": cycle_code})
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
    )
