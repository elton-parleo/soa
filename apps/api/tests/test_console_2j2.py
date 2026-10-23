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

3. The Prompts read model, GET /api/console/prompts?merchant= (console_prompts):
   the merchant's current study in sets, with the agents from the surfaces
   report.
"""
import json
import os

import pytest
from sqlalchemy import text

from app.services import console_parity as parity
from soa_shared import catalog_tiers as ct
from soa_shared.catalog_snapshot import build_snapshot, merge_merchant_record, merge_reads
from tests import console_fixture_2j2 as f2j2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2i8 import FIXTURES, _read
from tests.test_console_read_models import TOKEN_A, WS_TENANT, _encode, as_, http, upstream  # noqa: F401  (fixtures)

STORE_PRODUCTS = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'store_products_2j2.json')
#: the Prompts sample docs/console-read-models.md shows, for the console's fixtures
PROMPTS_SAMPLE = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'prompts_fl12_2j2.json')


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
    # AI Mode quotes each retailer's own price; Copilot another brand's product. 2N-1: the
    # status follows the issue ("Priced another brand's product in 2 of 4 runs"), never the cells'
    assert consumer['runs'] == 4 and consumer['status'] == 'wrong' and consumer['wrong_runs'] == 0
    assert consumer['issue_rule'] == 'product.other_brand'
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
    # 2L-3 adds each product's narrative beside the typed fields (null with SOA_NARRATIVES_ENABLED off)
    now = {s: [{k: v for k, v in p.items() if k != 'narrative'} for p in v['products']] for s, v in body['by_surface'].items()}
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
def pampers_tenant(upstream):
    tenant = {**WS_TENANT, 'merchants': WS_TENANT['merchants'] + [f2j2.TENANT_MERCHANT]}
    upstream.answer('GET', '/api/truesync/tenant', body=tenant, token=TOKEN_A)
    return upstream


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


# ═══ 3. The Prompts read model ═══════════════════════════════════════════

def _prompts(http, user='op', **params):
    as_(user)
    query = {'merchant': f2j2.MERCHANT, **({'org': 10} if user == 'op' else {}), **params}
    return http.get('/api/console/prompts', params=query)


def test_prompts_are_the_current_study_in_four_sets_on_six_agents(http, db, pampers_tenant):
    _brand(db)
    r = _prompts(http)
    assert r.status_code == 200, r.text
    body = r.json()
    # 2K-4 (B2): the study's own date beside its name (the fixture's job has no created_at)
    assert body['study'] == {'id': f2j2.STUDY, 'name': 'Wiggle & Snug full', 'created_at': None, 'created_at_local': None,
                             'timezone': 'America/Los_Angeles'} and body['cycle'] == f2j2.CYCLE
    assert body['headline'] == '88 prompts in 4 sets, 1 run each on 6 agents'
    assert (body['prompts'], body['set_count'], body['runs_per_question'], body['runs_per_question_source'],
            body['agents_on_last_cycle'], body['answers_per_cycle'], body['cadence']) == (88, 4, 1, 'cycle', 6, 528, None)
    assert [(s['tier'], s['name'], s['count'], s['answers_per_cycle']) for s in body['sets']] == [
        ('category_control', 'Category control', 51, 306), ('brand_direct', 'Brand-direct', 11, 66),
        ('catalog_accuracy', 'Catalog accuracy', 20, 120), ('value_incentives', 'Value & incentives', 6, 36)]
    assert sum(s['count'] for s in body['sets']) == body['prompts']
    catalog = body['sets'][2]
    assert catalog['examples'] == ['What does the Pampers Swaddlers NB 84 cost at walmart.com?',
                                   'What does the Pampers Swaddlers NB 84 cost at amazon.com?',
                                   'What does the Pampers Swaddlers S1 96 cost at walmart.com?']
    assert catalog['line'] == '20 prompts, 120 answers a cycle'
    assert all(len(s['examples']) == 3 for s in body['sets'])


def test_the_agents_are_the_surfaces_report_s_with_their_last_cycle(http, db, pampers_tenant):
    _brand(db)
    agents = _prompts(http).json()['agents']
    assert [a['id'] for a in agents] == ['chatgpt', 'gemini_grounded', 'aimode', 'perplexity', 'copilot', 'claude']
    assert [a['name'] for a in agents] == ['ChatGPT', 'Gemini', 'Google AI Mode', 'Perplexity', 'Copilot', 'Claude']
    by = {a['id']: a for a in agents}
    assert by['chatgpt']['method'] == 'API with search grounding' and by['aimode']['method'] == 'Consumer UI, logged out'
    # 87 of the 88 questions ran; AI Mode errored once with no answer
    assert (by['chatgpt']['last_status'], by['chatgpt']['last_runs'], by['chatgpt']['last_answered']) == ('answered', 87, 87)
    assert (by['aimode']['last_status'], by['aimode']['last_answered'], by['aimode']['last_errored']) == ('partial', 86, 1)


def test_runs_per_question_is_the_last_full_loop_request_s(http, db, pampers_tenant):
    _brand(db)
    with db.begin() as c:
        for rpq, at in ((2, '2026-10-18T10:00:00+00:00'), (3, '2026-10-19T10:00:00+00:00')):
            c.execute(text("INSERT INTO soa_full_loop_requests (organization_id, merchant_slug, study_type, platforms, "
                           "runs_per_query, status, created_at) VALUES (10, :m, :st, :p, :r, 'scored', :at)"),
                      {'m': f2j2.MERCHANT, 'st': f2j2.STUDY, 'p': '[]', 'r': rpq, 'at': at})
        c.execute(text("INSERT INTO soa_full_loop_requests (organization_id, merchant_slug, study_type, platforms, "
                       "runs_per_query, status, created_at) VALUES (10, :m, NULL, '[]', 5, 'reads_done', :at)"),
                  {'m': f2j2.MERCHANT, 'at': '2026-10-20T10:00:00+00:00'})   # reads-only: no study
    body = _prompts(http).json()
    assert (body['runs_per_question'], body['runs_per_question_source']) == (3, 'full_loop')
    assert body['headline'] == '88 prompts in 4 sets, 3 runs each on 6 agents'
    assert body['answers_per_cycle'] == 528      # questions x agents on the last cycle


def test_a_member_reads_their_own_merchant_s_prompts(http, db, pampers_tenant):
    _brand(db)
    assert _prompts(http, 'alice').json()['prompts'] == 88
    assert _prompts(http, 'alice', org=20).status_code == 403
    assert _prompts(http, merchant='not-ours').status_code == 404


def test_a_merchant_with_no_study_has_no_sets(http, db, pampers_tenant):
    body = _prompts(http).json()
    assert body['study'] is None and body['sets'] == [] and body['prompts'] == 0
    assert body['headline'] == '0 prompts in 0 sets'


def test_the_documented_sample_is_the_endpoint_s_response(http, db, pampers_tenant):
    _brand(db)
    with open(PROMPTS_SAMPLE) as fh:
        assert _prompts(http).json() == json.load(fh)
