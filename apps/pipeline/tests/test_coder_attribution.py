"""
Tests for entity attribution in pass-1 coding: the name-bearing keys the
model codes under (prompts.entity_key), the key → comparison code mapping
in coding_client.py, and the text-grounded check in attribution_check.py.
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from parser.attribution_check import (
    CODED_BUT_ABSENT,
    EVIDENCE_NAMES_OTHER,
    PRESENT_BUT_UNCODED,
    check_attribution,
    clear_absent_mentions,
    entity_terms,
    resolve_position_ties,
    retry_worthy,
)
from parser.coding_client import CodingClient
from parser.coding_response import MerchantCoding
from parser.prompts import build_coding_schema, build_system_prompt, entity_key


def _ce(code, name, slug=None, role="competitor", aliases=None, display_name=None):
    return SimpleNamespace(
        comparison_code=code,
        display_name=display_name,
        role=role,
        entity=SimpleNamespace(name=name, slug=slug or name.lower(), aliases=aliases),
    )


ENTITIES = [
    _ce("M001", "Petco", role="primary"),
    _ce("M002", "PetSmart"),
    _ce("M003", "Chewy"),
]
TERMS = {ce.comparison_code: entity_terms(ce) for ce in ENTITIES}


def _mc(code, mentioned, evidence=None, position=None):
    return MerchantCoding(
        merchant_id=code, mentioned=mentioned,
        position=position if mentioned else None,
        strength="Positive" if mentioned else None,
        deal_cited=False, deal_types=[], member_value_cited=mentioned,
        evidence=evidence, confidence=0.9,
    )


# ── keys ─────────────────────────────────────────────────────────────────────

def test_entity_key_carries_code_and_name():
    assert entity_key(_ce("M001", "Petco")) == "M001_petco"
    assert entity_key(_ce("M004", "Hill's Science Diet")) == "M004_hill_s_science_diet"
    assert entity_key(_ce("M002", "X", display_name="Pet Smart")) == "M002_pet_smart"


def test_prompt_lists_entities_under_their_keys():
    prompt = build_system_prompt(ENTITIES, "retailer")
    assert "M001_petco: Petco — PRIMARY ENTITY" in prompt
    assert "M003_chewy: Chewy" in prompt
    assert "ENTITY KEYS" in prompt


def test_schema_is_keyed_by_entity_key():
    keys = [entity_key(ce) for ce in ENTITIES]
    schema = build_coding_schema(keys)
    assert schema["properties"]["merchants"]["required"] == keys


def _coding_payload(merchants):
    empty = {
        "stated_price": None, "claimed_net_price": None,
        "claimed_discount_value": None, "claimed_discount_pct": None,
        "claimed_terms": [], "member_price_claimed": None,
        "subscription_offer_claimed": None,
    }
    return {
        "merchants": {
            key: {
                "mentioned": m, "position": 1 if m else None,
                "strength": "Positive" if m else None, "deal_cited": False,
                "deal_types": [], "member_value_cited": False,
                "evidence": key if m else None, "confidence": 0.9, **empty,
            }
            for key, m in merchants.items()
        },
        "other_merchants": [], "needs_review": False, "coder_notes": "",
    }


def test_client_maps_keys_back_to_comparison_codes():
    payload = _coding_payload({"M001_petco": True, "M002_petsmart": False, "M003_chewy": False})
    client = CodingClient()
    client._client = MagicMock()
    client._client.responses.create = AsyncMock(return_value=SimpleNamespace(
        output_text=json.dumps(payload),
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    ))
    run = SimpleNamespace(id=1, search_triggered=True, platform="chatgpt", raw_response="r")

    coding = asyncio.run(client.code_response(run, "q", ENTITIES, "retailer"))

    assert set(coding.merchants) == {"M001", "M002", "M003"}
    assert coding.merchants["M001"].merchant_id == "M001"
    assert coding.merchants["M001"].mentioned is True
    sent_schema = client._client.responses.create.call_args.kwargs["text"]["format"]["schema"]
    assert sent_schema["properties"]["merchants"]["required"] == [
        "M001_petco", "M002_petsmart", "M003_chewy",
    ]


# ── attribution check ────────────────────────────────────────────────────────

def test_swapped_keys_are_caught():
    """PET_039 in cycle 20260929-214118-petco-full: Chewy's recommendation
    was coded under Petco and Petco's under PetSmart."""
    raw = "Chewy is usually the better default. Choose Petco if you need it today."
    merchants = {
        "M001": _mc("M001", True, "My recommendation: Choose Chewy for most dog toys"),
        "M002": _mc("M002", True, "Choose Petco if you need something today"),
        "M003": _mc("M003", False),
    }
    kinds = {(i.code, i.kind) for i in check_attribution(merchants, raw, TERMS)}
    assert kinds == {
        ("M001", EVIDENCE_NAMES_OTHER),
        ("M002", CODED_BUT_ABSENT),
        ("M003", PRESENT_BUT_UNCODED),
    }


def test_correct_coding_has_no_issues():
    raw = "Both Chewy and Petco are good; PetSmart has stores nearby."
    merchants = {
        "M001": _mc("M001", True, "Both Chewy and Petco are good"),
        "M002": _mc("M002", True, "PetSmart has stores nearby"),
        "M003": _mc("M003", True, "Both Chewy and Petco are good"),
    }
    assert check_attribution(merchants, raw, TERMS) == []


def test_common_word_is_not_a_mention():
    raw = "Pick chewy treats your dog likes; Petco carries plenty."
    merchants = {
        "M001": _mc("M001", True, "Petco carries plenty"),
        "M002": _mc("M002", False),
        "M003": _mc("M003", False),
    }
    assert check_attribution(merchants, raw, TERMS) == []


def test_name_inside_another_brand_is_not_a_mention():
    raw = "Try Stella & Chewy's freeze-dried food or Soft & Chewy Treats."
    merchants = {"M003": _mc("M003", False)}
    assert check_attribution(merchants, raw, TERMS) == []


def test_domain_counts_as_present():
    raw = "Prices from [chewy.com](https://www.chewy.com/x)."
    merchants = {"M003": _mc("M003", False)}
    assert [i.kind for i in check_attribution(merchants, raw, TERMS)] == [PRESENT_BUT_UNCODED]


def test_spacing_and_case_variants_are_not_absent():
    raw = "Pet Smart and WAL-MART both stock it."
    terms = {"M002": TERMS["M002"], "M004": entity_terms(_ce("M004", "Walmart"))}
    merchants = {
        "M002": _mc("M002", True, "Pet Smart stocks it"),
        "M004": _mc("M004", True, "WAL-MART stocks it"),
    }
    assert check_attribution(merchants, raw, terms) == []


def test_clear_absent_mentions_resets_the_coding():
    merchants = {"M002": _mc("M002", True, "Choose Petco", position=2)}
    merchants["M002"].deal_types = ["discount_pct"]
    merchants["M002"].stated_price = 10.0
    issues = check_attribution(merchants, "Choose Petco today.", TERMS)

    assert retry_worthy(issues)
    assert clear_absent_mentions(merchants, issues) == 1
    mc = merchants["M002"]
    assert (mc.mentioned, mc.position, mc.strength, mc.evidence) == (False, None, None, None)
    assert mc.deal_types == [] and mc.stated_price is None and not mc.member_value_cited


def test_present_but_uncoded_alone_is_not_retry_worthy():
    merchants = {"M003": _mc("M003", False)}
    issues = check_attribution(merchants, "Chewy has it.", TERMS)
    assert issues and not retry_worthy(issues)


# ── position ties ────────────────────────────────────────────────────────────

def test_tied_positions_follow_text_order():
    raw = "Chewy, PetSmart and Petco all carry it."
    merchants = {
        "M001": _mc("M001", True, position=1),
        "M002": _mc("M002", True, position=2),
        "M003": _mc("M003", True, position=1),
    }
    assert resolve_position_ties(merchants, raw, TERMS) is True
    assert {c: m.position for c, m in merchants.items()} == {"M003": 1, "M001": 2, "M002": 3}


def test_untied_positions_are_left_alone():
    merchants = {
        "M001": _mc("M001", True, position=1),
        "M002": _mc("M002", True, position=4),
        "M003": _mc("M003", False),
    }
    assert resolve_position_ties(merchants, "Petco then PetSmart.", TERMS) is False
    assert (merchants["M001"].position, merchants["M002"].position) == (1, 4)


def test_tie_break_only_moves_what_it_must():
    raw = "PetSmart or Petco; later Chewy."
    merchants = {
        "M001": _mc("M001", True, position=2),
        "M002": _mc("M002", True, position=2),
        "M003": _mc("M003", True, position=5),
    }
    resolve_position_ties(merchants, raw, TERMS)
    assert {c: m.position for c, m in merchants.items()} == {"M002": 2, "M001": 3, "M003": 5}
