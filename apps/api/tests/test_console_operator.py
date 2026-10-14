"""
2C: the console's operator section (app/routers/console_ops.py) over HTTP:
Setup > Catalog over supply's 1B feed loader. Same fixtures and fake supply
as test_console_read_models.py. W&S (org 10) is Parleo-hosted, so its
catalog is the store config's, read-only; Brandco (org 20) is external, so
it has the feed loader. Supply payloads: fixtures/console/supply_feed_brandco.
json (shaped by supply's validate/views code) and the pipeline's real W&S
catalog fixture.
"""
import json
import os

from tests.test_console_read_models import (  # noqa: F401  (pytest fixtures)
    TOKEN_A, TOKEN_B, _fixture, as_, db, http, tenants, upstream,
)
from app.services import console_read_models as rm

HERE = os.path.dirname(__file__)
FEED = _fixture('supply_feed_brandco.json')
with open(os.path.join(HERE, '..', '..', 'pipeline', 'tests', 'fixtures', 'wiggle_and_snug_catalog.json')) as fh:
    WS_CATALOG = json.load(fh)['catalog']


def brandco_feed(upstream):
    tenants(upstream)
    upstream.answer('GET', '/api/truesync/merchants/brandco/feed', body=FEED['feed'], token=TOKEN_B)
    upstream.answer('GET', '/api/truesync/merchants/brandco/feed/history', body=FEED['history'], token=TOKEN_B)
    upstream.answer('POST', '/api/truesync/merchants/brandco/feed/validate', body=FEED['validate'], token=TOKEN_B)
    upstream.answer('GET', '/api/truesync/merchants/brandco/reference', body=FEED['reference'], token=TOKEN_B)
    upstream.answer('POST', '/api/truesync/merchants/brandco/feed/commit', token=TOKEN_B, body={
        'merchant': 'brandco', 'feed_version_id': 13, 'version_number': 3, 'committed_at': '2026-10-14T10:00:00+00:00',
        'row_count': 2, 'counts': {'ready': 2, 'warning': 0, 'error': 1}})


def test_a_member_cannot_open_the_operator_section(http, upstream):
    brandco_feed(upstream)
    as_('bob')
    for method, path in (('get', '/api/console/catalog?merchant=brandco'), ('get', '/api/console/catalog/versions?merchant=brandco'),
                         ('get', '/api/console/catalog/template.csv')):
        response = getattr(http, method)(path)
        assert response.status_code == 403 and response.json()['detail'].startswith('operator only')
    assert http.post('/api/console/catalog/commit', json={'merchant': 'brandco', 'upload_id': 'x'}).status_code == 403
    assert upstream.calls == []


def test_a_hosted_merchant_s_catalog_is_the_store_config_read_only(http, upstream):
    tenants(upstream)
    upstream.answer('GET', '/api/truesync/merchants/wiggle-and-snug/catalog', body=WS_CATALOG, token=TOKEN_A)
    as_('op')
    body = http.get('/api/console/catalog', params={'merchant': 'wiggle-and-snug', 'org': 10}).json()
    assert body['source'] == 'hosted' and body['read_only'] is True
    assert body['note'].startswith('Hosted on Parleo')
    assert len(body['rows']) == sum(len(l['variants']) for l in WS_CATALOG['listings'])
    first = body['rows'][0]
    assert first['product_name'] == 'Snug-Fit Diapers' and first['pack_count'] == 96 and first['price'] == '17.99'
    assert not any(c['path'].endswith('/feed') for c in upstream.calls)


def test_an_external_merchant_s_catalog_is_its_feed_and_versions(http, upstream):
    brandco_feed(upstream)
    as_('op')
    body = http.get('/api/console/catalog', params={'merchant': 'brandco', 'org': 20}).json()
    assert body['source'] == 'feed' and body['read_only'] is False
    assert body['version']['version_number'] == 2 and len(body['rows']) == 2
    assert [v['version_number'] for v in body['versions']] == [2, 1]
    assert {c['token'] for c in upstream.calls} == {TOKEN_B}


def test_an_external_merchant_with_no_feed_yet_is_empty_not_an_error(http, upstream):
    tenants(upstream)
    upstream.answer('GET', '/api/truesync/merchants/brandco/feed/history', body={'merchant': 'brandco', 'versions': []}, token=TOKEN_B)
    as_('op')
    response = http.get('/api/console/catalog', params={'merchant': 'brandco', 'org': 20})
    assert response.status_code == 200 and response.json()['source'] == 'none'


def test_validate_previews_with_the_multipack_warning_from_the_page(http, upstream):
    brandco_feed(upstream)
    as_('op')
    body = http.post('/api/console/catalog/validate', params={'merchant': 'brandco', 'org': 20},
                     files=[('files', ('skus.csv', b'gtin,product_name\n', 'text/csv'))]).json()
    assert body['upload_id'] == 'up_7f3c2a' and body['reference_checked'] is True
    wipes, diapers, balm = body['rows']
    assert wipes['status'] == 'warning'
    warning = wipes['messages'][-1]
    assert warning['code'] == 'multipack_suggested' and warning['severity'] == 'warning' and warning['suggested'] == 3
    assert warning['message'] == ('page shows a count but multipack is empty: target.com shows 3, 216, '
                                  'the row says pack_count 72, and multipack 3 would explain it')
    assert diapers['status'] == 'ready' and diapers['messages'] == []
    assert balm['status'] == 'error' and balm['messages'][0]['code'] == 'gtin_check_digit'
    assert body['summary'] == {**FEED['validate']['summary'], 'ready': 1, 'warning': 1, 'error': 1}


def test_validate_still_previews_when_no_page_was_read(http, upstream):
    brandco_feed(upstream)
    upstream.answer('GET', '/api/truesync/merchants/brandco/reference', status=404, body={'detail': 'no reference run'}, token=TOKEN_B)
    as_('op')
    body = http.post('/api/console/catalog/validate', params={'merchant': 'brandco', 'org': 20},
                     files=[('files', ('skus.csv', b'gtin\n', 'text/csv'))]).json()
    assert body['reference_checked'] is False and body['summary'] == FEED['validate']['summary']


def test_commit_and_versions_pass_through(http, upstream):
    brandco_feed(upstream)
    as_('op')
    committed = http.post('/api/console/catalog/commit', params={'org': 20},
                          json={'merchant': 'brandco', 'upload_id': 'up_7f3c2a', 'mode': 'all_valid_rows'}).json()
    assert committed['version_number'] == 3
    post = [c for c in upstream.calls if c['method'] == 'POST'][0]
    assert post['json'] == {'upload_id': 'up_7f3c2a', 'mode': 'all_valid_rows'} and post['token'] == TOKEN_B
    assert http.post('/api/console/catalog/commit', params={'org': 20},
                     json={'merchant': 'brandco', 'upload_id': 'x', 'mode': 'yolo'}).status_code == 422
    versions = http.get('/api/console/catalog/versions', params={'merchant': 'brandco', 'org': 20}).json()
    assert [v['version_number'] for v in versions['versions']] == [2, 1]


def test_the_multipack_warning_never_fires_without_a_page_count():
    preview = {'rows': [{'gtin': '012345678905', 'pack_count': 72, 'multipack': 3, 'status': 'ready', 'messages': []},
                        {'gtin': '012345678912', 'pack_count': None, 'multipack': None, 'status': 'ready', 'messages': []}]}
    out = rm.annotate_feed_preview(preview, FEED['reference'])
    assert [r['status'] for r in out['rows']] == ['ready', 'ready']
