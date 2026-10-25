"""
2Q-1 (B3): /overview's two-cycle read, cached per cycle and per supply read.

`/overview?cycle=FL15…` took 15.7 s on a warm API. On 2P-1's pair one read
made eleven supply calls in six rounds (the merchant's kind four times,
/reference and /deals twice) and read the previous cycle in full every time.
Now (console_cache): supply's reads run in one round and are kept a few
minutes per org (a failed one never); each cycle's rows, Visibility, promo
answers and attribute answers are kept under the cycle's stamp, so a rescore
or a reference refresh is a new key. Held here, with the cache on:

  * every read model body is the same, cached or not, cold or warm;
  * a warm overview makes one supply call (the merchant check) and reads
    neither cycle's rows again;
  * a refresh of the previous cycle's reference is seen on the next read;
  * a failed supply read is named, never kept: the next read tries again.
"""
import json

import pytest
from sqlalchemy import event

from app.services import console_cache
from tests import console_fixture_2p1 as f2p1
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2m1_attribute import R
from tests.test_console_2m2_promo import DEALS
from tests.test_console_2p1_two_cycles import WS, _get, _pair
from tests.test_console_2q1_one_prior import _refresh_truth
from tests.test_console_read_models import TOKEN_A, http, upstream  # noqa: F401  (pytest fixtures)

ENDPOINTS = ('overview', 'visibility', 'true-value', 'prove', 'revenue')


@pytest.fixture
def cache_on(monkeypatch):
    monkeypatch.setenv('SOA_CONSOLE_CACHE', '1')
    console_cache.clear()


def _bodies(http):
    return {e: json.dumps(_get(http, e, merchant=WS), sort_keys=True) for e in ENDPOINTS}


def test_every_body_is_the_same_cached_or_not(http, db, upstream, monkeypatch):
    _pair(db, http, upstream)
    monkeypatch.setenv('SOA_CONSOLE_CACHE', '0')
    plain = _bodies(http)
    monkeypatch.setenv('SOA_CONSOLE_CACHE', '1')
    console_cache.clear()
    cold, warm = _bodies(http), _bodies(http)
    for e in ENDPOINTS:
        assert cold[e] == plain[e], e
        assert warm[e] == plain[e], e
    assert console_cache.describe()['hit'] > 0


def test_a_warm_overview_reads_supply_once_and_no_cycle_again(http, db, upstream, cache_on):
    _pair(db, http, upstream)
    statements = []
    event.listen(db, 'before_cursor_execute', lambda *a, **k: statements.append(a[2]))

    def read():
        calls, statements[:] = len(upstream.calls), []
        _get(http, 'overview', merchant=WS)
        return [c['path'].rsplit('/', 1)[-1] for c in upstream.calls[calls:]], list(statements)

    console_cache.clear()   # _pair's score read warmed the routing reads
    cold_calls, cold_sql = read()
    assert sorted(cold_calls) == ['access', 'catalog', 'deals', 'deals', 'reference', 'retailers', 'tenant', 'tenant']
    warm_calls, warm_sql = read()
    # the merchant check reads the org's merchants every time (2H); nothing else is read again
    assert warm_calls == ['tenant']
    rows_sql = [s for s in warm_sql if 'FROM soa_runs r' in s and 'JOIN soa_queries q' in s and 'raw_response' in s]
    assert rows_sql == [] and len(warm_sql) < len(cold_sql)


def test_a_refresh_of_the_previous_cycle_is_seen_on_the_next_read(http, db, upstream, cache_on):
    _pair(db, http, upstream)
    changes = lambda: {c['label']: c['delta'] for c in _get(http, 'overview', merchant=WS)['by_surface']['all']['changes']}  # noqa: E731
    assert changes()['Size 4 weight range right'] == '+1'
    _refresh_truth(db, f2p1.ID_1, 'v2', R(22, 37))
    assert changes()['Size 4 weight range right'] == '-1'


def test_a_failed_supply_read_is_named_and_never_kept(http, db, upstream, cache_on):
    _pair(db, http, upstream)
    upstream.routes.path = None   # _pair answers /deals by read date; here it fails, then answers
    upstream.answer('GET', f'/api/truesync/merchants/{WS}/deals', status=502, body={'detail': 'boom'}, token=TOKEN_A)
    console_cache.clear()
    failed = _get(http, 'overview', merchant=WS)
    assert failed['read_errors'].get('deals') and 'promo_pass_through' not in failed
    upstream.answer('GET', f'/api/truesync/merchants/{WS}/deals', body=DEALS, token=TOKEN_A)
    before = len(upstream.calls)
    again = _get(http, 'overview', merchant=WS)
    assert 'deals' not in again['read_errors'] and again['promo_pass_through']
    assert [c for c in upstream.calls[before:] if c['path'].endswith('/deals')]


def test_the_stamp_moves_with_a_rescore(http, db, upstream, cache_on):
    from sqlalchemy import text
    _pair(db, http, upstream)
    with db.connect() as conn:
        cycle = dict(conn.execute(text("SELECT * FROM soa_cycles WHERE id = :i"), {'i': f2p1.ID_1}).mappings().one())
        before = console_cache.cycle_stamp(conn, cycle)
    with db.begin() as conn:
        # rescore_cycle replaces each row (delete, insert): a new id
        row = dict(conn.execute(text("SELECT * FROM soa_expectation_outcomes WHERE cycle_id = :c ORDER BY id LIMIT 1"),
                                {'c': f2p1.ID_1}).mappings().one())
        conn.execute(text("DELETE FROM soa_expectation_outcomes WHERE id = :i"), {'i': row['id']})
        new_id = conn.execute(text("SELECT MAX(id) FROM soa_expectation_outcomes")).scalar() + 1
        cols = [k for k in row if k != 'id']
        conn.execute(text(f"INSERT INTO soa_expectation_outcomes (id, {', '.join(cols)}) "
                          f"VALUES (:id, {', '.join(':' + k for k in cols)})"),
                     {**{k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in row.items()}, 'id': new_id})
    with db.connect() as conn:
        assert console_cache.cycle_stamp(conn, cycle) != before
