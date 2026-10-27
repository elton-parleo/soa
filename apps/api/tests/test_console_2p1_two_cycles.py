"""
2P-1 (B3): week-over-week preflight on a synthetic second cycle, sqlite and
Postgres. See console_fixture_2p1.py for the pair.
"""
import json
import os

from tests import console_fixture_2p1 as f2p1
from tests import test_console_2m1_attribute as t2m1
from tests import test_console_2m2_promo as t2m2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2k4_comparable import _fl13_shape
from tests.test_console_2l2_retired import _retired
from tests.test_console_2l4_routing import _intents, _supply
from tests.test_console_read_models import TOKEN_A, _encode, as_, http, upstream  # noqa: F401  (pytest fixtures)

WS = 'wiggle-and-snug'


def _get(http, endpoint, cycle=f2p1.CYCLE_2, **params):
    as_('op')
    r = http.get(f'/api/console/{endpoint}', params={'cycle': cycle, 'org': 10, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _dump(name, body):
    """SOA_2P1_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2P1_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


class _ByReadDate(dict):
    """The fake supply's routes, with /deals answered by the read date asked for."""

    def __init__(self, routes, upstream, path, by_date):
        super().__init__(routes)
        self.upstream, self.path, self.by_date = upstream, path, by_date

    def get(self, key, default=None):
        if key[1] == self.path:
            as_of = str(((self.upstream.calls[-1].get('params') or {}).get('as_of')) or '')
            return 200, next((body for day, body in self.by_date if as_of.startswith(day)), self.by_date[0][1])
        return super().get(key, default)


def _pair(db, http, upstream, changes=True):
    _fl13_shape(db, http, upstream)
    _retired(db)
    _intents(db)
    t2m2._questions(db)
    t2m1._attribute_questions(db)
    t2m1._cache_truths(db)
    f2p1.priced(db, _encode)
    _supply(upstream)
    upstream.answer('GET', f'/api/truesync/merchants/{WS}/reference', body=t2m1.ATTRIBUTE_REFERENCE, token=TOKEN_A)
    upstream.answer('GET', f'/api/truesync/merchants/{WS}/deals', body=t2m2.DEALS, token=TOKEN_A)
    # cycle 1's score stored, as the console's first read stores it
    _get(http, 'score', cycle=f2p1.CYCLE_1, merchant=WS)
    f2p1.clone(db, _encode)
    if changes:
        f2p1.apply_changes(db, _encode)
        upstream.answer('GET', f'/api/truesync/merchants/{WS}/reference', token=TOKEN_A,
                        body=f2p1.reference_2(t2m1.ATTRIBUTE_REFERENCE))
        upstream.routes = _ByReadDate(upstream.routes, upstream, f'/api/truesync/merchants/{WS}/deals',
                                      [('2026-10-21', f2p1.deals_2(t2m2.DEALS)), ('', t2m2.DEALS)])


PREV = f2p1.CYCLE_1
#: 2T-7 (2): copy names the earlier cycle by its day (rm.cycle_label), the code stays its id
PREV_NAME = 'the Oct 14 cycle'
PREV_LABEL = {'day': 'Oct 14', 'name': PREV_NAME, 'since': 'Since Oct 14', 'vs': 'vs Oct 14'}


def _detail(a, n, b, m):
    return f'{a} of {n} this cycle against {b} of {m} in {PREV_NAME}.'


def test_the_score_and_the_tiles(http, db, upstream):
    _pair(db, http, upstream)
    score = _get(http, 'score', merchant=WS)
    _dump('score-2p1.json', score)
    prev = score['previous']
    assert (score['score'], prev['score'], prev['delta'], prev['comparable'], prev['reason']) == (65, 61, 4, True, None)
    assert [(p['code'], p['previous'], p['score'], p['delta']) for p in prev['pillar_deltas']] == [
        ('visibility', 18, 19, 1.0), ('accessibility', 5.0, 5.0, 0.0), ('true_value', 19.0, 20.9, 1.9)]
    moved = {d['code']: d['delta'] for d in prev['dimension_deltas'] if d['delta']}
    assert moved == {'recommendation_strength': 1, 'member_value': 1.9}
    tiles = {m['key']: (m['value'], m['denominator'], m['delta']) for m in score['metrics']}
    assert tiles == {'attribute': (62, 79, 1), 'coverage': (40, 49, 2), 'presence': (51, 102, 0),
                     'retired': (7, 102, -3), 'promo': (3, 100, -2)}
    assert all(m['delta_reason'] is None for m in score['metrics'])


def test_the_overview_s_changes(http, db, upstream):
    _pair(db, http, upstream)
    over = _get(http, 'overview', merchant=WS)
    _dump('overview-2p1.json', over)
    assert over['previous_cycle'] == PREV and over['changes_note'] is None
    block = over['by_surface']['all']
    assert (block['changes_status'], block['changes_note'], block['changes_condition']) == ('compared', None, None)
    got = [(c['label'], c['delta'], c['dir'], c['detail']) for c in block['changes']]
    assert got == [
        ('Named', '0', 'flat', _detail(51, 102, 51, 102)),
        ('First pick', '0', 'flat', _detail(33, 102, 33, 102)),
        # v0 at Amazon wrong -> exact, v1 at Walmart exact -> wrong, v2 at Walmart exact -> stale
        ('Prices right', '-1', 'down', _detail(86, 120, 87, 120)),
        ("Answered with another brand's price", '0', 'flat', _detail(36, 228, 36, 228)),
        ('Wrong prices', '0', 'flat', _detail(33, 120, 33, 120)),
        ('Newborn weight range right', '0', 'flat', _detail(4, 5, 4, 5)),
        ('Size 4 weight range right', '+1', 'up', _detail(9, 15, 8, 15)),
        ('Retired product named', '-3', 'down', _detail(7, 102, 10, 102)),
        ('First pick, category questions', '0', 'flat', _detail(33, 102, 33, 102)),
        ('Retailer coverage', '+2', 'up', _detail(40, 49, 38, 49)),
        ('Deals named, cheapest-place answers', '-2', 'down', _detail(3, 100, 5, 100)),
    ]
    assert not [c for c in block['changes'] if c['delta'] == 'new']
    assert all(a['delta_status'] == 'compared' for a in block['agents'])
    assert block['summary']['lines'][1] == "Prices right in 86 of 120 scored answers, 36 answered with another " \
        "brand's price, 18 not checked."


def test_visibility_moved(http, db, upstream):
    _pair(db, http, upstream)
    vis = _get(http, 'visibility', merchant=WS)
    _dump('visibility-2p1.json', vis)
    _dump('visibility-2p1-c1.json', _get(http, 'visibility', cycle=PREV, merchant=WS))
    assert vis['previous'] == {'cycle': PREV, 'status': 'compared', 'note': None, **PREV_LABEL}
    every = vis['moved']['all']
    assert [(b['name'], b['prev_first'], b['first'], b['delta']) for b in every['brands']] == [
        ('Pampers', 27, 30, '+3'), ('Huggies', 30, 28, '-2'), ('Wiggle & Snug', 33, 33, '0')]
    assert every['brands'][0]['detail'] == f'Pampers first in 30 of 102 brand-choice answers, 27 in {PREV_NAME}.'
    assert {k: every['coverage'][k] for k in ('prev', 'now', 'of_now', 'delta')} == \
        {'prev': 38, 'now': 40, 'of_now': 49, 'delta': '+2'}
    assert {k: every['retired'][k] for k in ('prev', 'now', 'delta')} == {'prev': 10, 'now': 7, 'delta': '-3'}
    # the first store named did not move: two answers gained Walmart second
    assert [(r['name'], r['delta']) for r in every['routing']] == \
        [('Walmart', '0'), ('Target', '0'), ('Amazon', '0'), ('Other stores', '0')]
    # per surface too: the moves were on the grounded API
    assert [(b['name'], b['delta']) for b in vis['moved']['grounded_api']['brands']][:2] == \
        [('Pampers', '+3'), ('Huggies', '-2')]


def test_true_value_drift_and_the_stale_cell(http, db, upstream):
    _pair(db, http, upstream)
    tv = _get(http, 'true-value', merchant=WS)
    _dump('true-value-2p1.json', tv)
    assert tv['previous'] == {'cycle': PREV, 'status': 'compared', 'note': None, **PREV_LABEL}
    assert [(d['product'], d['column'], d['was'], d['now'], d['dir']) for d in tv['drift']] == [
        ('Newborn, 84 ct', 'amazon.com', 'wrong', 'exact', 'better'),
        ('Size 1, 96 ct', 'walmart.com', 'exact', 'wrong', 'worse'),
        ('Size 4, 120 ct', 'walmart.com', 'exact', 'stale', 'worse')]
    assert tv['drift'][2]['detail'] == f'Size 4, 120 ct at Walmart: exact in {PREV_NAME}, stale this cycle.'
    cell = next(r for r in tv['rows'] if r['product'] == 'Size 4, 120 ct')['cells']['walmart.com']
    # Walmart's price moved $39.97 -> $37.97 and Perplexity quoted last week's
    assert (cell['live'], cell['quoted'], cell['status'], cell['outcome']) == ('$37.97', '$39.97', 'wrong', 'stale')


def test_trade_promotions_moved(http, db, upstream):
    _pair(db, http, upstream)
    prove = _get(http, 'prove', merchant=WS)
    _dump('prove-2p1.json', prove)
    # 2T-8 (B6): live in both cycles is `continuing`
    assert [(r['title'], r['change']) for r in prove['rows']] == [
        ('Amazon: save 40% on 1 when you buy 2', 'continuing'), ('Amazon: $3 off coupon on Swaddlers v9', 'new')]
    assert [(e['title'], e['change'], e['note']) for e in prove['ended']] == [
        ("Sam's Club: $15 Sam's Cash on $100 of P&G", 'not_read',
         f"Not read on Oct 21: Sam's Club walled every read. Live in {PREV_NAME}."),
        ('Walmart: Rollback, 17% off', 'ended',
         f'Ended since {PREV_NAME}. Walmart was read on Oct 21 and no longer ran it.')]
    assert prove['aside']['value'] == '3 of 100'
    assert prove['aside']['delta'] == {'delta': '-2', 'dir': 'down', 'prev': 5, 'of_prev': 100,
                                       'detail': _detail(3, 100, 5, 100), 'vs': PREV_LABEL['vs']}   # 2T-11 (B2)
    assert prove['walled'] == ["Sam's Club", 'Target']


def test_impact_since_the_baseline(http, db, upstream):
    _pair(db, http, upstream)
    rev = _get(http, 'revenue', merchant=WS)
    _dump('revenue-2p1.json', rev)
    assert (rev['baseline_cycle'], rev['baseline_started']) == (PREV, '2026-10-14')
    assert [(m['label'], m['then'], m['now'], m['delta']) for m in rev['since_baseline']] == [
        ('Attribute accuracy', '61 of 79', '62 of 79', '+1'), ('Retailer coverage', '38 of 49', '40 of 49', '+2'),
        ('Promo pass-through', '5 of 100', '3 of 100', '-2'), ('Category presence', '51 of 102', '51 of 102', '0')]
    # cycle 1 is its own baseline: the cycle before it ran another study
    first = _get(http, 'revenue', cycle=PREV, merchant=WS)
    assert (first['baseline_cycle'], first['since_baseline']) == (PREV, None)
    as_('op')
    history = http.get('/api/console/revenue/history', params={'merchant': WS, 'org': 10}).json()
    _dump('revenue-history-2p1.json', history)
    measured = [c for c in history['cycles'] if c['measured']]
    assert [c['cycle'] for c in measured][-2:] == [PREV, f2p1.CYCLE_2]
    assert history['cycles'][-1]['vs_previous'] == {'cycle': PREV, 'comparable': True, 'condition': None, 'reason': None}


def test_the_answers_and_the_cycle_switcher(http, db, upstream):
    _pair(db, http, upstream)
    as_('op')
    runs = http.get('/api/console/runs', params={'org': 10, 'merchant': WS}).json()
    _dump('runs-2p1.json', runs)
    codes = [r['id'] for r in runs]
    assert codes[:2] == [f2p1.CYCLE_2, PREV]
    for code, name in ((f2p1.CYCLE_2, 'answers-summary-2p1.json'), (PREV, 'answers-summary-2p1-c1.json')):
        _dump(name, _get(http, 'answers/summary', cycle=code))
    two, one = _get(http, 'answers'), _get(http, 'answers', cycle=PREV)
    assert len(two) == len(one) and not {a['id'] for a in two} & {a['id'] for a in one}
    # the cycle switcher's two cycles each read their own answers: the stale quote is cycle 2's
    stale = [a for a in two if (a.get('verdict') or a.get('outcome')) == 'stale' or 'stale' in json.dumps(a.get('checks'))]
    assert stale and not [a for a in one if 'stale' in json.dumps(a.get('checks'))]
