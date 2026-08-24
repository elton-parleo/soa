"""
Merchant Command Center — the mutation proxy.

The Command Center page (web/src/components/MerchantCommandCenter.jsx)
reads TrueSync directly from the browser: TRUESYNC_API_BASE answers
GETs with Access-Control-Allow-Origin: *, so its catalog, channel,
publication and verification reads need nothing from this app.

Writes cannot work that way, for two independent reasons:

  1. TRUESYNC_ADMIN_KEY is a server-side secret. It must never be in a
     client bundle, a network tab, or a toast. clients/truesync_client.py
     attaches it here and scrubs it from every error it returns.

  2. The upstream CORS policy allows GET/POST/HEAD/OPTIONS only, so a
     browser PUT to /api/truesync/sync-rules fails preflight before it
     is ever sent. Verified 2026-08-22: OPTIONS returns 400 with
     access-control-allow-methods: GET, POST, HEAD, OPTIONS.

Paths deliberately mirror the upstream ones, so the only difference
between a read and a write in truesyncApi.js is which base they hang
off: TRUESYNC_API_BASE for reads, same-origin for these.

Authenticated — mounted with verify_token in app.py, same as cycles.py.
That gates who can trigger a mutation from this app.

The upstream now enforces the key too: re-probed 2026-08-24, a POST to
/api/truesync/listings/90/compile with no X-TrueSync-Key returns 403,
where on 2026-08-22 the same call returned 200. The header was always
sent, so nothing here had to change when that landed.

Only the mutations the page can actually issue are exposed. This is a
deliberate allow-list, not a generic pass-through: an open proxy to an
admin API is exactly the thing an admin key is meant to prevent.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from clients.truesync_client import TrueSyncClient

log = logging.getLogger(__name__)
router = APIRouter()


class SyncRuleProxyRequest(BaseModel):
    catalog_product_id: int
    channel_slug: str
    enabled: bool
    cadence: Optional[str] = None


def _unwrap(status, data, error):
    """
    (status, data, error) -> data, or an HTTPException carrying the
    upstream's own message verbatim (already key-scrubbed by the
    client). The page renders `detail` unchanged in its toast — the
    prompt's "API errors verbatim" — so nothing is rewritten here.

    A transport failure (status is None) becomes 502, not 500: the
    fault is upstream, and the distinction is what lets the page tell
    "TrueSync is down" from "this app is broken".
    """
    if error is not None:
        raise HTTPException(status_code=status or 502, detail=error)
    return data


@router.post("/truesync/listings/{listing_id}/publish")
async def publish_listing(listing_id: int, channels: Optional[str] = None):
    """
    Compile one listing and publish the result. `channels` is an
    optional comma-separated slug list; omitted means every enabled
    channel. Returns the upstream's PublicationRow[] so the caller can
    render the state the server actually recorded — the page does no
    optimistic update.
    """
    return _unwrap(*await TrueSyncClient().publish_listing(listing_id, channels))


@router.post("/truesync/listings/{listing_id}/verify")
async def verify_listing(listing_id: int):
    """
    Fetch this listing's live PDP and record what it served. Returns the
    upstream's own summary ({outcome, integrity, findings, ...}) so the
    page can report the result rather than assume one.

    Both verify routes are newer than the rest of this proxy — they
    shipped upstream on 2026-08-24 — and unlike the others they are
    genuinely key-gated: without X-TrueSync-Key the upstream answers
    403. That is what the proxy is for.
    """
    return _unwrap(*await TrueSyncClient().verify_listing(listing_id))


@router.post("/truesync/verify-all")
async def verify_all():
    """Verify every active listing of the active demo merchant."""
    return _unwrap(*await TrueSyncClient().verify_all())


@router.post("/truesync/gmc/diagnostics/refresh")
async def refresh_gmc_diagnostics(listing_id: Optional[int] = None):
    """
    Ask TrueSync to read Merchant Center product statuses back and
    record them. Omitting listing_id refreshes every listing — which is
    what the header button does.
    """
    return _unwrap(*await TrueSyncClient().refresh_gmc_diagnostics(listing_id))


@router.put("/truesync/sync-rules")
async def put_sync_rule(body: SyncRuleProxyRequest):
    """
    Turn one channel on or off for one catalog product. Note the key:
    the upstream sync-rule API is addressed by catalog_product_id, not
    the listing_id everything else on this page uses — the page reads
    the mapping off GET /api/truesync/listings/{id}.
    """
    return _unwrap(
        *await TrueSyncClient().put_sync_rule(
            body.catalog_product_id, body.channel_slug, body.enabled, body.cadence
        )
    )
