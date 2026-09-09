"""
Tests that worker.py::process_generation_jobs removes exact duplicates at
the ACCUMULATION point — the only place they are visible.

The model sees one batch at a time, so a duplicate spanning batch 2 and
batch 5 is invisible inside generate_query_batch by construction.
Deduping there would catch almost nothing; deduping where the batches are
stitched together catches the case that actually happened.

Same in-memory sqlite harness as test_process_generation_jobs.py, and the
same generate_query_batch mock signature — these tests add coverage
alongside that file rather than changing it.
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
        SELECT status, created_count, error_message
        FROM soa_query_generation_jobs WHERE study_type = :st
    """), {"st": study_type}).fetchone()


def _row(text_value, i, **overrides):
    row = dict(
        query_code=f"ACM_{i:03d}", query_text=text_value, category="Skincare",
        stage="Awareness", specificity="Broad", persona="Casual / Gift Buyer",
        study_pattern="brand_vs_brand", soa_focus="Mention Rate", rationale="test",
        status="Active",
    )
    row.update(overrides)
    return row


def _stored_texts(db, study_type="acme_full_1a2b3c"):
    with db.connect() as conn:
        return [
            r[0] for r in conn.execute(text(
                "SELECT query_text FROM soa_queries WHERE study_type = :st ORDER BY id"
            ), {"st": study_type}).fetchall()
        ]


def test_a_duplicate_spanning_two_batches_is_dropped(db):
    """Batch 2 repeats a question from batch 1 verbatim. Nothing inside a
    single batch could see that."""
    with db.begin() as conn:
        _insert_job(conn, target_count=20)

    batches = [
        ([_row(f"Batch one question {i}?", i) for i in range(10)], None),
        # First row repeats batch one's very first question.
        ([_row("Batch one question 0?", 100)]
         + [_row(f"Batch two question {i}?", 110 + i) for i in range(9)], None),
        ([_row("Filler question?", 200)], None),
    ]

    def _batch(study_name, description, batch_size, already_generated, api_key):
        return batches.pop(0)

    with patch("generation.query_generator.generate_query_batch", side_effect=_batch):
        worker.process_generation_jobs()

    stored = _stored_texts(db)
    assert stored.count("Batch one question 0?") == 1
    assert len(stored) == len(set(stored))


def test_a_cosmetic_variant_across_batches_is_dropped(db):
    """Trailing punctuation and casing drift is exactly how the model
    repeats itself — the normalizer is what makes these collide."""
    with db.begin() as conn:
        _insert_job(conn, target_count=3)

    batches = [
        ([_row("What is the best vitamin C serum?", 1)], None),
        ([_row("what is the best vitamin c serum", 2)], None),
        ([_row("Which retailer stocks it?", 3)], None),
        ([_row("Anything else?", 4)], None),
    ]

    def _batch(study_name, description, batch_size, already_generated, api_key):
        return batches.pop(0)

    with patch("generation.query_generator.generate_query_batch", side_effect=_batch):
        worker.process_generation_jobs()

    stored = _stored_texts(db)
    assert "what is the best vitamin c serum" not in stored
    assert "What is the best vitamin C serum?" in stored


def test_a_duplicate_within_one_batch_is_dropped(db):
    with db.begin() as conn:
        _insert_job(conn, target_count=2)

    batches = [
        ([_row("Same question?", 1), _row("Same question?", 2)], None),
        ([_row("A different question?", 3)], None),
    ]

    def _batch(study_name, description, batch_size, already_generated, api_key):
        return batches.pop(0)

    with patch("generation.query_generator.generate_query_batch", side_effect=_batch):
        worker.process_generation_jobs()

    assert _stored_texts(db) == ["Same question?", "A different question?"]


def test_dropped_rows_do_not_count_toward_created_count(db):
    """created_count is what the UI shows as progress, so it has to mean
    rows actually in the table."""
    with db.begin() as conn:
        _insert_job(conn, target_count=2)

    batches = [
        ([_row("Q1?", 1), _row("Q1?", 2)], None),
        ([_row("Q2?", 3)], None),
    ]

    def _batch(study_name, description, batch_size, already_generated, api_key):
        return batches.pop(0)

    with patch("generation.query_generator.generate_query_batch", side_effect=_batch):
        worker.process_generation_jobs()

    status, created_count, _ = _job_row(db.connect())
    assert status == "complete"
    assert created_count == 2


def test_the_avoid_list_only_ever_contains_accepted_rows(db):
    """A dropped duplicate must not be fed back as something to avoid —
    it is already represented by the row that was kept, and repeating it
    would just pad the prompt."""
    with db.begin() as conn:
        _insert_job(conn, target_count=3)

    seen_avoid_lists = []
    batches = [
        ([_row("Q1?", 1), _row("Q1?", 2)], None),
        ([_row("Q2?", 3), _row("Q3?", 4)], None),
    ]

    def _batch(study_name, description, batch_size, already_generated, api_key):
        seen_avoid_lists.append(list(already_generated))
        return batches.pop(0)

    with patch("generation.query_generator.generate_query_batch", side_effect=_batch):
        worker.process_generation_jobs()

    assert seen_avoid_lists[0] == []
    assert seen_avoid_lists[1] == ["Q1?"]      # one Q1, not two


def test_two_consecutive_all_duplicate_batches_stop_the_job(db):
    """Without this guard the loop never advances created_count and spins
    on OpenAI forever."""
    with db.begin() as conn:
        _insert_job(conn, target_count=50)

    def _batch(study_name, description, batch_size, already_generated, api_key):
        return [_row("The only question I know?", 1)], None

    with patch("generation.query_generator.generate_query_batch", side_effect=_batch) as mock_generate:
        worker.process_generation_jobs()

    # batch 1 accepted, batches 2 and 3 entirely duplicate -> stop.
    assert mock_generate.call_count == 3
    status, created_count, _ = _job_row(db.connect())
    assert status == "complete"
    assert created_count == 1


def test_a_single_all_duplicate_batch_does_not_stop_the_job(db):
    """One unlucky batch is normal; the guard is for a stall, not a
    hiccup."""
    with db.begin() as conn:
        _insert_job(conn, target_count=2)

    batches = [
        ([_row("Q1?", 1)], None),
        ([_row("Q1?", 2)], None),          # entirely duplicate
        ([_row("Q2?", 3)], None),          # recovers
    ]

    def _batch(study_name, description, batch_size, already_generated, api_key):
        return batches.pop(0)

    with patch("generation.query_generator.generate_query_batch", side_effect=_batch):
        worker.process_generation_jobs()

    status, created_count, _ = _job_row(db.connect())
    assert status == "complete"
    assert created_count == 2
    assert _stored_texts(db) == ["Q1?", "Q2?"]
