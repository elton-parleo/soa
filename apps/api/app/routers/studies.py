import csv
import io
import re
import uuid
from fastapi import APIRouter, Query, HTTPException, UploadFile, File
from typing import Optional
from sqlalchemy import text
from collections import defaultdict
from soa_shared.database import engine
from soa_shared.constants import QUERY_CONSTRAINTS
from app.schemas import (
    StudyResponse,
    StudyQueryBreakdown,
    QueryCreate,
    QueryUpdate,
    StudyGenerateRequest,
    StudyGenerateResponse,
    GenerationStatusResponse,
    STUDY_TYPE_NAMES,
    PATTERN_DISPLAY,
)

router = APIRouter()

# Pre-computed at startup — constraints never change at runtime
_CACHED_CONSTRAINTS = {k: list(v) for k, v in QUERY_CONSTRAINTS.items()}

# ─── CSV upload constants ─────────────────────────────────────────────────────

CSV_REQUIRED_COLUMNS = [
    'query_text',
    'category',
    'stage',
    'specificity',
    'persona',
    'study_type',
    'study_pattern',
    'status',
]

CSV_OPTIONAL_COLUMNS = [
    'soa_focus',
    'rationale',
    'query_code',
]


def _validate_csv_row(
    row: dict,
    row_num: int,
) -> tuple:
    """
    Validates one CSV row against soa_queries constraints.
    Returns (cleaned_row, errors).
    cleaned_row has None for empty optional fields.
    errors is a list of human-readable messages, empty if valid.
    """
    errors = []
    cleaned = {}

    for col in CSV_REQUIRED_COLUMNS:
        val = (row.get(col) or '').strip()
        if not val:
            errors.append(
                f"Row {row_num}: '{col}' is required but empty"
            )
        cleaned[col] = val or None

    for col in CSV_OPTIONAL_COLUMNS:
        val = (row.get(col) or '').strip()
        cleaned[col] = val or None

    for field, allowed in QUERY_CONSTRAINTS.items():
        val = cleaned.get(field)
        if val is None:
            continue
        if val not in allowed:
            errors.append(
                f"Row {row_num}: '{field}' value '{val}' is not valid. "
                f"Allowed: {', '.join(allowed)}"
            )

    return cleaned, errors


@router.get("/studies/constraints")
def get_query_constraints():
    """
    Returns all allowed values for constrained soa_queries fields.

    Used by the frontend to populate dropdown options dynamically.
    Values are sourced from soa_shared.constants — the same source used by
    SQLAlchemy CheckConstraints and Pydantic validators.

    Response shape:
    {
      "category":      [...],
      "stage":         [...],
      "specificity":   [...],
      "persona":       [...],
      "status":        [...],
      "study_pattern": [...]
    }
    """
    return _CACHED_CONSTRAINTS


# ─── AI generation helpers ────────────────────────────────────────────────────

def _slugify_study_name(name: str) -> str:
    """
    Converts a study name to a unique study_type slug.
    e.g. 'Brand Study' → 'brand_study_a1b2c3'
    Appends a short uuid suffix to avoid collisions.
    """
    slug = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    suffix = uuid.uuid4().hex[:6]
    return f"{slug}_{suffix}"


# ─── POST /studies/generate — create AI generation job ───────────────────────

@router.post("/studies/generate", response_model=StudyGenerateResponse, status_code=201)
def generate_study(data: StudyGenerateRequest):
    """
    Creates a generation job. The pipeline worker picks up pending jobs and
    generates queries via OpenAI in the background.

    Returns immediately with the new study_type so the frontend can redirect
    to the (initially empty) study detail page and poll for progress.
    """
    study_type = _slugify_study_name(data.study_name)

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                INSERT INTO soa_query_generation_jobs (
                    study_type, study_name, description,
                    target_count, status, created_at
                ) VALUES (
                    :study_type, :study_name, :description,
                    :target_count, 'pending', NOW()
                )
                RETURNING id, status
            """),
            {
                "study_type":   study_type,
                "study_name":   data.study_name,
                "description":  data.description,
                "target_count": data.target_count,
            },
        )
        conn.commit()
        row = result.fetchone()

    return StudyGenerateResponse(
        study_type=study_type,
        study_name=data.study_name,
        job_id=row[0],
        status=row[1],
    )


# ─── GET /studies/{study_type}/generation-status ─────────────────────────────

@router.get(
    "/studies/{study_type}/generation-status",
    response_model=GenerationStatusResponse,
)
def get_generation_status(study_type: str):
    """
    Returns the current status of a generation job for a study_type.
    Frontend polls this while status is 'pending' or 'running'.
    Returns 404 if no job exists for this study_type (e.g. CSV-uploaded
    studies have no generation job — this is normal).
    """
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT study_type, status, target_count,
                       created_count, error_message
                FROM soa_query_generation_jobs
                WHERE study_type = :st
            """),
            {"st": study_type},
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="No generation job found for this study.",
        )

    return GenerationStatusResponse(
        study_type=row[0],
        status=row[1],
        target_count=row[2],
        created_count=row[3],
        error_message=row[4],
    )


# ─── POST /studies/upload-csv — bulk CSV insert ───────────────────────────────

@router.post("/studies/upload-csv")
async def upload_study_csv(
    file: UploadFile = File(...),
):
    """
    Accepts a CSV file and bulk-inserts rows into soa_queries.

    Required columns: query_text, category, stage, specificity,
                      persona, study_type, study_pattern, status
    Optional columns: soa_focus, rationale, query_code
                      (query_code is auto-generated per study_type if blank)

    All rows are validated before any insert — if any row fails,
    zero rows are inserted (all-or-nothing).

    Returns: { "inserted": N, "study_types": [...], "errors": [] }
    On failure: 422 with { "errors": [...], "total_errors": N }
    """
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(
            status_code=400,
            detail="File must be a .csv file.",
        )

    try:
        raw = await file.read()
        text_content = raw.decode('utf-8-sig')  # strips BOM from Excel exports
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Could not read file. Ensure it is UTF-8 encoded CSV.",
        )

    try:
        reader = csv.DictReader(io.StringIO(text_content))
        rows = list(reader)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")

    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty.")

    header_cols = set(reader.fieldnames or [])
    missing_cols = [c for c in CSV_REQUIRED_COLUMNS if c not in header_cols]
    if missing_cols:
        raise HTTPException(
            status_code=422,
            detail={"errors": [
                f"CSV is missing required column: '{c}'"
                for c in missing_cols
            ]},
        )

    # Validate every row before inserting anything
    cleaned_rows = []
    all_errors = []

    for i, row in enumerate(rows, start=2):  # row 1 = header
        cleaned, errors = _validate_csv_row(row, i)
        if errors:
            all_errors.extend(errors)
        else:
            cleaned_rows.append(cleaned)

    if all_errors:
        raise HTTPException(
            status_code=422,
            detail={
                "errors":       all_errors[:50],
                "total_errors": len(all_errors),
            },
        )

    # All rows valid — insert
    study_types_seen = set()
    inserted = 0

    with engine.connect() as conn:
        # Pre-fetch existing query counts per study_type for code generation.
        # Also track codes assigned in this batch to avoid within-batch collisions.
        code_counters: dict = {}
        batch_codes: set = set()

        for row in cleaned_rows:
            study_type = row['study_type']
            study_types_seen.add(study_type)

            query_code = row.get('query_code')

            if not query_code:
                if study_type not in code_counters:
                    count_row = conn.execute(
                        text("SELECT COUNT(*) FROM soa_queries WHERE study_type = :st"),
                        {"st": study_type},
                    ).fetchone()
                    code_counters[study_type] = count_row[0] or 0

                prefix = _query_code_prefix(study_type)
                while True:
                    code_counters[study_type] += 1
                    candidate = f"{prefix}_{code_counters[study_type]:03d}"
                    if candidate in batch_codes:
                        continue
                    exists = conn.execute(
                        text("SELECT 1 FROM soa_queries WHERE query_code = :code"),
                        {"code": candidate},
                    ).fetchone()
                    if not exists:
                        query_code = candidate
                        break

            batch_codes.add(query_code)

            conn.execute(
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
                """),
                {
                    "query_code":    query_code,
                    "query_text":    row['query_text'],
                    "category":      row['category'],
                    "stage":         row['stage'],
                    "specificity":   row['specificity'],
                    "persona":       row['persona'],
                    "study_type":    study_type,
                    "study_pattern": row['study_pattern'],
                    "soa_focus":     row.get('soa_focus'),
                    "rationale":     row.get('rationale'),
                    "status":        row['status'],
                },
            )
            inserted += 1

        conn.commit()

    return {
        "inserted":    inserted,
        "study_types": sorted(study_types_seen),
        "errors":      [],
    }


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
