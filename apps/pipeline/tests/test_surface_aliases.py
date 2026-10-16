"""
2D: a cycle and its runs carry the surface that ran, never an alias.

Cycle 229 was created with platforms ["gemini"] and RUN as gemini_grounded
(the orchestrator's own alias), so its runs sit on grounded_api, while the
September cycle's "gemini" runs sit on api. Now one resolver
(soa_shared/surfaces.py) decides, at creation, explicitly: "gemini" is the
ungrounded gemini_api, "gemini_grounded" is the grounded runner, anything
else is refused. Each test runs on sqlite and on Postgres
(packages/testing/soa_pg_harness.py) over the model schema plus migration
a7d2c9e4b1f6's column.
"""
import asyncio
import json
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

import runners.run_orchestrator as run_orchestrator_module
from runners.platform_response import PlatformResponse
from runners.run_orchestrator import RunOrchestrator
from soa_pg_harness import model_schema
from soa_shared import surfaces
from soa_shared.cycle_creation import create_cycle_with_comparison_set
from soa_shared.models.soa_models import Base


def _fake(platform_id):
    class Runner:
        platform = platform_id

        def __init__(self, *a, **k):
            pass

        async def run(self, query_text):
            return PlatformResponse(response_text=f'{platform_id}: {query_text}', prompt_tokens=1,
                                    completion_tokens=1, latency_ms=1, platform=platform_id, model='fake')
    return Runner


@pytest.fixture
def db(any_engine, monkeypatch):
    model_schema(any_engine)
    kind = 'JSON' if any_engine.dialect.name == 'postgresql' else 'TEXT'
    t = Base.metadata.tables
    with any_engine.begin() as c:
        c.exec_driver_sql(f"ALTER TABLE soa_cycles ADD COLUMN surfaces {kind}")   # a7d2c9e4b1f6
        c.execute(t['organizations'].insert(), [{'id': 10, 'name': 'Wiggle & Snug'}])
        c.execute(t['soa_entities'].insert(), [{'id': 1, 'name': 'Wiggle & Snug', 'slug': 'wiggle-and-snug',
                                                 'entity_type': 'brand'}])
        c.execute(t['soa_queries'].insert(), [{
            'id': 1, 'query_code': 'WIG_001', 'query_text': 'Is Wiggle & Snug Bum Balm still sold?',
            'category': 'Cross-Category', 'stage': 'Research', 'specificity': 'Narrow',
            'persona': 'New / First-Time Parent', 'status': 'Active', 'study_type': 'ws',
            'study_pattern': 'retailer', 'organization_id': 10}])
    monkeypatch.setattr(run_orchestrator_module, 'session_factory',
                        sessionmaker(bind=any_engine, expire_on_commit=False))
    for platform_id in ('gemini_api', 'gemini_grounded', 'chatgpt'):
        monkeypatch.setitem(run_orchestrator_module._RUNNER_CLASSES, platform_id, _fake(platform_id))
    return any_engine


def _create(db, code, platforms):
    with db.begin() as conn:
        cycle_id, _ = create_cycle_with_comparison_set(
            conn, cycle_code=code, study_type='ws', study_pattern='retailer', cycle_mode='query',
            truecost_tiers=None, total_runs_planned=len(platforms), start_date=date(2026, 10, 15),
            platforms=json.dumps(platforms), runs_per_query=1, organization_id=10, created_by='op',
            notes=None, comparison_set=[{'entity_id': 1, 'comparison_code': 'M001', 'role': 'primary'}])
    return cycle_id


def _cycle(db, cycle_id):
    with db.connect() as c:
        platforms, by = c.execute(text("SELECT platforms, surfaces FROM soa_cycles WHERE id = :i"),
                                  {'i': cycle_id}).one()
    load = lambda v: json.loads(v) if isinstance(v, str) else v
    return load(platforms), load(by)


def _runs(db, cycle_id):
    with db.connect() as c:
        return [tuple(r) for r in c.execute(text(
            "SELECT platform, surface, collector FROM soa_runs WHERE cycle_id = :i ORDER BY platform"),
            {'i': cycle_id})]


def test_gemini_and_gemini_grounded_store_different_runner_ids_and_surfaces(db):
    ungrounded = _create(db, 'C-GEMINI', ['chatgpt', 'gemini'])
    grounded = _create(db, 'C-GROUNDED', ['chatgpt', 'gemini_grounded'])
    assert _cycle(db, ungrounded) == (['chatgpt', 'gemini_api'], {'chatgpt': 'grounded_api', 'gemini_api': 'api'})
    assert _cycle(db, grounded) == (['chatgpt', 'gemini_grounded'],
                                    {'chatgpt': 'grounded_api', 'gemini_grounded': 'grounded_api'})

    for code, cycle_id in (('C-GEMINI', ungrounded), ('C-GROUNDED', grounded)):
        platforms, _ = _cycle(db, cycle_id)
        asyncio.run(RunOrchestrator(cycle_code=code, platforms=platforms, runs_per_query=1).run_cycle())
    assert _runs(db, ungrounded) == [('chatgpt', 'grounded_api', 'openai'), ('gemini_api', 'api', 'google_genai')]
    assert _runs(db, grounded) == [('chatgpt', 'grounded_api', 'openai'),
                                   ('gemini_grounded', 'grounded_api', 'google_genai')]


def test_an_unknown_name_is_refused_before_anything_is_written(db):
    with pytest.raises(surfaces.UnknownSurface, match="unknown surface 'gemini_pro'"):
        _create(db, 'C-BAD', ['chatgpt', 'gemini_pro'])
    with db.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM soa_cycles")).scalar() == 0


def test_a_cycle_stored_with_the_alias_before_2d_runs_the_ungrounded_api(db):
    """A pre-2D row: "gemini" on the cycle, no surfaces. It runs what the
    name means now, and the run says so; it never falls through to the
    grounded runner."""
    t = Base.metadata.tables
    with db.begin() as c:
        c.execute(t['soa_cycles'].insert(), [{
            'id': 7, 'cycle_code': 'C-PRE-2D', 'start_date': date(2026, 10, 14), 'status': 'planned',
            'study_type': 'ws', 'study_pattern': 'retailer', 'cycle_mode': 'query', 'organization_id': 10,
            'platforms': ['gemini'], 'runs_per_query': 1}])
        c.execute(t['soa_cycle_entities'].insert(), [
            {'cycle_id': 7, 'entity_id': 1, 'comparison_code': 'M001', 'role': 'primary'}])
    asyncio.run(RunOrchestrator(cycle_code='C-PRE-2D', platforms=['gemini'], runs_per_query=1).run_cycle())
    assert _runs(db, 7) == [('gemini_api', 'api', 'google_genai')]


def test_without_the_migration_a_cycle_is_still_created(db, caplog):
    with db.begin() as c:
        c.exec_driver_sql("ALTER TABLE soa_cycles DROP COLUMN surfaces")
    cycle_id = _create(db, 'C-NO-COLUMN', ['gemini'])
    with db.connect() as c:
        platforms = c.execute(text("SELECT platforms FROM soa_cycles WHERE id = :i"), {'i': cycle_id}).scalar()
    assert (json.loads(platforms) if isinstance(platforms, str) else platforms) == ['gemini_api']
    assert 'migration a7d2c9e4b1f6 not applied' in caplog.text


def test_the_surface_list_offers_resolved_ids_with_their_fidelity_and_never_an_alias():
    listed = surfaces.modal_list(env={})
    ids = [s['id'] for s in listed]
    assert not set(ids) & set(surfaces.ALIASES) and 'gemini' not in ids
    assert {'gemini_api', 'gemini_grounded'} <= set(ids)
    for s in listed:
        assert s['fidelity'] and s['surface_label'] == surfaces.SURFACE_LABELS[s['surface']]
    by_id = {s['id']: s for s in listed}
    assert (by_id['gemini_api']['surface'], by_id['gemini_grounded']['surface']) == ('api', 'grounded_api')
