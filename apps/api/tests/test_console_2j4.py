"""
2J-4: the console after `rescore_cycle --refresh-reference`, on the
FL12-shaped brand fixture (console_fixture_2j2), sqlite and Postgres.

The refresh replaces soa_cycles.reference_prices with supply's corrected
read, stamped `refreshed_at` (apps/pipeline/scripts/rescore_cycle.py). The
recorded payloads are packages/testing/fixtures/retailer_prices_fl12_2j4.json:
Swaddlers NB 84 at Amazon $0.00 -> $27.97, Target $10.00 -> unverifiable,
pampers.com 9.97 -> none_by_design.

1. /true-value reads the new cells: Amazon $27.97, Target unverifiable, the
   brand's own page `not priced` (it was read and sets no price; it was not
   unreadable).
2. The stored score recomputes on the next read. Before 2J-4 nothing did:
   its triggers (scorer version, measured set, domain-check revision) do not
   see the cached reference or the outcomes a refresh re-classifies. The
   score records the `refreshed_at` it was computed on
   (inputs.cycle_reference_refreshed_at); a different one on the cycle row
   recomputes it, once, keeping the old value in its history.
"""
import json
import os

import soa_pg_harness
from sqlalchemy import text

from app.services import console_score as score_svc
from tests import console_fixture_2j2 as f2j2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import TOKEN_A, WS_TENANT, _encode, _fixture, as_, http, upstream  # noqa: F401

with open(os.path.join(os.path.dirname(soa_pg_harness.__file__), 'fixtures', 'retailer_prices_fl12_2j4.json')) as _fh:
    PAYLOADS = json.load(_fh)
STAMP = '2026-10-21T09:00:00+00:00'
NB84 = 'Swaddlers NB 84'


def _payload(cells: list, **envelope) -> dict:
    """The fixture cycle's cached read with NB 84's rows replaced by `cells`."""
    base = f2j2.reference_prices()
    rest = [r for r in base['prices'] if r['variant_label'] != NB84]
    return {**base, 'as_of': PAYLOADS['before']['as_of'], 'prices': cells + rest, **envelope}


def _store(db, payload: dict) -> None:
    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET reference_prices = :p WHERE cycle_code = :c"),
                  {'p': json.dumps(payload), 'c': f2j2.CYCLE})


def _cycle(db, payload):
    f2j2.load(db, _encode)
    kind = 'JSON' if db.dialect.name == 'postgresql' else 'TEXT'
    with db.begin() as c:
        c.exec_driver_sql(f"ALTER TABLE soa_cycles ADD COLUMN share_of_algorithm {kind}")
        c.exec_driver_sql("ALTER TABLE soa_cycles ADD COLUMN share_of_algorithm_version TEXT")
    _store(db, payload)


def _get(http, endpoint, **params):
    as_('op')
    r = http.get(f'/api/console/{endpoint}', params={'org': 10, 'cycle': f2j2.CYCLE, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _nb84(tv):
    row = next(r for r in tv['rows'] if r['product'] == NB84)
    return {d: (c['live'], c.get('method')) for d, c in row['cells'].items()}


BEFORE = _payload(PAYLOADS['before']['prices'])
AFTER = _payload(PAYLOADS['after']['prices'], refreshed_at=STAMP, previous_sha256='0' * 64)


def test_true_value_reads_the_refreshed_cells(http, db):
    _cycle(db, BEFORE)
    assert _nb84(_get(http, 'true-value')) == {
        'pampers.com': ('$9.97', 'regex'), 'amazon.com': ('$0.00', 'regex'), 'target.com': ('$10.00', 'regex'),
        'walmart.com': ('—', None)}
    _store(db, AFTER)
    assert _nb84(_get(http, 'true-value')) == {
        'pampers.com': ('not priced', 'none_by_design'), 'amazon.com': ('$27.97', 'regex'),
        'target.com': ('unverifiable', 'regex_rendered'), 'walmart.com': ('—', None)}


def test_the_products_block_says_the_brand_site_sets_no_price():
    from app.services import console_parity as parity
    cell = {'live': 'not priced', 'reference_source': 'honest_fetch', 'observed_at': '2026-10-19T14:01:58+00:00'}
    assert parity._live_text(cell, 'pampers.com') == "No price set at pampers.com, the brand's own site, Oct 19"


def _supply(upstream):
    base = f'/api/truesync/merchants/{f2j2.MERCHANT}'
    upstream.answer('GET', f'{base}/access', body=_fixture('supply_access_ws.json'), token=TOKEN_A)
    upstream.answer('GET', f'{base}/reference', body={'rows': [], 'reference_run': None}, token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/tenant',
                    body={**WS_TENANT, 'merchants': WS_TENANT['merchants'] + [f2j2.TENANT_MERCHANT]}, token=TOKEN_A)


def test_the_stored_score_recomputes_once_after_a_refresh_and_once_after_a_restore(http, db, upstream):
    _cycle(db, BEFORE)
    _supply(upstream)
    first = _get(http, 'score', merchant=f2j2.MERCHANT)
    # a copy never refreshed: the score's inputs carry nothing for it
    assert first['stored'] is True and 'cycle_reference_refreshed_at' not in first['inputs']
    scored_at = first['inputs']['scored_at']
    assert _get(http, 'score', merchant=f2j2.MERCHANT)['inputs']['scored_at'] == scored_at   # served as stored

    _store(db, AFTER)
    refreshed = _get(http, 'score', merchant=f2j2.MERCHANT)
    assert refreshed['inputs']['cycle_reference_refreshed_at'] == STAMP
    assert refreshed['history'][-1]['replaced_because'] == 'cycle reference refreshed'
    assert refreshed['history'][-1]['scored_at'] == scored_at
    again = _get(http, 'score', merchant=f2j2.MERCHANT)
    assert again['inputs']['scored_at'] == refreshed['inputs']['scored_at'] and len(again['history']) == 1

    _store(db, BEFORE)          # --restore: the copy before the refresh, with no stamp
    restored = _get(http, 'score', merchant=f2j2.MERCHANT)
    assert restored['history'][-1]['replaced_because'] == 'cycle reference restored'
    assert 'cycle_reference_refreshed_at' not in restored['inputs']


def test_the_trigger_reads_only_the_stamp():
    stored = {'scorer_version': score_svc.SCORER_VERSION, 'adapter_revision': score_svc.ADAPTER_REVISION,
              'measured': [], 'inputs': {}}
    # a score stored before 2J-4, on a copy never refreshed: served
    assert score_svc.needs_recompute(stored, None, BEFORE) is None
    assert score_svc.needs_recompute(stored, None, None) is None
    assert score_svc.needs_recompute(stored, None, AFTER) == 'cycle reference refreshed'
    on_it = {**stored, 'inputs': {'cycle_reference_refreshed_at': STAMP}}
    assert score_svc.needs_recompute(on_it, None, AFTER) is None
    assert score_svc.needs_recompute(on_it, None, {**AFTER, 'refreshed_at': '2026-10-22T09:00:00+00:00'}) == \
        'cycle reference refreshed'
    assert score_svc.needs_recompute(on_it, None, BEFORE) == 'cycle reference restored'
