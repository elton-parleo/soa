"""
2V-4: retail mode, an external seller's reading of what brand mode has.

On 2V-2's harness (tests/test_console_2v2_seller.py: 2U-2's harness, the
2P-1 pair, the recording served as `pampers-2r1`) with supply's answers
RE-RECORDED from parleo-supply-app `main` at 13c9c80 (2V-1 and 2V-2 merged;
tests/fixtures/console/supply_2v4/PROVENANCE.md). The pair's answers are
about diapers, so every count of answers about a Petco SKU is 0; the
builders' counting is tested on answers written here, said so.
"""
import json
import os

import pytest

from app.services import console_retail as rt
from app.services import console_seller as cs
from tests import test_console_2v2_seller as t2v2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import f2p1
from tests.test_console_read_models import TOKEN_A, as_, http, upstream  # noqa: F401  (pytest fixtures)

SLUG = t2v2.SLUG


def _dump(name, body):
    """SOA_2V4_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2V4_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


def _shape(db, http, upstream, **kw):
    t2v2._shape(db, http, upstream, **kw)


def _read(http, endpoint, **params):
    return t2v2._read(http, endpoint, **params)


def _rules(upstream, name):
    """Serve supply's /rules as recorded under `name` (rules-seed: before any rule is touched)."""
    from app.services import console_cache
    upstream.answer('GET', f'{t2v2.f2r2.BASE}/rules', body=t2v2.recorded(name), token=TOKEN_A)
    console_cache.clear()


# ─── B1: the one gate ─────────────────────────────────────────────────────

def test_the_gate_is_hosting_external_either_kind():
    seller = {'slug': 'petco', 'kind': 'seller', 'hosting': 'external', 'mode': 'seller_external'}
    brand = {'slug': 'pampers', 'kind': 'brand', 'hosting': 'external', 'mode': 'manufacturer'}
    hosted = {'slug': 'wiggle-and-snug', 'kind': 'seller', 'hosting': 'parleo', 'mode': 'seller'}
    before = {'slug': 'wiggle-and-snug-brand', 'kind': 'brand', 'hosting': 'external', 'mode': None}
    assert cs.external_kind(seller) == 'seller' and cs.external_kind(brand) == 'brand'
    assert not cs.is_external(hosted) and not cs.is_external(before) and not cs.is_external(None)


# ─── B3: TrueSync, the release page ───────────────────────────────────────

def test_truesync_is_the_release_page_over_the_sellers_channels(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'truesync')
    _dump('truesync-2v4.json', body)
    assert body['mode'] == 'seller_external'
    w = body['workspace']
    assert w['records'] == 4 and w['compiled'] == {'n': 28, 'of': 28} and w['published'] == 4
    assert w['channels'] == {'held': 6, 'live': 1, 'blocked': 0, 'not_for_seller': 1, 'not_compiled': 0}
    assert w['mode_note'].startswith("Offer records compiled from Petco's feed")
    assert [c['id'] for c in body['channels']] == list(rt.CHANNEL_ORDER)
    states = {c['id']: (c['state'], c['line']) for c in body['channels']}
    assert states['merchant_center'][1].startswith('4 of 4 SKUs held')
    assert states['mcp'] == ('live', '4 SKUs served · verified 4/4')
    assert states['manufacturer_center'] == ('not_for_seller', "a brand's channel")
    # the release: the brand page's fields beside 2V-2's card
    r = body['release']
    assert r['name'] == '4 Petco SKUs, 6 surfaces' and r['title'] == "4 Petco SKUs, 6 surfaces"
    assert r['state'] == 'held' and r['held'] == 6 and r['rules_on'] == {'on': 5, 'of': 6}
    assert r['mcp']['verified'] == '4/4'
    assert {s['channel']: s['status'] for s in r['surfaces']}['manufacturer_center'] == \
        "Not for a seller · a brand's channel"
    assert body['releases'][0]['approvals'] == '5 of 6 rules signed'
    assert body['releases'][0]['verification'] == 'MCP endpoint verified 4/4'


def test_the_matrix_is_one_row_per_sku_with_the_sellers_states(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'truesync')
    rows = {p['sku']: p for p in body['products']}
    assert sorted(rows) == ['2174511', '2579466', '3089211', '3879911']
    pro = rows['2579466']
    assert set(pro['cells']) == set(rt.CHANNEL_ORDER)
    assert pro['cells']['merchant_center'] == {**pro['cells']['merchant_center'], 's': 'held',
                                               'note': "Held for Petco's team"}
    assert pro['cells']['mcp']['s'] == 'live' and pro['cells']['mcp']['note'] == 'Served by get_product_true_cost'
    assert pro['cells']['manufacturer_center']['s'] == 'not_for_seller'
    assert rows['3879911']['cells']['schema_org']['note'] == 'Rx: list price only (rule s3)'
    # the master record is the offer record with the price path
    record = {f['k']: f for f in pro['record']}
    assert record['First Autoship order']['v'] == '$46.79' and record['Funded by']['v'] == 'Purina'
    # the compiler's lines: supply's flags, and 2V-1's table for the path's elements
    gmc = next(c for c in pro['compiler'] if c['channel'] == 'merchant_center')
    marks = {l['field']: l['mark'] for l in gmc['lines']}
    assert marks['price_path.first_order'] == 'approximated' and marks['price_path.later_steps'] == 'dropped'
    assert marks['price_path.valid_until'] == 'carried' and marks['gtin'] == 'info'
    assert gmc['rules_line'] == 's1, s2, s3, s4, s5, s6 apply, s1, s2, s3, s4 and s5 on'
    assert not any(c['channel'] == 'mcp' for c in pro['compiler'])


def test_the_drift_rows_judge_each_price_answer_against_the_path():
    row = {'sku': '2579466', 'variant_id': 'sku:2579466', 'product_name': 'Purina Pro Plan Sensitive Skin',
           'price_path': {'list_price': '77.99', 'steps': [{'order_n': '1', 'price': '46.79', 'program_name': 'Petco Autoship'}]}}
    answers = [{'run_id': 1, 'agent': 'chatgpt', 'text': 'Purina Pro Plan Sensitive Skin is $77.99, $46.79 first Autoship'},
               {'run_id': 2, 'agent': 'gemini', 'text': 'Purina Pro Plan Sensitive Skin is $77.99 at Petco'},
               {'run_id': 3, 'agent': 'claude', 'text': 'Purina Pro Plan Sensitive Skin runs $77.48'},
               {'run_id': 4, 'agent': 'copilot', 'text': 'Purina Pro Plan Sensitive Skin varies by store'}]
    lines = rt.drift_lines(row, answers, 'Autoship')
    assert [(l['agent'], l['verdict']) for l in lines] == [('claude', 'wrong'), ('gemini', 'partial'),
                                                            ('copilot', 'missed'), ('chatgpt', 'right')]
    assert lines[0]['truth'] == '$46.79 first Autoship, $77.99 list'


# ─── B4: the record's issues ──────────────────────────────────────────────

def test_the_record_carries_its_derived_issues(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'record', product='2579466')
    _dump('record-2v4.json', body)
    codes = {i['code']: i for i in body['issues']}
    assert set(codes) == {'program', 'gtin'}   # s1 on: the held markup carries the first order and its end date
    assert codes['gtin']['title'] == 'GTIN missing' and codes['gtin']['source']['kind'] == 'feed'
    assert codes['program']['detail'] == 'Autoship $74.09 on every order is description text in the held markup, not an Offer price.'
    rx = _read(http, 'record', product='3879911')
    assert 'rx' not in {i['code'] for i in rx['issues']}   # Autoship excludes Rx (not_applied: excluded: rx)


def test_each_issue_names_the_source_that_proves_it():
    row = {'sku': '1', 'variant_id': 'sku:1', 'product_name': 'NexGard PLUS', 'gtin': None,
           'price_path': {'list_price': '235.59', 'rx': True, 'not_applied': [],
                          'steps': [{'order_n': '1', 'price': '215.59', 'rule': '$20 off', 'program_name': 'Petco Autoship',
                                     'funded_by': 'purina', 'valid_until': '2026-10-31T00:00:00Z'}]}}
    page = {'role': 'own', 'sku': '1', 'url': 'https://www.petco.com/p/1', 'observed_at': '2026-10-29T12:00:00Z',
            'price': '239.99', 'title': 'NexGard PLUS, save with Vital Care',
            'json_ld': [{'@type': 'Product', 'offers': {'@type': 'Offer', 'price': '239.99'}}],
            'findings': [{'finding': 'name_differs', 'observed': 'NexGard PLUS Chew', 'expected': 'NexGard PLUS'}]}
    issues = {i['code']: i for i in rt.build_issues(
        row=row, held_rows={}, feed_row=None, feed_version={'version_number': 3}, page_rows=[page],
        loyalty={'name': 'Petco Perks', 'former_names': ['Vital Care']}, owned=[], rules=[], name='Petco',
        merchant='Petco', domain='petco.com')}
    assert set(issues) == {'first_order', 'ladder', 'gtin', 'page', 'retired', 'rx'}
    assert issues['first_order']['detail'] == 'petco.com publishes list price only in its Offer markup. The $215.59 lives in page text.'
    assert issues['first_order']['source'] == {'kind': 'page', 'label': 'petco.com page, read Oct 29',
                                               'url': 'https://www.petco.com/p/1', 'at': '2026-10-29T12:00:00Z'}
    assert issues['ladder']['detail'] == 'The Oct 31 end date is on the Purina ladder, not on the offer.'
    assert issues['page']['title'] == 'Page differs: name and price'
    assert issues['retired']['detail'] == 'The page still says "Vital Care". The program is Petco Perks.'
    assert issues['rx']['title'] == 'Rx with no program exclusion'
    assert issues['gtin']['source']['label'] == "Petco's feed, version 3"


# ─── B5: the Fix queue and Approvals ──────────────────────────────────────

def test_the_fix_queue_is_derived_from_signals_rules_the_hold_and_the_journal(http, db, upstream):
    _shape(db, http, upstream, rules='rules-seed')
    body = _read(http, 'fixes')
    _dump('fixes-2v4-seed.json', body)
    assert [f['id'] for f in body['fixes']] == ['first_order', 'release', 'order_data']
    assert body['fixes'][2]['title'] == 'Connect order data for Impact' and body['fixes'][2]['state'] == 'queued'
    _rules(upstream, 'rules')
    body = _read(http, 'fixes')
    _dump('fixes-2v4.json', body)
    # s1 on and approved: no first-order fix; s3 on: the Rx item waits on Pricing's term
    assert [f['id'] for f in body['fixes']] == ['release', 'rx_terms', 'order_data']
    rx = body['fixes'][1]
    assert rx['title'] == 'Attach the Rx first-order terms to NexGard PLUS Chewables for Dogs 33.1-66 lb'
    assert rx['detail'] == '1 Rx SKU compiles at list price only (rule s3) until Pricing picks one first-order term.'


def test_the_edge_and_the_retired_copy_are_fixes():
    access = {'problem_identities': [{'label': 'ChatGPT'}, {'label': 'Perplexity'}]}
    (edge, orders) = rt.more_fixes(paths=[], rules=[], access=access, domain='petco.com', issues={})
    assert edge['title'] == 'Open a verified-agent path at the edge'
    assert edge['detail'] == 'ChatGPT and Perplexity are turned away at petco.com. Signed agents should get the catalog.'
    assert orders['id'] == 'order_data'


def test_approvals_list_every_seller_rule_signed_rows_and_the_release(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'approvals')
    _dump('approvals-2v4.json', body)
    assert [r['code'] for r in body['requests']] == ['s1', 's2', 's3', 's4', 's5', 's6', 'release']
    states = {r['code']: r['state'] for r in body['requests']}
    assert states == {'s1': 'approved', 's2': 'approved', 's3': 'approved', 's4': 'approved', 's5': 'approved',
                      's6': 'pending', 'release': 'held'}
    s3 = next(r for r in body['requests'] if r['code'] == 's3')
    assert s3['fix_title'].startswith('Attach the Rx first-order terms') and s3['scope_text'] == '1 Rx SKU'
    assert next(r for r in body['requests'] if r['code'] == 's2')['fix_title'] is None
    assert [(s['code'], s['by']) for s in body['signed']] == [(c, 'elton@parleo.io') for c in ('s1', 's2', 's3', 's4', 's5')]
    assert body['requests'][-1]['title'] == "4 Petco SKUs, held for Petco's team"
    assert body['summary']['waiting'] == 1 and body['summary']['total'] == 7
    _rules(upstream, 'rules-seed')
    seed = _read(http, 'approvals')
    _dump('approvals-2v4-seed.json', seed)
    assert [r['state'] for r in seed['requests'][:6]] == ['pending'] * 6 and seed['signed'] == []


# ─── B2: the Overview ─────────────────────────────────────────────────────

def test_the_overview_reads_the_retail_blocks(http, db, upstream):
    _shape(db, http, upstream)
    as_('op')
    r = http.get('/api/console/overview', params={'merchant': SLUG, 'org': 10, 'cycle': f2p1.CYCLE_2})
    assert r.status_code == 200, r.text
    body = r.json()
    _dump('overview-2v4.json', body)
    assert body['mode'] == 'seller_external' and body['kind'] == 'seller'
    card = body['truesync_card']
    assert card['mode'] == 'seller_external' and card['held'] == 6 and card['products'] == 4
    assert card['cells'] == {'n': 28, 'of': 28}
    assert [a['key'] for a in body['actions']] == ['rule:s6', 'release', 'rule:s1', 'rule:s2', 'rule:s3', 'rule:s4', 'rule:s5']
    assert body['actions'][0]['what'] == 'Sign rule s6: Marketplace storefront excluded'
    assert [f['id'] for f in body['fix_queue']['fixes']] == ['release', 'rx_terms', 'order_data']
    assert body['strip']['approvals'] == 1
    assert body['revenue']['mode_note'].startswith('Retail mode: Petco sets its own prices')
    stages = [a['stage'] for a in body['activity']]
    assert 'compiled' in stages and 'readback' in stages and stages.count('signed') == 5
    assert body['header']['skus'] == 4


def test_the_sellers_signals_and_the_lead():
    vis = {'ranking': {'rows': [{'name': 'Petco', 'you': True}]}, 'byQuestion': [
        {'unprompted': True, 'answered': True, 'named': [{'name': 'Petco', 'you': True}, {'name': 'Chewy'}],
         'first': {'name': 'Chewy'}},
        {'unprompted': True, 'answered': True, 'named': [{'name': 'Chewy'}], 'first': {'name': 'Chewy'}},
        {'unprompted': True, 'answered': True, 'named': [{'name': 'Petco', 'you': True}], 'first': {'name': 'Petco', 'you': True}},
        {'unprompted': False, 'answered': True, 'named': [{'name': 'Petco', 'you': True}], 'first': {'name': 'Petco', 'you': True}}]}
    counts = rt.unprompted_counts(vis)
    store = rt.store_signal(counts, 'Petco')
    assert store['title'] == 'Agents name Petco, then recommend Chewy first.'
    assert store['detail'] == 'Petco first in 1 of 3 unprompted answers, Chewy in 2. Petco named in 2.'
    paths = [{'sku': '1', 'product_name': 'Tidy Cats LightWeight', 'price_path': {'list_price': '28.98', 'steps': [
        {'order_n': '1', 'price': '17.39', 'funded_by': 'purina', 'valid_until': '2026-10-31T00:00:00Z',
         'program_name': 'Petco Autoship'}]}}]
    answers = [{'run_id': 1, 'agent': 'chatgpt', 'text': 'Tidy Cats LightWeight: $18.84 with Petco Autoship'},
               {'run_id': 2, 'agent': 'gemini', 'text': 'Petco still offers Vital Care savings'}]
    new = [store, rt.missing_signal(paths=paths, price_answers=answers[:1], name='Petco', program='Autoship'),
           rt.misstated_signal(paths=paths, answers=answers, name='Petco', program='Autoship'),
           rt.funded_signal(paths=paths, answers=answers),
           rt.retired_signal(answers=answers, loyalty={'name': 'Petco Perks', 'former_names': ['Vital Care']}),
           rt.access_signal({'problem_identities': [{'label': 'ChatGPT'}]}, 'petco.com')]
    ranked = rt.rank_signals([{'id': 'other_brand', 'rule': 'other_brand', 'title': 'x', 'tag': 'Lost pool'}], new)
    assert [s['id'] for s in ranked] == ['another_store_first', 'program_price_missing', 'program_price_misstated',
                                         'funded_missed', 'retired_program', 'access', 'other_brand']
    assert [s['tag'] for s in ranked] == ['Another store first', 'Program price missing', 'Program price misstated',
                                          'Funded offer missed', 'Retired name', 'Access', 'Wrong price']
    assert ranked[3]['title'] == "Purina's ladder ends Oct 31 and agents don't apply it."
    assert ranked[4]['title'] == 'Gemini still says Vital Care.'
    lead = rt.build_lead(ranked, name='Petco', counts=counts, fixes=[{'state': 'needs_decision', 'title': 'Publish first-order Autoship prices on 4 SKUs'}])
    assert lead['headline'] == 'Agents name Petco, then recommend Chewy first.'
    assert lead['facts'] == [{'who': 'Petco', 'value': '1', 'of': 'of 3', 'cap': 'first recommendations'},
                             {'who': 'Chewy', 'value': '2', 'of': 'of 3', 'cap': 'first recommendations'}]
    assert lead['do'] == 'Publish first-order Autoship prices on 4 SKUs.'


# ─── B6, B7: Exposure rules and Funded offers on the re-recording ─────────

def test_rules_and_funded_offers_read_the_rerecording(http, db, upstream):
    _shape(db, http, upstream)
    rules = _read(http, 'rules')
    _dump('rules-2v4.json', rules)
    assert [r['id'] for r in rules['rules']] == list(rt.SELLER_RULES)
    # the pair's 192 price answers are about diapers: none quoted a Petco first-order price
    assert [b['before'] for b in rules['backtest']] == ['0 of 192', '0', '0']
    prove = _read(http, 'prove', cycle=f2p1.CYCLE_2)
    _dump('prove-2v4.json', prove)
    (row,) = prove['rows']
    assert row['funded_by'] == 'purina' and prove['aside']['kick'] == 'Purina partner seat'
