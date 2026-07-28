"""
Tests for the new Rung-0 extraction fields on MerchantCoding and the
tolerant .get()-based parsing in coding_client.py.
"""
from parser.coding_response import MerchantCoding


def test_merchant_coding_defaults_when_new_fields_absent():
    mc = MerchantCoding(
        merchant_id="M001",
        mentioned=True,
        position=1,
        strength="Positive",
        deal_cited=False,
        deal_types=[],
        member_value_cited=False,
        evidence="some evidence",
        confidence=0.9,
    )
    assert mc.stated_price is None
    assert mc.claimed_net_price is None
    assert mc.claimed_discount_value is None
    assert mc.claimed_discount_pct is None
    assert mc.claimed_terms == []
    assert mc.member_price_claimed is None
    assert mc.subscription_offer_claimed is None


def test_merchant_coding_populates_new_fields_when_present():
    mc = MerchantCoding(
        merchant_id="M001",
        mentioned=True,
        position=1,
        strength="Positive",
        deal_cited=True,
        deal_types=["member_price"],
        member_value_cited=True,
        evidence="Beauty Insider price is $74",
        confidence=0.95,
        stated_price=89.0,
        claimed_net_price=74.0,
        claimed_discount_value=15.0,
        claimed_discount_pct=None,
        claimed_terms=["Rouge members only"],
        member_price_claimed=True,
        subscription_offer_claimed=False,
    )
    assert mc.stated_price == 89.0
    assert mc.claimed_net_price == 74.0
    assert mc.claimed_discount_value == 15.0
    assert mc.claimed_terms == ["Rouge members only"]
    assert mc.member_price_claimed is True
    assert mc.subscription_offer_claimed is False


def _parse_legacy_payload_like_coding_client(data: dict) -> MerchantCoding:
    """Mirrors the .get()-based parsing in coding_client.py code_response()."""
    return MerchantCoding(
        merchant_id="M001",
        mentioned=data["mentioned"],
        position=data["position"],
        strength=data["strength"],
        deal_cited=data["deal_cited"],
        deal_types=data["deal_types"] or [],
        member_value_cited=data["member_value_cited"],
        evidence=data["evidence"],
        confidence=data["confidence"],
        stated_price=data.get("stated_price"),
        claimed_net_price=data.get("claimed_net_price"),
        claimed_discount_value=data.get("claimed_discount_value"),
        claimed_discount_pct=data.get("claimed_discount_pct"),
        claimed_terms=data.get("claimed_terms") or [],
        member_price_claimed=data.get("member_price_claimed"),
        subscription_offer_claimed=data.get("subscription_offer_claimed"),
    )


def test_parsing_tolerates_legacy_payload_missing_new_keys():
    legacy_payload = {
        "mentioned": True,
        "position": 1,
        "strength": "Neutral",
        "deal_cited": False,
        "deal_types": [],
        "member_value_cited": False,
        "evidence": "You can find this at Sephora.",
        "confidence": 0.8,
    }
    mc = _parse_legacy_payload_like_coding_client(legacy_payload)
    assert mc.stated_price is None
    assert mc.claimed_terms == []


def test_parsing_extracts_new_fields_when_present():
    payload = {
        "mentioned": True,
        "position": 2,
        "strength": "Positive",
        "deal_cited": True,
        "deal_types": ["discount_pct"],
        "member_value_cited": False,
        "evidence": "20% off today, final price $71.20",
        "confidence": 0.88,
        "stated_price": 89.0,
        "claimed_net_price": 71.2,
        "claimed_discount_value": None,
        "claimed_discount_pct": 20.0,
        "claimed_terms": ["today only"],
        "member_price_claimed": False,
        "subscription_offer_claimed": None,
    }
    mc = _parse_legacy_payload_like_coding_client(payload)
    assert mc.claimed_net_price == 71.2
    assert mc.claimed_discount_pct == 20.0
    assert mc.claimed_terms == ["today only"]
    assert mc.member_price_claimed is False
