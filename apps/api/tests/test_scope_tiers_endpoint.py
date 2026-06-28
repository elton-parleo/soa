"""
Tests for GET /api/scope/tiers (apps/api/app/routers/scope.py::get_scope_tiers)
— proxies the Deal Engine's GET /api/merchants/programs to list every
loyalty tier name, always prefixed with the non-member baseline option.

Calls the route function directly, mocking DealEngineClient.merchant_programs
so no real network call is made.
"""
from unittest.mock import AsyncMock, patch

import app.routers.scope as scope_router
from clients.deal_engine_client import MerchantProgramsResult

CURRENT_USER = {"organization_id": 1, "user_id": "u1"}

SAMPLE_MERCHANTS = [
    {
        "slug": "sephora",
        "programs": [
            {"tiers": [{"name": "Insider"}, {"name": "VIB"}, {"name": "Rouge"}]}
        ],
    },
    {
        "slug": "target",
        "programs": [{"tiers": [{"name": "Target Circle"}]}],
    },
]


def test_tiers_always_includes_baseline_first():
    with patch.object(
        scope_router.DealEngineClient, "merchant_programs",
        new=AsyncMock(return_value=MerchantProgramsResult(available=True, merchants=[])),
    ):
        result = scope_router.get_scope_tiers(current_user=CURRENT_USER)

    assert result.tiers[0].value is None
    assert result.tiers[0].label == "Non-member (baseline)"
    assert len(result.tiers) == 1


def test_tiers_deduped_and_sorted_across_merchants():
    with patch.object(
        scope_router.DealEngineClient, "merchant_programs",
        new=AsyncMock(return_value=MerchantProgramsResult(available=True, merchants=SAMPLE_MERCHANTS)),
    ):
        result = scope_router.get_scope_tiers(current_user=CURRENT_USER)

    values = [t.value for t in result.tiers]
    assert values[0] is None  # baseline always first
    assert values[1:] == sorted(["Insider", "VIB", "Rouge", "Target Circle"])


def test_tiers_raises_503_when_deal_engine_unavailable():
    from fastapi import HTTPException
    import pytest

    with patch.object(
        scope_router.DealEngineClient, "merchant_programs",
        new=AsyncMock(return_value=MerchantProgramsResult(available=False, error="connection refused")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            scope_router.get_scope_tiers(current_user=CURRENT_USER)
    assert exc_info.value.status_code == 503
