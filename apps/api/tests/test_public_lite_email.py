"""
Tests for PATCH /api/public/soa-lite/{token}/email
(app/routers/public_lite.py::set_lite_email) — email is always stored,
even before the report is ready; returns the full report inline once
complete, else {status, phase} (same shape as GET /status).
"""
import json
import pytest
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import create_engine, event

import app.routers.public_lite as public_lite
from app.schemas import PublicLiteEmailRequest


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_requests (
                id INTEGER PRIMARY KEY, token TEXT UNIQUE, email TEXT,
                status TEXT, cycle_id INTEGER, updated_at TIMESTAMP,
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
            CREATE TABLE soa_queries (
                id INTEGER PRIMARY KEY, stage TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, query_id INTEGER, status TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_coded_mentions (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                mentioned BOOLEAN, deal_cited BOOLEAN, deal_types TEXT, member_value_cited BOOLEAN
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_price_observations (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                stated_price FLOAT, claimed_net_price FLOAT, member_price_claimed BOOLEAN
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_entities (
                id INTEGER PRIMARY KEY, name TEXT, slug TEXT UNIQUE, entity_type TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycle_entities (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                comparison_code TEXT, role TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_metrics_results (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                slice_type TEXT, slice_value TEXT, total_runs INTEGER, total_mentions INTEGER,
                mention_rate FLOAT, soa_pct FLOAT, position_index FLOAT, rsi_score FLOAT,
                deal_citation_rate FLOAT, platform_dist_index FLOAT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_scan_results (
                id INTEGER PRIMARY KEY, lite_request_id INTEGER UNIQUE, status TEXT,
                total_score INTEGER, integrity_capped BOOLEAN, dimensions TEXT, pages_fetched TEXT,
                membership_probe TEXT, revenue_probe TEXT, fetch_probe TEXT
            )
        """)
    monkeypatch.setattr(public_lite, "engine", engine)
    return engine


def _email(v="visitor@example.com"):
    return PublicLiteEmailRequest(email=v)


# ─── 404 ──────────────────────────────────────────────────────────────────

def test_404_for_unknown_token(db):
    with pytest.raises(HTTPException) as exc_info:
        public_lite.set_lite_email("nope", _email())
    assert exc_info.value.status_code == 404


# ─── not yet complete: email stored, status returned ────────────────────

def test_stores_email_when_still_pending(db):
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, status) VALUES ('t1', 'pending')"
        )

    result = public_lite.set_lite_email("t1", _email("visitor@example.com"))

    assert result["status"] == "pending"
    assert result["phase"] == "queued"
    with db.connect() as conn:
        stored = conn.exec_driver_sql(
            "SELECT email FROM soa_lite_requests WHERE token = 't1'"
        ).fetchone()[0]
    assert stored == "visitor@example.com"


def test_stores_email_when_running_and_returns_progress_phase(db):
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_cycles (id, status, completed_runs, total_runs_planned) "
            "VALUES (1, 'running', 0, 12)"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, status, cycle_id) VALUES ('t1', 'running', 1)"
        )
        # Stage 12: progress is now derived live from soa_runs, not the
        # (stale, once-written) soa_cycles.completed_runs column.
        for _ in range(6):
            conn.exec_driver_sql("INSERT INTO soa_runs (cycle_id, status) VALUES (1, 'success')")

    result = public_lite.set_lite_email("t1", _email())

    assert result["phase"] == "running"
    assert result["progress"]["completed_runs"] == 6


def test_stores_email_and_returns_competitors_when_already_populated(db):
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, status, competitor_names, competitor_source) "
            "VALUES ('t1', 'generating', '[\"Rival\", \"Gen One\"]', 'mixed')"
        )

    result = public_lite.set_lite_email("t1", _email())

    assert result["competitors"] == ["Rival", "Gen One"]
    assert result["competitor_source"] == "mixed"


def test_does_not_return_report_shape_when_not_complete(db):
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, status) VALUES ('t1', 'generating')"
        )
    result = public_lite.set_lite_email("t1", _email())
    assert "overall" not in result
    assert "locked" not in result


# ─── complete: full report returned inline ──────────────────────────────

def _seed_complete_cycle(conn):
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_requests (token, status, cycle_id, competitor_source) "
        "VALUES ('t1', 'complete', 1, 'generated')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (101, 'Acme Co', 'acme-co', 'brand')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) "
        "VALUES (1, 101, 'M001', 'primary')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_metrics_results "
        "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, mention_rate, soa_pct) "
        "VALUES (1, 101, 'overall', 'overall', 12, 6, 0.5, 0.6)"
    )


def test_returns_full_unlocked_report_when_already_complete(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn)

    result = public_lite.set_lite_email("t1", _email("visitor@example.com"))

    assert result["locked"] is False
    assert result["overall"][0]["name"] == "Acme Co"
    assert "metrics" in result["overall"][0]
    assert result["competitor_source"] == "generated"


def test_email_persisted_when_complete(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn)

    public_lite.set_lite_email("t1", _email("visitor@example.com"))

    with db.connect() as conn:
        stored = conn.exec_driver_sql(
            "SELECT email FROM soa_lite_requests WHERE token = 't1'"
        ).fetchone()[0]
    assert stored == "visitor@example.com"


def test_subsequent_get_report_is_unlocked_after_email_patch(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn)

    public_lite.set_lite_email("t1", _email("visitor@example.com"))
    report = public_lite.get_lite_report("t1")

    assert report["locked"] is False


# ─── Part 3 (F4): email PATCH no longer changes fix serialization ────────
# The email gate mechanism (this PATCH) is unchanged — it still unlocks
# the report at all. What it does NOT do (and never specially did) is
# serialize a different `pillars.fixes` shape than a plain GET /report
# would for the same token: both routes share _build_report_payload,
# with no separate fix-unlock branch keyed off the PATCH itself.

def _seed_v3_cycle_with_a_fix(conn):
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_requests (token, status, cycle_id, competitor_source) "
        "VALUES ('v3fix', 'complete', 7, 'generated')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (301, 'Fixture Co', 'fixture-co', 'brand')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (7, 301, 'M001', 'primary')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_metrics_results "
        "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, mention_rate, soa_pct, rsi_score) "
        "VALUES (7, 301, 'overall', 'overall', 12, 6, 0.5, 0.6, 1.0)"
    )
    dimensions = {
        "scorer_version": "4",
        "agent_access": {"score": 6, "max": 6, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
        "catalog_context": {
            "score": 2, "max": 8, "coverage": "full", "evidence": [],
            "fix": "fix catalog_context", "fix_human": "Add product identifiers so agents can match your listings.",
        },
        "protocol_feed": {"score": 6, "max": 6, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
        "price_truth_seen": {"score": 5, "max": 5, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
        "member_value_seen": {"score": 9, "max": 9, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
        "deal_citability_seen": {"score": 4, "max": 4, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
        "value_protocols_seen": {"score": 7, "max": 7, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
    }
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_scan_results (lite_request_id, status, total_score, integrity_capped, dimensions, membership_probe) "
        "VALUES ((SELECT id FROM soa_lite_requests WHERE token = 'v3fix'), 'complete', 90, 0, ?, ?)",
        (json.dumps(dimensions), json.dumps({"result": "no", "raw_evidence": None})),
    )


def test_email_patch_and_get_report_serialize_the_same_fixes_shape(db):
    with db.begin() as conn:
        _seed_v3_cycle_with_a_fix(conn)

    patch_result = public_lite.set_lite_email("v3fix", _email("visitor@example.com"))
    get_result = public_lite.get_lite_report("v3fix")

    assert patch_result["pillars"]["fixes"] == get_result["pillars"]["fixes"]
    assert patch_result["pillars"]["fixes"]["visible"][0]["code"] == "catalog_context"
