"""
Scan reuse: don't re-crawl a store we read a few hours ago.

Justfoodfordogs was audited six times in one week; Petco, Vans, Warby
Parker, NAPA and AutoAccessoriesGarage twice each. Every repeat
re-crawled the same store to reach the same conclusion — a dozen fetches
and, on a walled store, minutes of wall clock, spent re-establishing
something already on file.

These tests hold the window and, more importantly, every boundary of it:
a different host, an older scorer version, a 'failed' row (exactly the
case worth retrying), and an expired window all fall through to an
ordinary crawl. _run_lite_scan is exercised directly against in-memory
SQLite, with scan.engine.run_scan mocked so "did we crawl?" is a
countable fact rather than an inference.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event

import worker
from soa_shared.scan_dimensions import SCORER_VERSION


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_requests (
                id INTEGER PRIMARY KEY, token TEXT, brand_name TEXT, store_url TEXT,
                status TEXT, events TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_scan_results (
                id INTEGER PRIMARY KEY, lite_request_id INTEGER UNIQUE, cycle_id INTEGER,
                input_url TEXT, status TEXT DEFAULT 'pending', total_score INTEGER,
                integrity_capped BOOLEAN DEFAULT 0, dimensions TEXT, pages_fetched TEXT,
                membership_probe TEXT, revenue_probe TEXT, fetch_probe TEXT,
                error TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP
            )
        """)
    monkeypatch.setattr(worker, "engine", engine)
    import importlib
    monkeypatch.setattr(importlib.import_module("lite_events"), "engine", engine)
    return engine


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _dimensions(scorer_version=SCORER_VERSION, **extra):
    d = {"scorer_version": scorer_version, "catalog_context": {"score": 6, "max": 8}}
    d.update(extra)
    return d


def _seed_source_scan(db, *, url="https://www.allbirds.com", status="complete",
                      hours_ago=2, scorer_version=SCORER_VERSION, score=71, dimensions=None):
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (id, token, brand_name, store_url, status) "
            "VALUES (1, 'src-token', 'Allbirds', ?, 'complete')", (url,),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_scan_results "
            "(id, lite_request_id, input_url, status, total_score, integrity_capped, "
            " dimensions, pages_fetched, fetch_probe, updated_at) "
            "VALUES (10, 1, ?, ?, ?, 0, ?, ?, ?, ?)",
            (
                url, status, score,
                json.dumps(dimensions if dimensions is not None else _dimensions(scorer_version)),
                json.dumps([{"url": url, "status": "fetched"}]),
                json.dumps({"outcome": "quoted_price", "price": "$98"}),
                _iso(hours_ago),
            ),
        )


def _seed_new_request(db, *, url="https://allbirds.com", request_id=2):
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (id, token, brand_name, store_url, status) "
            "VALUES (?, ?, 'Allbirds', ?, 'running')",
            (request_id, f"tok-{request_id}", url),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_scan_results (lite_request_id, input_url, status, updated_at) "
            "VALUES (?, ?, 'running', ?)", (request_id, url, _iso(0)),
        )


def _new_scan_row(db, request_id=2):
    with db.connect() as conn:
        return conn.exec_driver_sql(
            "SELECT status, total_score, dimensions, pages_fetched, fetch_probe, error "
            "FROM soa_lite_scan_results WHERE lite_request_id = ?", (request_id,),
        ).fetchone()


def _run(url="https://allbirds.com", request_id=2):
    """Runs _run_lite_scan with the crawl mocked, and reports whether
    the crawl actually happened."""
    crawled = []

    def _fake_run_scan(store_url, api_key=None):
        crawled.append(store_url)
        raise AssertionError("this test asserts on whether the crawl ran, not on its result")

    with patch("scan.engine.run_scan", _fake_run_scan):
        try:
            worker._run_lite_scan(request_id, url, None)
        except Exception:
            # The fake raises to make an unexpected crawl loud; the
            # orchestration-failed path swallows it, which is correct
            # behavior and not what this file is testing.
            pass
    return crawled


# ─── reuse fires ─────────────────────────────────────────────────────────

def test_a_recent_scan_of_the_same_store_is_reused_instead_of_crawled(db):
    _seed_source_scan(db)
    _seed_new_request(db)

    crawled = _run()

    assert crawled == []
    status, score, dims_raw, pages_raw, probe_raw, error = _new_scan_row(db)
    assert status == "complete"
    assert score == 71
    assert json.loads(pages_raw) == [{"url": "https://www.allbirds.com", "status": "fetched"}]
    assert json.loads(probe_raw)["price"] == "$98"
    assert error is None
    dims = json.loads(dims_raw)
    assert dims["catalog_context"] == {"score": 6, "max": 8}
    assert dims["reused_from_scan_id"] == 10
    assert dims["reused_at"]


def test_www_and_apex_are_the_same_store(db):
    """The source row is www.allbirds.com; this request is the apex."""
    _seed_source_scan(db, url="https://www.allbirds.com")
    _seed_new_request(db, url="https://allbirds.com")

    assert _run(url="https://allbirds.com") == []


def test_a_blocked_scan_is_reusable(db):
    """A walled store is exactly the expensive case — Warby Parker's
    local re-scan took 185 s to re-learn it is still walled."""
    _seed_source_scan(db, status="blocked", score=None)
    _seed_new_request(db)

    assert _run() == []
    assert _new_scan_row(db)[0] == "blocked"


def test_the_reuse_is_announced_in_the_crawl_events(db):
    _seed_source_scan(db, hours_ago=5)
    _seed_new_request(db)
    _run()

    with db.connect() as conn:
        events = json.loads(conn.exec_driver_sql(
            "SELECT events FROM soa_lite_requests WHERE id = 2").scalar())
    texts = [e["text"] for e in events if e.get("task") == "crawl"]
    assert any("Reusing our read of allbirds.com from 5 hours ago" == t for t in texts), texts


# ─── every boundary falls through to an ordinary crawl ───────────────────

def test_a_scan_outside_the_window_is_not_reused(db, monkeypatch):
    monkeypatch.setattr(worker, "SCAN_REUSE_WINDOW_HOURS", 72)
    _seed_source_scan(db, hours_ago=100)
    _seed_new_request(db)

    assert _run() == ["https://allbirds.com"]


def test_a_scan_of_a_different_host_is_not_reused(db):
    _seed_source_scan(db, url="https://rothys.com")
    _seed_new_request(db, url="https://allbirds.com")

    assert _run() == ["https://allbirds.com"]


def test_a_failed_scan_is_never_reused(db):
    """A 'failed' row is the one worth retrying — reusing it would make
    a transient outage permanent for the whole window."""
    _seed_source_scan(db, status="failed")
    _seed_new_request(db)

    assert _run() == ["https://allbirds.com"]


def test_a_scan_from_an_older_scorer_version_is_not_reused(db):
    _seed_source_scan(db, scorer_version="4")
    _seed_new_request(db)

    assert _run() == ["https://allbirds.com"]


def test_a_reused_scan_is_never_itself_reused(db):
    """Chaining would let one crawl's data outlive its own window
    indefinitely."""
    _seed_source_scan(db, dimensions=_dimensions(reused_from_scan_id=99, reused_at=_iso(1)))
    _seed_new_request(db)

    assert _run() == ["https://allbirds.com"]


def test_a_row_cannot_reuse_itself(db):
    """The new request's own 'running' row must never match."""
    _seed_new_request(db, request_id=2)
    with db.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE soa_lite_scan_results SET status='complete', dimensions=? WHERE lite_request_id=2",
            (json.dumps(_dimensions()),),
        )

    assert _run() == ["https://allbirds.com"]


def test_the_window_is_configurable(db, monkeypatch):
    monkeypatch.setattr(worker, "SCAN_REUSE_WINDOW_HOURS", 1)
    _seed_source_scan(db, hours_ago=4)
    _seed_new_request(db)

    assert _run() == ["https://allbirds.com"]


# ─── reuse can never cost a request its crawl ────────────────────────────

def test_a_bug_in_reuse_falls_through_to_an_ordinary_crawl(db, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("reuse exploded")

    monkeypatch.setattr(worker, "_reuse_recent_scan", _boom)
    _seed_source_scan(db)
    _seed_new_request(db)

    assert _run() == ["https://allbirds.com"]


# ─── canonical host ──────────────────────────────────────────────────────

@pytest.mark.parametrize("url,expected", [
    ("https://www.allbirds.com", "allbirds.com"),
    ("http://ALLBIRDS.com/", "allbirds.com"),
    ("allbirds.com", "allbirds.com"),
    ("https://shop.allbirds.com", "shop.allbirds.com"),  # a subdomain is a different store
    ("https://allbirds.com:443/collections/mens", "allbirds.com"),
    ("", None),
    (None, None),
    ("not a url at all ::::", None),
])
def test_canonical_host(url, expected):
    assert worker._canonical_host(url) == expected
