"""
Tests for worker.py::process_lite_requests and _sweep_lite_completions —
the SoA Lite state machine: pending -> generating -> running, then swept to
complete/failed once the cycle it created finishes.

Uses a real in-memory SQLite database for every table process_lite_requests
touches (organizations, soa_entities, soa_lite_requests, soa_queries,
soa_cycles, soa_cycle_entities) via worker.engine, same convention as
test_scope_resolution.py — only generate_lite_queries (the OpenAI call) is
mocked. SQLite has no NOW(); a connect-time SQL function fills the gap
since production code (worker.py, entity_helpers.py, cycle_creation.py)
issues raw NOW() calls throughout.

session_factory is patched via a fresh importlib.import_module() call
inside the fixture (not a module-level import) because test_pampers_seed.py
permanently swaps sys.modules['soa_shared.database'] for a stub with no
teardown — resolving the module at fixture-execution time, rather than at
this file's collection time, patches whichever object is actually live in
sys.modules when worker.py's own `from soa_shared.database import
session_factory` runs, regardless of test file ordering.
"""
import importlib
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import worker
from generation.query_generator import LiteGenerationError
from soa_shared.constants import QUERY_STAGES


def _lite_row(stage, i):
    return {
        'query_text': f"{stage} question {i}",
        'category': 'General',
        'stage': stage,
        'specificity': 'Broad',
        'persona': 'Casual / Gift Buyer',
        'study_pattern': 'brand_vs_brand',
        'status': 'Active',
        'subscription_state': 'not_subscribed',
        'soa_focus': 'Mention Rate',
        'rationale': 'test',
    }


def _twelve_rows():
    return [_lite_row(stage, i) for stage in QUERY_STAGES for i in range(3)]


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE organizations (
                id INTEGER PRIMARY KEY, name TEXT UNIQUE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_entities (
                id INTEGER PRIMARY KEY, name TEXT, slug TEXT UNIQUE, entity_type TEXT,
                category TEXT, merchant_id INTEGER, website_url TEXT, aliases TEXT,
                created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_requests (
                id INTEGER PRIMARY KEY, token TEXT UNIQUE, email TEXT, brand_name TEXT,
                competitor_names TEXT, brand_entity_id INTEGER, competitor_entity_ids TEXT,
                study_type TEXT, cycle_id INTEGER, status TEXT DEFAULT 'pending',
                error_message TEXT, ip_hash TEXT, organization_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, cycle_code TEXT UNIQUE, study_type TEXT,
                study_pattern TEXT, status TEXT, cycle_mode TEXT, truecost_tiers TEXT,
                total_runs_planned INTEGER, completed_runs INTEGER, start_date DATE,
                notes TEXT, platforms TEXT, runs_per_query INTEGER,
                organization_id INTEGER, created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycle_entities (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                comparison_code TEXT, role TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_queries (
                id INTEGER PRIMARY KEY, query_code TEXT UNIQUE, query_text TEXT, category TEXT,
                stage TEXT, specificity TEXT, persona TEXT, study_type TEXT, study_pattern TEXT,
                soa_focus TEXT, rationale TEXT, status TEXT, organization_id INTEGER,
                created_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    monkeypatch.setattr(worker, "engine", engine)
    db_module = importlib.import_module("soa_shared.database")
    monkeypatch.setattr(db_module, "session_factory", sessionmaker(bind=engine))
    monkeypatch.setenv("OPEN_AI_API_KEY", "test-key")
    return engine


def _insert_pending(conn, token="a1b2c3d4e5f6", brand="Acme", competitors=None):
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_requests (token, brand_name, competitor_names, status) "
        "VALUES (?, ?, ?, 'pending')",
        (token, brand, json.dumps(competitors if competitors is not None else ["Rival"])),
    )


def _lite_row_by_token(conn, token):
    return conn.exec_driver_sql(
        "SELECT status, brand_entity_id, competitor_entity_ids, study_type, cycle_id, error_message "
        "FROM soa_lite_requests WHERE token = ?", (token,),
    ).fetchone()


# ── happy path ───────────────────────────────────────────────────────────

def test_full_happy_path_reaches_running_with_cycle(db):
    with db.begin() as conn:
        _insert_pending(conn, competitors=["Rival"])

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()):
        worker.process_lite_requests()

    status, brand_entity_id, competitor_entity_ids, study_type, cycle_id, error = _lite_row_by_token(
        db.connect(), "a1b2c3d4e5f6"
    )
    assert status == "running"
    assert study_type == "lite-a1b2c3d4"
    assert cycle_id is not None
    assert error is None

    with db.connect() as conn:
        brand = conn.exec_driver_sql(
            "SELECT name, slug, entity_type FROM soa_entities WHERE id = ?", (brand_entity_id,)
        ).fetchone()
        rival_id = conn.exec_driver_sql(
            "SELECT id FROM soa_entities WHERE slug = 'rival'"
        ).fetchone()[0]
    assert brand == ("Acme", "acme", "brand")
    assert json.loads(competitor_entity_ids) == [rival_id]


def test_entities_resolved_and_reused_across_requests(db):
    with db.begin() as conn:
        _insert_pending(conn, token="req1", brand="Acme", competitors=["Rival"])

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()):
        worker.process_lite_requests()

    with db.begin() as conn:
        _insert_pending(conn, token="req2", brand="Acme", competitors=["OtherCo"])

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()):
        worker.process_lite_requests()

    with db.connect() as conn:
        acme_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM soa_entities WHERE slug = 'acme'"
        ).fetchone()[0]
    assert acme_count == 1


def test_creates_cycle_with_correct_comparison_set(db):
    with db.begin() as conn:
        _insert_pending(conn, competitors=["Rival"])

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()):
        worker.process_lite_requests()

    with db.connect() as conn:
        cycle = conn.exec_driver_sql(
            "SELECT cycle_code, status, cycle_mode, study_pattern, platforms, runs_per_query, total_runs_planned "
            "FROM soa_cycles"
        ).fetchone()
        comparison_set = conn.exec_driver_sql(
            "SELECT comparison_code, role FROM soa_cycle_entities ORDER BY comparison_code"
        ).fetchall()

    assert cycle[0] == "lite-a1b2c3d4"
    assert cycle[1] == "planned"
    assert cycle[2] == "query"
    assert cycle[3] == "brand_vs_brand"
    assert json.loads(cycle[4]) == ["chatgpt"]
    assert cycle[5] == 1
    assert cycle[6] == 12
    assert comparison_set == [("M001", "primary"), ("M002", "competitor")]


def test_inserts_twelve_queries_with_lite_study_type(db):
    with db.begin() as conn:
        _insert_pending(conn, competitors=[])

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()):
        worker.process_lite_requests()

    with db.connect() as conn:
        count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM soa_queries WHERE study_type = 'lite-a1b2c3d4'"
        ).fetchone()[0]
        created_by = conn.exec_driver_sql(
            "SELECT DISTINCT created_by FROM soa_queries WHERE study_type = 'lite-a1b2c3d4'"
        ).fetchone()[0]
    assert count == 12
    assert created_by == "soa-lite"


def test_no_competitors_yields_primary_only_comparison_set(db):
    with db.begin() as conn:
        _insert_pending(conn, competitors=[])

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()):
        worker.process_lite_requests()

    with db.connect() as conn:
        comparison_set = conn.exec_driver_sql(
            "SELECT comparison_code, role FROM soa_cycle_entities"
        ).fetchall()
    assert comparison_set == [("M001", "primary")]


def test_processes_only_one_pending_row_per_call(db):
    with db.begin() as conn:
        _insert_pending(conn, token="req1", brand="Acme")
        _insert_pending(conn, token="req2", brand="Beta")

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()):
        worker.process_lite_requests()

    with db.connect() as conn:
        statuses = dict(conn.exec_driver_sql(
            "SELECT token, status FROM soa_lite_requests"
        ).fetchall())
    assert statuses["req1"] == "running"
    assert statuses["req2"] == "pending"


def test_no_pending_rows_is_a_noop(db):
    worker.process_lite_requests()  # should not raise with an empty table


# ── failure paths ────────────────────────────────────────────────────────

def test_generation_failure_marks_request_failed(db):
    with db.begin() as conn:
        _insert_pending(conn)

    with patch(
        "generation.query_generator.generate_lite_queries",
        side_effect=LiteGenerationError("stage shortfall"),
    ):
        worker.process_lite_requests()

    status, _, _, _, cycle_id, error = _lite_row_by_token(db.connect(), "a1b2c3d4e5f6")
    assert status == "failed"
    assert cycle_id is None
    assert "stage shortfall" in error


def test_missing_api_key_marks_request_failed(db, monkeypatch):
    monkeypatch.delenv("OPEN_AI_API_KEY", raising=False)
    with db.begin() as conn:
        _insert_pending(conn)

    worker.process_lite_requests()

    status, _, _, _, _, error = _lite_row_by_token(db.connect(), "a1b2c3d4e5f6")
    assert status == "failed"
    assert "OPEN_AI_API_KEY" in error


def test_failed_request_leaves_no_cycle_row(db):
    with db.begin() as conn:
        _insert_pending(conn)

    with patch(
        "generation.query_generator.generate_lite_queries",
        side_effect=LiteGenerationError("boom"),
    ):
        worker.process_lite_requests()

    with db.connect() as conn:
        count = conn.exec_driver_sql("SELECT COUNT(*) FROM soa_cycles").fetchone()[0]
    assert count == 0


# ── completion sweep ─────────────────────────────────────────────────────

def _insert_running_lite_with_cycle(conn, token, cycle_status):
    conn.exec_driver_sql(
        "INSERT INTO soa_cycles (cycle_code, status) VALUES (?, ?)",
        (f"lite-{token}", cycle_status),
    )
    cycle_id = conn.exec_driver_sql(
        "SELECT id FROM soa_cycles WHERE cycle_code = ?", (f"lite-{token}",)
    ).fetchone()[0]
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_requests (token, brand_name, status, cycle_id) VALUES (?, 'Acme', 'running', ?)",
        (token, cycle_id),
    )


def test_sweep_marks_complete_when_cycle_completes(db):
    with db.begin() as conn:
        _insert_running_lite_with_cycle(conn, "done0001", "complete")

    worker._sweep_lite_completions()

    status, *_ = _lite_row_by_token(db.connect(), "done0001")
    assert status == "complete"


def test_sweep_marks_failed_when_cycle_fails(db):
    with db.begin() as conn:
        _insert_running_lite_with_cycle(conn, "fail0001", "failed")

    worker._sweep_lite_completions()

    status, _, _, _, _, error = _lite_row_by_token(db.connect(), "fail0001")
    assert status == "failed"
    assert error is not None


def test_sweep_leaves_still_running_cycles_alone(db):
    with db.begin() as conn:
        _insert_running_lite_with_cycle(conn, "run00001", "running")

    worker._sweep_lite_completions()

    status, *_ = _lite_row_by_token(db.connect(), "run00001")
    assert status == "running"
