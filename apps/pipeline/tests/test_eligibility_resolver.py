"""
Tests for eligibility/resolver.py — mocked DealEngineClient, including
member vs non-member persona behavior and caching.
"""
import asyncio

from clients.deal_engine_client import TrueCostResult
from eligibility.resolver import EligibilityResolver


class FakeClient:
    def __init__(self, result_by_tier=None, default_result=None):
        self.result_by_tier = result_by_tier or {}
        self.default_result = default_result
        self.calls = []

    async def true_cost(self, merchant_slug, product_price, product_category=None,
                         brand=None, user_tier_name=None, user_points_balance=None):
        self.calls.append({
            "merchant_slug": merchant_slug,
            "product_category": product_category,
            "brand": brand,
            "user_tier_name": user_tier_name,
        })
        if user_tier_name in self.result_by_tier:
            return self.result_by_tier[user_tier_name]
        return self.default_result or TrueCostResult(available=True, applied_deals=[], available_deals=[])


def test_member_tier_sees_member_gated_deal_as_eligible():
    member_result = TrueCostResult(
        available=True,
        applied_deals=[{"id": "d1", "deal_type": "member_price"}],
        available_deals=[],
    )
    client = FakeClient(result_by_tier={"Rouge": member_result})
    resolver = EligibilityResolver(deal_engine_client=client)

    eligible = asyncio.run(resolver.is_eligible(
        merchant_slug="sephora", category="Skincare", tier_name="Rouge",
    ))
    assert eligible is True


def test_non_member_does_not_see_member_gated_deal():
    # Base/non-member tier (tier_name=None) gets no eligible deals because
    # the member-gated deal never appears in applied/available for them.
    client = FakeClient(default_result=TrueCostResult(available=True, applied_deals=[], available_deals=[]))
    resolver = EligibilityResolver(deal_engine_client=client)

    eligible = asyncio.run(resolver.is_eligible(
        merchant_slug="sephora", category="Skincare", tier_name=None,
    ))
    assert eligible is False


def test_non_member_eligible_for_non_member_gated_live_deal():
    client = FakeClient(default_result=TrueCostResult(
        available=True,
        applied_deals=[{"id": "d2", "deal_type": "discount_pct"}],
        available_deals=[],
    ))
    resolver = EligibilityResolver(deal_engine_client=client)

    eligible = asyncio.run(resolver.is_eligible(
        merchant_slug="sephora", category="Skincare", tier_name=None,
    ))
    assert eligible is True


def test_specific_deal_id_lookup():
    client = FakeClient(default_result=TrueCostResult(
        available=True,
        applied_deals=[{"id": "d1"}],
        available_deals=[{"id": "d2"}],
    ))
    resolver = EligibilityResolver(deal_engine_client=client)

    assert asyncio.run(resolver.is_eligible(
        merchant_slug="sephora", deal_id="d2",
    )) is True
    assert asyncio.run(resolver.is_eligible(
        merchant_slug="sephora", deal_id="d99",
    )) is False


def test_eligible_deal_ids_returns_all_ids():
    client = FakeClient(default_result=TrueCostResult(
        available=True,
        applied_deals=[{"id": "d1"}],
        available_deals=[{"deal_id": "d2"}],
    ))
    resolver = EligibilityResolver(deal_engine_client=client)

    ids = asyncio.run(resolver.eligible_deal_ids(merchant_slug="sephora"))
    assert set(ids) == {"d1", "d2"}


def test_unavailable_deal_engine_returns_not_eligible():
    client = FakeClient(default_result=TrueCostResult(available=False, error="timeout"))
    resolver = EligibilityResolver(deal_engine_client=client)

    eligible = asyncio.run(resolver.is_eligible(merchant_slug="sephora"))
    assert eligible is False


def test_result_is_cached_per_combination():
    client = FakeClient(default_result=TrueCostResult(available=True, applied_deals=[{"id": "d1"}]))
    resolver = EligibilityResolver(deal_engine_client=client)

    asyncio.run(resolver.is_eligible(merchant_slug="sephora", category="Skincare", tier_name="Rouge"))
    asyncio.run(resolver.is_eligible(merchant_slug="sephora", category="Skincare", tier_name="Rouge"))
    asyncio.run(resolver.is_eligible(merchant_slug="sephora", category="Skincare", tier_name="Rouge"))

    assert len(client.calls) == 1


def test_different_combinations_are_not_cached_together():
    client = FakeClient(default_result=TrueCostResult(available=True, applied_deals=[{"id": "d1"}]))
    resolver = EligibilityResolver(deal_engine_client=client)

    asyncio.run(resolver.is_eligible(merchant_slug="sephora", tier_name="Rouge"))
    asyncio.run(resolver.is_eligible(merchant_slug="sephora", tier_name=None))
    asyncio.run(resolver.is_eligible(merchant_slug="ulta", tier_name="Rouge"))

    assert len(client.calls) == 3
