"""
Tests for clients/deal_engine_client.py using a mocked httpx.AsyncClient.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clients.deal_engine_client import DealEngineClient


def _mock_response(json_data, status_ok=True):
    resp = MagicMock()
    resp.json.return_value = json_data
    if status_ok:
        resp.raise_for_status = MagicMock()
    else:
        resp.raise_for_status = MagicMock(side_effect=Exception("HTTP error"))
    return resp


def _mock_client(response=None, raise_exc=None):
    instance = AsyncMock()
    if raise_exc is not None:
        instance.request = AsyncMock(side_effect=raise_exc)
    else:
        instance.request = AsyncMock(return_value=response)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=instance)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def test_true_cost_success():
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=0)
    payload = {
        "true_cost": 71.2,
        "total_savings": 17.8,
        "total_points_earned": 250,
        "applied_deals": [{"deal_type": "member_price", "terms": ["Rouge members only"]}],
        "available_deals": [],
        "confidence": 0.9,
        "user_tier_name": "Rouge",
    }
    cm = _mock_client(response=_mock_response(payload))

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm):
        result = asyncio.run(client.true_cost(merchant_slug="sephora", product_price=89.0))

    assert result.available is True
    assert result.true_cost == 71.2
    assert result.total_savings == 17.8
    assert result.user_tier_name == "Rouge"
    assert result.applied_deals[0]["deal_type"] == "member_price"


def test_true_cost_unreachable_returns_unavailable_never_raises():
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=0)
    cm = _mock_client(raise_exc=ConnectionError("connection refused"))

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm):
        result = asyncio.run(client.true_cost(merchant_slug="sephora", product_price=89.0))

    assert result.available is False
    assert result.error is not None
    assert result.true_cost is None


def test_true_cost_retries_then_succeeds():
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=2)

    instance = AsyncMock()
    success_resp = _mock_response({"true_cost": 50.0})
    instance.request = AsyncMock(side_effect=[ConnectionError("boom"), success_resp])

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=instance)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm):
        with patch("clients.deal_engine_client.asyncio.sleep", new=AsyncMock()):
            result = asyncio.run(client.true_cost(merchant_slug="sephora", product_price=89.0))

    assert result.available is True
    assert result.true_cost == 50.0


def test_no_base_url_configured_returns_unavailable():
    client = DealEngineClient(base_url="", max_retries=0)
    result = asyncio.run(client.true_cost(merchant_slug="sephora", product_price=89.0))
    assert result.available is False
    assert "not configured" in result.error


def test_active_deals_success():
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=0)
    cm = _mock_client(response=_mock_response({"deals": [{"id": 1}]}))

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm):
        result = asyncio.run(client.active_deals(merchant_slug="sephora"))

    assert result.available is True
    assert result.deals == [{"id": 1}]
