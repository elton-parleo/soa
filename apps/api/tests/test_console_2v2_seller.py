"""
2V-2 (B): an externally hosted seller (supply's `mode` seller_external).

On 2U-2's harness with supply's answers RECORDED from parleo-supply-app on
the Petco fixture (tests/fixtures/console/supply_2v4/, PROVENANCE.md there):
four SKUs, Autoship with Purina's ladder, Perks Premier, NexGard PLUS Rx;
rules s1-s5 on and approved, s6 waiting; every channel compiled and held,
mcp published and read back. The recording's merchant is `petco`; it is
served as the harness's `pampers-2r1` (`_rename`), so 2P-1's pair and its
cycles read it. The pair's answers are about diapers, so every count on
them is a count of answers that never priced a Petco SKU.
"""
import json
import os

from tests import console_fixture_2r2 as f2r2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import _pair, f2p1
from tests.test_console_read_models import TOKEN_A, as_, http, upstream  # noqa: F401  (pytest fixtures)

SLUG = f2r2.SLUG
RECORDED_SLUG = 'petco'
#: 2V-4: re-recorded from parleo-supply-app main at 13c9c80 (2V-1 and 2V-2 merged; supply_2v4/PROVENANCE.md)
HERE = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'supply_2v4')


def _rename(value):
    return json.loads(json.dumps(value).replace(f'feed:{RECORDED_SLUG}:', f'feed:{SLUG}:')
                      .replace(f'"{RECORDED_SLUG}"', f'"{SLUG}"').replace(f'merchant={RECORDED_SLUG}', f'merchant={SLUG}'))


def recorded(name):
    with open(os.path.join(HERE, f'{name}.json')) as fh:
        return _rename(json.load(fh)['body'])


def _shape(db, http, upstream, *, rules='rules', tenant='tenant-held', publications='publications-held'):
    _pair(db, http, upstream)
    f2r2.retag(db)
    f2r2.alias(upstream)
    f2r2.answer(upstream)
    base = f2r2.BASE
    upstream.answer('GET', f'{base}/rules', body=recorded(rules), token=TOKEN_A)
    upstream.answer('GET', f'{base}/price-paths', body=recorded('price-paths'), token=TOKEN_A)
    upstream.answer('GET', f'{base}/incentives/owned', body=recorded('incentives-owned'), token=TOKEN_A)
    upstream.answer('GET', f'{base}/feed', body=recorded('feed'), token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/tenant', body=recorded(tenant), token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/publications', body=recorded(publications), token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/channels', body=recorded('channels'), token=TOKEN_A)
    upstream.answer('POST', f'{base}/publish', body=recorded('publish'), token=TOKEN_A)
    upstream.answer('POST', f'{base}/publications/sent', body=recorded('sent'), token=TOKEN_A)
    upstream.answer('PUT', f'{base}/rules/s6', body=recorded('rules'), token=TOKEN_A)


def _read(http, endpoint, status=200, **params):
    as_('op')
    r = http.get(f'/api/console/{endpoint}', params={'merchant': SLUG, 'org': 10, **params})
    assert r.status_code == status, r.text
    return r.json()


def _dump(name, body):
    """SOA_2V2_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2V2_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


def _cycle(http):
    return _read(http, 'truesync').get('cycle') or 'FL15-2026-10-21'


# ─── Rules and Approvals: the seller's set ────────────────────────────────

def test_rules_are_the_seller_set_in_supplys_words(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'rules')
    _dump('rules-2v2.json', body)
    assert body['mode'] == 'seller_external'
    assert [r['id'] for r in body['rules']] == ['s1', 's2', 's3', 's4', 's5', 's6']
    s1 = body['rules'][0]
    assert s1['name'] == 'Publish first-order Autoship prices' and s1['on'] is True and s1['approval'] == 'approved'
    assert [a['name'] for a in s1['audience']] == ['Verified shopping agents', 'Unverified bots']
    assert body['rules'][5]['approval'] == 'needs_approval' and body['rules'][5]['on'] is False
    labels = [b['label'] for b in body['backtest']]
    assert labels == ['Price questions where Petco is cheapest and named so', 'Answers quoting a retired program name',
                      'Member prices visible to public agents']
    assert body['backtest'][2]['before'] == '0' and body['backtest'][2]['after'] == '0'   # s2 is on


def test_approvals_list_the_seller_rules_and_the_held_release(http, db, upstream):
    _shape(db, http, upstream, rules='rules-seed')
    body = _read(http, 'approvals')
    _dump('approvals-2v2-seed.json', body)
    codes = [r['code'] for r in body['requests']]
    assert codes[0] == 's1' and 'release' in codes
    release = next(r for r in body['requests'] if r['code'] == 'release')
    assert release['title'] == '4 Petco SKUs, held for Petco\'s team' and release['state'] == 'held'
    assert body['signed'] == []
    approved = _read(http, 'approvals')  # rules-seed: nothing signed
    assert approved['summary']['waiting'] >= 1


def test_the_approved_rules_read_as_signed(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'approvals')
    _dump('approvals-2v2.json', body)
    assert [r['code'] for r in body['signed']] == ['s1', 's2', 's3', 's4', 's5']


# ─── Publishing, TrueSync, the Overview card ─────────────────────────────

def test_publishing_shows_eight_channel_states_for_an_external_seller(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'publishing')
    _dump('publishing-2v2.json', body)
    assert body['mode'] == 'seller_external'
    states = {s['channel']: s['status'] for s in body['surfaces']}
    assert states == {'merchant_center': 'held', 'ucp_uip': 'held', 'acp': 'held', 'schema_org': 'held', 'mcp': 'live',
                      'deals_api': 'held', 'deal_directory': 'held', 'manufacturer_center': 'not_for_seller'}
    gmc = body['surfaces'][0]
    assert gmc['name'] == 'Google Merchant Center' and 'sale_price' in gmc['fields'] and 'price' in gmc['fields']
    diff = {d['field']: d for d in body['diff']}
    assert diff['first_order_price']['now'] == '46.79' and diff['first_order_price']['prov'] == 'brand'
    assert diff['first_order_rule']['now'] == '40% off, ends 2026-10-31'
    assert diff['ongoing_price']['now'] == '74.09'
    assert diff['program_name'] == {'field': 'program_name', 'was': 'Vital Care', 'now': 'Petco Perks', 'prov': 'retail'}
    assert 'member_price' not in diff   # s2 on: the held record carries no member price
    assert body['preview']['title'] == '4 Petco SKUs, 7 surfaces'
    assert {a['channel'] for a in body['artifacts']} >= {'merchant_center', 'schema_org', 'acp', 'deals_api'}


def test_mark_as_sent_records_the_sellers_statement(http, db, upstream):
    _shape(db, http, upstream)
    as_('op')
    r = http.post('/api/console/publishing/sent', params={'merchant': SLUG, 'org': 10},
                  json={'channel': 'merchant_center', 'sent_at': '2026-10-30T15:20:00Z', 'stated_by': 'Gabe L.'})   # after the 2V-4 recording's compile
    assert r.status_code == 200, r.text
    sent = [c for c in upstream.calls if c['method'] == 'POST' and c['path'].endswith('/publications/sent')]
    assert sent and sent[-1]['json']['stated_by'] == 'Gabe L.'
    upstream.answer('GET', '/api/truesync/tenant', body=recorded('tenant-sent'), token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/publications', body=recorded('publications-sent'), token=TOKEN_A)
    from app.services import console_cache
    console_cache.clear()
    body = _read(http, 'publishing')
    _dump('publishing-2v2-sent.json', body)
    gmc = next(s for s in body['surfaces'] if s['channel'] == 'merchant_center')
    assert gmc['sent'] and gmc['last'].startswith('Compiled ') and ', sent ' in gmc['last']


def test_truesync_carries_the_release_card(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'truesync')
    _dump('truesync-2v2.json', body)
    assert body['mode'] == 'seller_external'
    release = body['release']
    assert release['state'] == 'held' and release['held'] == 6
    assert release['mcp']['acceptance'] == 'approved' and release['mcp']['verified'] == '4/4'
    assert len(release['surfaces']) == 8


def test_the_overview_truesync_card_reads_the_release(http, db, upstream):
    _shape(db, http, upstream)
    as_('op')
    r = http.get('/api/console/overview', params={'merchant': SLUG, 'org': 10, 'cycle': f2p1.CYCLE_2})
    assert r.status_code == 200, r.text
    card = r.json().get('truesync_card')
    _dump('overview-2v2.json', r.json())
    assert card and card['mode'] == 'seller_external' and card['held'] == 6


# ─── Fix queue ────────────────────────────────────────────────────────────

def test_the_fix_queue_derives_first_order_prices_while_s1_waits(http, db, upstream):
    _shape(db, http, upstream, rules='rules-seed')
    body = _read(http, 'fixes')
    _dump('fixes-2v2-seed.json', body)
    ids = [f['id'] for f in body['fixes']]
    assert ids[0] == 'first_order' and 'release' in ids
    first = body['fixes'][0]
    assert first['title'] == 'Publish first-order Autoship prices on 4 SKUs'
    assert first['gate'] == 's1' and first['status'] == 'needs_decision'
    assert first['detail'].startswith('2 funded by a brand, 1 standard first-order, 1 Rx held by rule.')


def test_with_s1_on_and_approved_no_first_order_fix(http, db, upstream):
    _shape(db, http, upstream)
    ids = [f['id'] for f in _read(http, 'fixes')['fixes']]
    assert 'first_order' not in ids


def test_a_retired_program_name_in_answers_is_a_fix_while_s4_is_off():
    from app.services import console_seller as cs
    loyalty = {'name': 'Petco Perks', 'former_names': ['Vital Care', 'Repeat Delivery']}
    answers = [{'text': 'Petco offers Vital Care savings on repeat orders', 'agent': 'gemini'},
               {'text': 'Petco Perks Premier is $24.99 a month', 'agent': 'chatgpt'}]
    rules = [{'code': 's4', 'on': False, 'approval': 'needs_approval'}]
    body = cs.build_fixes(rules=rules, paths=[], answers=answers, price_answers=[], loyalty=loyalty, pubs=[],
                          name='Petco', program='Autoship')
    (fix,) = body['fixes']
    assert fix['id'] == 'retired_name' and fix['gate'] == 's4'
    assert fix['title'] == 'Fix "Vital Care" copy'   # 2V-4 (B5): the demo's copy fix
    assert fix['detail'] == '1 of 2 answers this cycle still said Vital Care. The program is Petco Perks.'
    rules = [{'code': 's4', 'on': True, 'approval': 'approved'}]
    assert cs.build_fixes(rules=rules, paths=[], answers=answers, price_answers=[], loyalty=loyalty, pubs=[],
                          name='Petco', program='Autoship')['fixes'] == []


# ─── True Value, Prove, the Product record ────────────────────────────────

def test_true_value_reads_the_price_path(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'true-value', cycle=f2p1.CYCLE_2)
    _dump('true-value-2v2.json', body)
    assert body['mode'] == 'seller_external'
    assert body['program_lines']['sku:2579466']['line'] == 'First Autoship $46.79 (Purina ladder). Quoted by 0 of 0 agents.'
    ladder = body['ladder']
    assert ladder['title'] == "Purina's Autoship ladder at Petco"
    assert ladder['sub'].endswith('Funded by Purina, ends Oct 31.')
    assert [(s['label'], s['value']) for s in ladder['steps']] == [
        ('List', '$77.99'), ('1st order, 40%', '$46.79'), ('2nd order, 20%', '$62.39'), ('3rd order, 10%', '$70.19'),
        ('Ongoing, 5%', '$74.09'), ('Perks Premier, 10% off, Premier members only', '$70.19')]   # 2V-5 (V3): to member
    receipt = {r['k']: r for r in body['receipt']['rows']}
    assert receipt['First Autoship order']['v'] == '$46.79'
    assert receipt['Purina ladder, first order 40% off']['v'] == '-$31.20'
    assert receipt['Perks Premier, 10% off, Premier members only']['tag'] == 'Member, not combinable'


def test_prove_lists_the_funded_offers(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'prove', cycle=f2p1.CYCLE_2)
    _dump('prove-2v2.json', body)
    assert body['mode'] == 'seller_external' and body['title'] == 'Funded offers'
    (row,) = body['rows']
    assert row['title'] == 'Purina Autoship ladder' and row['funded_by'] == 'purina'
    assert row['detail'] == '40% off the 1st, 20% off the 2nd, 10% off the 3rd. Ends Oct 31.'
    assert row['value'] == '$31.20 on the 30 lb'
    assert body['aside']['kick'] == 'Purina partner seat'


def test_the_product_record_states_the_price_path(http, db, upstream):
    _shape(db, http, upstream)
    listing = _read(http, 'record/list')
    _dump('record-list-2v2.json', listing)
    assert [p['status'] for p in listing['products']] == ['Ladder', 'Ladder', 'Standard first order', 'Rx, list price']
    body = _read(http, 'record', product='2579466')
    _dump('record-2v2.json', body)
    fields = {f['k']: f for f in body['fields']}
    assert fields['List price']['v'] == '$77.99'
    assert fields['First Autoship order']['v'] == '$46.79' and fields['First Autoship order']['prov'] == 'brand'
    assert fields['Second and third orders']['v'] == '$62.39, $70.19'
    assert fields['Funded by']['v'] == 'Purina' and fields['Funded by']['note'] == 'Ladder ends Oct 31'
    assert fields['Rx']['v'] == 'No'
    rx = {f['k']: f for f in _read(http, 'record', product='3879911')['fields']}
    assert rx['Rx']['v'] == 'Yes'


def test_a_brand_at_retail_is_unchanged(http, db, upstream):
    """2U-5's recorded Pampers shape still reads manufacturer mode."""
    from tests.test_console_2u5 import _shape as brand_shape
    brand_shape(db, http, upstream)
    assert _read(http, 'publishing')['mode'] == 'manufacturer'
    assert _read(http, 'rules')['mode'] == 'manufacturer'
