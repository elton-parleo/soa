"""
BasePlatformRunner.run() owns retries (3 attempts, Retry-After aware). The
SDK clients' own default of 2 retries would nest inside each attempt — up
to 9 calls per run, all inside one attempt's timeout — so every SDK-backed
runner builds its client with max_retries=0.
"""
import pytest

import soa_shared.config as config
from runners.claude_runner import ClaudeRunner
from runners.openai_api_runner import OpenAIApiRunner
from runners.openai_runner import OpenAIRunner
from runners.perplexity_runner import PerplexityRunner


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(config, 'OPEN_AI_API_KEY', 'sk-test')
    monkeypatch.setattr(config, 'PERPLEXITY_API_KEY', 'pplx-test')
    monkeypatch.setattr(config, 'ANTHROPIC_CLAUDE_API_KEY', 'sk-ant-test')


@pytest.mark.parametrize('runner_class', [OpenAIRunner, OpenAIApiRunner, PerplexityRunner])
def test_openai_sdk_runners_leave_retries_to_the_base_runner(runner_class):
    assert runner_class()._client.max_retries == 0


def test_claude_runner_leaves_retries_to_the_base_runner():
    assert ClaudeRunner().client.max_retries == 0
