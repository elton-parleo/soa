"""
Tests for worker.py::process_generation_jobs — the no-retry-on-
deterministic-failure branch and the created_count==0 guard.

Regression context: subscription_state (an opt-in, feature-flagged
eligibility field the general generation prompt never asked for) made
_validate_generated_row reject 100% of every generated row, every
batch, every retry — deterministically, not from LLM flakiness. The old
code retried anyway (wasting an OpenAI call), then silently "completed"
the job with 0 queries once both attempts came back empty. These tests
lock down the fix: a deterministic failure short-circuits the retry
entirely, and a job that truly ends up with nothing is marked 'failed'
with a human-readable reason, never 'complete'.

_insert_job leaves study_pattern NULL, so every test here exercises the
LEGACY generation path (the multi-batch generate_query_batch loop). That
is deliberate and is the behaviour being locked down: a job queued before
the study brief existed — or by a client that sends only
study_name/description/target_count — must keep running exactly as it did
when it was queued, not be reinterpreted under rules nobody agreed to.
The briefed path has its own file (test_briefed_generation.py). Only the
fixture's CREATE TABLE grew, to mirror the real table after migration
3f8e2a91c7d4; every assertion below is unchanged.
"""
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, text
from datetime import datetime, timezone

import worker


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_query_generation_jobs (
                id INTEGER PRIMARY KEY, study_type TEXT UNIQUE, study_name TEXT,
                description TEXT, target_count INTEGER, created_count INTEGER DEFAULT 0,
                status TEXT, error_message TEXT, organization_id INTEGER, created_by TEXT,
                syndicated_merchant TEXT, tier_config TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP,
                study_pattern TEXT, retailer_names TEXT, allowed_categories TEXT,
                stage_targets TEXT, rotate_named_retailer BOOLEAN,
                naming_rule_enabled BOOLEAN, personas TEXT, specificity_mode TEXT,
                provenance TEXT
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
    monkeypatch.setenv("OPEN_AI_API_KEY", "test-key")
    return engine


def _insert_job(conn, study_type="acme_full_1a2b3c", target_count=20):
    conn.execute(text("""
        INSERT INTO soa_query_generation_jobs
          (study_type, study_name, target_count, created_count, status, organization_id)
        VALUES (:st, 'Acme Full', :tc, 0, 'pending', 1)
    """), {"st": study_type, "tc": target_count})


def _job_row(conn, study_type="acme_full_1a2b3c"):
    return conn.execute(text("""
        SELECT status, created_count, error_message FROM soa_query_generation_jobs WHERE study_type = :st
    """), {"st": study_type}).fetchone()


def _row(i, **overrides):
    row = dict(
        query_code=f"ACM_{i:03d}", query_text=f"Question {i}?", category="Skincare",
        stage="Awareness", specificity="Broad", persona="Casual / Gift Buyer",
        study_pattern="brand_vs_brand", soa_focus="Mention Rate", rationale="test",
        status="Active",
    )
    row.update(overrides)
    return row


def test_deterministic_failure_skips_retry_and_fails_immediately(db):
    with db.begin() as conn:
        _insert_job(conn)

    with patch("generation.query_generator.generate_query_batch") as mock_generate:
        mock_generate.return_value = ([], "Every generated row failed validation on the same field(s): subscription_state")
        worker.process_generation_jobs()

    mock_generate.assert_called_once()  # no retry — deterministic failure short-circuits it
    status, created_count, error_message = _job_row(db.connect())
    assert status == "failed"
    assert created_count == 0
    assert "subscription_state" in error_message


def test_zero_rows_with_no_deterministic_reason_still_retries_then_fails(db):
    with db.begin() as conn:
        _insert_job(conn)

    with patch("generation.query_generator.generate_query_batch") as mock_generate:
        mock_generate.side_effect = [([], None), ([], None)]  # both attempts genuinely empty
        worker.process_generation_jobs()

    assert mock_generate.call_count == 2  # real retry still happens absent a deterministic reason
    status, created_count, error_message = _job_row(db.connect())
    assert status == "failed"
    assert created_count == 0
    assert error_message  # a human-readable reason, never blank


def test_successful_generation_marks_complete_with_created_count(db):
    with db.begin() as conn:
        _insert_job(conn, target_count=3)

    rows = [_row(i) for i in range(1, 4)]
    with patch("generation.query_generator.generate_query_batch") as mock_generate:
        mock_generate.return_value = (rows, None)
        worker.process_generation_jobs()

    mock_generate.assert_called_once()
    status, created_count, error_message = _job_row(db.connect())
    assert status == "complete"
    assert created_count == 3
    assert error_message is None

    with db.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM soa_queries WHERE study_type = 'acme_full_1a2b3c'")).scalar()
    assert count == 3


def test_no_pending_job_is_a_noop(db):
    worker.process_generation_jobs()  # must not raise with an empty queue


def test_end_to_end_50_query_study_commits_50_rows_across_batches(db):
    """
    The reported bug's own repro shape (a 50-query study, general path)
    run through the REAL batching loop in process_generation_jobs — 5
    batches of BATCH_SIZE=10, each row shaped exactly like _build_prompt's
    actual output (no subscription_state key, matching test_query_
    generator_validation.py's drift guard) — no live OpenAI call, but
    everything else (job dequeue, per-batch generate_query_batch calls,
    soa_queries inserts, incremental created_count, final status) is the
    real worker code. Confirms the fix actually resolves "20/20 rows
    rejected, job complete: 0 queries" end to end, not just at the
    validator's own unit-test layer.
    """
    with db.begin() as conn:
        _insert_job(conn, target_count=50)

    def _batch(study_name, description, batch_size, already_generated, api_key):
        start = len(already_generated) + 1
        rows = [_row(i) for i in range(start, start + batch_size)]
        return rows, None

    with patch("generation.query_generator.generate_query_batch", side_effect=_batch) as mock_generate:
        worker.process_generation_jobs()

    assert mock_generate.call_count == 5  # 50 / BATCH_SIZE(10)
    status, created_count, error_message = _job_row(db.connect())
    assert status == "complete"
    assert created_count == 50
    assert error_message is None

    with db.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM soa_queries WHERE study_type = 'acme_full_1a2b3c'")).scalar()
    assert count == 50
