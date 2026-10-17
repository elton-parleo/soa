"""
2C: the console's Create Study endpoints (app/routers/console_ops.py,
app/services/console_studies.py) over HTTP. The preview runs the
generator's own catalog tiers (soa_shared/catalog_tiers.py) over the real
Wiggle & Snug catalog fixture the pipeline's tests use, so its questions
are the worker's, word for word. Same fake supply and W&S fixture cycle as
test_console_read_models.py.
"""
import json
import os

import pytest
from sqlalchemy import text

import app.routers.console_ops as console_ops
import app.routers.cycles as cycles_router
import app.routers.studies as studies_router
import app.services.console_studies as console_studies
from soa_shared import catalog_tiers as ct
from soa_shared.catalog_snapshot import build_snapshot
from soa_shared.models.soa_models import SoaWorkerSurface
from tests.test_console_read_models import (  # noqa: F401  (pytest fixtures)
    TOKEN_A, TOKEN_B, as_, db, http, tenants, upstream,
)

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, '..', '..', 'pipeline', 'tests', 'fixtures', 'wiggle_and_snug_catalog.json')) as fh:
    WS = json.load(fh)
BASE = '/api/truesync/merchants/wiggle-and-snug'
TIERS_ON = {'brand_direct': True, 'catalog_accuracy': True, 'value_incentives': True, 'category_control': False}


@pytest.fixture
def studies_db(db, monkeypatch):
    with db.begin() as c:
        for col in ('stage_targets TEXT', 'rotate_named_retailer BOOLEAN', 'naming_rule_enabled BOOLEAN',
                    'personas TEXT', 'specificity_mode TEXT', 'error_message TEXT', 'provenance TEXT',
                    'updated_at TIMESTAMP'):
            c.exec_driver_sql(f"ALTER TABLE soa_query_generation_jobs ADD COLUMN {col}")
        for col in ('truecost_tiers TEXT', 'created_by TEXT', 'source_lite_request_id INTEGER',
                    'study_series_id TEXT', 'prior_cycle_id INTEGER'):
            c.exec_driver_sql(f"ALTER TABLE soa_cycles ADD COLUMN {col}")
    for module in (console_ops, cycles_router, studies_router, console_studies):
        monkeypatch.setattr(module, "engine", db)
    return db


def ws_supply(upstream):
    tenants(upstream)
    upstream.answer('GET', f'{BASE}/catalog', body=WS['catalog'], token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/merchants', body=WS['merchants'], token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/incentives', body=WS['incentives'], token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/retailers', body={'merchant': 'wiggle-and-snug', 'own_domain': 'trueshopstore.com', 'domains': []}, token=TOKEN_A)


def preview(http, **body):
    as_('op')
    response = http.post('/api/console/studies/preview', params={'org': 10},
                         json={'merchant': 'wiggle-and-snug', 'tiers': TIERS_ON, 'stage_total': 50, **body})
    assert response.status_code == 200, response.text
    return response.json()


def test_members_cannot_open_the_generator(http, upstream, studies_db):
    ws_supply(upstream)
    as_('alice')
    assert http.get('/api/console/studies/options').status_code == 403
    assert http.post('/api/console/studies/preview', json={'merchant': 'wiggle-and-snug'}).status_code == 403
    assert http.post('/api/console/studies/generate', json={'study_name': 'x'}).status_code == 403
    assert http.post('/api/console/cycles', json={'study_type': 'ws-2b-fixture', 'platforms': ['chatgpt']}).status_code == 403
    assert upstream.calls == []


def test_options_are_constraints_surfaces_and_the_scope_s_merchants(http, upstream, studies_db):
    tenants(upstream)
    as_('op')
    body = http.get('/api/console/studies/options', params={'org': 10}).json()
    assert body['constraints']['stage'] == ['Awareness', 'Research', 'Comparison', 'Ready to Buy']
    assert [s['id'] for s in body['surfaces']][-2:] == ['gemini_web', 'chatgpt_web']
    assert [m['slug'] for m in body['merchants']] == ['wiggle-and-snug']
    assert (body['max_questions'], body['default_brand_direct_count'], body['default_variant_cap']) == (100, 12, 20)


def test_the_preview_is_the_generator_s_own_questions(http, upstream, studies_db):
    ws_supply(upstream)
    body = preview(http)
    assert body['merchant']['readback'] == '5 products, 19 variants, 6 GTINs, 2 live codes, Member Rewards (2 tiers)'
    snap = build_snapshot(WS['catalog'], merchants=WS['merchants'], incentives=WS['incentives'])
    rows, _ = ct.build_catalog_accuracy(snap, category='General', persona='Casual / Gift Buyer', study_pattern='brand_at_retail')
    accuracy = body['tiers']['catalog_accuracy']
    assert [q['query_text'] for q in accuracy['questions']] == [r['query_text'] for r in rows]
    assert accuracy['count'] == 19 and accuracy['sampled'] is False and accuracy['variant_cap'] == 20
    first = accuracy['questions'][0]
    assert first['query_text'] == 'What does the Wiggle & Snug Snug-Fit Diapers Size 1 small pack cost?'
    assert first['expected'] == ['Expected: $17.99', '96 count']
    assert first['expected_answer']['type'] == 'price'
    value = body['tiers']['value_incentives']
    assert value['count'] == 6 and value['mechanics'] == {'code': 2, 'member_price': 3, 'points': 1}
    assert [q['expected'] for q in value['questions'][:3]] == [
        ['Expected: WELCOME10, 10.00% off'], ['Expected: SNUG3, $3.00 off'], ['Expected: $17.79 (Member+)']]
    brand = body['tiers']['brand_direct']
    assert brand['count'] == 12 and brand['illustrative'] is True
    assert brand['questions'][0]['expected'] == ['Expected: brand named, trueshopstore.com cited']
    # 50 stage questions + 12 brand-direct + 19 + 6: the 87 catalog_tiers.py documents.
    assert body['tally'] == {'ai_written': 62, 'from_catalog': 25, 'total': 87, 'limit': 100, 'within': True, 'tone': 'ok',
                             'text': '62 AI-written + 25 from the catalog = 87 questions, within the 100 limit'}


def test_the_variant_cap_samples_and_says_so(http, upstream, studies_db):
    ws_supply(upstream)
    accuracy = preview(http, variant_cap=5)['tiers']['catalog_accuracy']
    assert accuracy['count'] == 5 and accuracy['sampled'] is True and accuracy['variants_available'] == 19


def test_an_unreadable_catalog_is_said_not_hidden(http, upstream, studies_db):
    tenants(upstream)
    upstream.answer('GET', f'{BASE}/catalog', status=502, body={'detail': 'supply down'}, token=TOKEN_A)
    body = preview(http)
    assert body['merchant']['available'] is False
    assert body['tiers']['catalog_accuracy']['unavailable'] and body['tiers']['catalog_accuracy']['count'] == 0
    assert body['tally']['total'] == 50


def test_generate_refuses_over_the_cap_server_side(http, upstream, studies_db):
    ws_supply(upstream)
    as_('op')
    response = http.post('/api/console/studies/generate', params={'org': 10}, json={
        'study_name': 'W&S after syndication', 'target_count': 70, 'syndicated_merchant': 'wiggle-and-snug', 'tiers': TIERS_ON})
    assert response.status_code == 422
    assert response.json()['detail'] == '82 AI-written + 25 from the catalog = 107 questions, over the 100 limit. Reduce a stage or untick a tier.'


def test_generate_queues_the_job_for_this_customer(http, upstream, studies_db):
    ws_supply(upstream)
    as_('op')
    response = http.post('/api/console/studies/generate', params={'org': 10}, json={
        'study_name': 'W&S after syndication', 'target_count': 50, 'study_pattern': 'brand_at_retail',
        'stage_targets': {'Awareness': 10, 'Research': 12, 'Comparison': 12, 'Ready to Buy': 16},
        'allowed_categories': ['Baby Care'], 'syndicated_merchant': 'wiggle-and-snug', 'tiers': TIERS_ON})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['status'] == 'pending' and body['tally']['total'] == 87
    with studies_db.connect() as c:
        job = c.execute(text("SELECT * FROM soa_query_generation_jobs WHERE study_type = :st"),
                        {'st': body['study_type']}).mappings().one()
    assert job['organization_id'] == 1 and job['customer_organization_id'] == 10 and job['created_by'] == 'op'
    assert json.loads(job['tier_config']) == {'brand_direct': {'enabled': True, 'count': 12}, 'catalog_accuracy': {'enabled': True},
                                              'value_incentives': {'enabled': True}, 'category_control': {'enabled': False}}
    with studies_db.begin() as c:  # Postgres defaults created_count to 0; this sqlite table has no default
        c.execute(text("UPDATE soa_query_generation_jobs SET created_count = 0 WHERE study_type = :st"), {'st': body['study_type']})
    status = http.get(f"/api/console/studies/{body['study_type']}/status", params={'org': 10}).json()
    assert status['status'] == 'pending' and status['syndicated_merchant'] == 'wiggle-and-snug'


def test_an_ungrounded_study_sends_no_brand_half(http, upstream, studies_db):
    # 2I-4: but it is still the console org's study (customer_organization_id),
    # and, with no merchant sent, the primary's
    tenants(upstream)
    as_('op')
    body = http.post('/api/console/studies/generate', params={'org': 10}, json={'study_name': 'Plain', 'target_count': 20}).json()
    with studies_db.connect() as c:
        job = c.execute(text("SELECT syndicated_merchant, tier_config, customer_organization_id FROM soa_query_generation_jobs "
                             "WHERE study_type = :st"), {'st': body['study_type']}).one()
    assert tuple(job) == (None, None, 10) and body['tally'] is None
    assert body['merchant']['from'] == 'primary'
    assert not any('/catalog' in c['path'] for c in upstream.calls)


def test_start_a_cycle_on_the_study_s_comparison_set(http, upstream, studies_db):
    SoaWorkerSurface.__table__.create(studies_db, checkfirst=True)
    with studies_db.begin() as c:
        c.execute(text("INSERT INTO soa_worker_surfaces (surface_id, configured, seen_at) "
                       "VALUES ('aimode', :f, CURRENT_TIMESTAMP)"), {'f': False})
    as_('op')
    refused = http.post('/api/console/cycles', params={'org': 10}, json={'study_type': 'ws-2b-fixture', 'platforms': ['chatgpt', 'aimode']})
    assert refused.status_code == 422 and refused.json()['detail']['code'] == 'surface_not_configured'
    started = http.post('/api/console/cycles', params={'org': 10}, json={
        'study_type': 'ws-2b-fixture', 'platforms': ['chatgpt', 'gemini_grounded'], 'cycle_code': 'WS-2C-TEST'})
    assert started.status_code == 201, started.text
    body = started.json()
    assert body['status'] == 'planned' and body['study_pattern'] == 'brand_at_retail'
    assert body['total_runs_planned'] == 6 * 2
    with studies_db.connect() as c:
        roles = c.execute(text("SELECT entity_id, role FROM soa_cycle_entities ce JOIN soa_cycles cy ON cy.id = ce.cycle_id "
                               "WHERE cy.cycle_code = 'WS-2C-TEST' ORDER BY entity_id")).all()
    assert [tuple(r) for r in roles] == [(1, 'primary'), (2, 'competitor')]
    other = http.post('/api/console/cycles', params={'org': 20}, json={'study_type': 'ws-2b-fixture', 'platforms': ['chatgpt']})
    assert other.status_code == 422 and 'not this customer' in other.json()['detail']
