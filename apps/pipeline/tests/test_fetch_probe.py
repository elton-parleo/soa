"""
Tests for fetch_probe.py — Part 2 (P1/P2): worker-side probe asking
ChatGPT to open one sampled product URL.

probe_fetch's ONE-call, never-throw contract is tested by mocking
_call_once (the actual OpenAI Responses-API call), same idiom as
test_membership_probe.py. _parse_result/_derive_outcome are pure and
tested directly.
"""
import json
from unittest.mock import patch

import pytest

from generation.fetch_probe import (
    FETCH_PROBE_GEMINI,
    _derive_outcome,
    _parse_result,
    probe_fetch,
)

URL = "https://acme.example.com/products/classic-tee"


# ── outcome derivation (P2: three-way + guard) ───────────────────────────

def test_derive_outcome_quoted_price():
    assert _derive_outcome({"accessed": True, "price_found": True, "price": "$29.99"}) == "quoted_price"


def test_derive_outcome_opened_no_price():
    assert _derive_outcome({"accessed": True, "price_found": False, "price": None}) == "opened_no_price"


def test_derive_outcome_opened_price_found_true_but_no_price_string_is_opened_no_price():
    """A guard against a model saying price_found=true with no actual
    price string — must not be treated as a real quote."""
    assert _derive_outcome({"accessed": True, "price_found": True, "price": None}) == "opened_no_price"


def test_derive_outcome_could_not_access():
    assert _derive_outcome({"accessed": False, "price_found": False, "price": None}) == "could_not_access"
    assert _derive_outcome({"accessed": False}) == "could_not_access"


def test_parse_result_shape():
    content = json.dumps({
        "accessed": True, "price_found": True, "price": "$29.99",
        "quote": "Classic Tee — $29.99", "note": "Found the price in the page body.",
    })
    result = _parse_result(content, URL, "product_page")
    assert result == {
        "outcome": "quoted_price", "url": URL, "kind": "product_page", "price": "$29.99",
        "quote": "Classic Tee — $29.99", "note": "Found the price in the page body.",
    }


def test_parse_result_strips_markdown_fence():
    content = "```json\n" + json.dumps({"accessed": False, "price_found": False, "price": None}) + "\n```"
    result = _parse_result(content, URL, "product_page")
    assert result["outcome"] == "could_not_access"


# ── probe_fetch: ONE call, never-throw ────────────────────────────────────

def test_returns_result_from_successful_call():
    with patch("generation.fetch_probe._call_once") as mock_call:
        mock_call.return_value = {
            "outcome": "quoted_price", "url": URL, "price": "$29.99", "quote": "q", "note": "n",
        }
        result = probe_fetch(URL, "key")

    assert mock_call.call_count == 1
    assert result["outcome"] == "quoted_price"


def test_malformed_json_is_inconclusive_never_retried():
    """P2: malformed JSON must become 'inconclusive' directly — this
    probe never retries (unlike membership_probe/revenue_probe's
    2-attempt pattern), so _call_once is invoked exactly once."""
    with patch("generation.fetch_probe._call_once") as mock_call:
        mock_call.side_effect = json.JSONDecodeError("bad", "doc", 0)
        result = probe_fetch(URL, "key", kind="product_page")

    assert mock_call.call_count == 1
    assert result == {
        "outcome": "inconclusive", "url": URL, "kind": "product_page",
        "price": None, "quote": None, "note": None,
    }


def test_kind_defaults_to_none_and_is_preserved_on_inconclusive():
    with patch("generation.fetch_probe._call_once") as mock_call:
        mock_call.side_effect = RuntimeError("boom")
        result = probe_fetch(URL, "key")

    assert result["kind"] is None


def test_api_exception_is_inconclusive_never_raises():
    with patch("generation.fetch_probe._call_once") as mock_call:
        mock_call.side_effect = RuntimeError("boom")
        result = probe_fetch(URL, "key")

    assert mock_call.call_count == 1
    assert result["outcome"] == "inconclusive"


def test_url_and_kind_are_passed_through_to_call_once(monkeypatch):
    captured = {}

    def fake_call_once(url, api_key, kind):
        captured["url"] = url
        captured["api_key"] = api_key
        captured["kind"] = kind
        return {"outcome": "could_not_access", "url": url, "kind": kind, "price": None, "quote": None, "note": None}

    monkeypatch.setattr("generation.fetch_probe._call_once", fake_call_once)
    probe_fetch(URL, "test-key", kind="store_root")

    assert captured["url"] == URL
    assert captured["api_key"] == "test-key"
    assert captured["kind"] == "store_root"


# ── P5: Gemini twin scaffolded off ────────────────────────────────────────

def test_fetch_probe_gemini_defaults_off():
    assert FETCH_PROBE_GEMINI is False
