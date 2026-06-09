from fastapi import APIRouter
from sqlalchemy import text
from collections import defaultdict
from soa_shared.database import engine
from app.schemas import (
    StudyResponse,
    StudyQueryBreakdown,
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
