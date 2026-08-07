"""
Tests for generation/discovery_probe.py — Part 3 (rescue session):
last-resort LLM-assisted URL discovery. Same mocking idiom as
test_fetch_probe.py: _call_once (the actual OpenAI Responses-API call)
is mocked, never a real network/API call.
"""
import json
from unittest.mock import patch

from generation.discovery_probe import MAX_URLS_REQUESTED, probe_discover_urls

URL = "https://acme.example.com"


def test_returns_urls_from_successful_call():
    with patch("generation.discovery_probe._call_once") as mock_call:
        mock_call.return_value = {"urls": ["https://acme.example.com/products/tee"]}
        result = probe_discover_urls(URL, "key")

    assert mock_call.call_count == 1
    assert result == {"urls": ["https://acme.example.com/products/tee"]}


def test_malformed_json_is_empty_never_raises():
    with patch("generation.discovery_probe._call_once") as mock_call:
        mock_call.side_effect = json.JSONDecodeError("bad", "doc", 0)
        result = probe_discover_urls(URL, "key")

    assert result == {"urls": []}


def test_api_exception_is_empty_never_raises():
    with patch("generation.discovery_probe._call_once") as mock_call:
        mock_call.side_effect = RuntimeError("boom")
        result = probe_discover_urls(URL, "key")

    assert mock_call.call_count == 1
    assert result == {"urls": []}


def test_missing_api_key_is_empty_and_never_calls_the_client():
    with patch("generation.discovery_probe._call_once") as mock_call:
        result = probe_discover_urls(URL, None)

    mock_call.assert_not_called()
    assert result == {"urls": []}


def test_unexpected_shape_is_empty_never_raises():
    with patch("generation.discovery_probe._call_once") as mock_call:
        mock_call.side_effect = ValueError("Expected 'urls' to be a list")
        result = probe_discover_urls(URL, "key")

    assert result == {"urls": []}


def test_urls_are_capped_at_max_requested():
    with patch("generation.discovery_probe.OpenAI") as mock_openai_cls:
        mock_client = mock_openai_cls.return_value
        many_urls = [f"https://acme.example.com/products/item-{i}" for i in range(10)]
        mock_client.responses.create.return_value.output_text = json.dumps({"urls": many_urls})
        result = probe_discover_urls(URL, "key")

    assert len(result["urls"]) == MAX_URLS_REQUESTED


def test_strips_markdown_fence():
    with patch("generation.discovery_probe.OpenAI") as mock_openai_cls:
        mock_client = mock_openai_cls.return_value
        content = "```json\n" + json.dumps({"urls": ["https://acme.example.com/products/tee"]}) + "\n```"
        mock_client.responses.create.return_value.output_text = content
        result = probe_discover_urls(URL, "key")

    assert result == {"urls": ["https://acme.example.com/products/tee"]}
