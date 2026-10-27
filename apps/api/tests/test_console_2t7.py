"""
2T-7: seven items from the Oct 26 walk of the Measure screens (org 12,
FL15-pampers-20261024, scorer 18). No scorer change.

  1  the Visibility gap's second line from the counts (test_console_2t5_visibility's table)
  2  one cycle label (rm.cycle_label) for every "since / vs / against" string
  3  Accessibility's weight and GTIN checks as the demo words them
  4  True Value's brand column: "Markup lists no pack count" once
  5  the variant-clash clause on every cell whose shown run has one
  6  the receipt's SKU: a live deal first, then a list-vs-sale difference
  7  "Offer per retailer" on pampers.com: absence, explained, not drift

Inputs: the 2T-1 harness (supply #33's answers and pages RECORDED), with
console_fixture_2t5's FL15 shape (DERIVED and labelled), and rows built in
the served shapes where an item needs FL15's numbers. No production read, no
model call.
"""
import re

import pytest

from app.services import console_measure as measure
from app.services import console_read_models as rm
from tests import console_fixture_2p1 as f2p1
from tests import console_fixture_2r2 as f2r2
from tests import console_fixture_2t5 as f2t5
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import _encode, http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_console_2t1_overview_truesync import _read, _shape


# ── 2: one cycle label ────────────────────────────────────────────────────

def test_the_label_is_the_cycles_local_day():
    """FL15 against FL14: the cycle created 03:10 UTC on Oct 24 started Oct 23 in Los Angeles."""
    prev = {'cycle_code': 'FL14-pampers-20261023', 'created_at': '2026-10-24T03:10:00+00:00',
            'start_date': '2026-10-24'}
    assert rm.cycle_label(prev, 'America/Los_Angeles') == {
        'code': 'FL14-pampers-20261023', 'day': 'Oct 23', 'name': 'the Oct 23 cycle', 'since': 'Since Oct 23',
        'vs': 'vs Oct 23'}
    # no created_at: the UTC start date
    assert rm.cycle_label({'cycle_code': 'X', 'start_date': '2026-10-23'})['day'] == 'Oct 23'
    # no date at all: the code stands in
    assert rm.cycle_label({'cycle_code': 'X'}) == {'code': 'X', 'day': None, 'name': 'X', 'since': 'Since X',
                                                   'vs': 'vs X'}


def _strings(body, path=''):
    if isinstance(body, dict):
        for k, v in body.items():
            yield from _strings(v, f'{path}.{k}')
    elif isinstance(body, list):
        for i, v in enumerate(body):
            yield from _strings(v, f'{path}[{i}]')
    elif isinstance(body, str):
        yield path, body


#: the four Measure screens, the Overview (and its score card) and TrueSync
SCREENS = ('overview', 'score', 'answers', 'answers/summary', 'visibility', 'true-value', 'accessibility', 'truesync')


@pytest.mark.parametrize('shape', ['compared', 'fl15'])
def test_no_served_string_carries_a_cycle_code(shape, http, db, upstream):
    """Both cycles carry a local day, so no copy names either by its code: an identifier (a string that IS the
    code) stays. `compared` is 2P-1's pair (Changes, moved, drift); `fl15` adds FL15's comparison questions, so
    the pair does not compare (the "Not comparable" notes)."""
    _shape(db, http, upstream)
    if shape == 'fl15':
        f2t5.comparison(db, _encode)
    upstream.answer('GET', f'{f2r2.BASE}/reference', body=f2r2.body('reference'), token=f2r2.TOKEN_A)
    codes = (f2p1.CYCLE_1, f2p1.CYCLE_2)
    hits = []
    for endpoint in SCREENS:
        params = {} if endpoint in ('accessibility', 'truesync') else {'cycle': f2p1.CYCLE_2}
        body = _read(http, endpoint, **params)
        hits += [(endpoint, p, s) for p, s in _strings(body) if s not in codes and any(c in s for c in codes)]
    assert hits == []


def test_the_previous_block_and_the_copy_read_the_label(http, db, upstream):
    _shape(db, http, upstream)
    vis = _read(http, 'visibility', cycle=f2p1.CYCLE_2)
    assert vis['previous'] == {'cycle': f2p1.CYCLE_1, 'status': 'compared', 'note': None, 'day': 'Oct 14',
                               'name': 'the Oct 14 cycle', 'since': 'Since Oct 14', 'vs': 'vs Oct 14'}
    assert vis['lede'].startswith('Who the answers name, and who they name first, in the Oct 21 cycle.')
    assert all(re.search(r'in the Oct 14 cycle\.$', b['detail']) for b in vis['moved']['all']['brands'])
    over = _read(http, 'overview', cycle=f2p1.CYCLE_2)
    assert over['vs_label'] == 'vs Oct 14' and over['vs_cycle'] == f2p1.CYCLE_1
    assert all(c['detail'].endswith('in the Oct 14 cycle.') for c in over['by_surface']['all']['changes'])
    score = _read(http, 'score', cycle=f2p1.CYCLE_2)
    assert (score['previous']['cycle'], score['previous']['vs']) == (f2p1.CYCLE_1, 'vs Oct 14')



# ── 3: Accessibility's weight and GTIN checks, as the demo words them ─────

def test_the_weight_check_counts_the_pages_that_contradict_the_size_selector():
    """FL15: 3 of the 4 pages whose markup states a range state one their own chart does not. DERIVED on
    /reference's attributes (2M-1's markup and chart ranges)."""
    import copy
    from tests.test_console_2t4_accessibility import _build, _by_key
    reference = copy.deepcopy(f2r2.body('reference'))
    for a in reference['attributes']:
        if a['variant_ref'] == 'feed_sku:6':   # Zzz Size 4: markup 15 to 34, chart 22 to 37
            a.update(markup={'min': 15, 'max': 34}, chart={'min': 22, 'max': 37})
        if a['variant_ref'] == 'feed_sku:5':   # Swaddlers Size 4: agreeing
            a.update(markup={'min': 15, 'max': 34}, chart={'min': 15, 'max': 34})
    weight = _by_key(_build(reference=reference))['weight']
    assert weight['name'] == 'Weight in markup contradicts the size selector'
    assert (weight['value'], weight['got'], weight['of'], weight['status']) == ('1 of 2 pages: Zzz', 1, 2, 'partial')
    assert weight['basis'] == "pages whose markup states a weight range pampers.com's size selector does not: Zzz"
    for a in reference['attributes']:
        if a['variant_ref'] == 'feed_sku:6':
            a.update(chart={'min': 15, 'max': 34})
    weight = _by_key(_build(reference=reference))['weight']
    assert (weight['value'], weight['status']) == ('0 of 2 pages', 'ok')


def test_the_gtin_check_names_the_lines_that_drop_a_digit():
    from tests.test_console_2t4_accessibility import _build, _by_key
    import copy
    prices = f2r2.retailer_prices()['prices']
    zzz = next(r for r in prices if r.get('role') == 'own' and 'zzz' in (r.get('url') or ''))
    extra = []
    # each page's one gtin13 written with 11 digits (its leading zero dropped), on two of the feed's pages
    for line, url, gtin in (('AMORE', 'amore-diapers', '30772244425'),
                            ('Ultra', 'pure-protection-diapers', '37000833970')):
        page = copy.deepcopy(zzz)
        page.update(url=f'https://www.pampers.com/en-us/diapers-wipes/{url}', observed_at='2026-10-24T04:00:00+00:00')
        page['json_ld'] = {**page['json_ld'], 'name': f'Pampers® {line} Diapers',
                           'hasVariant': [{**page['json_ld']['hasVariant'][0], 'gtin13': gtin, 'size': '1'}]}
        extra.append(page)
    gtin = _by_key(_build(prices=prices + extra))['gtin']
    assert gtin['value'] == 'AMORE and Ultra drop the leading zero'
    assert gtin['basis'] == '2 of 16 GTINs in the markup drop the leading zero: AMORE and Ultra'


# ── 4: the brand column's note ────────────────────────────────────────────

def _tv_row(sku, product):
    return {'product': product, 'sku': sku, 'feed_sku': sku, 'variant_id': f'feed_sku:{sku}', 'gtin': None,
            'cells': {'pampers.com': {'status': 'none', 'quotes': []}}}


def _tv_body(rows):
    cols = [{'id': 'pampers.com', 'name': 'pampers.com', 'you': True}, {'id': 'amazon.com', 'name': 'Amazon'}]
    return {'column_kind': 'retailer', 'columns': cols, 'retailer_columns': [dict(c) for c in cols],
            'columns_by_surface': {'all': [dict(c) for c in cols]}, 'rows': rows, 'programs': [], 'as_of': None}


def _own_reads():
    """#33's pampers.com reads as recorded: the Swaddlers and Zzz ProductGroups, gtin13 per size, no count."""
    return [r for r in f2r2.retailer_prices()['prices'] if r.get('role') == 'own' and r.get('json_ld')]


def test_the_recorded_markup_lists_no_pack_count_and_says_it_once():
    reads = _own_reads()
    nodes = [v for r in reads for v in r['json_ld']['hasVariant']]
    assert nodes and not any(measure._COUNT.search(measure._words(n)) for n in nodes)
    assert measure.markup_lists(reads, ['pampers.com']) == {'counts': False, 'prices': False}
    rows = [_tv_row('5', 'Size 4, 150 ct'), _tv_row('6', 'Size 4, 104 ct')]
    body = measure.true_value_brand(_tv_body(rows), reads=reads, deals=None, promo=None, attribute_answers=[],
                                    feed_rows=None, own_domains=['pampers.com'], brand='Pampers')
    # once, on the brand's column in every column list
    assert body['brand_column_note'] == 'Markup lists no pack count'
    assert [c.get('note') for c in body['columns']] == ['Markup lists no pack count', None]
    assert body['columns_by_surface']['all'][0]['note'] == 'Markup lists no pack count'
    # and no cell repeats it (was "No 150 ct listed", "No 104 ct listed"); no price anywhere is not a cell's note
    assert [r['cells']['pampers.com']['note'] for r in body['rows']] == [None, None]


def test_no_count_listed_only_where_the_markup_lists_other_counts():
    """DERIVED: the Zzz page as recorded, the Swaddlers page with its sizes' counts in the variant names."""
    reads = _own_reads()
    swaddlers = next(r for r in reads if 'swaddlers' in r['url'])
    for v in swaddlers['json_ld']['hasVariant']:
        v['name'] = f"Size {v['size']}, 100 ct"
    rows = [_tv_row('5', 'Size 4, 150 ct'), _tv_row('6', 'Size 4, 104 ct')]
    body = measure.true_value_brand(_tv_body(rows), reads=reads, deals=None, promo=None, attribute_answers=[],
                                    feed_rows=None, own_domains=['pampers.com'], brand='Pampers')
    assert body['brand_column_note'] is None and body['columns'][0]['note'] is None
    assert [r['cells']['pampers.com']['note'] for r in body['rows']] == ['No 150 ct listed',
                                                                         'Markup lists no pack count']
