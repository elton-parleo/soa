"""
TrueSyncClient — async HTTP client for the supply app's TrueSync
syndication API (the /api/truesync/* surface of the same service
DEAL_ENGINE_BASE_URL points at).

Unlike deal_engine_client.py, this one is NOT mirrored to
apps/pipeline/clients/: only the Merchant Command Center's proxy router
(app/routers/truesync.py) uses it, and the pipeline has no TrueSync
call site. Edit here.

Two things shape it:

  1. It only ever carries MUTATIONS. The Command Center's reads go
     straight from the browser to TRUESYNC_API_BASE — that API answers
     GETs with Access-Control-Allow-Origin: *, so a proxy hop would add
     latency and buy nothing.

  2. TRUESYNC_ADMIN_KEY must never leave the server. It is attached
     here as X-TrueSync-Key and scrubbed out of every error string this
     module returns (_scrub) before a caller — and therefore a browser,
     a log line, or a toast — can ever see it. httpx puts the request
     URL in its exception strings but not headers; _scrub is the
     belt-and-braces for the case where a future upstream echoes the
     header back inside an error body.

Never raises on network/HTTP failure — callers get (status, data,
error) so an upstream outage renders as a toast, not a 500.
"""
import logging
from typing import Any, Optional, Tuple

import httpx

import soa_shared.config as config

logger = logging.getLogger(__name__)

# What the caller gets back: (upstream_status, parsed_json, error_text).
# Exactly one of parsed_json / error_text is meaningful. upstream_status
# is None when the request never got an HTTP response at all.
ForwardResult = Tuple[Optional[int], Optional[Any], Optional[str]]


class TrueSyncClient:

    def __init__(
        self,
        base_url: Optional[str] = None,
        admin_key: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self.base_url = (
            config.TRUESYNC_API_BASE if base_url is None else base_url
        ).rstrip("/")
        self.admin_key = (
            config.TRUESYNC_ADMIN_KEY if admin_key is None else admin_key
        )
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else config.SOA_TRUESYNC_TIMEOUT_SECONDS
        )

    def _scrub(self, text: Optional[str]) -> Optional[str]:
        """
        Remove the admin key from anything on its way back out of this
        module. A short or empty key is not scrubbed — replacing a
        1-character secret would mangle unrelated text, and a key that
        short is not a secret worth protecting anyway.
        """
        if not text or not self.admin_key or len(self.admin_key) < 8:
            return text
        return text.replace(self.admin_key, "[redacted]")

    def _headers(self) -> dict:
        # Empty key -> no header at all, rather than an empty one: an
        # upstream that starts enforcing the key should reject us with a
        # clean 401, not treat "" as a presented-but-wrong credential.
        if not self.admin_key:
            return {}
        return {"X-TrueSync-Key": self.admin_key}

    async def forward(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> ForwardResult:
        """
        One request to TRUESYNC_API_BASE + path, with the admin key
        attached. No retries: every caller is a mutation (publish,
        diagnostics refresh, sync-rule write), and a blind retry of a
        write whose response was merely lost is worse than surfacing the
        failure to the operator who clicked the button.
        """
        if not self.base_url:
            return None, None, "TRUESYNC_API_BASE is not configured"

        url = f"{self.base_url}{path}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.request(
                    method, url, params=params, json=json, headers=self._headers()
                )
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

        try:
            return response.status_code, response.json(), None
        except ValueError:
            # A 2xx with a non-JSON body is still a success upstream;
            # hand back the text so the caller can decide.
            return response.status_code, self._scrub(response.text), None

    # ─── The three mutations the Command Center actually issues ──────────

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
