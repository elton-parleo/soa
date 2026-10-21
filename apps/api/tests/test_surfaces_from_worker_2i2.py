"""
2I-2: the dialog lists what the worker reports it can run. A consumer
surface (aimode, copilot) is listed from soa_worker_surfaces, never from the
API's SOA_CONSUMER_SURFACES_ENABLED / SERPAPI_API_KEY, which are the
worker's settings (the API never calls SerpApi). conftest strips both from
every API test; the dispatch tests here set them on to show they change
nothing. Every HTTP test runs on sqlite and on a local Postgres.
"""
import os
import re

import pytest

from tests.test_console_2c3a import db  # noqa: F401  (db: both databases)
from tests.test_console_read_models import as_, http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_grounded_2i import BODY, _report

API = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _surface(http, sid):
    return {e['id']: e for e in http.get('/api/console/surfaces').json()['surfaces']}[sid]


@pytest.mark.parametrize('reported, available, reason, note', [
    (True, True, None, None),
    (False, False, 'no key on the worker', 'no key on the worker'),
    (None, True, None, 'the worker has not reported yet'),
])
def test_aimode_is_listed_as_the_worker_reports_it(http, db, reported, available, reason, note):
    if reported is not None:
        _report(db, aimode=reported)
    as_('alice')
    row = _surface(http, 'aimode')
    assert (row['configured'], row['available'], row['unavailable_reason'], row['worker_note']) == (
        reported, available, reason, note)
    assert row['fidelity_label'] == 'Consumer UI, logged out' and row['grounded'] is True


def test_an_api_surface_the_worker_has_not_reported_reads_the_same(http, db):
    _report(db, aimode=True)
    as_('alice')
    perplexity = _surface(http, 'perplexity')
    assert (perplexity['configured'], perplexity['available'], perplexity['worker_note']) == (
        None, True, 'the worker has not reported yet')


def test_the_two_with_no_provider_stay_as_they_were(http, db):
    _report(db, aimode=True, copilot=True)
    as_('alice')
    entries = http.get('/api/console/surfaces').json()['surfaces']
    assert [e['id'] for e in entries][-2:] == ['gemini_web', 'chatgpt_web']
    for e in entries[-2:]:
        assert e['available'] is False and 'No hosted provider we have verified.' in e['unavailable_reason']
        assert e['worker_note'] is None


@pytest.mark.parametrize('api_env_on', [False, True])
def test_dispatch_follows_the_worker_whatever_the_api_env_says(http, db, upstream, monkeypatch, api_env_on):
    if api_env_on:
        monkeypatch.setenv('SOA_CONSUMER_SURFACES_ENABLED', '1')
        monkeypatch.setenv('SERPAPI_API_KEY', 'not-used-by-the-api')
    _report(db, aimode=False, copilot=True)
    as_('alice')
    refused = http.post('/api/full-loop', json={**BODY, 'platforms': ['aimode']})
    assert refused.status_code == 422
    assert refused.json()['detail'] == {'code': 'surface_not_configured', 'message': 'no key on the worker for aimode'}
    accepted = http.post('/api/full-loop', json={**BODY, 'platforms': ['copilot']})
    assert accepted.status_code == 202, accepted.text
    status = http.get(f"/api/full-loop/{accepted.json()['full_loop_id']}").json()
    assert [(s['id'], s['available']) for s in status['surfaces']] == [('copilot', True)]


def test_no_api_code_reads_the_worker_s_serpapi_settings():
    """The API's code (app/, api/, clients/, its soa_shared/config.py) names
    neither setting, nor calls the env-reading helpers in soa_shared/surfaces."""
    pattern = re.compile(r'SOA_CONSUMER_SURFACES_ENABLED|SERPAPI_API_KEY|'
                         r'\bunavailable_reason\(|\bconsumer_enabled\(|\bmodal_list\(')
    hits = []
    paths = [os.path.join(API, 'soa_shared', 'config.py')]
    for top in ('app', 'api', 'clients'):
        for root, _, files in os.walk(os.path.join(API, top)):
            paths += [os.path.join(root, f) for f in files if f.endswith('.py')]
    for path in paths:
        with open(path) as fh:
            for n, line in enumerate(fh, 1):
                code = line.split('#', 1)[0]
                if pattern.search(code):
                    hits.append(f'{os.path.relpath(path, API)}:{n}')
    assert hits == []
