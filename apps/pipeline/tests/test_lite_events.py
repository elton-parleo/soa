"""
Tests for lite_events.py — the append-only events[] contract itself
(seq monotonicity, the 200-entry log cap, done/state events never
trimmed, task validation) independent of any one call site. Worker/
orchestrator-level emission is covered in test_process_lite_requests.py
and test_run_orchestrator_lite_events.py.

Uses a real in-memory SQLite database with just the one column this
module touches — lite_events.emit_event() issues a plain SELECT/UPDATE
against soa_lite_requests.events, nothing else.
"""
import json

import pytest
from sqlalchemy import create_engine

import lite_events


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_requests (
                id INTEGER PRIMARY KEY, events TEXT DEFAULT '[]'
            )
        """)
        conn.exec_driver_sql("INSERT INTO soa_lite_requests (id, events) VALUES (1, '[]')")
    monkeypatch.setattr(lite_events, "engine", engine)
    return engine


def _events(db):
    with db.connect() as conn:
        raw = conn.exec_driver_sql("SELECT events FROM soa_lite_requests WHERE id = 1").fetchone()[0]
    return json.loads(raw)


def test_first_event_gets_seq_one(db):
    lite_events.emit_log(1, lite_events.TASK_CRAWL, "reading store.com…")
    events = _events(db)
    assert len(events) == 1
    assert events[0]["seq"] == 1
    assert events[0]["kind"] == "log"
    assert events[0]["task"] == "crawl"
    assert events[0]["text"] == "reading store.com…"
    assert "ts" in events[0]


def test_seq_strictly_increases_across_calls(db):
    lite_events.emit_log(1, lite_events.TASK_CRAWL, "one")
    lite_events.emit_log(1, lite_events.TASK_CRAWL, "two")
    lite_events.emit_done(1, lite_events.TASK_CRAWL, "three")
    events = _events(db)
    assert [e["seq"] for e in events] == [1, 2, 3]


def test_done_event_carries_chips_when_given(db):
    lite_events.emit_done(1, lite_events.TASK_COMPETITORS, "2 found", chips=["Rival", "OtherCo"])
    events = _events(db)
    assert events[0]["chips"] == ["Rival", "OtherCo"]


def test_log_event_has_no_chips_key(db):
    lite_events.emit_log(1, lite_events.TASK_CRAWL, "reading…")
    events = _events(db)
    assert "chips" not in events[0]


def test_state_event_uses_run_pseudo_task(db):
    lite_events.emit_state(1, "running")
    events = _events(db)
    assert events[0]["kind"] == "state"
    assert events[0]["task"] == "run"
    assert events[0]["text"] == "running"


def test_invalid_task_for_log_kind_is_dropped_not_raised(db):
    lite_events.emit_event(1, "not_a_real_task", "x", kind="log")
    assert _events(db) == []


def test_run_pseudo_task_rejected_for_non_state_kind(db):
    lite_events.emit_event(1, lite_events.RUN_TASK, "x", kind="log")
    assert _events(db) == []


def test_unknown_request_id_is_a_silent_noop(db):
    lite_events.emit_log(999, lite_events.TASK_CRAWL, "x")  # never raises
    assert _events(db) == []


def test_never_raises_when_engine_is_broken(db, monkeypatch):
    class _BrokenEngine:
        def begin(self):
            raise RuntimeError("db is down")
    monkeypatch.setattr(lite_events, "engine", _BrokenEngine())
    lite_events.emit_log(1, lite_events.TASK_CRAWL, "x")  # must not raise


# ─── E2: log cap at 200, done/state never trimmed ────────────────────────

def test_log_events_capped_at_200_most_recent(db):
    for i in range(210):
        lite_events.emit_log(1, lite_events.TASK_CRAWL, f"line {i}")
    events = _events(db)
    logs = [e for e in events if e["kind"] == "log"]
    assert len(logs) == 200
    # The oldest 10 were dropped — the most recent 200 survive.
    texts = [e["text"] for e in logs]
    assert "line 0" not in texts
    assert "line 9" not in texts
    assert "line 10" in texts
    assert "line 209" in texts


def test_done_and_state_events_never_trimmed_even_past_the_log_cap(db):
    lite_events.emit_state(1, "running")
    for i in range(250):
        lite_events.emit_log(1, lite_events.TASK_CRAWL, f"line {i}")
    lite_events.emit_done(1, lite_events.TASK_CRAWL, "12 pages read")
    events = _events(db)
    kinds = [e["kind"] for e in events]
    assert kinds.count("log") == 200
    assert kinds.count("state") == 1
    assert kinds.count("done") == 1


def test_events_stay_seq_ordered_after_capping(db):
    for i in range(205):
        lite_events.emit_log(1, lite_events.TASK_CRAWL, f"line {i}")
    lite_events.emit_done(1, lite_events.TASK_CRAWL, "done")
    events = _events(db)
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)


# ─── Additivity: an old row's shape is never disturbed by a new column ──

def test_additivity_old_events_untouched_by_a_later_append(db):
    lite_events.emit_log(1, lite_events.TASK_CRAWL, "first")
    before = _events(db)
    lite_events.emit_log(1, lite_events.TASK_CRAWL, "second")
    after = _events(db)
    assert after[0] == before[0]
    assert len(after) == 2
