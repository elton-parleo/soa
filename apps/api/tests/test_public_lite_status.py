"""
Tests for GET /api/public/soa-lite/{token}/status
(app/routers/public_lite.py::get_lite_status), and _derive_phase directly
for the full cross-product of lite/cycle status combinations.

Stage 12 (P1/P2): progress and phase are derived from LIVE counts against
soa_runs/soa_coded_mentions — never from the stale, once-written
soa_cycles.completed_runs column — and the phase sequence now
distinguishes querying -> coding -> metrics (previously all collapsed
into one 'analyzing' bucket).
"""
import json
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
                cycle_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                competitor_names TEXT, competitor_source TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, status TEXT,
                completed_runs INTEGER, total_runs_planned INTEGER
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
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_scan_results (
                id INTEGER PRIMARY KEY, lite_request_id INTEGER UNIQUE, status TEXT
            )
        """)
    monkeypatch.setattr(public_lite, "engine", engine)
    return engine


def _insert_lite(conn, token, status, cycle_id=None, competitor_names=None, competitor_source=None):
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_requests (token, status, cycle_id, competitor_names, competitor_source) "
        "VALUES (?, ?, ?, ?, ?)",
        (token, status, cycle_id, json.dumps(competitor_names) if competitor_names is not None else None, competitor_source),
    )


def _insert_cycle(conn, cycle_id, status, total_runs_planned=None):
    conn.exec_driver_sql(
        "INSERT INTO soa_cycles (id, status, total_runs_planned) VALUES (?, ?, ?)",
        (cycle_id, status, total_runs_planned),
    )


def _insert_runs(conn, cycle_id, *, success=0, error=0, timeout=0, pending=0):
    for _ in range(success):
        conn.exec_driver_sql("INSERT INTO soa_runs (cycle_id, status) VALUES (?, 'success')", (cycle_id,))
    for _ in range(error):
        conn.exec_driver_sql("INSERT INTO soa_runs (cycle_id, status) VALUES (?, 'error')", (cycle_id,))
    for _ in range(timeout):
        conn.exec_driver_sql("INSERT INTO soa_runs (cycle_id, status) VALUES (?, 'timeout')", (cycle_id,))
    for _ in range(pending):
        conn.exec_driver_sql("INSERT INTO soa_runs (cycle_id, status) VALUES (?, 'pending')", (cycle_id,))


def _code_n_runs(conn, cycle_id, n):
    """Marks the first n success runs for this cycle as coded."""
    run_ids = [
        row[0] for row in conn.exec_driver_sql(
            "SELECT id FROM soa_runs WHERE cycle_id = ? AND status = 'success' ORDER BY id", (cycle_id,)
        ).fetchall()
    ][:n]
    for rid in run_ids:
        conn.exec_driver_sql("INSERT INTO soa_coded_mentions (run_id) VALUES (?)", (rid,))


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


def test_identifying_competitors_maps_to_identifying_competitors_phase(db):
    with db.begin() as conn:
        _insert_lite(conn, "t1", "identifying_competitors")
    result = public_lite.get_lite_status("t1")
    assert result.phase == "identifying_competitors"
    assert result.competitors is None  # Stage 13 (F3): null until generation completes


def test_generating_maps_to_generating_queries(db):
    with db.begin() as conn:
        _insert_lite(conn, "t1", "generating")
    result = public_lite.get_lite_status("t1")
    assert result.phase == "generating_queries"


def test_status_carries_competitors_once_generation_completes(db):
    with db.begin() as conn:
        _insert_lite(
            conn, "t1", "generating",
            competitor_names=["Rival", "Gen One"], competitor_source="mixed",
        )
    result = public_lite.get_lite_status("t1")
    assert result.competitors == ["Rival", "Gen One"]
    assert result.competitor_source == "mixed"


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


def test_running_lite_with_no_runs_yet_is_running_with_zero_progress(db):
    with db.begin() as conn:
        _insert_cycle(conn, 1, "running", total_runs_planned=12)
        _insert_lite(conn, "t1", "running", cycle_id=1)
    result = public_lite.get_lite_status("t1")
    assert result.phase == "running"
    assert result.progress.completed_runs == 0
    assert result.progress.total_runs == 12


def test_running_lite_advances_as_runs_are_persisted_live(db):
    """P1: progress reflects soa_runs rows as they're written — not a
    once-at-the-end column — so a live poll mid-runner-stage sees the
    true count (e.g. 3/12, later 7/12), not a stuck value."""
    with db.begin() as conn:
        _insert_cycle(conn, 1, "running", total_runs_planned=12)
        _insert_lite(conn, "t1", "running", cycle_id=1)
        _insert_runs(conn, 1, success=3)
    result = public_lite.get_lite_status("t1")
    assert result.phase == "running"
    assert result.progress.completed_runs == 3

    with db.begin() as conn:
        _insert_runs(conn, 1, success=4)
    result = public_lite.get_lite_status("t1")
    assert result.phase == "running"
    assert result.progress.completed_runs == 7


def test_crash_restart_never_regresses_or_double_counts_progress(db):
    """P1: progress is a pure read over already-persisted soa_runs rows —
    there is nothing incremental for a worker restart to corrupt. Polling
    status repeatedly with no new rows (simulating a crash/restart pause)
    must return the exact same count every time, and resuming with more
    rows must only ever move forward, never jump or double-count."""
    with db.begin() as conn:
        _insert_cycle(conn, 1, "running", total_runs_planned=12)
        _insert_lite(conn, "t1", "running", cycle_id=1)
        _insert_runs(conn, 1, success=5)

    for _ in range(3):  # repeated polls during the "stall" — must stay put
        result = public_lite.get_lite_status("t1")
        assert result.progress.completed_runs == 5

    # Worker "restarts" and resumes — only the genuinely new runs land.
    with db.begin() as conn:
        _insert_runs(conn, 1, success=5)
    result = public_lite.get_lite_status("t1")
    assert result.progress.completed_runs == 10

    with db.begin() as conn:
        _insert_runs(conn, 1, success=2)
    result = public_lite.get_lite_status("t1")
    assert result.progress.completed_runs == 12
    assert result.phase == "coding"


def test_errors_and_timeouts_count_toward_resolved_progress(db):
    """A query that errored or timed out has still been attempted — it
    should count toward "how far through the 12" honestly, not leave the
    bar looking stuck because it wasn't a clean success."""
    with db.begin() as conn:
        _insert_cycle(conn, 1, "running", total_runs_planned=12)
        _insert_lite(conn, "t1", "running", cycle_id=1)
        _insert_runs(conn, 1, success=8, error=2, timeout=1)
    result = public_lite.get_lite_status("t1")
    assert result.phase == "running"
    assert result.progress.completed_runs == 11


def test_all_runs_resolved_and_none_coded_yet_is_coding(db):
    with db.begin() as conn:
        _insert_cycle(conn, 1, "running", total_runs_planned=12)
        _insert_lite(conn, "t1", "running", cycle_id=1)
        _insert_runs(conn, 1, success=12)
    result = public_lite.get_lite_status("t1")
    assert result.phase == "coding"
    assert result.progress.completed_runs == 12
    assert result.progress.total_runs == 12


def test_some_runs_coded_still_reports_coding(db):
    with db.begin() as conn:
        _insert_cycle(conn, 1, "running", total_runs_planned=12)
        _insert_lite(conn, "t1", "running", cycle_id=1)
        _insert_runs(conn, 1, success=12)
        _code_n_runs(conn, 1, 5)
    result = public_lite.get_lite_status("t1")
    assert result.phase == "coding"


def test_all_success_runs_coded_is_metrics(db):
    with db.begin() as conn:
        _insert_cycle(conn, 1, "running", total_runs_planned=12)
        _insert_lite(conn, "t1", "running", cycle_id=1)
        _insert_runs(conn, 1, success=12)
        _code_n_runs(conn, 1, 12)
    result = public_lite.get_lite_status("t1")
    assert result.phase == "metrics"


def test_all_runs_errored_skips_coding_straight_to_metrics(db):
    """Nothing succeeded, so there's nothing to code — coding is
    trivially "done" and this should not get stuck reporting 'coding'
    forever with success_runs == 0."""
    with db.begin() as conn:
        _insert_cycle(conn, 1, "running", total_runs_planned=12)
        _insert_lite(conn, "t1", "running", cycle_id=1)
        _insert_runs(conn, 1, error=12)
    result = public_lite.get_lite_status("t1")
    assert result.phase == "metrics"


def test_running_lite_with_complete_cycle_is_complete(db):
    """Defensive: covers the brief window before _sweep_lite_completions catches up."""
    with db.begin() as conn:
        _insert_cycle(conn, 1, "complete", total_runs_planned=12)
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
        _insert_cycle(conn, 1, "running", total_runs_planned=12)
        _insert_lite(conn, "t1", "running", cycle_id=1)
        _insert_runs(conn, 1, success=6)
        lite_id = conn.exec_driver_sql(
            "SELECT id FROM soa_lite_requests WHERE token = 't1'"
        ).fetchone()[0]
        _insert_scan(conn, lite_id, "failed")

    result = public_lite.get_lite_status("t1")
    assert result.phase == "running"
    assert result.scan_status == "failed"


# ─── _derive_phase / _fetch_live_progress_counts unit coverage (direct, no DB) ──

@pytest.mark.parametrize("lite_status,expected_phase", [
    ("pending", "queued"),
    ("identifying_competitors", "identifying_competitors"),
    ("generating", "generating_queries"),
    ("complete", "complete"),
    ("failed", "failed"),
])
def test_derive_phase_terminal_and_pre_cycle_states(lite_status, expected_phase):
    phase, progress = public_lite._derive_phase(lite_status, None, None, None)
    assert phase == expected_phase
    assert progress is None


def test_derive_phase_no_total_runs_planned_is_running_with_no_progress():
    counts = public_lite._LiveProgressCounts(resolved_runs=0, success_runs=0, coded_runs=0)
    phase, progress = public_lite._derive_phase("running", "running", None, counts)
    assert phase == "running"
    assert progress is None
