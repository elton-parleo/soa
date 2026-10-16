"""
2I B2: a brand's catalog questions come from the newest retailer-prices read.
One question per variant x retailer page read, naming the retailer; the
expected answer is the page's price as read, none for a page not read yet.
The brand is the Wiggle & Snug brand in supply's shapes
(tests/fixtures/console/supply_ws_brand_2i.json, README.md 2I). Every HTTP
test runs on sqlite and on a local Postgres (test_console_2c3a's db fixture).
"""
import copy
import filecmp
import json
import os

import pytest

from soa_shared import catalog_tiers as ct
from soa_shared import expected_answers as ea
from soa_shared.catalog_snapshot import build_snapshot, merge_merchant_record, merge_reads, price_source
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import (  # noqa: F401  (fixtures)
    BRANDCO_TENANT, TOKEN_A, TOKEN_B, _fixture, as_, http, upstream,
)
from tests.test_console_studies import studies_db  # noqa: F401  (fixture)

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, '..', '..', '..')
WSB = _fixture('supply_ws_brand_2i.json')
TENANT_2H = _fixture('supply_tenant_ws_2h.json')
RETAILERS = _fixture('supply_retailers_ws_2h.json')
BRAND = 'wiggle-and-snug-brand'
BASE = f'/api/truesync/merchants/{BRAND}'
TIERS_ON = {'brand_direct': True, 'catalog_accuracy': True, 'value_incentives': True, 'category_control': False}
UNREAD = ('WS-SFD-3-84', 'WS-SFO-6-42')


def prices(unread=(), none=False):
    """The recorded read, with some trueshopstore.com pages not read yet:
    the row supply serves for a page with no read (prices.py `_row`)."""
    payload = copy.deepcopy(WSB['retailer_prices'])
    for row in payload['prices']:
        if row['role'] == 'retailer' and (none or row['sku'] in unread):
            row.update(price=None, member_price=None, list_price=None, currency=None, observed_at=None,
                       reference_source=None, method=None, read_status=None, verifiable=False,
                       unverifiable_reason='not read yet', reference_read_id=None, reference_run_id=None)
    return payload


def brand_snapshot(payload):
    snap = build_snapshot(WSB['catalog'], merchants=[], incentives=WSB['incentives'], merchant_slug=BRAND)
    record = next(m for m in TENANT_2H['merchants'] if m['slug'] == BRAND)
    merge_merchant_record(snap, merchant=record, retailers=RETAILERS[BRAND], feed=WSB['feed'])
    return merge_reads(snap, payload)


def accuracy(snap):
    return ct.build_catalog_accuracy(snap, category='Baby Care', persona='Value-Conscious Parent',
                                     study_pattern='brand_at_retail')


def test_the_fixture_is_the_shape_it_says():
    rows = WSB['retailer_prices']['prices']
    assert sum(len(l['variants']) for l in WSB['catalog']['listings']) == 19
    assert [r['role'] for r in rows].count('retailer') == 19 and [r['role'] for r in rows].count('own') == 19
    assert all(v['variant_id'].startswith('sku:') and v['list_price'] is None
               for l in WSB['catalog']['listings'] for v in l['variants'])


# ═══ the questions ═══════════════════════════════════════════════════════
def test_nineteen_read_pages_give_nineteen_questions_each_with_its_read_price():
    snap = brand_snapshot(prices())
    rows, report = accuracy(snap)
    assert len(rows) == 19 and report['skipped_no_price'] == []
    assert rows[0]['query_text'] == \
        'What does the Wiggle & Snug Snug-Fit Diapers Size 1 — Small Pack (96 ct) cost at trueshopstore.com?'
    assert all(r['query_text'].endswith(' cost at trueshopstore.com?') for r in rows)
    by_sku = {r['sku']: r for r in WSB['retailer_prices']['prices'] if r['role'] == 'retailer'}
    for row in rows:
        exp = row['expected_answer']
        assert exp['type'] == 'price' and exp['attributed_to'] == 'trueshopstore.com'
        sku = row['source_ref']['variant_id'].split(':', 1)[1]
        assert exp['amount'] == ea.normalize_money(by_sku[sku]['price'])
        assert ea.validate(exp) is exp
        assert ct.retailers_outside_list(row['query_text'], snap) == []
    assert report['price_source'] == [{'domain': 'trueshopstore.com', 'read_at': '2026-10-14T17:01:19+00:00',
                                       'read_count': 19, 'unread_count': 0}]


def test_two_pages_not_read_still_ask_their_question_with_no_amount():
    rows, report = accuracy(brand_snapshot(prices(unread=UNREAD)))
    assert len(rows) == 19
    amounts = [r['expected_answer']['amount'] for r in rows]
    assert sum(a is not None for a in amounts) == 17
    for row in rows:
        if row['expected_answer']['amount'] is None:
            assert ea.validate(row['expected_answer']) is row['expected_answer']
            assert ea.describe(row['expected_answer']) == 'the price at trueshopstore.com, as the page reads'
    assert report['price_source'][0]['read_count'] == 17 and report['price_source'][0]['unread_count'] == 2
    assert sorted(report['unread_pages']) == [f'sku:{s}@trueshopstore.com' for s in sorted(UNREAD)]


def test_no_page_read_gives_no_price_question():
    snap = brand_snapshot(prices(none=True))
    rows, report = accuracy(snap)
    assert rows == [] and report['price_source'] == [] and price_source(snap) == []
    assert 'no pages read yet' in report['unavailable']
    assert ct.expected_nulls(snap, 'catalog_accuracy').startswith('None asked yet: no retailer page has been read.')


def test_own_and_comparison_pages_are_never_asked_about():
    payload = prices()
    payload['prices'].append({**payload['prices'][1], 'retailer_domain': 'rival.example', 'role': 'comparison'})
    snap = brand_snapshot(payload)
    assert {r.domain for reads in snap.reads.values() for r in reads} == {'trueshopstore.com'}


def test_a_failed_read_keeps_the_feed_price_path():
    """reads None (a failed read): the 2B path, which for this feed (no
    price) skips every variant, as before 2I."""
    snap = brand_snapshot(None)
    rows, report = accuracy(snap)
    assert rows == [] and len(report['skipped_no_price']) == 19 and 'price_source' not in report


# ═══ seller byte-identical ═══════════════════════════════════════════════
def test_a_sellers_questions_are_unchanged_by_reads():
    with open(os.path.join(ROOT, 'apps', 'pipeline', 'tests', 'fixtures', 'merchant_records', 'external_seller.json')) as fh:
        rec = json.load(fh)

    def seller(with_reads):
        snap = build_snapshot(rec['catalog'], merchants=rec['merchants'])
        merge_merchant_record(snap, merchant=rec['tenant_merchant'], retailers=rec['retailers'], feed=rec['feed'])
        if with_reads:
            snap.reads = {}
        return snap
    before, after = accuracy(seller(False)), accuracy(seller(True))
    assert json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True)
    assert before[0], 'the seller fixture asks questions'


# ═══ the three expected_answers copies ═══════════════════════════════════
def test_the_three_expected_answers_copies_are_identical():
    api = os.path.join(ROOT, 'apps', 'api', 'soa_shared', 'expected_answers.py')
    for other in (os.path.join(ROOT, 'apps', 'pipeline', 'soa_shared', 'expected_answers.py'),
                  os.path.join(ROOT, 'packages', 'shared', 'soa_shared', 'expected_answers.py')):
        assert filecmp.cmp(api, other, shallow=False), other


def test_an_amount_is_only_optional_when_the_page_is_named():
    with pytest.raises(Exception):
        ea.price(None)
    assert ea.price(None, attributed_to='trueshopstore.com')['amount'] is None


# ═══ the preview, over HTTP ══════════════════════════════════════════════
@pytest.fixture
def brand_supply(upstream):
    upstream.answer('GET', '/api/truesync/tenant', body=TENANT_2H, token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/tenant', body=BRANDCO_TENANT, token=TOKEN_B)
    upstream.answer('GET', f'{BASE}/retailers', body=RETAILERS[BRAND], token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/catalog', body=WSB['catalog'], token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/merchants', body=[], token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/incentives', body=WSB['incentives'], token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/feed', body=WSB['feed'], token=TOKEN_A)
    return upstream


def preview(http, upstream, payload):
    upstream.answer('GET', f'{BASE}/retailer-prices', body=payload, token=TOKEN_A)
    as_('op')
    r = http.post('/api/console/studies/preview', params={'org': 10},
                  json={'merchant': BRAND, 'tiers': TIERS_ON, 'stage_total': 50})
    assert r.status_code == 200, r.text
    return r.json()['tiers']


@pytest.mark.parametrize('payload, count, amounts, source', [
    (prices(), 19, 19, [('trueshopstore.com', 19, 0)]),
    (prices(unread=UNREAD), 19, 17, [('trueshopstore.com', 17, 2)]),
    (prices(none=True), 0, 0, []),
])
def test_the_preview_names_its_price_source(http, studies_db, brand_supply, payload, count, amounts, source):
    tiers = preview(http, brand_supply, payload)
    acc = tiers['catalog_accuracy']
    assert acc['count'] == count
    assert sum(q['expected_answer']['amount'] is not None for q in acc['questions']) == amounts
    assert [(s['domain'], s['read_count'], s['unread_count']) for s in acc['price_source']] == source
    assert acc['skipped_no_price'] == []
    chips = [q['expected'][0] for q in acc['questions']]
    assert chips.count('Expected: the price at trueshopstore.com, as read') == count - amounts
    value = tiers['value_incentives']
    assert (value['count'], value['note']) == (0, "no offers of the brand's own")
