"""
Tests for the Merchant Command Center's mutation proxy —
clients/truesync_client.py and app/routers/truesync.py.

The proxy exists for exactly two reasons, and both are pinned here:

  1. TRUESYNC_ADMIN_KEY is attached server-side and never leaves the
     server — not in a response body, not in an error detail.
  2. Upstream failures surface as the upstream's own message, so the
     page can render "API errors verbatim" without the proxy
     paraphrasing them.

Route functions are called directly with a stubbed httpx client, the
same pattern test_full_analysis_router.py uses — no network, no live
TrueSync dependency.
"""
import asyncio

import pytest
from fastapi import HTTPException

import clients.truesync_client as truesync_client_module
from clients.truesync_client import TrueSyncClient
import app.routers.truesync as truesync_router
from app.routers.truesync import SyncRuleProxyRequest

ADMIN_KEY = "ts_live_supersecretkey_abcdef123456"


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body
        self.text = text if text else ("" if json_body is None else "<json>")

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeAsyncClient:
    """Records the one request made through it, then answers with a canned response."""

    def __init__(self, response=None, raises=None, recorder=None, **kwargs):
        self._response = response
        self._raises = raises
        self._recorder = recorder
        self.init_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def request(self, method, url, params=None, json=None, headers=None):
        if self._recorder is not None:
            self._recorder.append(
                {"method": method, "url": url, "params": params, "json": json,
                 "headers": headers or {}}
            )
        if self._raises is not None:
            raise self._raises
        return self._response


@pytest.fixture
def calls():
    return []


def patch_httpx(monkeypatch, calls, response=None, raises=None):
    def factory(**kwargs):
        return FakeAsyncClient(response=response, raises=raises, recorder=calls, **kwargs)

    monkeypatch.setattr(truesync_client_module.httpx, "AsyncClient", factory)


# ─── The key never leaves the server ─────────────────────────────────

def test_admin_key_is_attached_as_a_header(monkeypatch, calls):
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, [{"status": "published"}]))
    client = TrueSyncClient(base_url="https://api.example", admin_key=ADMIN_KEY)

    status, data, error = asyncio.run(client.publish_listing(90))

    assert error is None
    assert status == 200
    assert calls[0]["headers"]["X-TrueSync-Key"] == ADMIN_KEY


def test_no_header_at_all_when_no_key_is_configured(monkeypatch, calls):
    """An empty key must mean "no credential presented", not an empty one."""
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, []))
    client = TrueSyncClient(base_url="https://api.example", admin_key="")

    asyncio.run(client.publish_listing(90))

    assert "X-TrueSync-Key" not in calls[0]["headers"]


def test_key_is_scrubbed_from_an_upstream_error_body(monkeypatch, calls):
    """An upstream that echoes the key back must not pass it through."""
    patch_httpx(
        monkeypatch, calls,
        response=FakeResponse(403, None, text=f"forbidden: key {ADMIN_KEY} is revoked"),
    )
    client = TrueSyncClient(base_url="https://api.example", admin_key=ADMIN_KEY)

    status, data, error = asyncio.run(client.publish_listing(90))

    assert status == 403
    assert ADMIN_KEY not in error
    assert "[redacted]" in error


def test_key_is_scrubbed_from_a_transport_exception(monkeypatch, calls):
    patch_httpx(
        monkeypatch, calls,
        raises=RuntimeError(f"connect failed for https://api.example?k={ADMIN_KEY}"),
    )
    client = TrueSyncClient(base_url="https://api.example", admin_key=ADMIN_KEY)

    status, data, error = asyncio.run(client.publish_listing(90))

    assert status is None
    assert ADMIN_KEY not in error
    assert "[redacted]" in error


def test_success_payload_never_carries_the_key_back(monkeypatch, calls):
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, [{"channel_slug": "schema_org"}]))
    client = TrueSyncClient(base_url="https://api.example", admin_key=ADMIN_KEY)

    _, data, _ = asyncio.run(client.publish_listing(90))

    assert ADMIN_KEY not in repr(data)


def test_a_short_key_is_left_alone_rather_than_mangling_text():
    """Replacing a 1-character 'secret' would corrupt unrelated output."""
    client = TrueSyncClient(base_url="https://api.example", admin_key="a")
    assert client._scrub("a catastrophic failure") == "a catastrophic failure"


# ─── Requests are shaped the way the upstream expects ────────────────

def test_publish_forwards_the_channels_filter(monkeypatch, calls):
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, []))
    asyncio.run(TrueSyncClient(base_url="https://api.example").publish_listing(90, "schema_org"))

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "https://api.example/api/truesync/listings/90/publish"
    assert calls[0]["params"] == {"channels": "schema_org"}


def test_publish_omits_the_channels_param_when_unset(monkeypatch, calls):
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, []))
    asyncio.run(TrueSyncClient(base_url="https://api.example").publish_listing(90))

    assert calls[0]["params"] is None


def test_gmc_refresh_scopes_to_one_listing_or_all(monkeypatch, calls):
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, {}))
    client = TrueSyncClient(base_url="https://api.example")

    asyncio.run(client.refresh_gmc_diagnostics(90))
    assert calls[0]["params"] == {"listing_id": 90}

    asyncio.run(client.refresh_gmc_diagnostics())
    assert calls[1]["params"] is None


def test_sync_rule_is_keyed_by_catalog_product_id(monkeypatch, calls):
    """Not listing_id — the upstream keys this endpoint differently to every other."""
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, {"enabled": True}))

    asyncio.run(TrueSyncClient(base_url="https://api.example").put_sync_rule(27, "schema_org", True))

    assert calls[0]["method"] == "PUT"
    assert calls[0]["json"] == {
        "catalog_product_id": 27, "channel_slug": "schema_org",
        "enabled": True, "cadence": None,
    }


def test_verify_listing_targets_the_right_route(monkeypatch, calls):
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, {"outcome": "ok"}))

    asyncio.run(TrueSyncClient(base_url="https://api.example", admin_key=ADMIN_KEY).verify_listing(90))

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "https://api.example/api/truesync/listings/90/verify"
    assert calls[0]["params"] is None
    # This is the route the upstream genuinely 403s without a key.
    assert calls[0]["headers"]["X-TrueSync-Key"] == ADMIN_KEY


def test_verify_all_targets_the_right_route(monkeypatch, calls):
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, {"verified": 5}))

    asyncio.run(TrueSyncClient(base_url="https://api.example", admin_key=ADMIN_KEY).verify_all())

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "https://api.example/api/truesync/verify-all"
    assert calls[0]["headers"]["X-TrueSync-Key"] == ADMIN_KEY


def test_verify_surfaces_the_upstream_403_verbatim(monkeypatch, calls):
    """
    The realistic failure for these two: a missing or wrong key. The
    operator needs the upstream's own words, and the key must not be in
    them.
    """
    patch_httpx(monkeypatch, calls, response=FakeResponse(
        403, None, text='{"detail":"missing or invalid X-TrueSync-Key"}'))
    monkeypatch.setattr(truesync_router, "TrueSyncClient",
                        lambda: TrueSyncClient(base_url="https://api.example", admin_key=ADMIN_KEY))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(truesync_router.verify_listing(90))

    assert exc.value.status_code == 403
    assert "missing or invalid X-TrueSync-Key" in exc.value.detail
    assert ADMIN_KEY not in exc.value.detail


def test_router_returns_the_verify_summary_unchanged(monkeypatch, calls):
    summary = {"outcome": "ok", "integrity": True, "findings": [], "verification_id": 41}
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, summary))
    monkeypatch.setattr(truesync_router, "TrueSyncClient",
                        lambda: TrueSyncClient(base_url="https://api.example"))

    assert asyncio.run(truesync_router.verify_listing(90)) == summary


def test_an_unconfigured_base_url_fails_cleanly(monkeypatch, calls):
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, []))
    status, data, error = asyncio.run(TrueSyncClient(base_url="", admin_key=ADMIN_KEY).publish_listing(90))

    assert status is None
    assert "TRUESYNC_API_BASE" in error
    assert calls == []      # nothing was sent


# ─── The router's translation of that into HTTP ──────────────────────

def test_router_returns_the_upstream_rows_unchanged(monkeypatch, calls):
    rows = [{"channel_slug": "schema_org", "status": "published", "listing_id": 90}]
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, rows))
    monkeypatch.setattr(truesync_router, "TrueSyncClient",
                        lambda: TrueSyncClient(base_url="https://api.example", admin_key=ADMIN_KEY))

    assert asyncio.run(truesync_router.publish_listing(90)) == rows


def test_router_surfaces_the_upstream_message_verbatim(monkeypatch, calls):
    patch_httpx(monkeypatch, calls,
                response=FakeResponse(422, None, text="listing 999 does not exist"))
    monkeypatch.setattr(truesync_router, "TrueSyncClient",
                        lambda: TrueSyncClient(base_url="https://api.example"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(truesync_router.publish_listing(999))

    assert exc.value.status_code == 422
    assert exc.value.detail == "listing 999 does not exist"


def test_router_reports_a_transport_failure_as_502_not_500(monkeypatch, calls):
    """The fault is upstream; the page needs to tell that from "this app is broken"."""
    patch_httpx(monkeypatch, calls, raises=RuntimeError("connection refused"))
    monkeypatch.setattr(truesync_router, "TrueSyncClient",
                        lambda: TrueSyncClient(base_url="https://api.example"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(truesync_router.refresh_gmc_diagnostics())

    assert exc.value.status_code == 502
    assert "connection refused" in exc.value.detail


def test_router_never_leaks_the_key_in_an_error_detail(monkeypatch, calls):
    patch_httpx(monkeypatch, calls,
                response=FakeResponse(401, None, text=f"bad key {ADMIN_KEY}"))
    monkeypatch.setattr(truesync_router, "TrueSyncClient",
                        lambda: TrueSyncClient(base_url="https://api.example", admin_key=ADMIN_KEY))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(truesync_router.put_sync_rule(
            SyncRuleProxyRequest(catalog_product_id=27, channel_slug="acp", enabled=False)
        ))

    assert ADMIN_KEY not in exc.value.detail


# ─── Mounting ────────────────────────────────────────────────────────

def test_proxy_routes_are_mounted_and_authenticated():
    """
    The proxy must sit behind this app's own auth like every other
    mutation, and must expose ONLY the three allow-listed writes — an
    open pass-through to an admin API would defeat the point of it.
    """
    from app.app import app

    proxy_paths = {
        r.path: sorted(r.methods - {"HEAD", "OPTIONS"})
        for r in app.routes
        if getattr(r, "path", "").startswith("/api/truesync")
    }

    assert proxy_paths == {
        "/api/truesync/listings/{listing_id}/publish": ["POST"],
        "/api/truesync/listings/{listing_id}/verify": ["POST"],
        "/api/truesync/verify-all": ["POST"],
        "/api/truesync/gmc/diagnostics/refresh": ["POST"],
        "/api/truesync/sync-rules": ["PUT"],
    }

    # Same verify_token dependency the other authed routers carry.
    from app.auth import verify_token
    for route in app.routes:
        if getattr(route, "path", "").startswith("/api/truesync"):
            deps = [d.call for d in route.dependant.dependencies]
            assert verify_token in deps, f"{route.path} is not behind verify_token"
