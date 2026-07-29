"""
Tests for revenue_probe.py — Part 5 (R1) worker-side annual-revenue
estimate probe.

probe_revenue's one-attempt-plus-one-retry, never-throw contract is
tested by mocking _call_once (the actual OpenAI call) so no real API
call is made — same idiom as test_membership_probe.py. _parse_result is
pure and tested directly against raw model-content strings.
"""
import json
from unittest.mock import patch

import pytest

from generation.revenue_probe import _parse_result, probe_revenue


# ── probe_revenue: retry / never-throw ───────────────────────────────────

def test_returns_result_from_first_successful_attempt():
    with patch("generation.revenue_probe._call_once") as mock_call:
        mock_call.return_value = {"annual_revenue_usd": 5_000_000.0, "basis": "small DTC brand", "quote": "small DTC brand"}
        result = probe_revenue("Acme", "key")

    assert mock_call.call_count == 1
    assert result == {"annual_revenue_usd": 5_000_000.0, "basis": "small DTC brand", "quote": "small DTC brand"}


def test_retries_once_after_first_attempt_fails():
    with patch("generation.revenue_probe._call_once") as mock_call:
        mock_call.side_effect = [RuntimeError("boom"), {"annual_revenue_usd": None, "basis": None, "quote": None}]
        result = probe_revenue("Acme", "key")

    assert mock_call.call_count == 2
    assert result == {"annual_revenue_usd": None, "basis": None, "quote": None}


def test_both_attempts_failing_returns_all_none_never_raises():
    with patch("generation.revenue_probe._call_once") as mock_call:
        mock_call.side_effect = [RuntimeError("boom"), RuntimeError("boom again")]
        result = probe_revenue("Acme", "key")

    assert mock_call.call_count == 2
    assert result == {"annual_revenue_usd": None, "basis": None, "quote": None}


def test_store_url_is_optional_and_passed_through(monkeypatch):
    captured = {}

    def fake_call_once(brand_name, store_url, api_key):
        captured["store_url"] = store_url
        return {"annual_revenue_usd": None, "basis": None, "quote": None}

    monkeypatch.setattr("generation.revenue_probe._call_once", fake_call_once)
    probe_revenue("Acme", "key", store_url="https://acme.example.com")

    assert captured["store_url"] == "https://acme.example.com"


# ── _parse_result: defensive JSON parsing + plausibility clamp ───────────

def test_parse_result_clean_number():
    result = _parse_result(json.dumps({"annual_revenue_usd": 12_000_000, "basis": "estimated from headcount"}))
    assert result == {
        "annual_revenue_usd": 12_000_000.0,
        "basis": "estimated from headcount",
        "quote": "estimated from headcount",
    }


def test_parse_result_strips_markdown_code_fence():
    content = "```json\n" + json.dumps({"annual_revenue_usd": 1_000_000, "basis": "guess"}) + "\n```"
    result = _parse_result(content)
    assert result["annual_revenue_usd"] == 1_000_000.0


def test_parse_result_refusal_returns_null_revenue():
    result = _parse_result(json.dumps({"annual_revenue_usd": None, "basis": None}))
    assert result == {"annual_revenue_usd": None, "basis": None, "quote": None}


@pytest.mark.parametrize("absurd_value", [1, 50_000, 500_000_000_000, 10 ** 15])
def test_parse_result_absurd_revenue_outside_plausible_range_becomes_null(absurd_value):
    result = _parse_result(json.dumps({"annual_revenue_usd": absurd_value, "basis": "a guess"}))
    assert result["annual_revenue_usd"] is None
    # basis/quote still carry the model's stated reasoning even when the
    # number itself is discarded as implausible — an honest record of
    # what was rejected and why, not a silent double-failure.
    assert result["basis"] == "a guess"


@pytest.mark.parametrize("boundary_value", [100_000, 100_000_000_000])
def test_parse_result_boundary_values_are_plausible(boundary_value):
    result = _parse_result(json.dumps({"annual_revenue_usd": boundary_value, "basis": "boundary"}))
    assert result["annual_revenue_usd"] == float(boundary_value)


def test_parse_result_null_or_missing_basis_normalizes_to_none():
    assert _parse_result(json.dumps({"annual_revenue_usd": None}))["basis"] is None
    assert _parse_result(json.dumps({"annual_revenue_usd": None, "basis": ""}))["basis"] is None
    assert _parse_result(json.dumps({"annual_revenue_usd": None, "basis": "   "}))["basis"] is None


@pytest.mark.parametrize("bad_content", [
    "not json at all",
    json.dumps(["an", "array", "not", "an", "object"]),
])
def test_parse_result_raises_on_malformed_content(bad_content):
    with pytest.raises(Exception):
        _parse_result(bad_content)
