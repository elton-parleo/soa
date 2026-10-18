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
        if db.dialect.name == 'postgresql':   # production's timestamptz (test_full_loop_2i's production_timestamps)
            for col in ('created_at', 'updated_at'):
                c.exec_driver_sql(f"ALTER TABLE soa_full_loop_requests ALTER COLUMN {col} TYPE TIMESTAMPTZ")
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


def test_a_second_start_copies_the_first_and_adds_a_newly_listed_competitor(http, first, upstream):
    """2I-6: rivals = the previous cycle's rivals, then the list's new ones, numbered on."""
    as_('op')
    assert http.post('/api/console/cycles', params={'org': 10}, json={
        'study_type': STUDY, 'platforms': ['chatgpt'], 'cycle_code': 'WSB-FIRST'}).status_code == 201
    later = {**SUPPLY['two'], 'comparison_domains': ['huggies.com', 'luvs.com']}   # pampers.com removed, luvs.com added
    upstream.answer('GET', f'/api/truesync/merchants/{BRAND}/retailers', body=later, token=TOKEN_A)
    assert http.post('/api/console/cycles', params={'org': 10}, json={
        'study_type': STUDY, 'platforms': ['chatgpt'], 'cycle_code': 'WSB-SECOND'}).status_code == 201
    with first.connect() as c:
        rows = [tuple(x) for x in c.execute(text(
            "SELECT e.slug, ce.comparison_code FROM soa_cycle_entities ce JOIN soa_cycles cy ON cy.id = ce.cycle_id "
            "JOIN soa_entities e ON e.id = ce.entity_id WHERE cy.cycle_code = 'WSB-SECOND' ORDER BY ce.comparison_code"))]
    # the removed pampers.com stays until an operator removes it from the set
    assert rows == [(BRAND, 'M001'), ('pampers-com', 'M002'), ('huggies', 'M003'), ('luvs-com', 'M004')]


def test_a_study_with_no_merchant_is_a_422_saying_so(http, first):
    with first.begin() as c:
        c.execute(text("UPDATE soa_query_generation_jobs SET tier_config = NULL WHERE study_type = :st"), {'st': STUDY})
    as_('op')
    r = http.post('/api/console/cycles', params={'org': 10}, json={'study_type': STUDY, 'platforms': ['chatgpt']})
    assert r.status_code == 422 and r.json()['detail'] == 'could not create the cycle: the study belongs to no merchant'


# ═══ B2: the request's failure reason, and the step it failed at ═════════
RUN = f'/api/truesync/merchants/{BRAND}/full-loop/41'
OCT16 = 'could not create the cycle: the study has no earlier cycle to take a comparison set from'

#: (step, the request as the coordinator leaves it at that failure, supply's run as GET answers it, the cycle)
FAILURES = [
    ('reads', {'supply_run_id': None, 'supply_status': None,
               'error': 'TrueSync full loop did not start: upstream returned 502'}, None, None),
    ('reads', {'supply_run_id': 41, 'supply_status': 'failed', 'error': 'supply full loop failed: render timed out'},
     'failed', None),
    ('reads', {'supply_run_id': 41, 'supply_status': 'running',
               'error': 'timed_out: no progress for 60 minutes (last: reference_pending)'}, 'running', None),
    ('cycle', {'supply_run_id': 41, 'supply_status': 'reference_done', 'error': OCT16}, 'reference_done', None),
    ('study', {'supply_run_id': 41, 'supply_status': 'failed', 'error': 'cycle failed: every run failed'},
     'failed', 'failed'),
    ('study', {'supply_run_id': 41, 'supply_status': 'reference_done',
               'error': 'timed_out: no progress for 60 minutes (last: cycle_planned)'}, 'reference_done', 'running'),
    ('scoring', {'supply_run_id': 41, 'supply_status': 'conflict',
                 'error': "supply refused the PATCH (409): full loop run 41 is already scored by cycle '7'"},
     'scored', 'complete'),
]


def failed_request(db, upstream, fields, run_status, cycle_status):
    cycle_id = None
    with db.begin() as c:
        if cycle_status:
            cycle_id = c.execute(text("INSERT INTO soa_cycles (cycle_code, study_type, study_pattern, status, cycle_mode, "
                                      "start_date, organization_id, full_loop_run_id) VALUES ('FL41-wsb-20261016', :st, "
                                      "'retailer', :s, 'query', '2026-10-16', 1, 41) RETURNING id"),
                                 {'st': STUDY, 's': cycle_status}).scalar()
        rid = c.execute(text("""INSERT INTO soa_full_loop_requests (organization_id, merchant_slug, study_type, platforms,
            runs_per_query, supply_run_id, supply_status, cycle_id, status, error, created_by, created_at, updated_at)
            VALUES (10, :m, :st, :p, 1, :run, :ss, :c, 'failed', :e, 'op', :t, :t) RETURNING id"""),
                        {'m': BRAND, 'st': STUDY, 'p': json.dumps(['chatgpt']), 'run': fields['supply_run_id'],
                         'ss': fields['supply_status'], 'c': cycle_id, 'e': fields['error'],
                         't': '2026-10-17T03:45:00+00:00'}).scalar()
    if run_status:
        upstream.answer('GET', RUN, body={'id': 41, 'status': run_status, 'finished_at': '2026-10-17T03:44:10+00:00'},
                        token=TOKEN_A)
    return rid


@pytest.mark.parametrize('step, fields, run_status, cycle_status', FAILURES)
def test_a_failed_request_names_its_step_and_keeps_its_error(http, first, upstream, step, fields, run_status, cycle_status):
    rid = failed_request(first, upstream, fields, run_status, cycle_status)
    as_('op')
    by_id = http.get(f'/api/full-loop/{rid}', params={'org': 10}).json()
    latest = http.get('/api/console/full-loop/latest', params={'org': 10, 'merchant': BRAND}).json()
    for view in (by_id, latest):
        assert (view['status'], view['failed_step'], view['error']) == ('failed', step, fields['error'])
    assert by_id == latest


def test_a_request_that_has_not_failed_has_no_failed_step(http, first, upstream):
    with first.begin() as c:
        rid = c.execute(text("""INSERT INTO soa_full_loop_requests (organization_id, merchant_slug, study_type, platforms,
            runs_per_query, supply_run_id, supply_status, status, created_by, created_at, updated_at)
            VALUES (10, :m, :st, '["chatgpt"]', 1, 41, 'reference_done', 'reference_done', 'op', NOW(), NOW()) RETURNING id"""),
                        {'m': BRAND, 'st': STUDY}).scalar()
    upstream.answer('GET', RUN, body={'id': 41, 'status': 'reference_done'}, token=TOKEN_A)
    as_('op')
    assert 'failed_step' not in http.get(f'/api/full-loop/{rid}', params={'org': 10}).json()
