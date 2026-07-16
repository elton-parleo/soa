"""
Tests for the pass-2 extraction layer: coding_response_v2 dataclasses and
prompts_v2's schema/prompt builders. Pass 1 (parser/coding_response.py,
parser/prompts.py, parser/coding_client.py) is untouched by this session's
corrections and is covered by its own existing tests.
"""
from parser.coding_response_v2 import CitationCoding, Pass2CodingResult, PriceObservationCoding
from parser.prompts_v2 import build_pass2_schema, build_pass2_system_prompt


def test_price_observation_defaults():
    obs = PriceObservationCoding(comparison_code="M001")
    assert obs.stated_price is None
    assert obs.merchant_name is None
    assert obs.claimed_terms == []


def test_price_observation_populated():
    obs = PriceObservationCoding(
        comparison_code="M001", stated_price=44.97, merchant_name="Walmart",
        evidence="Walmart showed $44.97",
    )
    assert obs.stated_price == 44.97
    assert obs.merchant_name == "Walmart"


def test_citation_coding_context_defaults_to_none():
    c = CitationCoding(url="https://www.walmart.com/ip/123", domain="walmart.com")
    assert c.context is None


def test_pass2_result_defaults_empty():
    result = Pass2CodingResult(run_id=1, price_observations=[], citations=[], coding_latency_ms=100)
    assert result.price_observations == []
    assert result.citations == []


def test_pass2_schema_shape():
    schema = build_pass2_schema()
    assert set(schema["properties"].keys()) == {"price_observations", "citations"}
    obs_props = schema["properties"]["price_observations"]["items"]["properties"]
    assert "comparison_code" in obs_props
    assert "merchant_name" in obs_props
    # No mention-level fields — pass 2 must not ask for these.
    for forbidden in ["mentioned", "position", "strength", "deal_cited", "deal_types", "confidence"]:
        assert forbidden not in obs_props


def test_pass2_system_prompt_lists_only_mentioned_entities():
    prompt = build_pass2_system_prompt([
        {"comparison_code": "M001", "name": "Pampers"},
        {"comparison_code": "M003", "name": "Huggies"},
    ])
    assert "M001: Pampers" in prompt
    assert "M003: Huggies" in prompt


def test_pass2_system_prompt_handles_no_mentioned_entities():
    # A response can cite real third-party sources while mentioning none
    # of the tracked entities (e.g. a pure medical/dermatology-sourced
    # answer) — citation extraction must still be requested.
    prompt = build_pass2_system_prompt([])
    assert "price_observations must be empty" in prompt
    assert "Still extract citations" in prompt


def test_pass2_system_prompt_instructs_retailer_over_brand():
    prompt = build_pass2_system_prompt([{"comparison_code": "M001", "name": "Pampers"}])
    assert "never the brand itself" in prompt or "never the brand" in prompt.lower()
    assert "Target" in prompt  # the worked example from the actual failure case
