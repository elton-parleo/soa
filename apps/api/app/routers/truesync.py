"""
Merchant Command Center — the TrueSync proxy, for reads and writes.

Since supply's tenancy step (parleo-supply-app, docs/truesync/tenancy.md)
every TrueSync route is one of two kinds:

  * PUBLIC — the published serving surface: the active brand, a merchant's
    schema-org feed, one listing's record. The page still reads these
    straight from TRUESYNC_API_BASE; there is nothing to authenticate.

  * SCOPED — everything else, reads included. Refused without the
    tenant's token in X-TrueSync-Key. A token is a server-side secret, so
    every scoped call the page makes comes through here. Since Step 1C the
    token is the SELECTED CUSTOMER's: every route depends on
    customer_scope (app/customer_context.py), which resolves the page's
    X-Parleo-Customer against the user's rights and opens that org's
    sealed token; clients/truesync_client.py attaches it and scrubs it
    from every error it returns. It must never be in a client bundle, a
    network tab, or a toast. There is no global token any more except the
    TRUESYNC_TENANT_TOKEN fallback for a linked org with none stored.

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

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from typing import List, Optional

from app.customer_context import CustomerScope, customer_scope
from clients.truesync_client import TrueSyncClient

log = logging.getLogger(__name__)
router = APIRouter()


class SyncRuleProxyRequest(BaseModel):
    catalog_product_id: int
    channel_slug: str
    enabled: bool
    cadence: Optional[str] = None


def _client(scope: CustomerScope) -> TrueSyncClient:
    """The upstream client, holding the selected customer's token."""
    return TrueSyncClient(token=scope.token)


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
async def get_channels(scope: CustomerScope = Depends(customer_scope)):
    return _unwrap(*await _client(scope).get_channels())


@router.get("/truesync/publications")
async def get_publications(
    limit: Optional[int] = None,
    scope: CustomerScope = Depends(customer_scope),
):
    return _unwrap(*await _client(scope).get_publications(limit))


@router.get("/truesync/merchants")
async def get_merchants(scope: CustomerScope = Depends(customer_scope)):
    return _unwrap(*await _client(scope).get_merchants())


@router.get("/truesync/merchants/{merchant_slug}/catalog")
async def get_merchant_catalog(merchant_slug: str, scope: CustomerScope = Depends(customer_scope)):
    return _unwrap(*await _client(scope).get_merchant_catalog(merchant_slug))


@router.get("/truesync/merchants/{merchant_slug}/incentives")
async def get_merchant_incentives(
    merchant_slug: str,
    scope: CustomerScope = Depends(customer_scope),
):
    return _unwrap(*await _client(scope).get_merchant_incentives(merchant_slug))


@router.get("/truesync/merchants/{merchant_slug}/price-history")
async def get_merchant_price_history(
    merchant_slug: str,
    limit: Optional[int] = None,
    scope: CustomerScope = Depends(customer_scope),
):
    return _unwrap(
        *await _client(scope).get_merchant_price_history(merchant_slug, limit)
    )


@router.get("/truesync/prospects")
async def get_prospects(scope: CustomerScope = Depends(customer_scope)):
    return _unwrap(*await _client(scope).get_prospects())


@router.get("/truesync/prospects/{slug}/drift")
async def get_prospect_drift(slug: str, scope: CustomerScope = Depends(customer_scope)):
    return _unwrap(*await _client(scope).get_prospect_drift(slug))


@router.get("/truesync/listings/{listing_id}/verifications")
async def get_verifications(
    listing_id: int, channel: Optional[str] = None, limit: Optional[int] = None,
    scope: CustomerScope = Depends(customer_scope),
):
    return _unwrap(*await _client(scope).get_verifications(listing_id, channel, limit))


# ─── Writes ─────────────────────────────────────────────────────────────


@router.post("/truesync/listings/{listing_id}/publish")
async def publish_listing(
    listing_id: int,
    channels: Optional[str] = None,
    scope: CustomerScope = Depends(customer_scope),
):
    """
    Compile one listing and publish the result. `channels` is an
    optional comma-separated slug list; omitted means every enabled
    channel. Returns the upstream's PublicationRow[] so the caller can
    render the state the server actually recorded — the page does no
    optimistic update.
    """
    return _unwrap(*await _client(scope).publish_listing(listing_id, channels))


@router.post("/truesync/listings/{listing_id}/verify")
async def verify_listing(listing_id: int, scope: CustomerScope = Depends(customer_scope)):
    """
    Fetch this listing's live PDP and record what it served. Returns the
    upstream's own summary ({outcome, integrity, findings, ...}) so the
    page can report the result rather than assume one.

    Token-gated upstream like every scoped route: without X-TrueSync-Key
    it answers 403. That is what the proxy is for.
    """
    return _unwrap(*await _client(scope).verify_listing(listing_id))


@router.post("/truesync/listings/{listing_id}/verify-acp")
async def verify_listing_acp(listing_id: int, scope: CustomerScope = Depends(customer_scope)):
    """
    Fetch this listing's ACP feed from its serving URL and record what it
    served. Same shape of answer as /verify — {outcome, integrity, findings}
    — but against the `acp` channel, so the ACP cell gets its own badge
    rather than borrowing schema.org's.

    Token-gated upstream like the other verify routes; that is what the
    proxy is for.
    """
    return _unwrap(*await _client(scope).verify_listing_acp(listing_id))


@router.post("/truesync/verify-all")
async def verify_all(scope: CustomerScope = Depends(customer_scope)):
    """Verify every active listing of the active demo merchant."""
    return _unwrap(*await _client(scope).verify_all())


@router.post("/truesync/gmc/diagnostics/refresh")
async def refresh_gmc_diagnostics(
    listing_id: Optional[int] = None,
    scope: CustomerScope = Depends(customer_scope),
):
    """
    Ask TrueSync to read Merchant Center product statuses back and
    record them. Omitting listing_id refreshes every listing — which is
    what the header button does.
    """
    return _unwrap(*await _client(scope).refresh_gmc_diagnostics(listing_id))


@router.put("/truesync/sync-rules")
async def put_sync_rule(body: SyncRuleProxyRequest, scope: CustomerScope = Depends(customer_scope)):
    """
    Turn one channel on or off for one catalog product. Note the key:
    the upstream sync-rule API is addressed by catalog_product_id, not
    the listing_id everything else on this page uses — the page reads
    the mapping off GET /api/truesync/listings/{id}.
    """
    return _unwrap(
        *await _client(scope).put_sync_rule(
            body.catalog_product_id, body.channel_slug, body.enabled, body.cadence
        )
    )


# ─── Step 1C: the tenant, bulk verifications, the SKU feed ──────────────
#
# The setup wizard's reads and writes and the Command Center's bulk
# verification load. Same allow-list discipline: each is one named upstream
# call under the selected customer's token, nothing generic.

@router.get("/truesync/tenant")
async def get_tenant(scope: CustomerScope = Depends(customer_scope)):
    return _unwrap(*await _client(scope).get_tenant())


@router.get("/truesync/merchants/{merchant_slug}/verifications")
async def get_merchant_verifications(
    merchant_slug: str,
    channel: Optional[str] = None,
    method: Optional[str] = None,
    since: Optional[str] = None,
    limit: Optional[int] = None,
    scope: CustomerScope = Depends(customer_scope),
):
    """
    Every listing's verification history in one call (supply 1B). Replaces
    the per-listing x per-channel sweep: one Vercel invocation per channel
    instead of one per cell.
    """
    return _unwrap(*await _client(scope).get_merchant_verifications(
        merchant_slug, channel=channel, method=method, since=since, limit=limit,
    ))


class RetailerListRequest(BaseModel):
    domains: List[str]


@router.get("/truesync/merchants/{merchant_slug}/retailers")
async def get_retailers(merchant_slug: str, scope: CustomerScope = Depends(customer_scope)):
    return _unwrap(*await _client(scope).get_retailers(merchant_slug))


@router.put("/truesync/merchants/{merchant_slug}/retailers")
async def put_retailers(
    merchant_slug: str,
    body: RetailerListRequest,
    scope: CustomerScope = Depends(customer_scope),
):
    return _unwrap(*await _client(scope).put_retailers(merchant_slug, body.domains))


#: Vercel refuses a request body over 4.5 MB before this code runs, which is
#: under supply's own 5 MB cap. Said here, in words, for the upload that
#: gets as far as this function and is still too big for the upstream.
MAX_FEED_UPLOAD_BYTES = 4_500_000


@router.post("/truesync/merchants/{merchant_slug}/feed/validate")
async def validate_feed(
    merchant_slug: str,
    files: List[UploadFile] = File(...),
    skip_reachability: bool = Query(False),
    scope: CustomerScope = Depends(customer_scope),
):
    """
    The feed upload, passed through as multipart to supply's validate. Writes
    no record upstream; returns the preview (rows, statuses, messages,
    summary) and the upload_id commit takes.
    """
    parts, total = [], 0
    for upload in files:
        body = await upload.read()
        total += len(body)
        parts.append(("files", (upload.filename or "upload", body,
                                upload.content_type or "application/octet-stream")))
    if total > MAX_FEED_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"the upload is {total:,} bytes; the limit here is {MAX_FEED_UPLOAD_BYTES:,}",
        )
    return _unwrap(*await _client(scope).validate_feed(merchant_slug, parts, skip_reachability))


class FeedCommitRequest(BaseModel):
    upload_id: str
    mode: str


@router.post("/truesync/merchants/{merchant_slug}/feed/commit")
async def commit_feed(
    merchant_slug: str,
    body: FeedCommitRequest,
    scope: CustomerScope = Depends(customer_scope),
):
    return _unwrap(*await _client(scope).commit_feed(merchant_slug, body.upload_id, body.mode))


@router.get("/truesync/merchants/{merchant_slug}/feed")
async def get_feed(merchant_slug: str, scope: CustomerScope = Depends(customer_scope)):
    return _unwrap(*await _client(scope).get_feed(merchant_slug))


@router.get("/truesync/merchants/{merchant_slug}/feed/history")
async def get_feed_history(merchant_slug: str, scope: CustomerScope = Depends(customer_scope)):
    return _unwrap(*await _client(scope).get_feed_history(merchant_slug))


class OwnedIncentivesRequest(BaseModel):
    incentives: List[dict]


@router.get("/truesync/merchants/{merchant_slug}/incentives/owned")
async def get_owned_incentives(merchant_slug: str, scope: CustomerScope = Depends(customer_scope)):
    return _unwrap(*await _client(scope).get_owned_incentives(merchant_slug))


@router.put("/truesync/merchants/{merchant_slug}/incentives/owned")
async def put_owned_incentives(
    merchant_slug: str,
    body: OwnedIncentivesRequest,
    scope: CustomerScope = Depends(customer_scope),
):
    return _unwrap(*await _client(scope).put_owned_incentives(merchant_slug, body.incentives))


_TEMPLATE_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@router.get("/truesync/feed/template.{ext}")
async def get_feed_template(ext: str):
    """
    1B's SKU-feed template, proxied. Public upstream (invented data), so
    no customer is needed and no token is sent — only this app's own login.
    """
    if ext not in _TEMPLATE_TYPES:
        raise HTTPException(status_code=404, detail="no such template")
    status, response, error = await TrueSyncClient(token="").get_template(ext)
    if error is not None:
        raise HTTPException(status_code=status or 502, detail=error)
    return Response(
        content=response.content,
        media_type=_TEMPLATE_TYPES[ext],
        headers={"Content-Disposition": f'attachment; filename="sku-feed-template.{ext}"'},
    )
