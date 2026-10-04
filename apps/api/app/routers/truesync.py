"""
Merchant Command Center — the TrueSync proxy, for reads and writes.

Since supply's tenancy step (parleo-supply-app, docs/truesync/tenancy.md)
every TrueSync route is one of two kinds:

  * PUBLIC — the published serving surface: the active brand, a merchant's
    schema-org feed, one listing's record. The page still reads these
    straight from TRUESYNC_API_BASE; there is nothing to authenticate.

  * SCOPED — everything else, reads included. Refused without the
    tenant's token in X-TrueSync-Key. A token is a server-side secret, so
    every scoped call the page makes comes through here, where
    clients/truesync_client.py attaches TRUESYNC_TENANT_TOKEN and scrubs
    it from every error it returns. It must never be in a client bundle,
    a network tab, or a toast.

The upstream CORS policy also allows GET/POST/HEAD/OPTIONS only, so a
browser PUT to /api/truesync/sync-rules would fail preflight regardless.

Paths deliberately mirror the upstream ones, so the only difference
between a public read and a scoped one in truesyncApi.js is which base it
hangs off: TRUESYNC_API_BASE for public, same-origin for these.

Authenticated — mounted with verify_token in app.py, same as cycles.py.
That gates who can reach the tenant's data from this app.

A 403 from the upstream means it refused this app's tenant token: the
token is missing, revoked, or belongs to a different customer. It comes
back as 403 with NOT_AUTHORIZED leading the detail, so the page can say
"not authorized for this customer" rather than look empty or broken.

Only the calls the page actually issues are exposed. This is a
deliberate allow-list, not a generic pass-through: an open proxy holding
a tenant token would hand that tenant's data to anyone signed in here.
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


#: What a refused tenant token reads as, everywhere. The page keys on the
#: 403 status; the words are for whoever reads the toast or the job error.
NOT_AUTHORIZED = "Not authorized for this customer"


def _unwrap(status, data, error):
    """
    (status, data, error) -> data, or an HTTPException carrying the
    upstream's own message (already token-scrubbed by the client). The
    page renders `detail` unchanged in its toast, so nothing is
    paraphrased — except a 403, which is led by NOT_AUTHORIZED so it can
    never be mistaken for an empty catalog or a broken page. The
    upstream's words follow it.

    A transport failure (status is None) becomes 502, not 500: the
    fault is upstream, and the distinction is what lets the page tell
    "TrueSync is down" from "this app is broken".
    """
    if error is not None:
        if status == 403:
            raise HTTPException(
                status_code=403,
                detail=f"{NOT_AUTHORIZED} — TrueSync refused this app's tenant token ({error})",
            )
        raise HTTPException(status_code=status or 502, detail=error)
    return data


# ─── Reads — every scoped GET the page makes ────────────────────────────

@router.get("/truesync/channels")
async def get_channels():
    return _unwrap(*await TrueSyncClient().get_channels())


@router.get("/truesync/publications")
async def get_publications(limit: Optional[int] = None):
    return _unwrap(*await TrueSyncClient().get_publications(limit))


@router.get("/truesync/merchants")
async def get_merchants():
    return _unwrap(*await TrueSyncClient().get_merchants())


@router.get("/truesync/merchants/{merchant_slug}/catalog")
async def get_merchant_catalog(merchant_slug: str):
    return _unwrap(*await TrueSyncClient().get_merchant_catalog(merchant_slug))


@router.get("/truesync/merchants/{merchant_slug}/incentives")
async def get_merchant_incentives(merchant_slug: str):
    return _unwrap(*await TrueSyncClient().get_merchant_incentives(merchant_slug))


@router.get("/truesync/merchants/{merchant_slug}/price-history")
async def get_merchant_price_history(merchant_slug: str, limit: Optional[int] = None):
    return _unwrap(
        *await TrueSyncClient().get_merchant_price_history(merchant_slug, limit)
    )


@router.get("/truesync/prospects")
async def get_prospects():
    return _unwrap(*await TrueSyncClient().get_prospects())


@router.get("/truesync/prospects/{slug}/drift")
async def get_prospect_drift(slug: str):
    return _unwrap(*await TrueSyncClient().get_prospect_drift(slug))


@router.get("/truesync/listings/{listing_id}/verifications")
async def get_verifications(
    listing_id: int, channel: Optional[str] = None, limit: Optional[int] = None
):
    return _unwrap(*await TrueSyncClient().get_verifications(listing_id, channel, limit))


# ─── Writes ─────────────────────────────────────────────────────────────


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

    Token-gated upstream like every scoped route: without X-TrueSync-Key
    it answers 403. That is what the proxy is for.
    """
    return _unwrap(*await TrueSyncClient().verify_listing(listing_id))


@router.post("/truesync/listings/{listing_id}/verify-acp")
async def verify_listing_acp(listing_id: int):
    """
    Fetch this listing's ACP feed from its serving URL and record what it
    served. Same shape of answer as /verify — {outcome, integrity, findings}
    — but against the `acp` channel, so the ACP cell gets its own badge
    rather than borrowing schema.org's.

    Token-gated upstream like the other verify routes; that is what the
    proxy is for.
    """
    return _unwrap(*await TrueSyncClient().verify_listing_acp(listing_id))


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
