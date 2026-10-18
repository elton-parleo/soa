"""
2B §5: the full loop's worker half — POST supply for a queued request, poll
to reference_done, create the cycle with full_loop_run_id, PATCH supply once
it is scored; and fail a request that has stopped making progress.

Supply is a fake behind httpx.MockTransport that enforces the PATCH rules
from parleo-supply-app docs/truesync/access-series.md §5 (and
truesync/fullloop/runs.py pipeline_update): only reference_done -> scored |
failed, the same cycle id is idempotent, a different cycle id is a 409.
"""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import create_engine, event, text

from fullloop.coordinator import Coordinator, SupplyFullLoopClient

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)


class FakeSupply:
    def __init__(self, status='running', soa_cycle_id=None, starts_as=None):
        self.run = {'id': 33, 'status': status, 'soa_cycle_id': soa_cycle_id, 'error': None}
        #: what POST .../full-loop leaves the run in: reference_done is the
        #: synchronous answer (up to 25 pages), running the background one.
        self.starts_as = starts_as or status
        self.calls = []

    def handler(self, request):
        self.calls.append((request.method, request.url.path,
                           json.loads(request.content) if request.content else None,
                           request.headers.get('X-TrueSync-Key')))
        if request.method == 'POST':
            self.run['status'] = self.starts_as
            return httpx.Response(200 if self.starts_as == 'reference_done' else 202, json=dict(self.run))
        if request.method == 'GET':
            return httpx.Response(200, json=dict(self.run))
        body = json.loads(request.content)
        if set(body) == {'reason'}:
            # supply's runs.pipeline_update: a reason alone annotates the run, status unchanged
            self.run['reason'] = body['reason']
            return httpx.Response(200, json=dict(self.run))
        if body.get('soa_cycle_id') is None:
            if self.run['status'] != 'reference_done' or body['status'] != 'failed':
                return httpx.Response(409, json={'detail': f"full loop run 33 is {self.run['status']!r}"})
            self.run['status'] = 'failed'
            return httpx.Response(200, json=dict(self.run))
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
            runs_per_query INTEGER, allow_hosted_render BOOLEAN NOT NULL DEFAULT 1,
            supply_run_id INTEGER, supply_status TEXT, cycle_id INTEGER,
            status TEXT, error TEXT, created_by TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)""")
        c.exec_driver_sql("""CREATE TABLE soa_runs (id INTEGER PRIMARY KEY, cycle_id INTEGER,
            run_at TIMESTAMP)""")
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
        # 2I-5/2I-6: the comparison set reads the study's merchant from its job (none here: 'acme' predates them)
        c.exec_driver_sql("""CREATE TABLE soa_query_generation_jobs (id INTEGER PRIMARY KEY, study_type TEXT,
            organization_id INTEGER, customer_organization_id INTEGER, syndicated_merchant TEXT, tier_config TEXT)""")
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
    """2I-5: a study with no cycle takes its merchant's set (test_first_cycle_2i5.py); one
    with no job in the org, and so no merchant, fails saying so."""
    with db.begin() as c:
        c.exec_driver_sql("DELETE FROM soa_cycles")
    supply = FakeSupply('reference_done')
    co = coordinator(db, supply)
    rid = request(db, status='reference_done')
    co.tick()
    assert co.get(rid)['error'] == 'could not create the cycle: the study belongs to no merchant'


# ═══ the dispatch: the worker makes supply's POST ═════════════════════════

def queued(db, allow_hosted_render=True, at=None):
    """What POST /api/full-loop records: no supply run yet."""
    with db.begin() as c:
        return c.execute(text("""INSERT INTO soa_full_loop_requests (organization_id, merchant_slug,
            study_type, platforms, runs_per_query, allow_hosted_render, status, created_by,
            created_at, updated_at)
            VALUES (10, 'acme-baby', 'acme', :p, 1, :ahr, 'reference_pending', 'op', :at, :at)
            RETURNING id"""), {'p': json.dumps(['chatgpt', 'aimode']), 'ahr': allow_hosted_render,
                               'at': (at or NOW).isoformat()}).scalar()


def posts(supply):
    return [c for c in supply.calls if c[0] == 'POST']


def test_a_queued_request_runs_end_to_end_on_the_worker(db):
    supply = FakeSupply('running')
    co = coordinator(db, supply)
    rid = queued(db, allow_hosted_render=False)

    co.tick()                                              # POST supply
    row = co.get(rid)
    assert (row['status'], row['supply_run_id'], row['supply_status']) == ('reference_pending', 33, 'running')
    assert posts(supply) == [('POST', '/api/truesync/merchants/acme-baby/full-loop',
                              {'allow_hosted_render': False}, 'tst_org_token')]

    co.tick()                                              # poll: still running
    supply.run['status'] = 'reference_done'
    co.tick()                                              # poll: done
    co.tick()                                              # create the cycle
    row = co.get(rid)
    assert row['status'] == 'cycle_planned'
    with db.begin() as c:                                  # the worker's planned-cycle path runs it
        c.execute(text("INSERT INTO soa_runs (cycle_id, run_at) VALUES (:c, :t)"),
                  {'c': row['cycle_id'], 't': NOW.isoformat()})
    cycle_status(db, row['cycle_id'], 'complete')
    co.tick()                                              # PATCH scored
    final = co.get(rid)
    assert final['status'] == 'scored' and final['error'] is None
    assert len(posts(supply)) == 1                         # one press, one supply run
    assert [c[2] for c in supply.calls if c[0] == 'PATCH'] == [
        {'soa_cycle_id': str(row['cycle_id']), 'status': 'scored'}]


def test_a_synchronous_supply_answer_goes_straight_to_reference_done(db):
    supply = FakeSupply('reference_done')
    co = coordinator(db, supply)
    rid = queued(db)
    co.tick()
    assert co.get(rid)['status'] == 'reference_done'
    co.tick()
    assert co.get(rid)['status'] == 'cycle_planned'
    assert posts(supply)[0][2] == {'allow_hosted_render': True}


def test_supply_unreachable_stays_queued_and_is_retried(db):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    down = SupplyFullLoopClient('tst_org_token', base_url='https://supply.example',
                                transport=httpx.MockTransport(refuse))
    rid = queued(db)
    Coordinator(engine=db, client_for=lambda _org: down, clock=lambda: NOW).tick()
    row = Coordinator(engine=db, clock=lambda: NOW).get(rid)
    assert (row['status'], row['supply_run_id'], row['supply_status']) == ('reference_pending', None, None)

    supply = FakeSupply('running')
    coordinator(db, supply).tick()
    assert coordinator(db, supply).get(rid)["supply_run_id"] == 33


def test_a_post_that_reached_supply_and_failed_is_not_retried(db):
    outage = SupplyFullLoopClient('tst_org_token', base_url='https://supply.example',
                                  transport=httpx.MockTransport(lambda r: httpx.Response(500, text='boom')))
    co = Coordinator(engine=db, client_for=lambda _org: outage, clock=lambda: NOW)
    rid = queued(db)
    co.tick()
    row = co.get(rid)
    assert row['status'] == 'failed' and row['error'].startswith('TrueSync full loop did not start')
    assert co.tick() == 0


def test_an_unknown_merchant_fails_the_request(db):
    missing = SupplyFullLoopClient('tst_org_token', base_url='https://supply.example',
                                   transport=httpx.MockTransport(
                                       lambda r: httpx.Response(404, json={'detail': 'no such merchant'})))
    co = Coordinator(engine=db, client_for=lambda _org: missing, clock=lambda: NOW)
    rid = queued(db)
    co.tick()
    assert co.get(rid)['error'] == "merchant 'acme-baby' not found"


def test_a_post_interrupted_by_a_restart_is_failed_and_never_re_sent(db):
    supply = FakeSupply('running')
    co = coordinator(db, supply)
    rid = queued(db)
    with db.begin() as c:
        c.execute(text("UPDATE soa_full_loop_requests SET supply_status = 'starting' WHERE id = :id"),
                  {'id': rid})
    co.tick()
    row = co.get(rid)
    assert row['status'] == 'failed' and row['error'].startswith('orphaned_by_restart:')
    assert posts(supply) == []


# ═══ staleness: no progress for STALE_MINUTES ═════════════════════════════

def aged(db, rid, minutes):
    with db.begin() as c:
        then = (NOW - timedelta(minutes=minutes)).isoformat()
        c.execute(text("UPDATE soa_full_loop_requests SET created_at = :t, updated_at = :t WHERE id = :id"),
                  {'t': then, 'id': rid})


def test_the_stale_threshold_is_sixty_minutes():
    from soa_shared import full_loop_staleness
    assert full_loop_staleness.STALE_MINUTES == 60


def test_a_supply_run_with_no_progress_is_timed_out(db):
    supply = FakeSupply('running')
    co = coordinator(db, supply)
    rid = request(db)
    aged(db, rid, 59)
    co.tick()
    assert co.get(rid)['status'] == 'reference_pending'
    aged(db, rid, 61)
    co.tick()
    row = co.get(rid)
    assert row['status'] == 'failed'
    assert row['error'].startswith('timed_out: no progress for 60 minutes while reference_pending')
    # Supply's run is still `running`: it cannot be PATCHed failed, so it is not tried.
    assert [c for c in supply.calls if c[0] == 'PATCH'] == []
    assert co.tick() == 0                                  # terminal


def test_a_stalled_cycle_is_timed_out_failed_and_patched_failed(db):
    supply = FakeSupply('reference_done')
    co = coordinator(db, supply)
    rid = request(db, status='reference_done')
    co.tick()
    cid = co.get(rid)['cycle_id']
    cycle_status(db, cid, 'running')
    with db.begin() as c:
        c.execute(text("INSERT INTO soa_runs (cycle_id, run_at) VALUES (:c, :t)"),
                  {'c': cid, 't': (NOW - timedelta(minutes=61)).isoformat()})
    aged(db, rid, 61)
    co.tick()
    row = co.get(rid)
    assert row['status'] == 'failed' and row['error'].startswith('timed_out:')
    assert row['supply_status'] == 'failed'
    with db.connect() as c:
        cycle = c.execute(text("SELECT status, notes FROM soa_cycles WHERE id = :c"), {'c': cid}).one()
    assert cycle[0] == 'failed' and 'timed_out' in cycle[1]
    assert [c[2] for c in supply.calls if c[0] == 'PATCH'] == [{'soa_cycle_id': str(cid), 'status': 'failed'}]


def test_a_cycle_still_running_its_runs_is_not_stale(db):
    supply = FakeSupply('reference_done')
    co = coordinator(db, supply)
    rid = request(db, status='reference_done')
    co.tick()
    cid = co.get(rid)['cycle_id']
    cycle_status(db, cid, 'running')
    with db.begin() as c:
        c.execute(text("INSERT INTO soa_runs (cycle_id, run_at) VALUES (:c, :t)"),
                  {'c': cid, 't': (NOW - timedelta(minutes=2)).isoformat()})
    aged(db, rid, 180)
    co.tick()
    assert co.get(rid)['status'] == 'cycle_planned'


def test_a_request_queued_behind_a_busy_worker_is_not_stale(db):
    """The worker runs one cycle at a time; waiting behind one is not stuck."""
    supply = FakeSupply('running')
    co = coordinator(db, supply)
    rid = queued(db, at=NOW - timedelta(minutes=120))
    with db.begin() as c:                                  # another study's cycle, mid-run
        c.execute(text("INSERT INTO soa_runs (cycle_id, run_at) VALUES (1, :t)"),
                  {'t': (NOW - timedelta(minutes=1)).isoformat()})
    assert co.time_out(co.get(rid)) is False
    with db.begin() as c:
        c.execute(text("UPDATE soa_runs SET run_at = :t"), {'t': (NOW - timedelta(minutes=90)).isoformat()})
    assert co.time_out(co.get(rid)) is True                # and a stopped worker is
    assert co.get(rid)['error'].startswith('timed_out:') and posts(supply) == []


# ═══ 2H: a loop runs for the merchant its request names ════════════════════

def test_every_supply_call_and_the_cycle_carry_the_requests_merchant(db):
    """An org with two merchants (Wiggle & Snug's store and its brand): the
    request names the brand, and the worker's POST, its poll, the cycle it
    creates and the PATCH all key on that slug, never the org's other one."""
    supply = FakeSupply('running')
    co = coordinator(db, supply)
    rid = queued(db)
    with db.begin() as c:
        c.execute(text("UPDATE soa_full_loop_requests SET merchant_slug = 'wiggle-and-snug-brand' WHERE id = :i"), {'i': rid})
    co.tick()
    supply.run['status'] = 'reference_done'
    co.tick()
    co.tick()
    row = co.get(rid)
    with db.begin() as c:
        c.execute(text("INSERT INTO soa_runs (cycle_id, run_at) VALUES (:c, :t)"), {'c': row['cycle_id'], 't': NOW.isoformat()})
        code = c.execute(text("SELECT cycle_code FROM soa_cycles WHERE id = :i"), {'i': row['cycle_id']}).scalar()
    cycle_status(db, row['cycle_id'], 'complete')
    co.tick()
    paths = {c[1] for c in supply.calls}
    assert paths and all('/merchants/wiggle-and-snug-brand/' in p for p in paths)
    assert '-wiggle-and-snug-brand-' in code



# ═══ 2I: a reads-only request (no study) ═══════════════════════════════════

def reads_only_request(db, at=None):
    """What POST /api/full-loop records for a merchant with no study."""
    with db.begin() as c:
        return c.execute(text("""INSERT INTO soa_full_loop_requests (organization_id, merchant_slug,
            study_type, platforms, runs_per_query, allow_hosted_render, status, created_by,
            created_at, updated_at)
            VALUES (10, 'wiggle-and-snug-brand', NULL, '[]', 1, TRUE, 'reference_pending', 'op', :at, :at)
            RETURNING id"""), {'at': (at or NOW).isoformat()}).scalar()


@pytest.mark.parametrize('starts_as', ['running', 'reference_done'])
def test_a_reads_only_request_ends_at_reads_done_with_no_cycle(db, starts_as):
    supply = FakeSupply('running', starts_as=starts_as)
    co = coordinator(db, supply)
    rid = reads_only_request(db)
    with db.connect() as c:
        cycles_before = c.execute(text("SELECT COUNT(*) FROM soa_cycles")).scalar()
    co.tick()                                              # POST supply
    if starts_as == 'running':
        assert co.get(rid)['status'] == 'reference_pending'
        supply.run['status'] = 'reference_done'
        co.tick()                                          # poll: reference_done
    co.tick()                                              # no study: reads_done
    row = co.get(rid)
    assert (row['status'], row['cycle_id'], row['error']) == ('reads_done', None, None)
    with db.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM soa_cycles")).scalar() == cycles_before   # no cycle created
    patches = [c for c in supply.calls if c[0] == 'PATCH']
    assert patches == [('PATCH', '/api/truesync/merchants/wiggle-and-snug-brand/full-loop/33',
                        {'reason': 'reads_only'}, 'tst_org_token')]
    assert supply.run['status'] == 'reference_done'        # supply's run is left at reference_done
    assert co.tick() == 0                                  # terminal: never picked up again


def test_a_stale_sweep_leaves_reads_done_alone(db):
    supply = FakeSupply('reference_done')
    co = coordinator(db, supply)
    rid = reads_only_request(db)
    co.tick(); co.tick()
    assert co.get(rid)['status'] == 'reads_done'
    later = Coordinator(engine=db, client_for=supply.client, clock=lambda: NOW + timedelta(days=3))
    assert later.tick() == 0
    assert co.get(rid)['status'] == 'reads_done' and co.get(rid)['error'] is None
