"""
DealEngineClient — async HTTP client for the Deal Engine service.

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


class DealEngineClient:

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        self.base_url = (base_url or config.DEAL_ENGINE_BASE_URL).rstrip("/")
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
