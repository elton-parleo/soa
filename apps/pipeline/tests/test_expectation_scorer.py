"""
Layer 2's persistence — one soa_runs row in, one soa_expectation_outcomes
row out.

The properties worth holding: a question with no expectation is skipped
rather than scored (category control carries none deliberately, and so
does every query written before the tiers existed), a run whose answer
never arrived still gets a row so it is visible in the sample count
rather than quietly missing from a denominator, and a re-score replaces
its row rather than appending a second one.
"""
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, event, text

from parser.expectation_client import ExtractionResult
from scoring import expectation_scorer as scorer_module
from soa_shared import expected_answers as ea

PRICE = ea.price('22.99')
SOURCE_REF = {
    'merchant_slug': 'wiggle-and-snug',
    'listing_id': 90,
    'variant_id': 'snug-fit-diapers-s3-small',
    'published_at': '2026-09-04T20:49:40+00:00',
    'attribution': ['Size 3', 'Small Pack', '84'],
    'attribution_rivals': ['Size 1', 'Big Pack'],
}

EXTRACTION = {
    "prices": [{"amount": "22.99", "currency": "USD",
                "attributed_product": "Size 3 Small Pack"}],
    "codes": [], "pack_counts": [], "gtins": [], "member_prices": [], "points": [],
    "brand_mentioned": True, "sources_cited": ["trueshopstore.com"],
    "extraction_confident": True, "extraction_note": None,
}


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
            CREATE TABLE soa_queries (
                id INTEGER PRIMARY KEY, query_text TEXT, tier TEXT,
                expected_answer TEXT, provenance TEXT, source_ref TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, query_id INTEGER,
                platform TEXT, run_number INTEGER, raw_response TEXT, status TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_expectation_outcomes (
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
    monkeypatch.setattr(scorer_module, "engine", engine)
    return engine


def seed(db, *, expectation=PRICE, tier='catalog_accuracy',
         answer='The Size 3 Small Pack is $22.99.', status='success'):
    with db.begin() as conn:
        conn.execute(text("""
            INSERT INTO soa_queries (id, query_text, tier, expected_answer,
                                     provenance, source_ref)
            VALUES (1, 'What does it cost?', :tier, :expected, 'catalog', :ref)
        """), {
            "tier": tier,
            "expected": json.dumps(expectation) if expectation else None,
            "ref": json.dumps(SOURCE_REF),
        })
        conn.execute(text("""
            INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number,
                                  raw_response, status)
            VALUES (7, 3, 1, 'chatgpt', 1, :answer, :status)
        """), {"answer": answer, "status": status})


def outcomes(db):
    with db.connect() as conn:
        return conn.execute(
            text("SELECT * FROM soa_expectation_outcomes")
        ).mappings().all()


class FakeClient:
    def __init__(self, record=None):
        self.record = record if record is not None else EXTRACTION
        self.extract = AsyncMock(return_value=ExtractionResult(
            record=self.record, model='gpt-5.4-mini', latency_ms=400,
        ))


def make_scorer(record=None, history=None):
    class FakeHistory:
        def for_variant(self, _slug, _vid):
            return history
    return scorer_module.ExpectationScorer(FakeClient(record), FakeHistory())


def score(db, scorer=None, run_id=7):
    return asyncio.run((scorer or make_scorer()).score_run(run_id))


# ── the happy path ────────────────────────────────────────────────────────

def test_one_run_becomes_one_outcome_row(db):
    seed(db)
    result = score(db)

    assert result.status == 'success'
    assert result.outcome == 'exact'

    (row,) = outcomes(db)
    assert row['run_id'] == 7
    assert row['query_id'] == 1
    assert row['cycle_id'] == 3
    assert row['platform'] == 'chatgpt'
    assert row['tier'] == 'catalog_accuracy'
    assert row['outcome'] == 'exact'


def test_the_row_stores_the_expectation_as_a_copy_not_a_join(db):
    """Republishing rewrites the question's expectation, and an outcome
    reading through to the new one would silently restate what it had
    compared against."""
    seed(db)
    score(db)
    (row,) = outcomes(db)
    assert json.loads(row['expected_answer']) == PRICE


def test_the_row_stores_the_extraction_it_compared(db):
    """Every rate traces back to a stored answer AND the transcription of
    it, so a verdict is re-checkable rather than merely re-runnable."""
    seed(db)
    score(db)
    (row,) = outcomes(db)
    assert json.loads(row['extraction']) == EXTRACTION


def test_the_row_stores_the_publish_timestamp_it_compared_against(db):
    """Phase 2 plots outcomes against TrueSync publish markers from this
    field, with no re-run."""
    seed(db)
    score(db)
    (row,) = outcomes(db)
    assert str(row['record_published_at']).startswith('2026-09-04')


def test_the_answer_text_is_reachable_from_the_row_not_copied_into_it(db):
    """soa_runs already stores raw_response permanently and is the unique
    (cycle, query, platform, run_number) slot, so run_id IS
    question x surface x sample — and a second copy could only ever
    disagree with it."""
    seed(db)
    score(db)
    (row,) = outcomes(db)
    with db.connect() as conn:
        answer = conn.execute(
            text("SELECT raw_response FROM soa_runs WHERE id = :id"),
            {"id": row['run_id']},
        ).scalar()
    assert answer == 'The Size 3 Small Pack is $22.99.'


def test_the_source_attribution_bits_are_stored_beside_the_outcome(db):
    seed(db, expectation=ea.brand_mention('Wiggle & Snug', 'trueshopstore.com'))
    score(db)
    (row,) = outcomes(db)
    assert row['source_attribution'] == 'brand_domain'
    assert row['domain_cited'] in (1, True)


# ── what is not scored ────────────────────────────────────────────────────

def test_a_question_with_no_expectation_is_skipped_not_scored(db):
    """Category control carries none deliberately, and so does every
    query written before the tiers existed."""
    seed(db, expectation=None, tier='category_control')
    result = score(db)

    assert result.status == 'skipped_no_expectation'
    assert outcomes(db) == []


def test_an_unscoreable_expectation_is_skipped_rather_than_crashing(db):
    seed(db, expectation={'type': 'shipping_speed', 'value': '2 days'})
    assert score(db).status == 'skipped_no_expectation'
    assert outcomes(db) == []


def test_scoreable_run_ids_selects_on_the_expectation_not_the_tier(db):
    """A control question has a tier and no expectation and must not be
    scored; a hand-written question could have an expectation and no tier
    and should be."""
    with db.begin() as conn:
        conn.execute(text("""
            INSERT INTO soa_queries (id, query_text, tier, expected_answer, source_ref)
            VALUES (1, 'priced', 'catalog_accuracy', :e, '{}'),
                   (2, 'control', 'category_control', NULL, '{}'),
                   (3, 'untiered', NULL, :e, '{}')
        """), {"e": json.dumps(PRICE)})
        conn.execute(text("""
            INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number, status)
            VALUES (10, 3, 1, 'chatgpt', 1, 'success'),
                   (11, 3, 2, 'chatgpt', 1, 'success'),
                   (12, 3, 3, 'chatgpt', 1, 'success')
        """))
    assert scorer_module.scoreable_run_ids(3) == [10, 12]


# ── a run whose answer never arrived ──────────────────────────────────────

def test_a_failed_run_still_gets_a_row_so_it_is_visible(db):
    """A missing row would remove the run from a denominator silently.
    An unscoreable row keeps it in the sample count and says why."""
    seed(db, answer=None, status='error')
    result = score(db)

    assert result.status == 'skipped_no_answer'
    (row,) = outcomes(db)
    assert row['outcome'] == 'unscoreable'
    assert "'error'" in row['outcome_reason']


def test_a_failed_run_never_reaches_the_model(db):
    seed(db, answer=None, status='timeout')
    scorer = make_scorer()
    asyncio.run(scorer.score_run(7))
    scorer.client.extract.assert_not_awaited()


def test_an_answer_the_extractor_could_not_read_is_unscoreable(db):
    seed(db)
    unreadable = {**EXTRACTION, 'extraction_confident': False,
                  'extraction_note': 'answer truncated'}
    result = score(db, make_scorer(record=unreadable))

    assert result.outcome == 'unscoreable'
    (row,) = outcomes(db)
    assert row['outcome_reason'] == 'answer truncated'


# ── staleness reads history at scoring time ───────────────────────────────

def test_a_prior_published_price_scores_stale_and_names_the_publication(db):
    seed(db, answer='It is $21.49.')
    stale_extraction = {
        **EXTRACTION,
        'prices': [{'amount': '21.49', 'currency': 'USD',
                    'attributed_product': 'Size 3 Small Pack'}],
    }
    history = [
        {'published_at': '2026-08-15T00:00:00+00:00', 'list_price': '21.49',
         'member_price': None, 'member_tier_name': None},
        {'published_at': '2026-09-04T20:49:40+00:00', 'list_price': '22.99',
         'member_price': None, 'member_tier_name': None},
    ]
    result = score(db, make_scorer(record=stale_extraction, history=history))

    assert result.outcome == 'stale'
    (row,) = outcomes(db)
    assert str(row['matched_published_at']).startswith('2026-08-15')


def test_without_history_the_same_answer_scores_wrong(db):
    """Without a record saying a value was once published we cannot claim
    it was."""
    seed(db, answer='It is $21.49.')
    stale_extraction = {
        **EXTRACTION,
        'prices': [{'amount': '21.49', 'currency': 'USD',
                    'attributed_product': 'Size 3 Small Pack'}],
    }
    result = score(db, make_scorer(record=stale_extraction, history=None))
    assert result.outcome == 'wrong'


# ── re-scoring ────────────────────────────────────────────────────────────

def test_a_rescore_replaces_the_row_rather_than_appending(db):
    """A rate cannot double-count a run that was scored twice."""
    seed(db)
    score(db)
    score(db)
    assert len(outcomes(db)) == 1


def test_a_rescore_records_the_new_verdict(db):
    seed(db)
    score(db)
    wrong = {**EXTRACTION, 'prices': [
        {'amount': '5.00', 'currency': 'USD', 'attributed_product': 'Size 3 Small Pack'},
    ]}
    score(db, make_scorer(record=wrong))

    (row,) = outcomes(db)
    assert row['outcome'] == 'wrong'


# ── secondary expectations ────────────────────────────────────────────────

def test_a_volunteered_secondary_is_stored_beside_the_outcome(db):
    seed(db, expectation=ea.with_secondary(PRICE, [ea.gtin('884400137609')]))
    volunteered = {
        **EXTRACTION,
        'gtins': [{'value': '884400137609', 'attributed_product': 'Size 3 Small Pack'}],
    }
    score(db, make_scorer(record=volunteered))

    (row,) = outcomes(db)
    assert json.loads(row['secondary_results']) == [
        {'type': 'gtin', 'outcome': 'exact', 'reason': 'stated 884400137609'},
    ]


def test_an_unvolunteered_secondary_is_stored_as_absent(db):
    """The report gives each secondary its own column with the same rate
    rules as everything else, and it cannot have a denominator if the
    absents are thrown away."""
    seed(db, expectation=ea.with_secondary(PRICE, [ea.gtin('884400137609')]))
    score(db)
    (row,) = outcomes(db)
    assert json.loads(row['secondary_results']) == [
        {'type': 'gtin', 'outcome': 'absent', 'reason': 'the answer stated no GTIN'},
    ]


def test_a_question_with_no_secondary_leaves_the_column_null(db):
    seed(db, expectation=PRICE)
    score(db)
    (row,) = outcomes(db)
    assert row['secondary_results'] is None


# ── the extractor is told the brand and nothing else ──────────────────────

def test_the_extractor_is_handed_the_brand_and_its_domain_and_no_more(db):
    """The domain is for the deterministic pass after the call — telling
    the brand's own site apart from another brand when the answer writes
    one as the other. It never reaches the prompt: build_extraction_prompt
    takes the name alone, and handing a model the domain would tell it
    which citation we are hoping to find."""
    seed(db, expectation=ea.brand_mention('Wiggle & Snug', 'trueshopstore.com'))
    scorer = make_scorer()
    asyncio.run(scorer.score_run(7))

    kwargs = scorer.client.extract.call_args.kwargs
    assert kwargs == {
        'brand': 'Wiggle & Snug', 'brand_domain': 'trueshopstore.com',
    }


def test_the_domain_never_reaches_the_prompt():
    from parser.expectation_prompts import build_extraction_prompt
    prompt = build_extraction_prompt('Wiggle & Snug')
    assert 'Wiggle & Snug' in prompt
    assert 'trueshopstore' not in prompt
