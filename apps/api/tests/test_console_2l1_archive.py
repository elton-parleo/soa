"""
2L-1 §B3: archive a study.

Decision (Elton, Oct 21): "New study" stays the only way to change a study's
questions (an in-place edit would break week-over-week), and the study list
gets an archive. soa_query_generation_jobs.archived_at (the study's own row;
there is no soa_studies table).

    POST /api/console/studio/studies/{id}/archive     operator only; 409 while a loop of it runs
    POST /api/console/studio/studies/{id}/unarchive   operator only

An archived study leaves /studio/studies (the run dialog's study choice) and
the Prompts default, comes back with ?archived=1, and its cycles stay
readable. On the FL12-shaped brand fixture (console_fixture_2j2), with a
second, older study of the same merchant beside it.
"""
import json

import pytest
from sqlalchemy import text

from tests import console_fixture_2j2 as f2j2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2j2 import _brand, _get, pampers_tenant  # noqa: F401  (fixture)
from tests.test_console_read_models import as_, http, upstream  # noqa: F401  (fixtures)

OTHER = 'pampers-earlier'


def _two_studies(db):
    cycle = _brand(db)
    with db.begin() as c:
        job = dict(c.execute(text("SELECT * FROM soa_query_generation_jobs WHERE study_type = :st"),
                             {'st': f2j2.STUDY}).mappings().one())
        job.update(id=9001, study_type=OTHER, study_name='Pampers earlier', created_at='2026-10-01T12:00:00+00:00')
        for k in ('tier_config', 'allowed_categories', 'retailer_names', 'stage_targets', 'personas', 'provenance'):
            if isinstance(job.get(k), (dict, list)):
                job[k] = json.dumps(job[k])
        cols = ', '.join(job)
        c.execute(text(f"INSERT INTO soa_query_generation_jobs ({cols}) VALUES ({', '.join(':' + k for k in job)})"), job)
    return cycle


def _post(http, study, action, user='op'):
    as_(user)
    return http.post(f'/api/console/studio/studies/{study}/{action}', params={'org': 10})


def _listed(http, **params):
    return [s['id'] for s in _get(http, 'studio/studies', merchant=f2j2.MERCHANT, **params)]


def _loop(db, status, study=f2j2.STUDY):
    with db.begin() as c:
        c.execute(text("""INSERT INTO soa_full_loop_requests (organization_id, merchant_slug, study_type, platforms,
            runs_per_query, status, created_by, created_at, updated_at)
            VALUES (10, :m, :st, '["chatgpt"]', 1, :s, 'op', '2026-10-21T10:00:00+00:00', '2026-10-21T10:00:00+00:00')"""),
                  {'m': f2j2.MERCHANT, 'st': study, 's': status})


def test_archive_leaves_the_list_and_archived_1_brings_it_back(http, db, pampers_tenant):
    _two_studies(db)
    assert set(_listed(http)) == {f2j2.STUDY, OTHER}
    r = _post(http, OTHER, 'archive')
    assert r.status_code == 200, r.text
    assert r.json()['id'] == OTHER and r.json()['archived'] is True and r.json()['archived_at']
    assert _listed(http) == [f2j2.STUDY]
    every = {s['id']: s for s in _get(http, 'studio/studies', merchant=f2j2.MERCHANT, archived=1)}
    assert set(every) == {f2j2.STUDY, OTHER}
    assert every[OTHER]['archived'] is True and every[f2j2.STUDY]['archived'] is False
    assert every[OTHER]['archived_at'] == r.json()['archived_at']


def test_unarchive_brings_it_back(http, db, pampers_tenant):
    _two_studies(db)
    _post(http, OTHER, 'archive')
    r = _post(http, OTHER, 'unarchive')
    assert r.status_code == 200 and r.json() == {'id': OTHER, 'archived': False, 'archived_at': None}
    assert set(_listed(http)) == {f2j2.STUDY, OTHER}


def test_archiving_twice_keeps_the_first_stamp(http, db, pampers_tenant):
    _two_studies(db)
    first = _post(http, OTHER, 'archive').json()['archived_at']
    assert _post(http, OTHER, 'archive').json()['archived_at'] == first


def test_operator_only(http, db, pampers_tenant):
    _two_studies(db)
    for action in ('archive', 'unarchive'):
        assert _post(http, OTHER, action, user='alice').status_code == 403
    assert set(_listed(http)) == {f2j2.STUDY, OTHER}


def test_a_study_not_the_org_s_is_a_404(http, db, pampers_tenant):
    _two_studies(db)
    assert _post(http, 'no-such-study', 'archive').status_code == 404


@pytest.mark.parametrize('status', ['reference_pending', 'reference_done', 'cycle_planned', 'scoring'])
def test_a_study_with_a_running_loop_cannot_be_archived(http, db, pampers_tenant, status):
    _two_studies(db)
    _loop(db, status)
    r = _post(http, f2j2.STUDY, 'archive')
    assert r.status_code == 409
    assert r.json()['detail'].startswith('A full loop of this study is running (request ')
    assert ';' not in r.json()['detail']
    assert f2j2.STUDY in _listed(http)


@pytest.mark.parametrize('status', ['scored', 'failed', 'reads_done'])
def test_a_finished_loop_does_not_block(http, db, pampers_tenant, status):
    _two_studies(db)
    _loop(db, status)
    assert _post(http, f2j2.STUDY, 'archive').status_code == 200


def test_a_running_cycle_blocks_too(http, db, pampers_tenant):
    _two_studies(db)
    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET status = 'running' WHERE id = 229"))
    r = _post(http, f2j2.STUDY, 'archive')
    assert r.status_code == 409 and '(cycle ' in r.json()['detail']


def test_prompts_default_skips_an_archived_study(http, db, pampers_tenant):
    _two_studies(db)
    assert _get(http, 'prompts', merchant=f2j2.MERCHANT)['study']['id'] == f2j2.STUDY   # the newest cycle's
    _post(http, f2j2.STUDY, 'archive')
    assert _get(http, 'prompts', merchant=f2j2.MERCHANT)['study']['id'] == OTHER
    _post(http, f2j2.STUDY, 'unarchive')
    assert _get(http, 'prompts', merchant=f2j2.MERCHANT)['study']['id'] == f2j2.STUDY


def test_an_archived_study_s_cycles_stay_readable(http, db, pampers_tenant):
    cycle = _two_studies(db)
    before = {e: _get(http, e, cycle=cycle) for e in ('answers', 'answers/summary')}
    _post(http, f2j2.STUDY, 'archive')
    for e, body in before.items():
        assert _get(http, e, cycle=cycle) == body
    assert _get(http, 'overview', cycle=cycle, merchant=f2j2.MERCHANT)['study']['id'] == f2j2.STUDY
    assert cycle in [r['id'] for r in _get(http, 'runs', merchant=f2j2.MERCHANT)]


def test_the_model_carries_the_column():
    from soa_shared.models.soa_models import SoaQueryGenerationJob
    col = SoaQueryGenerationJob.__table__.c.archived_at
    assert col.nullable and col.type.timezone
