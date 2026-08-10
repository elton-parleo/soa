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
                error TEXT, updated_at TIMESTAMP
            )
        """)
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


def test_process_cycle_crawls_runs_pending_standalone_scan(db):
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
