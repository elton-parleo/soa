"""
2C-3a: /api/console/score returned 500 on production cycle 229.

Every test here runs on the console test database twice: sqlite (as every
console test does) and, when SOA_TEST_PG_URL names a local Postgres, the same
schema with production's column types (soa's JSON columns are Postgres json).
The 500 reproduces only on the second: see test_the_229_cycle_scores. The
harness (packages/testing/soa_pg_harness.py) skips the Postgres run when the
variable is unset outside CI, and fails it for a host that is not local or a
database it cannot reach.

    SOA_TEST_PG_URL=postgresql://postgres@127.0.0.1:55432/postgres pytest tests/test_console_2c3a.py
"""
import json
import logging

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

import app.console_scope as console_scope_module
import app.routers.console as console_router
import app.routers.console_ops as console_ops_router
import app.routers.full_loop as full_loop_router
import soa_shared.config as config
import soa_shared.customers as customers
from app.services import console_score as score_svc
from soa_pg_harness import postgres_engine, sqlite_engine
from tests import console_fixture_229 as f229
from tests.test_console_read_models import (  # noqa: F401  (pytest fixtures)
    TOKEN_A, _encode, _fixture, as_, http, seed_console_db, upstream,
)
from tests.test_console_visibility_record import WS, ws_supply

@pytest.fixture(params=['sqlite', 'postgres'])
def db(request, monkeypatch):
    """The console test database on sqlite, or on a local Postgres with
    production's types (packages/testing/soa_pg_harness.py). Overrides
    test_console_read_models.db for this module."""
    monkeypatch.setattr(config, "SOA_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(config, "TRUESYNC_TENANT_TOKEN", "")
    monkeypatch.setattr(config, "TRUESYNC_API_BASE", "https://supply.example")
    if request.param == 'sqlite':
        engine = sqlite_engine()
        seed_console_db(engine)
    else:
        engine = postgres_engine()
        seed_console_db(engine, pk='SERIAL PRIMARY KEY', json='JSON')
    for module in (customers, console_scope_module, console_router, console_ops_router, full_loop_router):
        monkeypatch.setattr(module, "engine", engine)
    yield engine
    engine.dispose()


def _cycle_229(db, *, columns=True):
    f229.load(db, _encode)
    if columns:   # migration f3b8d2a6c4e1, applied in production: both NULL on the first read
        kind = 'JSON' if db.dialect.name == 'postgresql' else 'TEXT'
        with db.begin() as c:
            c.exec_driver_sql(f"ALTER TABLE soa_cycles ADD COLUMN share_of_algorithm {kind}")
            c.exec_driver_sql("ALTER TABLE soa_cycles ADD COLUMN share_of_algorithm_version TEXT")


def _supply(upstream):
    ws_supply(upstream)
    upstream.answer('GET', f'{WS}/access', body=_fixture('supply_access_ws.json'), token=TOKEN_A)


def _get(http, **params):
    as_('op')
    return http.get('/api/console/score', params={'cycle': f229.CYCLE_229, 'merchant': 'wiggle-and-snug', 'org': 10, **params})


def _stored(db, cycle_id=229):
    with db.connect() as c:
        return c.execute(text("SELECT share_of_algorithm, share_of_algorithm_version FROM soa_cycles WHERE id = :i"),
                         {'i': cycle_id}).one()


# ═══ the fixture is 229's shape ══════════════════════════════════════════

def test_the_fixture_is_shaped_like_cycle_229():
    d = f229.build()
    runs = [r for r in d['runs'] if r['cycle_id'] == 229]
    q = {x['id']: x for x in d['queries']}
    assert (len(d['queries']), len({r['query_id'] for r in runs}), len(runs)) == (87, 86, 516)
    assert sum(r['answer_status'] == 'answered' for r in runs) == 514
    assert {r['surface'] for r in runs if r['answer_status'] != 'answered'} == {'consumer_ui'}
    tiers = {}
    for r in runs:
        tiers[q[r['query_id']]['tier']] = tiers.get(q[r['query_id']]['tier'], 0) + 1
    assert tiers == {None: 300, 'brand_direct': 66, 'catalog_accuracy': 114, 'value_incentives': 36}
    unprompted = {r['id'] for r in runs if q[r['query_id']]['tier'] is None}
    m = [x for x in d['coded_mentions'] if x['run_id'] in unprompted]
    named = lambda e: len({x['run_id'] for x in m if x['entity_id'] == e})
    first = lambda e: len({x['run_id'] for x in m if x['entity_id'] == e and x['position'] == 1})
    assert [(named(e), first(e)) for e in (f229.WS, f229.PAMPERS, f229.HUGGIES, f229.PULLUPS)] == [(0, 0), (80, 38), (71, 24), (3, 3)]
    assert len({x['run_id'] for x in m} - {x['run_id'] for x in m if x['position'] == 1}) == 26
    o = [x for x in d['outcomes'] if x['cycle_id'] == 229]
    cat = [x for x in o if x['tier'] == 'catalog_accuracy']
    assert sum(x['outcome'] == 'exact' for x in cat) == 9
    assert sum(x['outcome'] in ('exact', 'wrong', 'partial', 'stale') for x in cat) == 41
    assert sum(x['reason_code'] == 'other_brand' for x in cat) == 34


# ═══ the 500, and the fix ════════════════════════════════════════════════

def test_the_229_cycle_scores(http, upstream, db):
    """On main this is a 500 on Postgres only: load_score_runs ran SELECT
    DISTINCT q.query_code, q.expected_answer, and expected_answer is a
    Postgres json column, which has no equality operator (psycopg2
    UndefinedFunction: could not identify an equality operator for type json).
    sqlite stores it as TEXT, so the W&S fixture never saw it."""
    _cycle_229(db)
    _supply(upstream)
    r = _get(http)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['score'] is not None and body['scorer_version'] == score_svc.SCORER_VERSION


# ═══ the five rules ══════════════════════════════════════════════════════

def test_a_surface_with_no_answers_is_left_out_of_the_pool_and_said_so(http, upstream, db):
    _cycle_229(db)
    _supply(upstream)
    body = _get(http).json()
    assert [s['surface'] for s in body['surfaces']] == ['grounded_api']
    assert body['coverage']['ran_no_answers'] == ['consumer_ui']
    assert body['coverage']['line'] == ('1 surface, 86 questions, 2 agents · pooled across surfaces, equal weight'
                                        ' · the consumer UI ran, no answers')
    assert body['score'] == round(body['surfaces'][0]['score'])


def test_a_brand_named_zero_times_scores_visibility_as_a_measured_zero(http, upstream, db):
    """Ours is named in 0 of 300 unprompted answers: no mention to code. The
    Audit's functions score that 0 (absence is the visibility failure), so
    both dimensions are measured, 0 of 22 and 0 of 10."""
    _cycle_229(db)
    _supply(upstream)
    body = _get(http).json()
    vis = next(p for p in body['pillars'] if p['code'] == 'visibility')
    assert (vis['score'], vis['applicable_max']) == (0.0, 32.0)
    dims = {d['code']: d for d in vis['dimensions']}
    assert (dims['share_of_mentions']['state'], dims['share_of_mentions']['score']) == ('measured', 0.0)
    assert (dims['recommendation_strength']['state'], dims['recommendation_strength']['score']) == ('measured', 0.0)
    som = dims['share_of_mentions']['parts'][0]
    assert (som['numerator'], som['denominator']) == (0, 154)       # 80 + 71 + 3 tracked-brand mentions


def test_the_first_read_computes_and_stores_and_the_second_serves_the_row(http, upstream, db, monkeypatch):
    _cycle_229(db)
    _supply(upstream)
    assert tuple(_stored(db)) == (None, None)
    computed = []
    real = score_svc.build_score
    monkeypatch.setattr(score_svc, 'build_score', lambda *a, **k: computed.append(1) or real(*a, **k))
    first = _get(http)
    assert first.status_code == 200 and first.json()['stored'] is True and len(computed) == 1
    raw, version = _stored(db)
    assert version == score_svc.SCORER_VERSION
    assert (raw if isinstance(raw, dict) else json.loads(raw))['score'] == first.json()['score']
    second = _get(http)
    assert second.status_code == 200 and len(computed) == 1             # served from the row
    assert second.json()['score'] == first.json()['score']


@pytest.mark.parametrize('stored', [None, {'scorer_version': '5', 'adapter_revision': 1, 'score': 41, 'surfaces': []}])
def test_the_previous_cycle_is_not_comparable(http, upstream, db, stored):
    _cycle_229(db)
    if stored is not None:
        with db.begin() as c:
            c.execute(text("UPDATE soa_cycles SET share_of_algorithm = :b, share_of_algorithm_version = '5' WHERE id = 178"),
                      {'b': json.dumps(stored)})
    _supply(upstream)
    prev = _get(http).json()['previous']
    assert prev['cycle'] == f229.PREVIOUS and prev['comparable'] is False
    assert prev['reason'] == ('Scored under v5, re-score to compare.' if stored else
                              f'Not comparable: {f229.PREVIOUS} has no stored score yet. Open it to score it.')


def test_an_exception_in_the_score_is_a_422_with_a_short_reason_and_a_log_line(http, upstream, db, monkeypatch, caplog):
    _cycle_229(db)
    _supply(upstream)

    def boom(*a, **k):
        score_svc.at('share_of_mentions on grounded_api')
        raise ZeroDivisionError('division by zero')
    monkeypatch.setattr(score_svc, 'score_surface', boom)
    with caplog.at_level(logging.INFO, logger='app.services.console_score'):
        r = _get(http)
    assert r.status_code == 422
    assert r.json()['detail'] == 'Score unavailable: share_of_mentions on grounded_api failed (ZeroDivisionError)'
    failed = [json.loads(rec.getMessage()) for rec in caplog.records if '"event": "score.failed"' in rec.getMessage()]
    assert failed == [{'event': 'score.failed', 'cycle': f229.CYCLE_229, 'cycle_id': 229, 'org': 10,
                       'step': 'share_of_mentions on grounded_api', 'error': 'ZeroDivisionError',
                       'message': 'division by zero'}]
    assert tuple(_stored(db)) == (None, None)                           # nothing stored


def test_the_computation_logs_its_start_and_end(http, upstream, db, caplog):
    _cycle_229(db)
    _supply(upstream)
    with caplog.at_level(logging.INFO, logger='app.services.console_score'):
        assert _get(http).status_code == 200
    events = [json.loads(rec.getMessage()) for rec in caplog.records if rec.getMessage().startswith('{"event": "score.')]
    assert [e['event'] for e in events] == ['score.start', 'score.end']
    end = events[1]
    assert (end['cycle'], end['org'], end['surfaces']) == (f229.CYCLE_229, 10, ['grounded_api'])
    assert isinstance(end['ms'], int) and end['stored'] is True


def test_the_w_s_fixture_cycle_scores_on_postgres_too(http, upstream, db):
    """The cause was the column type, not 229's shape: Postgres refuses
    DISTINCT over json even on an empty table, so on main every cycle,
    the W&S fixture's included, was a 500 in production."""
    _supply(upstream)
    as_('op')
    r = http.get('/api/console/score', params={'cycle': 'WS-2B-FIXTURE', 'merchant': 'wiggle-and-snug', 'org': 10})
    assert r.status_code == 200 and r.json()['score'] == 60
