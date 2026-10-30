"""
RunOrchestrator scheduling: the inter-run delay between repetitions of the
same (query, platform) slot is waited out OUTSIDE the platform semaphore,
and the work list is run-number first, so a slot that ran recently never
holds a connection slot while it sleeps. The delay itself still holds:
each repetition starts at least inter_run_delay after the slot's previous
run finished.
"""
import asyncio
import time
from datetime import date

import pytest
from sqlalchemy.orm import sessionmaker

import runners.run_orchestrator as run_orchestrator_module
from runners.platform_response import PlatformResponse
from runners.run_orchestrator import RunOrchestrator
from soa_pg_harness import model_schema, sqlite_engine
from soa_shared.models.soa_models import Base

_DELAY = 0.3
_RUN_SECONDS = 0.1


@pytest.fixture
def calls(monkeypatch):
    engine = sqlite_engine()
    model_schema(engine)
    t = Base.metadata.tables
    with engine.begin() as c:
        c.execute(t['organizations'].insert(), [{'id': 10, 'name': 'Org'}])
        c.execute(t['soa_entities'].insert(), [{'id': 1, 'name': 'Acme', 'slug': 'acme', 'entity_type': 'brand'}])
        c.execute(t['soa_cycles'].insert(), [{
            'id': 1, 'cycle_code': 'C-SCHED', 'start_date': date(2026, 10, 30), 'status': 'planned',
            'study_type': 'sched', 'study_pattern': 'retailer', 'cycle_mode': 'query', 'organization_id': 10,
            'platforms': ['claude'], 'runs_per_query': 2}])
        c.execute(t['soa_cycle_entities'].insert(), [
            {'cycle_id': 1, 'entity_id': 1, 'comparison_code': 'M001', 'role': 'primary'}])
        c.execute(t['soa_queries'].insert(), [{
            'id': i, 'query_code': f'Q_{i}', 'query_text': f'q{i}', 'category': 'Cross-Category',
            'stage': 'Research', 'specificity': 'Narrow', 'persona': 'New / First-Time Parent',
            'status': 'Active', 'study_type': 'sched',
            'study_pattern': 'retailer', 'organization_id': 10} for i in (1, 2, 3)])

    log = []

    class Runner:
        platform = 'claude'

        def __init__(self, *a, **k):
            pass

        async def run(self, query_text):
            start = time.monotonic()
            await asyncio.sleep(_RUN_SECONDS)
            log.append((query_text, start, time.monotonic()))
            return PlatformResponse(response_text='ok', prompt_tokens=1, completion_tokens=1,
                                    latency_ms=1, platform='claude', model='fake')

    monkeypatch.setattr(run_orchestrator_module, 'session_factory',
                        sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setitem(run_orchestrator_module._RUNNER_CLASSES, 'claude', Runner)
    monkeypatch.setitem(run_orchestrator_module._PLATFORM_MAX_CONCURRENT, 'claude', 1)
    monkeypatch.setitem(run_orchestrator_module._PLATFORM_INTER_RUN_DELAY, 'claude', _DELAY)
    yield log
    engine.dispose()


def _run():
    t0 = time.monotonic()
    asyncio.run(RunOrchestrator(cycle_code='C-SCHED', platforms=['claude'], runs_per_query=2).run_cycle())
    return time.monotonic() - t0


def test_every_query_runs_once_before_any_query_repeats(calls):
    _run()
    assert [q for q, _, _ in calls][:3] == ['q1', 'q2', 'q3']
    assert sorted(q for q, _, _ in calls[3:]) == ['q1', 'q2', 'q3']


def test_repetitions_of_a_slot_still_keep_the_inter_run_delay(calls):
    _run()
    for q in ('q1', 'q2', 'q3'):
        (_, _, first_end), (_, second_start, _) = [c for c in calls if c[0] == q]
        assert second_start - first_end >= _DELAY - 0.01


def test_the_delay_is_not_slept_while_holding_the_platform_semaphore(calls):
    """Six 0.1s runs at concurrency 1. Sleeping the 0.3s delay inside the
    semaphore after each slot's first run (the old order and placement)
    took about 1.5s; waiting it out while other slots run takes about 0.7s."""
    assert _run() < 1.1
