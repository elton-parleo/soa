"""
Tests for pillar_headlines.py — Part 3 worker-side pillar-headline
generation. generate_pillar_headlines' never-throw, retry-once contract
is tested by mocking _call_once (the actual OpenAI call), same idiom as
test_revenue_probe.py. build_pillar_facts/_validate_headline are pure
and tested directly.
"""
from unittest.mock import patch

import pytest

from generation.pillar_headlines import (
    DEFAULT_HEADLINES,
    NOT_MEASURABLE_HEADLINE,
    SOURCE_DEFAULT,
    SOURCE_GENERATED,
    build_pillar_facts,
    generate_pillar_headlines,
    _validate_headline,
)


# ── build_pillar_facts: honest, lean fact extraction ─────────────────────

_FULL_DIMENSIONS_RAW = {
    "agent_access": {"score": 5, "max": 6, "coverage": "full", "evidence": ["robots.txt is fetchable"]},
    "catalog_context": {"score": 2, "max": 8, "coverage": "full", "evidence": ["3/4 product pages expose a gtin"]},
    "protocol_feed": {"score": 1, "max": 6, "coverage": "full", "evidence": []},
    "price_truth_seen": {"score": 2, "max": 5, "coverage": "full", "evidence": ["price found in code"]},
    "member_value_seen": {"score": 0, "max": 9, "coverage": "na", "evidence": []},
    "deal_citability_seen": {"score": 0, "max": 4, "coverage": "full", "evidence": ["no published deals"]},
    "value_protocols_seen": {"score": 0, "max": 7, "coverage": "full", "evidence": ["no UCP declaration found"]},
}

_VIS_METRICS = {"som_pct": 35.0, "mention_rate": 42.0, "rsi_score": 3.2, "rank_line": "2nd of 4 in the competitor set"}


def test_build_pillar_facts_full_run():
    facts = build_pillar_facts(_FULL_DIMENSIONS_RAW, _VIS_METRICS)

    assert facts["visibility"] == _VIS_METRICS
    assert facts["accessibility"]["earned"] == 8.0
    assert facts["accessibility"]["max"] == 20.0
    assert len(facts["accessibility"]["dimensions"]) == 3

    # member_value_seen is na -> excluded; the other 3 True Value dims present.
    tv_names = [d["name"] for d in facts["true_value"]["dimensions"]]
    assert "Member Value" not in tv_names
    assert len(tv_names) == 3


def test_build_pillar_facts_blocked_dimension_excluded():
    dims = dict(_FULL_DIMENSIONS_RAW)
    dims["agent_access"] = {**dims["agent_access"], "coverage": "blocked"}
    facts = build_pillar_facts(dims, _VIS_METRICS)
    acc_names = [d["name"] for d in facts["accessibility"]["dimensions"]]
    assert "Agent Access" not in acc_names
    assert facts["accessibility"]["earned"] == 3.0  # catalog(2) + protocol(1)


def test_build_pillar_facts_pillar_is_none_when_nothing_measured():
    facts = build_pillar_facts({}, {})
    assert facts["visibility"] is None
    assert facts["accessibility"] is None
    assert facts["true_value"] is None


def test_build_pillar_facts_true_value_none_when_all_dims_na_or_blocked():
    dims = {
        "price_truth_seen": {"score": 0, "max": 5, "coverage": "blocked", "evidence": []},
        "member_value_seen": {"score": 0, "max": 9, "coverage": "na", "evidence": []},
        "deal_citability_seen": {"score": 0, "max": 4, "coverage": "blocked", "evidence": []},
        "value_protocols_seen": {"score": 0, "max": 7, "coverage": "blocked", "evidence": []},
    }
    facts = build_pillar_facts(dims, {})
    assert facts["true_value"] is None


def test_build_pillar_facts_visibility_none_when_all_metrics_none():
    facts = build_pillar_facts({}, {"som_pct": None, "mention_rate": None, "rsi_score": None, "rank_line": None})
    assert facts["visibility"] is None


# ── _validate_headline: length/sentence/number-grounding/placeholder ─────

def test_validate_headline_accepts_a_clean_grounded_sentence():
    facts_text = "- Share of brand mentions: 35%"
    assert _validate_headline("You hold 35% share of all brand mentions.", facts_text) is not None


def test_validate_headline_rejects_over_length():
    long_headline = "a" * 91
    assert _validate_headline(long_headline, "- fact") is None


def test_validate_headline_rejects_exclamation_marks():
    assert _validate_headline("Great news, agents love you!", "- fact") is None


def test_validate_headline_rejects_multiple_sentences():
    assert _validate_headline("First sentence. Second sentence.", "- fact") is None


def test_validate_headline_rejects_a_number_not_in_the_facts():
    facts_text = "- Share of brand mentions: 35%"
    assert _validate_headline("You hold 42% share of all brand mentions.", facts_text) is None


def test_validate_headline_accepts_a_number_that_is_in_the_facts():
    facts_text = "- Share of brand mentions: 35%"
    assert _validate_headline("You hold 35% share of all brand mentions.", facts_text) is not None


@pytest.mark.parametrize("bad", [
    "Lorem ipsum dolor sit amet.",
    "TODO write a real headline here",
    "Your rank is TBD this run.",
    "Value at — this run.",
    "Value at % this run.",
    "See example.com for details.",
    "Your [brand] score improved.",
])
def test_validate_headline_rejects_placeholder_or_encoded_claim_prose(bad):
    assert _validate_headline(bad, "- fact") is None


def test_validate_headline_rejects_non_string():
    assert _validate_headline(None, "- fact") is None
    assert _validate_headline(42, "- fact") is None


def test_validate_headline_rejects_empty_string():
    assert _validate_headline("", "- fact") is None
    assert _validate_headline("   ", "- fact") is None


# ── generate_pillar_headlines: never-throw, retry, storage contract ──────

def test_generate_pillar_headlines_all_generated_on_clean_response():
    with patch("generation.pillar_headlines._call_once") as mock_call:
        mock_call.return_value = {
            "visibility": "You hold 35% share of all brand mentions.",
            "accessibility": "Agent Access earns 5 of 6 points.",
            "true_value": "Price Truth earns 2 of 5 points on your site.",
        }
        result = generate_pillar_headlines(_FULL_DIMENSIONS_RAW, _VIS_METRICS, "key")

    assert mock_call.call_count == 1
    for pillar in ("visibility", "accessibility", "true_value"):
        assert result[pillar]["source"] == SOURCE_GENERATED
        assert result[pillar]["headline"]


def test_generate_pillar_headlines_retries_once_then_falls_back():
    with patch("generation.pillar_headlines._call_once") as mock_call:
        mock_call.side_effect = [RuntimeError("boom"), RuntimeError("boom again")]
        result = generate_pillar_headlines(_FULL_DIMENSIONS_RAW, _VIS_METRICS, "key")

    assert mock_call.call_count == 2
    for pillar in ("visibility", "accessibility", "true_value"):
        assert result[pillar]["source"] == SOURCE_DEFAULT
        assert result[pillar]["headline"] == DEFAULT_HEADLINES[pillar]


def test_generate_pillar_headlines_never_raises_on_malformed_json():
    with patch("generation.pillar_headlines._call_once") as mock_call:
        mock_call.side_effect = ValueError("bad json")
        result = generate_pillar_headlines(_FULL_DIMENSIONS_RAW, _VIS_METRICS, "key")
    assert all(result[p]["source"] == SOURCE_DEFAULT for p in ("visibility", "accessibility", "true_value"))


def test_generate_pillar_headlines_per_pillar_fallback_on_partial_violation():
    # visibility's headline cites a number not in its own facts (should
    # fall back); accessibility/true_value stay generated — one bad
    # pillar must never take the other two down with it.
    with patch("generation.pillar_headlines._call_once") as mock_call:
        mock_call.return_value = {
            "visibility": "You hold 99% share of all brand mentions.",
            "accessibility": "Agent Access earns 5 of 6 points.",
            "true_value": "Price Truth earns 2 of 5 points on your site.",
        }
        result = generate_pillar_headlines(_FULL_DIMENSIONS_RAW, _VIS_METRICS, "key")

    assert result["visibility"]["source"] == SOURCE_DEFAULT
    assert result["visibility"]["headline"] == DEFAULT_HEADLINES["visibility"]
    assert result["accessibility"]["source"] == SOURCE_GENERATED
    assert result["true_value"]["source"] == SOURCE_GENERATED


def test_generate_pillar_headlines_skips_the_api_call_when_nothing_is_measurable():
    with patch("generation.pillar_headlines._call_once") as mock_call:
        result = generate_pillar_headlines({}, {}, "key")

    assert mock_call.call_count == 0
    for pillar in ("visibility", "accessibility", "true_value"):
        assert result[pillar]["source"] == SOURCE_DEFAULT
        assert result[pillar]["headline"] == NOT_MEASURABLE_HEADLINE


def test_generate_pillar_headlines_not_measurable_pillar_never_sent_to_the_model_or_asked_about():
    # true_value has nothing measured (all na/blocked); only visibility
    # and accessibility should even be requested from the model.
    dims = {
        "agent_access": {"score": 5, "max": 6, "coverage": "full", "evidence": []},
        "price_truth_seen": {"score": 0, "max": 5, "coverage": "blocked", "evidence": []},
        "member_value_seen": {"score": 0, "max": 9, "coverage": "na", "evidence": []},
        "deal_citability_seen": {"score": 0, "max": 4, "coverage": "blocked", "evidence": []},
        "value_protocols_seen": {"score": 0, "max": 7, "coverage": "blocked", "evidence": []},
    }
    captured = {}

    def fake_call_once(pillars_with_facts, api_key):
        captured["pillars"] = set(pillars_with_facts.keys())
        return {"visibility": "You hold 35% share of all brand mentions.", "accessibility": "Agent Access earns 5 of 6 points."}

    with patch("generation.pillar_headlines._call_once", side_effect=fake_call_once):
        result = generate_pillar_headlines(dims, _VIS_METRICS, "key")

    assert captured["pillars"] == {"visibility", "accessibility"}
    assert result["true_value"]["source"] == SOURCE_DEFAULT
    assert result["true_value"]["headline"] == NOT_MEASURABLE_HEADLINE


def test_generate_pillar_headlines_extra_or_missing_keys_in_model_response_are_handled():
    # Model returns only 2 of 3 requested keys — the missing one falls
    # back cleanly rather than crashing on a KeyError.
    with patch("generation.pillar_headlines._call_once") as mock_call:
        mock_call.return_value = {"visibility": "You hold 35% share of all brand mentions."}
        result = generate_pillar_headlines(_FULL_DIMENSIONS_RAW, _VIS_METRICS, "key")

    assert result["visibility"]["source"] == SOURCE_GENERATED
    assert result["accessibility"]["source"] == SOURCE_DEFAULT
    assert result["true_value"]["source"] == SOURCE_DEFAULT
