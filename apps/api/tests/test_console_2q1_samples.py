"""
2Q-1 (A's samples): the week-over-week pair as the console reads it after 2Q-1.

2P-1's pair (console_fixture_2p1.py), with what FL15 showed on Oct 24:
  * cycle 1's reference refreshed after its score was stored (Swaddlers
    Size 4 to 22-37 lb): every delta takes cycle 1's current read (B2);
  * cycle 2's Size 4, 120 ct at Amazon quoted at the reference's own price
    for a 58 ct pack by four agents (B4);
  * cycle 2's Amazon multi-buy read beside "Out of stock" (B4).
SOA_2Q1_SAMPLE_DUMP=<dir> writes the console's samples, unedited.
"""
import json
import os

from tests import console_fixture_2p1 as f2p1
from tests import test_console_2m2_promo as t2m2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2m1_attribute import R
from tests.test_console_2p1_two_cycles import PREV, WS, _get, _pair
from tests.test_console_2q1_copy import _out_of_stock, _quoted_for_another_pack
from tests.test_console_2q1_one_prior import _refresh_truth
from tests.test_console_read_models import as_, http, upstream  # noqa: F401  (pytest fixtures)


def _dump(name, body):
    out = os.environ.get('SOA_2Q1_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


def test_the_samples(http, db, upstream):
    _pair(db, http, upstream)
    _refresh_truth(db, f2p1.ID_1, 'v2', R(22, 37))
    assert _quoted_for_another_pack(db, f2p1.ID_2, 'v2', 'amazon.com', '42.97') == 4
    deals_2 = f2p1.deals_2(t2m2.DEALS)
    upstream.routes.by_date[0] = ('2026-10-21', _out_of_stock(deals_2, deals_2['deals'][0]['text']))

    score = _get(http, 'score', merchant=WS)
    over = _get(http, 'overview', merchant=WS)
    vis = _get(http, 'visibility', merchant=WS)
    prove = _get(http, 'prove', merchant=WS)
    rev = _get(http, 'revenue', merchant=WS)
    for name, body in (('score-2q1.json', score), ('overview-2q1.json', over), ('visibility-2q1.json', vis),
                       ('prove-2q1.json', prove), ('revenue-2q1.json', rev),
                       ('true-value-2q1.json', _get(http, 'true-value', merchant=WS)),
                       ('visibility-2q1-c1.json', _get(http, 'visibility', cycle=PREV, merchant=WS))):
        _dump(name, body)
    as_('op')
    _dump('revenue-history-2q1.json', http.get('/api/console/revenue/history', params={'merchant': WS, 'org': 10}).json())
    _dump('runs-2q1.json', http.get('/api/console/runs', params={'org': 10, 'merchant': WS}).json())
    for code, name in ((f2p1.CYCLE_2, 'answers-summary-2q1.json'), (PREV, 'answers-summary-2q1-c1.json')):
        _dump(name, _get(http, 'answers/summary', cycle=code))

    tiles = {m['key']: m for m in score['metrics']}
    # B2: the tile and Impact agree, against cycle 1's current read
    since = {m['label']: m for m in rev['since_baseline']}
    assert (tiles['attribute']['value'], tiles['attribute']['delta']) == (62, -1)
    assert (since['Attribute accuracy']['then'], since['Attribute accuracy']['delta']) == ('63 of 79', '-1')
    # B4: the lead price signal names the pack
    block = over['by_surface']['all']
    signal = next(s for s in block['signals'] if s['rule'] == 'wrong_product')
    assert signal['detail'].startswith('Quoted $42.97 for a 58 ct pack against $42.97 for the 120 ct. ')
    product = next(p for p in block['products'] if p['name'] == 'Size 4, 120 ct')
    assert product['issue'].startswith('Quoted $42.97 for a 58 ct pack against $42.97 for the 120 ct in ')
    # B4: the multi-buy beside "Out of stock" is not live; its row says so
    gone = [r for r in prove['rows'] if r.get('not_live')]
    assert [(r['retailer'], r['agents'], r['change']) for r in gone] == \
        [('Amazon', 'Not counted: out of stock', 'out_of_stock')]
    assert over['promo_pass_through']['k'] == prove['promo_pass_through']['k']
    assert int(next(c for c in block['changes'] if c['label'] == 'Deals named, cheapest-place answers')['delta']) == \
        tiles['promo']['delta']
