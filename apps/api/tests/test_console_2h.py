"""
2H: one org, several merchants. The Wiggle & Snug org (10) holds the store
(`wiggle-and-snug`, seller, Parleo-hosted) and the brand
(`wiggle-and-snug-brand`, brand, customer-hosted); Brandco's org (20) one
merchant. Supply answers with the recorded /tenant and /retailers payloads
(tests/fixtures/console/README.md, 2H). Every test runs on sqlite and on a
local Postgres (test_console_2c3a's db fixture).
"""
import json

import pytest
from sqlalchemy import text

from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import (  # noqa: F401  (fixtures)
    BRANDCO_TENANT, CYCLE, TOKEN_A, TOKEN_B, _fixture, as_, http, start, upstream,
)

TENANT_2H = _fixture('supply_tenant_ws_2h.json')
RETAILERS = _fixture('supply_retailers_ws_2h.json')
STORE, BRAND = 'wiggle-and-snug', 'wiggle-and-snug-brand'


@pytest.fixture
def supply(upstream):
    upstream.answer('GET', '/api/truesync/tenant', body=TENANT_2H, token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/tenant', body=BRANDCO_TENANT, token=TOKEN_B)
    for slug in (STORE, BRAND):
        upstream.answer('GET', f'/api/truesync/merchants/{slug}/retailers', body=RETAILERS[slug], token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/merchants/brandco/retailers',
                    body={'own_domain': 'brandco.test', 'own_domains': ['brandco.test'], 'domains': []}, token=TOKEN_B)
    return upstream


# ═══ B.1 the merchants, per org ══════════════════════════════════════════

def test_the_switcher_lists_each_orgs_merchants_primary_first(http, db, supply):
    as_('op')
    orgs = {o['id']: o for o in http.get('/api/console/me').json()['orgs']}
    assert orgs[10]['merchants'] == [
        {'slug': STORE, 'name': 'Wiggle & Snug', 'kind': 'seller', 'hosting': 'parleo', 'domain': 'trueshopstore.com', 'primary': True},
        {'slug': BRAND, 'name': 'Wiggle & Snug Brand', 'kind': 'brand', 'hosting': 'external', 'domain': 'wiggleandsnug.com', 'primary': False}]
    assert [m['slug'] for m in orgs[20]['merchants']] == ['brandco'] and orgs[20]['merchants'][0]['primary'] is True
    # the org's own fields stay what 2C-0 served: the primary merchant's
    assert (orgs[10]['slug'], orgs[10]['kind'], orgs[10]['domain']) == (STORE, 'seller', 'trueshopstore.com')


def test_each_orgs_merchants_are_read_with_its_own_token(http, db, supply):
    as_('op')
    http.get('/api/console/me')
    by = {c['path']: c['token'] for c in supply.calls}
    assert by[f'/api/truesync/merchants/{BRAND}/retailers'] == TOKEN_A
    assert by['/api/truesync/merchants/brandco/retailers'] == TOKEN_B


# ═══ B.2 ?merchant= on every endpoint that resolves one ══════════════════

MERCHANT_ENDPOINTS = [
    ('/api/console/runs', {}), ('/api/console/full-loop/latest', {}), ('/api/console/studio/studies', {}),
    ('/api/console/truesync', {}), ('/api/console/record/list', {}), ('/api/console/record', {'product': '91'}),
    ('/api/console/accessibility', {}), ('/api/console/overview', {'cycle': CYCLE}),
    ('/api/console/score', {'cycle': CYCLE}), ('/api/console/catalog', {}),
]


@pytest.mark.parametrize('path, params', MERCHANT_ENDPOINTS)
def test_a_slug_that_is_not_the_orgs_is_a_404(http, db, supply, path, params):
    as_('op')
    r = http.get(path, params={'org': 10, 'merchant': 'brandco', **params})
    assert r.status_code == 404 and r.json()['detail'] == "merchant 'brandco' not found"


# ═══ B.3 cycles belong to one merchant ═══════════════════════════════════

def test_the_cycle_list_is_the_merchants(http, db, supply):
    as_('op')
    store = http.get('/api/console/runs', params={'org': 10, 'merchant': STORE}).json()
    assert [r['id'] for r in store] == [CYCLE]
    assert http.get('/api/console/runs', params={'org': 10}).json() == store            # absent: the primary
    assert http.get('/api/console/runs', params={'org': 10, 'merchant': BRAND}).json() == []


def test_a_study_generated_for_the_brand_is_the_brands(http, db, supply):
    _brand_study(db)
    as_('op')
    brand = http.get('/api/console/runs', params={'org': 10, 'merchant': BRAND}).json()
    assert [r['id'] for r in brand] == ['WSB-1']
    assert 'WSB-1' not in [r['id'] for r in http.get('/api/console/runs', params={'org': 10}).json()]


def _brand_study(db):
    with db.begin() as c:
        c.execute(text("""INSERT INTO soa_query_generation_jobs (id, study_type, study_name, status, organization_id,
            customer_organization_id, syndicated_merchant, tier_config) VALUES (900, 'ws-brand', 'W&S brand', 'complete', 1, 10,
            :m, :t)"""), {'m': BRAND, 't': json.dumps({'merchant': {'slug': BRAND, 'brand': 'Wiggle & Snug'}})})
        c.execute(text("""INSERT INTO soa_cycles (id, cycle_code, study_type, study_pattern, status, cycle_mode, start_date,
            organization_id) VALUES (900, 'WSB-1', 'ws-brand', 'brand_at_retail', 'complete', 'query', '2026-10-16', 1)"""))


# ═══ B.5 studies name their merchant ═════════════════════════════════════

def test_the_study_list_is_the_merchants_and_names_it(http, db, supply):
    _brand_study(db)
    as_('op')
    store = http.get('/api/console/studio/studies', params={'org': 10}).json()
    assert [s['merchant'] for s in store] == [{'slug': STORE, 'name': 'Wiggle & Snug'}]
    brand = http.get('/api/console/studio/studies', params={'org': 10, 'merchant': BRAND}).json()
    assert [(s['merchant']['slug'], s['merchant']['name']) for s in brand] == [(BRAND, 'Wiggle & Snug Brand')]


# ═══ B.4 a full loop runs for the merchant it names ══════════════════════

def test_a_loop_is_queued_for_the_brand_and_the_latest_is_per_merchant(http, db, supply):
    _brand_study(db)
    as_('alice')
    r = start(http, merchant_slug=BRAND, study_type='ws-brand')
    assert r.status_code == 202
    assert [c for c in supply.calls if c['path'] != '/api/truesync/tenant'] == []   # no supply call to start one
    with db.connect() as c:
        assert c.execute(text("SELECT merchant_slug FROM soa_full_loop_requests WHERE id = :i"),
                         {'i': r.json()['full_loop_id']}).scalar() == BRAND
    as_('op')
    assert http.get('/api/console/full-loop/latest', params={'org': 10, 'merchant': BRAND}).json()['merchant'] == BRAND
    assert http.get('/api/console/full-loop/latest', params={'org': 10}).json() is None   # the store has none


def test_a_loop_for_another_merchant_than_its_studys_is_refused(http, db, supply):
    as_('alice')
    r = start(http, merchant_slug=BRAND)                     # ws-2b-fixture was generated for the store
    assert r.status_code == 404
    assert start(http).status_code == 202
