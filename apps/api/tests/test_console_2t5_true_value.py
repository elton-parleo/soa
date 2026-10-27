"""
2T-5 (True Value): the demo's True Value for a brand at retail (pg.ts
trueValue, Leads.tsx TrueValueLead), from the Oct 26 findings.

  TV1 `hero` from the tiles, no program clause; `programs` null for a brand
      with none
  TV3 the brand's own domain first, then the retailers alphabetical
  TV4 cells gain `live_deal` (ppt.label), the brand column's `note` from the
      brand page's read, `not_sold` when the feed lists no page there
  TV5 each row's `line`: the deal clause and the weight clause
  TV6 `anatomy` of the most-asked SKU on its most-asked retailer
  TV8 a variant-clash cell shows the clash
  TV9 the brand-mode captions

Two kinds of input, each named where it is used: the 2T-1 harness (supply
#33's answers RECORDED) end to end; and brand-page reads, list prices, a feed
and quotes built here in supply's served shape (/reference rows with
json_ld, /feed rows, deals), DERIVED for the notes FL15 showed ("No 84 ct
listed. Markup prices the 140 ct at $44.94", "No price in markup. GTIN has 11
digits", "Retired. Redirects to AMORE"). No production read, no model call.
"""
import pytest

from app.services import console_measure as measure
from tests import console_fixture_2p1 as f2p1
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_console_2t1_overview_truesync import _read, _shape

OWN = ['pampers.com']


def _tv(db, http, upstream):
    _shape(db, http, upstream)
    return _read(http, 'true-value', cycle=f2p1.CYCLE_2)


# ── end to end on the harness ─────────────────────────────────────────────

def test_brand_mode_on_the_harness(http, db, upstream):
    tv = _tv(db, http, upstream)
    assert tv['mode'] == 'manufacturer'
    # TV3: own first, then alphabetical
    assert [c['id'] for c in tv['columns']] == ['pampers.com', 'amazon.com', 'walmart.com']
    # TV1: the hero is the cells'
    cells = [c for r in tv['rows'] for c in r['cells'].values()]
    wrong = sum(1 for c in cells if c['status'] == 'wrong')
    left = sum(1 for c in cells if c['status'] == 'missed')
    read = sum(1 for c in cells if c['status'] in ('exact', 'wrong', 'partial', 'missed'))
    assert tv['hero']['text'] == (f"{wrong + left} of {read} prices read are wrong or missing · {wrong} quoted prices "
                                  f"are off the live page, and {left} retailer prices were left out")
    assert 'program' not in tv['hero']['text']
    # TV9
    assert tv['captions']['wrong'] == "A price the retailer's page did not show"
    # TV4, TV5 on the harness's deals (Amazon's multi-buy live on five SKUs) and its weight answers
    first = tv['rows'][0]
    assert first['cells']['amazon.com']['live_deal'] == 'Amazon: save 40% on 1 when you buy 2'
    assert first['cells']['walmart.com']['live_deal'] is None
    assert first['line'] == ('Amazon: save 40% on 1 when you buy 2 was live. 2 of 10 cheapest-place answers named '
                             'it. Weight right in 4 of 5.')
    # TV6: the most-asked cell, what agents quoted
    assert tv['anatomy']['title'] == 'Anatomy of a Wiggle & Snug pack'
    assert tv['anatomy']['rows'][-1]['k'] == 'What agents quoted'
    assert tv['read_errors'] == {}


def test_a_merchant_not_in_brand_mode_is_served_as_before(http, db, upstream):
    _shape(db, http, upstream)
    tv = _read(http, 'true-value', cycle=f2p1.CYCLE_2, merchant=None)
    assert 'hero' not in tv and 'mode' not in tv


# ── the brand-page read, DERIVED in supply's /reference shape ─────────────

def _page(sku, label, nodes, *, url='https://www.pampers.com/swaddlers', final_url=None):
    return {'retailer_domain': 'pampers.com', 'role': 'own', 'sku': sku, 'variant_ref': f'feed_sku:{sku}',
            'variant_label': label, 'url': url, 'final_url': final_url or url, 'read_status': 'ok',
            'observed_at': '2026-10-24T04:00:00+00:00', 'method': 'none_by_design', 'price': None,
            'json_ld': {'@type': 'ProductGroup', 'name': 'Pampers Swaddlers', 'hasVariant': nodes}}


def _node(name, size, gtin='0037000799818', price=None):
    node = {'@type': 'Product', 'name': name, 'size': size, 'gtin13': gtin}
    if price:
        node['offers'] = {'@type': 'Offer', 'price': price, 'url': 'https://www.amazon.com/x'}
    return node


def _row(sku, product, **kw):
    return {'product': product, 'sku': sku, 'feed_sku': sku, 'variant_id': f'feed_sku:{sku}', 'gtin': None, **kw}


@pytest.mark.parametrize('row,reads,note', [
    (_row('nb84', 'Newborn, 84 ct'),
     [_page('nb84', 'Newborn, 84 ct', [_node('Swaddlers Newborn 140 ct', 'Newborn', price='44.94')])],
     'No 84 ct listed. Markup prices the 140 ct at $44.94'),
    (_row('am1', 'Size 1, 132 ct'),
     [_page('am1', 'Size 1, 132 ct', [_node('AMORE Size 1 132 ct', '1', gtin='37000799818')])],
     'No price in markup. GTIN has 11 digits'),
    (_row('pure1', 'Size 1, 132 ct', retired={'successor': {'label': 'AMORE'}}),
     [_page('pure1', 'Size 1, 132 ct', [], url='https://www.pampers.com/pure',
            final_url='https://www.pampers.com/amore')],
     'Retired. Redirects to AMORE'),
    (_row('pure1', 'Size 1, 132 ct', retired={'successor': {'label': 'AMORE'}}), [],
     'Retired. AMORE is its successor'),
    (_row('s4', 'Size 4, 150 ct'), [], None),   # no read of the brand's page: no note
])
def test_the_brand_columns_note(row, reads, note):
    # 2T-7 (4): the demo's markup lists counts and prices on other lines (pg.ts "Markup prices the 140 ct")
    assert measure.brand_note(row, reads, OWN, 'Pampers', {'counts': True, 'prices': True}) == note


def _cell(**kw):
    return {'quoted': '—', 'live': '$27.97', 'status': 'exact', 'runs': 0, 'quotes': [], **kw}


def _body(rows):
    return {'column_kind': 'retailer', 'columns': [{'id': 'walmart.com', 'name': 'Walmart', 'you': False},
                                                   {'id': 'pampers.com', 'name': 'pampers.com', 'you': True},
                                                   {'id': 'amazon.com', 'name': 'Amazon', 'you': False},
                                                   {'id': 'cvs.com', 'name': 'CVS', 'you': False}],
            'retailer_columns': [], 'columns_by_surface': {}, 'rows': rows, 'programs': [], 'as_of': None}


def test_not_sold_reads_the_feed_and_the_clash_is_shown():
    quotes = [{'agent': 'chatgpt', 'stated': '44.99', 'outcome': 'wrong', 'clash': 'Pampers Swaddlers Size 3, 116-count'},
              {'agent': 'gemini', 'stated': '44.99', 'outcome': 'wrong', 'clash': 'Pampers Swaddlers Size 3, 116-count'},
              {'agent': 'copilot', 'stated': '49.99', 'outcome': 'wrong'}]
    row = _row('s4', 'Size 4, 104 ct', cells={'pampers.com': _cell(status='none'),
                                              'amazon.com': _cell(status='wrong', outcome='wrong', quoted='$44.99',
                                                                  runs=3, quotes=quotes),
                                              'cvs.com': _cell(status='none', live='—')})
    feed = [{'sku': 's4', 'retailers': [{'domain': 'pampers.com'}, {'domain': 'amazon.com'}]}]
    body = measure.true_value_brand(_body([row]), reads=[], deals=None, promo=None, attribute_answers=[],
                                    feed_rows=feed, own_domains=OWN, brand='Pampers')
    cells = body['rows'][0]['cells']
    assert (cells['amazon.com']['not_sold'], cells['cvs.com']['not_sold']) == (False, True)
    assert cells['amazon.com']['clash'] == '$44.99 for Size 3, 116 ct'
    assert 'clash' not in cells['cvs.com']
    # TV3 on the columns, TV1's programs
    assert [c['id'] for c in body['columns']] == ['pampers.com', 'amazon.com', 'cvs.com', 'walmart.com']
    assert body['programs'] is None and body['programs_reason']
    # with no feed read, not_sold is not claimed
    body = measure.true_value_brand(_body([_row('s4', 'Size 4, 104 ct', cells={'cvs.com': _cell()})]), reads=[],
                                    deals=None, promo=None, attribute_answers=[], feed_rows=None, own_domains=OWN,
                                    brand='Pampers')
    assert body['rows'][0]['cells']['cvs.com']['not_sold'] is None


DEALS = {'read_date': '2026-10-24', 'deals': [
    {'retailer_domain': 'amazon.com', 'kind': 'multi_buy', 'text': 'Save 40% on 1 when you buy 2',
     'terms': 'buy 2, save 40% on 1', 'variants': [{'sku': 's1', 'variant_ref': 'feed_sku:s1', 'price': '22.38'}]}]}


def test_the_anatomy_of_the_most_asked_cell():
    quotes = [{'agent': 'gemini', 'stated': '27.97', 'outcome': 'exact'},
              {'agent': 'perplexity', 'stated': '27.97', 'outcome': 'exact'}]
    row = _row('s1', 'Size 1, 96 ct', cells={'amazon.com': _cell(runs=2, quotes=quotes),
                                             'walmart.com': _cell(runs=1)})
    read = {'retailer_domain': 'amazon.com', 'sku': 's1', 'variant_ref': 'feed_sku:s1', 'price': '27.97',
            'list_price': '29.99', 'observed_at': '2026-10-24T14:00:00+00:00'}
    deal_id = measure.ppt.deal_id(DEALS['deals'][0])
    promo = {'judged': [{'variant_id': 'feed_sku:s1', 'live': [deal_id], 'named': []} for _ in range(5)]}
    a = measure.anatomy([row], reads=[read], deals=DEALS, promo=promo, brand='Pampers', day='Oct 24')
    assert (a['title'], a['sub']) == ('Anatomy of a Pampers pack', 'Size 1, 96 ct on Amazon, Oct 24')
    assert [(r['k'], r['v'], r.get('tag')) for r in a['rows']] == [
        ('List price', '$29.99', 'amazon.com'),
        ('Amazon price cut', '-$2.02', '-7% vs list'),
        ('One-time price', '$27.97', None),
        (f"Or {measure.ppt.label(DEALS['deals'][0], DEALS['deals'][0]['variants'][0]).split(': ', 1)[1]}", '$22.38',
         'Named 0 of 5'),
        ('What agents quoted', '$27.97', 'Gemini and Perplexity'),
    ]


def test_the_product_line_with_two_deals_and_weight():
    deals = {'deals': [DEALS['deals'][0], {'retailer_domain': 'kroger.com', 'kind': 'spend_get', 'text':
                                           'Spend $60, save $15', 'variants': [{'sku': 's1'}]}]}
    promo = {'judged': [{'variant_id': 'feed_sku:s1', 'named': []} for _ in range(5)]}
    weights = [{'variant_id': 'feed_sku:s1', 'verdict': 'match'} for _ in range(5)]
    line = measure.product_line(_row('s1', 'Size 1, 96 ct'), deals=deals, promo=promo, attribute_answers=weights)
    assert line.endswith('were live. 0 of 5 cheapest-place answers named either. Weight right in 5 of 5.')
    assert line.startswith('Amazon: ') and ' and Kroger: ' in line


def test_the_hero_counts():
    rows = [{'cells': {'a': {'status': 'wrong'}, 'b': {'status': 'missed'}, 'c': {'status': 'exact'},
                       'd': {'status': 'none'}, 'e': {'status': 'unverifiable'}}}]
    hero = measure.true_value_hero(rows)
    assert hero['text'] == ('2 of 3 prices read are wrong or missing · 1 quoted price is off the live page, and 1 '
                            'retailer price was left out')
