"""
2B §5 and §6: the console read models and "Run full loop", over HTTP.

The data is the W&S fixture cycle (tests/fixtures/console/ws_fixture_cycle.
json, built by apps/pipeline/scripts/build_console_fixture.py from real
Wiggle & Snug golden answers scored by the real classifier). Supply is a fake
upstream that answers by token, so "the right tenant's token went up" is
asserted, not assumed. Shapes are checked against fixtures/console/
console_types.schema.json, derived from the console's types.ts and studio.ts.

Users:
  op     operator (staff org 1)    — may read any org with ?org=
  alice  member of org 10 (W&S)    — pinned to W&S
  bob    member of org 20 (Brandco)— pinned to Brandco
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import StaticPool

import app.console_scope as console_scope_module
import app.routers.console as console_router
import app.routers.full_loop as full_loop_router
import clients.truesync_client as truesync_client_module
import soa_shared.config as config
import soa_shared.customers as customers
from app.app import app
from app.auth import verify_token
from app.services import console_read_models as rm
from tests.console_schema import check

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures', 'console')
TOKEN_A = "tst_aaaaaaaaaaaaaaaa_" + "A" * 43
TOKEN_B = "tst_bbbbbbbbbbbbbbbb_" + "B" * 43
CYCLE = 'WS-2B-FIXTURE'


def _fixture(name):
    with open(os.path.join(FIXTURES, name)) as fh:
        return json.load(fh)


def _encode(value):
    return json.dumps(value) if isinstance(value, (dict, list)) else value


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(config, "SOA_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(config, "TRUESYNC_TENANT_TOKEN", "")
    monkeypatch.setattr(config, "TRUESYNC_API_BASE", "https://supply.example")
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _now(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

    data = _fixture('ws_fixture_cycle.json')
    with engine.begin() as c:
        c.exec_driver_sql("""CREATE TABLE organizations (id INTEGER PRIMARY KEY, name TEXT UNIQUE,
            created_at TIMESTAMP, truesync_tenant_slug TEXT UNIQUE, truesync_token_sealed TEXT,
            truesync_token_id TEXT)""")
        c.exec_driver_sql("""CREATE TABLE organization_members (id INTEGER PRIMARY KEY,
            organization_id INTEGER, user_id TEXT, email TEXT, role TEXT DEFAULT 'member',
            is_operator BOOLEAN NOT NULL DEFAULT 0, created_at TIMESTAMP)""")
        c.exec_driver_sql("""CREATE TABLE soa_query_generation_jobs (id INTEGER PRIMARY KEY,
            study_type TEXT UNIQUE, study_name TEXT, description TEXT, target_count INTEGER,
            created_count INTEGER, status TEXT, organization_id INTEGER, customer_organization_id INTEGER,
            created_by TEXT, created_at TIMESTAMP, study_pattern TEXT, allowed_categories TEXT,
            retailer_names TEXT, syndicated_merchant TEXT, tier_config TEXT)""")
        c.exec_driver_sql("""CREATE TABLE soa_entities (id INTEGER PRIMARY KEY, name TEXT, slug TEXT,
            entity_type TEXT, category TEXT, website_url TEXT, aliases TEXT)""")
        c.exec_driver_sql("""CREATE TABLE soa_cycles (id INTEGER PRIMARY KEY, cycle_code TEXT UNIQUE,
            study_type TEXT, study_pattern TEXT, status TEXT, cycle_mode TEXT, start_date DATE,
            end_date DATE, total_runs_planned INTEGER, completed_runs INTEGER, platforms TEXT,
            runs_per_query INTEGER, organization_id INTEGER, created_at TIMESTAMP, notes TEXT,
            full_loop_run_id INTEGER, reference_prices TEXT)""")
        c.exec_driver_sql("""CREATE TABLE soa_cycle_entities (id INTEGER PRIMARY KEY, cycle_id INTEGER,
            entity_id INTEGER, comparison_code TEXT, role TEXT)""")
        c.exec_driver_sql("""CREATE TABLE soa_queries (id INTEGER PRIMARY KEY, query_code TEXT,
            query_text TEXT, category TEXT, stage TEXT, specificity TEXT, persona TEXT, status TEXT,
            study_type TEXT, study_pattern TEXT, organization_id INTEGER, tier TEXT,
            expected_answer TEXT, provenance TEXT, source_ref TEXT)""")
        c.exec_driver_sql("""CREATE TABLE soa_runs (id INTEGER PRIMARY KEY, cycle_id INTEGER,
            query_id INTEGER, platform TEXT, run_number INTEGER, run_at TIMESTAMP, raw_response TEXT,
            status TEXT, surface TEXT, collector TEXT, answer_status TEXT, retrieved_sources TEXT)""")
        c.exec_driver_sql("""CREATE TABLE soa_expectation_outcomes (id INTEGER PRIMARY KEY,
            run_id INTEGER, query_id INTEGER, cycle_id INTEGER, platform TEXT, tier TEXT,
            expected_answer TEXT, extraction TEXT, outcome TEXT, outcome_reason TEXT, flags TEXT,
            claim_results TEXT, source_split TEXT, reason_code TEXT, surface TEXT,
            source_attribution TEXT, domain_cited BOOLEAN)""")
        c.exec_driver_sql("""CREATE TABLE soa_coded_mentions (id INTEGER PRIMARY KEY, run_id INTEGER,
            entity_id INTEGER, mentioned BOOLEAN, position INTEGER)""")
        c.exec_driver_sql("""CREATE TABLE soa_full_loop_requests (id INTEGER PRIMARY KEY,
            organization_id INTEGER, merchant_slug TEXT, study_type TEXT, platforms TEXT,
            runs_per_query INTEGER, allow_hosted_render BOOLEAN NOT NULL DEFAULT 1,
            supply_run_id INTEGER, supply_status TEXT, cycle_id INTEGER,
            status TEXT, error TEXT, created_by TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)""")

        for table, rows in (('organizations', data['organizations']),
                            ('soa_query_generation_jobs', data['generation_jobs']),
                            ('soa_entities', data['entities']), ('soa_cycles', data['cycles']),
                            ('soa_cycle_entities', data['cycle_entities']),
                            ('soa_queries', data['queries']),
                            ('soa_runs', [{k: v for k, v in r.items() if not k.startswith('_')}
                                          for r in data['runs']]),
                            ('soa_expectation_outcomes', data['outcomes']),
                            ('soa_coded_mentions', data['coded_mentions'])):
            for row in rows:
                cols = [k for k in row if k != 'truesync_tenant_slug']
                c.execute(text(f"INSERT INTO {table} ({', '.join(cols)}) VALUES "
                               f"({', '.join(':' + k for k in cols)})"),
                          {k: _encode(row[k]) for k in cols})
        customers.link_tenant(c, 10, 'wiggle-and-snug', TOKEN_A, 'aaaaaaaaaaaaaaaa')
        customers.link_tenant(c, 20, 'brandco', TOKEN_B, 'bbbbbbbbbbbbbbbb')
        c.exec_driver_sql("""INSERT INTO organization_members (organization_id, user_id, email, is_operator)
            VALUES (1, 'op', 'op@parleo.io', 1), (10, 'alice', 'alice@ws.test', 0),
                   (20, 'bob', 'bob@brandco.test', 0)""")
    for module in (customers, console_scope_module, console_router, full_loop_router):
        monkeypatch.setattr(module, "engine", engine)
    return engine


class Upstream:
    """Supply. Answers by (method, path) and, where given, by token."""

    def __init__(self):
        self.calls, self.routes = [], {}

    def answer(self, method, path, status=200, body=None, token=None):
        self.routes[(method, path, token)] = (status, body)

    def factory(self, **_kwargs):
        upstream = self

        class Response:
            def __init__(self, status, body):
                self.status_code, self._body = status, body
                self.text = '' if body is None else json.dumps(body)

            def json(self):
                if self._body is None:
                    raise ValueError
                return self._body

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def request(self, method, url, params=None, json=None, headers=None, files=None):
                path = url.replace("https://supply.example", "")
                token = (headers or {}).get("X-TrueSync-Key")
                upstream.calls.append({'method': method, 'path': path, 'json': json, 'token': token})
                hit = upstream.routes.get((method, path, token)) or upstream.routes.get((method, path, None))
                return Response(*(hit or (404, {'detail': 'not found'})))

        return Client()


@pytest.fixture
def upstream(monkeypatch):
    fake = Upstream()
    monkeypatch.setattr(truesync_client_module.httpx, "AsyncClient", fake.factory)
    return fake


@pytest.fixture
def http(db, upstream):
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(verify_token, None)


def as_(user):
    app.dependency_overrides[verify_token] = lambda: {"sub": user, "email": f"{user}@test"}


CYCLE_ENDPOINTS = ['answers', 'true-value', 'studies', 'accuracy']


# ═══ shapes ═══════════════════════════════════════════════════════════════

def test_answers_are_console_answers(http):
    as_('alice')
    answers = http.get('/api/console/answers', params={'cycle': CYCLE}).json()
    assert len(answers) == 8
    for answer in answers:
        check(answer, 'Answer')
    by_id = {a['id']: a for a in answers}
    exact = by_id['run-1001']
    assert exact['verdict'] == 'right' and exact['tone'] == 'ok' and exact['agent'] == 'gemini'
    assert any(seg.get('mark') == 'ok' for para in exact['paragraphs'] for seg in para)
    assert by_id['run-1002']['verdict'] == 'wrong'
    brand = by_id['run-1007']
    assert brand['verdict'] is None and brand['brand_verdict'] == 'acknowledged_unknown'
    assert brand['flags'] == ['fabricated_citation']
    wall = by_id['run-1008']
    assert wall['verdict'] == 'missed' and wall['answer_status'] == 'no_ai_answer'
    assert wall['surface'] == 'consumer_ui' and wall['agent'] == 'aimode'


def test_paragraphs_are_the_stored_spans_verbatim(http):
    as_('alice')
    answer = {a['id']: a for a in http.get('/api/console/answers', params={'cycle': CYCLE}).json()}['run-1004']
    joined = ''.join(seg['t'] for para in answer['paragraphs'] for seg in para)
    assert 'Wiggle & Snug is a Target-exclusive brand.' in joined
    assert any(seg.get('mark') == 'wrong' for para in answer['paragraphs'] for seg in para)


def test_true_value_is_console_true_value(http):
    as_('alice')
    tv = http.get('/api/console/true-value', params={'cycle': CYCLE}).json()
    check(tv, 'TrueValue')
    assert [c['id'] for c in tv['columns']] == ['trueshopstore.com']
    cells = {r['sku']: r['cells']['trueshopstore.com'] for r in tv['rows']}
    assert cells['snug-fit-overnight-s6']['status'] == 'wrong'
    assert cells['snug-fit-overnight-s6']['live'] == '$29.99'
    # One run right, one wrong, one wall: the wall does not vote, the tie
    # goes to the worse, and the runs behind the cell are counted.
    balm = cells['bum-balm-4oz']
    assert balm['status'] == 'wrong' and balm['runs'] == 3


def test_accessibility_is_proxied_with_claude_in_the_vocabulary(http, upstream):
    upstream.answer('GET', '/api/truesync/merchants/wiggle-and-snug/access',
                    body=_fixture('supply_access_ws.json'), token=TOKEN_A)
    as_('alice')
    access = http.get('/api/console/accessibility', params={'merchant': 'wiggle-and-snug'}).json()
    check(access, 'Accessibility')
    claude = [r for r in access['requests'] if r.get('agent') == 'claude'][0]
    assert claude['vendor'] == 'claude'
    assert [c['token'] for c in upstream.calls] == [TOKEN_A]


def test_studies_are_study_rows(http):
    as_('alice')
    rows = http.get('/api/console/studies', params={'cycle': CYCLE}).json()
    for row in rows:
        check(row, 'StudyRow')
    balm = [r for r in rows if r['id'] == 'WIG_167'][0]
    assert set(balm['cells']) == {'gemini', 'chatgpt', 'aimode'}
    assert balm['cells']['gemini']['s'] == 'ok'


def test_runs_studies_and_entities_are_studio_shapes(http):
    as_('alice')
    for run in http.get('/api/console/runs').json():
        check(run, 'Run')
    studies = http.get('/api/console/studio/studies').json()
    assert studies and all(not check(s, 'Study') for s in studies)
    entities = http.get('/api/console/studio/entities').json()
    assert {e['id'] for e in entities} == {'wiggle-and-snug', 'huggies'}
    for entity in entities:
        check(entity, 'Entity')


def test_accuracy_is_split_by_surface_never_pooled(http):
    as_('alice')
    body = http.get('/api/console/accuracy', params={'cycle': CYCLE}).json()
    assert [s['surface'] for s in body['surfaces']] == ['grounded_api', 'consumer_ui']
    consumer = body['surfaces'][1]
    assert consumer['scored'] == 0 and consumer['coverage']['no_ai_answer'] == 1
    assert 'overall' not in body


def test_surfaces_lists_the_modal(http):
    as_('alice')
    entries = http.get('/api/console/surfaces').json()['surfaces']
    assert [e['id'] for e in entries][-2:] == ['gemini_web', 'chatgpt_web']
    assert all(e['fidelity'] for e in entries)


# ═══ the full loop ════════════════════════════════════════════════════════

def start(http, **overrides):
    body = {'merchant_slug': 'wiggle-and-snug', 'study_type': 'ws-2b-fixture',
            'platforms': ['chatgpt', 'gemini_grounded'], **overrides}
    return http.post('/api/full-loop', json=body)


def worker_started(db, request_id, run_id=33, supply_status='running'):
    """What the worker's first step leaves behind: supply's run id on the row."""
    with db.begin() as c:
        c.execute(text("UPDATE soa_full_loop_requests SET supply_run_id = :r, supply_status = :s "
                       "WHERE id = :id"), {'r': run_id, 's': supply_status, 'id': request_id})


def test_run_full_loop_queues_and_answers_202_without_calling_supply(http, db, upstream):
    as_('alice')
    started = start(http, allow_hosted_render=False)
    assert started.status_code == 202
    body = started.json()
    assert body['status'] == 'queued' and isinstance(body['full_loop_id'], int)
    assert upstream.calls == []                          # supply is the worker's to call
    with db.connect() as c:
        row = c.execute(text("SELECT * FROM soa_full_loop_requests WHERE id = :id"),
                        {'id': body['full_loop_id']}).mappings().one()
    assert row['status'] == 'reference_pending' and row['supply_run_id'] is None
    assert not row['allow_hosted_render'] and row['organization_id'] == 10

    queued = http.get(f"/api/full-loop/{body['full_loop_id']}").json()
    check(queued, 'FullLoopStatus')
    assert queued['supply'] == {'run_id': None, 'status': None, 'run': None, 'read_error': None}
    assert queued['strip'][0]['state'] == 'running'
    assert upstream.calls == []                          # no run id yet: nothing to read upstream


def test_run_full_loop_answers_within_budget_however_slow_supply_is(http, upstream, monkeypatch):
    """The 504: supply's POST ran the whole loop inline. Here every call to
    supply takes 5 seconds; the POST must neither make one nor wait."""
    make = upstream.factory

    def slow_factory(**kwargs):
        client = make(**kwargs)
        inner = client.request

        async def request(*args, **kw):
            time.sleep(5)
            return await inner(*args, **kw)

        client.request = request
        return client

    monkeypatch.setattr(truesync_client_module.httpx, "AsyncClient", slow_factory)
    as_('alice')
    began = time.monotonic()
    response = start(http)
    assert time.monotonic() - began < 1.0
    assert response.status_code == 202 and response.json()['status'] == 'queued'
    assert upstream.calls == []


def test_the_worker_s_run_reads_back_one_combined_object(http, db, upstream):
    upstream.answer('GET', '/api/truesync/merchants/wiggle-and-snug/full-loop/33',
                    body={'id': 33, 'status': 'access_done'}, token=TOKEN_A)
    as_('alice')
    request_id = start(http).json()['full_loop_id']
    worker_started(db, request_id)

    got = http.get(f"/api/full-loop/{request_id}").json()
    check(got, 'FullLoopStatus')
    assert got['id'] == request_id and got['status'] == 'reference_pending'
    assert got['supply']['status'] == 'access_done'
    assert got['strip'][0] == {'step': 'reference', 'label': 'Access and reference reads', 'state': 'running'}
    assert http.get(f"/api/console/full-loop/{request_id}").json() == got
    assert {c['token'] for c in upstream.calls} == {TOKEN_A}


def age(db, request_id, minutes):
    with db.begin() as c:
        then = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        c.execute(text("UPDATE soa_full_loop_requests SET created_at = :t, updated_at = :t "
                       "WHERE id = :id"), {'t': then, 'id': request_id})
        c.execute(text("UPDATE soa_runs SET run_at = :t"), {'t': then})


def test_a_stale_request_reads_back_failed_timed_out_and_latest_re_enables(http, db):
    as_('alice')
    request_id = start(http).json()['full_loop_id']
    age(db, request_id, 59)
    assert http.get('/api/console/full-loop/latest').json()['status'] == 'reference_pending'

    age(db, request_id, 61)                              # the worker never picked it up
    latest = http.get('/api/console/full-loop/latest').json()
    check(latest, 'FullLoopStatus')
    assert latest['id'] == request_id and latest['status'] == 'failed'
    assert latest['error'].startswith('timed_out: no progress for 60 minutes')
    assert latest['strip'][0]['state'] == 'failed'
    assert latest == http.get(f'/api/console/full-loop/{request_id}').json()


def test_a_request_marked_timed_out_by_the_worker_reads_back_as_written(http, db):
    as_('alice')
    request_id = start(http).json()['full_loop_id']
    with db.begin() as c:
        c.execute(text("UPDATE soa_full_loop_requests SET status = 'failed', error = :e WHERE id = :id"),
                  {'e': 'timed_out: no progress for 60 minutes while cycle_planned', 'id': request_id})
    latest = http.get('/api/console/full-loop/latest').json()
    assert latest['status'] == 'failed' and latest['error'].startswith('timed_out:')


def test_a_surface_that_cannot_run_is_refused_before_supply_is_called(http, upstream, monkeypatch):
    monkeypatch.delenv('SOA_CONSUMER_SURFACES_ENABLED', raising=False)
    as_('alice')
    response = start(http, platforms=['aimode'])
    assert response.status_code == 422 and 'consumer surfaces are off' in response.json()['detail']
    assert upstream.calls == []


# ═══ tenant isolation, on every new endpoint ══════════════════════════════

def test_a_member_of_another_tenant_cannot_read_this_cycle(http):
    as_('bob')
    for endpoint in CYCLE_ENDPOINTS:
        assert http.get(f'/api/console/{endpoint}', params={'cycle': CYCLE}).status_code == 404, endpoint
    assert http.get('/api/console/runs').json() == []
    assert http.get('/api/console/studio/studies').json() == []
    assert http.get('/api/console/studio/entities').json() == []


def test_a_member_naming_another_org_is_refused(http):
    as_('bob')
    for endpoint in CYCLE_ENDPOINTS:
        assert http.get(f'/api/console/{endpoint}', params={'cycle': CYCLE, 'org': 10}).status_code == 403
    for endpoint in ('runs', 'studio/studies', 'studio/entities', 'surfaces'):
        assert http.get(f'/api/console/{endpoint}', params={'org': 10}).status_code == 403
    assert http.get('/api/console/accessibility',
                    params={'merchant': 'wiggle-and-snug', 'org': 10}).status_code == 403


def test_an_operator_reads_another_tenant_with_org(http):
    as_('op')
    for endpoint in CYCLE_ENDPOINTS:
        assert http.get(f'/api/console/{endpoint}', params={'cycle': CYCLE, 'org': 10}).status_code == 200
        assert http.get(f'/api/console/{endpoint}', params={'cycle': CYCLE, 'org': 20}).status_code == 404
    assert len(http.get('/api/console/runs', params={'org': 10}).json()) == 1


def test_accessibility_uses_the_scoped_tenants_token(http, upstream):
    upstream.answer('GET', '/api/truesync/merchants/wiggle-and-snug/access',
                    body=_fixture('supply_access_ws.json'), token=TOKEN_A)
    as_('bob')
    assert http.get('/api/console/accessibility', params={'merchant': 'wiggle-and-snug'}).status_code == 404
    assert [c['token'] for c in upstream.calls] == [TOKEN_B]


def test_full_loop_is_tenant_scoped(http, upstream):
    as_('alice')
    request_id = start(http).json()['full_loop_id']
    as_('bob')
    assert start(http).status_code == 404                       # not bob's study
    assert http.get(f'/api/full-loop/{request_id}').status_code == 404
    assert http.get(f'/api/console/full-loop/{request_id}').status_code == 404
    assert http.get(f'/api/full-loop/{request_id}', params={'org': 10}).status_code == 403
    as_('op')
    assert http.get(f'/api/full-loop/{request_id}', params={'org': 10}).status_code == 200


# ═══ 2C-0: who is signed in, and the latest full loop ══════════════════════

WS_TENANT = {'slug': 'wiggle-and-snug', 'merchants': [
    {'slug': 'wiggle-and-snug', 'name': 'Wiggle & Snug', 'domain': 'trueshopstore.com',
     'kind': 'brand', 'hosting': 'parleo', 'has_record': True}]}
BRANDCO_TENANT = {'slug': 'brandco', 'merchants': [
    {'slug': 'brandco', 'name': 'Brandco', 'domain': 'brandco.test',
     'kind': 'seller', 'hosting': 'external', 'has_record': False}]}


def tenants(upstream):
    upstream.answer('GET', '/api/truesync/tenant', body=WS_TENANT, token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/tenant', body=BRANDCO_TENANT, token=TOKEN_B)


def test_me_lists_every_linked_org_for_an_operator(http, upstream):
    tenants(upstream)
    as_('op')
    me = http.get('/api/console/me').json()
    assert me['user'] == {'id': 'op', 'email': 'op@test'}
    assert me['is_operator'] is True
    by_id = {o['id']: o for o in me['orgs']}
    assert set(by_id) == {10, 20}                    # the staff org is not a customer
    assert {k: by_id[10][k] for k in ('slug', 'kind', 'hosting', 'domain')} == {
        'slug': 'wiggle-and-snug', 'kind': 'brand', 'hosting': 'parleo', 'domain': 'trueshopstore.com'}
    assert by_id[20]['kind'] == 'seller' and by_id[20]['hosting'] == 'external'
    assert {c['token'] for c in upstream.calls} == {TOKEN_A, TOKEN_B}


def test_me_pins_a_member_to_their_own_org(http, upstream):
    tenants(upstream)
    as_('alice')
    me = http.get('/api/console/me').json()
    assert me['is_operator'] is False
    assert [o['id'] for o in me['orgs']] == [10]
    assert [c['token'] for c in upstream.calls] == [TOKEN_A]


def test_me_still_lists_an_org_whose_record_read_fails(http, upstream):
    upstream.answer('GET', '/api/truesync/tenant', status=403, body={'detail': 'revoked'}, token=TOKEN_A)
    as_('alice')
    org = http.get('/api/console/me').json()['orgs'][0]
    assert org['id'] == 10 and org['kind'] is None and org['slug'] == 'wiggle-and-snug'
    assert 'refused its token' in org['error']


def test_me_needs_a_session(http):
    assert http.get('/api/console/me').status_code in (401, 403)


def test_latest_full_loop_is_null_before_the_first_run(http):
    as_('alice')
    response = http.get('/api/console/full-loop/latest')
    assert response.status_code == 200 and response.json() is None


def test_latest_full_loop_is_the_newest_in_the_by_id_shape(http, db, upstream):
    upstream.answer('GET', '/api/truesync/merchants/wiggle-and-snug/full-loop/33',
                    body={'id': 33, 'status': 'access_done'}, token=TOKEN_A)
    as_('alice')
    start(http)
    newest = start(http).json()['full_loop_id']
    worker_started(db, newest)
    latest = http.get('/api/console/full-loop/latest').json()
    check(latest, 'FullLoopStatus')
    assert latest['id'] == newest
    assert latest == http.get(f'/api/console/full-loop/{newest}').json()


def test_latest_full_loop_is_tenant_scoped(http, upstream):
    as_('alice')
    start(http)
    as_('bob')
    assert http.get('/api/console/full-loop/latest').json() is None        # bob's org has none
    assert http.get('/api/console/full-loop/latest', params={'org': 10}).status_code == 403
    as_('op')
    assert http.get('/api/console/full-loop/latest', params={'org': 10}).json()['merchant'] == 'wiggle-and-snug'
    assert http.get('/api/console/full-loop/latest', params={'org': 20}).json() is None


# ═══ the verdict mapping ══════════════════════════════════════════════════

def test_the_verdict_mapping_is_explicit_and_not_lossy():
    assert rm.VALUE_VERDICT == {
        'exact': 'right', 'wrong': 'wrong', 'absent': 'missed', 'partial': 'partial',
        'stale': 'stale', 'unverifiable': 'unverifiable', 'unscoreable': 'unscoreable',
    }
    assert len(set(rm.VALUE_VERDICT.values())) == len(rm.VALUE_VERDICT)
    for verdict in rm.VALUE_VERDICT.values():
        assert verdict in rm.VERDICT_TONE


def test_true_value_for_an_external_brand_reads_the_2a_reference():
    """Columns are the record's retailers; `live` is supply's retailer-prices
    row; a page that blocked both sources is `unverifiable`, never wrong."""
    reference = {'as_of': '2026-10-09T12:00:00+00:00', 'prices': [
        {'gtin': '00012345678905', 'variant_label': 'Size 3', 'retailer_domain': 'target.com',
         'price': '21.49', 'currency': 'USD', 'verifiable': True},
        {'gtin': '00012345678905', 'variant_label': 'Size 3', 'retailer_domain': 'walmart.com',
         'price': None, 'currency': None, 'verifiable': False,
         'unverifiable_reason': 'page unreadable from every source (challenged)'},
    ]}
    scored = [
        {'gtin': '00012345678905', 'retailer': 'target.com', 'outcome': 'stale', 'stated': '22.99'},
        {'gtin': '00012345678905', 'retailer': 'walmart.com', 'outcome': 'unverifiable', 'stated': '17.00'},
    ]
    tv = rm.build_true_value(reference, scored, own_domain='acmebaby.example', record_variants=[])
    check(tv, 'TrueValue')
    assert [c['id'] for c in tv['columns']] == ['target.com', 'walmart.com']
    cells = tv['rows'][0]['cells']
    assert cells['target.com'] == {'quoted': '$22.99', 'live': '$21.49', 'status': 'wrong',
                                   'outcome': 'stale', 'runs': 1}
    assert cells['walmart.com']['status'] == 'unverifiable'
    assert cells['walmart.com']['live'] == 'unverifiable'
