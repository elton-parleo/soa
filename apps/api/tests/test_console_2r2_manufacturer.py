"""
2R-2 (B1-B4) and 2R-2a: manufacturer mode, a brand at retail, on 2P-1's pair
(cycle 229 Oct 14, cycle 230 Oct 21) with supply's answers RECORDED from
parleo-supply-app#33 (console_fixture_2r2; tests/fixtures/console/supply_2r1/
PROVENANCE.md). sqlite and Postgres.

#33's merchant `pampers-2r1` holds four records compiled Oct 25: schema_org
and Manufacturer Center held (Manufacturer Center 2 of 4 valid: Pure and AMORE
carry no GTIN), ACP blocked with its spec clause. The brand's team sends the
file; Parleo never does. Until the brand says it sent it, Rules' "after"
reads "Next read" and Impact is locked; once it says so (Oct 17, between the
two cycles) after is cycle 230 and Impact reads what moved since cycle 229,
through the one comparability rule.

A test that needs a state #33's harness did not produce (every Manufacturer
Center record failing) derives it from a recorded row and says so.
"""
import json
import os

import pytest

from app.services import console_cache
from app.services import console_manufacturer as manu
from tests import console_fixture_2p1 as f2p1
from tests import console_fixture_2r2 as f2r2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import _get, _pair
from tests.test_console_read_models import TOKEN_A, WS_TENANT, as_, http, upstream  # noqa: F401  (pytest fixtures)

SLUG, BASE = f2r2.SLUG, f2r2.BASE
CLAUSE = f2r2.body('artifact-acp')['detail']['spec_clause']


def _shape(db, http, upstream, sent=None):
    _pair(db, http, upstream)
    f2r2.retag(db)
    f2r2.alias(upstream)
    return f2r2.answer(upstream, sent=sent)


def _read(http, endpoint, user='op', status=200, merchant=SLUG, **params):
    as_(user)
    r = http.get(f'/api/console/{endpoint}', params={'merchant': merchant, **({'org': 10} if user == 'op' else {}),
                                                     **params})
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
    for key in ('surfaces', 'diff', 'preview', 'artifacts', 'held'):
        assert ts[key] == pub[key], key
    # the matrix reads the held feed records as its catalog listings (record_ref = the listing's product_id)
    cells = {p['name']: {k: c['s'] for k, c in p['cells'].items()} for p in ts['products']}
    assert list(cells) == ['Pampers Swaddlers', 'Pampers Pure Protection', 'Pampers AMORE', 'Pampers Zzz']
    assert {(c['schema_org'], c['acp'], c['manufacturer_center']) for c in cells.values()} == {('compiled', 'compiled', 'na')}


def test_the_surfaces_from_33(http, db, upstream):
    _shape(db, http, upstream)
    surfaces = {s['id']: s for s in _read(http, 'publishing')['surfaces']}
    assert list(surfaces) == ['mfc', 'oai', 'markup', 'ucp', 'coupons']
    mfc = surfaces['mfc']
    assert (mfc['status'], mfc['last'], mfc['records'], mfc['connected']) == \
        ('held', 'File compiled Oct 25', '2 of 4 valid', False)
    # the attribute names the valid records' compile actually carried
    assert mfc['fields'] == 'brand, description, gtin, imageLink, itemGroupId, productName, productPageUrl, title, count'
    assert mfc['note'] == "The brand's own team sends it. Parleo never writes into its account"
    assert (mfc['images_from_brand_page'], mfc['no_image']) == (2, 0)
    assert mfc['errors'] == ['no variant carries a GTIN; Manufacturer Center keys every product by GTIN'] * 2
    oai = surfaces['oai']
    assert (oai['status'], oai['last'], oai['note'], oai['blocked']) == ('blocked', 'Compiled Oct 25', CLAUSE, 4)
    markup = surfaces['markup']
    assert (markup['name'], markup['status'], markup['last'], markup['pages']) == \
        ('Site markup (pampers.com)', 'drift', 'Read Oct 20', 2)
    # the weight rows are the pair's (/reference attributes); the brand pages' GTINs are all GTINs as written
    assert markup['note'] == 'Cruisers 360, Zzz and Swaddlers markup carry the wrong Size 3, Size 4 and Size 5 weights'
    assert markup['gtin_flags'] == 0
    assert (surfaces['ucp']['status'], surfaces['ucp']['last']) == ('none', 'Not in this pass')
    coupons = surfaces['coupons']
    assert (coupons['note'], coupons['approval'], coupons['approval_look']) == \
        ('Publishes after Legal approves rule 4', 'needs_approval', 'needs_legal')


def test_rule_4_s_approval_moves_the_deals_surface(http, db, upstream):
    _shape(db, http, upstream)
    upstream.answer('GET', f'{BASE}/rules', body=f2r2.body('rules-after-put'), token=TOKEN_A)
    coupons = {s['id']: s for s in _read(http, 'publishing')['surfaces']}['coupons']
    assert coupons['note'] == 'Legal approved rule 4 on Oct 25. Publishes in the next release'
    upstream.answer('GET', f'{BASE}/rules', status=500, body={'detail': 'down'}, token=TOKEN_A)
    body = _read(http, 'publishing')
    assert 'rules' in body['read_errors']
    assert {s['id']: s for s in body['surfaces']}['coupons']['note'] == \
        "Publishes after Legal approves rule 4. Rule 4's approval could not be read"


def test_every_manufacturer_center_record_failing_is_blocked():
    """A4. #33's harness held 2 of 4 valid; every record failing is derived from its rows: the two valid ones
    given the failing ones' validation."""
    rows = f2r2.mine(f2r2.body('publications-held'))
    failing = next(r for r in rows if r['channel_slug'] == 'manufacturer_center' and r['error'])
    derived = [{**r, 'validation': failing['validation'], 'error': failing['error']}
               if r['channel_slug'] == 'manufacturer_center' else r for r in rows]
    held = f2r2.body('tenant-held')['merchants'][0]['held']
    surfaces = manu.build_surfaces(pubs=derived, channels=f2r2.body('channels'), drift=[], reference=None, pages=[],
                                   flags=[], own_domain='pampers.com', rules=[], held=held)
    mfc = surfaces[0]
    assert (mfc['status'], mfc['records'], mfc['note']) == \
        ('blocked', '0 of 4 valid', 'no variant carries a GTIN; Manufacturer Center keys every product by GTIN')
    preview = manu.build_preview(surfaces=surfaces, brand='Pampers', name='Pampers 2R-1', domain='pampers.com')
    assert preview['note'] == ("Compiled Oct 25 from Pampers 2R-1's feed and pampers.com. 0 of 4 valid, so nothing is "
                               "ready to send: no variant carries a GTIN; Manufacturer Center keys every product by GTIN")
    assert preview['held'] is False


def test_no_image_yet_is_never_invented():
    """A record whose compile took no image from the brand page and whose validator names the image."""
    row = {'expressiveness': [{'field': 'description_from_brand_page'}],
           'validation': {'ok': False, 'errors': ['US:en:00037000799818: imageLink is required']}}
    assert manu.no_image(row) is True
    assert manu.no_image({**row, 'expressiveness': [{'field': 'image_from_brand_page'}]}) is False
    assert manu.no_image({'expressiveness': [], 'validation': {'ok': True, 'errors': []}}) is False


def test_the_diff_preview_and_artifacts(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'publishing')
    kinds = [r['kind'] for r in body['diff']]
    # 2M-1's weight rows (3 markup, 6 retailer pages) and the retired line. No GTIN row: every GTIN the brand
    # pages' markup and #33's feed state is one as written. No sellers row: #33's feed SKUs (sku_pg_…) are not
    # the pair's questions' variants, so no SKU has both sides.
    assert (kinds.count('markup'), kinds.count('page'), kinds.count('gtin'), kinds.count('sellers')) == (3, 6, 0, 0)
    assert [(r['field'], r['was'], r['now'], r['prov']) for r in body['diff'] if r['kind'] == 'lifecycle'] == [
        ('pure_protection.status', 'sold, per 4 of 6 agents', 'retired, successor AMORE', 'brand')]
    assert {r['source']['cycle'] for r in body['diff']} == {f2p1.CYCLE_2}
    assert body['preview'] == {
        'title': 'Four Pampers records, Manufacturer Center first',
        'note': "Compiled Oct 25 from Pampers 2R-1's feed and pampers.com. 2 of 4 valid. Held until Pampers 2R-1's "
                "team sends it.",
        'records': 4, 'valid': 2, 'compiled_at': f2r2.body('tenant-held')['merchants'][0]['held']['compiled_at'],
        'held': True, 'sent': None}
    assert [(a['channel'], a['records'], a['held'], a['blocked']) for a in body['artifacts']] == [
        ('manufacturer_center', 4, True, False), ('schema_org', 4, True, False), ('acp', 4, False, True)]
    assert body['artifacts'][2]['spec_clause'] == CLAUSE


def test_a_merchant_not_in_manufacturer_mode_is_unchanged(http, db, upstream):
    _shape(db, http, upstream)
    upstream.answer('GET', '/api/truesync/tenant', body=WS_TENANT, token=TOKEN_A)
    ts = _read(http, 'truesync', merchant=f2r2.PAIR_SLUG)
    assert not {'mode', 'surfaces', 'diff', 'preview', 'artifacts'} & set(ts)
    for endpoint in ('publishing', 'rules'):
        assert _read(http, endpoint, status=404, merchant=f2r2.PAIR_SLUG)['detail'] == \
            f"merchant '{f2r2.PAIR_SLUG}' is not in manufacturer mode"


# ── B2: /rules, its backtest, the switch ──────────────────────────────────

def test_rules_are_supply_s_words_and_the_backtest(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'rules')
    _dump('rules-2r2.json', body)
    supply = f2r2.body('rules')['rules']
    # every word of the rules is supply's (2R-2a A3); soa carries none
    for mine, theirs in zip(body['rules'], supply):
        assert (mine['id'], mine['name'], mine['detail'], mine['scope'], mine['outcome'], mine['on']) == \
            (theirs['code'], theirs['name'], theirs['detail'], theirs['scope'], theirs['outcome'], theirs['on'])
        assert mine['audience'] == [{'name': theirs['audience']}] and mine['audience_text'] == theirs['audience']
    assert {(r['approval'], r['approval_look']) for r in body['rules']} == {('needs_approval', 'needs_legal')}
    assert not {'title', 'sub', 'note'} & set(body)
    assert body['cycle'] == f2p1.CYCLE_2 and body['sent'] is None
    rows = {r['key']: r for r in body['backtest']}
    assert [(r['label'], r['before'], r['after']) for r in body['backtest']] == [
        ("Size 4 weight answers giving only the chart's range", '9 of 15', 'Next read'),
        ('Category answers naming Pure', '7 of 102', 'Next read'),
        ('Cheapest-place answers naming a live deal', '3 of 100', 'Next read')]
    unsent = ("After is the first cycle scored after Pampers 2R-1's team sends the file. A held file changes nothing an "
              "agent reads, so holding it starts no clock.")
    assert rows['attribute']['note'] == f'Swaddlers, Zzz and Baby-Dry, Oct 21. {unsent}'
    assert rows['retired']['note'] == f'AMORE named in 3, Oct 21. {unsent}'
    assert rows['promo']['note'] == f'Amazon multi-buy 2 and Amazon coupon 1, Oct 21. {unsent}'
    # the same helpers as the Overview: its retired line and its promo tile read the same counts
    over = _get(http, 'overview', cycle=f2p1.CYCLE_2, merchant=SLUG)
    pure = over['retired_named']['lines'][0]['brand_choice']['all']
    assert rows['retired']['before'] == f"{pure['named']} of {pure['answers']}"
    promo = over['promo_pass_through']
    assert rows['promo']['before'] == f"{promo['k']} of {promo['n']}"
    size4_misses = [m for m in over['attribute_accuracy']['misses'] if m['kind'] == 'answer' and m['size'] == 'Size 4']
    assert rows['attribute']['before'] == f'{15 - len(size4_misses)} of 15'


def test_putting_a_rule_is_forwarded_with_the_actor_operator_only(http, db, upstream):
    _shape(db, http, upstream)
    as_('alice')
    assert http.put('/api/console/rules/r4', params={'merchant': SLUG}, json={'on': True}).status_code == 403
    as_('op')
    r = http.put('/api/console/rules/r4', params={'merchant': SLUG, 'org': 10},
                 json={'approval': 'approved', 'note': 'Legal signed Oct 24'})
    assert r.status_code == 200, r.text
    put = [c for c in upstream.calls if c['method'] == 'PUT']
    assert put == [{'method': 'PUT', 'path': f'{BASE}/rules/r4', 'token': TOKEN_A, 'params': None,
                    'json': {'approval': 'approved', 'note': 'Legal signed Oct 24', 'actor': 'op@test'}}]
    assert [x['id'] for x in r.json()['rules']] == ['r1', 'r2', 'r3', 'r4', 'r5', 'r6']   # the re-read list
    bad = lambda body: http.put('/api/console/rules/r4', params={'merchant': SLUG, 'org': 10}, json=body).status_code  # noqa: E731
    assert bad({}) == 422
    assert bad({'approval': 'pending'}) == 422     # 2R-2's assumed state; supply's are needs_approval/approved/declined


# ── B3: sent is a fact the brand states; Impact unlocks on it ─────────────

def test_impact_is_locked_until_the_brand_says_it_sent_the_file(http, db, upstream):
    _shape(db, http, upstream)
    assert _read(http, 'revenue', cycle=f2p1.CYCLE_2)['locked'] == {
        'state': 'locked', 'title': 'Cause shows once Pampers 2R-1 publishes the record',
        'text': ("TrueSync can tie a change in these answers to a fix only after Pampers 2R-1's team publishes the "
                 "Pampers record to Manufacturer Center and pampers.com. Until then every figure here is a count of "
                 "answers you can audit.")}


def test_the_sent_statement_goes_to_supply_as_33_takes_it(http, db, upstream):
    _shape(db, http, upstream)
    as_('alice')   # the brand states it: a member may
    post = lambda body: http.post('/api/console/publishing/sent', params={'merchant': SLUG}, json=body)  # noqa: E731
    r = post({'channel': 'manufacturer_center', 'sent_at': '2026-10-25T23:00:00Z', 'stated_by': 'P&G content team',
              'note': 'uploaded in Manufacturer Center'})
    assert r.status_code == 200, r.text
    [call] = [c for c in upstream.calls if c['method'] == 'POST']
    assert call['token'] == TOKEN_A and call['path'] == f'{BASE}/publications/sent'
    assert call['json'] == {'channel': 'manufacturer_center', 'sent_at': '2026-10-25T23:00:00Z',
                            'stated_by': 'P&G content team', 'actor': 'alice@test',
                            'note': 'uploaded in Manufacturer Center'}
    assert r.json()['recorded'] == 4 and r.json()['mode'] == 'manufacturer'
    # ACP is blocked: nothing held to send, as supply says it (and soa does not ask it)
    r = post({'channel': 'acp', 'sent_at': '2026-10-25T23:00:00Z', 'stated_by': 'P&G content team'})
    assert r.status_code == 409 and r.json()['detail'] == "acp is blocked for 'pampers-2r1'; nothing was held to send"
    assert r.json()['detail'] == f2r2.body('sent-acp-409')['detail']
    assert post({'channel': 'manufacturer_center', 'sent_at': 'yesterday', 'stated_by': 'x'}).status_code == 422
    assert post({'channel': 'manufacturer_center', 'sent_at': '2999-01-01', 'stated_by': 'x'}).status_code == 422
    assert post({'channel': 'manufacturer_center', 'sent_at': '2026-10-25T23:00:00Z', 'stated_by': ' '}).status_code == 422
    assert len([c for c in upstream.calls if c['method'] == 'POST']) == 1


def test_a_send_cannot_predate_its_compile(http, db, upstream):
    """2R-2b. #33 compiled the held Manufacturer Center file Oct 25 (22:02 UTC) and accepted a send stated for
    Oct 17; soa refuses it before forwarding, naming both dates. Later the same day is recorded."""
    _shape(db, http, upstream)
    compiled = f2r2.body('tenant-held')['merchants'][0]['held']['compiled_at']
    assert compiled.startswith('2026-10-25T22:')
    as_('alice')
    post = lambda sent_at: http.post('/api/console/publishing/sent', params={'merchant': SLUG},  # noqa: E731
                                     json={'channel': 'manufacturer_center', 'sent_at': sent_at,
                                           'stated_by': 'P&G content team'})
    r = post('2026-10-17T15:30:00Z')
    assert r.status_code == 422, r.text
    assert r.json()['detail'] == (
        f"sent_at 2026-10-17T15:30:00Z is before the held manufacturer_center file was compiled "
        f"({compiled}+00:00): a file cannot be sent before it exists")
    assert not [c for c in upstream.calls if c['method'] == 'POST']   # never forwarded
    r = post('2026-10-25T23:00:00Z')
    assert r.status_code == 200, r.text
    assert r.json()['recorded'] == 4
    assert [c['json']['sent_at'] for c in upstream.calls if c['method'] == 'POST'] == ['2026-10-25T23:00:00Z']


def test_once_sent_impact_and_the_backtest_read_the_next_cycle(http, db, upstream):
    _shape(db, http, upstream, sent='2026-10-17')
    locked = _read(http, 'revenue', cycle=f2p1.CYCLE_2)['locked']
    _dump('revenue-locked-2r2.json', locked)
    assert (locked['state'], locked['title']) == ('unlocked', 'What moved since the record was sent (Oct 17)')
    assert (locked['before'], locked['after'], locked['status']) == (f2p1.CYCLE_1, f2p1.CYCLE_2, 'compared')
    assert (locked['sent']['stated_by'], locked['sent']['by']) == ('P&G content team', 'alice@test')
    assert [(m['label'], m['then'], m['now'], m['delta']) for m in locked['rows']] == [
        ('Attribute accuracy', '61 of 79', '62 of 79', '+1'), ('Retailer coverage', '38 of 49', '40 of 49', '+2'),
        ('Promo pass-through', '5 of 100', '3 of 100', '-2'), ('Category presence', '51 of 102', '51 of 102', '0')]
    rules = _read(http, 'rules')
    assert (rules['cycle'], rules['after_cycle']) == (f2p1.CYCLE_1, f2p1.CYCLE_2)
    rows = {r['key']: r for r in rules['backtest']}
    assert (rows['promo']['before'], rows['promo']['after']) == ('5 of 100', '3 of 100')
    assert rows['promo']['note'].endswith(f'After is {f2p1.CYCLE_2} (Oct 21), the first cycle scored after the send on Oct 17.')
    pub = _read(http, 'publishing')
    mfc = pub['surfaces'][0]
    # the sent line is /tenant's `held.sent`, never a recount
    assert (mfc['last'], mfc['sent']) == ('File compiled Oct 25, sent Oct 17', '2026-10-17T15:30:00+00:00')
    assert pub['preview']['note'] == ("Compiled Oct 25 from Pampers 2R-1's feed and pampers.com. 2 of 4 valid. "
                                      "Pampers 2R-1's team says it sent it on Oct 17.")


def test_a_send_after_the_newest_cycle_waits_for_the_next_read(http, db, upstream):
    _shape(db, http, upstream, sent='2026-10-23')
    locked = _read(http, 'revenue', cycle=f2p1.CYCLE_2)['locked']
    assert (locked['state'], locked['rows'], locked['after']) == ('unlocked', None, None)
    assert locked['note'] == 'The first cycle scored after Oct 23 has not run yet. Each figure moves on that read.'
    rows = _read(http, 'rules')['backtest']
    assert {r['after'] for r in rows} == {'Next read'}
    assert rows[0]['note'].endswith('After is the first cycle scored after the send on Oct 23. None has run yet.')


# ── A2: the compile trigger ───────────────────────────────────────────────

def test_compiling_is_operator_only_forwarded_and_says_what_was_not_compiled(http, db, upstream):
    _shape(db, http, upstream)
    as_('alice')
    assert http.post('/api/console/publishing/compile', params={'merchant': SLUG}).status_code == 403
    as_('op')
    r = http.post('/api/console/publishing/compile', params={'merchant': SLUG, 'org': 10})
    assert r.status_code == 200, r.text
    [call] = [c for c in upstream.calls if c['method'] == 'POST']
    assert (call['path'], call['token'], call['params']) == (f'{BASE}/publish', TOKEN_A, None)
    compiled = r.json()['compile']
    assert compiled['dry_run'] is False and compiled['rows'] == 12
    assert compiled['by_channel'] == {'schema_org': {'held_for_merchant': 4}, 'manufacturer_center': {'held_for_merchant': 4},
                                      'acp': {'blocked': 4}}
    assert compiled['not_compiled'] == f2r2.body('publish')['skipped']
    assert r.json()['surfaces'][0]['records'] == '2 of 4 valid'   # the re-read Publishing
    upstream.answer('POST', f'{BASE}/publish', body=f2r2.body('publish-dry-run'), token=TOKEN_A)
    r = http.post('/api/console/publishing/compile', params={'merchant': SLUG, 'org': 10, 'dry_run': 'true'})
    assert r.status_code == 200 and r.json()['compile']['dry_run'] is True
    assert [c for c in upstream.calls if c['method'] == 'POST'][-1]['params'] == {'dry_run': 'true'}


# ── B4: the file through soa ──────────────────────────────────────────────

def test_the_artifact_comes_through_soa_with_33_s_headers(http, db, upstream):
    pub_id = _shape(db, http, upstream)
    as_('alice')
    get = lambda **p: http.get('/api/console/truesync/artifact', params={'merchant': SLUG, **p})  # noqa: E731
    r = get(channel='manufacturer_center')
    assert r.status_code == 200, r.text
    assert r.content == f2r2.content('artifact-manufacturer_center')
    recorded = f2r2.recorded('artifact-manufacturer_center')['headers']
    for header in ('content-disposition', 'x-truesync-compiled-at', 'x-truesync-record-count', 'x-truesync-validator',
                   'x-truesync-merchant-kind', 'x-truesync-mode'):
        assert r.headers[header] == recorded[header], header
    assert r.headers['x-truesync-validator'] == 'ok=2; failed=2'
    assert TOKEN_A not in r.text and TOKEN_A not in json.dumps(dict(r.headers))
    [call] = [c for c in upstream.calls if '/artifacts' in c['path']]
    assert (call['token'], call['params']) == (TOKEN_A, {'channel': 'manufacturer_center'})
    # one publication's file
    r = get(channel='manufacturer_center', publication_id=pub_id)
    assert r.status_code == 200 and r.content == f2r2.content('artifact-publication')
    assert r.headers['x-truesync-reason'] == 'held_for_merchant'
    assert get(channel='manufacturer_center', publication_id=999).status_code == 404   # not the merchant's
    assert get(channel='ucp_uip').status_code == 404
    # ACP while blocked: supply's 409 with its clause, as JSON, never a file
    upstream.answer('GET', f'{BASE}/artifacts', status=409, body=f2r2.body('artifact-acp'), token=TOKEN_A)
    r = get(channel='acp')
    assert r.status_code == 409 and r.headers['content-type'].startswith('application/json')
    assert r.json()['spec_clause'] == CLAUSE and r.json()['reason'] == 'blocked' and r.json()['record_count'] == 4


def test_cors_exposes_the_download_headers_on_the_artifact_route(http, db, upstream):
    """2R-2b: the console (another origin) reads the filename and the X-TrueSync-* lines of the file it downloads.
    Starlette answers the preflight, then names the exposed headers on the GET itself."""
    _shape(db, http, upstream)
    origin = 'http://localhost:5173'
    as_('alice')
    preflight = http.options('/api/console/truesync/artifact', headers={
        'Origin': origin, 'Access-Control-Request-Method': 'GET',
        'Access-Control-Request-Headers': 'authorization, x-parleo-customer'})
    assert preflight.status_code == 200 and preflight.headers['access-control-allow-origin'] == origin
    r = http.get('/api/console/truesync/artifact', params={'merchant': SLUG, 'channel': 'manufacturer_center'},
                 headers={'Origin': origin})
    assert r.status_code == 200, r.text
    exposed = [h.strip().lower() for h in r.headers['access-control-expose-headers'].split(',')]
    assert exposed == ['content-disposition', 'x-truesync-compiled-at', 'x-truesync-record-count',
                       'x-truesync-validator']
    assert r.headers['content-disposition'] == f2r2.recorded('artifact-manufacturer_center')['headers']['content-disposition']


def test_the_artifact_is_kept_per_compiled_at(http, db, upstream, monkeypatch):
    _shape(db, http, upstream)
    monkeypatch.setenv('SOA_CONSOLE_CACHE', '1')
    console_cache.clear()
    as_('alice')

    def fetch():
        r = http.get('/api/console/truesync/artifact', params={'merchant': SLUG, 'channel': 'manufacturer_center'})
        assert r.status_code == 200
        return sum(1 for c in upstream.calls if '/artifacts' in c['path'])
    assert fetch() == 1
    assert fetch() == 1                 # the same compile: kept
    # #33's second recording compiled the same records again, a few seconds later: a new file
    upstream.answer('GET', '/api/truesync/publications', body=f2r2.body('sent-20261023/publications-sent'), token=TOKEN_A)
    assert fetch() == 2


# ── the rules by hand ─────────────────────────────────────────────────────

def test_the_markup_gtin_is_the_brand_page_s_json_ld():
    pages = [{'url': p['url'], 'observed_at': p['observed_at'], 'brand_page': p['brand_page']}
             for p in f2r2.recorded('brand-pages').values()]
    gtins = manu.markup_gtins(pages)
    # each page's hasVariant Products, by its line: Swaddlers Size 4 and Zzz Size 4 among them
    assert {'gtin': '037000799818', 'size': 'Size 4', 'line': 'Pampers Swaddlers'} in gtins
    assert [g for g in gtins if g['gtin'] == '037000833970'][0]['size'] == 'Size 4'
    assert manu.gtin_flags(pages) == []     # every one a GTIN as written
    # a Product whose gtin13 lost its leading zero (by hand: no recorded page has one)
    lost = [{'brand_page': {'line': 'Pampers AMORE', 'json_ld': {'@type': 'ProductGroup', 'hasVariant': [
        {'@type': 'Product', 'size': '1', 'gtin13': '30772244425'}]}}}]
    assert manu.gtin_flags(lost, brand='Pampers') == [
        {'field': 'amore.size_1.gtin (markup)', 'was': '30772244425', 'now': '030772244425', 'prov': 'parleo',
         'kind': 'gtin', 'where': 'markup', 'line': 'AMORE', 'digits': 11}]


def test_build_rules_maps_33_s_flat_approval():
    rules = manu.build_rules([{**f2r2.body('rules')['rules'][3], 'approval': a} for a in manu.APPROVAL_STATES])
    assert [(r['approval'], r['approval_look']) for r in rules] == [
        ('needs_approval', 'needs_legal'), ('approved', 'approved'), ('declined', 'returned')]
    assert manu.build_rules([{'code': 'r1', 'audience': 'All agents, Google agents'}])[0]['audience'] == \
        [{'name': 'All agents'}, {'name': 'Google agents'}]


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


# ── 2S-1: the brand page's read date, and possessives ─────────────────────

def _markup(pages, read_at, own='pampers.com'):
    surfaces = manu.build_surfaces(pubs=[], channels=[], drift=[], reference=None, pages=pages, flags=[],
                                   own_domain=own, rules=None, held=None, read_at=read_at)
    return next(s for s in surfaces if s['id'] == 'markup')


def test_the_site_markup_date_is_the_newest_brand_page_read_on_the_recorded_rows():
    rows = f2r2.body('retailer-prices')['prices']
    # supply serves the brand page on the own row itself (2O-6), never under a `brand_page` key
    assert not [r for r in rows if 'brand_page' in r]
    assert manu.brand_page_read_at(rows) == '2026-10-20T04:00:06.882849+00:00'
    pages = manu.brand_pages(rows, ['pampers.com'])
    assert [p['url'] for p in pages] == ['https://www.pampers.com/en-us/products/pampers-zzz',
                                         'https://www.pampers.com/en-us/products/pampers-swaddlers-diapers']
    assert pages[0]['brand_page']['size_chart'] and pages[0]['brand_page']['json_ld']
    assert _markup(pages, manu.brand_page_read_at(rows))['last'] == 'Read Oct 20'
    # the date is read across the merchant's rows, with no own-domain match needed
    assert _markup([], manu.brand_page_read_at(rows), own=None)['last'] == 'Read Oct 20'
    # "Not read yet" only when no row carries a brand page
    unread = [{k: v for k, v in r.items() if k not in manu.BRAND_PAGE_FIELDS} for r in rows]
    assert manu.brand_page_read_at(unread) is None and manu.brand_pages(unread, ['pampers.com']) == []
    assert _markup([], manu.brand_page_read_at(unread))['last'] == 'Not read yet'


@pytest.mark.parametrize('name, said', [('Pampers', "Pampers'"), ('P&G', "P&G's"), ('Wiggle & Snug', "Wiggle & Snug's")])
def test_one_possessive_for_every_brand_name(name, said):
    from soa_shared.possessive import possessive

    assert possessive(name) == said
    cycle = {'cycle_code': 'c1', 'start_date': '2026-10-21'}
    rows = manu.build_backtest({'attribute': (9, 15, ['Swaddlers'])}, cycle, None, None, None, name)
    assert f"after {said} team sends the file" in rows[0]['note']
    assert f"after {said} team publishes" in manu.locked_block(name=name, brand=None, domain=None)['text']
    held = {'id': 'mfc', 'records_total': 4, 'compiled_at': '2026-10-25', 'status': 'held', 'records': '2 of 4 valid',
            'records_valid': 2, 'errors': [], 'sent': None}
    note = manu.build_preview(surfaces=[held], brand=name, name=name, domain='example.com')['note']
    assert f"from {said} feed" in note and f"Held until {said} team sends it" in note
    assert "s's" not in note
    from app.services import console_revenue

    assert console_revenue.TEMPLATES['missed.title.retailer'].format(name=name, name_s=possessive(name)) == \
        f"{said} price is wrong"
