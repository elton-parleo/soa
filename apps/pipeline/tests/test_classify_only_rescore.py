"""
2B: rescore --cycle <code> --classify-only.

Re-runs the deterministic classifier over each outcome row's STORED
expectation and extraction. The properties held here:

  * no model call — the scorer's extraction client raises if touched;
  * the same stored rows classify identically twice, and a second
    classify-only run moves nothing and writes identical rows;
  * every moved row names the rule that moved it.
"""
import json
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event, text

from clients.truesync_catalog import build_snapshot
from scoring import expectation_scorer as scorer_module
from scripts import rescore_cycle as rc
from soa_shared import expected_answers as ea

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')

SIZE_3_SMALL = {
    'merchant_slug': 'wiggle-and-snug', 'listing_id': 90,
    'variant_id': 'snug-fit-diapers-s3-small',
    'attribution': ['Size 3', 'small pack'],
    'attribution_rivals': ['big pack', 'Size 1', 'Size 2', 'Size 4', 'Size 5', 'Size 6'],
}
ACME_REF = {
    'merchant_slug': 'acme-baby', 'variant_id': '00012345678905', 'gtin': '00012345678905',
    'own_domain': 'acmebaby.example', 'merchant_kind': 'brand',
    'retailer_list': ['target.com', 'walmart.com'],
}


def _json(*parts):
    with open(os.path.join(FIXTURES, *parts)) as fh:
        return json.load(fh)


def extraction(prices):
    return {'prices': prices, 'codes': [], 'pack_counts': [], 'gtins': [], 'member_prices': [],
            'points': [], 'brand_mentioned': True, 'sources_cited': [],
            'extraction_confident': True, 'extraction_note': None}


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _now(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

    with engine.begin() as c:
        c.exec_driver_sql("""CREATE TABLE soa_cycles (id INTEGER PRIMARY KEY, cycle_code TEXT,
            study_type TEXT, start_date DATE, created_at TIMESTAMP,
            reference_prices TEXT, reference_as_of TIMESTAMP)""")
        c.exec_driver_sql("""CREATE TABLE soa_queries (id INTEGER PRIMARY KEY, tier TEXT,
            expected_answer TEXT, source_ref TEXT, study_type TEXT, query_code TEXT)""")
        c.exec_driver_sql("""CREATE TABLE soa_runs (id INTEGER PRIMARY KEY, cycle_id INTEGER,
            query_id INTEGER, platform TEXT, run_number INTEGER, raw_response TEXT, status TEXT,
            retrieved_sources TEXT, grounding TEXT, surface TEXT, collector TEXT, answer_status TEXT)""")
        c.exec_driver_sql("""CREATE TABLE soa_expectation_outcomes (
            id INTEGER PRIMARY KEY, run_id INTEGER UNIQUE, query_id INTEGER, cycle_id INTEGER,
            platform TEXT, tier TEXT, expected_answer TEXT, extraction TEXT, outcome TEXT,
            outcome_reason TEXT, domain_cited BOOLEAN, source_attribution TEXT,
            secondary_results TEXT, record_published_at TIMESTAMP, matched_published_at TIMESTAMP,
            near_miss BOOLEAN, extraction_model TEXT, flags TEXT, claim_results TEXT,
            source_split TEXT, reason_code TEXT, surface TEXT, scored_at TIMESTAMP)""")
        c.execute(text("""INSERT INTO soa_cycles (id, cycle_code, study_type, start_date,
            created_at, reference_prices) VALUES (1, 'WS-2B', 'ws', '2026-10-09',
            '2026-10-09T12:30:00+00:00', :ref)"""),
                  {"ref": json.dumps(_json('retailer_prices', 'acme_baby_as_of_cycle2.json'))})
    monkeypatch.setattr(rc, "engine", engine)
    monkeypatch.setattr(scorer_module, "engine", engine)
    return engine


ROWS = [
    # (code, expectation, source_ref, stored extraction prices, stored outcome)
    ('Q1', ea.price('22.99'), SIZE_3_SMALL,
     [{'amount': '22.99', 'currency': 'USD', 'attributed_product': 'Size 3 small pack'}], 'exact'),
    ('Q2', ea.price('17.99'), {**SIZE_3_SMALL, 'variant_id': 'snug-fit-diapers-s1-small',
                               'attribution': ['Size 1', 'small pack'],
                               'attribution_rivals': ['big pack', 'Size 2', 'Size 3']},
     [{'amount': '18', 'currency': None, 'attributed_product': 'Size 1 small pack'}], 'wrong'),
    ('Q3', ea.price('22.99'), SIZE_3_SMALL,
     [{'amount': '19.49', 'currency': None, 'attributed_product': None}], 'wrong'),
    ('Q4', ea.price('22.99'), SIZE_3_SMALL,
     [{'amount': '39.99', 'currency': None, 'attributed_product': 'Size 3 big pack (168 ct)'}],
     'absent'),
    ('Q5', ea.price('24.99', attributed_to='target.com'), ACME_REF,
     [{'amount': '21.49', 'currency': None, 'attributed_product': 'Acme Swaddle Size 3'}], 'wrong'),
]


def seed(db):
    with db.begin() as c:
        for i, (code, expectation, ref, prices, outcome) in enumerate(ROWS, start=1):
            c.execute(text("""INSERT INTO soa_queries (id, tier, expected_answer, source_ref,
                study_type, query_code) VALUES (:i, 'catalog_accuracy', :e, :r, 'ws', :c)"""),
                      {"i": i, "e": json.dumps(expectation), "r": json.dumps(ref), "c": code})
            c.execute(text("""INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number,
                raw_response, status, surface) VALUES (:i, 1, :i, 'chatgpt', 1, 'x', 'success',
                'grounded_api')"""), {"i": i})
            c.execute(text("""INSERT INTO soa_expectation_outcomes (run_id, query_id, cycle_id,
                platform, tier, expected_answer, extraction, outcome, extraction_model)
                VALUES (:i, :i, 1, 'chatgpt', 'catalog_accuracy', :e, :x, :o, 'gpt-x')"""),
                      {"i": i, "e": json.dumps(expectation), "x": json.dumps(extraction(prices)),
                       "o": outcome})


class SnapshotClient:
    """The W&S catalog fixture, for every merchant. No network."""

    def __init__(self):
        payloads = _json('wiggle_and_snug_catalog.json')
        self.snap = build_snapshot(payloads['catalog'], merchants=payloads['merchants'],
                                   incentives=payloads['incentives'],
                                   price_history=payloads['price_history'])

    def snapshot(self, slug, *, with_history=True):
        return self.snap


class NoFacts:
    def for_merchant(self, _slug, study_type=None):
        return {}


def make_scorer():
    history = scorer_module.HistoryCache(SnapshotClient())
    return scorer_module.ExpectationScorer(
        client=rc._NoModel(), history=history, brand_facts=NoFacts(), labeler=False,
        references=scorer_module.ReferenceCache(fetch=False), domain_checker=False,
    )


def rows(db):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(text(
            "SELECT run_id, outcome, outcome_reason, flags, claim_results, reason_code, "
            "extraction_model FROM soa_expectation_outcomes ORDER BY run_id")).mappings()]


def test_classify_only_moves_each_row_for_a_named_rule_and_calls_no_model(db):
    seed(db)
    result = rc.classify_only('WS-2B', scorer=make_scorer())
    assert result['deterministic'] is True
    moved = {code: (was, now, rule) for _rid, code, _p, _n, was, now, rule in result['moved']}
    assert moved['Q2'][:2] == ('wrong', 'partial') and 'rule 1' in moved['Q2'][2]
    assert moved['Q3'][:2] == ('wrong', 'unscoreable') and 'rule 3' in moved['Q3'][2]
    assert moved['Q4'][:2] == ('absent', 'partial') and 'rule 2' in moved['Q4'][2]
    assert moved['Q5'][:2] == ('wrong', 'exact') and '§2' in moved['Q5'][2]
    assert 'Q1' not in moved
    # The extraction model recorded on the row is the one that produced the
    # stored extraction, not a new one: nothing was re-extracted.
    assert {r['extraction_model'] for r in rows(db)} == {'gpt-x'}


def test_classify_only_produces_identical_output_twice(db):
    seed(db)
    rc.classify_only('WS-2B', scorer=make_scorer())
    first = rows(db)
    again = rc.classify_only('WS-2B', scorer=make_scorer())
    assert again['moved'] == []
    assert rows(db) == first


def test_dry_run_writes_nothing(db):
    seed(db)
    before = rows(db)
    result = rc.classify_only('WS-2B', scorer=make_scorer(), write=False)
    assert result['moved']
    assert rows(db) == before


def test_the_cli_flag_reaches_classify_only(db, monkeypatch, capsys):
    seed(db)
    monkeypatch.setattr(rc, 'classify_only', lambda code, tiers, write: {
        'cid': 1, 'rows': 0, 'moved': [], 'deterministic': True, 'skipped': []})
    assert rc.main(['--cycle', 'WS-2B', '--classify-only', '--dry-run']) == 0
    assert 'no model call' in capsys.readouterr().out


def _seed_unexplained_move(db, *, query_expectation):
    """Q1's answer is exact; its stored outcome says absent. No named rule
    explains absent -> exact, so the move is unattributed."""
    seed(db)
    with db.begin() as c:
        c.execute(text("UPDATE soa_expectation_outcomes SET outcome = 'absent' WHERE run_id = 1"))
        c.execute(text("UPDATE soa_queries SET expected_answer = :e WHERE id = 1"),
                  {"e": json.dumps(query_expectation)})


def test_an_unexplained_move_on_identical_inputs_says_so_and_blocks_the_write(db):
    _seed_unexplained_move(db, query_expectation=ea.price('22.99'))
    before = rows(db)
    result = rc.classify_only('WS-2B', scorer=make_scorer())
    assert [(m[1], m[4], m[5], m[6]) for m in result['unattributed']] == [
        ('Q1', 'absent', 'exact', 'unattributed: classifier output changed on identical inputs')]
    assert result['written'] is False
    assert rows(db) == before


def test_an_unexplained_move_names_the_input_that_differs(db):
    _seed_unexplained_move(db, query_expectation=ea.price('22.99', attributed_to='target.com'))
    result = rc.classify_only('WS-2B', scorer=make_scorer(), write=False)
    (rule,) = [m[6] for m in result['unattributed']]
    assert rule == 'unattributed: no named rule fired; inputs differ: expected_answer.attributed_to'


def _cli_with_fixture_scorer(monkeypatch):
    real = rc.classify_only
    monkeypatch.setattr(rc, 'classify_only', lambda code, tiers, write: real(
        code, tiers, scorer=make_scorer(), write=write))


def test_the_real_run_refuses_and_prints_the_unattributed_moves(db, monkeypatch, capsys):
    _seed_unexplained_move(db, query_expectation=ea.price('22.99'))
    _cli_with_fixture_scorer(monkeypatch)
    before = rows(db)
    assert rc.main(['--cycle', 'WS-2B', '--classify-only']) == 1
    out = capsys.readouterr().out
    assert 'REFUSED' in out and 'unattributed moves: 1' in out
    assert 'Q1 · chatgpt · run 1: absent -> exact' in out
    assert rows(db) == before


def test_the_dry_run_warns_a_real_run_would_refuse(db, monkeypatch, capsys):
    _seed_unexplained_move(db, query_expectation=ea.price('22.99'))
    _cli_with_fixture_scorer(monkeypatch)
    assert rc.main(['--cycle', 'WS-2B', '--classify-only', '--dry-run']) == 0
    assert 'a real run would REFUSE' in capsys.readouterr().out


def test_a_not_our_product_move_is_attributed_and_writes(db):
    """Rule 2 narrowed: wrong -> absent for a price about a retailer program
    is a named rule, so it does not block the write."""
    seed(db)
    with db.begin() as c:
        c.execute(text("UPDATE soa_expectation_outcomes SET extraction = :x WHERE run_id = 1"),
                  {"x": json.dumps(extraction([{'amount': '2', 'currency': None,
                                                 'attributed_product': 'eligible purchases made at Costco'}]))})
        c.execute(text("UPDATE soa_expectation_outcomes SET outcome = 'wrong' WHERE run_id = 1"))
    result = rc.classify_only('WS-2B', scorer=make_scorer())
    assert [(m[1], m[4], m[5]) for m in result['moved'] if m[1] == 'Q1'] == [('Q1', 'wrong', 'absent')]
    assert 'not our product' in [m[6] for m in result['moved'] if m[1] == 'Q1'][0]
    assert result['unattributed'] == [] and result['written'] is True
