"""
TrueSyncClient — async HTTP client for the supply app's TrueSync
syndication API (the /api/truesync/* surface of the same service
DEAL_ENGINE_BASE_URL points at).

Unlike deal_engine_client.py, this one is NOT mirrored to
apps/pipeline/clients/: only the Merchant Command Center's proxy router
(app/routers/truesync.py) uses it. The pipeline's catalog reads have
their own synchronous client (apps/pipeline/clients/truesync_catalog.py).

Two things shape it:

  1. It carries every SCOPED call the Command Center makes, reads as well
     as writes. Since supply's tenancy step, a scoped TrueSync route
     refuses a request without its tenant's token, and a token cannot go
     to a browser — so the page's reads come through here too. Only the
     public serving routes (active brand, schema-org feeds, a listing's
     record) are still read straight from the browser.

  2. The token must never leave the server. Since Step 1C it is the
     selected customer org's (app/customer_context.py hands it in; the
     TRUESYNC_TENANT_TOKEN default is only the per-org fallback's). It is
     attached here as X-TrueSync-Key and scrubbed out of every error string this
     module returns (_scrub) before a caller — and therefore a browser,
     a log line, or a toast — can ever see it. httpx puts the request
     URL in its exception strings but not headers; _scrub is the
     belt-and-braces for the case where an upstream echoes the header
     back inside an error body.

Never raises on network/HTTP failure — callers get (status, data,
error) so an upstream outage renders as a toast, not a 500.
"""
import logging
from typing import Any, Optional, Tuple
from urllib.parse import quote

import httpx

import soa_shared.config as config

logger = logging.getLogger(__name__)

# What the caller gets back: (upstream_status, parsed_json, error_text).
# Exactly one of parsed_json / error_text is meaningful. upstream_status
# is None when the request never got an HTTP response at all.
ForwardResult = Tuple[Optional[int], Optional[Any], Optional[str]]


def _slug(value: str) -> str:
    """A path segment, encoded — a slug is caller input on its way upstream."""
    return quote(str(value), safe="")


class TrueSyncClient:

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        read_timeout_seconds: Optional[float] = None,
        header_name: str = "X-TrueSync-Key",
    ) -> None:
        self.base_url = (
            config.TRUESYNC_API_BASE if base_url is None else base_url
        ).rstrip("/")
        self.token = config.TRUESYNC_TENANT_TOKEN if token is None else token
        # The provisioning client sends a different credential under a
        # different name; scrubbing covers whichever this instance holds.
        self.header_name = header_name
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else config.SOA_TRUESYNC_TIMEOUT_SECONDS
        )
        self.read_timeout_seconds = (
            read_timeout_seconds
            if read_timeout_seconds is not None
            else config.SOA_TRUESYNC_READ_TIMEOUT_SECONDS
        )

    def _scrub(self, text: Optional[str]) -> Optional[str]:
        """
        Remove the token from anything on its way back out of this
        module. A short or empty token is not scrubbed — replacing a
        1-character secret would mangle unrelated text, and a token that
        short is not a secret worth protecting anyway.
        """
        if not text or not self.token or len(self.token) < 8:
            return text
        return text.replace(self.token, "[redacted]")

    def _headers(self) -> dict:
        # Empty token -> no header at all, rather than an empty one: the
        # upstream should reject us as "no credential presented", not as
        # a presented-but-wrong one.
        if not self.token:
            return {}
        return {self.header_name: self.token}

    async def forward(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
        files: Optional[list] = None,
        raw: bool = False,
    ) -> ForwardResult:
        """
        One request to TRUESYNC_API_BASE + path, with the token attached.

        `files` is httpx's multipart list, passed through as-is (the feed
        upload). `raw=True` hands back the response itself rather than its
        JSON, for the template download, which is a file.
        No retries: a blind retry of a write whose response was merely
        lost is worse than surfacing the failure to the operator who
        clicked the button, and a read the page retries on its own.
        """
        if not self.base_url:
            return None, None, "TRUESYNC_API_BASE is not configured"

        url = f"{self.base_url}{path}"
        timeout = self.read_timeout_seconds if method == "GET" else self.timeout_seconds

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                kwargs = {"params": params, "headers": self._headers()}
                if json is not None:
                    kwargs["json"] = json
                if files is not None:
                    kwargs["files"] = files
                response = await client.request(method, url, **kwargs)
        except Exception as exc:
            # str(exc) carries the URL, never the headers — but scrub anyway.
            error = self._scrub(str(exc))
            logger.warning("[truesync] %s %s failed: %s", method, url, error)
            return None, None, error

        if response.status_code >= 400:
            detail = self._scrub(response.text)[:1000] if response.text else ""
            logger.warning(
                "[truesync] %s %s -> %d: %s", method, url, response.status_code, detail
            )
            return response.status_code, None, detail or f"upstream returned {response.status_code}"

        if raw:
            return response.status_code, response, None
        try:
            return response.status_code, response.json(), None
        except ValueError:
            # A 2xx with a non-JSON body is still a success upstream;
            # hand back the text so the caller can decide.
            return response.status_code, self._scrub(response.text), None

    # ─── Reads — the Command Center's scoped GETs ────────────────────────

    async def get(self, path: str, params: Optional[dict] = None) -> ForwardResult:
        return await self.forward("GET", path, params=params)

    async def get_channels(self) -> ForwardResult:
        return await self.get("/api/truesync/channels")

    async def get_publications(self, limit: Optional[int] = None) -> ForwardResult:
        return await self.get(
            "/api/truesync/publications",
            params={"limit": limit} if limit is not None else None,
        )

    async def get_merchants(self) -> ForwardResult:
        return await self.get("/api/truesync/merchants")

    async def get_merchant_catalog(self, merchant_slug: str) -> ForwardResult:
        return await self.get(f"/api/truesync/merchants/{_slug(merchant_slug)}/catalog")

    async def get_merchant_incentives(self, merchant_slug: str) -> ForwardResult:
        return await self.get(f"/api/truesync/merchants/{_slug(merchant_slug)}/incentives")

    async def get_merchant_price_history(
        self, merchant_slug: str, limit: Optional[int] = None
    ) -> ForwardResult:
        return await self.get(
            f"/api/truesync/merchants/{_slug(merchant_slug)}/price-history",
            params={"limit": limit} if limit is not None else None,
        )

    async def get_prospects(self) -> ForwardResult:
        return await self.get("/api/truesync/prospects")

    async def get_prospect_drift(self, slug: str) -> ForwardResult:
        return await self.get(f"/api/truesync/prospects/{_slug(slug)}/drift")

    async def get_verifications(
        self,
        listing_id: int,
        channel: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> ForwardResult:
        params = {}
        if channel:
            params["channel"] = channel
        if limit is not None:
            params["limit"] = limit
        return await self.get(
            f"/api/truesync/listings/{listing_id}/verifications", params=params or None
        )

    # ─── Step 1C: the tenant, bulk verifications, the SKU feed ───────────

    async def get_tenant(self) -> ForwardResult:
        """The selected org's tenant and every merchant it owns (the switcher)."""
        return await self.get("/api/truesync/tenant")

    async def get_merchant_verifications(
        self, merchant_slug: str, *, channel: Optional[str] = None,
        method: Optional[str] = None, since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> ForwardResult:
        params = {
            k: v for k, v in
            {"channel": channel, "method": method, "since": since, "limit": limit}.items()
            if v is not None
        }
        return await self.get(
            f"/api/truesync/merchants/{_slug(merchant_slug)}/verifications",
            params=params or None,
        )

    async def get_retailers(self, merchant_slug: str) -> ForwardResult:
        return await self.get(f"/api/truesync/merchants/{_slug(merchant_slug)}/retailers")

    async def put_retailers(self, merchant_slug: str, domains: list) -> ForwardResult:
        return await self.forward(
            "PUT", f"/api/truesync/merchants/{_slug(merchant_slug)}/retailers",
            json={"domains": domains},
        )

    async def validate_feed(
        self, merchant_slug: str, files: list, skip_reachability: bool = False,
    ) -> ForwardResult:
        return await self.forward(
            "POST", f"/api/truesync/merchants/{_slug(merchant_slug)}/feed/validate",
            params={"skip_reachability": "true" if skip_reachability else "false"},
            files=files,
        )

    async def commit_feed(self, merchant_slug: str, upload_id: str, mode: str) -> ForwardResult:
        return await self.forward(
            "POST", f"/api/truesync/merchants/{_slug(merchant_slug)}/feed/commit",
            json={"upload_id": upload_id, "mode": mode},
        )

    async def get_feed(self, merchant_slug: str) -> ForwardResult:
        return await self.get(f"/api/truesync/merchants/{_slug(merchant_slug)}/feed")

    async def get_feed_history(self, merchant_slug: str) -> ForwardResult:
        return await self.get(f"/api/truesync/merchants/{_slug(merchant_slug)}/feed/history")

    async def get_owned_incentives(self, merchant_slug: str) -> ForwardResult:
        return await self.get(
            f"/api/truesync/merchants/{_slug(merchant_slug)}/incentives/owned"
        )

    async def put_owned_incentives(self, merchant_slug: str, incentives: list) -> ForwardResult:
        return await self.forward(
            "PUT", f"/api/truesync/merchants/{_slug(merchant_slug)}/incentives/owned",
            json={"incentives": incentives},
        )

    async def create_merchant(self, merchant: dict) -> ForwardResult:
        """A merchant in this token's tenant: {slug, name, domain, kind, hosting}."""
        return await self.forward("POST", "/api/truesync/tenant/merchants", json=merchant)

    async def get_template(self, ext: str) -> ForwardResult:
        """The SKU-feed template file. Public upstream; carried raw."""
        return await self.forward("GET", f"/api/truesync/feed/template.{ext}", raw=True)

    # ─── Writes ──────────────────────────────────────────────────────────

    async def publish_listing(
        self, listing_id: int, channels: Optional[str] = None
    ) -> ForwardResult:
        params = {"channels": channels} if channels else None
        return await self.forward(
            "POST", f"/api/truesync/listings/{listing_id}/publish", params=params
        )

    async def verify_listing(self, listing_id: int) -> ForwardResult:
        """
        POST /listings/{id}/verify — fetches the listing's live PDP and
        records what it served as a fetch_probe verification. Read-only
        against the merchant's own store; it appends a verification row
        and publishes nothing.
        """
        return await self.forward(
            "POST", f"/api/truesync/listings/{listing_id}/verify"
        )

    async def verify_listing_acp(self, listing_id: int) -> ForwardResult:
        """
        POST /listings/{id}/verify-acp — fetches the listing's ACP feed from
        the serving URL on its publication row and compares it to the stored
        artifact. Writes a fetch_probe verification row against the `acp`
        channel, exactly as the schema.org probe does against `schema_org`.

        Separate from verify_listing because they probe different surfaces:
        one fetches the merchant's storefront, the other fetches our own feed
        endpoint. A single call cannot do both, and pointing the schema.org
        probe at an ACP cell is what this fixes.
        """
        return await self.forward(
            "POST", f"/api/truesync/listings/{listing_id}/verify-acp"
        )

    async def verify_all(self) -> ForwardResult:
        """
        POST /verify-all — the same probe across every active listing of
        the active demo merchant. Slower than a single verify by roughly
        the listing count, which is why the timeout is generous.
        """
        return await self.forward("POST", "/api/truesync/verify-all")

    async def refresh_gmc_diagnostics(
        self, listing_id: Optional[int] = None
    ) -> ForwardResult:
        params = {"listing_id": listing_id} if listing_id is not None else None
        return await self.forward(
            "POST", "/api/truesync/gmc/diagnostics/refresh", params=params
        )

    async def put_sync_rule(
        self,
        catalog_product_id: int,
        channel_slug: str,
        enabled: bool,
        cadence: Optional[str] = None,
    ) -> ForwardResult:
        return await self.forward(
            "PUT",
            "/api/truesync/sync-rules",
            json={
                "catalog_product_id": catalog_product_id,
                "channel_slug": channel_slug,
                "enabled": enabled,
                "cadence": cadence,
            },
        )


PROVISIONING_HEADER = "X-TrueSync-Provisioning-Key"


class TrueSyncProvisioningClient(TrueSyncClient):
    """
    The one call made with supply's provisioning key instead of a tenant
    token: create a tenant and receive its first token, once. The key is
    scrubbed exactly as a token is; the returned token is the caller's to
    seal and store, and it never goes further than that.
    """

    def __init__(self, key: Optional[str] = None, **kwargs) -> None:
        super().__init__(
            token=config.TRUESYNC_PROVISIONING_KEY if key is None else key,
            header_name=PROVISIONING_HEADER,
            **kwargs,
        )

    async def create_tenant(self, slug: str, display_name: str, soa_org_id: str) -> ForwardResult:
        if not self.token:
            return None, None, "TRUESYNC_PROVISIONING_KEY is not set on this service"
        return await self.forward(
            "POST", "/api/truesync/tenants",
            json={"slug": slug, "display_name": display_name, "soa_org_id": soa_org_id},
        )
