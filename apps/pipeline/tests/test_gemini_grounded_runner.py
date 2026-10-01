"""
Tests for runners/gemini_grounded_runner.py — mocked google-genai SDK.
Confirms platform identifier, retrieved_sources extraction from grounding
metadata, 503 recovery inherited from GeminiRunner, and that cycles never
run ungrounded Gemini.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from google.genai.errors import ServerError

import runners.gemini_runner as gemini_runner_module
from runners.gemini_grounded_runner import GeminiGroundedRunner
from runners.gemini_runner import GeminiRunner
from runners.run_orchestrator import _RUNNER_CLASSES, normalize_platforms


def _fake_response(text, sources, prompt_tokens=10, completion_tokens=20):
    grounding_chunks = [
        SimpleNamespace(web=SimpleNamespace(uri=url)) for url in sources
    ]
    candidate = SimpleNamespace(
        grounding_metadata=SimpleNamespace(grounding_chunks=grounding_chunks)
    )
    return SimpleNamespace(
        text=text,
        candidates=[candidate],
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt_tokens,
            candidates_token_count=completion_tokens,
        ),
    )


def test_platform_identifier_is_gemini_grounded():
    runner = GeminiGroundedRunner()
    assert runner.platform == "gemini_grounded"


def test_existing_gemini_platform_is_untouched():
    assert GeminiRunner.platform == "gemini"


def test_call_api_populates_retrieved_sources_from_grounding_metadata():
    runner = GeminiGroundedRunner()
    fake_resp = _fake_response(
        "Sephora has 20% off today.",
        ["https://example.com/sephora-sale", "https://example.com/source2"],
    )
    runner._client.aio.models.generate_content = AsyncMock(return_value=fake_resp)

    result = asyncio.run(runner._call_api("best skincare deals"))

    assert result.platform == "gemini_grounded"
    assert result.response_text == "Sephora has 20% off today."
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 20
    assert result.search_triggered is True
    assert result.retrieved_sources == [
        "https://example.com/sephora-sale",
        "https://example.com/source2",
    ]


def test_call_api_no_grounding_metadata_yields_none_sources():
    runner = GeminiGroundedRunner()
    fake_resp = _fake_response("No search needed.", [])
    runner._client.aio.models.generate_content = AsyncMock(return_value=fake_resp)

    result = asyncio.run(runner._call_api("simple query"))

    assert result.retrieved_sources is None
    assert result.search_triggered is False


def test_call_api_passes_google_search_tool_in_config():
    runner = GeminiGroundedRunner()
    fake_resp = _fake_response("text", [])
    mock_generate = AsyncMock(return_value=fake_resp)
    runner._client.aio.models.generate_content = mock_generate

    asyncio.run(runner._call_api("query"))

    _, kwargs = mock_generate.call_args
    assert kwargs["model"] == runner.model
    tools = kwargs["config"].tools
    assert len(tools) == 1
    assert tools[0].google_search is not None


def test_503s_fall_back_to_fallback_model_with_grounding(monkeypatch):
    monkeypatch.setattr(gemini_runner_module.asyncio, "sleep", AsyncMock())
    runner = GeminiGroundedRunner()
    runner.fallback_model = "gemini-fallback-test"
    unavailable = ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}})
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == runner.model:
            raise unavailable
        return _fake_response("grounded answer", ["https://example.com/a"])

    runner._client.aio.models.generate_content = generate

    result = asyncio.run(runner.run("query"))

    assert result.status == "success"
    assert result.platform == "gemini_grounded"
    assert result.model == runner.fallback_model
    assert result.retrieved_sources == ["https://example.com/a"]
    assert calls[-1] == runner.fallback_model
    assert runner.gemini_503_fallback_successes == 1


def test_cycles_never_run_ungrounded_gemini():
    assert "gemini" not in _RUNNER_CLASSES
    assert _RUNNER_CLASSES["gemini_grounded"] is GeminiGroundedRunner


def test_gemini_platform_runs_grounded():
    assert normalize_platforms(["chatgpt", "gemini"]) == ["chatgpt", "gemini_grounded"]
    assert normalize_platforms(["gemini", "gemini_grounded"]) == ["gemini_grounded"]
    assert normalize_platforms(["chatgpt", "claude"]) == ["chatgpt", "claude"]
