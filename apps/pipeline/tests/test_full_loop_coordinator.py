"""
2B §5: the full loop's worker half — poll supply to reference_done, create
the cycle with full_loop_run_id, PATCH supply once it is scored.

Supply is a fake behind httpx.MockTransport that enforces the PATCH rules
from parleo-supply-app docs/truesync/access-series.md §5 (and
truesync/fullloop/runs.py pipeline_update): only reference_done -> scored |
failed, the same cycle id is idempotent, a different cycle id is a 409.
"""
import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import create_engine, event, text

from fullloop.coordinator import Coordinator, SupplyFullLoopClient

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)


class FakeSupply:
    def __init__(self, status='running', soa_cycle_id=None):
        self.run = {'id': 33, 'status': status, 'soa_cycle_id': soa_cycle_id, 'error': None}
        self.calls = []

    def handler(self, request):
        self.calls.append((request.method, request.url.path,
                           json.loads(request.content) if request.content else None,
                           request.headers.get('X-TrueSync-Key')))
        if request.method == 'GET':
            return httpx.Response(200, json=dict(self.run))
        body = json.loads(request.content)
        if self.run['soa_cycle_id'] and self.run['soa_cycle_id'] != body['soa_cycle_id']:
            return httpx.Response(409, json={'detail': f"full loop run 33 is already scored by cycle "
                                                       f"{self.run['soa_cycle_id']!r}"})
        if self.run['status'] not in ('reference_done', 'scored'):
            return httpx.Response(409, json={'detail': f"full loop run 33 is {self.run['status']!r}"})
        self.run.update(soa_cycle_id=body['soa_cycle_id'], status=body['status'])
        return httpx.Response(200, json=dict(self.run))

    def client(self, _org_id):
        return SupplyFullLoopClient('tst_org_token', base_url='https://supply.example',
                                    transport=httpx.MockTransport(self.handler))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _now(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: NOW.isoformat())

    with engine.begin() as c:
        c.exec_driver_sql("""CREATE TABLE soa_full_loop_requests (id INTEGER PRIMARY KEY,
            organization_id INTEGER, merchant_slug TEXT, study_type TEXT, platforms TEXT,
            runs_per_query INTEGER, supply_run_id INTEGER, supply_status TEXT, cycle_id INTEGER,
            status TEXT, error TEXT, created_by TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)""")
        c.exec_driver_sql("""CREATE TABLE soa_cycles (id INTEGER PRIMARY KEY, cycle_code TEXT UNIQUE,
            study_type TEXT, study_pattern TEXT, status TEXT, cycle_mode TEXT, truecost_tiers TEXT,
            total_runs_planned INTEGER, completed_runs INTEGER, start_date DATE, notes TEXT,
            platforms TEXT, runs_per_query INTEGER, organization_id INTEGER, created_by TEXT,
            source_lite_request_id INTEGER, study_series_id TEXT, prior_cycle_id INTEGER,
            full_loop_run_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        c.exec_driver_sql("""CREATE TABLE soa_cycle_entities (id INTEGER PRIMARY KEY, cycle_id INTEGER,
            entity_id INTEGER, comparison_code TEXT, role TEXT)""")
        c.exec_driver_sql("""CREATE TABLE soa_queries (id INTEGER PRIMARY KEY, study_type TEXT,
            study_pattern TEXT, status TEXT)""")
        c.exec_driver_sql("INSERT INTO soa_queries (study_type, study_pattern, status) VALUES "
                          "('acme', 'brand_at_retail', 'Active'), ('acme', 'brand_at_retail', 'Active')")
        c.exec_driver_sql("""INSERT INTO soa_cycles (id, cycle_code, study_type, study_pattern, status,
            start_date, organization_id) VALUES (1, 'ACME-PRIOR', 'acme', 'brand_at_retail', 'complete',
            '2026-10-01', 10)""")
        c.exec_driver_sql("INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) "
                          "VALUES (1, 7, 'M001', 'primary'), (1, 8, 'M002', 'competitor')")
    return engine


def request(db, status='reference_pending'):
    with db.begin() as c:
        return c.execute(text("""INSERT INTO soa_full_loop_requests (organization_id, merchant_slug,
            study_type, platforms, runs_per_query, supply_run_id, supply_status, status, created_by)
            VALUES (10, 'acme-baby', 'acme', :p, 1, 33, 'running', :s, 'op') RETURNING id"""),
                         {'p': json.dumps(['chatgpt', 'aimode']), 's': status}).scalar()


def coordinator(db, supply):
    return Coordinator(engine=db, client_for=supply.client, clock=lambda: NOW)


def cycle_status(db, cycle_id, status):
    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET status = :s WHERE id = :c"), {'s': status, 'c': cycle_id})


def test_the_whole_loop_poll_create_score_patch(db):
    supply = FakeSupply('running')
    co = coordinator(db, supply)
    rid = request(db)

    assert co.tick() == 0                                  # still running: nothing moves
    supply.run['status'] = 'reference_done'
    co.tick()
    assert co.get(rid)['status'] == 'reference_done'

    co.tick()                                              # creates the cycle
    row = co.get(rid)
    assert row['status'] == 'cycle_planned'
    with db.connect() as c:
        cycle = c.execute(text("SELECT * FROM soa_cycles WHERE id = :c"), {'c': row['cycle_id']}).mappings().one()
        entities = c.execute(text("SELECT entity_id FROM soa_cycle_entities WHERE cycle_id = :c"),
                             {'c': row['cycle_id']}).scalars().all()
    assert cycle['full_loop_run_id'] == 33
    assert cycle['status'] == 'planned'
    assert json.loads(cycle['platforms']) == ['chatgpt', 'aimode']
    assert cycle['total_runs_planned'] == 4
    assert sorted(entities) == [7, 8]

    co.tick()                                              # cycle not finished yet
    assert co.get(rid)['status'] == 'cycle_planned'
    cycle_status(db, row['cycle_id'], 'complete')
    co.tick()
    final = co.get(rid)
    assert final['status'] == 'scored'
    patch = [c for c in supply.calls if c[0] == 'PATCH'][-1]
    assert patch[1] == '/api/truesync/merchants/acme-baby/full-loop/33'
    assert patch[2] == {'soa_cycle_id': str(row['cycle_id']), 'status': 'scored'}
    # Every supply call carried the org's tenant token.
    assert {c[3] for c in supply.calls} == {'tst_org_token'}


def test_a_failed_cycle_patches_failed(db):
    supply = FakeSupply('reference_done')
    co = coordinator(db, supply)
    rid = request(db, status='reference_done')
    co.tick()
    cycle_status(db, co.get(rid)['cycle_id'], 'failed')
    co.tick()
    assert co.get(rid)['status'] == 'failed'
    assert [c[2]['status'] for c in supply.calls if c[0] == 'PATCH'] == ['failed']


def test_a_409_for_a_different_cycle_id_fails_the_request_and_is_not_retried(db):
    supply = FakeSupply('reference_done', soa_cycle_id='999')
    co = coordinator(db, supply)
    rid = request(db, status='reference_done')
    co.tick()
    cycle_status(db, co.get(rid)['cycle_id'], 'complete')
    co.tick()
    row = co.get(rid)
    assert row['status'] == 'failed' and row['supply_status'] == 'conflict'
    assert "already scored by cycle '999'" in row['error']
    patches = len([c for c in supply.calls if c[0] == 'PATCH'])
    co.tick()                                              # terminal: nothing more is sent
    assert len([c for c in supply.calls if c[0] == 'PATCH']) == patches


def test_repeating_the_same_cycle_id_is_idempotent_upstream(db):
    supply = FakeSupply('reference_done')
    co = coordinator(db, supply)
    rid = request(db, status='reference_done')
    co.tick()
    cid = co.get(rid)['cycle_id']
    supply.run.update(status='scored', soa_cycle_id=str(cid))   # an earlier PATCH landed
    cycle_status(db, cid, 'complete')
    co.tick()
    assert co.get(rid)['status'] == 'scored'


def test_a_supply_run_that_failed_creates_no_cycle(db):
    supply = FakeSupply('failed')
    supply.run['error'] = 'reference reads crashed'
    co = coordinator(db, supply)
    rid = request(db)
    co.tick()
    row = co.get(rid)
    assert row['status'] == 'failed' and 'reference reads crashed' in row['error']
    assert row['cycle_id'] is None


def test_a_transient_supply_outage_is_retried_on_the_next_tick(db):
    supply = FakeSupply('running')
    outage = SupplyFullLoopClient('tst_org_token', base_url='https://supply.example',
                                  transport=httpx.MockTransport(lambda r: httpx.Response(503, text='down')))
    co = Coordinator(engine=db, client_for=lambda _org: outage, clock=lambda: NOW)
    rid = request(db)
    co.tick()
    assert co.get(rid)['status'] == 'reference_pending'


def test_no_comparison_set_fails_with_the_reason(db):
    with db.begin() as c:
        c.exec_driver_sql("DELETE FROM soa_cycles")
    supply = FakeSupply('reference_done')
    co = coordinator(db, supply)
    rid = request(db, status='reference_done')
    co.tick()
    assert 'comparison set' in co.get(rid)['error']
