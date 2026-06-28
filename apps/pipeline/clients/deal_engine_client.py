"""
DealEngineClient — async HTTP client for the Deal Engine service.

Canonical copy lives here (apps/pipeline/clients/). Also mirrored to
apps/api/clients/ for Vercel deployment, the same way soa_shared/ is
mirrored (see apps/api/requirements.txt) — edit here first, then re-copy.

Used by scoring/incentive_scorer.py (and reusable by later workstreams) to
fetch ground-truth true-cost data for a merchant/product so an agent's
stated incentive can be checked against it.

Never raises on network/HTTP failure — callers get back a typed result with
available=False so a Deal-Engine outage degrades the pipeline (rows written
with status=ground_truth_unavailable) instead of aborting it.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

import soa_shared.config as config

logger = logging.getLogger(__name__)


@dataclass
class TrueCostResult:
    available: bool
    true_cost: Optional[float] = None
    total_savings: Optional[float] = None
    total_points_earned: Optional[float] = None
    applied_deals: List[Dict[str, Any]] = field(default_factory=list)
    available_deals: List[Dict[str, Any]] = field(default_factory=list)
    confidence: Optional[float] = None
    user_tier_name: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ActiveDealsResult:
    available: bool
    deals: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class CatalogSearchResult:
    available: bool
    listings: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ResolveListingResult:
    available: bool
    listing: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class MerchantProgramsResult:
    available: bool
    merchants: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ListingTrueCostResult:
    available: bool
    true_cost: Optional[float] = None
    listed_price: Optional[float] = None
    currency: Optional[str] = None
    total_savings: Optional[float] = None
    total_points_earned: Optional[float] = None
    applied_deals: List[Dict[str, Any]] = field(default_factory=list)
    available_deals: List[Dict[str, Any]] = field(default_factory=list)
    confidence: Optional[float] = None
    user_tier_name: Optional[str] = None
    price_was_refreshed: bool = False
    price_refreshed_at: Optional[str] = None
    error: Optional[str] = None


class DealEngineClient:

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        self.base_url = (
            config.DEAL_ENGINE_BASE_URL if base_url is None else base_url
        ).rstrip("/")
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else config.SOA_DEAL_ENGINE_TIMEOUT_SECONDS
        )
        self.max_retries = (
            max_retries if max_retries is not None else config.SOA_DEAL_ENGINE_MAX_RETRIES
        )

    async def true_cost(
        self,
        merchant_slug: str,
        product_price: float,
        product_category: Optional[str] = None,
        brand: Optional[str] = None,
        user_tier_name: Optional[str] = None,
        user_points_balance: Optional[float] = None,
    ) -> TrueCostResult:
        if not self.base_url:
            return TrueCostResult(available=False, error="DEAL_ENGINE_BASE_URL not configured")

        payload = {
            "merchant_slug": merchant_slug,
            "product_price": product_price,
            "product_category": product_category,
            "brand": brand,
            "user_tier_name": user_tier_name,
            "user_points_balance": user_points_balance,
        }

        data, error = await self._request(
            "POST", "/api/deals/true-cost", json=payload
        )
        if data is None:
            return TrueCostResult(available=False, error=error)

        return TrueCostResult(
            available=True,
            true_cost=data.get("true_cost"),
            total_savings=data.get("total_savings"),
            total_points_earned=data.get("total_points_earned"),
            applied_deals=data.get("applied_deals") or [],
            available_deals=data.get("available_deals") or [],
            confidence=data.get("confidence"),
            user_tier_name=data.get("user_tier_name"),
        )

    async def active_deals(self, merchant_slug: Optional[str] = None) -> ActiveDealsResult:
        if not self.base_url:
            return ActiveDealsResult(available=False, error="DEAL_ENGINE_BASE_URL not configured")

        params = {"merchant_slug": merchant_slug} if merchant_slug else None
        data, error = await self._request("GET", "/api/deals/active", params=params)
        if data is None:
            return ActiveDealsResult(available=False, error=error)

        deals = data.get("deals", data) if isinstance(data, dict) else data
        return ActiveDealsResult(available=True, deals=deals or [])

    async def search_catalog(
        self,
        q: Optional[str] = None,
        brand: Optional[str] = None,
        category: Optional[str] = None,
        merchant_slug: Optional[str] = None,
        is_active: Optional[bool] = None,
        skip: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> CatalogSearchResult:
        """
        GET /api/catalog/listings — browse the supply app's measurable
        catalog. Used by the scope-authoring API so the frontend can search
        for a SKU to add to scope.
        """
        if not self.base_url:
            return CatalogSearchResult(available=False, error="DEAL_ENGINE_BASE_URL not configured")

        params = {
            "q": q,
            "brand": brand,
            "category": category,
            "merchant_slug": merchant_slug,
            "is_active": is_active,
            "skip": skip,
            "limit": limit,
        }
        params = {k: v for k, v in params.items() if v is not None}

        data, error = await self._request("GET", "/api/catalog/listings", params=params)
        if data is None:
            return CatalogSearchResult(available=False, error=error)

        listings = data.get("listings", data) if isinstance(data, dict) else data
        return CatalogSearchResult(available=True, listings=listings or [])

    async def resolve_listing(
        self,
        product_url: str,
        user_tier_name: Optional[str] = None,
    ) -> ResolveListingResult:
        """
        POST /api/catalog/listings/resolve — registers a measurable SKU
        from a product URL (crawls, extracts, and persists a catalog
        listing on the Deal Engine side). Used by the "paste product URL"
        scope-authoring path.
        """
        if not self.base_url:
            return ResolveListingResult(available=False, error="DEAL_ENGINE_BASE_URL not configured")

        payload = {"product_url": product_url, "user_tier_name": user_tier_name}

        data, error = await self._request(
            "POST", "/api/catalog/listings/resolve", json=payload
        )
        if data is None:
            return ResolveListingResult(available=False, error=error)

        return ResolveListingResult(available=True, listing=data)

    async def merchant_programs(self) -> MerchantProgramsResult:
        """
        GET /api/merchants/programs — all merchants with their loyalty
        programs and tiers. Used to populate the truecost-sweep wizard's
        tier multi-select (each tier.name is a valid user_tier_name).
        """
        if not self.base_url:
            return MerchantProgramsResult(available=False, error="DEAL_ENGINE_BASE_URL not configured")

        data, error = await self._request("GET", "/api/merchants/programs")
        if data is None:
            return MerchantProgramsResult(available=False, error=error)

        return MerchantProgramsResult(available=True, merchants=data or [])

    async def listing_true_cost(
        self,
        listing_id: int,
        user_tier_name: Optional[str] = None,
        refresh_price: bool = False,
    ) -> ListingTrueCostResult:
        """
        GET /api/catalog/listings/{id}/true-cost — ground truth for a known
        listing. Used by the SKU-level scorer instead of true_cost() once a
        scope SKU has a dealengine_listing_id.

        refresh_price=True asks the Deal Engine to re-scrape the listing's
        current price before computing true cost (used once per SKU by the
        truecost sweep executor). Default False keeps every existing caller
        unchanged.
        """
        if not self.base_url:
            return ListingTrueCostResult(available=False, error="DEAL_ENGINE_BASE_URL not configured")

        params: Dict[str, Any] = {}
        if user_tier_name:
            params["user_tier_name"] = user_tier_name
        if refresh_price:
            params["refresh_price"] = refresh_price

        data, error = await self._request(
            "GET", f"/api/catalog/listings/{listing_id}/true-cost", params=params or None
        )
        if data is None:
            return ListingTrueCostResult(available=False, error=error)

        true_cost_result = data.get("true_cost_result") or {}
        return ListingTrueCostResult(
            available=True,
            true_cost=true_cost_result.get("true_cost"),
            listed_price=data.get("listed_price"),
            currency=data.get("currency"),
            total_savings=true_cost_result.get("total_savings"),
            total_points_earned=true_cost_result.get("total_points_earned"),
            applied_deals=true_cost_result.get("applied_deals") or [],
            available_deals=true_cost_result.get("available_deals") or [],
            confidence=true_cost_result.get("confidence"),
            user_tier_name=true_cost_result.get("user_tier_name"),
            price_was_refreshed=data.get("price_was_refreshed") or False,
            price_refreshed_at=data.get("price_refreshed_at"),
        )

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> tuple[Optional[Any], Optional[str]]:
        url = f"{self.base_url}{path}"
        last_error: Optional[str] = None

        for attempt in range(1, self.max_retries + 2):  # 1 initial try + retries
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.request(method, url, json=json, params=params)
                    response.raise_for_status()
                    return response.json(), None
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "[deal_engine] %s %s attempt=%d/%d failed: %s",
                    method, url, attempt, self.max_retries + 1, exc,
                )
                if attempt <= self.max_retries:
                    await asyncio.sleep(min(2 ** (attempt - 1), 5))

        return None, last_error
