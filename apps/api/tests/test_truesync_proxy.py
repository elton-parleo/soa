"""
Tests for the Merchant Command Center's TrueSync proxy —
clients/truesync_client.py and app/routers/truesync.py.

The proxy exists for three reasons, and all are pinned here:

  1. The tenant token (TRUESYNC_TENANT_TOKEN) is attached server-side, on
     every read and every write, and never leaves the server — not in a
     response body, not in an error detail.
  2. Upstream failures surface as the upstream's own message, so the
     page can render "API errors verbatim" without the proxy
     paraphrasing them.
  3. A 403 — the upstream refusing the token — always leads with
     NOT_AUTHORIZED, so the page can say "not authorized for this
     customer" rather than render an empty or broken view.

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
from app.customer_context import CustomerScope, customer_scope
from app.routers.truesync import SyncRuleProxyRequest
from soa_shared.customers import CustomerOrg

TOKEN = "tst_0123456789abcdef_supersecretsupersecretsupersecretsupersec"

#: The selected customer, as customer_scope hands it to every route. Which
#: org's token is picked, and who may pick which org, is
#: tests/test_customer_scope.py's subject; here it is given.
SCOPE = CustomerScope(
    org=CustomerOrg(id=7, name="Wiggle & Snug", tenant_slug="wiggle-and-snug",
                    token_id="0123456789abcdef", has_stored_token=True),
    token=TOKEN,
)


def upstream_at(base="https://api.example"):
    """TrueSyncClient, pointed at the fake upstream, holding whatever token the router hands it."""
    return lambda token=None: TrueSyncClient(base_url=base, token=token)


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

    async def request(self, method, url, params=None, json=None, headers=None, files=None):
        if self._recorder is not None:
            self._recorder.append(
                {"method": method, "url": url, "params": params, "json": json,
                 "headers": headers or {}, "files": files}
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
    client = TrueSyncClient(base_url="https://api.example", token=TOKEN)

    status, data, error = asyncio.run(client.publish_listing(90))

    assert error is None
    assert status == 200
    assert calls[0]["headers"]["X-TrueSync-Key"] == TOKEN


def test_no_header_at_all_when_no_key_is_configured(monkeypatch, calls):
    """An empty key must mean "no credential presented", not an empty one."""
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, []))
    client = TrueSyncClient(base_url="https://api.example", token="")

    asyncio.run(client.publish_listing(90))

    assert "X-TrueSync-Key" not in calls[0]["headers"]


def test_key_is_scrubbed_from_an_upstream_error_body(monkeypatch, calls):
    """An upstream that echoes the key back must not pass it through."""
    patch_httpx(
        monkeypatch, calls,
        response=FakeResponse(403, None, text=f"forbidden: key {TOKEN} is revoked"),
    )
    client = TrueSyncClient(base_url="https://api.example", token=TOKEN)

    status, data, error = asyncio.run(client.publish_listing(90))

    assert status == 403
    assert TOKEN not in error
    assert "[redacted]" in error


def test_key_is_scrubbed_from_a_transport_exception(monkeypatch, calls):
    patch_httpx(
        monkeypatch, calls,
        raises=RuntimeError(f"connect failed for https://api.example?k={TOKEN}"),
    )
    client = TrueSyncClient(base_url="https://api.example", token=TOKEN)

    status, data, error = asyncio.run(client.publish_listing(90))

    assert status is None
    assert TOKEN not in error
    assert "[redacted]" in error


def test_success_payload_never_carries_the_key_back(monkeypatch, calls):
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, [{"channel_slug": "schema_org"}]))
    client = TrueSyncClient(base_url="https://api.example", token=TOKEN)

    _, data, _ = asyncio.run(client.publish_listing(90))

    assert TOKEN not in repr(data)


def test_a_short_key_is_left_alone_rather_than_mangling_text():
    """Replacing a 1-character 'secret' would corrupt unrelated output."""
    client = TrueSyncClient(base_url="https://api.example", token="a")
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

    asyncio.run(TrueSyncClient(base_url="https://api.example", token=TOKEN).verify_listing(90))

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "https://api.example/api/truesync/listings/90/verify"
    assert calls[0]["params"] is None
    # This is the route the upstream genuinely 403s without a key.
    assert calls[0]["headers"]["X-TrueSync-Key"] == TOKEN


def test_verify_all_targets_the_right_route(monkeypatch, calls):
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, {"verified": 5}))

    asyncio.run(TrueSyncClient(base_url="https://api.example", token=TOKEN).verify_all())

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "https://api.example/api/truesync/verify-all"
    assert calls[0]["headers"]["X-TrueSync-Key"] == TOKEN


def test_verify_surfaces_the_upstream_403_verbatim(monkeypatch, calls):
    """
    The realistic failure for these two: a missing or wrong key. The
    operator needs the upstream's own words, and the key must not be in
    them.
    """
    patch_httpx(monkeypatch, calls, response=FakeResponse(
        403, None, text='{"detail":"missing or invalid X-TrueSync-Key"}'))
    monkeypatch.setattr(truesync_router, "TrueSyncClient", upstream_at())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(truesync_router.verify_listing(90, scope=SCOPE))

    assert exc.value.status_code == 403
    assert exc.value.detail.startswith(truesync_router.NOT_AUTHORIZED)
    assert "missing or invalid X-TrueSync-Key" in exc.value.detail
    assert TOKEN not in exc.value.detail


def test_router_returns_the_verify_summary_unchanged(monkeypatch, calls):
    summary = {"outcome": "ok", "integrity": True, "findings": [], "verification_id": 41}
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, summary))
    monkeypatch.setattr(truesync_router, "TrueSyncClient", upstream_at())

    assert asyncio.run(truesync_router.verify_listing(90, scope=SCOPE)) == summary


def test_an_unconfigured_base_url_fails_cleanly(monkeypatch, calls):
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, []))
    status, data, error = asyncio.run(TrueSyncClient(base_url="", token=TOKEN).publish_listing(90))

    assert status is None
    assert "TRUESYNC_API_BASE" in error
    assert calls == []      # nothing was sent


# ─── The router's translation of that into HTTP ──────────────────────

def test_router_returns_the_upstream_rows_unchanged(monkeypatch, calls):
    rows = [{"channel_slug": "schema_org", "status": "published", "listing_id": 90}]
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, rows))
    monkeypatch.setattr(truesync_router, "TrueSyncClient", upstream_at())

    assert asyncio.run(truesync_router.publish_listing(90, scope=SCOPE)) == rows


def test_router_surfaces_the_upstream_message_verbatim(monkeypatch, calls):
    patch_httpx(monkeypatch, calls,
                response=FakeResponse(422, None, text="listing 999 does not exist"))
    monkeypatch.setattr(truesync_router, "TrueSyncClient", upstream_at())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(truesync_router.publish_listing(999, scope=SCOPE))

    assert exc.value.status_code == 422
    assert exc.value.detail == "listing 999 does not exist"


def test_router_reports_a_transport_failure_as_502_not_500(monkeypatch, calls):
    """The fault is upstream; the page needs to tell that from "this app is broken"."""
    patch_httpx(monkeypatch, calls, raises=RuntimeError("connection refused"))
    monkeypatch.setattr(truesync_router, "TrueSyncClient", upstream_at())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(truesync_router.refresh_gmc_diagnostics(scope=SCOPE))

    assert exc.value.status_code == 502
    assert "connection refused" in exc.value.detail


def test_router_never_leaks_the_key_in_an_error_detail(monkeypatch, calls):
    patch_httpx(monkeypatch, calls,
                response=FakeResponse(401, None, text=f"bad key {TOKEN}"))
    monkeypatch.setattr(truesync_router, "TrueSyncClient", upstream_at())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(truesync_router.put_sync_rule(
            SyncRuleProxyRequest(catalog_product_id=27, channel_slug="acp", enabled=False),
            scope=SCOPE,
        ))

    assert TOKEN not in exc.value.detail


# ─── Mounting ────────────────────────────────────────────────────────

def test_proxy_routes_are_mounted_and_authenticated():
    """
    The proxy must sit behind this app's own auth like every other
    authed route, and must expose ONLY the allow-listed calls — an open
    pass-through holding a tenant token would hand that tenant's data to
    anyone signed in here.
    """
    from app.app import app

    # Merged per path: a GET and a PUT on one path are two route objects.
    proxy_paths = {}
    for r in app.routes:
        if getattr(r, "path", "").startswith("/api/truesync"):
            proxy_paths[r.path] = sorted(
                set(proxy_paths.get(r.path, [])) | (r.methods - {"HEAD", "OPTIONS"})
            )

    assert proxy_paths == {
        **{path: ["GET"] for path in READ_ROUTES},
        **{path: ["GET"] for path in TOKENLESS_READS},
        **{path: [method] for (method, path) in WRITE_ROUTES},
        "/api/truesync/listings/{listing_id}/publish": ["POST"],
        "/api/truesync/listings/{listing_id}/verify": ["POST"],
        # The ACP feed's own probe. Separate from /verify because they fetch
        # different surfaces: that one the merchant's storefront, this one the
        # feed we serve. Routing both through /verify is what left the ACP
        # cell unverified while reporting success.
        "/api/truesync/listings/{listing_id}/verify-acp": ["POST"],
        "/api/truesync/verify-all": ["POST"],
        "/api/truesync/gmc/diagnostics/refresh": ["POST"],
        "/api/truesync/sync-rules": ["PUT"],
        # Step 1C: GET and PUT on one path.
        "/api/truesync/merchants/{merchant_slug}/retailers": ["GET", "PUT"],
        "/api/truesync/merchants/{merchant_slug}/incentives/owned": ["GET", "PUT"],
    }

    # Same verify_token dependency the other authed routers carry.
    from app.auth import verify_token
    for route in app.routes:
        if getattr(route, "path", "").startswith("/api/truesync"):
            deps = [d.call for d in route.dependant.dependencies]
            assert verify_token in deps, f"{route.path} is not behind verify_token"
            # And every one that reaches a tenant is scoped to the SELECTED
            # customer: no route builds its client from a global token.
            if route.path not in TOKENLESS_READS:
                assert customer_scope in deps, f"{route.path} is not scoped to a customer"


# ─── Reads: every scoped GET carries the token ───────────────────────

#: Every read route the proxy mounts -> (concrete path to call, the
#: upstream path it must reach). Table-driven against the router: a GET
#: added without a row here fails test_every_read_route_is_in_the_table.
READ_ROUTES = {
    "/api/truesync/channels": (
        "/api/truesync/channels", "/api/truesync/channels"),
    "/api/truesync/publications": (
        "/api/truesync/publications?limit=500", "/api/truesync/publications"),
    "/api/truesync/merchants": (
        "/api/truesync/merchants", "/api/truesync/merchants"),
    "/api/truesync/merchants/{merchant_slug}/catalog": (
        "/api/truesync/merchants/wiggle-and-snug/catalog",
        "/api/truesync/merchants/wiggle-and-snug/catalog"),
    "/api/truesync/merchants/{merchant_slug}/incentives": (
        "/api/truesync/merchants/wiggle-and-snug/incentives",
        "/api/truesync/merchants/wiggle-and-snug/incentives"),
    "/api/truesync/merchants/{merchant_slug}/price-history": (
        "/api/truesync/merchants/wiggle-and-snug/price-history?limit=50",
        "/api/truesync/merchants/wiggle-and-snug/price-history"),
    "/api/truesync/prospects": (
        "/api/truesync/prospects", "/api/truesync/prospects"),
    "/api/truesync/prospects/{slug}/drift": (
        "/api/truesync/prospects/pampers/drift", "/api/truesync/prospects/pampers/drift"),
    "/api/truesync/listings/{listing_id}/verifications": (
        "/api/truesync/listings/90/verifications?channel=acp&limit=100",
        "/api/truesync/listings/90/verifications"),
    # ── Step 1C ──
    "/api/truesync/tenant": (
        "/api/truesync/tenant", "/api/truesync/tenant"),
    "/api/truesync/merchants/{merchant_slug}/verifications": (
        "/api/truesync/merchants/wiggle-and-snug/verifications?channel=acp&limit=100",
        "/api/truesync/merchants/wiggle-and-snug/verifications"),
    "/api/truesync/merchants/{merchant_slug}/retailers": (
        "/api/truesync/merchants/petco/retailers", "/api/truesync/merchants/petco/retailers"),
    "/api/truesync/merchants/{merchant_slug}/feed": (
        "/api/truesync/merchants/petco/feed", "/api/truesync/merchants/petco/feed"),
    "/api/truesync/merchants/{merchant_slug}/feed/history": (
        "/api/truesync/merchants/petco/feed/history",
        "/api/truesync/merchants/petco/feed/history"),
    "/api/truesync/merchants/{merchant_slug}/incentives/owned": (
        "/api/truesync/merchants/petco/incentives/owned",
        "/api/truesync/merchants/petco/incentives/owned"),
    # ── Step 2A-0
    "/api/truesync/merchants/{merchant_slug}/provenance": (
        "/api/truesync/merchants/petco/provenance",
        "/api/truesync/merchants/petco/provenance"),
}

#: GETs that carry NO tenant token: public upstream, no customer's data.
TOKENLESS_READS = {"/api/truesync/feed/template.{ext}"}

#: Step 1C's writes -> (method, concrete path, request kwargs, upstream path).
#: Table-driven like READ_ROUTES: each must carry the selected customer's token.
WRITE_ROUTES = {
    ("PUT", "/api/truesync/merchants/{merchant_slug}/retailers"): (
        "/api/truesync/merchants/petco/retailers", {"json": {"domains": ["petco.com"]}},
        "/api/truesync/merchants/petco/retailers"),
    ("POST", "/api/truesync/merchants/{merchant_slug}/feed/validate"): (
        "/api/truesync/merchants/petco/feed/validate?skip_reachability=true",
        {"files": [("files", ("f.csv", b"gtin,product_name\n", "text/csv"))]},
        "/api/truesync/merchants/petco/feed/validate"),
    ("POST", "/api/truesync/merchants/{merchant_slug}/feed/commit"): (
        "/api/truesync/merchants/petco/feed/commit",
        {"json": {"upload_id": "u1", "mode": "all_valid_rows"}},
        "/api/truesync/merchants/petco/feed/commit"),
    ("PUT", "/api/truesync/merchants/{merchant_slug}/incentives/owned"): (
        "/api/truesync/merchants/petco/incentives/owned", {"json": {"incentives": []}},
        "/api/truesync/merchants/petco/incentives/owned"),
}


def _mounted_read_routes():
    from app.app import app

    return {
        r.path for r in app.routes
        if getattr(r, "path", "").startswith("/api/truesync") and "GET" in (r.methods or set())
    }


@pytest.fixture
def authed_http(monkeypatch):
    """The real app over HTTP, with this app's own auth satisfied."""
    from fastapi.testclient import TestClient

    from app.app import app
    from app.auth import verify_token

    monkeypatch.setattr(truesync_router, "TrueSyncClient", upstream_at())
    app.dependency_overrides[verify_token] = lambda: {"sub": "test-user"}
    app.dependency_overrides[customer_scope] = lambda: SCOPE
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(verify_token, None)
        app.dependency_overrides.pop(customer_scope, None)


def test_every_read_route_is_in_the_table():
    assert _mounted_read_routes() == set(READ_ROUTES) | TOKENLESS_READS


@pytest.mark.parametrize("key", sorted(WRITE_ROUTES), ids=lambda k: f"{k[0]} {k[1]}")
def test_every_1c_write_attaches_the_tenant_token(authed_http, monkeypatch, calls, key):
    method, _template = key
    call_path, kwargs, upstream_path = WRITE_ROUTES[key]
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, {"ok": True}))

    response = getattr(authed_http, method.lower())(call_path, **kwargs)

    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert calls[0]["method"] == method
    assert calls[0]["url"] == f"https://api.example{upstream_path}"
    assert calls[0]["headers"]["X-TrueSync-Key"] == TOKEN
    assert TOKEN not in response.text


@pytest.mark.parametrize("key", sorted(WRITE_ROUTES), ids=lambda k: f"{k[0]} {k[1]}")
def test_every_1c_write_reports_a_refusal_as_not_authorized(authed_http, monkeypatch, calls, key):
    method, _template = key
    call_path, kwargs, _ = WRITE_ROUTES[key]
    patch_httpx(monkeypatch, calls, response=FakeResponse(403, None, text=f"no {TOKEN}"))

    response = getattr(authed_http, method.lower())(call_path, **kwargs)

    assert response.status_code == 403
    assert response.json()["detail"].startswith(truesync_router.NOT_AUTHORIZED)
    assert TOKEN not in response.text


def test_the_feed_upload_is_forwarded_as_multipart(authed_http, monkeypatch, calls):
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, {"upload_id": "u1"}))
    body = b"gtin,product_name\n036000291452,Thing\n"

    authed_http.post(
        "/api/truesync/merchants/petco/feed/validate?skip_reachability=true",
        files=[("files", ("petco.csv", body, "text/csv"))],
    )

    assert calls[0]["files"] == [("files", ("petco.csv", body, "text/csv"))]
    assert calls[0]["params"] == {"skip_reachability": "true"}


def test_an_oversized_feed_is_refused_before_it_goes_upstream(authed_http, monkeypatch, calls):
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, {}))
    monkeypatch.setattr(truesync_router, "MAX_FEED_UPLOAD_BYTES", 10)

    response = authed_http.post(
        "/api/truesync/merchants/petco/feed/validate",
        files=[("files", ("big.csv", b"x" * 11, "text/csv"))],
    )

    assert response.status_code == 413
    assert calls == []


def test_the_template_is_proxied_without_any_token(authed_http, monkeypatch, calls):
    class FileResponse(FakeResponse):
        content = b"gtin,product_name\n"

    patch_httpx(monkeypatch, calls, response=FileResponse(200, None, text="gtin"))

    response = authed_http.get("/api/truesync/feed/template.csv")

    assert response.status_code == 200
    assert response.content == b"gtin,product_name\n"
    assert "sku-feed-template.csv" in response.headers["content-disposition"]
    assert calls[0]["url"] == "https://api.example/api/truesync/feed/template.csv"
    assert "X-TrueSync-Key" not in calls[0]["headers"]
    assert authed_http.get("/api/truesync/feed/template.exe").status_code == 404


@pytest.mark.parametrize("route", sorted(READ_ROUTES))
def test_every_read_attaches_the_tenant_token(authed_http, monkeypatch, calls, route):
    call_path, upstream_path = READ_ROUTES[route]
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, {"ok": True}))

    response = authed_http.get(call_path)

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}
    assert len(calls) == 1
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == f"https://api.example{upstream_path}"
    assert calls[0]["headers"]["X-TrueSync-Key"] == TOKEN
    # The token goes upstream, never back down.
    assert TOKEN not in response.text


@pytest.mark.parametrize("route", sorted(READ_ROUTES))
def test_every_read_reports_a_refusal_as_not_authorized(authed_http, monkeypatch, calls, route):
    call_path, _ = READ_ROUTES[route]
    patch_httpx(monkeypatch, calls, response=FakeResponse(
        403, None, text=f'{{"detail":"missing or invalid X-TrueSync-Key {TOKEN}"}}'))

    response = authed_http.get(call_path)

    assert response.status_code == 403
    assert response.json()["detail"].startswith(truesync_router.NOT_AUTHORIZED)
    assert TOKEN not in response.text


def test_reads_forward_their_query_params(authed_http, monkeypatch, calls):
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, []))

    authed_http.get("/api/truesync/listings/90/verifications?channel=acp&limit=100")

    assert calls[0]["params"] == {"channel": "acp", "limit": 100}


def test_a_slug_cannot_walk_the_upstream_path(authed_http, monkeypatch, calls):
    """A slug is caller input; it is one path segment upstream, never more."""
    patch_httpx(monkeypatch, calls, response=FakeResponse(200, {}))

    asyncio.run(TrueSyncClient(base_url="https://api.example", token=TOKEN)
                .get_merchant_catalog("../../admin"))

    assert calls[0]["url"] == "https://api.example/api/truesync/merchants/..%2F..%2Fadmin/catalog"


def test_reads_use_the_short_read_timeout(monkeypatch, calls):
    seen = {}

    def factory(**kwargs):
        seen.update(kwargs)
        return FakeAsyncClient(response=FakeResponse(200, []), recorder=calls)

    monkeypatch.setattr(truesync_client_module.httpx, "AsyncClient", factory)
    client = TrueSyncClient(base_url="https://api.example", token=TOKEN,
                            timeout_seconds=90, read_timeout_seconds=15)

    asyncio.run(client.get_merchants())
    assert seen["timeout"] == 15
    asyncio.run(client.verify_all())
    assert seen["timeout"] == 90


def test_the_token_reads_the_new_name_first_and_the_old_as_a_fallback(monkeypatch):
    import importlib

    import soa_shared.config as config

    monkeypatch.setenv("TRUESYNC_ADMIN_KEY", "old-name-value-123")
    monkeypatch.delenv("TRUESYNC_TENANT_TOKEN", raising=False)
    assert importlib.reload(config).TRUESYNC_TENANT_TOKEN == "old-name-value-123"

    monkeypatch.setenv("TRUESYNC_TENANT_TOKEN", "new-name-value-456")
    assert importlib.reload(config).TRUESYNC_TENANT_TOKEN == "new-name-value-456"

    monkeypatch.delenv("TRUESYNC_TENANT_TOKEN")
    monkeypatch.delenv("TRUESYNC_ADMIN_KEY")
    importlib.reload(config)
