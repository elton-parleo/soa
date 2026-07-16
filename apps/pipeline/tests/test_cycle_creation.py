"""
Tests for soa_shared/cycle_creation.py::create_cycle_with_comparison_set,
extracted from apps/api/app/routers/cycles.py::create_cycle so the SoA Lite
worker can create cycles the same way. cycles.py's own tests
(test_create_cycle_truecost.py) prove create_cycle's behavior is unchanged
by the extraction; these tests cover the helper directly.
"""
import pytest
from sqlalchemy import create_engine

from soa_shared.cycle_creation import create_cycle_with_comparison_set


@pytest.fixture
def conn():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as c:
        c.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, cycle_code TEXT UNIQUE, study_type TEXT,
                study_pattern TEXT, status TEXT, cycle_mode TEXT, truecost_tiers TEXT,
                total_runs_planned INTEGER, completed_runs INTEGER, start_date DATE,
                notes TEXT, platforms TEXT, runs_per_query INTEGER,
                organization_id INTEGER, created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.exec_driver_sql("""
            CREATE TABLE soa_cycle_entities (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                comparison_code TEXT, role TEXT
            )
        """)
    with engine.connect() as c:
        yield c
    engine.dispose()


def _comparison_set():
    return [
        {"entity_id": 1, "comparison_code": "M001", "role": "primary"},
        {"entity_id": 2, "comparison_code": "M002", "role": "competitor"},
        {"entity_id": 3, "comparison_code": "M003", "role": "competitor"},
    ]


def test_inserts_cycle_row_planned(conn):
    cycle_id, created_at = create_cycle_with_comparison_set(
        conn,
        cycle_code="lite-abcd1234",
        study_type="lite-abcd1234",
        study_pattern="brand_vs_brand",
        cycle_mode="query",
        truecost_tiers=None,
        total_runs_planned=12,
        start_date="2026-07-15",
        platforms='["chatgpt"]',
        runs_per_query=1,
        organization_id=99,
        created_by="soa-lite",
        notes=None,
        comparison_set=_comparison_set(),
    )
    conn.commit()

    assert created_at is not None
    row = conn.exec_driver_sql(
        "SELECT status, cycle_mode, study_pattern, total_runs_planned, organization_id, created_by "
        "FROM soa_cycles WHERE id = ?", (cycle_id,),
    ).fetchone()
    assert row == ("planned", "query", "brand_vs_brand", 12, 99, "soa-lite")


def test_inserts_comparison_set_rows(conn):
    cycle_id, _ = create_cycle_with_comparison_set(
        conn,
        cycle_code="lite-abcd1234",
        study_type="lite-abcd1234",
        study_pattern="brand_vs_brand",
        cycle_mode="query",
        truecost_tiers=None,
        total_runs_planned=12,
        start_date="2026-07-15",
        platforms='["chatgpt"]',
        runs_per_query=1,
        organization_id=99,
        created_by="soa-lite",
        notes=None,
        comparison_set=_comparison_set(),
    )
    conn.commit()

    rows = conn.exec_driver_sql(
        "SELECT entity_id, comparison_code, role FROM soa_cycle_entities WHERE cycle_id = ? ORDER BY comparison_code",
        (cycle_id,),
    ).fetchall()
    assert rows == [
        (1, "M001", "primary"),
        (2, "M002", "competitor"),
        (3, "M003", "competitor"),
    ]
