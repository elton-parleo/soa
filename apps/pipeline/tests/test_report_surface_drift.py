"""
2D: scripts/report_surface_drift.py, read only, on the console's 229-shaped
fixture (apps/api/tests/console_fixture_229.py, its cycles and runs) and on
the two shapes production is known to have: 229 created with "gemini" and
run as gemini_grounded, and a September cycle whose "gemini" rows are the
ungrounded API. sqlite and Postgres.
"""
import importlib.util
import json
import os

import pytest
from sqlalchemy import text

from scripts import report_surface_drift as drift

_FIXTURE = os.path.join(os.path.dirname(__file__), '..', '..', 'api', 'tests', 'console_fixture_229.py')
_spec = importlib.util.spec_from_file_location('console_fixture_229', _FIXTURE)
f229 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f229)


@pytest.fixture
def db(any_engine):
    kind = 'JSON' if any_engine.dialect.name == 'postgresql' else 'TEXT'
    with any_engine.begin() as c:
        c.exec_driver_sql(f"CREATE TABLE soa_cycles (id INTEGER PRIMARY KEY, cycle_code TEXT, platforms {kind})")
        c.exec_driver_sql("CREATE TABLE soa_runs (id INTEGER PRIMARY KEY, cycle_id INTEGER, platform TEXT, surface TEXT)")
        data = f229.build()
        for cy in data['cycles']:
            c.execute(text("INSERT INTO soa_cycles (id, cycle_code, platforms) VALUES (:i, :c, :p)"),
                      {'i': cy['id'], 'c': cy['cycle_code'], 'p': json.dumps(cy['platforms'])})
        c.execute(text("INSERT INTO soa_runs (id, cycle_id, platform, surface) VALUES (:id, :cycle_id, :platform, :surface)"),
                  [{k: r[k] for k in ('id', 'cycle_id', 'platform', 'surface')} for r in data['runs']])
    return any_engine


def _report(db, *codes):
    with db.connect() as conn:
        return drift.report(conn, list(codes) or None)


def test_on_the_fixture_as_built_229_stores_resolved_ids_and_only_its_errored_runs_stand_out(db):
    """The fixture stores ["chatgpt", "gemini_grounded"], so its Gemini rows
    are what the name means. Its 2 errored runs are labelled consumer_ui
    under gemini_grounded (a fixture shortcut), and the report says so."""
    (c,) = _report(db, f229.CYCLE_229)
    assert c['platforms'] == ['chatgpt', 'gemini_grounded'] and c['surfaces'] is None
    rows = {e['name']: [(g['platform'], g['surface'], g['runs'], g['drift']) for g in e['rows']] for e in c['names']}
    assert rows['gemini_grounded'] == [('gemini_grounded', 'consumer_ui', 2, True), ('gemini_grounded', 'grounded_api', 256, False)]
    assert rows['chatgpt'] == [('chatgpt', 'grounded_api', 258, False)]
    assert c['unclaimed'] == []


def test_229_as_production_has_it_stored_gemini_on_grounded_rows(db):
    with db.begin() as conn:
        conn.execute(text("UPDATE soa_cycles SET platforms = :p WHERE id = 229"), {'p': json.dumps(['chatgpt', 'gemini'])})
    (c,) = _report(db, f229.CYCLE_229)
    gemini = next(e for e in c['names'] if e['name'] == 'gemini')
    assert (gemini['now_id'], gemini['now_surface']) == ('gemini_api', 'api')
    assert [(g['platform'], g['surface'], g['runs'], g['drift']) for g in gemini['rows']] == [
        ('gemini_grounded', 'consumer_ui', 2, True), ('gemini_grounded', 'grounded_api', 256, True)]
    assert c['drift'] is True
    out = drift.render([c])
    assert 'rows: gemini_grounded on grounded_api x 256   DRIFT: on grounded_api, the name now means api' in out


def test_a_september_shaped_cycle_s_gemini_rows_are_what_the_name_means(db):
    with db.begin() as conn:
        conn.execute(text("INSERT INTO soa_cycles (id, cycle_code, platforms) VALUES (150, 'SEPT', :p)"),
                     {'p': json.dumps(['chatgpt', 'gemini'])})
        conn.execute(text("INSERT INTO soa_runs (id, cycle_id, platform, surface) VALUES "
                          "(90001, 150, 'gemini', 'api'), (90002, 150, 'gemini', 'api'), (90003, 150, 'chatgpt', 'grounded_api')"))
    (c,) = _report(db, 'SEPT')
    gemini = next(e for e in c['names'] if e['name'] == 'gemini')
    assert [(g['platform'], g['surface'], g['runs'], g['drift']) for g in gemini['rows']] == [('gemini', 'api', 2, False)]
    assert c['drift'] is False


def test_it_writes_nothing(db):
    def counts():
        with db.connect() as conn:
            return [conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in ('soa_cycles', 'soa_runs')]
    before = counts()
    _report(db)
    assert counts() == before
