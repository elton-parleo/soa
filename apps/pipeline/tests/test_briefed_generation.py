"""
Tests for the briefed generation path — worker.py::_run_briefed_generation,
reached from process_generation_jobs when the job row carries a
study_pattern (migration 3f8e2a91c7d4).

The discriminator is the load-bearing part. study_pattern is NULL exactly
when a job was queued before the brief existed, or by a client sending
only study_name/description/target_count, and such a job must run the way
it would have run the day it was queued — a pending row must not be
retroactively reinterpreted under rules nobody agreed to when they
submitted it. test_process_generation_jobs.py covers that legacy side;
this file covers the briefed side and the boundary between them.

Same in-memory sqlite harness as the other worker tests.
"""
import json
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


STUDY_TYPE = "prestige_beauty_1a2b3c"

BRIEF = {
    "study_pattern": "retailer",
    "retailer_names": ["Sephora", "Ulta Beauty", "Nordstrom"],
    "allowed_categories": ["Skincare", "Fragrance"],
    "stage_targets": {"Awareness": 2, "Comparison": 2},
    "rotate_named_retailer": True,
    "naming_rule_enabled": True,
    "personas": ["Beauty Enthusiast"],
    "specificity_mode": "even_split",
}


def _insert_job(conn, brief=None, target_count=4, study_type=STUDY_TYPE):
    """brief=None inserts a legacy job (study_pattern NULL)."""
    brief = {} if brief is None else brief
    conn.execute(text("""
        INSERT INTO soa_query_generation_jobs
          (study_type, study_name, description, target_count, created_count,
           status, organization_id, created_by,
           study_pattern, retailer_names, allowed_categories, stage_targets,
           rotate_named_retailer, naming_rule_enabled, personas, specificity_mode)
        VALUES
          (:st, 'Prestige Beauty', 'Prestige skincare and fragrance', :tc, 0,
           'pending', 1, 'u1',
           :study_pattern, :retailer_names, :allowed_categories, :stage_targets,
           :rotate, :naming_rule, :personas, :specificity_mode)
    """), {
        "st": study_type,
        "tc": target_count,
        "study_pattern": brief.get("study_pattern"),
        "retailer_names": json.dumps(brief["retailer_names"]) if "retailer_names" in brief else None,
        "allowed_categories": json.dumps(brief["allowed_categories"]) if "allowed_categories" in brief else None,
        "stage_targets": json.dumps(brief["stage_targets"]) if "stage_targets" in brief else None,
        "rotate": brief.get("rotate_named_retailer"),
        "naming_rule": brief.get("naming_rule_enabled"),
        "personas": json.dumps(brief["personas"]) if "personas" in brief else None,
        "specificity_mode": brief.get("specificity_mode"),
    })


def _job_row(db, study_type=STUDY_TYPE):
    with db.connect() as conn:
        return conn.execute(text("""
            SELECT status, created_count, error_message, provenance
            FROM soa_query_generation_jobs WHERE study_type = :st
        """), {"st": study_type}).fetchone()


def _stored(db, study_type=STUDY_TYPE):
    with db.connect() as conn:
        return conn.execute(text("""
            SELECT query_text, stage, category, study_pattern
            FROM soa_queries WHERE study_type = :st ORDER BY id
        """), {"st": study_type}).fetchall()


def _row(stage, suffix="", category="Skincare"):
    return {
        'query_text': f"Question about {stage}{suffix}",
        'category': category,
        'stage': stage,
        'specificity': 'Mid',
        'persona': 'Beauty Enthusiast',
        'study_pattern': 'retailer',
        'status': 'Active',
        'subscription_state': None,
        'soa_focus': 'Mention Rate',
        'rationale': 'test',
    }


def _perfect_batch():
    return [_row('Awareness', "-0"), _row('Awareness', "-1"),
            _row('Comparison', "-0"), _row('Comparison', "-1")]


# ─── the path discriminator ───────────────────────────────────────────────

def test_a_job_with_a_study_pattern_takes_the_briefed_path(db):
    with db.begin() as conn:
        _insert_job(conn, BRIEF)

    with patch("generation.query_generator._call_openai_and_validate") as mock_call, \
         patch("generation.query_generator.review_semantic_duplicates", return_value=[]), \
         patch("generation.query_generator.review_coherence", return_value=[]), \
         patch("generation.query_generator.generate_query_batch") as legacy:
        mock_call.return_value = (_perfect_batch(), None)
        worker.process_generation_jobs()

    legacy.assert_not_called()          # never the multi-batch loop
    status, created_count, error_message, _ = _job_row(db)
    assert status == "complete"
    assert created_count == 4
    assert error_message is None
    assert len(_stored(db)) == 4


def test_a_job_without_a_study_pattern_still_takes_the_legacy_path(db):
    """A row queued before the brief existed runs under the rules it was
    queued under."""
    with db.begin() as conn:
        _insert_job(conn, brief=None, target_count=2)

    rows = [_row('Awareness', "-0"), _row('Awareness', "-1")]
    with patch("generation.query_generator.generate_query_batch", return_value=(rows, None)) as legacy, \
         patch("generation.query_generator._call_openai_and_validate") as briefed:
        worker.process_generation_jobs()

    legacy.assert_called_once()
    briefed.assert_not_called()
    status, created_count, _, provenance = _job_row(db)
    assert status == "complete"
    assert created_count == 2
    assert provenance is None           # the legacy path records none


# ─── the brief actually reaches the generator ─────────────────────────────

def test_every_brief_field_reaches_the_generator(db):
    with db.begin() as conn:
        _insert_job(conn, BRIEF)

    with patch("generation.query_generator.generate_and_review_study") as mock_gen:
        mock_gen.return_value = (_perfect_batch(), {'shortfall_by_stage': {}})
        worker.process_generation_jobs()

    kwargs = mock_gen.call_args.kwargs
    assert kwargs['study_name'] == 'Prestige Beauty'
    assert kwargs['description'] == 'Prestige skincare and fragrance'
    assert kwargs['study_pattern'] == 'retailer'
    assert kwargs['retailer_names'] == ["Sephora", "Ulta Beauty", "Nordstrom"]
    assert kwargs['allowed_categories'] == ["Skincare", "Fragrance"]
    assert kwargs['stage_targets'] == {"Awareness": 2, "Comparison": 2}
    assert kwargs['rotate_named_retailer'] is True
    assert kwargs['naming_rule_enabled'] is True
    assert kwargs['personas'] == ["Beauty Enthusiast"]
    assert kwargs['specificity_mode'] == 'even_split'


def test_json_columns_survive_the_round_trip_as_python(db):
    """sqlite hands JSON columns back as TEXT; Postgres hands them back
    parsed. The generator must see lists and dicts either way."""
    with db.begin() as conn:
        _insert_job(conn, BRIEF)

    with patch("generation.query_generator.generate_and_review_study") as mock_gen:
        mock_gen.return_value = ([_row('Awareness')], {})
        worker.process_generation_jobs()

    kwargs = mock_gen.call_args.kwargs
    assert isinstance(kwargs['retailer_names'], list)
    assert isinstance(kwargs['stage_targets'], dict)


def test_the_stamped_study_pattern_lands_on_the_persisted_rows(db):
    with db.begin() as conn:
        _insert_job(conn, {**BRIEF, "study_pattern": "brand_at_retail"})

    stamped = [dict(r, study_pattern='brand_at_retail') for r in _perfect_batch()]
    with patch("generation.query_generator.generate_and_review_study",
               return_value=(stamped, {})):
        worker.process_generation_jobs()

    assert {r[3] for r in _stored(db)} == {'brand_at_retail'}


# ─── falling back on a partial brief ──────────────────────────────────────

def test_a_missing_stage_targets_falls_back_to_an_even_split(db):
    """These are shaping inputs, and the job has a study_pattern, so the
    brief is real even when a field of it is absent — falling back beats
    failing."""
    brief = {k: v for k, v in BRIEF.items() if k != 'stage_targets'}
    with db.begin() as conn:
        _insert_job(conn, brief, target_count=10)

    with patch("generation.query_generator.generate_and_review_study") as mock_gen:
        mock_gen.return_value = ([_row('Awareness')], {})
        worker.process_generation_jobs()

    targets = mock_gen.call_args.kwargs['stage_targets']
    assert sum(targets.values()) == 10
    assert len(targets) == 4                       # every QUERY_STAGES stage
    assert max(targets.values()) - min(targets.values()) <= 1


def test_missing_allowed_categories_falls_back_to_every_category(db):
    from soa_shared.constants import QUERY_CATEGORIES

    brief = {k: v for k, v in BRIEF.items() if k != 'allowed_categories'}
    with db.begin() as conn:
        _insert_job(conn, brief)

    with patch("generation.query_generator.generate_and_review_study") as mock_gen:
        mock_gen.return_value = ([_row('Awareness')], {})
        worker.process_generation_jobs()

    assert mock_gen.call_args.kwargs['allowed_categories'] == list(QUERY_CATEGORIES)


def test_null_booleans_default_to_on(db):
    brief = {k: v for k, v in BRIEF.items()
             if k not in ('rotate_named_retailer', 'naming_rule_enabled')}
    with db.begin() as conn:
        _insert_job(conn, brief)

    with patch("generation.query_generator.generate_and_review_study") as mock_gen:
        mock_gen.return_value = ([_row('Awareness')], {})
        worker.process_generation_jobs()

    kwargs = mock_gen.call_args.kwargs
    assert kwargs['rotate_named_retailer'] is True
    assert kwargs['naming_rule_enabled'] is True


# ─── provenance ───────────────────────────────────────────────────────────

def test_provenance_is_recorded_on_the_job_row(db):
    with db.begin() as conn:
        _insert_job(conn, BRIEF)

    with patch("generation.query_generator._call_openai_and_validate") as mock_call, \
         patch("generation.query_generator.review_semantic_duplicates",
               return_value=[{'members': [0, 1], 'keep': 0, 'reason': 'same question',
                              'member_texts': ['a', 'b'], 'keep_text': 'a'}]), \
         patch("generation.query_generator.review_coherence",
               return_value=[{'index': 0, 'verdict': 'out_of_scope',
                              'query_text': 'x', 'category': 'Skincare',
                              'reason': 'off brief'}]):
        mock_call.return_value = (_perfect_batch(), None)
        worker.process_generation_jobs()

    _, _, _, raw = _job_row(db)
    provenance = json.loads(raw)

    assert provenance['rows_generated'] == 4
    assert provenance['requested_by_stage'] == {'Awareness': 2, 'Comparison': 2}
    assert provenance['delivered_by_stage'] == {'Awareness': 2, 'Comparison': 2}
    assert len(provenance['semantic_duplicate_groups']) == 1
    assert len(provenance['coherence_findings_by_outcome']['out_of_scope']) == 1
    assert provenance['retailers_named'] == ["Sephora", "Ulta Beauty", "Nordstrom"]


def test_provenance_records_what_was_dropped_and_what_fell_short(db):
    with db.begin() as conn:
        _insert_job(conn, BRIEF)

    batches = [
        # A duplicate, and a row outside the allowed categories.
        [_row('Awareness', "-a"), _row('Awareness', "-a"),
         _row('Comparison', "-x", category='Baby Care')],
    ] + [[] for _ in range(20)]

    with patch("generation.query_generator._call_openai_and_validate",
               side_effect=[(b, None) for b in batches]), \
         patch("generation.query_generator.review_semantic_duplicates", return_value=[]), \
         patch("generation.query_generator.review_coherence", return_value=[]):
        worker.process_generation_jobs()

    _, created_count, _, raw = _job_row(db)
    provenance = json.loads(raw)

    assert len(provenance['exact_duplicates_dropped']) == 1
    assert provenance['category_drops'][0]['category'] == 'Baby Care'
    assert provenance['shortfall_by_stage'] == {'Awareness': 1, 'Comparison': 2}
    # Reported, not raised — the one good row is still committed.
    assert created_count == 1


def test_a_shortfall_still_completes_the_job(db):
    """Hard-failing a study because it came up short would discard every
    query that WAS generated."""
    with db.begin() as conn:
        _insert_job(conn, BRIEF)

    with patch("generation.query_generator._call_openai_and_validate",
               side_effect=[([_row('Awareness', "-0")], None)] + [([], None)] * 20), \
         patch("generation.query_generator.review_semantic_duplicates", return_value=[]), \
         patch("generation.query_generator.review_coherence", return_value=[]):
        worker.process_generation_jobs()

    status, created_count, error_message, _ = _job_row(db)
    assert status == "complete"
    assert created_count == 1
    assert error_message is None


def test_a_job_that_produces_nothing_is_failed_not_completed(db):
    """Never 'complete' with 0 queries — the frontend would render that
    as a normal, if oddly empty, study."""
    with db.begin() as conn:
        _insert_job(conn, BRIEF)

    with patch("generation.query_generator._call_openai_and_validate",
               return_value=([], None)), \
         patch("generation.query_generator.review_semantic_duplicates", return_value=[]), \
         patch("generation.query_generator.review_coherence", return_value=[]):
        worker.process_generation_jobs()

    status, created_count, error_message, raw = _job_row(db)
    assert status == "failed"
    assert created_count == 0
    assert error_message
    assert raw is not None              # the record of the failure survives


def test_a_generator_exception_fails_the_job_cleanly(db):
    with db.begin() as conn:
        _insert_job(conn, BRIEF)

    with patch("generation.query_generator.generate_and_review_study",
               side_effect=RuntimeError("openai exploded")):
        worker.process_generation_jobs()

    status, _, error_message, _ = _job_row(db)
    assert status == "failed"
    assert "openai exploded" in error_message


def test_a_provenance_write_failure_does_not_destroy_the_study(db):
    """The report is about a study that already exists. Failing the job
    because the report could not be written destroys the thing the
    report is about."""
    with db.begin() as conn:
        _insert_job(conn, BRIEF)

    with patch("generation.query_generator.generate_and_review_study",
               return_value=(_perfect_batch(), {})), \
         patch.object(worker, "_record_provenance", side_effect=RuntimeError("db gone")):
        with pytest.raises(RuntimeError):
            worker.process_generation_jobs()

    # The rows and the completed status are committed before provenance
    # is even attempted.
    status, created_count, _, _ = _job_row(db)
    assert status == "complete"
    assert created_count == 4
    assert len(_stored(db)) == 4


def test_record_provenance_swallows_its_own_failures(db):
    with db.begin() as conn:
        _insert_job(conn, BRIEF)

    with patch.object(worker, "engine") as broken:
        broken.connect.side_effect = RuntimeError("db gone")
        worker._record_provenance(1, {"rows_generated": 4})   # must not raise
