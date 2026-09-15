"""
Tests for PATCH /api/public/soa-lite/{token}/email
(app/routers/public_lite.py::set_lite_email) — email is always stored,
even before the report is ready; returns the full report inline once
complete, else {status, phase} (same shape as GET /status).

The internal "new lead" notification this endpoint now fires is a pure
side effect: every test here patches the sender out (see the autouse
_no_lead_emails fixture), and the dedupe/wiring tests at the bottom
assert it can never change the response either way.
"""
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch
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
                competitor_names TEXT, competitor_source TEXT, events TEXT DEFAULT '[]',
                brand_name TEXT, store_url TEXT, lead_notified_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, status TEXT,
                completed_runs INTEGER, total_runs_planned INTEGER,
                extraction_validation TEXT,
                study_type TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS soa_expectation_outcomes (
                id INTEGER PRIMARY KEY, run_id INTEGER UNIQUE, query_id INTEGER,
                cycle_id INTEGER, platform TEXT, tier TEXT,
                expected_answer TEXT, extraction TEXT, outcome TEXT,
                outcome_reason TEXT, domain_cited BOOLEAN,
                source_attribution TEXT, secondary_results TEXT,
                record_published_at TIMESTAMP, matched_published_at TIMESTAMP,
                near_miss BOOLEAN,
                extraction_model TEXT, scored_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_queries (
                id INTEGER PRIMARY KEY, stage TEXT, persona TEXT, query_text TEXT,
                tier TEXT, expected_answer TEXT, provenance TEXT, source_ref TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, query_id INTEGER, status TEXT,
                platform TEXT, raw_response TEXT, run_at TEXT, run_number INTEGER
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_coded_mentions (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                mentioned BOOLEAN, deal_cited BOOLEAN, deal_types TEXT, member_value_cited BOOLEAN,
                position INTEGER, strength TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_price_observations (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                stated_price FLOAT, claimed_net_price FLOAT, member_price_claimed BOOLEAN,
                merchant_name TEXT, attribution_status TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_incentive_scores (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                scoring_grain TEXT, status TEXT, measurement_status TEXT,
                stated_price FLOAT, ground_truth_true_cost FLOAT, net_price_accuracy BOOLEAN
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_entities (
                id INTEGER PRIMARY KEY, name TEXT, slug TEXT UNIQUE, entity_type TEXT, website_url TEXT,
                aliases TEXT
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
                membership_probe TEXT, revenue_probe TEXT, fetch_probe TEXT, input_url TEXT
            )
        """)
    monkeypatch.setattr(public_lite, "engine", engine)
    return engine


@pytest.fixture(autouse=True)
def _no_lead_emails():
    """Nothing in this file should reach Resend — a developer with
    RESEND_API_KEY set in their environment must not send real mail by
    running the suite. Tests that care about the notification override
    this with their own patch.object inside the test body."""
    with patch.object(public_lite, "send_lead_notification", return_value=False):
        yield


def _email(v="visitor@example.com"):
    return PublicLiteEmailRequest(email=v)


def _notified_at(db, token="t1"):
    with db.connect() as conn:
        return conn.exec_driver_sql(
            "SELECT lead_notified_at FROM soa_lite_requests WHERE token = ?", (token,)
        ).fetchone()[0]


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
        "scorer_version": "5",
        "agent_access": {"score": 5, "max": 5, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
        "catalog_context": {
            "score": 2, "max": 8, "coverage": "full", "evidence": [],
            "fix": "fix catalog_context", "fix_human": "Add product identifiers so agents can match your listings.",
        },
        "protocol_feed": {"score": 5, "max": 5, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
        "price_truth_seen": {"score": 7, "max": 7, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
        "member_value_seen": {"score": 5, "max": 5, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
        "deal_citability_seen": {"score": 7, "max": 7, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
        "value_protocols_seen": {"score": 14, "max": 14, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
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


# ─── internal "new lead" notification ────────────────────────────────────
# One notification per lead, not one per PATCH retry: the widget's PATCH
# is idempotent and a visitor can repeat it, so the gate is whether the
# stored address actually changed. The send happens after the storing
# transaction has committed, so it can never roll the email back and
# never changes the response.

def test_first_email_notifies_once_with_the_lead_fields_and_stamps_notified_at(db):
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, status, brand_name, store_url, competitor_names) "
            "VALUES ('t1', 'running', 'Allbirds', 'https://allbirds.com', '[\"Rothys\", \"Vessi\"]')"
        )

    with patch.object(public_lite, "send_lead_notification", return_value=True) as mock_send:
        public_lite.set_lite_email("t1", _email("visitor@example.com"))

    assert mock_send.call_count == 1
    fields = mock_send.call_args[0][0]
    assert fields["brand_name"] == "Allbirds"
    assert fields["email"] == "visitor@example.com"
    assert fields["competitors"] == ["Rothys", "Vessi"]
    assert fields["store_url"] == "https://allbirds.com"
    assert fields["status"] == "running"
    assert fields["token"] == "t1"
    assert fields["submitted_at"]

    assert _notified_at(db) is not None


def test_repeating_the_same_email_does_not_notify_again(db):
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, status, brand_name) VALUES ('t1', 'running', 'Allbirds')"
        )

    with patch.object(public_lite, "send_lead_notification", return_value=True) as mock_send:
        public_lite.set_lite_email("t1", _email("visitor@example.com"))
        public_lite.set_lite_email("t1", _email("visitor@example.com"))
        public_lite.set_lite_email("t1", _email("visitor@example.com"))

    assert mock_send.call_count == 1


def test_a_different_email_notifies_again(db):
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, status, brand_name) VALUES ('t1', 'running', 'Allbirds')"
        )

    with patch.object(public_lite, "send_lead_notification", return_value=True) as mock_send:
        public_lite.set_lite_email("t1", _email("typo@example.com"))
        public_lite.set_lite_email("t1", _email("corrected@example.com"))

    assert mock_send.call_count == 2
    assert [c[0][0]["email"] for c in mock_send.call_args_list] == [
        "typo@example.com", "corrected@example.com",
    ]


def test_failed_send_leaves_notified_at_null_but_still_stores_the_email(db):
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, status, brand_name) VALUES ('t1', 'pending', 'Allbirds')"
        )

    with patch.object(public_lite, "send_lead_notification", return_value=False):
        result = public_lite.set_lite_email("t1", _email("visitor@example.com"))

    # The stored email is the source of truth — a send failure never
    # rolls it back, and never shows up in the response.
    assert result["status"] == "pending"
    assert result["phase"] == "queued"
    with db.connect() as conn:
        stored = conn.exec_driver_sql(
            "SELECT email FROM soa_lite_requests WHERE token = 't1'"
        ).fetchone()[0]
    assert stored == "visitor@example.com"
    assert _notified_at(db) is None


def test_send_outcome_never_changes_the_response(db):
    """The sender never raises (its own contract — see
    test_lead_notification_email.py); what this endpoint adds on top is
    that whether it succeeded or failed is invisible to the caller."""
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, status, brand_name) VALUES ('t1', 'generating', 'Allbirds')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, status, brand_name) VALUES ('t2', 'generating', 'Allbirds')"
        )

    with patch.object(public_lite, "send_lead_notification", return_value=True):
        sent = public_lite.set_lite_email("t1", _email())
    with patch.object(public_lite, "send_lead_notification", return_value=False):
        unsent = public_lite.set_lite_email("t2", _email())

    assert sent == unsent


def test_response_shape_is_unchanged_for_the_not_complete_case(db):
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, status, brand_name) VALUES ('t1', 'generating', 'Allbirds')"
        )

    with patch.object(public_lite, "send_lead_notification", return_value=True):
        result = public_lite.set_lite_email("t1", _email())
    status = public_lite.get_lite_status("t1").model_dump()

    # The documented contract: the same shape GET /status returns.
    assert set(result) == set(status)
    assert result["status"] == status["status"] == "generating"
    assert "lead_notified_at" not in result


def test_response_shape_is_unchanged_for_the_complete_case(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn)

    with patch.object(public_lite, "send_lead_notification", return_value=True):
        patch_result = public_lite.set_lite_email("t1", _email())
    report = public_lite.get_lite_report("t1")

    assert patch_result == report
    assert "lead_notified_at" not in patch_result


def test_lead_notification_carries_a_null_store_url_through_unchanged(db):
    """store_url is optional on the row — the sender renders "(none)"
    rather than the caller having to substitute anything."""
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, status, brand_name) VALUES ('t1', 'running', 'Allbirds')"
        )

    with patch.object(public_lite, "send_lead_notification", return_value=True) as mock_send:
        public_lite.set_lite_email("t1", _email())

    assert mock_send.call_args[0][0]["store_url"] is None
