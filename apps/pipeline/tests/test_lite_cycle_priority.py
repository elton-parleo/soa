"""
Tests get_next_planned_cycle's lite-first ordering: cycles whose cycle_code
starts with 'lite-' are picked before any other planned cycle, regardless
of created_at, so a live lead-gen visitor isn't starved behind an
hours-long client cycle. Uses a real in-memory SQLite database.
"""
import pytest
from sqlalchemy import create_engine

import worker


@pytest.fixture
def patched_engine(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, cycle_code TEXT UNIQUE, status TEXT,
                study_type TEXT, platforms TEXT, runs_per_query INTEGER,
                cycle_mode TEXT, created_at TIMESTAMP
            )
        """)
    monkeypatch.setattr(worker, "engine", engine)
    return engine


def _insert(conn, cycle_code, created_at, status="planned"):
    conn.exec_driver_sql(
        "INSERT INTO soa_cycles (cycle_code, status, study_type, platforms, "
        "runs_per_query, cycle_mode, created_at) VALUES (?, ?, 'st', '[\"chatgpt\"]', 1, 'query', ?)",
        (cycle_code, status, created_at),
    )


def test_lite_cycle_picked_before_older_client_cycle(patched_engine):
    with patched_engine.begin() as conn:
        _insert(conn, "client-cycle-1", "2026-01-01 00:00:00")
        _insert(conn, "lite-abcd1234", "2026-01-02 00:00:00")

    row = worker.get_next_planned_cycle()

    assert row[0] == "lite-abcd1234"


def test_oldest_first_within_lite_cycles(patched_engine):
    with patched_engine.begin() as conn:
        _insert(conn, "lite-newer00", "2026-01-02 00:00:00")
        _insert(conn, "lite-older000", "2026-01-01 00:00:00")

    row = worker.get_next_planned_cycle()

    assert row[0] == "lite-older000"


def test_oldest_first_within_client_cycles_when_no_lite_pending(patched_engine):
    with patched_engine.begin() as conn:
        _insert(conn, "client-newer", "2026-01-02 00:00:00")
        _insert(conn, "client-older", "2026-01-01 00:00:00")

    row = worker.get_next_planned_cycle()

    assert row[0] == "client-older"


def test_non_planned_lite_cycle_is_not_picked(patched_engine):
    with patched_engine.begin() as conn:
        _insert(conn, "lite-done0000", "2026-01-01 00:00:00", status="running")
        _insert(conn, "client-cycle", "2026-01-02 00:00:00", status="planned")

    row = worker.get_next_planned_cycle()

    assert row[0] == "client-cycle"
