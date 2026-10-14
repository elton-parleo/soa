"""
2C: the console's operator section, under /api/console/.

What the soa web app's operator screens do, for the console: the SKU-feed
loader (Setup > Catalog) and, in step 4, the study generator. Every route
is operator-only (a member is 403, worded so) and scoped to one tenant by
app/console_scope.py, so an operator names the org with ?org=. Supply is
called with that org's tenant token, server-side, as app/routers/truesync.py
does for the web app.

    GET  /api/console/catalog?merchant=<slug>          the merchant's record: feed version + rows, or the hosted catalog
    GET  /api/console/catalog/versions?merchant=<slug> every feed version, newest first
    GET  /api/console/catalog/template.{csv|xlsx}      the SKU-feed template
    POST /api/console/catalog/validate?merchant=<slug> validate + preview (multipart), with the 2A-1 multipack warning
    POST /api/console/catalog/commit                   commit a validated upload as the new version
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict

from app.auth import verify_token
from app.console_scope import console_scope
from app.customer_context import CustomerScope
from app.routers import full_loop
from app.routers.customers import _tenant_view
from app.routers.truesync import MAX_FEED_UPLOAD_BYTES, _unwrap, get_feed_template
from app.services import console_read_models as rm
from soa_shared import customers

router = APIRouter(prefix="/console", tags=["console-operator"])

OPERATOR_ONLY = "operator only: this console screen is for Parleo staff"


def operator_scope(scope: CustomerScope = Depends(console_scope),
                   user: dict = Depends(verify_token)) -> CustomerScope:
    if not customers.is_operator(user.get("sub")):
        raise HTTPException(status_code=403, detail=OPERATOR_ONLY)
    return scope


# ─── Setup > Catalog: supply's 1B feed loader ──────────────────────────────

@router.get("/catalog")
async def get_catalog(merchant: str = Query(...), scope: CustomerScope = Depends(operator_scope)):
    """The merchant's record as the Catalog screen shows it. Which kind of
    merchant comes from the tenant's record (supply's /tenant, as /me reads
    it). Parleo-hosted: the catalog as published from the store config,
    read-only (supply refuses a feed for it). External: its current feed
    version and rows, and every version; no feed yet (supply's 404) is an
    empty record here, not an error."""
    view = await _tenant_view(scope.org)
    record = next((m for m in view.get('merchants') or [] if m.get('slug') == merchant), None)
    if record is None and view.get('error') is None:
        raise HTTPException(status_code=404, detail=f"merchant {merchant!r} not found")
    client = full_loop._client(scope)
    if (record or {}).get('hosting') == 'parleo':
        catalog = _unwrap(*await client.get_merchant_catalog(merchant))
        return rm.build_catalog(merchant, feed=None, history=[], hosted_catalog=catalog or {})
    status, feed, error = await client.get_feed(merchant)
    if error is not None and status != 404:
        _unwrap(status, feed, error)
    history = _unwrap(*await client.get_feed_history(merchant))
    return rm.build_catalog(merchant, feed=feed if error is None else None,
                            history=(history or {}).get('versions') or [], hosted_catalog=None)


@router.get("/catalog/versions")
async def get_catalog_versions(merchant: str = Query(...), scope: CustomerScope = Depends(operator_scope)):
    body = _unwrap(*await full_loop._client(scope).get_feed_history(merchant))
    return {'merchant': body.get('merchant') or merchant, 'versions': body.get('versions') or []}


@router.get("/catalog/template.{ext}")
async def get_catalog_template(ext: str, scope: CustomerScope = Depends(operator_scope)):
    return await get_feed_template(ext)


@router.post("/catalog/validate")
async def validate_catalog(
    merchant: str = Query(...),
    files: List[UploadFile] = File(...),
    skip_reachability: bool = Query(False),
    scope: CustomerScope = Depends(operator_scope),
):
    """supply's validate (which is the preview: every row ready / warning /
    error with its reasons, staged under upload_id), then the 2A-1 warning
    supply's validate cannot raise because it has not read the pages: a
    row whose page showed a count that only a multipack explains, while
    the row's multipack is empty. That warning is advisory and shown here
    only; what commit writes is supply's staged preview."""
    parts, total = [], 0
    for upload in files:
        body = await upload.read()
        total += len(body)
        parts.append(("files", (upload.filename or "upload", body, upload.content_type or "application/octet-stream")))
    if total > MAX_FEED_UPLOAD_BYTES:
        raise HTTPException(status_code=413,
                            detail=f"the upload is {total:,} bytes; the limit here is {MAX_FEED_UPLOAD_BYTES:,}")
    client = full_loop._client(scope)
    preview = _unwrap(*await client.validate_feed(merchant, parts, skip_reachability))
    r_status, reference, r_error = await client.get_reference(merchant)
    return rm.annotate_feed_preview(preview, reference if r_error is None else None,
                                    reference_error=r_error)


class CatalogCommit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant: str
    upload_id: str
    mode: str = "all_valid_rows"


@router.post("/catalog/commit")
async def commit_catalog(body: CatalogCommit, scope: CustomerScope = Depends(operator_scope)):
    if body.mode not in ("all_valid_rows", "require_clean"):
        raise HTTPException(status_code=422, detail="mode is all_valid_rows or require_clean")
    return _unwrap(*await full_loop._client(scope).commit_feed(body.merchant, body.upload_id, body.mode))
