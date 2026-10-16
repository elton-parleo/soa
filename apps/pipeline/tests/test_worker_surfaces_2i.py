"""
2I B3: the worker reports at boot which runners have their key, one row per
runner in soa_worker_surfaces, booleans only. On sqlite and on a local
Postgres (any_engine).
"""
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

import soa_shared.config as config
from runners import configured as worker_surfaces
from runners.run_orchestrator import _RUNNER_CLASSES
from soa_pg_harness import model_schema
from soa_shared import surfaces

SECRET = 'sk-test-never-stored'
BOOT = datetime(2026, 10, 16, 18, 0, tzinfo=timezone.utc)


def _keys(monkeypatch, **values):
    for name in ('OPEN_AI_API_KEY', 'GEMINI_API_KEY', 'PERPLEXITY_API_KEY', 'ANTHROPIC_CLAUDE_API_KEY'):
        monkeypatch.setattr(config, name, values.get(name, ''))


def _rows(engine):
    with engine.connect() as c:
        return {r[0]: (bool(r[1]), r[2]) for r in c.execute(text(
            "SELECT surface_id, configured, seen_at FROM soa_worker_surfaces"))}


def test_every_runner_is_reported():
    assert set(worker_surfaces.configured(env={})) == set(_RUNNER_CLASSES)


def test_a_runner_is_configured_when_its_key_is_set(monkeypatch):
    _keys(monkeypatch, OPEN_AI_API_KEY=SECRET, GEMINI_API_KEY=SECRET)
    found = worker_surfaces.configured(env={'SOA_CONSUMER_SURFACES_ENABLED': '1', 'SERPAPI_API_KEY': SECRET})
    assert found == {'chatgpt': True, 'chatgpt_api': True, 'gemini_grounded': True, 'gemini_api': True,
                     'perplexity': False, 'claude': False, 'aimode': True, 'copilot': True}
    assert surfaces.default_platforms(found) == ['chatgpt', 'gemini_grounded', 'aimode', 'copilot']


def test_the_boot_report_writes_one_boolean_row_per_runner_and_replaces_the_last(any_engine, monkeypatch):
    model_schema(any_engine)
    _keys(monkeypatch, OPEN_AI_API_KEY=SECRET)
    worker_surfaces.report(any_engine, env={}, now=BOOT)
    rows = _rows(any_engine)
    assert set(rows) == set(_RUNNER_CLASSES)
    assert rows['chatgpt'][0] is True and rows['claude'][0] is False and rows['aimode'][0] is False
    _keys(monkeypatch, OPEN_AI_API_KEY=SECRET, ANTHROPIC_CLAUDE_API_KEY=SECRET)
    worker_surfaces.report(any_engine, env={})
    again = _rows(any_engine)
    assert len(again) == len(rows) and again['claude'][0] is True
    with any_engine.connect() as c:
        dump = ' '.join(str(v) for row in c.execute(text("SELECT * FROM soa_worker_surfaces")) for v in row)
    assert SECRET not in dump


def test_a_worker_on_a_database_without_the_table_still_boots(caplog):
    engine = create_engine('sqlite://')
    assert set(worker_surfaces.report(engine, env={})) == set(_RUNNER_CLASSES)
    assert 'could not report' in caplog.text
