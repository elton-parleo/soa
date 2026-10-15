"""
2C-1: /api/console/visibility and /api/console/record{,/list}, over HTTP.

Visibility reads the W&S fixture cycle (tests/fixtures/console/ws_fixture_cycle.
json): Layer 1 coded mentions and the stored Layer 2 extractions. The rules
the fixture cannot show (other brands, the roll-up, sources, span position,
a first pick outside the coded set) are tested on build_visibility with rows
shaped like cycle 229's (FL3-wiggle-and-snug-20261014).

The record reads supply as test_console_truesync.py fakes it: the pipeline's
real W&S catalog (listings 90-94), the web app's real publications and
channels, plus the W&S reference read (supply_reference_ws.json,
illustrative) and Brandco, soa's external test fake, served from its feed.
"""
import copy
import json
import os

from tests.test_console_read_models import (  # noqa: F401  (pytest fixtures)
    BRANDCO_TENANT, CYCLE, OWNED, TOKEN_A, TOKEN_B, WS_TENANT, as_, db, http, upstream,
)
from tests.test_console_truesync import PROVENANCE, WS_CATALOG, _web, channels, envelope
from tests.console_schema import check
from app.services import console_read_models as rm

HERE = os.path.dirname(__file__)


def _fixture(name):
    with open(os.path.join(HERE, 'fixtures', 'console', name)) as fh:
        return json.load(fh)


with open(os.path.join(HERE, '..', '..', 'pipeline', 'tests', 'fixtures', 'wiggle_and_snug_catalog.json')) as fh:
    WS_INCENTIVES = json.load(fh)['incentives']
WS_REFERENCE = _fixture('supply_reference_ws.json')
BRANDCO = _fixture('supply_feed_brandco.json')
WS = '/api/truesync/merchants/wiggle-and-snug'


# ═══ Visibility ═══════════════════════════════════════════════════════════

def test_visibility_is_per_surface_with_the_agent_split(http):
    as_('alice')
    body = http.get('/api/console/visibility', params={'cycle': CYCLE}).json()
    check(body, 'Visibility')
    assert body['cycle'] == CYCLE and len(body['byQuestion']) == 8
    ranking = body['ranking']
    # grounded_api is the highest-fidelity surface with answered runs; consumer_ui (aimode) had none.
    assert ranking['surface'] == 'grounded_api'
    assert ranking['denoms'] == {'grounded_api': 7, 'consumer_ui': 0} and ranking['denom'] == 7
    [ws] = ranking['rows']
    assert ws['name'] == 'Wiggle & Snug' and ws['you'] is True
    assert (ws['named'], ws['first']) == (6, 6)
    assert ws['surfaces']['grounded_api']['agents'] == {'chatgpt': {'named': 2, 'first': 2},
                                                        'gemini': {'named': 4, 'first': 4}}
    assert ws['surfaces']['consumer_ui'] == {'named': 0, 'first': 0, 'agents': {}}
    assert ranking['agent_denoms']['grounded_api'] == {'chatgpt': 3, 'gemini': 4}
    # Huggies is in the comparison set but no answer named it: not a row.
    assert [r['name'] for r in ranking['rows']] == ['Wiggle & Snug']
    assert [t['tier'] for t in body['tiers']] == ['brand_direct', 'catalog_accuracy']


def test_a_run_layer_1_did_not_code_names_nobody(http):
    as_('alice')
    rows = {r['run']: r for r in http.get('/api/console/visibility', params={'cycle': CYCLE}).json()['byQuestion']}
    assert rows['run-1005']['named'] == [] and rows['run-1005']['first'] is None
    assert rows['run-1001']['first'] == {'name': 'Wiggle & Snug', 'you': True}
    assert rows['run-1001']['first_basis'] == 'layer1_position'
    wall = rows['run-1008']
    assert wall['answered'] is False and wall['surface'] == 'consumer_ui' and wall['agent'] == 'aimode'


def test_visibility_is_tenant_scoped(http):
    as_('bob')
    assert http.get('/api/console/visibility', params={'cycle': CYCLE}).status_code == 404
    assert http.get('/api/console/visibility', params={'cycle': CYCLE, 'org': 10}).status_code == 403
    as_('op')
    assert http.get('/api/console/visibility', params={'cycle': CYCLE, 'org': 10}).status_code == 200


ENTITIES = [{'name': 'Wiggle & Snug', 'role': 'primary', 'aliases': ['Wiggle and Snug']},
            {'name': 'Huggies', 'role': 'competitor', 'aliases': []},
            {'name': 'Pampers', 'role': 'competitor', 'aliases': []}]


def _run(rid, tier='catalog_accuracy', platform='chatgpt', status='answered'):
    return {'id': rid, 'platform': platform, 'run_number': 1, 'surface': 'grounded_api', 'answer_status': status,
            'query_code': f'Q{rid}', 'query_text': f'question {rid}', 'tier': tier, 'stage': 'Awareness'}


def test_other_brands_roll_up_and_sources_are_left_out():
    """Rows like cycle 229's: Layer 2 names product lines ('Huggies Snug &
    Dry'), spellings ('HUGGIES'), sources and brands outside the set."""
    extractions = {
        1: {'other_brands_named': [{'name': 'Huggies Snug & Dry', 'presented_as': 'closest_match'},
                                   {'name': 'Millie Moon Overnight Diapers', 'presented_as': 'closest_match'}]},
        2: {'other_brands_named': [{'name': 'HUGGIES', 'presented_as': 'closest_match'},
                                   {'name': 'Millie Moon', 'presented_as': 'comparison'},
                                   {'name': 'Babylist', 'presented_as': 'source', 'relation': 'citation_only'},
                                   {'name': 'amallow.com', 'presented_as': 'comparison', 'relation': 'citation_only'}]},
    }
    mentions = [{'run_id': 1, 'name': 'Wiggle & Snug', 'position': 1, 'role': 'primary'},
                {'run_id': 2, 'name': 'Wiggle & Snug', 'position': 1, 'role': 'primary'}]
    body = rm.build_visibility('C', runs=[_run(1), _run(2)], entities=ENTITIES, mentions=mentions, extractions=extractions)
    rows = {r['name']: r for r in body['ranking']['rows']}
    assert set(rows) == {'Wiggle & Snug', 'Huggies', 'Millie Moon'}
    assert rows['Huggies']['named'] == 2 and rows['Huggies']['first'] == 0 and rows['Huggies']['you'] is False
    assert rows['Millie Moon']['named'] == 2
    assert body['sources_left_out'] == 2
    first = body['byQuestion'][0]
    assert first['named'] == [{'name': 'Wiggle & Snug', 'you': True}, {'name': 'Huggies', 'you': False},
                              {'name': 'Millie Moon', 'you': False}]


def test_first_pick_is_layer_1_position_1_then_span_position():
    spans = [{'id': 1, 'text': "I couldn't find that exact product."},
             {'id': 2, 'text': 'If you meant **Millie Moon Overnight Diapers**, Target has them at $26.99.'},
             {'id': 3, 'text': 'If you meant Huggies Overnites, Walmart has them.'}]
    extractions = {
        # Layer 1 coded Huggies at position 2: something outside the set came first, and Layer 2 says which.
        1: {'other_brands_named': [{'name': 'Huggies', 'presented_as': 'closest_match'},
                                   {'name': 'Millie Moon', 'presented_as': 'closest_match'}], 'spans': spans},
        # Layer 1 coded nothing: Layer 2 alone, by span position.
        2: {'other_brands_named': [{'name': 'Huggies', 'presented_as': 'closest_match'},
                                   {'name': 'Millie Moon', 'presented_as': 'closest_match'}], 'spans': spans},
        # Not located in any span: the first listed.
        4: {'other_brands_named': [{'name': 'Pampers Swaddlers', 'presented_as': 'comparison'}], 'spans': []},
    }
    mentions = [{'run_id': 1, 'name': 'Huggies', 'position': 2, 'role': 'competitor'},
                {'run_id': 3, 'name': 'Pampers', 'position': 3, 'role': 'competitor'},
                {'run_id': 5, 'name': 'Pampers', 'position': 1, 'role': 'competitor'},
                {'run_id': 5, 'name': 'Wiggle & Snug', 'position': 2, 'role': 'primary'}]
    runs = [_run(1), _run(2), _run(3, tier=None), _run(4), _run(5, tier=None)]
    body = rm.build_visibility('C', runs=runs, entities=ENTITIES, mentions=mentions, extractions=extractions)
    by = {r['run']: r for r in body['byQuestion']}
    assert by['run-1']['first'] == {'name': 'Millie Moon', 'you': False} and by['run-1']['first_basis'] == 'span_position'
    assert by['run-2']['first'] == {'name': 'Millie Moon', 'you': False}
    # An unprompted answer has no Layer 2: Pampers at position 3 means another brand came first,
    # and no coding names it.
    assert by['run-3']['first'] is None and by['run-3']['first_basis'] == 'uncoded'
    assert by['run-3']['tier'] == 'unprompted' and by['run-3']['type'] == 'Awareness'
    assert by['run-4']['first'] == {'name': 'Pampers', 'you': False} and by['run-4']['first_basis'] == 'coded_order'
    assert by['run-5']['first'] == {'name': 'Pampers', 'you': False}
    assert body['ranking']['first_uncoded'] == {'grounded_api': 1}
    assert body['ranking']['agent_first_uncoded'] == {'grounded_api': {'chatgpt': 1}}
    assert body['tiers'][0] == {'tier': 'unprompted', 'label': 'Unprompted'}


def test_an_unanswered_run_is_outside_every_denominator():
    runs = [_run(1), _run(2, status='no_ai_answer'), _run(3, platform='gemini_grounded')]
    mentions = [{'run_id': 1, 'name': 'Wiggle & Snug', 'position': 1, 'role': 'primary'},
                {'run_id': 2, 'name': 'Wiggle & Snug', 'position': 1, 'role': 'primary'}]
    body = rm.build_visibility('C', runs=runs, entities=ENTITIES, mentions=mentions, extractions={})
    ws = body['ranking']['rows'][0]
    assert body['ranking']['denom'] == 2 and (ws['named'], ws['first']) == (1, 1)
    assert body['ranking']['agent_denoms'] == {'grounded_api': {'chatgpt': 1, 'gemini': 1}}


# ═══ Offer record ═════════════════════════════════════════════════════════

def ws_supply(upstream, *, reference=WS_REFERENCE, provenance=PROVENANCE, tenant=WS_TENANT):
    upstream.answer('GET', '/api/truesync/tenant', body=tenant, token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/channels', body=channels(), token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/publications', body=_web('publications.json'), token=TOKEN_A)
    upstream.answer('GET', f'{WS}/catalog', body=WS_CATALOG, token=TOKEN_A)
    upstream.answer('GET', f'{WS}/provenance', body=provenance, token=TOKEN_A)
    upstream.answer('GET', f'{WS}/incentives', body=WS_INCENTIVES, token=TOKEN_A)
    upstream.answer('GET', f'{WS}/incentives/owned', body=OWNED, token=TOKEN_A)
    upstream.answer('GET', f'{WS}/verifications', body=envelope(
        _web('verifications-fetch-probe.json'), _web('verifications-gmc.json')), token=TOKEN_A)
    if reference is not None:
        upstream.answer('GET', f'{WS}/reference', body=reference, token=TOKEN_A)


def record(http, product, merchant='wiggle-and-snug', **params):
    response = http.get('/api/console/record', params={'merchant': merchant, 'product': product, **params})
    assert response.status_code == 200, response.text
    body = response.json()
    check(body, 'Record_')
    return body


def test_the_record_list_is_the_published_catalog(http, upstream):
    ws_supply(upstream)
    as_('alice')
    body = http.get('/api/console/record/list', params={'merchant': 'wiggle-and-snug'}).json()
    assert [p['listing_id'] for p in body['products']] == [90, 91, 92, 93, 94]
    by = {p['listing_id']: p for p in body['products']}
    assert by[91]['sku'] == next(l['product_id'] for l in WS_CATALOG['listings'] if l['listing_id'] == 91)
    assert by[91]['status'] == {'label': '1 page difference', 'tone': 'warn'} and by[91]['diffs'] == 1
    assert by[93]['status'] == {'label': 'Published to 4 channels', 'tone': 'ok'}
    assert body['kind'] == 'brand' and body['hosting'] == 'parleo'
    assert {c['token'] for c in upstream.calls} == {TOKEN_A}


def test_a_field_the_page_disagrees_with_carries_was_and_diff(http, upstream):
    ws_supply(upstream)
    as_('alice')
    sku = next(l['product_id'] for l in WS_CATALOG['listings'] if l['listing_id'] == 91)
    body = record(http, sku)
    [diff] = [f for f in body['fields'] if f.get('diff')]
    assert diff['k'] == 'Name · Snug-Fit Overnight Diapers Size 6 (42 ct)'
    assert diff['v'] == 'Snug-Fit Overnight Diapers Size 6 (42 ct)'
    assert diff['was'] == 'Overnight Diapers Size 6, 42 Count'
    assert diff['prov'] == 'brand' and diff['finding'] == 'name_differs'
    assert diff['note'] == ('trueshopstore.com, read 2026-10-09 by our own fetch. only in the record: snug fit')
    assert body['kind'] == 'product'          # W&S is a brand
    v6 = next(v for v in body['variants'] if v['id'] == 'snug-fit-overnight-s6')
    assert v6['status'] == 'Page differs: name' and v6['tone'] == 'warn'
    assert next(v for v in body['variants'] if v['id'] == 'snug-fit-overnight-s3')['status'] == 'Not read yet'
    # Every field of a brand's published record is the brand's.
    assert {f['prov'] for f in body['fields']} == {'brand'}


def test_pack_differs_shows_on_the_record(http, upstream):
    ws_supply(upstream)
    as_('alice')
    body = record(http, '92')                   # the listing id works as well as the sku
    [diff] = [f for f in body['fields'] if f.get('diff')]
    assert (diff['k'], diff['v'], diff['was']) == ('Pack count · Cloud Wipes 3-Pack', '216', '3')


def test_issues_variants_member_price_and_the_artifact(http, upstream):
    ws_supply(upstream)
    as_('alice')
    body = record(http, '93')
    assert body['title'] == 'Bum Balm 4 oz' and body['sub'] == 'Wiggle & Snug · 1 variant · trueshopstore.com'
    fields = {f['k']: f for f in body['fields']}
    assert fields['Price']['v'] == '$12.99' and fields['Member price']['v'] == '$10.99'
    assert fields['GTIN'] == {'k': 'GTIN', 'v': '884400896186', 'prov': 'brand', 'mono': True}
    [v] = body['variants']
    assert v['price'] == '$12.99 · member $10.99' and v['status'] == 'Matches the page' and v['tone'] == 'ok'
    blocked = body['issues'][0]
    assert blocked['title'].startswith('Not published to ') and blocked['tone'] == 'warn'
    assert 'not implemented in Step 2' in blocked['detail']
    assert all(i['tone'] in ('bad', 'warn', 'neu') for i in body['issues'])
    artifact = json.loads(body['json'])
    assert body['json_channel'] == 'schema_org' and artifact
    assert body['json'].startswith('{\n  ')   # pretty-printed


def test_a_record_with_no_reference_read_still_renders(http, upstream):
    ws_supply(upstream, reference=None)
    as_('alice')
    body = record(http, '93')
    assert not any(f.get('diff') for f in body['fields'])
    assert body['variants'][0]['status'] == 'Not read yet'
    assert list(body['read_errors']) == ['reference']


def test_scraped_listings_are_parleo_s_observation(http, upstream):
    ws_supply(upstream, provenance={**PROVENANCE, 'listings': {'scrape': 5, 'published': 0}})
    as_('alice')
    assert {f['prov'] for f in record(http, '93')['fields']} == {'parleo'}


def test_an_unknown_merchant_kind_is_neutral_never_a_crash(http, upstream):
    tenant = copy.deepcopy(WS_TENANT)
    tenant['merchants'][0]['kind'] = None
    ws_supply(upstream, tenant=tenant)
    as_('alice')
    assert {f['prov'] for f in record(http, '93')['fields']} == {'unknown'}


def test_an_unknown_product_is_404(http, upstream):
    ws_supply(upstream)
    as_('alice')
    response = http.get('/api/console/record', params={'merchant': 'wiggle-and-snug', 'product': 'nope'})
    assert response.status_code == 404 and 'nope' in response.json()['detail']


def brandco_supply(upstream, catalog):
    base = '/api/truesync/merchants/brandco'
    upstream.answer('GET', '/api/truesync/tenant', body=BRANDCO_TENANT, token=TOKEN_B)
    upstream.answer('GET', '/api/truesync/channels', body=channels(), token=TOKEN_B)
    upstream.answer('GET', '/api/truesync/publications', body=[], token=TOKEN_B)
    if catalog is not None:
        upstream.answer('GET', f'{base}/catalog', body=catalog, token=TOKEN_B)
    upstream.answer('GET', f'{base}/provenance', body={'merchant': 'brandco', 'merchant_source': 'published',
                                                     'listings': {'scrape': 0, 'published': 0}}, token=TOKEN_B)
    upstream.answer('GET', f'{base}/reference', body=BRANDCO['reference'], token=TOKEN_B)
    upstream.answer('GET', f'{base}/incentives', body={'merchant': 'brandco', 'listings': []}, token=TOKEN_B)


#: supply's feed-served catalog (truesync/feed/serve.py catalog()) for Brandco's current feed,
#: with the wipes row's price left empty, as a brand's feed may.
BRANDCO_CATALOG = {'merchant': 'brandco', 'listings': [
    {'listing_id': 501, 'product_url': None, 'published_at': '2026-10-08T10:00:00+00:00', 'spec_version': 'sku-feed-v1',
     'product_id': 'feed:brandco:00012345678905', 'title': 'Brandco Wipes', 'brand': 'Brandco',
     'variants': [{'variant_id': '00012345678905', 'title': '72 ct', 'size': None, 'count': 72, 'attributes': {},
                   'list_price': None, 'currency': None, 'gtin': '00012345678905'}]},
    {'listing_id': 502, 'product_url': None, 'published_at': '2026-10-08T10:00:00+00:00', 'spec_version': 'sku-feed-v1',
     'product_id': 'feed:brandco:00012345678912', 'title': 'Brandco Diapers Size 3', 'brand': 'Brandco',
     'variants': [{'variant_id': '00012345678912', 'title': '84 ct', 'size': None, 'count': 84, 'attributes': {},
                   'list_price': '22.99', 'currency': 'USD', 'gtin': '00012345678912'}]}]}


def test_an_external_seller_s_feed_with_no_price_reads_not_carried(http, upstream):
    brandco_supply(upstream, BRANDCO_CATALOG)
    as_('bob')
    body = record(http, 'feed:brandco:00012345678905', merchant='brandco')
    fields = {f['k']: f for f in body['fields']}
    assert fields['Price']['v'] == 'not carried' and fields['Product page']['v'] == 'not carried'
    assert body['variants'][0]['price'] == 'not carried'
    assert body['kind'] == 'offer' and body['status'] == {'label': '1 page difference', 'tone': 'warn'}
    [diff] = [f for f in body['fields'] if f.get('diff')]
    assert (diff['k'], diff['v'], diff['was']) == ('Pack count · 72 ct', '72', '216, 3')
    assert diff['note'].startswith('target.com, read 2026-10-09 by our own fetch')
    # A seller publishes its own record: the retailer's. Nothing compiled for an external feed.
    assert {f['prov'] for f in body['fields']} == {'retail'} and body['json'] == ''
    assert {c['token'] for c in upstream.calls} == {TOKEN_B}


def test_a_merchant_with_no_record_yet_is_an_empty_list(http, upstream):
    brandco_supply(upstream, None)
    as_('bob')
    body = http.get('/api/console/record/list', params={'merchant': 'brandco'}).json()
    assert body['products'] == [] and body['hosting'] == 'external'


def test_the_record_is_tenant_scoped(http, upstream):
    ws_supply(upstream)
    as_('bob')
    assert http.get('/api/console/record/list', params={'merchant': 'wiggle-and-snug', 'org': 10}).status_code == 403
    as_('op')
    assert http.get('/api/console/record/list', params={'merchant': 'wiggle-and-snug', 'org': 10}).status_code == 200


def test_provenance_mapping_is_stated_once():
    assert rm.record_prov('published', 'seller') == 'retail'
    assert rm.record_prov('published', 'brand') == 'brand'
    assert rm.record_prov('scrape', 'seller') == 'parleo' and rm.record_prov('scrape', None) == 'parleo'
    assert rm.record_prov('agent', 'brand') == 'agent'
    assert rm.record_prov('published', None) == 'unknown' and rm.record_prov(None, 'brand') == 'unknown'
