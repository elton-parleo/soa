"""
The extraction validation harness.

The property that matters: the script cannot produce an agreement rate on
its own. It samples and it records, and the number in between comes from
a person — a script that scored itself would be measuring the thing it
exists to be checked against.
"""
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event, text

from scripts import validate_extractions as ve


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _):
        dbapi_conn.create_function(
            "NOW", 0, lambda: datetime.now(timezone.utc).isoformat(),
        )

    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, cycle_code TEXT UNIQUE,
                extraction_validation TEXT, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_queries (
                id INTEGER PRIMARY KEY, query_code TEXT, query_text TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, run_number INTEGER, raw_response TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_expectation_outcomes (
                id INTEGER PRIMARY KEY, run_id INTEGER, query_id INTEGER,
                cycle_id INTEGER, platform TEXT, tier TEXT,
                expected_answer TEXT, extraction TEXT, outcome TEXT,
                outcome_reason TEXT
            )
        """)
        conn.exec_driver_sql(
            "INSERT INTO soa_cycles (id, cycle_code) VALUES (1, 'fc-2026-09')"
        )
    monkeypatch.setattr(ve, "engine", engine)
    return engine


def seed(db, outcomes, *, answer='The Size 3 pack is $22.99.'):
    with db.begin() as conn:
        for i, outcome in enumerate(outcomes, start=1):
            conn.execute(text("""
                INSERT INTO soa_queries (id, query_code, query_text)
                VALUES (:i, :code, 'What does it cost?')
            """), {"i": i, "code": f"WS_{i:03d}"})
            conn.execute(text("""
                INSERT INTO soa_runs (id, run_number, raw_response)
                VALUES (:i, 1, :answer)
            """), {"i": i, "answer": answer})
            conn.execute(text("""
                INSERT INTO soa_expectation_outcomes (
                    run_id, query_id, cycle_id, platform, tier,
                    expected_answer, extraction, outcome, outcome_reason
                ) VALUES (
                    :i, :i, 1, 'chatgpt', 'catalog_accuracy',
                    :expected, :extraction, :outcome, 'because'
                )
            """), {
                "i": i,
                "expected": json.dumps({"type": "price", "amount": "22.99",
                                        "currency": "USD"}),
                "extraction": json.dumps({"prices": [{"amount": "22.99"}]}),
                "outcome": outcome,
            })


# ── sampling ──────────────────────────────────────────────────────────────

def test_sampling_is_stratified_by_outcome(db, tmp_path, capsys):
    """A uniform sample of a run that is 80% exact spends 80% of a
    human's attention on the easy case; the readings worth checking
    hardest are the ones that produced a wrong or an unscoreable."""
    seed(db, ['exact'] * 20 + ['wrong', 'unscoreable', 'stale'])
    out = tmp_path / "v.md"

    ve.main(['sample', '--cycle', 'fc-2026-09', '--n', '4', '--out', str(out)])
    document = out.read_text()

    # All three rare outcomes reach a four-row sample.
    assert 'wrong' in document
    assert 'unscoreable' in document
    assert 'stale' in document


def test_the_sample_is_reproducible_and_says_its_seed(db, tmp_path):
    """A validation nobody can reproduce is a validation nobody can
    check."""
    seed(db, ['exact'] * 10)
    first = tmp_path / "a.md"
    second = tmp_path / "b.md"

    ve.main(['sample', '--cycle', 'fc-2026-09', '--n', '3', '--seed', '7', '--out', str(first)])
    ve.main(['sample', '--cycle', 'fc-2026-09', '--n', '3', '--seed', '7', '--out', str(second)])

    assert first.read_text() == second.read_text()
    assert 'seed 7' in first.read_text()


def test_the_answer_comes_before_the_extraction(db, tmp_path):
    """A reader shown the extraction first reads the answer looking for
    confirmation of it."""
    seed(db, ['exact'])
    out = tmp_path / "v.md"
    ve.main(['sample', '--cycle', 'fc-2026-09', '--n', '1', '--out', str(out)])

    document = out.read_text()
    assert document.index('### The answer') < document.index('### What the extractor read')


def test_the_verdict_is_shown_last_and_commented_out(db, tmp_path):
    """The question is 'did the extractor read this correctly', not 'was
    the verdict right' — so the verdict is there to check against
    afterwards, not to prime with."""
    seed(db, ['wrong'])
    out = tmp_path / "v.md"
    ve.main(['sample', '--cycle', 'fc-2026-09', '--n', '1', '--out', str(out)])

    document = out.read_text()
    assert document.index('### AGREE / DISAGREE:') < document.index('<!-- expected')


def test_a_long_answer_is_truncated_visibly(db, tmp_path):
    seed(db, ['exact'], answer='x' * 9000)
    out = tmp_path / "v.md"
    ve.main(['sample', '--cycle', 'fc-2026-09', '--n', '1', '--out', str(out)])
    assert '…(truncated)' in out.read_text()


def test_sampling_a_cycle_with_nothing_scored_says_so(db, capsys):
    assert ve.main(['sample', '--cycle', 'fc-2026-09', '--n', '5']) == 1
    assert 'no scored expectations' in capsys.readouterr().out


def test_an_unknown_cycle_is_an_error_not_an_empty_document(db):
    with pytest.raises(SystemExit):
        ve.main(['sample', '--cycle', 'nope', '--n', '5'])


# ── recording ─────────────────────────────────────────────────────────────

def test_recording_writes_the_humans_number_onto_the_cycle(db):
    seed(db, ['exact'])
    ve.main([
        'record', '--cycle', 'fc-2026-09', '--sample-size', '40',
        '--agreed', '37', '--by', 'elton', '--notes', 'ranged prices',
    ])

    with db.connect() as conn:
        stored = json.loads(conn.execute(
            text("SELECT extraction_validation FROM soa_cycles WHERE id = 1")
        ).scalar())

    assert stored['sample_size'] == 40
    assert stored['agreed'] == 37
    assert stored['agreement_rate'] == 0.925
    assert stored['validated_by'] == 'elton'
    assert stored['notes'] == 'ranged prices'
    assert stored['validated_at']


def test_the_field_is_null_until_someone_records(db):
    seed(db, ['exact'])
    with db.connect() as conn:
        assert conn.execute(
            text("SELECT extraction_validation FROM soa_cycles WHERE id = 1")
        ).scalar() is None


def test_recording_refuses_an_impossible_number(db):
    with pytest.raises(SystemExit):
        ve.main([
            'record', '--cycle', 'fc-2026-09', '--sample-size', '10',
            '--agreed', '11', '--by', 'elton',
        ])


def test_recording_requires_a_person_to_attribute_it_to(db):
    """A validated agreement rate with nobody's name on it is a number
    nobody stands behind."""
    with pytest.raises(SystemExit):
        ve.main([
            'record', '--cycle', 'fc-2026-09', '--sample-size', '10',
            '--agreed', '9',
        ])


def test_the_script_never_computes_an_agreement_rate_itself(db, tmp_path):
    """Sampling produces a document, not a verdict. If this ever starts
    writing extraction_validation on its own, the number in the report
    stops meaning what it says."""
    seed(db, ['exact', 'wrong'])
    ve.main(['sample', '--cycle', 'fc-2026-09', '--n', '2',
             '--out', str(tmp_path / "v.md")])

    with db.connect() as conn:
        assert conn.execute(
            text("SELECT extraction_validation FROM soa_cycles WHERE id = 1")
        ).scalar() is None
