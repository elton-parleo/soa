"""
2R-2 (B1-B4): manufacturer mode, a brand at retail, on 2P-1's pair (cycle 229
Oct 14, cycle 230 Oct 21) with supply's answers for a brand whose `mode` is
manufacturer (console_fixture_2r2, synthetic to 2R-1's shapes: see its
docstring). sqlite and Postgres.

Supply holds Manufacturer Center's ten records and the brand's ACP feed
(compiled Oct 13); P&G's team sends them, Parleo never does. Until P&G says it
sent the file, Rules' "after" reads "Next read" and Impact is locked; once it
says so (sent Oct 17, between the two cycles), after is cycle 230 and Impact
reads what moved since cycle 229, through the one comparability rule.
"""
import copy
import json
import os

import pytest
from sqlalchemy import text

from app.routers.console_manufacturer import named_by_variant
from app.services import console_cache
from app.services import console_manufacturer as manu
from tests import console_fixture_2p1 as f2p1
from tests import console_fixture_2r2 as f2r2
from tests import test_console_2m1_attribute as t2m1
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import WS, _get, _pair
from tests.test_console_read_models import TOKEN_A, WS_TENANT, as_, http, upstream  # noqa: F401  (pytest fixtures)

BASE = f2r2.BASE
SELLERS_OVERRIDE = {'v5': ['costco.com', 'samsclub.com', 'bjs.com']}


def _named(db, cycle_id=f2p1.ID_2):
    with db.connect() as c:
        row = dict(c.execute(text("SELECT * FROM soa_cycles WHERE id = :i"), {'i': cycle_id}).mappings().one())
        return named_by_variant(c, row)


def _shape(db, http, upstream, **kw):
    _pair(db, http, upstream)
    f2r2.answer(upstream, base_reference=f2p1.reference_2(t2m1.ATTRIBUTE_REFERENCE), named=_named(db),
                override=SELLERS_OVERRIDE, **kw)


def _read(http, endpoint, user='op', status=200, **params):
    as_(user)
    r = http.get(f'/api/console/{endpoint}', params={'merchant': WS, **({'org': 10} if user == 'op' else {}), **params})
    assert r.status_code == status, r.text
    return r.json()


def _dump(name, body):
    """SOA_2R2_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2R2_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


# ── B1: /truesync in manufacturer mode ────────────────────────────────────

def test_truesync_and_publishing_carry_the_same_objects(http, db, upstream):
    _shape(db, http, upstream)
    ts = _read(http, 'truesync')
    pub = _read(http, 'publishing')
    _dump('truesync-2r2.json', ts)
    _dump('publishing-2r2.json', pub)
    assert ts['mode'] == pub['mode'] == 'manufacturer'
    for key in ('surfaces', 'diff', 'preview', 'artifacts'):
        assert ts[key] == pub[key], key
    # the matrix is still there beside them
    assert [p['listing_id'] for p in ts['products']] == list(range(40, 50))
    # a tenant with no Manufacturer Center account: the matrix's cell is "not connected", as before; the held
    # file is on the surface
    assert ts['products'][0]['cells']['manufacturer_center']['s'] == 'na'
    assert ts['products'][0]['cells']['acp']['s'] == 'compiled'


def test_the_surfaces_by_hand(http, db, upstream):
    _shape(db, http, upstream)
    surfaces = {s['id']: s for s in _read(http, 'publishing')['surfaces']}
    assert list(surfaces) == ['mfc', 'oai', 'markup', 'ucp', 'coupons']
    mfc = surfaces['mfc']
    assert (mfc['status'], mfc['last'], mfc['records'], mfc['connected']) == ('held', 'File compiled Oct 13', 10, False)
    # the attribute names the compile actually carried, never a fixed list
    assert mfc['fields'] == 'gtin, brand, title, productName, count, size, productDetail, productPageUrl'
    assert mfc['note'] == "The brand's own team sends it. Parleo never writes into its account"
    assert (surfaces['oai']['status'], surfaces['oai']['last']) == ('held', 'Compiled Oct 13')
    markup = surfaces['markup']
    assert (markup['name'], markup['status'], markup['last']) == ('Site markup (pampers.com)', 'drift', 'Read Oct 13')
    assert markup['note'] == ('Cruisers 360, Zzz and Swaddlers markup carry the wrong Size 3, Size 4 and Size 5 weights. '
                              'AMORE GTIN has 11 digits')
    assert (surfaces['ucp']['status'], surfaces['ucp']['last']) == ('none', 'Not in this pass')
    coupons = surfaces['coupons']
    assert (coupons['status'], coupons['last'], coupons['note'], coupons['approval']) == \
        ('next', 'Next release', 'Publishes after Legal approves rule 4', 'needs_legal')


def test_each_surface_follows_supply(http, db, upstream):
    _shape(db, http, upstream, acp='blocked', ucp=True)
    rules = copy.deepcopy(f2r2.RULES)
    rules['rules'][3]['approval'] = {'state': 'approved', 'by': 'legal@pg.test', 'at': '2026-10-24T10:00:00+00:00'}
    upstream.answer('GET', f'{BASE}/rules', body=rules, token=TOKEN_A)
    surfaces = {s['id']: s for s in _read(http, 'publishing')['surfaces']}
    assert surfaces['oai']['status'] == 'blocked'
    assert surfaces['oai']['note'].startswith('ACP product feed spec, price: required on every item.')
    assert (surfaces['ucp']['status'], surfaces['ucp']['last']) == ('live', 'Live, version 2026-04-08')
    assert surfaces['coupons']['note'] == 'Legal approved rule 4 on Oct 24. Publishes in the next release'
    # before the first hold Manufacturer Center is not compiled; no markup drift reads none
    upstream.answer('GET', '/api/truesync/publications', body=[], token=TOKEN_A)
    plain = copy.deepcopy(f2p1.reference_2(t2m1.ATTRIBUTE_REFERENCE))
    for v in plain['attributes']:
        v['markup'] = v['chart']
    upstream.answer('GET', f'{BASE}/reference', body=plain, token=TOKEN_A)
    body = _read(http, 'publishing')
    surfaces = {s['id']: s for s in body['surfaces']}
    assert (surfaces['mfc']['status'], surfaces['mfc']['last'], surfaces['mfc']['fields']) == \
        ('not_compiled', 'Not compiled yet', '')
    assert surfaces['markup']['status'] == 'none'
    assert body['preview'] == {'title': 'No Pampers record compiled yet', 'note': 'Not compiled yet', 'records': 0,
                               'compiled_at': None, 'held': False}
    assert body['artifacts'] == []
    # a rules read that fails is named, never "approved"
    upstream.answer('GET', f'{BASE}/rules', status=500, body={'detail': 'down'}, token=TOKEN_A)
    body = _read(http, 'publishing')
    assert 'rules' in body['read_errors']
    assert {s['id']: s for s in body['surfaces']}['coupons']['note'] == \
        "Publishes after Legal approves rule 4. Rule 4's approval could not be read"


def test_the_diff_preview_and_artifacts(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'publishing')
    diff = body['diff']
    kinds = [r['kind'] for r in diff]
    # 2M-1's weight rows first (3 markup, 6 retailer pages), then GTINs, the retired line, the sellers
    assert (kinds.count('markup'), kinds.count('page')) == (3, 6)
    assert [(r['field'], r['was'], r['now'], r['prov']) for r in diff if r['kind'] != 'markup' and r['kind'] != 'page'] == [
        ('amore.size_1.gtin', '30772244425', '030772244425', 'parleo'),
        ('baby_dry.size_4.gtin', '37000799818', '037000799818', 'parleo'),
        ('pure_protection.status', 'sold, per 4 of 6 agents', 'retired, successor AMORE', 'brand'),
        ('swaddlers.size_5.sellers', 'Target, Walmart, Amazon', "Costco, Sam's Club, BJ's", 'brand')]
    # every "was" names its source cycle
    assert {r['source']['cycle'] for r in diff} == {f2p1.CYCLE_2}
    assert {r['source']['what'] for r in diff} == {'supply read', 'feed', 'answers'}
    assert body['preview'] == {
        'title': 'Ten Pampers records, Manufacturer Center first',
        'note': "Compiled Oct 13 from pampers.com and same-day shelf reads. Held until P&G's team sends it.",
        'records': 10, 'compiled_at': f2r2.COMPILED_AT, 'held': True, 'sent': None}
    assert [(a['channel'], a['records'], a['url']) for a in body['artifacts']] == [
        ('manufacturer_center', 10, f'/api/console/truesync/artifact?merchant={WS}&channel=manufacturer_center'),
        ('acp', 10, f'/api/console/truesync/artifact?merchant={WS}&channel=acp')]


def test_a_merchant_not_in_manufacturer_mode_is_unchanged(http, db, upstream):
    _shape(db, http, upstream)
    upstream.answer('GET', '/api/truesync/tenant', body=WS_TENANT, token=TOKEN_A)
    ts = _read(http, 'truesync')
    assert not {'mode', 'surfaces', 'diff', 'preview', 'artifacts'} & set(ts)
    for endpoint in ('publishing', 'rules'):
        assert _read(http, endpoint, status=404)['detail'] == f"merchant '{WS}' is not in manufacturer mode"
    assert 'locked' not in _read(http, 'revenue', cycle=f2p1.CYCLE_2)


# ── B2: /rules, its backtest, the switch ──────────────────────────────────

def test_rules_and_the_backtest_on_the_fl15_shape(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'rules')
    _dump('rules-2r2.json', body)
    assert [(r['id'], r['on'], r['approval']['state']) for r in body['rules']] == [
        ('r1', True, 'approved'), ('r2', True, 'approved'), ('r3', True, 'approved'), ('r4', False, 'needs_legal'),
        ('r5', True, 'approved'), ('r6', True, 'approved')]
    assert body['note'] == 'Compliance rules compile into every product record. Legal signs off before Publishing switches a rule on.'
    assert body['cycle'] == f2p1.CYCLE_2 and body['sent'] is None
    rows = {r['key']: r for r in body['backtest']}
    assert [(r['label'], r['before'], r['after']) for r in body['backtest']] == [
        ("Size 4 weight answers giving only the chart's range", '9 of 15', 'Next read'),
        ('Category answers naming Pure', '7 of 102', 'Next read'),
        ('Cheapest-place answers naming a live deal', '3 of 100', 'Next read')]
    unsent = ("After is the first cycle scored after P&G's team sends the file. A held file changes nothing an agent "
              "reads, so holding it starts no clock.")
    assert rows['attribute']['note'] == f'Swaddlers, Zzz and Baby-Dry, Oct 21. {unsent}'
    assert rows['retired']['note'] == f'AMORE named in 3, Oct 21. {unsent}'
    assert rows['promo']['note'] == f'Amazon multi-buy 2 and Amazon coupon 1, Oct 21. {unsent}'
    # the same helpers as the Overview: its retired line and its promo tile read the same counts
    over = _get(http, 'overview', cycle=f2p1.CYCLE_2, merchant=WS)
    pure = over['retired_named']['lines'][0]['brand_choice']['all']
    assert rows['retired']['before'] == f"{pure['named']} of {pure['answers']}"
    promo = over['promo_pass_through']
    assert rows['promo']['before'] == f"{promo['k']} of {promo['n']}"
    size4_misses = [m for m in over['attribute_accuracy']['misses'] if m['kind'] == 'answer' and m['size'] == 'Size 4']
    assert rows['attribute']['before'] == f'{15 - len(size4_misses)} of 15'


def test_putting_a_rule_is_forwarded_operator_only_and_rereads(http, db, upstream):
    _shape(db, http, upstream)
    upstream.answer('PUT', f'{BASE}/rules/r4', body={'code': 'r4', 'on': True}, token=TOKEN_A)
    as_('alice')
    r = http.put('/api/console/rules/r4', params={'merchant': WS}, json={'on': True})
    assert r.status_code == 403, r.text
    as_('op')
    r = http.put('/api/console/rules/r4', params={'merchant': WS, 'org': 10},
                 json={'on': True, 'approval': 'approved', 'note': 'Legal signed Oct 24'})
    assert r.status_code == 200, r.text
    put = [c for c in upstream.calls if c['method'] == 'PUT']
    assert put == [{'method': 'PUT', 'path': f'{BASE}/rules/r4', 'token': TOKEN_A, 'params': None,
                    'json': {'on': True, 'approval': 'approved', 'note': 'Legal signed Oct 24', 'by': 'op@test'}}]
    assert [x['id'] for x in r.json()['rules']] == ['r1', 'r2', 'r3', 'r4', 'r5', 'r6']   # the re-read list
    assert http.put('/api/console/rules/r4', params={'merchant': WS, 'org': 10}, json={}).status_code == 422
    assert http.put('/api/console/rules/r4', params={'merchant': WS, 'org': 10},
                    json={'approval': 'yes'}).status_code == 422


# ── B3: sent is a fact the brand states; Impact unlocks on it ─────────────

def test_impact_is_locked_until_the_brand_says_it_sent_the_file(http, db, upstream):
    _shape(db, http, upstream)
    rev = _read(http, 'revenue', cycle=f2p1.CYCLE_2)
    assert rev['locked'] == {
        'state': 'locked', 'title': 'Cause shows once P&G publishes the record',
        'text': ("TrueSync can tie a change in these answers to a fix only after P&G's team publishes the Pampers record "
                 "to Manufacturer Center and pampers.com. Until then every figure here is a count of answers you can "
                 "audit.")}


def test_the_sent_statement_is_journaled_on_the_held_publications(http, db, upstream):
    _shape(db, http, upstream)
    upstream.answer('POST', f'{BASE}/publications/sent', body={'journaled': []}, token=TOKEN_A)
    as_('alice')   # the brand states it: a member may
    r = http.post('/api/console/publishing/sent', params={'merchant': WS},
                  json={'channel': 'manufacturer_center', 'sent_at': f2r2.SENT_AT,
                        'by': "P&G's Manufacturer Center team", 'note': 'uploaded through the UI'})
    assert r.status_code == 200, r.text
    [call] = [c for c in upstream.calls if c['method'] == 'POST']
    assert call['token'] == TOKEN_A and call['path'] == f'{BASE}/publications/sent'
    assert call['json'] == {'channel': 'manufacturer_center', 'sent_at': f2r2.SENT_AT,
                            'by': "P&G's Manufacturer Center team", 'note': 'uploaded through the UI',
                            'stated_by': 'alice@test', 'event': 'sent_by_merchant',
                            'publication_ids': list(range(8040, 8050))}
    assert r.json()['mode'] == 'manufacturer'   # the re-read Publishing
    bad = lambda body: http.post('/api/console/publishing/sent', params={'merchant': WS}, json=body).status_code  # noqa: E731
    assert bad({'channel': 'ucp_uip', 'sent_at': f2r2.SENT_AT}) == 409          # nothing held there
    assert bad({'channel': 'manufacturer_center', 'sent_at': 'last week'}) == 422
    assert bad({'channel': 'manufacturer_center', 'sent_at': '2027-01-01'}) == 422


def test_once_sent_impact_and_the_backtest_read_the_next_cycle(http, db, upstream):
    _shape(db, http, upstream, sent=f2r2.SENT_AT)
    rev = _read(http, 'revenue', cycle=f2p1.CYCLE_2)
    _dump('revenue-2r2.json', rev)
    locked = rev['locked']
    assert (locked['state'], locked['title']) == ('unlocked', 'What moved since the record was sent (Oct 17)')
    assert (locked['before'], locked['after'], locked['status']) == (f2p1.CYCLE_1, f2p1.CYCLE_2, 'compared')
    assert locked['sent']['by'] == "P&G's Manufacturer Center team"
    # the first cycle after the send against the last before it: 2P-1's four rows, by the same rule
    assert [(m['label'], m['then'], m['now'], m['delta']) for m in locked['rows']] == [
        ('Attribute accuracy', '61 of 79', '62 of 79', '+1'), ('Retailer coverage', '38 of 49', '40 of 49', '+2'),
        ('Promo pass-through', '5 of 100', '3 of 100', '-2'), ('Category presence', '51 of 102', '51 of 102', '0')]
    rules = _read(http, 'rules')
    assert (rules['cycle'], rules['after_cycle']) == (f2p1.CYCLE_1, f2p1.CYCLE_2)
    rows = {r['key']: r for r in rules['backtest']}
    assert rows['promo']['before'] == '5 of 100' and rows['promo']['after'] == '3 of 100'
    assert rows['promo']['note'].endswith(f'After is {f2p1.CYCLE_2} (Oct 21), the first cycle scored after the send on Oct 17.')
    pub = _read(http, 'publishing')
    mfc = pub['surfaces'][0]
    assert mfc['last'] == 'File compiled Oct 13, sent Oct 17' and mfc['sent']['sent_at'] == f2r2.SENT_AT
    assert pub['preview']['note'] == ("Compiled Oct 13 from pampers.com and same-day shelf reads. P&G's team says it "
                                      "sent it on Oct 17.")


def test_a_send_after_the_newest_cycle_waits_for_the_next_read(http, db, upstream):
    _shape(db, http, upstream, sent='2026-10-23')
    locked = _read(http, 'revenue', cycle=f2p1.CYCLE_2)['locked']
    assert (locked['state'], locked['rows'], locked['after']) == ('unlocked', None, None)
    assert locked['note'] == 'The first cycle scored after Oct 23 has not run yet. Each figure moves on that read.'
    rows = _read(http, 'rules')['backtest']
    assert {r['after'] for r in rows} == {'Next read'}
    assert rows[0]['note'].endswith('After is the first cycle scored after the send on Oct 23. None has run yet.')


# ── B4: the file through soa ──────────────────────────────────────────────

def test_the_artifact_comes_through_soa_with_its_filename(http, db, upstream):
    _shape(db, http, upstream)
    as_('alice')
    r = http.get('/api/console/truesync/artifact', params={'merchant': WS, 'channel': 'manufacturer_center'})
    assert r.status_code == 200, r.text
    assert r.content == f2r2.ARTIFACT
    assert r.headers['content-type'].startswith('application/json')
    assert r.headers['content-disposition'] == 'attachment; filename="pampers-manufacturer-center-2026-10-13.json"'
    assert TOKEN_A not in r.text and TOKEN_A not in json.dumps(dict(r.headers))
    [call] = [c for c in upstream.calls if '/artifacts/' in c['path']]
    assert call['token'] == TOKEN_A
    assert http.get('/api/console/truesync/artifact', params={'merchant': WS, 'channel': 'ucp_uip'}).status_code == 404
    # supply refuses the token: said so, never an empty file
    upstream.answer('GET', f'{BASE}/artifacts/manufacturer_center', status=403, body={'detail': 'bad key'}, token=TOKEN_A)
    r = http.get('/api/console/truesync/artifact', params={'merchant': WS, 'channel': 'manufacturer_center'})
    assert r.status_code == 403 and r.json()['detail'].startswith('Not authorized for this customer')


def test_the_artifact_is_kept_per_compiled_at(http, db, upstream, monkeypatch):
    _shape(db, http, upstream)
    monkeypatch.setenv('SOA_CONSOLE_CACHE', '1')
    console_cache.clear()
    as_('alice')

    def fetch():
        r = http.get('/api/console/truesync/artifact', params={'merchant': WS, 'channel': 'manufacturer_center'})
        assert r.status_code == 200
        return sum(1 for c in upstream.calls if '/artifacts/' in c['path'])
    assert fetch() == 1
    assert fetch() == 1                 # the same compile: kept
    recompiled = f2r2.publications()
    for p in recompiled:
        p['compiled_at'] = '2026-10-24T16:00:00+00:00'
    upstream.answer('GET', '/api/truesync/publications', body=recompiled, token=TOKEN_A)
    assert fetch() == 2                 # a recompile is a new file


# ── the rules by hand ─────────────────────────────────────────────────────

def test_gtin_corrections_and_carried_fields():
    assert manu.gtin_correction('30772244425') == '030772244425'
    assert manu.gtin_correction('037000799818') is None        # a GTIN as written
    assert manu.gtin_correction('30772244426') is None         # no padding makes it one
    assert manu.carried_fields({'products': [{'attributes': {'gtin': 1, 'size': 2}}, {'attributes': {'count': 3}}]}) == \
        ['gtin', 'size', 'count']
    assert manu.carried_fields({'items': [{'item_id': 1, 'title': 2}]}) == ['item_id', 'title']


@pytest.mark.parametrize('sent, before, after', [
    (None, 'c3', None), ({'sent_at': '2026-10-17'}, 'c2', 'c3'), ({'sent_at': '2026-10-22'}, 'c3', None),
    ({'sent_at': '2026-10-01'}, None, 'c1')])
def test_around_send(sent, before, after):
    cycles = [{'cycle_code': 'c3', 'start_date': '2026-10-21'}, {'cycle_code': 'c2', 'start_date': '2026-10-14'},
              {'cycle_code': 'c1', 'start_date': '2026-10-07'}]
    b, a = manu.around_send(cycles, sent)
    assert ((b or {}).get('cycle_code'), (a or {}).get('cycle_code')) == (before, after)


def test_the_markup_reason_pairs_each_line_with_its_sizes():
    reference = {'attributes': [
        {'variant_ref': 'a', 'product_name': 'Pampers Swaddlers', 'variant_label': 'Size 4, 120 ct'},
        {'variant_ref': 'b', 'product_name': 'Pampers Swaddlers', 'variant_label': 'Size 5, 108 ct'},
        {'variant_ref': 'c', 'product_name': 'Pampers Zzz', 'variant_label': 'Size 4, 104 ct'}]}
    drift = [{'kind': 'markup', 'variant_ref': v} for v in ('a', 'b', 'c')]
    assert manu.markup_reason(drift, reference, []) == \
        'Swaddlers Size 4 and Size 5 and Zzz Size 4 markup carry the wrong weights'
    assert manu.markup_reason(drift[2:], reference, []) == 'Zzz markup carries the wrong Size 4 weight'
    assert manu.markup_reason([], reference, []) is None
