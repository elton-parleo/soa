"""
Tests for Part 1 (E1)'s lite-gated event emission in RunOrchestrator
(the "queries" task) and PipelineOrchestrator (the "scoring" task).

_resolve_lite_request_id is tested directly against a bare instance
(object.__new__, bypassing __init__ entirely) for the non-lite
short-circuit — the whole point of the cheap cycle_code prefix check is
that it costs ZERO DB round trips for the vast majority (every non-lite
cycle), which a bare instance with no working session_factory proves
cleanly: if it touched the DB at all, this would raise.

The lite-prefixed resolution path and the "queries" task's throttled
log line + final done event are covered by one real, minimal
run_cycle() execution — a real in-memory SQLite schema (just the
tables RunOrchestrator's constructor and run loop touch) with a fake
chatgpt runner standing in for the real OpenAI call, so this exercises
the ACTUAL wiring (not a re-implementation of it) without a live API
call.
"""
import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import lite_events
import runners.run_orchestrator as run_orchestrator_module
from orchestrator.pipeline import PipelineOrchestrator
from runners.platform_response import PlatformResponse
from runners.run_orchestrator import RunOrchestrator


# ─── _resolve_lite_request_id: zero-cost non-lite short-circuit ─────────

class _ExplodingSessionFactory:
    """Raising on any call proves the cheap prefix check never reaches
    the DB for a non-lite cycle_code."""
    def __call__(self, *a, **k):
        raise AssertionError("session_factory() was called for a non-lite cycle_code")


def test_run_orchestrator_resolve_lite_request_id_short_circuits_for_non_lite(monkeypatch):
    monkeypatch.setattr(run_orchestrator_module, "session_factory", _ExplodingSessionFactory())
    orch = object.__new__(RunOrchestrator)
    orch.cycle_code = "retailer_sephora_2026"
    assert orch._resolve_lite_request_id() is None


def test_pipeline_orchestrator_resolve_lite_request_id_short_circuits_for_non_lite(monkeypatch):
    import orchestrator.pipeline as pipeline_module
    monkeypatch.setattr(pipeline_module, "session_factory", _ExplodingSessionFactory())
    orch = object.__new__(PipelineOrchestrator)
    orch.cycle_code = "retailer_sephora_2026"
    assert orch._resolve_lite_request_id() is None


# ─── Real (minimal) run_cycle() — queries task event emission ───────────

class _FakeChatgptRunner:
    """Stands in for OpenAIRunner — no real API call, resolves
    instantly with a canned success response."""
    platform = "chatgpt"

    def __init__(self, *a, **k):
        pass

    async def run(self, query_text):
        return PlatformResponse(
            response_text=f"answer to: {query_text}",
            prompt_tokens=10, completion_tokens=10, latency_ms=5,
            platform="chatgpt", model="fake-model",
        )


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_entities (
                id INTEGER PRIMARY KEY, name TEXT, slug TEXT, entity_type TEXT,
                category TEXT, merchant_id INTEGER, website_url TEXT, aliases TEXT,
                created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, cycle_code TEXT, start_date DATE,
                end_date DATE, total_runs_planned INTEGER, completed_runs INTEGER,
                status TEXT, notes TEXT, platforms TEXT, runs_per_query INTEGER,
                study_type TEXT, study_pattern TEXT,
                scope_frozen_at TIMESTAMP, scope_is_custom BOOLEAN,
                organization_id INTEGER, created_by TEXT,
                cycle_mode TEXT DEFAULT 'query', truecost_tiers TEXT,
                created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycle_entities (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                comparison_code TEXT, role TEXT, display_name TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_scope_skus (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                role TEXT, dealengine_listing_id INTEGER,
                dealengine_catalog_product_id INTEGER, merchant_slug TEXT,
                merchant_sku TEXT, brand TEXT, category TEXT, product_url TEXT,
                listed_price NUMERIC, currency TEXT, display_name TEXT,
                is_active BOOLEAN, created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_queries (
                id INTEGER PRIMARY KEY, query_code TEXT UNIQUE, query_text TEXT, category TEXT,
                stage TEXT, specificity TEXT, persona TEXT, study_type TEXT, study_pattern TEXT,
                soa_focus TEXT, rationale TEXT, status TEXT, organization_id INTEGER,
                created_by TEXT, membership_program TEXT, tier_name TEXT,
                subscription_state TEXT, expected_incentive TEXT, new_customer BOOLEAN,
                created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, query_id INTEGER, platform TEXT,
                run_number INTEGER, run_at TIMESTAMP, raw_response TEXT, response_tokens INTEGER,
                latency_ms INTEGER, status TEXT DEFAULT 'pending', error_message TEXT,
                search_triggered BOOLEAN, retrieved_sources TEXT, created_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_requests (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, events TEXT DEFAULT '[]'
            )
        """)

        conn.exec_driver_sql("INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (1, 'Acme', 'acme', 'brand')")
        conn.exec_driver_sql("""
            INSERT INTO soa_cycles (id, cycle_code, study_type, study_pattern, status, cycle_mode, organization_id)
            VALUES (1, 'lite-abc12345', 'lite-abc12345', 'brand_vs_brand', 'planned', 'query', 1)
        """)
        conn.exec_driver_sql(
            "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (1, 1, 'M001', 'primary')"
        )
        for i in range(2):
            conn.exec_driver_sql(
                "INSERT INTO soa_queries (query_code, query_text, study_type, status) VALUES (?, ?, 'lite-abc12345', 'Active')",
                (f"LIT_{i:03d}", f"question {i}"),
            )
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (id, cycle_id, events) VALUES (1, 1, '[]')"
        )

    # expire_on_commit=False matches production's soa_shared.database.
    # session_factory — without it, RunOrchestrator's own session.commit()
    # (right before it expunges self.cycle in __init__) expires every
    # attribute, and the object is detached by the time anything reads
    # self.cycle.id afterward.
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(run_orchestrator_module, "session_factory", session_factory)
    monkeypatch.setattr(lite_events, "engine", engine)
    monkeypatch.setitem(run_orchestrator_module._RUNNER_CLASSES, "chatgpt", _FakeChatgptRunner)
    return engine


def _events(db):
    with db.connect() as conn:
        raw = conn.exec_driver_sql("SELECT events FROM soa_lite_requests WHERE id = 1").fetchone()[0]
    return json.loads(raw) if isinstance(raw, str) else (raw or [])


def test_queries_task_emits_throttled_log_lines_and_a_final_done_event(db):
    orch = RunOrchestrator(cycle_code="lite-abc12345", platforms=["chatgpt"], runs_per_query=1)
    assert orch._lite_request_id == 1  # resolved via the real DB lookup, not hand-set

    asyncio.run(orch.run_cycle())

    events = _events(db)
    query_events = [e for e in events if e["task"] == "queries"]
    log_lines = [e["text"] for e in query_events if e["kind"] == "log"]
    done_lines = [e for e in query_events if e["kind"] == "done"]

    # One throttled line per resolved run — never more, never fewer —
    # regardless of which order the two concurrent runs actually land in.
    assert sorted(log_lines) == ["q1/2 answered", "q2/2 answered"]
    assert len(done_lines) == 1
    assert done_lines[0]["text"] == "All 2 answers collected"


def test_non_lite_cycle_emits_no_events_at_all(db):
    with db.begin() as conn:
        conn.exec_driver_sql("UPDATE soa_cycles SET cycle_code = 'retailer_sephora_2026', study_type = 'retailer_sephora_2026' WHERE id = 1")
        conn.exec_driver_sql("UPDATE soa_queries SET study_type = 'retailer_sephora_2026'")

    orch = RunOrchestrator(cycle_code="retailer_sephora_2026", platforms=["chatgpt"], runs_per_query=1)
    assert orch._lite_request_id is None

    asyncio.run(orch.run_cycle())

    assert _events(db) == []
