"""
Tests for worker.py::process_cycle_crawls/_run_cycle_scan — Full Analysis
coexistence, Phase 2: the pipeline-side stage that runs a standalone
(non-lite) cycle's crawl, queued by apps/api/app/routers/full_analysis.py
::launch_crawl as a 'pending' soa_lite_scan_results row with cycle_id set
and lite_request_id NULL. scan.engine.run_scan is mocked, same convention
as test_process_lite_requests.py.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, text

import worker


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_scan_results (
                id INTEGER PRIMARY KEY, lite_request_id INTEGER, cycle_id INTEGER,
                input_url TEXT, status TEXT, total_score INTEGER,
                integrity_capped BOOLEAN, dimensions TEXT, pages_fetched TEXT,
                error TEXT, revenue_probe TEXT, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, source_lite_request_id INTEGER
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycle_entities (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER, role TEXT
            )
        """)
        conn.exec_driver_sql("CREATE TABLE soa_entities (id INTEGER PRIMARY KEY, name TEXT)")
        # Every test's default cycle_id (42) and the lite-owned-row test's
        # cycle_id (7) — process_cycle_crawls now joins soa_cycles to read
        # source_lite_request_id (revenue-probe gating below).
        conn.execute(text(
            "INSERT INTO soa_cycles (id, source_lite_request_id) VALUES (42, NULL), (7, NULL)"
        ))
    monkeypatch.setattr(worker, "engine", engine)
    return engine


def _make_scan_result(**overrides):
    from scan.engine import ScanResult

    defaults = dict(
        status="complete", total_score=91, integrity_capped=False,
        dimensions={"agent_access": {"score": 5, "max": 5}},
        pages_fetched=[{"url": "https://acme.example.com", "status": "fetched"}],
        error=None,
    )
    defaults.update(overrides)
    return ScanResult(**defaults)


def _insert_pending(conn, cycle_id=42, store_url="https://acme.example.com", status="pending"):
    row = conn.execute(text("""
        INSERT INTO soa_lite_scan_results (cycle_id, lite_request_id, input_url, status)
        VALUES (:cid, NULL, :url, :status)
        RETURNING id
    """), {"cid": cycle_id, "url": store_url, "status": status}).fetchone()
    return row[0]


def _fetch_row(conn, scan_id):
    return conn.execute(text("""
        SELECT status, total_score, cycle_id, lite_request_id
        FROM soa_lite_scan_results WHERE id = :id
    """), {"id": scan_id}).fetchone()


def test_process_cycle_crawls_runs_pending_standalone_scan(db, monkeypatch):
    # Scoped to crawl behavior only — see the "revenue probe" tests
    # below for that side of process_cycle_crawls.
    monkeypatch.delenv("OPEN_AI_API_KEY", raising=False)
    with db.begin() as conn:
        scan_id = _insert_pending(conn)

    with patch("scan.engine.run_scan", return_value=_make_scan_result()) as mock_scan:
        worker.process_cycle_crawls()

    mock_scan.assert_called_once()
    assert mock_scan.call_args.args[0] == "https://acme.example.com"

    with db.connect() as conn:
        status, total_score, cycle_id, lite_request_id = _fetch_row(conn, scan_id)
    assert status == "complete"
    assert total_score == 91
    assert cycle_id == 42
    assert lite_request_id is None


def test_process_cycle_crawls_skips_when_no_store_url(db):
    with db.begin() as conn:
        scan_id = _insert_pending(conn, store_url=None)

    with patch("scan.engine.run_scan") as mock_scan:
        worker.process_cycle_crawls()

    mock_scan.assert_not_called()
    with db.connect() as conn:
        status, *_ = _fetch_row(conn, scan_id)
    assert status == "skipped"


def test_process_cycle_crawls_never_touches_lite_owned_rows(db):
    with db.begin() as conn:
        conn.execute(text("""
            INSERT INTO soa_lite_scan_results (cycle_id, lite_request_id, input_url, status)
            VALUES (7, 1, 'https://acme.example.com', 'pending')
        """))

    with patch("scan.engine.run_scan") as mock_scan:
        worker.process_cycle_crawls()

    mock_scan.assert_not_called()


def test_process_cycle_crawls_is_a_noop_when_queue_empty(db):
    with patch("scan.engine.run_scan") as mock_scan:
        worker.process_cycle_crawls()
    mock_scan.assert_not_called()


# ─── Revenue probe (1a — exposure widget's seed) ───────────────────────────

def _seed_primary_entity(conn, cycle_id, name="Acme"):
    conn.execute(text(
        "INSERT INTO soa_entities (id, name) VALUES (:cid, :name)"
    ), {"cid": cycle_id * 100 + 1, "name": name})
    conn.execute(text(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, role) VALUES (:cid, :eid, 'primary')"
    ), {"cid": cycle_id, "eid": cycle_id * 100 + 1})


def test_process_cycle_crawls_runs_a_revenue_probe_for_a_standalone_cycle(db, monkeypatch):
    monkeypatch.setenv("OPEN_AI_API_KEY", "test-key")
    with db.begin() as conn:
        scan_id = _insert_pending(conn)  # cycle_id=42, source_lite_request_id=NULL
        _seed_primary_entity(conn, 42, name="Acme")

    probe_result = {"annual_revenue_usd": 50_000_000.0, "basis": "estimated", "quote": None}
    with patch("scan.engine.run_scan", return_value=_make_scan_result()), \
         patch("generation.revenue_probe.probe_revenue", return_value=probe_result) as mock_probe:
        worker.process_cycle_crawls()

    mock_probe.assert_called_once()
    assert mock_probe.call_args.args[0] == "Acme"

    with db.connect() as conn:
        row = conn.execute(text(
            "SELECT revenue_probe FROM soa_lite_scan_results WHERE id = :id"
        ), {"id": scan_id}).fetchone()
    import json
    assert json.loads(row[0]) == probe_result


def test_process_cycle_crawls_skips_the_revenue_probe_for_a_continuation_cycle(db, monkeypatch):
    """The audit's own scan row already has a revenue_probe — re-running
    it here would be a second, redundant OpenAI call for the same
    brand. app/routers/full_analysis.py reads the audit's seed instead."""
    monkeypatch.setenv("OPEN_AI_API_KEY", "test-key")
    with db.begin() as conn:
        conn.execute(text(
            "UPDATE soa_cycles SET source_lite_request_id = 999 WHERE id = 42"
        ))
        _insert_pending(conn)
        _seed_primary_entity(conn, 42)

    with patch("scan.engine.run_scan", return_value=_make_scan_result()), \
         patch("generation.revenue_probe.probe_revenue") as mock_probe:
        worker.process_cycle_crawls()

    mock_probe.assert_not_called()


def test_process_cycle_crawls_skips_the_revenue_probe_without_an_api_key(db, monkeypatch):
    monkeypatch.delenv("OPEN_AI_API_KEY", raising=False)
    with db.begin() as conn:
        _insert_pending(conn)
        _seed_primary_entity(conn, 42)

    with patch("scan.engine.run_scan", return_value=_make_scan_result()), \
         patch("generation.revenue_probe.probe_revenue") as mock_probe:
        worker.process_cycle_crawls()

    mock_probe.assert_not_called()


def test_process_cycle_crawls_revenue_probe_never_fails_the_crawl(db, monkeypatch):
    """Isolated exactly like the lite-side probes: a bug in the revenue
    probe must never affect the crawl result already written."""
    monkeypatch.setenv("OPEN_AI_API_KEY", "test-key")
    with db.begin() as conn:
        scan_id = _insert_pending(conn)
        _seed_primary_entity(conn, 42)

    with patch("scan.engine.run_scan", return_value=_make_scan_result()), \
         patch("generation.revenue_probe.probe_revenue", side_effect=RuntimeError("boom")):
        worker.process_cycle_crawls()  # must not raise

    with db.connect() as conn:
        status, total_score, *_ = _fetch_row(conn, scan_id)
    assert status == "complete"
    assert total_score == 91
