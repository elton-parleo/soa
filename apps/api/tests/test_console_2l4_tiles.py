"""
2L-4 (B3): the brand Overview's five tiles, sqlite and Postgres.

A brand merchant's five metric tiles are the demo's charter set, in its order:
Attribute accuracy (not measured), Retailer coverage, Category presence,
Retired product named, Promo pass-through (not measured). A retailer merchant
keeps the five it had. Both sets are counted in metric_counts and served in
metrics_by_kind; `metrics` is the merchant's. Counts, not the score: the
scorer version is unchanged and the pins (test_console_2k1_score_pin.py) hold
with the brand tiles set aside (tests/score_2l4.py).

On the FL13 shape with 2L-2's retired Pure and 2L-4's 20 intent questions
(test_console_2l4_routing.py): coverage 38 of 49, presence the Share of
answers row, retired 10 of 102 with AMORE in 3.
"""
import json
import os

from app.services import console_score as score_svc
from tests import console_fixture_229 as f229
from tests.score_2l4 import retailer_rows
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2k4_comparable import DIFFERENT, _fl13_shape
from tests.test_console_2l2_retired import _retired
from tests.test_console_2l4_routing import _intents, _supply
from tests.test_console_read_models import WS_TENANT, as_, http, upstream  # noqa: F401  (pytest fixtures)

WS = 'wiggle-and-snug'
BRAND_KEYS = ['attribute', 'coverage', 'presence', 'retired', 'promo']


def _read(http, endpoint, **params):
    as_('op')
    r = http.get(f'/api/console/{endpoint}', params={'cycle': f229.CYCLE_229, 'org': 10, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _dump(name, body):
    """SOA_2L4_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2L4_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


def _pampers_shape(db, http, upstream):
    _fl13_shape(db, http, upstream)
    _retired(db)
    _intents(db)
    _supply(upstream)


def test_the_brand_tiles_on_the_fl13_shape(http, db, upstream):
    _pampers_shape(db, http, upstream)
    score = _read(http, 'score', merchant=WS, rescore=1)
    _dump('score-2l4.json', score)
    _dump('overview-2l4.json', _read(http, 'overview', merchant=WS))
    _dump('visibility-2l4.json', _read(http, 'visibility', merchant=WS))
    assert score['metric_kind'] == 'brand'
    assert score['scorer_version'] == score_svc.SCORER_VERSION
    rows = {m['key']: m for m in score['metrics']}
    assert [m['key'] for m in score['metrics']] == BRAND_KEYS
    assert [m['name'] for m in score['metrics']] == ['Attribute accuracy', 'Retailer coverage', 'Category presence',
                                                     'Retired product named', 'Promo pass-through']
    for key in ('attribute', 'promo'):
        assert (rows[key]['state'], rows[key]['value'], rows[key]['denominator'], rows[key]['delta']) == \
            ('not_measured', None, None, None)
    assert rows['attribute']['reason'] == score_svc.BRAND_TILE_TEMPLATES['attribute.not_measured']
    assert rows['promo']['reason'] == 'Not measured: retailer-page deals are not read yet.'
    cov = rows['coverage']
    assert (cov['state'], cov['value'], cov['denominator']) == ('measured', 38, 49)
    assert cov['sub'] == '38 of 49 where-to-buy answers name 2 or more of Walmart, Target, Amazon'
    assert sum(v['value'] for v in cov['by_surface'].values()) == 38
    # Category presence is the Share of answers row, under the demo's name
    share = {m['key']: m for m in retailer_rows(score)}['share']
    presence = rows['presence']
    assert (presence['value'], presence['denominator']) == (share['value'], share['denominator'])
    assert presence['surface_note'] == share['surface_note']
    assert presence['sub'].startswith('Category answers naming Wiggle & Snug. First in ')
    retired = rows['retired']
    assert (retired['value'], retired['denominator']) == (10, 102)
    assert retired['sub'] == 'Category answers naming Pure, which pampers.com retired. AMORE, its successor: 3'
    # both sets are served
    assert [m['key'] for m in score['metrics_by_kind']['retailer']] == ['first', 'share', 'program', 'exact', 'terms']


def test_comparability_is_2k4_s(http, db, upstream):
    """FL13 against FL12, another study: no delta on any tile, the one reason."""
    _pampers_shape(db, http, upstream)
    score = _read(http, 'score', merchant=WS)
    assert score['previous']['comparable'] is False
    for m in score['metrics']:
        assert m['delta'] is None
        assert m['delta_reason'] == (DIFFERENT if m['state'] == 'measured' else None)


def test_a_retailer_merchant_keeps_its_five(http, db, upstream):
    _fl13_shape(db, http, upstream)
    _intents(db)
    _supply(upstream, tenant={**WS_TENANT, 'merchants': [{**WS_TENANT['merchants'][0], 'kind': 'seller'}]})
    score = _read(http, 'score', merchant=WS, rescore=1)
    assert score['metric_kind'] == 'retailer'
    assert [m['key'] for m in score['metrics']] == ['first', 'share', 'program', 'exact', 'terms']
    assert score['metrics'] == score['metrics_by_kind']['retailer']
    # its brand set is counted but has no routing to read: coverage is not measured
    brand = {m['key']: m for m in score['metrics_by_kind']['brand']}
    assert brand['coverage']['state'] == 'not_measured'


def test_a_brand_with_no_where_to_buy_question_or_retired_line(http, db, upstream):
    """FL13 before its regeneration: presence measured, the rest not, each saying why."""
    _fl13_shape(db, http, upstream)
    _supply(upstream)
    rows = {m['key']: m for m in _read(http, 'score', merchant=WS, rescore=1)['metrics']}
    assert [k for k, m in rows.items() if m['state'] == 'measured'] == ['presence']
    assert rows['coverage']['reason'] == score_svc.BRAND_TILE_TEMPLATES['coverage.not_measured']
    assert rows['retired']['reason'] == "Not measured: the brand's record has no retired line."


def test_a_score_stored_before_the_brand_tiles_is_recomputed():
    body = {'scorer_version': score_svc.SCORER_VERSION, 'adapter_revision': score_svc.ADAPTER_REVISION,
            'measured': [], 'metric_surface': 'all', 'metric_counts': {'all': {'first': {'value': 1, 'of': 2}}}}
    assert score_svc.needs_recompute(body, None) == 'brand tiles not counted'
    body['metric_counts']['all']['presence'] = {'value': 1, 'of': 2}
    assert score_svc.needs_recompute(body, None) != 'brand tiles not counted'


def test_a_comparable_previous_score_without_the_tile_says_so():
    counts = {'all': {'tier': 'unprompted', 'attribute': None, 'promo': None, 'retired': None,
                      'coverage': {'value': 3, 'of': 4, 'names': ['Walmart']},
                      'presence': {'value': 5, 'of': 9, 'first': 2, 'brand': 'Pampers', 'rival': None}}}
    previous = {'comparable': True, 'cycle': 'FL12', 'metric_counts': {'all': {'presence': {'value': 4, 'of': 9}}}}
    rows = {m['key']: m for m in score_svc.build_brand_metrics(counts, 'all', previous)}
    assert (rows['presence']['delta'], rows['presence']['delta_reason']) == (1, None)
    assert rows['coverage']['delta'] is None
    assert rows['coverage']['delta_reason'] == 'Not comparable: FL12 was scored before this tile was counted'
    assert rows['coverage']['sub'] == '3 of 4 where-to-buy answers name 2 or more of Walmart'
