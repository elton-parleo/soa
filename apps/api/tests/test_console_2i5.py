"""
2I-5: the console's Start cycle runs a study's first cycle. Before, a study
with no cycle and no soa_entities row for its brand was a 422 "create its
first cycle in Command Center"; now its set is soa_shared.comparison_sets'
(the coordinator's): the study's merchant as M001, its comparison_domains
from supply after it. Supply answers with the recorded 2H /tenant and the
brand's /retailers with a competitor list
(apps/pipeline/tests/fixtures/first_cycle/supply_ws_brand_2i5.json). On
sqlite and on a local Postgres (test_console_2c3a's db fixture).
"""
import json
import os

import pytest
from sqlalchemy import text

import app.routers.cycles as cycles_router
import app.services.console_studies as console_studies
from soa_shared.models.soa_models import SoaWorkerSurface
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import TOKEN_A, as_, http, upstream  # noqa: F401  (fixtures)

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, '..', '..', 'pipeline', 'tests', 'fixtures', 'first_cycle', 'supply_ws_brand_2i5.json')) as fh:
    SUPPLY = json.load(fh)
BRAND, STUDY = 'wiggle-and-snug-brand', 'ws_brand_smoke_test_1a2b3c'


@pytest.fixture
def first(db, upstream, monkeypatch):
    """The brand's smoke-test study as #120 records it, five active questions, never run."""
    with db.begin() as c:
        for col in ('truecost_tiers TEXT', 'created_by TEXT', 'source_lite_request_id INTEGER',
                    'study_series_id TEXT', 'prior_cycle_id INTEGER'):
            c.exec_driver_sql(f"ALTER TABLE soa_cycles ADD COLUMN {col}")
        if db.dialect.name == 'postgresql':   # the seed writes its ids; the serials start after them
            for table in ('soa_entities', 'soa_cycles', 'soa_cycle_entities', 'soa_query_generation_jobs', 'soa_queries'):
                c.exec_driver_sql(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT MAX(id) FROM {table}))")
        c.execute(text("INSERT INTO soa_query_generation_jobs (study_type, study_name, target_count, status, organization_id, "
                       "customer_organization_id, tier_config) VALUES (:st, 'W&S Brand smoke test', 5, 'complete', 1, 10, :t)"),
                  {'st': STUDY, 't': json.dumps({'merchant': {'slug': BRAND}})})
        for i in range(5):
            c.execute(text("INSERT INTO soa_queries (query_code, query_text, study_type, study_pattern, status, organization_id) "
                           "VALUES (:q, 'Best diapers?', :st, 'retailer', 'Active', 1)"), {'q': f'WSB-{i}', 'st': STUDY})
    SoaWorkerSurface.__table__.create(db, checkfirst=True)
    monkeypatch.setattr(cycles_router, 'engine', db)
    monkeypatch.setattr(console_studies, 'engine', db)
    upstream.answer('GET', '/api/truesync/tenant', body=SUPPLY['tenant'], token=TOKEN_A)
    upstream.answer('GET', f'/api/truesync/merchants/{BRAND}/retailers', body=SUPPLY['two'], token=TOKEN_A)
    return db


def test_start_cycle_on_a_never_run_study_is_201_with_the_merchant_and_its_competitors(http, first, upstream):
    as_('op')
    r = http.post('/api/console/cycles', params={'org': 10}, json={
        'study_type': STUDY, 'platforms': ['chatgpt'], 'cycle_code': 'WSB-FIRST'})
    assert r.status_code == 201, r.text
    assert r.json()['status'] == 'planned' and r.json()['total_runs_planned'] == 5
    with first.connect() as c:
        rows = [tuple(x) for x in c.execute(text(
            "SELECT e.slug, e.name, ce.comparison_code, ce.role FROM soa_cycle_entities ce JOIN soa_cycles cy ON cy.id = ce.cycle_id "
            "JOIN soa_entities e ON e.id = ce.entity_id WHERE cy.cycle_code = 'WSB-FIRST' ORDER BY ce.comparison_code"))]
    # pampers.com is not in this registry: created, named by its domain until the wizard (2I-6) names it.
    # huggies.com is the seeded Huggies entity's site: matched by domain, not created again.
    assert rows == [(BRAND, 'Wiggle & Snug Brand', 'M001', 'primary'), ('pampers-com', 'pampers.com', 'M002', 'competitor'),
                    ('huggies', 'Huggies', 'M003', 'competitor')]
    assert {c['path'] for c in upstream.calls} >= {'/api/truesync/tenant', f'/api/truesync/merchants/{BRAND}/retailers'}


def test_a_second_start_copies_the_first_and_reads_no_competitor_list(http, first, upstream):
    as_('op')
    assert http.post('/api/console/cycles', params={'org': 10}, json={
        'study_type': STUDY, 'platforms': ['chatgpt'], 'cycle_code': 'WSB-FIRST'}).status_code == 201
    upstream.calls.clear()
    assert http.post('/api/console/cycles', params={'org': 10}, json={
        'study_type': STUDY, 'platforms': ['chatgpt'], 'cycle_code': 'WSB-SECOND'}).status_code == 201
    assert not any('/retailers' in c['path'] for c in upstream.calls)


def test_a_study_with_no_merchant_is_a_422_saying_so(http, first):
    with first.begin() as c:
        c.execute(text("UPDATE soa_query_generation_jobs SET tier_config = NULL WHERE study_type = :st"), {'st': STUDY})
    as_('op')
    r = http.post('/api/console/cycles', params={'org': 10}, json={'study_type': STUDY, 'platforms': ['chatgpt']})
    assert r.status_code == 422 and r.json()['detail'] == 'could not create the cycle: the study belongs to no merchant'
