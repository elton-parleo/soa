"""
Tests for GET /api/public/soa-lite/{token}/status
(app/routers/public_lite.py::get_lite_status), and _derive_phase directly
for the full cross-product of lite/cycle status combinations.
"""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine

import app.routers.public_lite as public_lite


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_requests (
                id INTEGER PRIMARY KEY, token TEXT UNIQUE, status TEXT,
                cycle_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, status TEXT,
                completed_runs INTEGER, total_runs_planned INTEGER
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_scan_results (
                id INTEGER PRIMARY KEY, lite_request_id INTEGER UNIQUE, status TEXT
            )
        """)
    monkeypatch.setattr(public_lite, "engine", engine)
    return engine


def _insert_lite(conn, token, status, cycle_id=None):
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_requests (token, status, cycle_id) VALUES (?, ?, ?)",
        (token, status, cycle_id),
    )


def _insert_cycle(conn, cycle_id, status, completed_runs=None, total_runs_planned=None):
    conn.exec_driver_sql(
        "INSERT INTO soa_cycles (id, status, completed_runs, total_runs_planned) VALUES (?, ?, ?, ?)",
        (cycle_id, status, completed_runs, total_runs_planned),
    )


def _insert_scan(conn, lite_request_id, status):
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_scan_results (lite_request_id, status) VALUES (?, ?)",
        (lite_request_id, status),
    )


# ─── 404 ──────────────────────────────────────────────────────────────────

def test_unknown_token_returns_404(db):
    with pytest.raises(HTTPException) as exc_info:
        public_lite.get_lite_status("no-such-token")
    assert exc_info.value.status_code == 404


# ─── phases without a cycle yet ─────────────────────────────────────────

def test_pending_maps_to_queued(db):
    with db.begin() as conn:
        _insert_lite(conn, "t1", "pending")
    result = public_lite.get_lite_status("t1")
    assert result.status == "pending"
    assert result.phase == "queued"
    assert result.progress is None


def test_generating_maps_to_generating_queries(db):
    with db.begin() as conn:
        _insert_lite(conn, "t1", "generating")
    result = public_lite.get_lite_status("t1")
    assert result.phase == "generating_queries"


def test_failed_maps_to_failed(db):
    with db.begin() as conn:
        _insert_lite(conn, "t1", "failed")
    result = public_lite.get_lite_status("t1")
    assert result.phase == "failed"


def test_complete_maps_to_complete(db):
    with db.begin() as conn:
        _insert_lite(conn, "t1", "complete")
    result = public_lite.get_lite_status("t1")
    assert result.phase == "complete"


# ─── phases with a cycle (lite status = 'running') ──────────────────────

def test_running_lite_with_planned_cycle_is_queued(db):
    with db.begin() as conn:
        _insert_cycle(conn, 1, "planned")
        _insert_lite(conn, "t1", "running", cycle_id=1)
    result = public_lite.get_lite_status("t1")
    assert result.phase == "queued"


def test_running_lite_with_running_cycle_partial_progress_is_running(db):
    with db.begin() as conn:
        _insert_cycle(conn, 1, "running", completed_runs=0, total_runs_planned=12)
        _insert_lite(conn, "t1", "running", cycle_id=1)
    result = public_lite.get_lite_status("t1")
    assert result.phase == "running"
    assert result.progress.completed_runs == 0
    assert result.progress.total_runs == 12


def test_running_lite_with_all_runs_done_is_analyzing(db):
    with db.begin() as conn:
        _insert_cycle(conn, 1, "running", completed_runs=12, total_runs_planned=12)
        _insert_lite(conn, "t1", "running", cycle_id=1)
    result = public_lite.get_lite_status("t1")
    assert result.phase == "analyzing"
    assert result.progress.completed_runs == 12
    assert result.progress.total_runs == 12


def test_running_lite_with_running_cycle_null_completed_runs_is_running(db):
    with db.begin() as conn:
        _insert_cycle(conn, 1, "running", completed_runs=None, total_runs_planned=12)
        _insert_lite(conn, "t1", "running", cycle_id=1)
    result = public_lite.get_lite_status("t1")
    assert result.phase == "running"
    assert result.progress.completed_runs == 0


def test_running_lite_with_complete_cycle_is_complete(db):
    """Defensive: covers the brief window before _sweep_lite_completions catches up."""
    with db.begin() as conn:
        _insert_cycle(conn, 1, "complete", completed_runs=12, total_runs_planned=12)
        _insert_lite(conn, "t1", "running", cycle_id=1)
    result = public_lite.get_lite_status("t1")
    assert result.phase == "complete"


def test_running_lite_with_failed_cycle_is_failed(db):
    with db.begin() as conn:
        _insert_cycle(conn, 1, "failed")
        _insert_lite(conn, "t1", "running", cycle_id=1)
    result = public_lite.get_lite_status("t1")
    assert result.phase == "failed"


# ─── scan_status ─────────────────────────────────────────────────────────

def test_scan_status_null_when_no_scan_row_exists(db):
    with db.begin() as conn:
        _insert_lite(conn, "t1", "running")
    result = public_lite.get_lite_status("t1")
    assert result.scan_status is None


@pytest.mark.parametrize("scan_status", ["running", "complete", "blocked", "failed", "skipped"])
def test_scan_status_mirrors_scan_row(db, scan_status):
    with db.begin() as conn:
        _insert_lite(conn, "t1", "running")
        lite_id = conn.exec_driver_sql(
            "SELECT id FROM soa_lite_requests WHERE token = 't1'"
        ).fetchone()[0]
        _insert_scan(conn, lite_id, scan_status)

    result = public_lite.get_lite_status("t1")
    assert result.scan_status == scan_status


def test_scan_status_does_not_affect_lite_phase(db):
    """The lite phase is still driven by lite/cycle status alone — the
    scan reaching a terminal state never changes it (rule 7)."""
    with db.begin() as conn:
        _insert_cycle(conn, 1, "running", completed_runs=6, total_runs_planned=12)
        _insert_lite(conn, "t1", "running", cycle_id=1)
        lite_id = conn.exec_driver_sql(
            "SELECT id FROM soa_lite_requests WHERE token = 't1'"
        ).fetchone()[0]
        _insert_scan(conn, lite_id, "failed")

    result = public_lite.get_lite_status("t1")
    assert result.phase == "running"
    assert result.scan_status == "failed"


# ─── _derive_phase unit coverage (direct, no DB) ────────────────────────

@pytest.mark.parametrize("lite_status,expected_phase", [
    ("pending", "queued"),
    ("generating", "generating_queries"),
    ("complete", "complete"),
    ("failed", "failed"),
])
def test_derive_phase_terminal_and_pre_cycle_states(lite_status, expected_phase):
    phase, progress = public_lite._derive_phase(lite_status, None, None, None)
    assert phase == expected_phase
    assert progress is None
