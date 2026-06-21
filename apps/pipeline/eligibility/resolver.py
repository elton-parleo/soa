"""
EligibilityResolver — Deal Engine as the eligibility oracle.

A deal is "eligible" for a (merchant, tier, category, brand) combination if
the Deal Engine's true-cost response includes it in either applied_deals
(it was applied) or available_deals (eligible but not applied, e.g. a
member price the buyer didn't ask about). Together these are the eligible
set for that combination. "Live" deals with no eligibility match for the
persona (e.g. a Rouge-only deal for a non-member persona) never appear in
either list and are therefore correctly excluded.

Results are cached per (merchant_slug, tier_name, category, brand, as_of)
so a metrics run that touches the same combination many times (once per
coded run) only calls the Deal Engine once.
"""
import datetime
import logging
from typing import Dict, List, Optional, Tuple

from clients.deal_engine_client import DealEngineClient, TrueCostResult

logger = logging.getLogger(__name__)

# Nominal price used to probe the Deal Engine for the eligible-deal set.
# Eligibility (which deals apply) does not depend on the actual product
# price for the deal types currently modeled (member_price, discount_pct,
# promo_name, loyalty_points, free_shipping, gift_with_purchase), so any
# positive placeholder works; it never appears in is_eligible()'s result.
_PROBE_PRICE = 100.0

CacheKey = Tuple[str, Optional[str], Optional[str], Optional[str], str]


class EligibilityResolver:

    def __init__(self, deal_engine_client: Optional[DealEngineClient] = None) -> None:
        self.client = deal_engine_client or DealEngineClient()
        self._cache: Dict[CacheKey, TrueCostResult] = {}

    def _cache_key(
        self,
        merchant_slug: str,
        tier_name: Optional[str],
        category: Optional[str],
        brand: Optional[str],
        as_of: Optional[datetime.date],
    ) -> CacheKey:
        as_of_str = (as_of or datetime.date.today()).isoformat()
        return (merchant_slug, tier_name, category, brand, as_of_str)

    async def _eligible_set(
        self,
        merchant_slug: str,
        category: Optional[str] = None,
        brand: Optional[str] = None,
        tier_name: Optional[str] = None,
        as_of: Optional[datetime.date] = None,
    ) -> TrueCostResult:
        """
        Returns the cached (or freshly fetched) TrueCostResult for this
        combination. tier_name=None is treated by the Deal Engine as the
        base/non-member tier — only non-member-gated live deals are eligible.
        """
        key = self._cache_key(merchant_slug, tier_name, category, brand, as_of)
        if key in self._cache:
            return self._cache[key]

        result = await self.client.true_cost(
            merchant_slug=merchant_slug,
            product_price=_PROBE_PRICE,
            product_category=category,
            brand=brand,
            user_tier_name=tier_name,
        )
        self._cache[key] = result
        return result

    async def is_eligible(
        self,
        merchant_slug: str,
        category: Optional[str] = None,
        brand: Optional[str] = None,
        tier_name: Optional[str] = None,
        deal_id: Optional[str] = None,
        as_of: Optional[datetime.date] = None,
    ) -> bool:
        """
        True if there is at least one live, eligible deal for this
        combination (deal_id=None), or if the specific deal_id is in the
        eligible set. False (never raises) if the Deal Engine is
        unreachable or returns no eligible deals.
        """
        result = await self._eligible_set(merchant_slug, category, brand, tier_name, as_of)
        if not result.available:
            return False

        eligible = result.applied_deals + result.available_deals
        if deal_id is None:
            return len(eligible) > 0
        return any(self._deal_id(d) == deal_id for d in eligible)

    async def eligible_deal_ids(
        self,
        merchant_slug: str,
        category: Optional[str] = None,
        brand: Optional[str] = None,
        tier_name: Optional[str] = None,
        as_of: Optional[datetime.date] = None,
    ) -> List[str]:
        result = await self._eligible_set(merchant_slug, category, brand, tier_name, as_of)
        if not result.available:
            return []
        eligible = result.applied_deals + result.available_deals
        return [self._deal_id(d) for d in eligible if self._deal_id(d) is not None]

    @staticmethod
    def _deal_id(deal: dict) -> Optional[str]:
        deal_id = deal.get("id") or deal.get("deal_id")
        return str(deal_id) if deal_id is not None else None

    def clear_cache(self) -> None:
        self._cache.clear()
