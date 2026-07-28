"""
Tests for worker.py::process_lite_requests and _sweep_lite_completions —
the SoA Lite state machine: pending -> generating -> running, then swept to
complete/failed once BOTH the cycle it created and the Agent Scan it
triggers (soa_lite_scan_results) reach a terminal state.

Uses a real in-memory SQLite database for every table process_lite_requests
touches (organizations, soa_entities, soa_lite_requests, soa_queries,
soa_cycles, soa_cycle_entities, soa_lite_scan_results) via worker.engine,
same convention as test_scope_resolution.py — only generate_lite_queries
(the OpenAI call) and scan.engine.run_scan (the store crawl) are mocked.
SQLite has no NOW(); a connect-time SQL function fills the gap since
production code (worker.py, entity_helpers.py, cycle_creation.py) issues
raw NOW() calls throughout.

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
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import worker
from generation.competitor_generator import CompetitorCandidate
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
                study_type TEXT, store_url TEXT, cycle_id INTEGER, status TEXT DEFAULT 'pending',
                error_message TEXT, ip_hash TEXT, organization_id INTEGER,
                report_email_sent_at TIMESTAMP, competitor_source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_scan_results (
                id INTEGER PRIMARY KEY, lite_request_id INTEGER UNIQUE, input_url TEXT,
                status TEXT DEFAULT 'pending', total_score INTEGER,
                integrity_capped BOOLEAN DEFAULT 0, dimensions TEXT, pages_fetched TEXT,
                membership_probe TEXT,
                error TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP
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


@pytest.fixture(autouse=True)
def _no_generated_competitors(monkeypatch):
    """
    Stage 13: process_lite_requests now always calls
    generation.competitor_generator.generate_competitors ahead of query
    generation. Defaulting it to [] (as if the API found nothing) keeps
    every pre-Stage-13 test's entity/query-count assertions exactly as
    they were — the manual competitor list, if any, passes through
    select_competitors unchanged since there's nothing to top up with.
    Tests that care about auto-generated competitors override this
    per-test (see the Stage 13 section below).
    """
    monkeypatch.setattr("generation.competitor_generator.generate_competitors", lambda *a, **k: [])


@pytest.fixture(autouse=True)
def _no_membership_probe_call(monkeypatch):
    """
    Stage 16 (Part 4): process_lite_requests now always calls
    generation.membership_probe.probe_membership after the scan.
    Defaulting it to a benign 'unknown' result keeps every pre-Stage-16
    test's assertions unaffected — no real OpenAI call is made. Tests
    that care about the probe's result override this per-test (see the
    Stage 16 section below).
    """
    monkeypatch.setattr(
        "generation.membership_probe.probe_membership",
        lambda *a, **k: {"result": "unknown", "raw_evidence": None},
    )


def _insert_pending(conn, token="a1b2c3d4e5f6", brand="Acme", competitors=None, store_url=None):
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_requests (token, brand_name, competitor_names, store_url, status) "
        "VALUES (?, ?, ?, ?, 'pending')",
        (token, brand, json.dumps(competitors if competitors is not None else ["Rival"]), store_url),
    )


def _lite_row_by_token(conn, token):
    return conn.exec_driver_sql(
        "SELECT status, brand_entity_id, competitor_entity_ids, study_type, cycle_id, error_message "
        "FROM soa_lite_requests WHERE token = ?", (token,),
    ).fetchone()


def _scan_row_by_token(conn, token):
    return conn.exec_driver_sql(
        "SELECT status, total_score, integrity_capped, dimensions, pages_fetched, error, input_url "
        "FROM soa_lite_scan_results "
        "WHERE lite_request_id = (SELECT id FROM soa_lite_requests WHERE token = ?)",
        (token,),
    ).fetchone()


def _membership_probe_by_token(conn, token):
    row = conn.exec_driver_sql(
        "SELECT membership_probe FROM soa_lite_scan_results "
        "WHERE lite_request_id = (SELECT id FROM soa_lite_requests WHERE token = ?)",
        (token,),
    ).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def _age_scan_row(conn, token, minutes_ago):
    old = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    conn.exec_driver_sql(
        "UPDATE soa_lite_scan_results SET updated_at = ? "
        "WHERE lite_request_id = (SELECT id FROM soa_lite_requests WHERE token = ?)",
        (old, token),
    )


def _make_scan_result(**overrides):
    from scan.engine import ScanResult

    defaults = dict(
        status="complete",
        total_score=82,
        integrity_capped=False,
        dimensions={"F1": {"score": 8.0, "max": 10, "evidence": ["ok"], "fix": None}},
        pages_fetched=[{"url": "https://acme.example.com", "status": "fetched"}],
        started_at="2026-07-22T00:00:00+00:00",
        finished_at="2026-07-22T00:00:05+00:00",
        error=None,
    )
    defaults.update(overrides)
    return ScanResult(**defaults)


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

def _insert_running_lite_with_cycle(conn, token, cycle_status, scan_status="complete"):
    """
    scan_status defaults to 'complete' — in production a 'running' lite
    row always has a scan row (they're created atomically, see
    process_lite_requests), so every pre-existing sweep test that doesn't
    care about the scan gets one that's already terminal and out of the
    way.
    """
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
    lite_id = conn.exec_driver_sql(
        "SELECT id FROM soa_lite_requests WHERE token = ?", (token,)
    ).fetchone()[0]
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_scan_results (lite_request_id, status, updated_at) VALUES (?, ?, ?)",
        (lite_id, scan_status, datetime.now(timezone.utc).isoformat()),
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


def test_sweep_isolates_one_bad_row_from_others_in_the_same_pass(db):
    """
    Stage 14 (W2): two rows are both eligible to complete in the same
    sweep pass; badrow's completion UPDATE is made to fail at the DB
    level (a before_cursor_execute hook, simulating e.g. a constraint
    violation) while goodrow's is not. Before Stage 14, both rows'
    writes shared one engine.begin() transaction, so badrow's failure
    would roll back goodrow's write too and raise past
    _sweep_lite_completions entirely. Now each row gets its own
    connection/transaction + try/except: goodrow must still complete,
    badrow must be left untouched (still 'running', to retry next
    pass — never marked 'failed' just because this pass's write broke),
    and the call itself must not raise.
    """
    from sqlalchemy import event

    with db.begin() as conn:
        _insert_running_lite_with_cycle(conn, "badrow0", "complete")
        _insert_running_lite_with_cycle(conn, "goodrow", "complete")
        bad_lite_id = conn.exec_driver_sql(
            "SELECT id FROM soa_lite_requests WHERE token = 'badrow0'"
        ).fetchone()[0]

    def _fail_badrow_completion_write(conn, cursor, statement, parameters, context, executemany):
        if "UPDATE soa_lite_requests" in statement and bad_lite_id in (parameters or ()):
            raise RuntimeError("simulated DB failure for badrow's completion write")

    event.listen(db, "before_cursor_execute", _fail_badrow_completion_write)
    try:
        worker._sweep_lite_completions()  # must not raise
    finally:
        event.remove(db, "before_cursor_execute", _fail_badrow_completion_write)

    bad_status, *_ = _lite_row_by_token(db.connect(), "badrow0")
    assert bad_status == "running"  # untouched — will retry next pass, not marked failed

    good_status, *_ = _lite_row_by_token(db.connect(), "goodrow")
    assert good_status == "complete"  # unaffected by badrow's failure


def test_sweep_leaves_still_running_cycles_alone(db):
    with db.begin() as conn:
        _insert_running_lite_with_cycle(conn, "run00001", "running")

    worker._sweep_lite_completions()

    status, *_ = _lite_row_by_token(db.connect(), "run00001")
    assert status == "running"


# ── Agent Scan integration ──────────────────────────────────────────────

def test_store_url_creates_scan_row_and_persists_result(db):
    with db.begin() as conn:
        _insert_pending(conn, competitors=["Rival"], store_url="https://acme.example.com")

    scan_result = _make_scan_result()
    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()), \
         patch("scan.engine.run_scan", return_value=scan_result) as mock_scan:
        worker.process_lite_requests()

    mock_scan.assert_called_once_with("https://acme.example.com")

    status, *_ = _lite_row_by_token(db.connect(), "a1b2c3d4e5f6")
    assert status == "running"  # scan result never affects the lite request's own status

    scan_status, total_score, integrity_capped, dimensions, pages_fetched, scan_error, input_url = (
        _scan_row_by_token(db.connect(), "a1b2c3d4e5f6")
    )
    assert scan_status == "complete"
    assert total_score == 82
    assert bool(integrity_capped) is False
    assert json.loads(dimensions) == scan_result.dimensions
    assert json.loads(pages_fetched) == scan_result.pages_fetched
    assert scan_error is None
    assert input_url == "https://acme.example.com"


def test_without_store_url_scan_is_skipped_and_flow_unchanged(db):
    with db.begin() as conn:
        _insert_pending(conn, competitors=["Rival"])  # no store_url

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()), \
         patch("scan.engine.run_scan") as mock_scan:
        worker.process_lite_requests()

    mock_scan.assert_not_called()

    status, brand_entity_id, competitor_entity_ids, study_type, cycle_id, error = _lite_row_by_token(
        db.connect(), "a1b2c3d4e5f6"
    )
    assert status == "running"
    assert study_type == "lite-a1b2c3d4"
    assert cycle_id is not None
    assert error is None

    scan_status, total_score, *_ = _scan_row_by_token(db.connect(), "a1b2c3d4e5f6")
    assert scan_status == "skipped"
    assert total_score is None


@pytest.mark.parametrize("scan_status", ["blocked", "failed"])
def test_degraded_scan_result_persisted_and_request_still_completes(db, scan_status):
    with db.begin() as conn:
        _insert_pending(conn, competitors=["Rival"], store_url="https://blocked.example.com")

    scan_result = _make_scan_result(
        status=scan_status, total_score=None, dimensions={}, pages_fetched=[],
        error="site blocked automated access",
    )
    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()), \
         patch("scan.engine.run_scan", return_value=scan_result):
        worker.process_lite_requests()

    recorded_status, *_ = _scan_row_by_token(db.connect(), "a1b2c3d4e5f6")
    assert recorded_status == scan_status

    # The scan already reached a terminal state, so the cycle completing
    # alone is now enough to complete the lite request.
    with db.begin() as conn:
        conn.exec_driver_sql("UPDATE soa_cycles SET status = 'complete' WHERE cycle_code = 'lite-a1b2c3d4'")

    worker._sweep_lite_completions()

    status, *_ = _lite_row_by_token(db.connect(), "a1b2c3d4e5f6")
    assert status == "complete"


# ── Stage 16 (Part 4): membership probe ─────────────────────────────────

def test_membership_probe_result_persisted_on_scan_row(db):
    with db.begin() as conn:
        _insert_pending(conn, competitors=["Rival"], store_url="https://acme.example.com")

    probe_result = {"result": "yes", "raw_evidence": "Acme Rewards is a free loyalty program."}
    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()), \
         patch("scan.engine.run_scan", return_value=_make_scan_result()), \
         patch("generation.membership_probe.probe_membership", return_value=probe_result) as mock_probe:
        worker.process_lite_requests()

    mock_probe.assert_called_once_with("Acme", "test-key", store_url="https://acme.example.com")
    assert _membership_probe_by_token(db.connect(), "a1b2c3d4e5f6") == probe_result


def test_membership_probe_runs_even_without_store_url(db):
    """probe_membership asks about the brand generally, not the crawl —
    it must still run when there's no store_url to scan (scan itself
    gets skipped, see test_without_store_url_scan_is_skipped_and_flow_
    unchanged)."""
    with db.begin() as conn:
        _insert_pending(conn, competitors=["Rival"])  # no store_url

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()), \
         patch("generation.membership_probe.probe_membership",
               return_value={"result": "no", "raw_evidence": None}) as mock_probe:
        worker.process_lite_requests()

    mock_probe.assert_called_once_with("Acme", "test-key", store_url=None)
    assert _membership_probe_by_token(db.connect(), "a1b2c3d4e5f6") == {"result": "no", "raw_evidence": None}


def test_membership_probe_failure_never_blocks_the_run(db):
    """probe_membership itself never raises (see test_membership_probe.py),
    but this isolation must hold even if it somehow did — same rule-4
    discipline as the scan orchestration try/except right above it in
    process_lite_requests."""
    with db.begin() as conn:
        _insert_pending(conn, competitors=["Rival"], store_url="https://acme.example.com")

    def _raise(*a, **k):
        raise RuntimeError("boom")

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()), \
         patch("scan.engine.run_scan", return_value=_make_scan_result()), \
         patch("generation.membership_probe.probe_membership", _raise):
        worker.process_lite_requests()

    status, *_ = _lite_row_by_token(db.connect(), "a1b2c3d4e5f6")
    assert status == "running"  # request itself still succeeded
    assert _membership_probe_by_token(db.connect(), "a1b2c3d4e5f6") is None  # never written


def test_sweep_waits_when_scan_still_running_within_window(db):
    with db.begin() as conn:
        _insert_running_lite_with_cycle(conn, "wait0001", "complete", scan_status="running")

    worker._sweep_lite_completions()

    status, *_ = _lite_row_by_token(db.connect(), "wait0001")
    assert status == "running"  # cycle is done, but the scan hasn't reached a terminal state yet

    scan_status, *_ = _scan_row_by_token(db.connect(), "wait0001")
    assert scan_status == "running"  # untouched — not stuck long enough to force-fail


def test_sweep_recovers_scan_stuck_running_past_ten_minutes(db):
    with db.begin() as conn:
        _insert_running_lite_with_cycle(conn, "stuck0001", "complete", scan_status="running")
        _age_scan_row(conn, "stuck0001", minutes_ago=15)

    worker._sweep_lite_completions()

    status, *_ = _lite_row_by_token(db.connect(), "stuck0001")
    assert status == "complete"

    scan_status, _, _, _, _, scan_error, _ = _scan_row_by_token(db.connect(), "stuck0001")
    assert scan_status == "failed"
    assert scan_error == "scan timed out"


def test_worker_crash_mid_scan_does_not_reprocess_and_sweep_recovers(db):
    """
    Simulates the worker dying mid-scan: the cycle is queued and the scan
    row created (both atomic, per process_lite_requests), but run_scan
    itself never returns — mirrored here by raising instead of returning,
    since a real worker crash means no result is ever written. The next
    poll must not reprocess this row (it already left 'pending'), and the
    sweep's 10-minute rule is what eventually recovers it.
    """
    with db.begin() as conn:
        _insert_pending(conn, token="crash001", store_url="https://acme.example.com")

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()), \
         patch("scan.engine.run_scan", side_effect=RuntimeError("worker died mid-scan")):
        worker.process_lite_requests()

    status, *_ = _lite_row_by_token(db.connect(), "crash001")
    assert status == "running"  # cycle queued; the scan crash must not affect it

    scan_status, *_ = _scan_row_by_token(db.connect(), "crash001")
    assert scan_status == "running"  # stuck, as if the worker died before writing a result

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()) as mock_gen:
        worker.process_lite_requests()
    mock_gen.assert_not_called()  # no longer 'pending' — must not be reprocessed

    with db.begin() as conn:
        conn.exec_driver_sql("UPDATE soa_cycles SET status = 'complete' WHERE cycle_code = 'lite-crash001'")
        _age_scan_row(conn, "crash001", minutes_ago=15)

    worker._sweep_lite_completions()

    status, *_ = _lite_row_by_token(db.connect(), "crash001")
    assert status == "complete"

    scan_status, _, _, _, _, scan_error, _ = _scan_row_by_token(db.connect(), "crash001")
    assert scan_status == "failed"
    assert scan_error == "scan timed out"


# ── Stage 12 (E3): report-ready email delivery ──────────────────────────

def _insert_complete_lite(conn, token, email=None, brand="Acme"):
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_requests (token, brand_name, email, status) "
        "VALUES (?, ?, ?, 'complete')",
        (token, brand, email),
    )


def _sent_at_by_token(conn, token):
    return conn.exec_driver_sql(
        "SELECT report_email_sent_at FROM soa_lite_requests WHERE token = ?", (token,)
    ).fetchone()[0]


class _FakeSender:
    """Records every call and returns a scripted True/False per call, so
    tests can assert exactly how many times send was attempted."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def send_report_ready(self, to, report_url, brand_name):
        self.calls.append((to, report_url, brand_name))
        return self._results.pop(0) if self._results else True


def test_sweep_sends_report_ready_email_exactly_once(db):
    with db.begin() as conn:
        _insert_complete_lite(conn, "mail0001", email="visitor@example.com", brand="Acme")

    fake = _FakeSender([True])
    with patch("email_sender.get_email_sender", return_value=fake):
        worker._sweep_lite_completions()
        worker._sweep_lite_completions()  # second pass must not resend

    assert len(fake.calls) == 1
    to, report_url, brand_name = fake.calls[0]
    assert to == "visitor@example.com"
    assert report_url.endswith("/report/mail0001")
    assert brand_name == "Acme"
    assert _sent_at_by_token(db.connect(), "mail0001") is not None


def test_sweep_retries_send_failure_on_next_pass_and_completion_unaffected(db):
    with db.begin() as conn:
        _insert_complete_lite(conn, "retry001", email="visitor@example.com")

    fake = _FakeSender([False, True])
    with patch("email_sender.get_email_sender", return_value=fake):
        worker._sweep_lite_completions()
        assert _sent_at_by_token(db.connect(), "retry001") is None
        status, *_ = _lite_row_by_token(db.connect(), "retry001")
        assert status == "complete"  # a send failure never blocks/reverts completion

        worker._sweep_lite_completions()

    assert len(fake.calls) == 2
    assert _sent_at_by_token(db.connect(), "retry001") is not None


def test_sweep_skips_requests_with_no_email_on_file(db):
    with db.begin() as conn:
        _insert_complete_lite(conn, "noemail1", email=None)

    fake = _FakeSender([True])
    with patch("email_sender.get_email_sender", return_value=fake):
        worker._sweep_lite_completions()

    assert fake.calls == []


def test_sweep_does_not_send_before_request_completes(db):
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, brand_name, email, status) "
            "VALUES (?, ?, ?, 'running')",
            ("stillrun", "Acme", "visitor@example.com"),
        )

    fake = _FakeSender([True])
    with patch("email_sender.get_email_sender", return_value=fake):
        worker._sweep_lite_completions()

    assert fake.calls == []


def test_sweep_uses_logsender_by_default_and_masks_email_in_logs(db, monkeypatch, caplog):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    with db.begin() as conn:
        _insert_complete_lite(conn, "logmail1", email="visitor@example.com", brand="Acme")

    with caplog.at_level("INFO"):
        worker._sweep_lite_completions()

    assert _sent_at_by_token(db.connect(), "logmail1") is not None
    assert "visitor@example.com" not in caplog.text
    assert "v***@example.com" in caplog.text


def test_email_body_contains_report_url_and_no_score_language():
    from email_sender import _email_html, _email_text

    report_url = "https://parleo.io/report/abc123token"
    text = _email_text(report_url, "Acme")
    html = _email_html(report_url, "Acme")

    assert report_url in text
    assert report_url in html
    assert "score" not in text.lower()
    assert "score" not in html.lower()


# ── Stage 13: worker-side competitor auto-generation ─────────────────────

def _competitor_fields_by_token(conn, token):
    row = conn.exec_driver_sql(
        "SELECT competitor_names, competitor_source, status FROM soa_lite_requests WHERE token = ?",
        (token,),
    ).fetchone()
    names = json.loads(row[0]) if row[0] else []
    return names, row[1], row[2]


def test_generated_competitors_top_up_manual_ones_and_persist_mixed_source(db, monkeypatch):
    monkeypatch.setattr(
        "generation.competitor_generator.generate_competitors",
        lambda *a, **k: [CompetitorCandidate(name="Gen One"), CompetitorCandidate(name="Gen Two")],
    )
    with db.begin() as conn:
        _insert_pending(conn, competitors=["Rival"])

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()) as mock_gen:
        worker.process_lite_requests()

    names, source, status = _competitor_fields_by_token(db.connect(), "a1b2c3d4e5f6")
    assert names == ["Rival", "Gen One", "Gen Two"]
    assert source == "mixed"
    assert status == "running"

    # F1: generation must precede (and feed) query generation — the
    # final, topped-up list is what the prompt embeds competitor names
    # from, not the original manual-only list.
    mock_gen.assert_called_once_with("Acme", ["Rival", "Gen One", "Gen Two"], "test-key")


def test_generated_competitors_get_entities_created_alongside_manual_ones(db, monkeypatch):
    monkeypatch.setattr(
        "generation.competitor_generator.generate_competitors",
        lambda *a, **k: [CompetitorCandidate(name="Gen One")],
    )
    with db.begin() as conn:
        _insert_pending(conn, competitors=["Rival"])

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()):
        worker.process_lite_requests()

    with db.connect() as conn:
        gen_entity = conn.exec_driver_sql(
            "SELECT id FROM soa_entities WHERE slug = 'gen-one'"
        ).fetchone()
        comparison_roles = conn.exec_driver_sql(
            "SELECT comparison_code, role FROM soa_cycle_entities ORDER BY comparison_code"
        ).fetchall()

    assert gen_entity is not None  # entity created exactly once for the generated candidate
    assert comparison_roles == [("M001", "primary"), ("M002", "competitor"), ("M003", "competitor")]


def test_no_manual_competitors_and_generation_finds_none_yields_none_source(db):
    # The autouse _no_generated_competitors fixture already returns [].
    with db.begin() as conn:
        _insert_pending(conn, competitors=[])

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()):
        worker.process_lite_requests()

    names, source, status = _competitor_fields_by_token(db.connect(), "a1b2c3d4e5f6")
    assert names == []
    assert source == "none"
    assert status == "running"


def test_competitor_generation_failure_never_blocks_the_run(db, monkeypatch):
    def _raise(*a, **k):
        raise RuntimeError("OpenAI is down")

    # generate_competitors itself never raises (see test_competitor_generator.py),
    # but this proves process_lite_requests survives even if that
    # contract were somehow violated — never-throw is enforced at both
    # layers, not assumed.
    monkeypatch.setattr("generation.competitor_generator.generate_competitors", _raise)
    with db.begin() as conn:
        _insert_pending(conn, competitors=["Rival"])

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()):
        worker.process_lite_requests()

    status, *_ , error = _lite_row_by_token(db.connect(), "a1b2c3d4e5f6")
    assert status == "failed"
    assert error is not None


def test_crash_after_persisting_competitors_leaves_generated_set_intact(db, monkeypatch):
    """
    F1/G4: competitor_names/competitor_source are persisted in their own
    transaction BEFORE entity resolution/query generation/cycle
    queueing. If something downstream then fails, the already-persisted
    competitor set must not be lost or reset — _mark_lite_failed only
    ever touches status/error_message, never competitor_names/source.
    """
    monkeypatch.setattr(
        "generation.competitor_generator.generate_competitors",
        lambda *a, **k: [CompetitorCandidate(name="Gen One")],
    )
    with db.begin() as conn:
        _insert_pending(conn, competitors=["Rival"])

    with patch(
        "soa_shared.cycle_creation.create_cycle_with_comparison_set",
        side_effect=RuntimeError("crash during cycle creation"),
    ), patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()):
        worker.process_lite_requests()

    names, source, status = _competitor_fields_by_token(db.connect(), "a1b2c3d4e5f6")
    assert status == "failed"
    assert names == ["Rival", "Gen One"]  # not lost or regenerated
    assert source == "mixed"


# ── Stage 14 (T3): poll-loop isolation — one bad row must never block ───

def test_first_request_failure_does_not_block_second_in_next_poll(db, monkeypatch):
    """
    Two pending requests; the oldest (req1) fails partway through
    processing (simulated by making generate_competitors raise on its
    first call only). process_lite_requests only ever claims the
    single oldest pending row per call (by design — same rate-limit/
    contention-avoiding semantics as process_generation_jobs), so "the
    same iteration" here means two back-to-back calls, mirroring two
    consecutive ticks of main()'s poll loop: the first call must mark
    req1 'failed' (with the error recorded) rather than raising past
    process_lite_requests, and the second call must then pick up req2
    and process it normally — proving req1 no longer occupies the
    "oldest pending" slot and blocks req2 forever.
    """
    call_count = {"n": 0}

    def _flaky_generate_competitors(*a, **k):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated crash on first request")
        return []

    monkeypatch.setattr("generation.competitor_generator.generate_competitors", _flaky_generate_competitors)

    with db.begin() as conn:
        _insert_pending(conn, token="req1first", brand="Acme", competitors=["Rival"])
        _insert_pending(conn, token="req2second", brand="Beta", competitors=["Rival2"])

    with patch("generation.query_generator.generate_lite_queries", return_value=_twelve_rows()):
        worker.process_lite_requests()  # claims req1 (oldest) -> raises -> marked failed
        worker.process_lite_requests()  # claims req2 (now oldest pending) -> succeeds

    status1, *_, error1 = _lite_row_by_token(db.connect(), "req1first")
    assert status1 == "failed"
    assert error1 is not None and "simulated crash on first request" in error1

    status2, *_ = _lite_row_by_token(db.connect(), "req2second")
    assert status2 == "running"  # processed normally, unaffected by req1's failure

    assert call_count["n"] == 2  # both requests were actually attempted


def test_failed_request_is_not_re_picked_on_a_third_poll(db, monkeypatch):
    """Re-poll fixture: once req1 is marked 'failed' it has left
    'pending' for good — a third call finds nothing left to do rather
    than re-claiming and re-failing the same row forever (the exact
    Stage 13 crash-loop shape)."""
    monkeypatch.setattr(
        "generation.competitor_generator.generate_competitors",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("always fails")),
    )
    with db.begin() as conn:
        _insert_pending(conn, token="alwaysfail", brand="Acme", competitors=["Rival"])

    worker.process_lite_requests()  # claims + fails the only pending row
    status, *_ = _lite_row_by_token(db.connect(), "alwaysfail")
    assert status == "failed"

    with patch("generation.query_generator.generate_lite_queries") as mock_gen:
        worker.process_lite_requests()  # nothing pending left — must be a clean no-op
    mock_gen.assert_not_called()
