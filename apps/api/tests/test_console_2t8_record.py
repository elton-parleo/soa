"""
2T-8 (B1, B2, B3): the Product record of a brand at retail, from the Oct 26
walk (org 12, Pampers, FL15). Each test quotes what the live console showed.

Inputs, each named where it is used:
  - the recorded pampers.com pages (supply #33's own brand_page.read,
    tests/fixtures/console/supply_2r1/brand-pages.json, PROVENANCE.md there);
  - the 2T-1 harness (2P-1's pair with #33's answers RECORDED), end to end;
  - FL15-shaped rows built here in supply's served shape (FL15's own are
    production reads this pass never makes), each saying so.
No model call, no production read.
"""
import copy
import json
import os

from app.services import console_manufacturer as manu
from app.services import console_product_record as pr
from app.services import console_read_models as rm
from tests import console_fixture_2r2 as f2r2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import TOKEN_A, http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_console_2t1_overview_truesync import _read, _shape

PAGES = json.load(open(os.path.join(f2r2.HERE, 'brand-pages.json')))
SWADDLERS = PAGES['swaddlers']['brand_page']['json_ld']


def _dump(name, body):
    """SOA_2T8_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2T8_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


# ── B1: a feed variant is compared with its own variant on the page ───────

def _first_variant_findings(variant, json_ld):
    """The before: supply's own-page findings as the live record showed them, every feed row against the
    ProductGroup's first variant (Preemie), the variant-level fields the markup does not carry read as absent."""
    first = json_ld['hasVariant'][0]
    out = []
    if variant.get('gtin') and pr._gtin14(variant['gtin']) != pr._gtin14(first.get('gtin13')):
        out.append({'finding': 'gtin_mismatch', 'expected': variant['gtin'], 'observed': first.get('gtin13')})
    out.append({'finding': 'name_differs', 'expected': variant['label'], 'observed': first.get('name')})
    out.append({'finding': 'brand_missing_on_page', 'expected': 'Pampers', 'observed': None})
    return out


def test_swaddlers_newborn_has_no_difference_with_its_own_variant():
    """Live: "GTIN · 037000749622 · Page shows 037000863403", "Name · Page shows Preemie", "Brand · Page shows not
    on the page" on every Swaddlers SKU. On the recorded Swaddlers page, Newborn 84 ct matches the Newborn variant
    by size and no field both sides carry differs."""
    nb = {'gtin': None, 'label': 'Newborn, 84 ct', 'count': 84, 'product_name': 'Pampers Swaddlers'}
    before = _first_variant_findings(nb, SWADDLERS)
    assert [(f['finding'], f['observed']) for f in before] == [('name_differs', 'Preemie'),
                                                               ('brand_missing_on_page', None)]
    got = pr.markup_differences(nb, SWADDLERS, brand='Pampers')
    assert (got['matched'], got['node']['name'], got['differences']) == ('size', 'Newborn', [])
    # the markup carries no pack count on a variant: "not in the markup", never a difference
    assert got['not_in_markup'] == ['count']


def test_an_eleven_digit_gtin_is_matched_after_normalisation():
    """DERIVED: the recorded Size 4 row with the GTIN written as 11 digits (the AMORE and Ultra markup's habit)."""
    s4 = {'gtin': '37000799818', 'label': 'Size 4', 'count': None, 'product_name': 'Pampers Swaddlers'}
    got = pr.markup_differences(s4, SWADDLERS, brand='Pampers')
    assert (got['matched'], got['node']['gtin13'], got['differences']) == ('gtin', '037000799818', [])


def test_a_difference_is_one_the_matching_variant_states():
    """FL15's Swaddlers Size 4 150 ct (GTIN 037000749622) against the recorded page, whose Size 4 variant states
    037000799818: matched by size, the GTIN is a difference, the size and line are not."""
    s4 = {'gtin': '037000749622', 'label': 'Size 4, 150 ct', 'count': 150, 'product_name': 'Pampers Swaddlers'}
    got = pr.markup_differences(s4, SWADDLERS, brand='Pampers')
    assert got['matched'] == 'size'
    assert got['differences'] == [{'field': 'gtin', 'record': '037000749622', 'page': '037000799818'}]
    # a line whose URL lands on another line's page: the page's line is named, as a difference
    ultra = {'gtin': None, 'label': 'Size 3, 180 ct', 'count': 180, 'product_name': 'Pampers Swaddlers Ultra Day + Night'}
    assert pr.markup_differences(ultra, SWADDLERS, brand='Pampers')['differences'] == [
        {'field': 'line', 'record': 'Pampers Swaddlers Ultra Day + Night', 'page': 'Pampers Swaddlers'}]


def test_the_record_reads_soa_s_comparison_not_supply_s_first_variant():
    """build_record, an own-page read carrying the ProductGroup and supply's first-variant findings (the live
    shape, DERIVED on the recorded page): the differences count was 2 on Newborn; it is 0."""
    listing = {'listing_id': 1, 'title': 'Pampers Swaddlers', 'brand': 'Pampers', 'product_id': 'feed:x',
               'variants': [{'variant_id': 'sku:nb', 'sku': 'nb', 'title': 'Newborn, 84 ct', 'count': 84}]}
    nb = {'gtin': None, 'label': 'Newborn, 84 ct'}
    row = {'variant_ref': 'sku:nb', 'role': 'own', 'retailer_domain': 'pampers.com', 'json_ld': SWADDLERS,
           'observed_at': '2026-10-24T02:00:00', 'reference_source': 'honest_fetch',
           'findings': _first_variant_findings(nb, SWADDLERS)}
    body = rm.build_record('pampers', listing, merchant_record={'kind': 'brand'}, publications=[], channels=[],
                           provenance=None, reference={'rows': [row]}, incentives=None)
    assert [f for f in body['fields'] if f.get('diff')] == []
    assert body['variants'][0]['status'] == 'Matches the page'
    # a page with no ProductGroup keeps supply's findings
    plain = {**row, 'json_ld': {'@type': 'Product', 'name': 'x'}}
    body = rm.build_record('pampers', listing, merchant_record={'kind': 'brand'}, publications=[], channels=[],
                           provenance=None, reference={'rows': [plain]}, incentives=None)
    assert len([f for f in body['fields'] if f.get('diff')]) == 2


# ── B2: /record per feed SKU ──────────────────────────────────────────────

def test_the_list_is_one_row_per_feed_sku_with_its_readback_state(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'record/list')
    _dump('record-list-2t8.json', body)
    feed = f2r2.body('feed')['rows']
    assert (body['mode'], len(body['products'])) == ('manufacturer', len(feed))
    rows = {p['sku']: p for p in body['products']}
    assert rows['sku_pg_pure_s1']['retired'] == {'successor': {'productName': 'Pampers AMORE',
                                                               'sku': 'sku_pg_amore_s1_132'}}
    assert rows['00037000833970']['sub'] == 'Size 4, 104 ct, 22 to 37 lb'
    # a SKU takes its line's chart, never "No chart" because its own row carries none
    assert rows['00037000799818']['sub'] == 'Size 4, 15 to 34 lb'
    assert {p['state'] for p in body['products']} <= {'agents_disagree', 'match', 'not_quoted'}
    bad = [p for p in body['products'] if p['state'] == 'agents_disagree']
    assert body['hero']['disagree'] == {'n': len(bad), 'of': len(feed)}
    k = max(p['disagree']['n'] for p in bad)
    tops = list(dict.fromkeys(p['line'] for p in bad if p['disagree']['n'] == k))
    assert body['hero']['sentence'] == (f"Agents contradict the record on {len(bad)} products this cycle. "
                                        f"{' and '.join(tops)} each have {k} agents disagreeing.")
    # the Gainable pool is the revenue model's (no sales entered on the pair: no dollars, never a $0)
    assert body['hero']['gainable']['value'] is None


def test_the_swaddlers_size_4_record_and_its_issues(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'record', product='00037000799818')
    _dump('record-2t8.json', body)
    fields = {f['k']: f for f in body['record']}
    assert list(fields)[:5] == ['Name on pampers.com', 'GTIN', 'Weight range', 'Claims', 'Price']
    assert fields['Name on pampers.com']['v'] == 'Pampers® Swaddlers™'
    assert (fields['GTIN']['v'], fields['GTIN']['mono'], fields['GTIN']['diff']) == ('037000799818', True, False)
    assert (fields['Weight range']['v'], fields['Weight range']['note']) == ('15 to 34 lb', 'pampers.com size chart, Oct 19')
    assert fields['Price']['v'] == 'Not set. Retailers price it'
    assert body['differences'] == []
    kinds = [i['kind'] for i in body['issues']]
    assert kinds == ['two_charts', 'retailers_wrong_range']
    assert body['issues'][0]['text'].startswith(
        'pampers.com rates Swaddlers Size 4 at 15 to 34 lb and Zzz Size 4 at 22 to 37 lb.')
    assert body['issues'][1]['text'] == 'Walmart says 22 to 37 lb, Target says 22 to 37 lb, Amazon says 22 to 37 lb.'
    assert body['issues_none'] is None
    assert [(s['channel'], s['word'], s['drift_word']) for s in body['surfaces']] == [
        ('schema_org', 'Held in preview', '2 agents disagree'),
        ('manufacturer_center', 'Held in preview', '2 agents disagree'), ('acp', 'Blocked', None)]
    assert [h['kind'] for h in body['history']] == ['compiled', 'verified', 'first_read']


def test_a_record_with_no_issue_says_so_in_brand_words(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'record', product='sku_pg_amore_s1_132')
    assert (body['issues'], body['issues_none']) == ([], 'None found on this record.')
    assert _read(http, 'record', product='nope', status=404)['detail'] == "product 'nope' is not in 'pampers-2r1''s record"


def _fl15_shelf(prices):
    """FL15-shaped retailer rows for Swaddlers Size 4 (DERIVED, supply's served row shape): Amazon read by our
    fetch at $49.77 stating 15 to 34 lb, Walmart read at $49.77 from $59.77 stating 16 to 28 lb, Target walled
    with an HTTP 435."""
    base = {'role': 'retailer', 'sku': None, 'gtin': '037000799818', 'variant_ref': 'feed_sku:5',
            'variant_label': 'Size 4', 'observed_at': '2026-10-24T14:00:00'}
    return prices + [
        {**base, 'retailer_domain': 'amazon.com', 'url': 'https://www.amazon.com/dp/B07DC8BR3B', 'method': 'json_ld',
         'price': '49.77', 'list_price': None, 'weight_range': {'min': 15, 'max': 34}, 'read_status': 'ok'},
        {**base, 'retailer_domain': 'walmart.com', 'url': 'https://www.walmart.com/ip/Pampers-Swaddlers/209107239',
         'method': 'regex', 'price': '49.77', 'list_price': '59.77', 'weight_range': {'min': 16, 'max': 28},
         'read_status': 'ok'},
        {**base, 'retailer_domain': 'target.com', 'url': 'https://www.target.com/p/-/A-12345678', 'method': 'none',
         'price': None, 'read_status': 'blocked', 'http_status': 435}]


def test_retailer_rows_variants_and_walls_on_fl15_s_shelf(http, db, upstream):
    _shape(db, http, upstream)
    prices = f2r2.retailer_prices()
    prices['prices'] = _fl15_shelf(prices['prices'])
    upstream.answer('GET', f'{f2r2.BASE}/retailer-prices', body=prices, token=TOKEN_A)
    body = _read(http, 'record', product='00037000799818')
    _dump('record-fl15-2t8.json', body)
    fields = {f['k']: f for f in body['record']}
    assert fields['Amazon, Oct 24']['v'] == '$49.77. Page says 15 to 34 lb'
    walmart = fields['Walmart, Oct 24']
    assert (walmart['v'], walmart['diff'], walmart['struck']) == ('$49.77, from $59.77. Page says 16 to 28 lb', True,
                                                                 '15 to 34 lb')
    assert fields['Target']['v'] == "Couldn't read. HTTP 435"
    assert fields['Last verified']['v'] == 'Oct 24, 2026'
    assert [(v['id'], v['retailer'], v['price'], v['note'], v['tone']) for v in body['variants']] == [
        ('037000799818', 'Amazon', '$49.77', 'Page says 15 to 34 lb', 'ok'),
        ('037000799818', 'Target', None, 'Not read · walled, HTTP 435', 'neu'),
        ('037000799818', 'Walmart', '$49.77', 'Page says 16 to 28 lb', 'bad')]
    ranges = next(i for i in body['issues'] if i['kind'] == 'retailers_wrong_range')
    assert ranges['text'].endswith(' Amazon matches pampers.com at 15 to 34 lb.')
    assert body['history'][0]['kind'] == 'compiled' and body['history_all'][0]['text'] in ('Amazon read', 'Walmart read')


def test_issue_generators_on_derived_markup():
    """DERIVED on the recorded Swaddlers page: one GTIN on two packs (an Offer per retailer, the shape the demo's
    pampers.com carries), the markup's Size 5 to 8 carrying Cruisers 360's weights, an 11-digit GTIN flag."""
    ld = copy.deepcopy(SWADDLERS)
    s4 = next(n for n in ld['hasVariant'] if n['size'] == '4')
    s4['offers'] = [{'@type': 'Offer', 'seller': {'name': 'Amazon'}, 'name': 'Size 4, 100 Count'},
                    {'@type': 'Offer', 'seller': {'name': 'Walmart'}, 'name': 'Size 4, 150 Count'}]
    for n, desc in zip([n for n in ld['hasVariant'] if n['size'] in ('5', '6', '7', '8')],
                       ('27-35 lbs', '35-45 lbs', '41-50 lbs', '46-55 lbs')):
        n['description'] = desc
    charts = {'swaddlers': [{'size': '4', 'min': 15, 'max': 34}, {'size': '5', 'min': 20, 'max': 37},
                            {'size': '6', 'min': 23, 'max': 44}, {'size': '7', 'min': 26, 'max': 50},
                            {'size': '8', 'min': 30, 'max': None}],
              'cruisers_360': [{'size': '4', 'min': 22, 'max': 37}, {'size': '5', 'min': 27, 'max': 35},
                               {'size': '6', 'min': 35, 'max': 45}, {'size': '7', 'min': 41, 'max': 50},
                               {'size': '8', 'min': 46, 'max': 55}]}
    v = {'gtin': '037000799818', 'label': 'Size 4, 150 ct', 'count': 150, 'product_name': 'Pampers Swaddlers'}
    feed = [{'product_name': 'Pampers Swaddlers', 'variant_label': 'Size 4'},
            {'product_name': 'Pampers Cruisers 360', 'variant_label': 'Size 4'}]
    flags = [{'where': 'feed', 'was': '37000799818', 'now': '037000799818', 'digits': 11, 'line': 'Swaddlers'}]
    issues = pr.build_issues({**v, 'gtin': '37000799818'}, page={'json_ld': ld}, charts=charts, feed_rows=feed,
                             brand='Pampers', domain='pampers.com', attribute_answers=[], drift=[], shelf_rows=[],
                             flags=flags, chart_weight='15 to 34 lb')
    by = {i['title']: i['text'] for i in issues}
    assert by['One GTIN for two packs'] == "pampers.com maps 37000799818 to Amazon's 100 ct and Walmart's 150 ct."
    assert by['A GTIN with 11 digits'] == ('The feed gives 37000799818 for Swaddlers Size 4, which drops its leading '
                                           'zero: 037000799818.')
    assert by['Markup borrows another line'] == ('The Swaddlers page markup lists sizes 5 to 8 with Cruisers 360 '
                                                  'weights, against its own size chart.')
    assert by['Two Size 4 charts'] == 'pampers.com rates Swaddlers Size 4 at 15 to 34 lb and Cruisers 360 Size 4 at 22 to 37 lb.'
    # the markup's offers name the pack the GTIN is also mapped to, on the record's GTIN row
    rows = pr.record_rows(v, page={'json_ld': ld}, shelf_rows=[], retailers=[], own={'pampers.com'},
                          domain='pampers.com', chart=charts['swaddlers'], deals=None, drift=[], club_lines=[],
                          brand='Pampers', markup=pr.markup_differences(v, ld, brand='Pampers'))
    assert next(r for r in rows if r['k'] == 'GTIN')['note'] == 'pampers.com also maps it to an Amazon 100 ct pack'
    assert next(r for r in rows if r['k'].startswith('Size 4 packs'))['v'] == '100 ct Amazon, 150 ct Walmart'


def test_a_seller_record_is_unchanged(http, db, upstream):
    """A merchant not in manufacturer mode reads 2C-1's record list, as before."""
    from tests.test_console_2r2_manufacturer import WS_TENANT
    _shape(db, http, upstream)
    upstream.answer('GET', '/api/truesync/tenant', body=WS_TENANT, token=TOKEN_A)
    body = _read(http, 'record/list', merchant=f2r2.PAIR_SLUG)
    assert 'hero' not in body and 'mode' not in body


# ── B3: the preview counts SKUs, the GTIN rows collapse per line ──────────

def test_the_gtin_rows_collapse_to_one_line_per_line():
    """DERIVED, FL15's markup: Swaddlers Ultra's nine sizes and AMORE's eight each drop the leading zero."""
    rows = [{'field': f"swaddlers_ultra.size_{i}.gtin (markup)", 'was': f"3077209{i:04d}", 'now': f"03077209{i:04d}",
             'prov': 'parleo', 'kind': 'gtin', 'where': 'markup', 'line': 'Swaddlers Ultra', 'digits': 11}
            for i in range(9)]
    rows += [{'field': f"amore.size_{i}.gtin (markup)", 'was': f"3077224{i:04d}", 'now': f"03077224{i:04d}",
              'prov': 'parleo', 'kind': 'gtin', 'where': 'markup', 'line': 'AMORE', 'digits': 11} for i in range(8)]
    weight = {'field': 'zzz.size_4.weight (markup)', 'was': '15 to 34 lb', 'now': '22 to 37 lb', 'kind': 'markup'}
    diff, line = manu.collapse_gtin_rows([weight] + rows)
    assert line == 'Swaddlers Ultra: 9 sizes drop the leading zero · AMORE: 8'
    assert [(r['field'], r['was']) for r in diff] == [
        ('zzz.size_4.weight (markup)', '15 to 34 lb'),
        ('swaddlers_ultra.gtin (markup)', '9 sizes drop the leading zero'),
        ('amore.gtin (markup)', '8 sizes drop the leading zero')]


def test_publishing_serves_the_sku_count_and_both_diffs(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'publishing')
    _dump('publishing-2t8.json', body)
    assert (body['preview']['title'], body['preview']['skus'], body['preview']['records']) == (
        'Six Pampers records, Manufacturer Center first', 6, 4)
    assert body['diff'] == body['diff_all'] and body['gtin_line'] is None   # #33's GTINs are all well formed
    ts = _read(http, 'truesync')
    assert not {'diff', 'diff_all', 'gtin_line'} & set(ts)
