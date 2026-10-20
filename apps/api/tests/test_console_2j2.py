"""
2J-2: a brand's read models, on the FL12-shaped brand fixture
(console_fixture_2j2) and on sqlite and a local Postgres.

1. "Products this week" on a brand. A brand's True Value has its own site as
   the `you` column, which no agent quotes, and build_products read only that
   column when it was there: every row was skipped and the Overview hid the
   block (FL12). A row now reads its `you` cell when that cell has quotes,
   else the retailer cells together. A store reads as before: its products
   on every surface are pinned to main's (fixtures/console/store_products_2j2.json).

2. Catalog stages for a GTIN-less row. FL12's Catalog said "Not measured" for
   its four feed rows with no GTIN and True Value showed them "not quoted",
   though the study asked about them. The generator does ask (case (a), not a
   generator gap): its brand mode keys a GTIN-less variant by supply's
   `sku:<sku>` and writes that as the question's variant_id. Both joins
   missed it: catalog_stages keyed a row by variant_id (a feed row has none)
   else its GTIN (none), and True Value keyed the read by its variant_ref
   (`feed_sku:<n>`) with the bare SKU as an alias, never `sku:<sku>`.
"""
import json
import os

import pytest

from app.services import console_parity as parity
from soa_shared import catalog_tiers as ct
from soa_shared.catalog_snapshot import build_snapshot, merge_merchant_record, merge_reads
from tests import console_fixture_2j2 as f2j2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2i8 import FIXTURES, _read
from tests.test_console_read_models import TOKEN_A, WS_TENANT, _encode, as_, http, upstream  # noqa: F401  (fixtures)

STORE_PRODUCTS = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'store_products_2j2.json')


def _brand(db):
    f2j2.load(db, _encode)
    return f2j2.CYCLE


def _get(http, endpoint, **params):
    as_('op')
    r = http.get(f'/api/console/{endpoint}', params={'org': 10, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _products(http, db, surface='all'):
    body = _get(http, 'overview', cycle=_brand(db))
    return {p['name']: p for p in body['by_surface'][surface]['products']}


# ═══ 1. Products this week on a brand ════════════════════════════════════

def test_the_brand_fixture_is_the_shape_it_says(http, db):
    tv = _get(http, 'true-value', cycle=_brand(db))
    assert tv['column_kind'] == 'retailer'
    assert [(c['id'], c['you']) for c in tv['columns']] == [('pampers.com', True), ('walmart.com', False),
                                                           ('amazon.com', False)]
    # no agent quotes the brand's own site: the cause
    assert all(not r['cells']['pampers.com']['quotes'] for r in tv['rows'])


def test_a_brand_s_products_read_its_retailer_cells_together(http, db):
    products = _products(http, db)
    gtin = [label for label, _sku, g, _p in f2j2.VARIANTS if g]
    assert set(gtin) <= set(products)
    row = products['Swaddlers NB 84']
    assert row['quoted'] == ('Amazon and Walmart $27.97, 5 of 12 runs (Gemini 2, Google AI Mode 1, Perplexity 2). '
                             'Amazon and Walmart $24.97, 3 of 12 runs (ChatGPT 2, Google AI Mode 1). '
                             'No price, 4 of 12 runs (Claude 2, Copilot 2)')
    assert row['live'] == ('$24.97 at walmart.com, our own fetch, Oct 19. '
                           '$27.97 at amazon.com, our own fetch, Oct 19')
    # the worst cell's status; the issue over every quote: Gemini and Perplexity at Walmart, ChatGPT at Amazon
    assert row['status'] == 'wrong' and row['cell_status'] == 'wrong'
    assert row['issue'] == 'Quoted a wrong price in 3 of 12 runs.' and row['wrong_runs'] == 3
    assert row['runs'] == 12 and row['read_across'] is True
    assert [(r['name'], r['runs'], r['quote'], r['live_price'], r['cell_status']) for r in row['retailers']] == [
        ('Walmart', 6, '$27.97', '$24.97', 'wrong'), ('Amazon', 6, '$24.97', '$27.97', 'wrong')]
    assert sum(g['runs'] for g in row['quote_groups']) == row['runs']


def test_each_surface_counts_its_own_quotes_across_retailers(http, db):
    body = _get(http, 'overview', cycle=_brand(db))
    rows = {s: {p['name']: p for p in v['products']} for s, v in body['by_surface'].items()}
    consumer = rows['consumer_ui']['Swaddlers NB 84']
    # AI Mode quotes each retailer's own price; Copilot another brand's product
    assert consumer['runs'] == 4 and consumer['status'] == 'exact' and consumer['wrong_runs'] == 0
    assert consumer['quoted'] == 'Walmart $24.97, 1 of 4 runs (Google AI Mode 1). Amazon $27.97, 1 of 4 runs ' \
                                 '(Google AI Mode 1). No price, 2 of 4 runs (Copilot 2)'
    assert rows['grounded_api']['Swaddlers NB 84']['runs'] == 8


def test_a_you_cell_with_quotes_is_read_alone():
    """A store's `you` column is the store: its cell decides, the other
    retailers' cells are not read across."""
    def cell(quotes, status):
        return {'quotes': quotes, 'by_surface': {'all': {'status': status, 'quoted': '$9.99'}}, 'live': '$9.99',
                'reference_source': 'record'}
    q = {'agent': 'chatgpt', 'surface': 'grounded_api', 'outcome': 'exact', 'stated': '9.99', 'run': 'run-1'}
    tv = {'retailer_columns': [{'id': 'shop.com', 'you': True}, {'id': 'walmart.com', 'you': False}],
          'rows': [{'product': 'P', 'sku': 'p', 'cells': {
              'shop.com': cell([q], 'exact'), 'walmart.com': cell([{**q, 'outcome': 'wrong', 'run': 'run-2'}], 'wrong')}}]}
    [row] = parity.build_products(tv, [], 'all', variant_of_run={}, reason_of_run={})
    assert row['retailer'] == 'shop.com' and row['status'] == 'exact' and row['runs'] == 1
    assert 'read_across' not in row


@pytest.mark.parametrize('name', ['ws', 'ws_two'])
def test_a_store_s_products_are_byte_identical_to_main(http, db, name):
    with open(STORE_PRODUCTS) as fh:
        pinned = json.load(fh)[name]
    body = _read(http, FIXTURES[name](db), 'overview')
    now = {s: v['products'] for s, v in body['by_surface'].items()}
    assert json.dumps(now, sort_keys=True) == json.dumps(pinned, sort_keys=True)


# ═══ 2. Catalog stages for a GTIN-less row ═══════════════════════════════

def _generated():
    snap = build_snapshot(f2j2.catalog(), merchants=[], incentives=None, merchant_slug=f2j2.MERCHANT)
    merge_merchant_record(snap, merchant=f2j2.TENANT_MERCHANT, retailers=f2j2.RETAILERS_RECORD, feed=f2j2.feed())
    merge_reads(snap, f2j2.reference_prices())
    return ct.build_catalog_accuracy(snap, category='Baby Care', persona='Value-Conscious Parent',
                                     study_pattern='brand_at_retail')


def test_the_generator_asks_about_every_gtin_less_variant_as_the_fixture_does():
    rows, report = _generated()
    asked = {(r['source_ref']['variant_id'], r['expected_answer']['attributed_to']) for r in rows}
    gtinless = {f2j2.variant_id(sku, gtin) for label, sku, gtin, _p in f2j2.VARIANTS if not gtin}
    assert gtinless == {'sku:PAM-ULTRA-120', 'sku:PAM-PURE-2-74', 'sku:PAM-AMORE-3-60', 'sku:PAM-CR-5-92'}
    assert {(v, d) for v in gtinless for d in f2j2.RETAILERS} <= asked
    assert report['skipped_no_retailer'] == [] and report['skipped_no_price'] == [] and len(rows) == 20
    # the fixture's questions are the generator's: the same variant ids at the same retailers
    fixture = {(q['source_ref']['variant_id'], q['expected_answer']['attributed_to'])
               for q in f2j2.build()['queries'] if q['tier'] == 'catalog_accuracy'}
    assert fixture == asked


def test_true_value_files_a_gtin_less_row_s_quotes_under_its_read(http, db):
    tv = _get(http, 'true-value', cycle=_brand(db))
    rows = {r['product']: r for r in tv['rows']}
    for label in f2j2.GTINLESS:
        cells = rows[label]['cells']
        assert len(cells['walmart.com']['quotes']) == 6 and len(cells['amazon.com']['quotes']) == 6, label
        assert cells['walmart.com']['quoted'] != '—' and cells['amazon.com']['quoted'] != '—', label
        assert not cells['pampers.com']['quotes']
    ultra = rows['Ultra']['cells']
    assert (ultra['walmart.com']['quoted'], ultra['walmart.com']['live']) == ('$25.97', '$22.97')
    assert len(tv['rows']) == len(f2j2.VARIANTS)       # no second row for the same variant


def test_the_overview_has_the_gtin_less_products_too(http, db):
    products = _products(http, db)
    assert set(f2j2.GTINLESS) <= set(products) and len(products) == 10
    assert products['Ultra']['runs'] == 12 and products['Ultra']['read_across'] is True


@pytest.fixture
def pampers_supply(upstream):
    tenant = {**WS_TENANT, 'merchants': WS_TENANT['merchants'] + [f2j2.TENANT_MERCHANT]}
    base = f'/api/truesync/merchants/{f2j2.MERCHANT}'
    upstream.answer('GET', '/api/truesync/tenant', body=tenant, token=TOKEN_A)
    upstream.answer('GET', f'{base}/feed', body=f2j2.feed(), token=TOKEN_A)
    upstream.answer('GET', f'{base}/feed/history', body={'merchant': f2j2.MERCHANT, 'versions': []}, token=TOKEN_A)
    upstream.answer('GET', f'{base}/reference', body={'rows': []}, token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/publications', body=[], token=TOKEN_A)
    return upstream


def test_catalog_stages_a_gtin_less_feed_row_measured(http, db, pampers_supply):
    _brand(db)
    body = _get(http, 'catalog', merchant=f2j2.MERCHANT)
    assert body['source'] == 'feed' and body['stage_cycle'] == f2j2.CYCLE
    by = {r['variant_label']: r for r in body['rows']}
    for label in f2j2.GTINLESS:
        row = by[label]
        assert row['gtin'] is None and row['key'] == row['variant_key'] and row['key'].startswith('sku:')
        assert row['stages'] == ['measured'], label
        # 4 of 6 agents quote a price at each retailer: exact ChatGPT and AI Mode at Walmart,
        # Gemini, Perplexity and AI Mode at Amazon
        assert (row['quoted_runs'], row['scored'], row['exact']) == (8, 8, 5), label
    assert all(r['stages'] == ['measured'] for r in body['rows'])
    ladder = {s['key']: s['products'] for s in body['stage_ladder']['stages']}
    assert ladder['not_measured'] == 0 and ladder['measured'] == 10


def test_catalog_row_keys_order():
    assert parity.catalog_row_keys({'variant_id': 'bum-balm-4oz', 'gtin': '012345678905'}) == \
        ['bum-balm-4oz', '00012345678905']
    assert parity.catalog_row_keys({'variant_key': 'sku:A-1', 'gtin': None, 'sku': 'A-1'}) == ['sku:A-1']
    assert parity.catalog_row_keys({'variant_key': '00037000863434', 'gtin14': '00037000863434',
                                    'gtin': '00037000863434', 'sku': 'S'}) == ['00037000863434', 'sku:S']
