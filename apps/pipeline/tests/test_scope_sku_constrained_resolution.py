"""
Tests for constrained-resolution (SKU-scope) support in prompts.py and
coding_client.py: the prompt/schema are unchanged when there are no scope
SKUs, and scope_sku_codings parse correctly when they're present.
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from parser.coding_client import CodingClient
from parser.coding_response import ScopeSkuCoding
from parser.prompts import SYSTEM_PROMPT, build_coding_schema, build_system_prompt


def _fake_cycle_entity(code="M001", name="Sephora", role="primary"):
    ce = MagicMock()
    ce.comparison_code = code
    ce.display_name = None
    ce.entity.name = name
    ce.entity.aliases = None
    ce.role = role
    return ce


# ─────────────────────────────────────────────────────────────────────────────
# prompts.py — byte-for-byte unchanged when scope_skus is absent
# ─────────────────────────────────────────────────────────────────────────────

def test_build_system_prompt_unchanged_without_scope_skus():
    ce = _fake_cycle_entity()
    no_arg = build_system_prompt([ce], "retailer")
    explicit_none = build_system_prompt([ce], "retailer", scope_skus=None)
    explicit_empty = build_system_prompt([ce], "retailer", scope_skus=[])

    assert no_arg == explicit_none == explicit_empty
    assert "SKU-LEVEL SCOPE" not in no_arg


def test_build_system_prompt_appends_scope_section_when_present():
    ce = _fake_cycle_entity()
    prompt = build_system_prompt([ce], "retailer", scope_skus=[
        {"code": "SKU001", "display_name": "Soft Pinch Lip Oil",
         "brand": "Rare Beauty", "model": None, "merchant_slug": "sephora"},
    ])
    assert "SKU-LEVEL SCOPE" in prompt
    assert "SKU001" in prompt
    assert "Soft Pinch Lip Oil" in prompt
    assert "Rare Beauty" in prompt
    assert "sephora" in prompt
    # Base prompt is a strict prefix — nothing in the existing rubric changed.
    base = build_system_prompt([ce], "retailer")
    assert prompt.startswith(base)


def test_build_coding_schema_unchanged_without_scope_sku_codes():
    no_arg = build_coding_schema(["M001"])
    explicit_none = build_coding_schema(["M001"], None)
    explicit_empty = build_coding_schema(["M001"], [])

    assert no_arg == explicit_none == explicit_empty
    assert "scope_skus" not in no_arg["properties"]
    assert "scope_sku_coding" not in no_arg["$defs"]


def test_build_coding_schema_entity_coding_has_member_value_cited():
    """Stage 16 (Part 5): member_value_cited is a required boolean on
    every entity_coding, independent of deal_cited/deal_types."""
    schema = build_coding_schema(["M001"])
    entity_def = schema["$defs"]["entity_coding"]
    assert entity_def["properties"]["member_value_cited"] == {"type": "boolean"}
    assert "member_value_cited" in entity_def["required"]


def test_system_prompt_defines_member_value_citation_rules():
    assert "MEMBER VALUE CITATION RULES" in SYSTEM_PROMPT
    assert "member_value_cited" in SYSTEM_PROMPT


def test_build_coding_schema_adds_scope_skus_property_when_present():
    schema = build_coding_schema(["M001"], ["SKU001", "SKU002"])
    assert "scope_skus" in schema["properties"]
    assert "scope_skus" in schema["required"]
    assert set(schema["properties"]["scope_skus"]["properties"]) == {"SKU001", "SKU002"}
    assert schema["properties"]["scope_skus"]["required"] == ["SKU001", "SKU002"]
    assert "scope_sku_coding" in schema["$defs"]
    sku_def = schema["$defs"]["scope_sku_coding"]
    assert set(sku_def["required"]) == {
        "surfaced", "stated_price", "claimed_terms",
        "member_price_claimed", "evidence",
    }


# ─────────────────────────────────────────────────────────────────────────────
# coding_client.py — code_response() parses scope_sku_codings
# ─────────────────────────────────────────────────────────────────────────────

def _fake_openai_response(result_dict, input_tokens=100, output_tokens=50):
    return SimpleNamespace(
        output_text=json.dumps(result_dict),
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _make_client_with_mocked_create(result_dict):
    client = CodingClient()
    client._client = MagicMock()
    client._client.responses = MagicMock()
    client._client.responses.create = AsyncMock(return_value=_fake_openai_response(result_dict))
    return client


def _base_result(scope_skus=None):
    result = {
        "merchants": {
            "M001": {
                "mentioned": True, "position": 1, "strength": "Positive",
                "deal_cited": False, "deal_types": [], "member_value_cited": False, "evidence": "ev",
                "confidence": 0.9, "stated_price": None, "claimed_net_price": None,
                "claimed_discount_value": None, "claimed_discount_pct": None,
                "claimed_terms": [], "member_price_claimed": None,
                "subscription_offer_claimed": None,
            },
        },
        "other_merchants": [],
        "needs_review": False,
        "coder_notes": "",
    }
    if scope_skus is not None:
        result["scope_skus"] = scope_skus
    return result


def test_code_response_without_scope_skus_returns_empty_codings():
    client = _make_client_with_mocked_create(_base_result())
    run = SimpleNamespace(id=1, search_triggered=False, platform="chatgpt", raw_response="resp")
    ce = _fake_cycle_entity()

    coding = asyncio.run(client.code_response(run, "query", [ce], "retailer"))

    assert coding.scope_sku_codings == []


def test_code_response_parses_surfaced_scope_sku_coding():
    scope_skus_payload = {
        "SKU001": {
            "surfaced": True,
            "stated_price": 19.80,
            "claimed_terms": ["Rouge members only"],
            "member_price_claimed": True,
            "evidence": "Soft Pinch Lip Oil is $19.80 for Rouge members",
        },
    }
    client = _make_client_with_mocked_create(_base_result(scope_skus_payload))
    run = SimpleNamespace(id=1, search_triggered=False, platform="chatgpt", raw_response="resp")
    ce = _fake_cycle_entity()

    coding = asyncio.run(client.code_response(
        run, "query", [ce], "retailer",
        scope_skus=[{
            "code": "SKU001", "display_name": "Soft Pinch Lip Oil",
            "brand": "Rare Beauty", "model": None, "merchant_slug": "sephora",
        }],
    ))

    assert len(coding.scope_sku_codings) == 1
    sku_coding = coding.scope_sku_codings[0]
    assert isinstance(sku_coding, ScopeSkuCoding)
    assert sku_coding.scope_sku_code == "SKU001"
    assert sku_coding.surfaced is True
    assert sku_coding.stated_price == 19.80
    assert sku_coding.claimed_terms == ["Rouge members only"]
    assert sku_coding.member_price_claimed is True


def test_code_response_not_surfaced_scope_sku_coding_has_null_fields():
    scope_skus_payload = {
        "SKU001": {
            "surfaced": False,
            "stated_price": None,
            "claimed_terms": [],
            "member_price_claimed": None,
            "evidence": None,
        },
    }
    client = _make_client_with_mocked_create(_base_result(scope_skus_payload))
    run = SimpleNamespace(id=1, search_triggered=False, platform="chatgpt", raw_response="resp")
    ce = _fake_cycle_entity()

    coding = asyncio.run(client.code_response(
        run, "query", [ce], "retailer",
        scope_skus=[{
            "code": "SKU001", "display_name": "Soft Pinch Lip Oil",
            "brand": "Rare Beauty", "model": None, "merchant_slug": "sephora",
        }],
    ))

    sku_coding = coding.scope_sku_codings[0]
    assert sku_coding.surfaced is False
    assert sku_coding.stated_price is None
    assert sku_coding.claimed_terms == []
