"""
C1/C2: soa_cycles.completed_runs is written exactly ONCE, at the very end
of the Runner stage (RunOrchestrator._finalize_cycle) — never
incrementally — so a RUNNING cycle's dashboard card sat at 0 the entire
time queries were actually executing, then jumped straight to the final
count on completion. The public lite status page hit the identical bug
and fixed it by counting soa_runs rows live instead
(public_lite._fetch_live_progress_counts); cycles.py::_live_completed_runs
reuses that same helper for GET /api/cycles and GET /api/cycles/{code}.

Calls the route functions directly (same pattern as
test_create_cycle_truecost.py) against a real in-memory SQLite database.
"""
import pytest
from sqlalchemy import create_engine

import app.routers.cycles as cycles_router

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
                organization_id INTEGER, created_by TEXT,
                cycle_mode TEXT DEFAULT 'query', truecost_tiers TEXT,
                extraction_validation TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, status TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_coded_mentions (
                id INTEGER PRIMARY KEY, run_id INTEGER
            )
        """)
    monkeypatch.setattr(cycles_router, "engine", engine)
    return engine


def _seed_cycle(engine, *, cycle_code, status, total_runs_planned, completed_runs, cycle_mode="query", platforms='["chatgpt"]'):
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            INSERT INTO soa_cycles
              (cycle_code, status, total_runs_planned, completed_runs,
               organization_id, cycle_mode, platforms, runs_per_query)
            VALUES (?, ?, ?, ?, 1, ?, ?, 5)
            """,
            (cycle_code, status, total_runs_planned, completed_runs, cycle_mode, platforms),
        )
        cycle_id = conn.exec_driver_sql(
            "SELECT id FROM soa_cycles WHERE cycle_code = ?", (cycle_code,)
        ).fetchone()[0]
    return cycle_id


def _seed_runs(engine, cycle_id, statuses):
    with engine.begin() as conn:
        for status in statuses:
            conn.exec_driver_sql(
                "INSERT INTO soa_runs (cycle_id, status) VALUES (?, ?)",
                (cycle_id, status),
            )


def test_running_cycle_reports_live_resolved_run_count_not_the_stale_zero(patched_engine):
    cycle_id = _seed_cycle(
        patched_engine, cycle_code="c-running", status="running",
        total_runs_planned=24, completed_runs=0,
    )
    _seed_runs(patched_engine, cycle_id, ["success", "success", "error", "pending", "pending"])

    result = cycles_router.get_cycle("c-running", current_user=CURRENT_USER)

    assert result.completed_runs == 3
    assert result.total_runs_planned == 24


def test_running_cycle_progress_increases_as_more_runs_resolve(patched_engine):
    cycle_id = _seed_cycle(
        patched_engine, cycle_code="c-progress", status="running",
        total_runs_planned=10, completed_runs=0,
    )
    _seed_runs(patched_engine, cycle_id, ["success"])
    first = cycles_router.get_cycle("c-progress", current_user=CURRENT_USER)
    assert first.completed_runs == 1

    _seed_runs(patched_engine, cycle_id, ["success", "success", "timeout"])
    second = cycles_router.get_cycle("c-progress", current_user=CURRENT_USER)
    assert second.completed_runs == 4


def test_complete_cycle_uses_the_stored_column_not_a_live_recount(patched_engine):
    cycle_id = _seed_cycle(
        patched_engine, cycle_code="c-done", status="complete",
        total_runs_planned=24, completed_runs=24,
    )
    # Only 2 soa_runs rows exist (e.g. history was pruned) — a live count
    # would wrongly regress a finished cycle's card to "2/24".
    _seed_runs(patched_engine, cycle_id, ["success", "success"])

    result = cycles_router.get_cycle("c-done", current_user=CURRENT_USER)

    assert result.completed_runs == 24


def test_running_truecost_cycle_uses_the_stored_column_since_it_never_writes_soa_runs(patched_engine):
    _seed_cycle(
        patched_engine, cycle_code="c-tc", status="running",
        total_runs_planned=12, completed_runs=5, cycle_mode="truecost",
    )

    result = cycles_router.get_cycle("c-tc", current_user=CURRENT_USER)

    assert result.completed_runs == 5


def test_planned_cycle_uses_the_stored_column(patched_engine):
    _seed_cycle(
        patched_engine, cycle_code="c-planned", status="planned",
        total_runs_planned=24, completed_runs=0,
    )

    result = cycles_router.get_cycle("c-planned", current_user=CURRENT_USER)

    assert result.completed_runs == 0


def test_list_cycles_derives_each_running_cycle_live_independently(patched_engine):
    running_id = _seed_cycle(
        patched_engine, cycle_code="c-a", status="running",
        total_runs_planned=24, completed_runs=0,
    )
    _seed_runs(patched_engine, running_id, ["success", "success", "success"])
    _seed_cycle(
        patched_engine, cycle_code="c-b", status="complete",
        total_runs_planned=24, completed_runs=24,
    )

    results = {r.cycle_code: r for r in cycles_router.list_cycles(current_user=CURRENT_USER)}

    assert results["c-a"].completed_runs == 3
    assert results["c-b"].completed_runs == 24
