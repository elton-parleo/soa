"""
Tests for POST /api/cycles accepting cycle_mode='truecost' + truecost_tiers
(apps/api/app/routers/cycles.py::create_cycle), and the pydantic validation
in app/schemas.py::CreateCycleRequest.

Calls the route function directly (FastAPI's @router.post decorator returns
the underlying function unchanged), same pattern as
test_truecost_snapshots_endpoint.py — a real in-memory SQLite database
stands in for engine.begin()/engine.connect() since create_cycle issues raw
SQL via sqlalchemy.text().
"""
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine

import app.routers.cycles as cycles_router
from app.schemas import ComparisonEntityInput, CreateCycleRequest

CURRENT_USER = {"organization_id": 1, "user_id": "u1"}


@pytest.fixture
def patched_engine(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, cycle_code TEXT UNIQUE, start_date DATE,
                end_date DATE, total_runs_planned INTEGER, completed_runs INTEGER,
                status TEXT, notes TEXT, platforms TEXT, runs_per_query INTEGER,
                study_type TEXT, study_pattern TEXT,
                scope_frozen_at TIMESTAMP, scope_is_custom BOOLEAN,
                organization_id INTEGER, created_by TEXT,
                cycle_mode TEXT DEFAULT 'query', truecost_tiers TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_queries (
                id INTEGER PRIMARY KEY, study_type TEXT, status TEXT,
                study_pattern TEXT, organization_id INTEGER
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycle_entities (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                comparison_code TEXT, role TEXT
            )
        """)
    monkeypatch.setattr(cycles_router, "engine", engine)
    return engine


def _comparison_set(*entity_ids):
    return [
        ComparisonEntityInput(
            entity_id=eid,
            comparison_code=f"M{str(i + 1).zfill(3)}",
            role="primary" if i == 0 else "competitor",
        )
        for i, eid in enumerate(entity_ids)
    ]


# ─── Schema validation ──────────────────────────────────────────────────────

def test_schema_defaults_cycle_mode_to_query():
    req = CreateCycleRequest(
        cycle_code="q1", study_type="retailer_sephora", platforms=["chatgpt"],
        runs_per_query=5, comparison_set=_comparison_set(1, 2),
    )
    assert req.cycle_mode == "query"


def test_schema_rejects_invalid_cycle_mode():
    with pytest.raises(ValidationError):
        CreateCycleRequest(
            cycle_code="x", cycle_mode="bogus",
            comparison_set=_comparison_set(1),
        )


def test_schema_query_mode_requires_study_type_platforms_runs():
    with pytest.raises(ValidationError):
        CreateCycleRequest(cycle_code="q1", comparison_set=_comparison_set(1, 2))


def test_schema_truecost_mode_requires_at_least_one_entity():
    with pytest.raises(ValidationError):
        CreateCycleRequest(
            cycle_code="t1", cycle_mode="truecost",
            truecost_tiers=[None], comparison_set=[],
        )


def test_schema_truecost_mode_requires_at_least_one_tier():
    with pytest.raises(ValidationError):
        CreateCycleRequest(
            cycle_code="t1", cycle_mode="truecost",
            comparison_set=_comparison_set(1),
        )


def test_schema_truecost_mode_accepts_baseline_only():
    req = CreateCycleRequest(
        cycle_code="t1", cycle_mode="truecost",
        truecost_tiers=[None], comparison_set=_comparison_set(1),
    )
    assert req.truecost_tiers == [None]


# ─── create_cycle endpoint ──────────────────────────────────────────────────

def test_create_cycle_truecost_does_not_require_study_fields(patched_engine):
    data = CreateCycleRequest(
        cycle_code="truecost-sweep-1",
        cycle_mode="truecost",
        truecost_tiers=[None, "Rouge"],
        comparison_set=_comparison_set(7),
    )
    result = cycles_router.create_cycle(data, current_user=CURRENT_USER)

    assert result.cycle_mode == "truecost"
    assert result.study_type is None
    assert result.platforms is None
    assert result.runs_per_query is None
    assert result.truecost_tiers == [None, "Rouge"]
    assert result.status == "planned"


def test_create_cycle_truecost_persists_cycle_mode_and_tiers(patched_engine):
    data = CreateCycleRequest(
        cycle_code="truecost-sweep-2",
        cycle_mode="truecost",
        truecost_tiers=[None, "Rouge", "Insider"],
        comparison_set=_comparison_set(7, 8),
    )
    cycles_router.create_cycle(data, current_user=CURRENT_USER)

    with patched_engine.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT cycle_mode, truecost_tiers FROM soa_cycles WHERE cycle_code = 'truecost-sweep-2'"
        ).fetchone()
    assert row[0] == "truecost"
    assert row[1] == '[null, "Rouge", "Insider"]'.replace(" ", "") or "Rouge" in row[1]


def test_create_cycle_truecost_writes_comparison_set(patched_engine):
    data = CreateCycleRequest(
        cycle_code="truecost-sweep-3",
        cycle_mode="truecost",
        truecost_tiers=[None],
        comparison_set=_comparison_set(7, 8, 9),
    )
    cycles_router.create_cycle(data, current_user=CURRENT_USER)

    with patched_engine.connect() as conn:
        rows = conn.exec_driver_sql(
            """
            SELECT ce.entity_id FROM soa_cycle_entities ce
            JOIN soa_cycles c ON c.id = ce.cycle_id
            WHERE c.cycle_code = 'truecost-sweep-3'
            """
        ).fetchall()
    assert {r[0] for r in rows} == {7, 8, 9}


def test_create_cycle_query_mode_unchanged(patched_engine):
    """Existing query-cycle behavior is untouched: study_pattern/total_runs
    still come from soa_queries, cycle_mode defaults to 'query'."""
    with patched_engine.begin() as conn:
        conn.exec_driver_sql("""
            INSERT INTO soa_queries (study_type, status, study_pattern, organization_id)
            VALUES ('retailer_sephora', 'Active', 'retailer', 1)
        """)

    data = CreateCycleRequest(
        cycle_code="query-cycle-1",
        study_type="retailer_sephora",
        platforms=["chatgpt"],
        runs_per_query=5,
        comparison_set=_comparison_set(1, 2),
    )
    result = cycles_router.create_cycle(data, current_user=CURRENT_USER)

    assert result.cycle_mode == "query"
    assert result.study_type == "retailer_sephora"
    assert result.study_pattern == "retailer"
    assert result.total_runs_planned == 1 * 1 * 5
    assert result.truecost_tiers is None
