"""
2I B3: grounded only. A dispatch naming an ungrounded surface is a 422
(`ungrounded_surface_not_allowed`), one the worker reported no key for is a
422 (`surface_not_configured`), /api/console/surfaces serves `grounded`,
`configured` and `seen_at`, and the pooled score (scorer 7) is the mean over
grounded surfaces only. Every HTTP test runs on sqlite and on a local
Postgres (test_console_2c3a's db fixture); supply is the recorded fake.
"""
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.services import console_score as score_svc
from soa_shared import surfaces
from soa_shared.models.soa_models import SoaWorkerSurface
from tests.test_console_2c3 import _dims, _score, _two_surfaces, _with_store
from tests.test_console_2c3a import _cycle_229, _get, _supply as _supply_229, db  # noqa: F401  (db: both databases)
from tests.test_console_read_models import as_, http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_console_studies import studies_db  # noqa: F401  (pytest fixture)

BODY = {'merchant_slug': 'wiggle-and-snug', 'study_type': 'ws-2b-fixture'}
SEEN = datetime(2026, 10, 16, 18, 0, tzinfo=timezone.utc)


def _report(db, **configured):
    SoaWorkerSurface.__table__.create(db, checkfirst=True)   # d2f6b8a4c1e9
    with db.begin() as c:
        for sid, ok in configured.items():
            c.execute(text("INSERT INTO soa_worker_surfaces (surface_id, configured, seen_at) VALUES (:s, :c, :t)"),
                      {'s': sid, 'c': ok, 't': SEEN})


def _count(db, table):
    with db.connect() as c:
        return c.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()


# ═══ the registry: grounded, from each runner's code ═════════════════════
def test_the_registry_classifies_every_runner():
    assert {s.id: s.grounded for s in surfaces.SURFACES} == {
        'chatgpt_api': False, 'chatgpt': True, 'gemini_api': False, 'gemini_grounded': True,
        'perplexity': True, 'claude': True, 'aimode': True, 'copilot': True,
        'gemini_web': False, 'chatgpt_web': False}
    assert surfaces.LEGACY['gemini'].grounded is False
    # every runnable surface kind but `api` is grounded, and only those pool
    assert {s.surface for s in surfaces.SURFACES if s.grounded} <= set(surfaces.GROUNDED_KINDS)
    assert surfaces.API not in surfaces.GROUNDED_KINDS


def test_the_default_is_every_grounded_surface_with_a_key():
    configured = {'chatgpt': True, 'chatgpt_api': True, 'gemini_grounded': True, 'gemini_api': True,
                  'perplexity': False, 'claude': True, 'aimode': False, 'copilot': False}
    assert surfaces.default_platforms(configured) == ['chatgpt', 'gemini_grounded', 'claude']


# ═══ dispatch ════════════════════════════════════════════════════════════
@pytest.mark.parametrize('name, instead', [('gemini', 'gemini_grounded'), ('gemini_api', 'gemini_grounded'),
                                           ('chatgpt_api', 'chatgpt')])
def test_the_full_loop_refuses_an_ungrounded_surface_or_alias(http, db, upstream, name, instead):
    as_('alice')
    before = _count(db, 'soa_full_loop_requests')
    r = http.post('/api/full-loop', json={**BODY, 'platforms': ['chatgpt', name]})
    assert r.status_code == 422
    assert r.json()['detail']['code'] == 'ungrounded_surface_not_allowed'
    assert f'Use {instead}.' in r.json()['detail']['message']
    assert _count(db, 'soa_full_loop_requests') == before and upstream.calls == []


def test_the_console_and_the_web_app_refuse_it_too(http, studies_db):
    as_('op')
    before = _count(studies_db, 'soa_cycles')
    console = http.post('/api/console/cycles', params={'org': 10},
                        json={'study_type': 'ws-2b-fixture', 'platforms': ['gemini'], 'cycle_code': 'WS-2I-C'})
    web = http.post('/api/cycles', json={'cycle_code': 'WS-2I-W', 'study_type': 'ws-2b-fixture',
                                         'platforms': ['chatgpt', 'gemini'], 'runs_per_query': 1,
                                         'comparison_set': [{'entity_id': 1, 'comparison_code': 'M001', 'role': 'primary'}]})
    for r in (console, web):
        assert r.status_code == 422, r.text
        assert r.json()['detail']['code'] == 'ungrounded_surface_not_allowed'
        assert 'Use gemini_grounded.' in r.json()['detail']['message']
    assert _count(studies_db, 'soa_cycles') == before


def test_a_surface_the_worker_has_no_key_for_is_refused(http, db, upstream):
    _report(db, chatgpt=True, perplexity=False)
    as_('alice')
    r = http.post('/api/full-loop', json={**BODY, 'platforms': ['chatgpt', 'perplexity']})
    assert r.status_code == 422
    assert r.json()['detail'] == {'code': 'surface_not_configured', 'message': 'no key on the worker for perplexity'}
    assert http.post('/api/full-loop', json={**BODY, 'platforms': ['chatgpt']}).status_code == 202


def test_a_surface_the_worker_has_not_reported_on_is_not_refused(http, db, upstream):
    """Before the worker's first boot on d2f6b8a4c1e9 the table is empty."""
    as_('alice')
    assert http.post('/api/full-loop', json={**BODY, 'platforms': ['chatgpt', 'claude']}).status_code == 202


# ═══ /api/console/surfaces ═══════════════════════════════════════════════
def test_the_surface_list_carries_grounded_and_the_workers_report(http, db):
    _report(db, chatgpt=True, gemini_grounded=True, claude=False, gemini_api=True)
    as_('alice')
    by_id = {e['id']: e for e in http.get('/api/console/surfaces').json()['surfaces']}
    pick = lambda e: {k: e[k] for k in ('id', 'label', 'fidelity_label', 'grounded', 'configured', 'seen_at')}
    assert pick(by_id['chatgpt']) == {'id': 'chatgpt', 'label': 'ChatGPT with web search (OpenAI API)',
                                      'fidelity_label': 'API with search grounding', 'grounded': True,
                                      'configured': True, 'seen_at': by_id['chatgpt']['seen_at']}
    assert by_id['chatgpt']['seen_at'].startswith('2026-10-16')
    assert (by_id['claude']['grounded'], by_id['claude']['configured']) == (True, False)
    assert (by_id['gemini_api']['grounded'], by_id['gemini_api']['configured']) == (False, True)
    assert (by_id['perplexity']['configured'], by_id['perplexity']['seen_at']) == (None, None)   # not reported
    assert not any('key' in k.lower() and k != 'configured' for e in by_id.values() for k in e)


# ═══ scorer 7: pooled over grounded surfaces only ════════════════════════
def _second_surface_ungrounded(db):
    """The two-surface fixture with its consumer-UI runs re-cast as the
    ungrounded Gemini API: the same answers, on an `api` surface."""
    with db.begin() as c:
        c.execute(text("UPDATE soa_runs SET platform = 'gemini_api', surface = 'api' WHERE surface = 'consumer_ui'"))
        c.execute(text("UPDATE soa_expectation_outcomes SET platform = 'gemini_api', surface = 'api' "
                       "WHERE surface = 'consumer_ui'"))


def test_an_ungrounded_surface_is_listed_not_pooled(http, upstream, db):
    from tests.test_console_2c3 import _supply
    _two_surfaces(db)
    _second_surface_ungrounded(db)
    _supply(upstream)
    as_('alice')
    body = _score(http)
    assert [s['surface'] for s in body['surfaces']] == ['grounded_api']
    grounded = body['surfaces'][0]
    assert grounded['score'] == pytest.approx(45.3 / 69 * 100)   # the two-surface fixture's grounded API
    assert body['score'] == round(grounded['score']) == 66
    assert body['surfaces_left_out'] == [{'surface': 'api', 'label': 'API, no tools', 'reason': 'ungrounded · not scored'}]
    assert body['coverage']['ungrounded'] == ['api']
    assert body['coverage']['line'] == ('1 surface, 10 questions, 2 agents · pooled across surfaces, equal weight'
                                        ' · the model-only API: ungrounded · not scored')
    assert set(_dims(body)['share_of_mentions']['by_surface']) == {'grounded_api'}


def test_the_229_fixture_scores_the_same_under_6_and_7(http, upstream, db, monkeypatch):
    """229's runs are all on grounded_api (its 'gemini' ran as
    gemini_grounded), so excluding ungrounded surfaces changes nothing."""
    _cycle_229(db)
    _supply_229(upstream)
    now = _get(http, rescore=1).json()
    monkeypatch.setattr(surfaces, 'GROUNDED_KINDS', surfaces.SURFACE_KINDS)   # v6: every answered surface pooled
    before = _get(http, rescore=1).json()
    assert now['score'] is not None and now['score'] == before['score']
    assert now['surfaces'] == before['surfaces'] and 'ungrounded' not in now['coverage']


def test_the_recompute_line_names_the_change_only_when_the_number_moved():
    old = {'scorer_version': '6', 'score': 32}
    dropped = {'coverage': {'ungrounded': ['api']}}   # 2I-2: and only when an ungrounded surface was dropped
    assert score_svc.recompute_line(old, {'scorer_version': '7', 'score': 32, **dropped}, 'stale') == 'scorer 6 → 7'
    assert score_svc.recompute_line({'scorer_version': '6', 'score': 24}, {'scorer_version': '7', 'score': 20, **dropped},
                                    'stale') == 'scorer 6 → 7: ungrounded surfaces excluded from pooling'
    assert score_svc.recompute_line({'scorer_version': '7', 'score': 20}, {'scorer_version': '7', 'score': 21},
                                    'rescore') == 'rescore'


def test_a_stored_v6_score_recomputes_with_the_line_in_its_history(http, upstream, db):
    from tests.test_console_2c3 import _supply
    _with_store(db)
    _two_surfaces(db)
    _second_surface_ungrounded(db)
    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET share_of_algorithm = :b, share_of_algorithm_version = '6' WHERE id = 1"),
                  {'b': json.dumps({'scorer_version': '6', 'adapter_revision': score_svc.ADAPTER_REVISION, 'score': 68})})
    _supply(upstream)
    as_('alice')
    body = _score(http)
    assert (body['score'], body['scorer_version']) == (66, '17')
    assert body['history'][-1]['replaced_because'] == 'scorer 6 → 17: ungrounded surfaces excluded from pooling'
