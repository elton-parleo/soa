"""
2T-8 (B6, B7): Trade promotions and Impact, from the Oct 26 Prove walk (org
12, FL15). Each test quotes what the live console showed.

On the 2T-1 harness (2P-1's pair with supply #33's answers RECORDED), and
FL14/FL15-shaped deals built here in supply's /deals shape, each saying so.
No model call, no production read.
"""
import copy
import json
import os

from app.services import console_read_models as rm
from app.services import console_revenue as revenue_svc
from soa_shared import promo_pass_through as ppt
from tests import console_fixture_2p1 as f2p1
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_console_2t1_overview_truesync import _read, _shape


def _dump(name, body):
    out = os.environ.get('SOA_2T8_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


def _amore(text, read_at):
    """FL14/FL15-shaped: Amazon's 25% list price cut on AMORE Size 1, as supply's /deals serves it. The shelf text
    and the read differ between the two reads; the deal does not."""
    return {'retailer_domain': 'amazon.com', 'kind': 'rollback_or_was', 'text': text, 'value': '25',
            'value_unit': 'percent', 'observed_at': read_at,
            'variants': [{'sku': 'sku_pg_amore_s1_132', 'variant_ref': 'feed_sku:7', 'variant_label': 'Size 1, 132 ct',
                          'product_name': 'Pampers AMORE', 'price': '36.18', 'was_price': '47.99',
                          'evidence': text}]}


# ── B6: a continuing deal is neither new nor ended ────────────────────────

def test_the_same_deal_in_both_cycles_is_continuing():
    """Live: "Amazon: 25% off list price on AMORE Size 1, $36.18 from $47.99 · New" and, under "No longer live
    since FL14", the identical deal. The two reads' shelf text differs, so its id (deal_id) did."""
    fl14 = {'deals': [_amore('$36.18 with 25 percent savings -25% List Price: $47.99', '2026-10-23T14:00:00')],
            'walled': [], 'read_date': '2026-10-23'}
    fl15 = {'deals': [_amore('Current price $36.18, List: $47.99 (25% off) 27.4 ¢/count', '2026-10-24T14:00:00')],
            'walled': [], 'read_date': '2026-10-24'}
    assert ppt.deal_id(fl14['deals'][0]) != ppt.deal_id(fl15['deals'][0])   # what the walk's keying saw
    body = rm.build_prove(None, fl15, 'Pampers', '2026-10-24')
    rm.prove_changes(body, fl15, fl14, None, None, 'the Oct 23 cycle')
    assert [(r['title'], r['change']) for r in body['rows']] == [
        ('Amazon: 25% off list price on AMORE Size 1, $36.18 from $47.99', 'continuing')]
    assert body['ended'] == []
    # a deal only in the newer read is new, only in the older one ended
    other = copy.deepcopy(fl14)
    other['deals'][0]['value'] = '20'
    other['deals'][0]['variants'][0]['was_price'] = '45.23'
    body = rm.build_prove(None, fl15, 'Pampers', '2026-10-24')
    rm.prove_changes(body, fl15, other, None, None, 'the Oct 23 cycle')
    assert [r['change'] for r in body['rows']] == ['new'] and [e['change'] for e in body['ended']] == ['ended']


def test_the_detail_is_a_sentence_and_the_shelf_text_rides_beside():
    """Live: "The shelf said: Current price is USD Now $49.77 You save $10.00 was $59.77 $59.77 33.2 ¢/count." The
    demo: who named it, and who quoted the cut without the word Rollback. FL15-shaped Walmart Rollback on Swaddlers
    Size 4, two answers judged by the study rule (one naming it, one quoting $49.77 without the word)."""
    said = 'Current price is USD Now $49.77 You save $10.00 was $59.77 $59.77 33.2 ¢/count'
    deal = {'retailer_domain': 'walmart.com', 'kind': 'rollback_or_was', 'text': said,
            'variants': [{'sku': 's4', 'variant_ref': 'feed_sku:5', 'variant_label': 'Size 4, 150 ct',
                          'product_name': 'Pampers Swaddlers', 'price': '49.77', 'was_price': '59.77', 'evidence': said}]}
    deals = {'deals': [deal], 'walled': [], 'read_date': '2026-10-24'}
    answers = [
        {'run_id': 1, 'surface': 'grounded_api', 'intent': 'cheapest_place', 'source_ref': {'sku': 's4'},
         'text': 'Walmart has a Rollback on Swaddlers Size 4 at $49.77.'},
        {'run_id': 2, 'surface': 'consumer_ui', 'intent': 'cheapest_place', 'source_ref': {'sku': 's4'},
         'text': 'Walmart sells the 150 count for $49.77, cheaper than Target.'},
    ]
    promo = ppt.count(answers, deals)
    assert [(j['named'] != [], j['quoted'] != []) for j in promo['judged']] == [(True, False), (False, True)]
    body = rm.build_prove(promo, deals, 'Pampers', '2026-10-24', agent_of_run={1: 'Perplexity', 2: 'Google AI Mode'})
    row = body['rows'][0]
    assert 'The shelf said' not in row['detail'] and '¢' not in row['detail']
    assert row['detail'].endswith('Perplexity named it. Google AI Mode quoted the Swaddlers cut without the word '
                                  'Rollback, which the study rule does not count.')
    assert row['shelf_text'] == said
    assert (row['agents'], promo['k']) == ('Named 1 of 2', 1)   # the rule counts naming only


def test_trade_promotions_as_served(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'prove', cycle=f2p1.CYCLE_2)
    _dump('prove-2t8.json', body)
    assert [(r['title'], r['change']) for r in body['rows']] == [
        ('Amazon: save 40% on 1 when you buy 2', 'continuing'), ('Amazon: $3 off coupon on Swaddlers v9', 'new')]
    assert all('The shelf said' not in r['detail'] for r in body['rows'])
    # the shelf said only what the title says: no shelf text to show
    assert body['rows'][1]['shelf_text'] is None


# ── B7: Impact ────────────────────────────────────────────────────────────

def test_the_series_is_on_the_hero_s_model(http, db, upstream):
    """Live: "At stake, per scored cycle: $38M FL14 · $35M FL15" beside a hero of $24M: the stored series predated
    2T-1's Missed (size answers). Recomputed on read under the hero's model, the newest point is the hero."""
    _shape(db, http, upstream)
    hero = _read(http, 'revenue', cycle=f2p1.CYCLE_2)
    _dump('revenue-2t8.json', hero)
    history = _read(http, 'revenue/history')
    _dump('revenue-history-2t8.json', history)
    newest = history['cycles'][-1]
    assert newest['cycle'] == f2p1.CYCLE_2
    assert newest['shares'] == hero['shares'] and newest['counts'] == hero['counts']
    assert newest['counts']['missed']['basis'] == 'attribute'


def test_the_third_driver_is_the_record(http, db, upstream):
    """Live #3: "Access · Agents can't read www.pampers.com … 3 agent identities could not read the pages", while
    every agent reads pampers.com (the blocks are retailer-page tokens)."""
    _shape(db, http, upstream)
    body = _read(http, 'revenue', cycle=f2p1.CYCLE_2)
    assert (body['third_driver'], body['access']) == ('record', None)
    assert body['record_driver'] == {
        'id': 'record', 'kind': 'root', 'title': 'pampers.com disagrees with itself', 'tag': 'Root cause',
        'sub': 'Feeds the two above', 'route': 'record',
        'measured': 'pampers.com states two Size 4 charts and Pure called current in 7 of 102 category answers.',
        'fix': 'One record per SKU with the right size chart per line, and Pure retired with AMORE as successor',
        'facts': {'two_charts': True, 'gtins': 0, 'retired': 'Pure'}}
    # the tile counts size answers, so it says so
    assert body['missed_tile'] == {'label': 'Missed on facts', 'unit': 'size answers'}
    # every GTIN fact named when the markup drops a digit
    driver = revenue_svc.record_driver(domain='pampers.com', size_signal=None, retired_signal=None,
                                       gtin_rows=[{'digits': 11}, {'digits': 11}])
    assert (driver['measured'], driver['fix']) == ('pampers.com states 2 GTINs that drop the leading zero.',
                                                   'One record per SKU with the right size chart per line, clean GTINs')


def test_the_charter_series_and_labels(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'revenue', cycle=f2p1.CYCLE_2)
    overview = _read(http, 'overview', cycle=f2p1.CYCLE_2)
    assert body['charter'] == overview['charter']
    assert body['baseline_line'] == 'Baseline, Oct 21, 6 SKUs, 6 agents, 4 retailers'
    # 2T-11 (B1): the series is /revenue/history's, read after first paint
    assert 'series' not in body
    series = _read(http, 'revenue/history')['series']
    # two scored cycles: two measured points per measure and nothing else
    assert [len(s['points']) for s in series] == [2, 2, 2, 2]
    assert all(p['measured'] for s in series for p in s['points'])
    assert body['scenario'] is None and all(s['scenario'] is None for s in series)
    newest = {s['key']: s['points'][-1]['value'] for s in series}
    assert newest == {t['key']: t['value'] for t in body['charter']}
    assert (body['baseline_label']['day'], body['cycle_label']['day']) == ('Oct 14', 'Oct 21')


def test_the_sent_block_carries_labels(http, db, upstream):
    _shape(db, http, upstream, sent='2026-10-17')
    lock = _read(http, 'revenue', cycle=f2p1.CYCLE_2)['locked']
    assert (lock['before'], lock['after']) == (f2p1.CYCLE_1, f2p1.CYCLE_2)
    assert (lock['baseline_label']['day'], lock['cycle_label']['day']) == ('Oct 14', 'Oct 21')
