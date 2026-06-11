from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from sqlalchemy import text
from collections import defaultdict
from soa_shared.database import engine
from app.schemas import (
    StudyResponse,
    StudyQueryBreakdown,
    QueryCreate,
    QueryUpdate,
    STUDY_TYPE_NAMES,
    PATTERN_DISPLAY,
)

router = APIRouter()


@router.get("/studies", response_model=list[StudyResponse])
def get_studies():
    """
    Returns all study types that have at least one Active query.
    Builds one StudyResponse per study_type with:
    - name from STUDY_TYPE_NAMES or title-cased from id
    - category from most common category value across queries
    - patterns deduplicated and mapped to display labels
    - queryCount total active queries
    - lastRun from most recent soa_run for any cycle of this study_type
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
              q.study_type,
              q.category,
              q.study_pattern,
              COUNT(*) AS query_count
            FROM soa_queries q
            WHERE q.status = 'Active'
            GROUP BY q.study_type, q.category, q.study_pattern
            ORDER BY q.study_type
        """)).fetchall()

        last_runs = conn.execute(text("""
            SELECT c.study_type, MAX(r.run_at) AS last_run
            FROM soa_runs r
            JOIN soa_cycles c ON c.id = r.cycle_id
            GROUP BY c.study_type
        """)).fetchall()

    last_run_map = {
        row[0]: str(row[1])[:10] if row[1] else None
        for row in last_runs
    }

    by_type = defaultdict(lambda: {
        "categories": defaultdict(int),
        "patterns":   set(),
        "count":      0,
    })

    for row in rows:
        st  = row[0]
        cat = row[1]
        pat = row[2]
        cnt = row[3]
        by_type[st]["categories"][cat] += cnt
        by_type[st]["patterns"].add(pat)
        by_type[st]["count"] += cnt

    results = []
    for study_type, data in by_type.items():
        category = max(data["categories"], key=data["categories"].get)
        patterns = list({PATTERN_DISPLAY.get(p, p) for p in data["patterns"]})
        name = STUDY_TYPE_NAMES.get(
            study_type,
            study_type.replace("_", " ").title(),
        )
        results.append(StudyResponse(
            id=study_type,
            name=name,
            category=category,
            patterns=patterns,
            queryCount=data["count"],
            lastRun=last_run_map.get(study_type),
        ))

    return sorted(results, key=lambda s: s.name)


@router.get("/studies/{study_type}/queries", response_model=StudyQueryBreakdown)
def get_study_queries(study_type: str):
    """
    Returns query count and pattern breakdown for a specific study type.
    Used by the wizard Step 5 review panel.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT study_pattern, COUNT(*) AS cnt
            FROM soa_queries
            WHERE study_type = :st AND status = 'Active'
            GROUP BY study_pattern
        """), {"st": study_type}).fetchall()

    by_pattern = {PATTERN_DISPLAY.get(r[0], r[0]): r[1] for r in rows}
    total = sum(by_pattern.values())

    return StudyQueryBreakdown(
        study_type=study_type,
        total=total,
        by_pattern=by_pattern,
    )


@router.get("/studies/{study_type}/query-rows")
def get_study_query_rows(
    study_type: str,
    stage:        Optional[str] = Query(None),
    specificity:  Optional[str] = Query(None),
    persona:      Optional[str] = Query(None),
    status:       Optional[str] = Query(None),
):
    """
    Returns all individual query rows for a given study_type from soa_queries.
    Supports optional server-side filtering by stage, specificity, persona, status.
    (Frontend also filters client-side, so server params are optional.)
    """
    with engine.connect() as conn:
        conditions = ["study_type = :study_type"]
        params = {"study_type": study_type}

        if stage and stage != "All":
            conditions.append("stage = :stage")
            params["stage"] = stage

        if specificity and specificity != "All":
            conditions.append("specificity = :specificity")
            params["specificity"] = specificity

        if persona and persona != "All":
            conditions.append("persona = :persona")
            params["persona"] = persona

        if status and status != "All":
            conditions.append("LOWER(status) = LOWER(:status)")
            params["status"] = status

        where = " AND ".join(conditions)

        rows = conn.execute(text(f"""
            SELECT
              query_code,
              query_text,
              category,
              stage,
              specificity,
              persona,
              study_type,
              study_pattern,
              status,
              soa_focus,
              rationale,
              created_at
            FROM soa_queries
            WHERE {where}
            ORDER BY query_code
        """), params).fetchall()

    return [
        {
            "query_code":    r[0],
            "query_text":    r[1],
            "category":      r[2],
            "stage":         r[3],
            "specificity":   r[4],
            "persona":       r[5],
            "study_type":    r[6],
            "study_pattern": r[7],
            "status":        r[8],
            "soa_focus":     r[9],
            "rationale":     r[10],
            "created_at":    str(r[11])[:10] if r[11] else None,
        }
        for r in rows
    ]


# ─── Query code prefix helper ─────────────────────────────────────────────────

def _query_code_prefix(study_type: str) -> str:
    """
    Derive a short uppercase prefix from the study_type slug for use in
    auto-generated query codes.
    e.g. brand_gillette → GIL,  brand_oral_b → ORL,  retailer_target → TGT
    """
    name = study_type
    for pfx in ['brand_', 'retailer_', 'sonic_', 'senso_']:
        if name.startswith(pfx):
            name = name[len(pfx):]
            break
    first_word = name.split('_')[0]
    return first_word[:3].upper()


# ─── POST /studies/{study_type}/queries — create new query ────────────────────

@router.post("/studies/{study_type}/queries", status_code=201)
def create_query(study_type: str, data: QueryCreate):
    """
    Creates a new query in soa_queries for the given study_type.
    Auto-generates query_code in the format PREFIX_NNN.
    """
    with engine.connect() as conn:
        # Count existing queries for this study_type to generate next code
        count_row = conn.execute(
            text("SELECT COUNT(*) FROM soa_queries WHERE study_type = :st"),
            {"st": study_type},
        ).fetchone()
        next_num = (count_row[0] or 0) + 1

        prefix = _query_code_prefix(study_type)
        query_code = f"{prefix}_{next_num:03d}"

        # Check uniqueness — increment on collision
        while True:
            exists = conn.execute(
                text("SELECT 1 FROM soa_queries WHERE query_code = :code"),
                {"code": query_code},
            ).fetchone()
            if not exists:
                break
            next_num += 1
            query_code = f"{prefix}_{next_num:03d}"

        # category/stage/specificity/persona are NOT NULL in the schema
        result = conn.execute(
            text("""
                INSERT INTO soa_queries (
                    query_code, query_text, category, stage,
                    specificity, persona, study_type, study_pattern,
                    soa_focus, rationale, status, created_at
                ) VALUES (
                    :query_code, :query_text, :category, :stage,
                    :specificity, :persona, :study_type, :study_pattern,
                    :soa_focus, :rationale, :status, NOW()
                )
                RETURNING
                    id, query_code, query_text, category, stage,
                    specificity, persona, study_type, study_pattern,
                    status, soa_focus, rationale, created_at
            """),
            {
                "query_code":    query_code,
                "query_text":    data.query_text,
                "category":      data.category    or "",
                "stage":         data.stage       or "",
                "specificity":   data.specificity or "",
                "persona":       data.persona     or "",
                "study_type":    study_type,
                "study_pattern": data.study_pattern or "",
                "soa_focus":     data.soa_focus,
                "rationale":     data.rationale,
                "status":        data.status,
            },
        )
        conn.commit()
        row = result.fetchone()

    return {
        "query_code":    row[1],
        "query_text":    row[2],
        "category":      row[3],
        "stage":         row[4],
        "specificity":   row[5],
        "persona":       row[6],
        "study_type":    row[7],
        "study_pattern": row[8],
        "status":        row[9],
        "soa_focus":     row[10],
        "rationale":     row[11],
        "created_at":    str(row[12])[:10] if row[12] else None,
    }


# ─── PATCH /studies/{study_type}/queries/{query_code} — update query ──────────

@router.patch("/studies/{study_type}/queries/{query_code}")
def update_query(study_type: str, query_code: str, data: QueryUpdate):
    """
    Updates an existing query by query_code within a study_type.
    Only provided (non-None) fields are updated via a dynamic SET clause.
    Returns the updated query row.
    """
    with engine.connect() as conn:
        existing = conn.execute(
            text("""
                SELECT id FROM soa_queries
                WHERE query_code = :code AND study_type = :st
            """),
            {"code": query_code, "st": study_type},
        ).fetchone()

        if not existing:
            raise HTTPException(
                status_code=404,
                detail=f"Query '{query_code}' not found in study '{study_type}'.",
            )

        # Build SET clause from only the fields actually provided
        updates = {}
        for field in [
            "query_text", "category", "stage", "specificity",
            "persona", "study_pattern", "soa_focus", "rationale", "status",
        ]:
            val = getattr(data, field)
            if val is not None:
                updates[field] = val

        if not updates:
            raise HTTPException(status_code=422, detail="No fields to update.")

        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        params = {**updates, "code": query_code, "st": study_type}

        result = conn.execute(
            text(f"""
                UPDATE soa_queries
                SET {set_clause}, updated_at = NOW()
                WHERE query_code = :code AND study_type = :st
                RETURNING
                    query_code, query_text, category, stage,
                    specificity, persona, study_type, study_pattern,
                    status, soa_focus, rationale, created_at, updated_at
            """),
            params,
        )
        conn.commit()
        row = result.fetchone()

    return {
        "query_code":    row[0],
        "query_text":    row[1],
        "category":      row[2],
        "stage":         row[3],
        "specificity":   row[4],
        "persona":       row[5],
        "study_type":    row[6],
        "study_pattern": row[7],
        "status":        row[8],
        "soa_focus":     row[9],
        "rationale":     row[10],
        "created_at":    str(row[11])[:10] if row[11] else None,
        "updated_at":    str(row[12])[:19] if row[12] else None,
    }
