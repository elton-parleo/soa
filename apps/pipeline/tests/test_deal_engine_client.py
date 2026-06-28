"""
Tests for clients/deal_engine_client.py using a mocked httpx.AsyncClient.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import soa_shared.config as config
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


def test_no_base_url_configured_returns_unavailable(monkeypatch):
    # Monkeypatch config to a real-looking, non-empty URL to prove the
    # explicit base_url="" still wins over config — regardless of whatever
    # DEAL_ENGINE_BASE_URL happens to be set to in the ambient environment.
    monkeypatch.setattr(config, "DEAL_ENGINE_BASE_URL", "http://localhost:8001")
    client = DealEngineClient(base_url="", max_retries=0)
    assert client.base_url == ""
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


# ─────────────────────────────────────────────────────────────────────────────
# SKU-scope client methods: search_catalog, resolve_listing, listing_true_cost
# ─────────────────────────────────────────────────────────────────────────────

def test_search_catalog_success():
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=0)
    listings = [{"listing_id": 1, "name": "Soft Pinch Lip Oil", "merchant_slug": "sephora"}]
    cm = _mock_client(response=_mock_response(listings))

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm) as mock_cls:
        result = asyncio.run(client.search_catalog(q="lip oil", brand="Rare Beauty"))

    assert result.available is True
    assert result.listings == listings


def test_search_catalog_passes_only_provided_params():
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=0)
    instance = AsyncMock()
    instance.request = AsyncMock(return_value=_mock_response([]))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=instance)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm):
        asyncio.run(client.search_catalog(q="serum"))

    _, kwargs = instance.request.call_args
    assert kwargs["params"] == {"q": "serum"}


def test_search_catalog_unreachable_returns_unavailable_never_raises():
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=0)
    cm = _mock_client(raise_exc=ConnectionError("connection refused"))

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm):
        result = asyncio.run(client.search_catalog(q="serum"))

    assert result.available is False
    assert result.listings == []
    assert result.error is not None


def test_resolve_listing_success():
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=0)
    listing = {
        "listing_id": 7, "catalog_product_id": 3, "merchant_slug": "sephora",
        "merchant_sku": "P123456", "brand": "Rare Beauty", "category": "lip",
        "product_url": "https://www.sephora.com/product/x", "listed_price": 22.0,
        "currency": "USD", "name": "Soft Pinch Lip Oil",
    }
    cm = _mock_client(response=_mock_response(listing))

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm):
        result = asyncio.run(client.resolve_listing("https://www.sephora.com/product/x"))

    assert result.available is True
    assert result.listing == listing


def test_resolve_listing_unreachable_returns_unavailable_never_raises():
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=0)
    cm = _mock_client(raise_exc=ConnectionError("connection refused"))

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm):
        result = asyncio.run(client.resolve_listing("https://example.com/p"))

    assert result.available is False
    assert result.listing is None
    assert result.error is not None


def test_resolve_listing_no_base_url_configured(monkeypatch):
    monkeypatch.setattr(config, "DEAL_ENGINE_BASE_URL", "http://localhost:8001")
    client = DealEngineClient(base_url="", max_retries=0)
    assert client.base_url == ""
    result = asyncio.run(client.resolve_listing("https://example.com/p"))
    assert result.available is False
    assert "not configured" in result.error


def test_empty_string_base_url_is_preserved_not_replaced_by_config():
    """Regression test for the or-vs-None bug: base_url="" is falsy, so a
    naive `base_url or config.DEAL_ENGINE_BASE_URL` silently discards an
    explicit empty string in favor of config. The constructor must honor
    "" exactly as passed."""
    client = DealEngineClient(base_url="")
    assert client.base_url == ""


def test_none_base_url_falls_back_to_config():
    """The None path (the default — real callers passing nothing) must
    still resolve to config.DEAL_ENGINE_BASE_URL, unaffected by the fix."""
    client = DealEngineClient(base_url=None)
    assert client.base_url == config.DEAL_ENGINE_BASE_URL.rstrip("/")


def test_listing_true_cost_success():
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=0)
    payload = {
        "true_cost_result": {
            "true_cost": 19.80,
            "total_savings": 2.20,
            "total_points_earned": 66,
            "applied_deals": [{"deal_type": "discount_pct"}],
            "available_deals": [],
            "confidence": 1.0,
            "user_tier_name": None,
        },
        "listed_price": 22.0,
        "currency": "USD",
    }
    cm = _mock_client(response=_mock_response(payload))

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm):
        result = asyncio.run(client.listing_true_cost(listing_id=7))

    assert result.available is True
    assert result.true_cost == 19.80
    assert result.listed_price == 22.0
    assert result.currency == "USD"
    assert result.total_savings == 2.20
    assert result.applied_deals == [{"deal_type": "discount_pct"}]


def test_listing_true_cost_unreachable_returns_unavailable_never_raises():
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=0)
    cm = _mock_client(raise_exc=ConnectionError("connection refused"))

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm):
        result = asyncio.run(client.listing_true_cost(listing_id=7, user_tier_name="Rouge"))

    assert result.available is False
    assert result.true_cost is None
    assert result.error is not None


def test_listing_true_cost_uses_correct_path_and_tier_param():
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=0)
    instance = AsyncMock()
    instance.request = AsyncMock(return_value=_mock_response({"true_cost_result": {}}))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=instance)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm):
        asyncio.run(client.listing_true_cost(listing_id=42, user_tier_name="Gold"))

    args, kwargs = instance.request.call_args
    method, url = args[0], args[1]
    assert method == "GET"
    assert url.endswith("/api/catalog/listings/42/true-cost")
    assert kwargs["params"] == {"user_tier_name": "Gold"}


def test_listing_true_cost_default_refresh_price_omits_param():
    """refresh_price defaults to False and must not appear in params at all,
    so every existing caller's request is byte-for-byte unchanged."""
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=0)
    instance = AsyncMock()
    instance.request = AsyncMock(return_value=_mock_response({"true_cost_result": {}}))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=instance)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm):
        asyncio.run(client.listing_true_cost(listing_id=42))

    _, kwargs = instance.request.call_args
    assert kwargs["params"] is None


def test_listing_true_cost_refresh_price_true_passes_query_param():
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=0)
    instance = AsyncMock()
    instance.request = AsyncMock(return_value=_mock_response({"true_cost_result": {}}))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=instance)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm):
        asyncio.run(client.listing_true_cost(listing_id=42, refresh_price=True))

    _, kwargs = instance.request.call_args
    assert kwargs["params"] == {"refresh_price": True}


def test_listing_true_cost_surfaces_price_refresh_fields():
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=0)
    payload = {
        "true_cost_result": {"true_cost": 19.80},
        "listed_price": 22.0,
        "currency": "USD",
        "price_was_refreshed": True,
        "price_refreshed_at": "2026-06-28T00:00:00+00:00",
    }
    cm = _mock_client(response=_mock_response(payload))

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm):
        result = asyncio.run(client.listing_true_cost(listing_id=7, refresh_price=True))

    assert result.price_was_refreshed is True
    assert result.price_refreshed_at == "2026-06-28T00:00:00+00:00"


def test_listing_true_cost_defaults_price_refresh_fields_when_absent():
    client = DealEngineClient(base_url="http://deal-engine.test", max_retries=0)
    payload = {"true_cost_result": {"true_cost": 19.80}, "listed_price": 22.0, "currency": "USD"}
    cm = _mock_client(response=_mock_response(payload))

    with patch("clients.deal_engine_client.httpx.AsyncClient", return_value=cm):
        result = asyncio.run(client.listing_true_cost(listing_id=7))

    assert result.price_was_refreshed is False
    assert result.price_refreshed_at is None
