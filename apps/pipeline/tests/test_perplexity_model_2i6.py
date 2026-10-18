"""
2I-6 B3: Perplexity's model is current and configurable. FL7's Perplexity
runs answered 0 of 5: the runner hard-coded llama-3.1-sonar-large-128k-online,
which Perplexity retired (400 invalid_model). The runner now asks
SOA_PERPLEXITY_MODEL (default sonar-pro, docs.perplexity.ai "Migrate from
Sonar", read 2026-10-17). Requests go through the real openai client to an
httpx MockTransport; nothing reaches Perplexity.
"""
import asyncio
import json
import os

import httpx
import pytest
from openai import AsyncOpenAI

import soa_shared.config as config
from runners.perplexity_runner import PerplexityRunner

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, 'fixtures', 'perplexity', 'invalid_model_400.json')) as fh:
    INVALID = json.load(fh)


def runner_with(monkeypatch, handler, **kwargs):
    monkeypatch.setattr(config, 'PERPLEXITY_API_KEY', 'pplx-test')
    runner = PerplexityRunner(**kwargs)
    runner._client = AsyncOpenAI(api_key='pplx-test', base_url='https://api.perplexity.ai', max_retries=0,
                                 http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return runner


def answer(model):
    return {'id': 'x', 'object': 'chat.completion', 'created': 1, 'model': model,
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'Pampers Swaddlers [1].'}}],
            'usage': {'prompt_tokens': 9, 'completion_tokens': 7, 'total_tokens': 16},
            'citations': ['https://www.target.com/p/pampers-swaddlers']}


def test_the_default_is_the_documented_model():
    assert config.SOA_PERPLEXITY_MODEL == 'sonar-pro'


def test_the_runner_sends_the_configured_model(monkeypatch):
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body['model'])
        return httpx.Response(200, json=answer(body['model']))
    monkeypatch.setattr(config, 'SOA_PERPLEXITY_MODEL', 'sonar')
    result = asyncio.run(runner_with(monkeypatch, handler).run('best newborn diapers'))
    assert sent == ['sonar'] and result.status == 'success' and result.model == 'sonar'
    assert result.retrieved_sources == ['https://www.target.com/p/pampers-swaddlers']


def test_an_explicit_model_still_wins(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=answer(json.loads(request.content)['model']))
    result = asyncio.run(runner_with(monkeypatch, handler, model='sonar-reasoning-pro').run('q'))
    assert result.model == 'sonar-reasoning-pro'


def test_a_400_invalid_model_is_the_runs_error(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(INVALID['status'], json=INVALID['body'])
    monkeypatch.setattr(config, 'SOA_PERPLEXITY_MODEL', 'llama-3.1-sonar-large-128k-online')
    result = asyncio.run(runner_with(monkeypatch, handler).run('q'))
    assert (result.status, result.response_text) == ('error', '')
    assert 'invalid_model' in result.error and 'llama-3.1-sonar-large-128k-online' in result.error
    assert len(calls) == 1   # a 400 is not retried: asking again cannot make the model exist
