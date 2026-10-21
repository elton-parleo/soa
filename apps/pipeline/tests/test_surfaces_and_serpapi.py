"""
2B §4: surface fidelity, the SerpApi runners, and per-surface accuracy.

The SerpApi runner is exercised on fixture bodies through httpx's
MockTransport: no request leaves the process, and no key is real. See
tests/fixtures/serpapi/README.md for what those bodies are (hand-written in
SerpApi's documented shape; none is a captured response).
"""
import asyncio
import json
import os

import httpx
import pytest

from runners import run_orchestrator as ro
from runners.platform_response import PlatformResponse
from runners.serpapi_runner import (
    COST_UNITS_PER_CALL, SERPAPI_URL, AiModeRunner, CopilotRunner, build_params,
    parse_response, render_text_blocks,
)
from soa_shared import surface_accuracy as sa
from soa_shared import surfaces

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures', 'serpapi')
KEY = 'serp-test-key-not-real'


def body(name):
    with open(os.path.join(FIXTURES, name)) as fh:
        return json.load(fh)


def transport(payload, status=200, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handler)


def run(runner, text='best diapers for a newborn'):
    return asyncio.run(runner.run(text))


# ── the catalogue ─────────────────────────────────────────────────────────

def test_every_runner_platform_has_a_surface_and_collector():
    for platform in ro._RUNNER_CLASSES:
        assert surfaces.surface_of(platform) in surfaces.SURFACE_KINDS, platform
        assert surfaces.collector_of(platform), platform


def test_each_grounded_api_surface_sits_beside_an_ungrounded_one():
    assert surfaces.surface_of('chatgpt') == 'grounded_api'
    assert surfaces.surface_of('chatgpt_api') == 'api'
    assert surfaces.surface_of('gemini_grounded') == 'grounded_api'
    assert surfaces.surface_of('gemini_api') == 'api'
    # Perplexity Sonar is grounded by nature, and labelled so.
    assert surfaces.surface_of('perplexity') == 'grounded_api'


def test_the_modal_lists_only_what_will_run_plus_the_two_with_no_provider():
    off = surfaces.modal_list(env={})
    ids = [s['id'] for s in off]
    assert 'aimode' not in ids and 'copilot' not in ids
    assert ids[-2:] == ['gemini_web', 'chatgpt_web']
    for entry in off[-2:]:
        assert entry['available'] is False
        assert 'No hosted provider we have verified.' in entry['unavailable_reason']
    on = surfaces.modal_list(env={'SOA_CONSUMER_SURFACES_ENABLED': '1', 'SERPAPI_API_KEY': 'k'})
    assert {'aimode', 'copilot'} <= {s['id'] for s in on if s['available']}
    for entry in on:
        assert entry['fidelity'] and entry['surface_label']


def test_the_orchestrator_refuses_a_consumer_surface_that_is_off(monkeypatch):
    monkeypatch.delenv('SOA_CONSUMER_SURFACES_ENABLED', raising=False)
    with pytest.raises(ValueError, match='consumer surfaces are off'):
        ro.RunOrchestrator('C-1', platforms=['aimode'])
    with pytest.raises(ValueError, match='No hosted provider'):
        ro.RunOrchestrator('C-1', platforms=['gemini_web'])


def test_an_api_answer_is_answered_and_a_failed_call_is_not_a_result():
    ok = PlatformResponse('text', 0, 0, 0, 'chatgpt', 'm')
    failed = PlatformResponse('', 0, 0, 0, 'chatgpt', 'm', error='boom', status='error')
    wall = PlatformResponse('Sign in', 0, 0, 0, 'copilot', 'm', answer_status='sign_in_wall')
    assert ro.answer_status_for(ok) == 'answered'
    assert ro.answer_status_for(failed) is None
    assert ro.answer_status_for(wall) == 'sign_in_wall'


# ── the SerpApi request ───────────────────────────────────────────────────

def test_request_shape_matches_the_engine():
    assert build_params('aimode', 'q') == {
        'engine': 'google_ai_mode', 'q': 'q',
        'location': 'Berkeley, California, United States', 'gl': 'us', 'hl': 'en'}
    # Bing Copilot takes no location.
    assert build_params('copilot', 'q') == {'engine': 'bing_copilot', 'q': 'q'}


def test_the_key_goes_to_serpapi_and_nowhere_else():
    seen = []
    result = run(AiModeRunner(KEY, transport=transport(body('google_ai_mode_answer.json'), seen=seen)))
    assert str(seen[0].url).startswith(SERPAPI_URL)
    assert seen[0].url.params['api_key'] == KEY
    assert KEY not in json.dumps(result.__dict__)


# ── answer, no AI answer, sign-in wall ────────────────────────────────────

def test_an_ai_mode_answer_is_rebuilt_in_page_order_with_products_and_sources():
    result = run(AiModeRunner(KEY, transport=transport(body('google_ai_mode_answer.json'))))
    assert result.status == 'success' and result.answer_status == 'answered'
    assert result.response_text.startswith('The top newborn diapers focus on absorbency')
    assert 'Products shown:\n- Pampers Swaddlers Baby Diapers: $27.97, Walmart' in result.response_text
    # References sorted by index, as the engine sorts them.
    assert result.retrieved_sources == [
        'https://www.pampers.com/en-us/diapers-wipes/swaddlers',
        'https://www.babylist.com/hello-baby/best-diapers']
    assert result.cost_units == COST_UNITS_PER_CALL == 1


def test_a_copilot_answer_puts_the_header_first():
    result = run(CopilotRunner(KEY, transport=transport(body('bing_copilot_answer.json'))))
    assert result.answer_status == 'answered'
    assert result.response_text.startswith('Pampers Swaddlers are the best overall newborn diapers.')


def test_no_ai_answer_is_a_recorded_result_not_a_failure():
    result = run(AiModeRunner(KEY, transport=transport(body('google_ai_mode_no_ai_answer.json'))))
    assert result.status == 'success'
    assert result.answer_status == 'no_ai_answer'
    assert result.response_text == ''
    assert "Google hasn't returned any results" in result.error


def test_a_sign_in_wall_is_a_recorded_result():
    result = run(CopilotRunner(KEY, transport=transport(body('bing_copilot_sign_in_wall.json'))))
    assert result.status == 'success'
    assert result.answer_status == 'sign_in_wall'


def test_an_http_error_from_serpapi_is_a_failed_call_without_the_key():
    result = run(CopilotRunner(KEY, transport=transport({'error': f'Invalid API key {KEY}.'}, status=401)))
    assert result.status == 'error' and result.answer_status is None
    assert 'HTTP 401 from SerpApi' in result.error
    assert KEY not in result.error


def test_engine_render_examples():
    assert render_text_blocks([{'type': 'list', 'snippet': 'Picks:', 'list': ['A', 'B']},
                               {'type': 'table', 'headers': ['x', 'y'], 'table': [[1, 2]]}]) \
        == 'Picks:\n- A\n- B\n\nx | y\n1 | 2'
    assert parse_response({'reconstructed_markdown': '**Pampers** first.'})['text'] == '**Pampers** first.'


# ── per-surface accuracy, never pooled ────────────────────────────────────

def test_per_surface_accuracy_is_split_by_surface_and_never_pooled():
    outcome_rows = [
        ('grounded_api', 'chatgpt', 'exact', 8), ('grounded_api', 'chatgpt', 'wrong', 2),
        ('api', 'chatgpt_api', 'exact', 1), ('api', 'chatgpt_api', 'wrong', 3),
        ('consumer_ui', 'aimode', 'exact', 2), ('consumer_ui', 'aimode', 'absent', 3),
        ('consumer_ui', 'aimode', 'partial', 1), ('consumer_ui', 'aimode', 'unverifiable', 1),
    ]
    run_rows = [
        ('grounded_api', 'chatgpt', 'success', 'answered', 10),
        ('api', 'chatgpt_api', 'success', 'answered', 4),
        ('consumer_ui', 'aimode', 'success', 'answered', 4),
        ('consumer_ui', 'aimode', 'success', 'no_ai_answer', 2),
        ('consumer_ui', 'aimode', 'success', 'sign_in_wall', 1),
        ('consumer_ui', 'aimode', 'error', None, 1),
    ]
    out = sa.summarise(outcome_rows, run_rows)
    assert [s['surface'] for s in out] == ['api', 'grounded_api', 'consumer_ui']
    by = {s['surface']: s for s in out}
    assert by['grounded_api']['accuracy'] == 0.8
    assert by['api']['accuracy'] == 0.25
    # absent and unverifiable stay out of the denominator; partial is in it.
    assert by['consumer_ui']['scored'] == 3 and by['consumer_ui']['accuracy'] == round(2 / 3, 4)
    assert by['consumer_ui']['coverage'] == {'runs': 8, 'results': 7, 'answered': 4,
                                             'no_ai_answer': 2, 'sign_in_wall': 1, 'blocked': 0,
                                             'failed': 1}
    # No pooled number anywhere.
    assert isinstance(out, list) and not any('overall' in s for s in out)


def test_a_legacy_null_surface_is_placed_by_platform():
    out = sa.summarise([(None, 'perplexity', 'exact', 1)], [(None, 'perplexity', 'success', None, 1)])
    assert out[0]['surface'] == 'grounded_api'


def test_the_ops_report_prints_each_surface_and_no_total():
    from scripts import surface_accuracy as cli
    text = cli.render(sa.summarise([('api', 'chatgpt_api', 'exact', 1), ('grounded_api', 'chatgpt', 'wrong', 1)],
                                   []))
    assert text.splitlines()[0].startswith('api (API, no tools): accuracy 100.0%')
    assert 'grounded_api (API with search grounding): accuracy 0.0%' in text
    assert 'overall' not in text.lower() and 'total' not in text.lower()
