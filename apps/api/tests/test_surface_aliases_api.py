"""
2D: the API's three ways to start a cycle store resolved surface ids,
never an alias, and refuse an unknown name with a 422 before anything is
written: POST /api/cycles (the web app), POST /api/console/cycles, POST
/api/full-loop (whose stored request the coordinator turns into a cycle;
229 was one that stored "gemini"). The resolver is soa_shared/surfaces.py;
the cycle and run side is apps/pipeline/tests/test_surface_aliases.py.
"""
import json

from sqlalchemy import text

from tests.test_console_read_models import as_, db, http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_console_studies import studies_db  # noqa: F401  (pytest fixture)


def _cycle(db, code):
    with db.connect() as c:
        row = c.execute(text("SELECT platforms, surfaces FROM soa_cycles WHERE cycle_code = :c"),
                        {'c': code}).one()
    return tuple(json.loads(v) if isinstance(v, str) else v for v in row)


def _start(http, code, platforms):
    as_('op')
    return http.post('/api/console/cycles', params={'org': 10}, json={
        'study_type': 'ws-2b-fixture', 'platforms': platforms, 'cycle_code': code})


def test_gemini_is_refused_and_gemini_grounded_starts_on_grounded_api(http, studies_db):
    """2I: only grounded surfaces start. 'gemini' still means gemini_api
    (2D), which is ungrounded, so it is refused naming what to send."""
    with studies_db.begin() as c:
        c.exec_driver_sql("ALTER TABLE soa_cycles ADD COLUMN surfaces TEXT")   # a7d2c9e4b1f6
    refused = _start(http, 'WS-2D-GEMINI', ['chatgpt', 'gemini'])
    assert refused.status_code == 422
    assert refused.json()['detail']['code'] == 'ungrounded_surface_not_allowed'
    assert 'use gemini_grounded' in refused.json()['detail']['message']
    assert _start(http, 'WS-2D-GROUNDED', ['chatgpt', 'gemini_grounded']).status_code == 201
    assert _cycle(studies_db, 'WS-2D-GROUNDED') == (['chatgpt', 'gemini_grounded'],
                                                    {'chatgpt': 'grounded_api', 'gemini_grounded': 'grounded_api'})


def _cycle_count(db):
    with db.connect() as c:
        return c.execute(text("SELECT COUNT(*) FROM soa_cycles")).scalar()


def test_an_unknown_name_is_a_422_on_the_console_and_nothing_is_written(http, studies_db):
    before = _cycle_count(studies_db)
    r = _start(http, 'WS-2D-BAD', ['chatgpt', 'gemini_pro'])
    assert r.status_code == 422 and r.json()['detail'].startswith("unknown surface 'gemini_pro'")
    assert _cycle_count(studies_db) == before


def test_an_unknown_name_is_a_422_on_the_web_app_s_create_cycle(http, studies_db):
    as_('op')
    r = http.post('/api/cycles', json={'cycle_code': 'WS-2D-WEB', 'study_type': 'ws-2b-fixture',
                                       'platforms': ['gemini_pro'], 'runs_per_query': 1,
                                       'comparison_set': [{'entity_id': 1, 'comparison_code': 'M001',
                                                           'role': 'primary'}]})
    assert r.status_code == 422 and "unknown surface 'gemini_pro'" in r.text


def test_the_full_loop_request_stores_resolved_ids_and_refuses_an_unknown_name(http, db):
    as_('alice')
    body = {'merchant_slug': 'wiggle-and-snug', 'study_type': 'ws-2b-fixture'}
    started = http.post('/api/full-loop', json={**body, 'platforms': ['chatgpt', 'gemini_grounded', 'chatgpt']})
    assert started.status_code == 202, started.text
    with db.connect() as c:
        stored = c.execute(text("SELECT platforms FROM soa_full_loop_requests WHERE id = :i"),
                           {'i': started.json()['full_loop_id']}).scalar()
    assert json.loads(stored) == ['chatgpt', 'gemini_grounded']
    ungrounded = http.post('/api/full-loop', json={**body, 'platforms': ['chatgpt', 'gemini']})
    assert ungrounded.status_code == 422 and ungrounded.json()['detail']['code'] == 'ungrounded_surface_not_allowed'
    refused = http.post('/api/full-loop', json={**body, 'platforms': ['gemini_pro']})
    assert refused.status_code == 422 and refused.json()['detail'].startswith("unknown surface 'gemini_pro'")


def test_the_surface_list_shows_resolved_ids_with_their_fidelity(http):
    as_('alice')
    entries = http.get('/api/console/surfaces').json()['surfaces']
    by_id = {e['id']: e for e in entries}
    assert 'gemini' not in by_id
    assert (by_id['gemini_api']['surface_label'], by_id['gemini_grounded']['surface_label']) == (
        'API, no tools', 'API with search grounding')
    assert by_id['gemini_api']['fidelity'] == 'Gemini API, no grounding tool: answers from the model alone'
