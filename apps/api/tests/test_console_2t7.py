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


# ── 5: the variant-clash clause on every cell whose shown run has one ─────

def _q(agent, stated, outcome='wrong', clash=None):
    return {'agent': agent, 'stated': stated, 'outcome': outcome, **({'clash': clash} if clash else {})}


def test_the_clash_shows_whenever_the_shown_run_has_one():
    """FL15's Zzz row, DERIVED in True Value's served shape: on Amazon the shown quote, $44.99, equals the live
    price, and the worst run is ChatGPT's "$44.99 for Size 3, 116-count" (variant_clash), the other wrong quotes
    carrying none, so most wrong quotes named no clash (2T-5's rule showed none); on Walmart the clash is most of
    them, as before."""
    amazon = {'quoted': '$44.99', 'live': '$44.99', 'status': 'wrong', 'outcome': 'wrong', 'runs': 5, 'quotes': [
        _q('chatgpt', '44.99', clash='Pampers Zzz Size 3, 116-count'), _q('perplexity', '44.99'),
        _q('copilot', '47.99'), _q('claude', '41.99'), _q('gemini', '44.99', 'exact')]}
    walmart = {'quoted': '$22.97', 'live': '$38.97', 'status': 'wrong', 'outcome': 'wrong', 'runs': 2, 'quotes': [
        _q('chatgpt', '22.97', clash='Pampers Zzz Size 5, 56 ct'), _q('gemini', '22.97', clash='Pampers Zzz Size 5, 56 ct')]}
    row = {'product': 'Size 4, 104 ct', 'sku': '6', 'feed_sku': '6', 'variant_id': 'feed_sku:6', 'gtin': None,
           'cells': {'pampers.com': {'status': 'none', 'quotes': []}, 'amazon.com': amazon, 'walmart.com': walmart}}
    body = measure.true_value_brand(_tv_body([row]), reads=[], deals=None, promo=None, attribute_answers=[],
                                    feed_rows=None, own_domains=['pampers.com'], brand='Pampers')
    cells = body['rows'][0]['cells']
    assert cells['amazon.com']['clash'] == '$44.99 for Size 3, 116 ct'
    assert cells['walmart.com']['clash'] == '$22.97 for Size 5, 56 ct'
    # the shown run carries no clash: none, though another run's does
    amazon['quotes'][0].pop('clash')
    amazon['quotes'][2]['clash'] = 'Pampers Zzz Size 3, 116-count'
    assert measure.clash_text(amazon) is None


# ── 6: the receipt's SKU ──────────────────────────────────────────────────

ROLLBACK = {'retailer_domain': 'walmart.com', 'kind': 'rollback', 'text': 'Rollback', 'terms': 'Rollback, 17% off',
            'variants': [{'sku': 's4', 'variant_ref': 'feed_sku:s4', 'price': '49.77'}]}


def _rcell(runs, quotes=()):
    return {'quoted': '—', 'live': '—', 'status': 'exact', 'runs': runs, 'quotes': list(quotes)}


def _receipt_rows():
    """FL15's shape, DERIVED: Swaddlers Newborn asked most (on Amazon, one-time price only), Swaddlers Size 4
    asked next, most on Walmart, where its Rollback was live and the page listed $59.77 against $49.77."""
    quotes = [{'agent': 'chatgpt', 'stated': '49.77', 'outcome': 'exact'},
              {'agent': 'gemini', 'stated': '59.77', 'outcome': 'wrong'}]
    return [
        {'product': 'Newborn, 84 ct', 'sku': 'nb', 'feed_sku': 'nb', 'variant_id': 'feed_sku:nb', 'gtin': None,
         'cells': {'amazon.com': _rcell(12), 'walmart.com': _rcell(4)}},
        {'product': 'Size 4, 150 ct', 'sku': 's4', 'feed_sku': 's4', 'variant_id': 'feed_sku:s4', 'gtin': None,
         'cells': {'amazon.com': _rcell(3), 'walmart.com': _rcell(10, quotes)}},
    ]


READS = [{'retailer_domain': 'amazon.com', 'sku': 'nb', 'variant_ref': 'feed_sku:nb', 'price': '27.97',
          'observed_at': '2026-10-24T14:00:00+00:00'},
         {'retailer_domain': 'walmart.com', 'sku': 's4', 'variant_ref': 'feed_sku:s4', 'price': '49.77',
          'list_price': '59.77', 'observed_at': '2026-10-24T14:00:00+00:00'}]


def test_the_receipt_takes_the_most_asked_sku_with_a_live_deal():
    deals = {'read_date': '2026-10-24', 'deals': [ROLLBACK]}
    deal_id = measure.ppt.deal_id(ROLLBACK)
    promo = {'judged': [{'variant_id': 'feed_sku:s4', 'live': [deal_id], 'named': [deal_id] if i < 1 else []}
                        for i in range(4)]}
    a = measure.anatomy(_receipt_rows(), reads=READS, deals=deals, promo=promo, brand='Pampers', day='Oct 24')
    assert (a['sku'], a['retailer'], a['picked_by']) == ('s4', 'walmart.com', 'live_deal')
    assert a['sub'] == 'Size 4, 150 ct on Walmart, Oct 24'
    # list, the price cut, the one-time price, the deal with its named count, what agents quoted
    assert [(r['k'], r['v'], r.get('tag')) for r in a['rows']] == [
        ('List price', '$59.77', 'walmart.com'),
        ('Walmart price cut', '-$10.00', '-17% vs list'),
        ('One-time price', '$49.77', None),
        (f"Or {measure.ppt.label(ROLLBACK, ROLLBACK['variants'][0]).split(': ', 1)[1]}", '$49.77', 'Named 1 of 4'),
        ('What agents quoted', '$49.77, $59.77', 'ChatGPT and Gemini'),
    ]


def test_with_no_live_deal_a_list_vs_sale_difference_then_the_most_asked():
    a = measure.anatomy(_receipt_rows(), reads=READS, deals=None, promo=None, brand='Pampers', day='Oct 24')
    assert (a['sku'], a['retailer'], a['picked_by']) == ('s4', 'walmart.com', 'list_vs_sale')
    flat = [{**r, 'list_price': None} for r in READS]
    a = measure.anatomy(_receipt_rows(), reads=flat, deals=None, promo=None, brand='Pampers', day='Oct 24')
    # 2T-5's pick: the most-asked cell, Swaddlers Newborn on Amazon, one line
    assert (a['sku'], a['retailer'], a['picked_by']) == ('nb', 'amazon.com', 'most_asked')
    assert [r['k'] for r in a['rows']] == ['One-time price']


# ── 7: "Offer per retailer" on pampers.com ────────────────────────────────

def test_the_recorded_pages_carry_productgroup_and_gtin13_and_no_offer():
    """What #33's recorded pampers.com pages carry (FL15's live pages are production reads, not read here;
    2T-4's report found the same on all 7): a ProductGroup, a gtin13 on every variant, no Offer node."""
    reads = _own_reads()
    assert len(reads) == 2
    for r in reads:
        assert r['json_ld']['@type'] == 'ProductGroup'
        assert all(v.get('gtin13') for v in r['json_ld']['hasVariant'])
        assert not any(v.get('offers') for v in r['json_ld']['hasVariant']) and 'offers' not in r['json_ld']


def test_the_check_explains_its_zero_and_the_markup_counts_no_drift_for_it():
    from app.services import console_manufacturer as manu
    from tests.test_console_2t4_accessibility import _build, _by_key
    check = _by_key(_build())['product_group']
    assert (check['value'], check['status'], check['offers_absent']) == ('0 of 6', 'bad', True)
    assert check['basis'] == 'ProductGroup with gtin13 on 2 of 6. No Offer per retailer in the markup'
    # FL15's 7 pages, each a ProductGroup with gtin13 and no Offer, DERIVED from the recorded Swaddlers page
    import copy
    prices = f2r2.retailer_prices()['prices']
    swaddlers = next(r for r in prices if r.get('role') == 'own' and r.get('json_ld') and 'swaddlers' in r['url'])
    feed = [{'sku': f's{i}', 'retailers': [{'domain': 'pampers.com', 'url': f'https://www.pampers.com/p{i}'},
                                           {'domain': 'amazon.com', 'url': f'https://www.amazon.com/p{i}'}]}
            for i in range(7)]
    pages = [{**copy.deepcopy(swaddlers), 'url': f'https://www.pampers.com/p{i}'} for i in range(7)]
    from app.services import console_accessibility_brand as acc
    out = acc.build(prices=pages, feed_rows=feed, reference=None, access=None, robots=None,
                    own_domains=['pampers.com'], retailers=['amazon.com'], brand='Pampers')
    seven = _by_key(out)['product_group']
    assert (seven['value'], seven['basis']) == ('0 of 7', 'ProductGroup with gtin13 on 7 of 7. No Offer per retailer '
                                                          'in the markup')
    # not drift: the site markup surface and the lead's markup tile count weight rows and GTIN flags only
    page_list = [{'url': p['url'], 'observed_at': p['observed_at'], 'brand_page': manu.row_brand_page(p) or {}}
                 for p in pages]
    flags = [f for f in manu.gtin_flags(page_list, None, brand='Pampers') if f.get('where') == 'markup']
    assert flags == [] and manu.markup_reason([], None, flags) is None


# ── the console's samples ─────────────────────────────────────────────────

def _dump(out, name, body):
    import json
    import os
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, name), 'w') as fh:
        json.dump(body, fh, indent=1, sort_keys=True)


def _fl15_true_value(tv: dict) -> dict:
    """True Value with FL15's shape laid on the harness's served body, DERIVED and said so, by soa's own
    console_measure.true_value_brand: pampers.com's recorded ProductGroups as each row's brand page (no pack
    count anywhere, item 4), an Amazon list price over v0's one-time price (item 6's receipt), FL15's Zzz row
    on Size 4, 104 ct (item 5: Amazon's shown run $44.99 for Size 3, 116-count beside a live $44.99, Walmart's
    $22.97 for Size 5, 56 ct), and the harness's deals and named counts."""
    import copy
    body = copy.deepcopy(tv)
    page = next(r for r in _own_reads() if 'swaddlers' in r['url'])
    reads = [{**copy.deepcopy(page), 'variant_ref': r['variant_id'], 'sku': None} for r in body['rows']]
    reads.append({'retailer_domain': 'amazon.com', 'variant_ref': 'feed_sku:v0', 'price': '27.97',
                  'list_price': '29.99', 'observed_at': '2026-10-21T14:00:00+00:00'})
    zzz = next(r for r in body['rows'] if r['variant_id'] == 'feed_sku:v4')
    zzz['cells']['amazon.com'].update(quoted='$44.99', live='$44.99', status='wrong', outcome='wrong', runs=5, quotes=[
        _q('chatgpt', '44.99', clash='Pampers Zzz Size 3, 116-count'), _q('perplexity', '44.99'),
        _q('copilot', '47.99'), _q('claude', '41.99'), _q('gemini', '44.99', 'exact')])
    zzz['cells']['walmart.com'].update(quoted='$22.97', live='$38.97', status='wrong', outcome='wrong', runs=2, quotes=[
        _q('chatgpt', '22.97', clash='Pampers Zzz Size 5, 56 ct'), _q('gemini', '22.97', clash='Pampers Zzz Size 5, 56 ct')])
    deal = {'retailer_domain': 'amazon.com', 'kind': 'multi_buy', 'text': 'Save 40% on 1 when you buy 2',
            'terms': 'buy 2, save 40% on 1', 'variants': [{'sku': 'v0', 'variant_ref': 'feed_sku:v0', 'price': '22.38'}]}
    did = measure.ppt.deal_id(deal)
    promo = {'judged': [{'variant_id': 'feed_sku:v0', 'live': [did], 'named': [did] if i < 2 else []}
                        for i in range(10)]}
    return measure.true_value_brand(body, reads=reads, deals={'read_date': '2026-10-21', 'deals': [deal]},
                                    promo=promo, attribute_answers=[], feed_rows=None, own_domains=['pampers.com'],
                                    brand='Wiggle & Snug')


def _fl15_accessibility(acc_body: dict) -> dict:
    """Accessibility's six checks with FL15's shape, DERIVED and said so, by soa's own
    console_accessibility_brand.build: seven pampers.com pages, each the recorded Swaddlers ProductGroup (gtin13,
    no Offer), the AMORE and Ultra pages' gtin13 written with 11 digits, and the markup's weight range against the
    chart on four lines, three of them contradicting it (Baby-Dry, Cruisers 360, Zzz). The hero and the retailer
    checks are the harness's."""
    import copy
    from app.services import console_accessibility_brand as acc
    body = copy.deepcopy(acc_body)
    swaddlers = next(r for r in _own_reads() if 'swaddlers' in r['url'])
    lines = (('swaddlers', 'Swaddlers', None), ('baby-dry', 'Baby-Dry', None), ('cruisers-360', 'Cruisers 360', None),
             ('zzz', 'Zzz', None), ('pure', 'Pure Protection', None), ('amore', 'AMORE', '30772244425'),
             ('ultra', 'Swaddlers Ultra Day + Night', '37000833970'))
    pages, feed = [], []
    for slug, line, short in lines:
        url = f'https://www.pampers.com/en-us/products/pampers-{slug}'
        page = copy.deepcopy(swaddlers)
        page.update(url=url, observed_at='2026-10-24T04:00:00+00:00')
        page['json_ld'] = {**page['json_ld'], 'name': f'Pampers® {line} Diapers'}
        if short:
            page['json_ld']['hasVariant'] = [{**page['json_ld']['hasVariant'][2], 'gtin13': short}]
        pages.append(page)
        feed.append({'sku': slug, 'retailers': [{'domain': 'pampers.com', 'url': url},
                                                {'domain': 'amazon.com', 'url': f'https://www.amazon.com/{slug}'}]})
    attrs = [{'variant_ref': f'feed_sku:{slug}', 'product_name': f'Pampers {line}', 'variant_label': 'Size 4',
              'markup': {'min': 15, 'max': 34}, 'chart': {'min': 15 if slug == 'swaddlers' else 22, 'max': 34 if
                                                          slug == 'swaddlers' else 37}}
             for slug, line, _s in lines[:4]]
    out = acc.build(prices=pages, feed_rows=feed, reference={'attributes': attrs}, access=None, robots=None,
                    own_domains=['pampers.com'], retailers=['amazon.com'], brand='Pampers')
    body['checks'] = out['checks']
    return body


def _fl15_visibility(vis: dict) -> dict:
    """Visibility's gap with FL15's counts, DERIVED and said so: the brand named 103 times and first in 80, Huggies
    named 64 and first in 26, every other brand behind Huggies, laid on the harness's brand-choice ranking, the lead rebuilt by soa's own
    console_measure.visibility_lead."""
    import copy
    body = copy.deepcopy(vis)
    rows = body['ranking']['brand_choice']['rows']
    for r in rows:
        if r.get('you'):
            r.update(named=103, first=80)
        elif r['name'] == f2t5.RIVAL:
            r.update(named=64, first=26)
        else:   # the harness's third brand stays behind Huggies, as every other brand was on FL15
            r.update(first=min(r['first'], 12), named=min(r['named'], 40))
    body.update(measure.visibility_lead(body, f2t5.BRAND, {'dollars': None,
                                                           'reason': 'enter sales in scope on Impact'}))
    return body


def test_the_console_samples(http, db, upstream):
    """SOA_2T7_SAMPLE_DUMP=<dir>: the 2T-5 samples re-recorded on this branch (the 2T-1 harness, FL15's comparison
    questions, #33's /reference), and the FL15-shaped samples DERIVED above for the items the harness cannot show."""
    import os
    _shape(db, http, upstream)
    f2t5.comparison(db, _encode)
    upstream.answer('GET', f'{f2r2.BASE}/reference', body=f2r2.body('reference'), token=f2r2.TOKEN_A)
    read = {name: _read(http, ep, **({} if ep == 'accessibility' else {'cycle': f2p1.CYCLE_2}))
            for name, ep in (('answers-2t5.json', 'answers'), ('answers-summary-2t5.json', 'answers/summary'),
                             ('visibility-2t5.json', 'visibility'), ('true-value-2t5.json', 'true-value'),
                             ('accessibility-2t5.json', 'accessibility'))}
    derived = {'true-value-2t7.json': _fl15_true_value(read['true-value-2t5.json']),
               'accessibility-2t7.json': _fl15_accessibility(read['accessibility-2t5.json']),
               'visibility-2t7.json': _fl15_visibility(read['visibility-2t5.json'])}
    tv = derived['true-value-2t7.json']
    assert tv['brand_column_note'] == 'Markup lists no pack count'
    assert {r['variant_id']: r['cells']['pampers.com'].get('note') for r in tv['rows']} == \
        {r['variant_id']: None for r in tv['rows']}
    zzz = next(r for r in tv['rows'] if r['variant_id'] == 'feed_sku:v4')['cells']
    assert (zzz['amazon.com']['clash'], zzz['walmart.com']['clash']) == ('$44.99 for Size 3, 116 ct',
                                                                       '$22.97 for Size 5, 56 ct')
    assert (tv['anatomy']['picked_by'], [r['k'] for r in tv['anatomy']['rows']][:3]) == (
        'live_deal', ['List price', 'Amazon price cut', 'One-time price'])
    checks = {c['key']: c for c in derived['accessibility-2t7.json']['checks']}
    assert checks['weight']['value'] == '3 of 4 pages: Baby-Dry, Cruisers 360 and Zzz'
    assert checks['gtin']['value'] == 'AMORE and Swaddlers Ultra Day + Night drop the leading zero'
    assert checks['product_group']['basis'] == 'ProductGroup with gtin13 on 7 of 7. No Offer per retailer in the markup'
    assert derived['visibility-2t7.json']['gap']['sentence'] == (
        '54 first picks ahead of Huggies · Named more often than Huggies, picked first more often')
    out = os.environ.get('SOA_2T7_SAMPLE_DUMP')
    if out:
        for name, body in {**read, **derived}.items():
            _dump(out, name, body)
