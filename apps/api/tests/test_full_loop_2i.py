"""
2I B1: a reads-only full loop. "Run full loop" on a merchant with no study
reads its pages (supply's stage one) and stops: no study, no surfaces, no
cycle. Every test runs on sqlite and on a local Postgres (test_console_2c3a's
db fixture); supply is the recorded fake of test_console_read_models.
"""
import json

import pytest
from sqlalchemy import text

import app.routers.full_loop as fl
from tests.fixtures import full_loop_pre_2i as frozen
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import TOKEN_A, as_, http, start, upstream, worker_started  # noqa: F401

BRAND = 'wiggle-and-snug-brand'
RUN = '/api/truesync/merchants/wiggle-and-snug-brand/full-loop/41'
B4_FIELDS = ('surface_ids', 'runs_per_question', 'study_id')


def reads_only(http, **overrides):
    return http.post('/api/full-loop', json={'merchant_slug': BRAND, **overrides})


def _row(db, rid):
    with db.connect() as c:
        return dict(c.execute(text("SELECT * FROM soa_full_loop_requests WHERE id = :i"), {'i': rid}).mappings().one())


def test_a_merchant_with_no_study_queues_a_reads_only_request(http, db, upstream):
    as_('alice')
    r = reads_only(http)
    assert r.status_code == 202
    body = r.json()
    assert body['mode'] == 'reads_only' and body['status'] == 'queued'
    assert upstream.calls == []                                  # no supply call from the API
    row = _row(db, body['full_loop_id'])
    assert row['study_type'] is None and row['merchant_slug'] == BRAND and row['status'] == 'reference_pending'
    assert (json.loads(row['platforms']) if isinstance(row['platforms'], str) else row['platforms']) == []


def test_a_reads_only_request_sends_no_surface(http, db, upstream):
    as_('alice')
    r = reads_only(http, platforms=['chatgpt'])
    assert r.status_code == 422 and 'send no platforms' in r.json()['detail']


def test_a_request_with_a_study_still_needs_a_surface(http, db, upstream):
    as_('alice')
    assert start(http, platforms=[]).status_code == 422


@pytest.mark.parametrize('stage, supply_status, expected', [
    ('reference_pending', 'running', ['running', 'none_yet', 'not_applicable']),
    ('reads_done', 'reference_done', ['done', 'none_yet', 'not_applicable']),
])
def test_the_strip_names_no_study_and_no_scoring(http, db, upstream, stage, supply_status, expected):
    as_('alice')
    rid = reads_only(http).json()['full_loop_id']
    worker_started(db, rid, run_id=41, supply_status=supply_status)
    with db.begin() as c:
        c.execute(text("UPDATE soa_full_loop_requests SET status = :s WHERE id = :i"), {'s': stage, 'i': rid})
    upstream.answer('GET', RUN, body={'id': 41, 'status': supply_status, 'finished_at': '2026-10-16T18:02:00+00:00'},
                    token=TOKEN_A)
    view = http.get(f'/api/full-loop/{rid}').json()
    assert [c['state'] for c in view['strip']] == expected, (view['status'], view['error'])
    assert view['strip'][1]['label'] == 'Study: none yet'
    assert view['mode'] == 'reads_only' and view['platforms'] == [] and view['surfaces'] == []
    assert view['read_at'] == ('2026-10-16T18:02:00+00:00' if stage == 'reads_done' else None)


def test_latest_returns_the_mode_and_the_read_date(http, db, upstream):
    as_('alice')
    rid = reads_only(http).json()['full_loop_id']
    worker_started(db, rid, run_id=41, supply_status='reference_done')
    with db.begin() as c:
        c.execute(text("UPDATE soa_full_loop_requests SET status = 'reads_done' WHERE id = :i"), {'i': rid})
    upstream.answer('GET', RUN, body={'id': 41, 'status': 'reference_done', 'finished_at': '2026-10-16T18:02:00+00:00'},
                    token=TOKEN_A)
    as_('op')
    latest = http.get('/api/console/full-loop/latest', params={'org': 10, 'merchant': BRAND}).json()
    assert (latest['mode'], latest['read_at'], latest['status']) == ('reads_only', '2026-10-16T18:02:00+00:00', 'reads_done')


def test_reads_done_is_never_timed_out(http, db, upstream):
    """reads_done is terminal: not in the stale list, so a read days ago is
    still 'done', not 'timed_out'."""
    as_('alice')
    rid = reads_only(http).json()['full_loop_id']
    worker_started(db, rid, run_id=41, supply_status='reference_done')
    with db.begin() as c:
        c.execute(text("UPDATE soa_full_loop_requests SET status = 'reads_done', updated_at = '2026-10-01T00:00:00+00:00', "
                       "created_at = '2026-10-01T00:00:00+00:00' WHERE id = :i"), {'i': rid})
    upstream.answer('GET', RUN, body={'id': 41, 'status': 'reference_done'}, token=TOKEN_A)
    view = http.get(f'/api/full-loop/{rid}').json()
    assert view['status'] == 'reads_done' and view['error'] is None


@pytest.mark.parametrize('stage, supply_status', [
    ('reference_pending', None), ('reference_pending', 'running'), ('reference_done', 'reference_done'),
    ('cycle_planned', 'reference_done'), ('scored', 'scored'), ('failed', 'failed')])
def test_a_request_with_a_study_reads_byte_for_byte_as_before(http, db, upstream, stage, supply_status):
    """The combined status of a request with a study, against the function as
    it was on main before 2I (frozen copy): the same, plus B4's three fields."""
    as_('alice')
    rid = start(http).json()['full_loop_id']
    with db.begin() as c:
        c.execute(text("UPDATE soa_full_loop_requests SET status = :s, supply_status = :ss WHERE id = :i"),
                  {'s': stage, 'ss': supply_status, 'i': rid})
    row = _row(db, rid)
    view = {'id': 33, 'status': supply_status} if supply_status else None
    now = fl.combined_status(row, supply_view=view, supply_error=None)
    before = frozen.combined_status(row, supply_view=view, supply_error=None)
    # identical but for B4's three added fields, and 2I-5's failed_step on a failed request
    assert {k: now.pop(k) for k in B4_FIELDS} == {'surface_ids': ['chatgpt', 'gemini_grounded'],
                                                 'runs_per_question': 1, 'study_id': 'ws-2b-fixture'}
    assert now.pop('failed_step', None) == ('reads' if stage == 'failed' else None)
    # 2K-3 adds the cycle's local dates (no cycle here); 2K-4 the study, with its own local date
    assert now.pop('study')['id'] == 'ws-2b-fixture'
    assert json.dumps(now, sort_keys=True, default=str) == json.dumps(before, sort_keys=True, default=str)
    assert 'mode' not in now and 'read_at' not in now


# ═══ B4: what the run dialog compares against ════════════════════════════
def test_the_cycle_list_names_each_cycles_surfaces_runs_and_study(http, db, upstream):
    """The W&S fixture cycle ran ChatGPT, Gemini with Google Search and AI
    Mode, one run per question, of ws-2b-fixture."""
    as_('op')
    runs = http.get('/api/console/runs', params={'org': 10}).json()
    first = runs[0]
    assert (first['surface_ids'], first['runs_per_question'], first['study_id']) == (
        ['chatgpt', 'gemini_grounded', 'aimode'], 1, 'ws-2b-fixture')
    assert first['surfaces'] == ['consumer_ui', 'grounded_api']           # the kinds, as before


def test_a_cycle_not_run_yet_names_what_it_stored(db):
    from app.services import console_read_models as rm
    planned = {'platforms': ['chatgpt', 'gemini'], 'surfaces': None, 'runs_per_query': 3, 'study_type': 'x'}
    assert rm.run_identity(planned, [])['surface_ids'] == ['chatgpt', 'gemini_api']
    stored = {**planned, 'surfaces': {'chatgpt': 'grounded_api', 'gemini_grounded': 'grounded_api'}}
    assert rm.run_identity(stored, [])['surface_ids'] == ['chatgpt', 'gemini_grounded']
    # what ran wins: 229 stored "gemini" and ran gemini_grounded
    assert rm.run_identity(planned, ['gemini_grounded', 'chatgpt'])['surface_ids'] == ['chatgpt', 'gemini_grounded']


def test_latest_names_its_surfaces_runs_and_study(http, db, upstream):
    as_('alice')
    start(http, platforms=['chatgpt', 'gemini_grounded'])
    as_('op')
    latest = http.get('/api/console/full-loop/latest', params={'org': 10}).json()
    assert (latest['surface_ids'], latest['runs_per_question'], latest['study_id']) == (
        ['chatgpt', 'gemini_grounded'], 1, 'ws-2b-fixture')
    as_('alice')
    reads_only(http)
    as_('op')
    latest = http.get('/api/console/full-loop/latest', params={'org': 10, 'merchant': BRAND}).json()
    assert latest['merchant'] == BRAND
    assert (latest['surface_ids'], latest['runs_per_question'], latest['study_id']) == ([], 1, None)
