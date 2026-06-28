"""
Tests for runners/gemini_grounded_runner.py — mocked google-genai SDK.
Confirms platform identifier, retrieved_sources extraction from grounding
metadata, and that the existing "gemini" platform/runner is untouched.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from runners.gemini_grounded_runner import GeminiGroundedRunner
from runners.gemini_runner import GeminiRunner


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
