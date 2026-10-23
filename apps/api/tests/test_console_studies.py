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
from tests.console_tables import add_columns
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
        add_columns(c, 'soa_query_generation_jobs', 'stage_targets', 'rotate_named_retailer', 'naming_rule_enabled',
                    'personas', 'specificity_mode', 'error_message', 'provenance', 'updated_at')
        add_columns(c, 'soa_cycles', 'truecost_tiers', 'created_by', 'source_lite_request_id', 'study_series_id',
                    'prior_cycle_id')
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
    # 2L-4: 19 where-to-buy and 19 cheapest-place, templates, which the stage
    # counts absorb: still 87, now 12 + 12 AI-written and 38 + 25 from the catalog
    assert [(i['intent'], i['count'], i['line']) for i in brand['intents']] == [
        ('where_to_buy', 19, '19 where-to-buy questions, one per sampled product, naming no retailer'),
        ('cheapest_place', 19, '19 cheapest-place questions, one per sampled product, naming no retailer'),
        # 2M-1: the Accuracy set, 10 attribute questions, which add to the study
        ('attribute', 10, '10 accuracy questions (weight range and pack count), one per sampled product, '
                          'naming no retailer, added to the study')]
    assert brand['intents'][0]['questions'][0]['query_text'] == 'Where can I buy Wiggle & Snug Snug-Fit Diapers Size 1 small pack?'
    assert (brand['absorbed'], brand['not_absorbed']) == (38, 0)
    assert body['tally'] == {'ai_written': 24, 'from_catalog': 73, 'total': 97, 'limit': 100, 'within': True, 'tone': 'ok',
                             'text': '24 AI-written + 73 from the catalog = 97 questions, within the 100 limit'}


def test_the_variant_cap_samples_and_says_so(http, upstream, studies_db):
    ws_supply(upstream)
    accuracy = preview(http, variant_cap=5)['tiers']['catalog_accuracy']
    assert accuracy['count'] == 5 and accuracy['sampled'] is True and accuracy['variants_available'] == 19


def test_the_control_line_says_none_names_the_brand(http, upstream, studies_db):
    """2I-7: the generator checks every category-control question against the
    brand's terms and drops one that still names it."""
    ws_supply(upstream)
    control = preview(http, tiers={**TIERS_ON, 'category_control': True})['tiers']['category_control']
    # 2L-4: 38 of the 50 are where-to-buy and cheapest-place questions instead
    assert (control['count'], control['additive'], control['checked']) == (12, False, True)
    assert control['line'] == '12 questions, none naming the brand'


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
    assert response.json()['detail'] == '44 AI-written + 73 from the catalog = 117 questions, over the 100 limit. Reduce a stage or untick a tier.'


def test_generate_queues_the_job_for_this_customer(http, upstream, studies_db):
    ws_supply(upstream)
    as_('op')
    response = http.post('/api/console/studies/generate', params={'org': 10}, json={
        'study_name': 'W&S after syndication', 'target_count': 50, 'study_pattern': 'brand_at_retail',
        'stage_targets': {'Awareness': 10, 'Research': 12, 'Comparison': 12, 'Ready to Buy': 16},
        'allowed_categories': ['Baby Care'], 'syndicated_merchant': 'wiggle-and-snug', 'tiers': TIERS_ON})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['status'] == 'pending' and body['tally']['total'] == 97   # 2M-1: 87 + 10 attribute
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


# 2N-1: the Create Study dialog shows soa's tally and absorbed line for the study as set, never
# its own count. Its old count took every intent out of the stage counts (48 here: 19 + 19 + 10),
# where soa takes only where-to-buy and cheapest-place (38): 87 in the dialog, 97 here. The bodies
# are the ones the dialog sends (balanced 50 over the fixture's four stages, the default tiers).
BALANCED = {'Awareness': 13, 'Research': 13, 'Comparison': 12, 'Ready to Buy': 12}
DIALOG_TIERS = {'brand_direct': True, 'catalog_accuracy': True, 'value_incentives': True, 'category_control': False}


def _sample(name, body):
    """SOA_2N1_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2N1_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


def test_the_tally_for_the_study_as_set(http, upstream, studies_db):
    ws_supply(upstream)
    catalog = preview(http, tiers={**DIALOG_TIERS, 'category_control': True}, stage_total=0)
    _sample('studies-preview-2n1-catalog.json', catalog)
    default = preview(http, tiers=DIALOG_TIERS, stage_total=50, stage_targets=BALANCED, brand_direct_count=12)
    _sample('studies-preview-2n1-default.json', default)
    assert default['tally']['text'] == '24 AI-written + 73 from the catalog = 97 questions, within the 100 limit'
    assert default['tiers']['brand_direct']['absorbed_line'] == (
        '38 taken out of the stage counts, Ready to Buy first, so the study stays the size you set')
    no_accuracy = preview(http, tiers={**DIALOG_TIERS, 'catalog_accuracy': False}, stage_total=50, stage_targets=BALANCED,
                          brand_direct_count=12)
    _sample('studies-preview-2n1-no-accuracy.json', no_accuracy)
    assert no_accuracy['tally']['text'] == '24 AI-written + 54 from the catalog = 78 questions, within the 100 limit'
    over = preview(http, tiers=DIALOG_TIERS, stage_total=70, stage_targets={**BALANCED, 'Awareness': 33}, brand_direct_count=12)
    _sample('studies-preview-2n1-over.json', over)
    # what generate refuses (test_generate_refuses_over_the_cap_server_side), word for word
    assert over['tally']['text'] == '44 AI-written + 73 from the catalog = 117 questions, over the 100 limit. Reduce a stage or untick a tier.'
    control = preview(http, tiers={**DIALOG_TIERS, 'category_control': True}, stage_total=50, stage_targets=BALANCED,
                      brand_direct_count=12)
    _sample('studies-preview-2n1-control.json', control)
    assert control['tiers']['category_control']['line'] == '0 questions, none naming the brand'
