"""
2C: /api/console/truesync, the TrueSync matrix, over HTTP. Supply answers
with the web app's real W&S captures (web/src/components/merchant-command-
center/__fixtures__/, Aug 2026: channels, publications, a schema_org
fetch_probe and merchant_center gmc_diagnostics on listing 90) and the
pipeline's real W&S catalog fixture (listings 90-94). manufacturer_center
is added to /channels as supply's seed has it (channels_seed.py); its
mc_acceptance rows are the shape supply's MC-1 serves
(docs/truesync/manufacturer-center-lane.md), synthetic: no tenant has a
Manufacturer Center account connected yet.
"""
import copy
import json
import os

from tests.test_console_read_models import (  # noqa: F401  (pytest fixtures)
    TOKEN_A, TOKEN_B, as_, db, http, upstream,
)
from app.services import console_read_models as rm

HERE = os.path.dirname(__file__)
WEB = os.path.join(HERE, '..', 'web', 'src', 'components', 'merchant-command-center', '__fixtures__')


def _web(name):
    with open(os.path.join(WEB, name)) as fh:
        return json.load(fh)


with open(os.path.join(HERE, '..', '..', 'pipeline', 'tests', 'fixtures', 'wiggle_and_snug_catalog.json')) as fh:
    WS_CATALOG = json.load(fh)['catalog']
MC_CHANNEL = {'slug': 'manufacturer_center', 'name': 'Google Manufacturer Center', 'depth_label': 'Acceptance read back',
              'spec_version': 'manufacturers-v1-2026-10-05', 'is_active': True, 'verification_surface': 'acceptance',
              'extension_status': None, 'extension_status_reason': None, 'connected': False}
PROVENANCE = {'merchant': 'wiggle-and-snug', 'merchant_source': 'published',
              'deals': {'scrape': 0, 'published': 3}, 'listings': {'scrape': 0, 'published': 5}, 'journal': []}


def channels(connected=False):
    out = [{**c, 'connected': None} for c in _web('channels.json')]
    return out[:2] + [{**MC_CHANNEL, 'connected': connected}] + out[2:]


def envelope(*per_listing):
    return {'merchant': 'wiggle-and-snug', 'listings': list(per_listing)}


def mc_row(listing_id, acceptance, origin='parleo', created_at='2026-10-10T09:00:00+00:00'):
    return {'id': 900 + listing_id, 'listing_id': listing_id, 'gtin': '00020000000039', 'channel_slug': 'manufacturer_center',
            'phase': 'after', 'method': 'mc_acceptance', 'created_at': created_at, 'observed': {},
            'outcome': 'approved' if acceptance == 'approved' else 'not_approved',
            'drift': {'acceptance': acceptance, 'approved': acceptance == 'approved', 'origin': origin,
                      'name': 'US:en:00020000000039', 'issues': [], 'destinations': [], 'origin_basis': 'test'}}


def supply(upstream, *, connected=False, mc_rows=(), mc_publications=()):
    base = '/api/truesync/merchants/wiggle-and-snug'
    upstream.answer('GET', '/api/truesync/channels', body=channels(connected), token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/publications', body=_web('publications.json') + list(mc_publications), token=TOKEN_A)
    upstream.answer('GET', f'{base}/catalog', body=WS_CATALOG, token=TOKEN_A)
    upstream.answer('GET', f'{base}/provenance', body=PROVENANCE, token=TOKEN_A)
    upstream.answer('GET', f'{base}/verifications', body=envelope(
        _web('verifications-fetch-probe.json'), _web('verifications-gmc.json'),
        *([{'listing_id': r['listing_id'], 'lineage': {}, 'verifications': [r]} for r in mc_rows])), token=TOKEN_A)


def read(http):
    as_('alice')
    response = http.get('/api/console/truesync', params={'merchant': 'wiggle-and-snug'})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_matrix_is_the_catalog_by_the_tenant_s_channels(http, upstream):
    supply(upstream)
    body = read(http)
    assert [c['id'] for c in body['channels']] == ['schema_org', 'merchant_center', 'manufacturer_center', 'acp',
                                                    'ucp_uip', 'deals_api', 'mcp', 'deal_directory']
    assert [p['listing_id'] for p in body['products']] == [90, 91, 92, 93, 94]
    first = body['products'][0]
    assert first['name'] == 'Snug-Fit Diapers' and first['provenance'] == 'published'
    assert 'snug-fit-diapers-s1-small' in first['variant_ids']
    assert {c['token'] for c in upstream.calls} == {TOKEN_A}


def test_cells_keep_publish_state_drift_and_acceptance_apart(http, upstream):
    supply(upstream)
    cells = read(http)['products'][0]['cells']
    schema = cells['schema_org']
    # Published; the fetch_probe after the publish found nothing: verified, no drift.
    assert schema['s'] == 'published' and schema['d'] == 'none' and schema['at'].startswith('2026-08-24T22:35')
    gmc = cells['merchant_center']
    # Supply's newest merchant_center row for 90 failed ("not implemented in Step 2"): blocked, with
    # the reason; the gmc_diagnostics read is 404, which is not_found, never drift.
    assert gmc['s'] == 'blocked' and gmc['note'] == 'not implemented in Step 2' and gmc['d'] == 'unverified'
    assert cells['acp']['s'] == 'blocked'
    assert cells['deal_directory']['s'] == 'published'


def test_manufacturer_center_reads_not_connected_without_an_account(http, upstream):
    supply(upstream, connected=False, mc_rows=[mc_row(90, 'approved')])
    for product in read(http)['products']:
        mc = product['cells']['manufacturer_center']
        assert mc['s'] == 'na' and mc['note'] == 'not connected' and mc['connected'] is False


def test_manufacturer_center_acceptance_and_the_gmc_sync_origin(http, upstream):
    pub = lambda lid: {'id': 7000 + lid, 'record_ref': f'listing:{lid}', 'listing_id': lid, 'channel_slug': 'manufacturer_center',
                       'payload': {'apiVersion': 'v1', 'products': [{'name': 'US:en:00020000000039', 'attributes': {}}]},
                       'validation': {'ok': True, 'errors': []}, 'expressiveness': [{'field': 'amount_off', 'severity': 'dropped', 'note': 'MC carries no offer'}],
                       'spec_version': 'manufacturers-v1-2026-10-05', 'status': 'published',
                       'external_ref': 'accounts/1234567/products/US:en:00020000000039',
                       'compiled_at': '2026-10-09T08:00:00+00:00', 'published_at': '2026-10-09T08:01:00+00:00', 'error': None}
    supply(upstream, connected=True, mc_publications=[pub(90), pub(91), pub(92), pub(93)],
           mc_rows=[mc_row(90, 'approved'), mc_row(91, 'pending'), mc_row(92, 'disapproved'), mc_row(93, 'not_found', origin='gmc_sync')])
    products = {p['listing_id']: p for p in read(http)['products']}
    got = {lid: (p['cells']['manufacturer_center']['acceptance'], p['cells']['manufacturer_center'].get('origin')) for lid, p in products.items()}
    assert got == {90: ('approved', 'parleo'), 91: ('pending', 'parleo'), 92: ('disapproved', 'parleo'),
                   93: ('not_found', 'gmc_sync'), 94: (None, None)}
    assert products[94]['cells']['manufacturer_center']['s'] == 'not_published'
    assert products[90]['validator']['manufacturer_center'] == [{'field': 'amount_off', 'verdict': 'dropped', 'note': 'MC carries no offer'}]
    assert json.loads(products[90]['payload']['manufacturer_center'])['products'][0]['name'] == 'US:en:00020000000039'


def test_a_record_older_than_the_publish_counts_for_nothing():
    catalog = {'listings': [{'listing_id': 1, 'title': 'X', 'variants': []}]}
    pubs = [{'id': 1, 'listing_id': 1, 'channel_slug': 'schema_org', 'status': 'published', 'payload': {},
             'validation': {'ok': True, 'errors': []}, 'expressiveness': [], 'compiled_at': '2026-10-02', 'published_at': '2026-10-02'}]
    old = {'merchant': 'm', 'listings': [{'listing_id': 1, 'verifications': [
        {'channel_slug': 'schema_org', 'method': 'fetch_probe', 'created_at': '2026-10-01',
         'drift': {'outcome': 'ok', 'findings': [{'field': 'price'}]}}]}]}
    body = rm.build_truesync('m', channels=[{'slug': 'schema_org', 'is_active': True}], publications=pubs,
                             catalog=catalog, verifications={'schema_org': old}, provenance=None)
    cell = body['products'][0]['cells']['schema_org']
    assert cell['d'] == 'unverified' and 'at' not in cell
    fresh = copy.deepcopy(old)
    fresh['listings'][0]['verifications'][0]['created_at'] = '2026-10-03'
    cell = rm.build_truesync('m', channels=[{'slug': 'schema_org', 'is_active': True}], publications=pubs, catalog=catalog,
                             verifications={'schema_org': fresh}, provenance=None)['products'][0]['cells']['schema_org']
    assert cell['d'] == 'drift' and cell['n'] == 1
    assert body['products'][0]['validator']['schema_org'] == [{'field': 'record', 'verdict': 'ok', 'note': 'valid against the spec'}]


def test_a_member_of_another_tenant_cannot_read_the_matrix(http, upstream):
    supply(upstream)
    as_('bob')
    assert http.get('/api/console/truesync', params={'merchant': 'wiggle-and-snug', 'org': 10}).status_code == 403
    assert upstream.calls == []
