"""
Tests for membership_probe.py — Stage 16 (Part 4) worker-side
membership/loyalty program probe.

probe_membership's one-attempt-plus-one-retry, never-throw contract is
tested by mocking _call_once (the actual OpenAI call) so no real API
call is made — same idiom as test_competitor_generator.py mocking
generate_competitors' _call_once. _parse_result is pure and tested
directly against raw model-content strings.
"""
import json
from unittest.mock import patch

import pytest

from generation.membership_probe import _parse_result, probe_membership


# ── probe_membership: retry / never-throw ────────────────────────────────

def test_returns_result_from_first_successful_attempt():
    with patch("generation.membership_probe._call_once") as mock_call:
        mock_call.return_value = {"result": "yes", "raw_evidence": "Has a rewards program."}
        result = probe_membership("Acme", "key")

    assert mock_call.call_count == 1
    assert result == {"result": "yes", "raw_evidence": "Has a rewards program."}


def test_retries_once_after_first_attempt_fails():
    with patch("generation.membership_probe._call_once") as mock_call:
        mock_call.side_effect = [RuntimeError("boom"), {"result": "no", "raw_evidence": None}]
        result = probe_membership("Acme", "key")

    assert mock_call.call_count == 2
    assert result == {"result": "no", "raw_evidence": None}


def test_both_attempts_failing_returns_unknown_never_raises():
    with patch("generation.membership_probe._call_once") as mock_call:
        mock_call.side_effect = [RuntimeError("boom"), RuntimeError("boom again")]
        result = probe_membership("Acme", "key")

    assert mock_call.call_count == 2
    assert result == {"result": "unknown", "raw_evidence": None}


def test_store_url_is_optional_and_passed_through(monkeypatch):
    captured = {}

    def fake_call_once(brand_name, store_url, api_key):
        captured["store_url"] = store_url
        return {"result": "unknown", "raw_evidence": None}

    monkeypatch.setattr("generation.membership_probe._call_once", fake_call_once)
    probe_membership("Acme", "key", store_url="https://acme.example.com")

    assert captured["store_url"] == "https://acme.example.com"


# ── _parse_result: defensive JSON parsing ────────────────────────────────

def test_parse_result_plain_json():
    result = _parse_result(json.dumps({"result": "yes", "evidence": "Loyalty program found."}))
    assert result == {"result": "yes", "raw_evidence": "Loyalty program found."}


def test_parse_result_strips_markdown_code_fence():
    content = "```json\n" + json.dumps({"result": "no", "evidence": None}) + "\n```"
    result = _parse_result(content)
    assert result == {"result": "no", "raw_evidence": None}


def test_parse_result_lowercases_and_trims_result():
    result = _parse_result(json.dumps({"result": " YES ", "evidence": None}))
    assert result["result"] == "yes"


def test_parse_result_null_or_missing_evidence_normalizes_to_none():
    assert _parse_result(json.dumps({"result": "unknown"}))["raw_evidence"] is None
    assert _parse_result(json.dumps({"result": "unknown", "evidence": ""}))["raw_evidence"] is None
    assert _parse_result(json.dumps({"result": "unknown", "evidence": "   "}))["raw_evidence"] is None


@pytest.mark.parametrize("bad_content", [
    "not json at all",
    json.dumps(["an", "array", "not", "an", "object"]),
    json.dumps({"result": "maybe"}),   # not in VALID_RESULTS
    json.dumps({"evidence": "no result key at all"}),
])
def test_parse_result_raises_on_malformed_or_invalid_content(bad_content):
    with pytest.raises(Exception):
        _parse_result(bad_content)
