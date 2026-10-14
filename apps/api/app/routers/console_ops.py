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
    GET  /api/console/studies/options                   what the Create Study modal offers (constraints, surfaces, merchants)
    POST /api/console/studies/preview                   the catalog tiers the generator will build, question by question
    POST /api/console/studies/generate                  queue the study (the existing generation job), 100-question cap enforced
    POST /api/console/studies/{study_type}/regenerate   rebuild a grounded study's catalog tiers from the record as it is now
    GET  /api/console/studies/{study_type}/status       generation status and provenance
    POST /api/console/cycles                            start a cycle of a study on surfaces from /api/console/surfaces
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict

from app.auth import verify_token
from app.console_scope import console_scope
from app.customer_context import CustomerScope
from app.routers import full_loop
from app.routers.customers import _tenant_view
from app.routers.truesync import MAX_FEED_UPLOAD_BYTES, _unwrap, get_feed_template
from app.routers import cycles as cycles_router
from app.routers import studies as studies_router
from app.schemas import ComparisonEntityInput, CreateCycleRequest, RegenerateStudyRequest, StudyGenerateRequest
from app.services import console_read_models as rm
from app.services import console_studies as cs
from soa_shared import customers, surfaces
from soa_shared.constants import QUERY_CONSTRAINTS
from soa_shared.database import engine
from sqlalchemy import text

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


# ─── Studies & Audits: the study generator (2C step 4) ────────────────────

def _as_user(user: dict) -> dict:
    """The current_user the web app's study and cycle routes take: its own
    org (the operator's staff org, which is what owns the job and its
    queries, as when the web app's modal creates one) and user id."""
    user_id = user.get("sub")
    org_id = user.get("organization_id")
    if org_id is None:
        with engine.connect() as conn:
            org_id = conn.execute(text(
                "SELECT organization_id FROM organization_members WHERE user_id = :u ORDER BY id LIMIT 1"),
                {"u": user_id}).scalar()
    return {"user_id": user_id, "organization_id": org_id, "sub": user_id, "email": user.get("email")}


@router.get("/studies/options")
async def get_study_options(scope: CustomerScope = Depends(operator_scope)):
    """Everything the Create Study modal reads before the first keystroke:
    the soa_queries constraints, the surface list (with the two not
    available entries), the scope's merchants (a merchant with no
    published record is listed and cannot be chosen), and the limits."""
    view = await _tenant_view(scope.org)
    return {
        "constraints": {k: list(v) for k, v in QUERY_CONSTRAINTS.items()},
        "surfaces": surfaces.modal_list(),
        "merchants": view.get("merchants") or [],
        "merchants_error": view.get("error"),
        "max_questions": cs.MAX_QUESTIONS,
        "default_brand_direct_count": cs.ct.DEFAULT_BRAND_DIRECT_COUNT,
        "default_variant_cap": cs.ct.DEFAULT_VARIANT_CAP,
    }


class StudyPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant: str
    tiers: Dict[str, bool] = {}
    stage_total: int = 0
    brand_direct_count: Optional[int] = None
    variant_cap: Optional[int] = None
    allowed_categories: Optional[List[str]] = None
    personas: Optional[List[str]] = None
    study_pattern: Optional[str] = None


@router.post("/studies/preview")
async def preview_study(body: StudyPreviewRequest, scope: CustomerScope = Depends(operator_scope)):
    """The catalog-built tiers exactly as the generation worker will build
    them (soa_shared/catalog_tiers.py, the same module), from the record
    as it is now: every question with its typed expectation, the sample
    when the variant cap bites, the per-tier counts, the expected nulls,
    and the tally against the 100-question cap. Brand-direct is counted
    and shown with one illustrative example: a model writes its wording at
    generation time."""
    snapshot = await cs.read_snapshot(full_loop._client(scope), body.merchant)
    return cs.build_preview(snapshot, tiers=body.tiers, stage_total=body.stage_total,
                            brand_direct_count=body.brand_direct_count, variant_cap=body.variant_cap,
                            allowed_categories=body.allowed_categories, personas=body.personas,
                            study_pattern=body.study_pattern)


class ConsoleStudyGenerate(StudyGenerateRequest):
    """POST /api/studies/generate's body, plus the tiers as the modal holds
    them. The syndicated merchant's customer is the console's scope."""
    tiers: Optional[Dict[str, bool]] = None
    brand_direct_count: Optional[int] = None


@router.post("/studies/generate", status_code=201)
async def generate_console_study(body: ConsoleStudyGenerate, scope: CustomerScope = Depends(operator_scope),
                                 user: dict = Depends(verify_token)):
    """Queues the study through the web app's own route (the generation
    job the worker runs, brand-catalog mode included). Before that, the
    grand total, stage questions plus the catalog tiers the record will
    produce, is checked against the 100 cap here, server-side, not only
    in the modal."""
    data = body.model_dump(exclude={"tiers", "brand_direct_count"})
    preview = None
    if body.syndicated_merchant:
        tiers = body.tiers if body.tiers is not None else {
            k: bool((body.tier_config or {}).get(k, {}).get("enabled")) for k in cs.TIER_KEYS}
        snapshot = await cs.read_snapshot(full_loop._client(scope), body.syndicated_merchant)
        preview = cs.build_preview(snapshot, tiers=tiers, stage_total=body.target_count,
                                   brand_direct_count=body.brand_direct_count)
        if preview["tally"]["total"] > cs.MAX_QUESTIONS:
            raise HTTPException(status_code=422, detail=preview["tally"]["text"])
        data["tier_config"] = cs.tier_config(tiers, body.brand_direct_count)
        data["customer_org_id"] = scope.org.id
    result = studies_router.generate_study(StudyGenerateRequest(**data), current_user=_as_user(user))
    return {**result.model_dump(), "tally": (preview or {}).get("tally")}


@router.post("/studies/{study_type}/regenerate", status_code=202)
async def regenerate_console_study(study_type: str, body: RegenerateStudyRequest,
                                   scope: CustomerScope = Depends(operator_scope),
                                   user: dict = Depends(verify_token)):
    return studies_router.regenerate_study(study_type, body, current_user=_as_user(user))


@router.get("/studies/{study_type}/status")
async def get_console_study_status(study_type: str, scope: CustomerScope = Depends(operator_scope),
                                   user: dict = Depends(verify_token)):
    return studies_router.get_generation_status(study_type, current_user=_as_user(user))


class ConsoleCycleStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_type: str
    platforms: List[str]
    runs_per_query: int = 1
    cycle_code: Optional[str] = None
    notes: Optional[str] = None


@router.post("/cycles", status_code=201)
async def start_console_cycle(body: ConsoleCycleStart, scope: CustomerScope = Depends(operator_scope),
                              user: dict = Depends(verify_token)):
    """Starts a cycle of one of the scope's studies on surfaces from
    /api/console/surfaces, through the web app's own create_cycle. A
    surface that cannot run here is refused before anything is written.
    The comparison set is the study's last cycle's, else its brand as the
    primary entity."""
    if not 1 <= body.runs_per_query <= 10:
        raise HTTPException(status_code=422, detail="runs_per_query is 1 to 10")
    refused = [f"{p}: {surfaces.unavailable_reason(p)}" for p in body.platforms if surfaces.unavailable_reason(p)]
    if refused:
        raise HTTPException(status_code=422, detail="surface cannot run: " + "; ".join(refused))
    comparison = cs.comparison_set_for(body.study_type, scope.org.id)
    if not comparison:
        raise HTTPException(status_code=422, detail=(
            f"study {body.study_type!r} is not this customer's, or has no entity to measure; "
            "create its first cycle in Command Center"))
    code = body.cycle_code or f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{body.study_type}"
    request = CreateCycleRequest(cycle_code=code, study_type=body.study_type, platforms=body.platforms,
                                 runs_per_query=body.runs_per_query, notes=body.notes,
                                 comparison_set=[ComparisonEntityInput(**c) for c in comparison])
    return cycles_router.create_cycle(request, current_user=_as_user(user)).model_dump()
