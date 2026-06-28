"""
Scope-authoring API — lets a user designate specific SKUs (a catalog
product at a specific retailer) as the measurement scope for a brand, and
manage how a cycle's scope relates to that brand-level template.

Two kinds of soa_scope_skus rows (see soa_shared/scope_resolution.py):
  - ENTITY TEMPLATE rows: entity_id set, cycle_id NULL. The brand's living,
    editable measured-SKU set.
  - CYCLE SNAPSHOT rows: cycle_id set, entity_id set. A copy of the
    templates captured for a specific cycle (inherited live while Planned,
    or materialized/frozen — see scope_resolution.get_effective_scope).

Uses DealEngineClient (mirrored from apps/pipeline/clients/ — see that
file's header) to browse and resolve catalog listings on the supply app's
Deal Engine. Catalog-Engine-reference columns are stored BY VALUE, the
same pattern as soa_shared/models/merchant_ref.py — no cross-DB FK.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from soa_shared.database import engine, session_factory
from soa_shared.models.soa_models import SoaCycle, SoaScopeSku
from soa_shared.scope_resolution import (
    add_scope_sku_to_cycle,
    get_effective_scope,
    remove_scope_sku_from_cycle,
)
from app.auth import get_current_user
from app.schemas import (
    CreateScopeSkuRequest,
    CycleScopeResponse,
    ScopeSkuResponse,
    ScopeTiersResponse,
    TierOption,
)
from clients.deal_engine_client import DealEngineClient

router = APIRouter()


def _run_async(coro):
    """Sync routers call into the async DealEngineClient via a fresh loop."""
    return asyncio.run(coro)


def _get_cycle_org_id(cycle_id: int) -> Optional[int]:
    """Returns the owning organization_id for a cycle, or None if it doesn't exist."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT organization_id FROM soa_cycles WHERE id = :id"),
            {"id": cycle_id},
        ).fetchone()
    return row[0] if row else None


def _auto_link_entity_id(brand: Optional[str]) -> Optional[int]:
    """
    Matches brand by case-insensitive name against soa_entities. Returns
    None (leaves entity_id null) if brand is missing or no entity matches —
    never raises, this is a best-effort convenience link.
    """
    if not brand:
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM soa_entities WHERE LOWER(name) = LOWER(:brand) LIMIT 1"),
            {"brand": brand},
        ).fetchone()
    return row[0] if row else None


def _row_to_scope_sku(row: SoaScopeSku) -> ScopeSkuResponse:
    return ScopeSkuResponse(
        id=row.id,
        cycle_id=row.cycle_id,
        entity_id=row.entity_id,
        role=row.role,
        dealengine_listing_id=row.dealengine_listing_id,
        dealengine_catalog_product_id=row.dealengine_catalog_product_id,
        merchant_slug=row.merchant_slug,
        merchant_sku=row.merchant_sku,
        brand=row.brand,
        category=row.category,
        product_url=row.product_url,
        listed_price=float(row.listed_price) if row.listed_price is not None else None,
        currency=row.currency,
        display_name=row.display_name,
        is_active=row.is_active,
        created_at=str(row.created_at)[:19] if row.created_at else None,
        updated_at=str(row.updated_at)[:19] if row.updated_at else None,
    )


async def _resolve_listing_fields(data: CreateScopeSkuRequest) -> dict:
    """
    Resolves the picked-listing-or-product-url request into the by-value
    fields to persist. Path A (listing_id present) persists directly from
    the payload. Path B calls resolve_listing() on the Deal Engine.
    """
    if data.listing_id is not None:
        return dict(
            dealengine_listing_id=data.listing_id,
            dealengine_catalog_product_id=data.catalog_product_id,
            merchant_slug=data.merchant_slug,
            merchant_sku=data.merchant_sku,
            brand=data.brand,
            category=data.category,
            product_url=data.product_url,
            listed_price=data.listed_price,
            currency=data.currency,
            display_name=data.display_name,
        )

    client = DealEngineClient()
    result = await client.resolve_listing(data.product_url, user_tier_name=data.user_tier_name)
    if not result.available or result.listing is None:
        raise HTTPException(
            status_code=502,
            detail=f"Could not resolve product_url via the Deal Engine: {result.error}",
        )
    listing = result.listing
    return dict(
        dealengine_listing_id=listing.get("listing_id"),
        dealengine_catalog_product_id=listing.get("catalog_product_id"),
        merchant_slug=listing.get("merchant_slug"),
        merchant_sku=listing.get("merchant_sku"),
        brand=listing.get("brand"),
        category=listing.get("category"),
        product_url=listing.get("product_url") or data.product_url,
        listed_price=listing.get("listed_price"),
        currency=listing.get("currency"),
        display_name=listing.get("name"),
    )


@router.get("/scope/catalog/search")
def search_catalog(
    q: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    merchant_slug: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """
    Proxies the Deal Engine's GET /api/catalog/listings so the frontend can
    browse the catalog when adding scope SKUs. Returns the raw listing
    dicts — not modeled strictly here since this app does not own that
    schema (see DealEngineClient.search_catalog).
    """
    client = DealEngineClient()
    result = _run_async(client.search_catalog(
        q=q, brand=brand, category=category, merchant_slug=merchant_slug,
    ))
    if not result.available:
        raise HTTPException(
            status_code=503,
            detail=f"Deal Engine catalog search unavailable: {result.error}",
        )
    return {"listings": result.listings}


@router.get("/scope/tiers", response_model=ScopeTiersResponse)
def get_scope_tiers(
    current_user: dict = Depends(get_current_user),
):
    """
    Proxies the Deal Engine's GET /api/merchants/programs to list every
    loyalty tier name across all merchants, for the truecost-sweep wizard's
    tier multi-select. Always prepends a "Non-member (baseline)" option
    (value=None) — every truecost cycle implicitly sweeps the baseline.

    Tier names are deduped and sorted; a tier may appear at multiple
    merchants (the underlying value is just the tier's display name, which
    is matched case-insensitively against the Deal Engine's tier.name — see
    deal_engine/loyalty_eligibility.py).
    """
    client = DealEngineClient()
    result = _run_async(client.merchant_programs())
    if not result.available:
        raise HTTPException(
            status_code=503,
            detail=f"Deal Engine unavailable: {result.error}",
        )

    names = set()
    for merchant in result.merchants:
        for program in merchant.get("programs") or []:
            for tier in program.get("tiers") or []:
                name = tier.get("name")
                if name:
                    names.add(name)

    tiers = [TierOption(value=None, label="Non-member (baseline)")]
    tiers += [TierOption(value=name, label=name) for name in sorted(names)]
    return ScopeTiersResponse(tiers=tiers)


# ─────────────────────────────────────────────────────────────────────────────
# Entity template endpoints — the brand's living, editable measured-SKU set.
# entity_id set, cycle_id NULL.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/entities/{entity_id}/scope-skus", response_model=list[ScopeSkuResponse])
def list_entity_scope_skus(
    entity_id: int,
    current_user: dict = Depends(get_current_user),
):
    with session_factory() as session:
        rows = (
            session.query(SoaScopeSku)
            .filter_by(entity_id=entity_id, cycle_id=None, is_active=True)
            .order_by(SoaScopeSku.id)
            .all()
        )
        return [_row_to_scope_sku(r) for r in rows]


@router.post("/entities/{entity_id}/scope-skus", response_model=ScopeSkuResponse, status_code=201)
def create_entity_scope_sku(
    entity_id: int,
    data: CreateScopeSkuRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Adds a SKU to a brand's measured-SKU template — independent of any
    cycle. Picked-listing or product_url, same as the cycle-scoped
    endpoint below. entity_id always comes from the path, never the body.
    """
    fields = _run_async(_resolve_listing_fields(data))

    with session_factory() as session:
        row = SoaScopeSku(
            entity_id=entity_id,
            cycle_id=None,
            role=data.role,
            is_active=True,
            **fields,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _row_to_scope_sku(row)


@router.delete("/scope-skus/{scope_sku_id}", status_code=200)
def delete_scope_sku(
    scope_sku_id: int,
    current_user: dict = Depends(get_current_user),
):
    """
    Soft-deletes (is_active = FALSE) a scope SKU by id — an entity
    template row (cycle_id NULL) or a cycle snapshot row. 404 if it
    doesn't exist or its cycle belongs to a different organization.
    Template rows (and cycle-less rows) have no organization to check
    against and are deletable by any authenticated user.
    """
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT ss.id, c.organization_id
            FROM soa_scope_skus ss
            LEFT JOIN soa_cycles c ON c.id = ss.cycle_id
            WHERE ss.id = :id
        """), {"id": scope_sku_id}).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail=f"Scope SKU {scope_sku_id} not found")

        _id, cycle_org_id = row
        if cycle_org_id is not None and cycle_org_id != current_user["organization_id"]:
            raise HTTPException(status_code=404, detail=f"Scope SKU {scope_sku_id} not found")

        conn.execute(text("""
            UPDATE soa_scope_skus
            SET is_active = FALSE, updated_at = NOW()
            WHERE id = :id
        """), {"id": scope_sku_id})
        conn.commit()

    return {"id": scope_sku_id, "deleted": True}


# ─────────────────────────────────────────────────────────────────────────────
# Cycle scope — read returns the resolved effective scope (frozen / custom /
# inherited / materialized); write operates on cycle snapshot rows and
# always goes through scope_resolution's materialize-on-first-edit helpers.
# ─────────────────────────────────────────────────────────────────────────────

def _load_cycle_for_org(session, cycle_id: int, org_id: int) -> SoaCycle:
    cycle = session.get(SoaCycle, cycle_id)
    if cycle is None or cycle.organization_id != org_id:
        raise HTTPException(status_code=404, detail=f"Cycle {cycle_id} not found")
    return cycle


@router.get("/cycles/{cycle_id}/scope-skus", response_model=CycleScopeResponse)
def get_cycle_scope(
    cycle_id: int,
    current_user: dict = Depends(get_current_user),
):
    with session_factory() as session:
        cycle = _load_cycle_for_org(session, cycle_id, current_user["organization_id"])
        effective = get_effective_scope(cycle, session)
        return CycleScopeResponse(
            cycle_id=cycle_id,
            source=effective.source,
            is_editable=effective.is_editable,
            skus=[_row_to_scope_sku(r) for r in effective.skus],
        )


@router.post("/cycles/{cycle_id}/scope-skus", response_model=ScopeSkuResponse, status_code=201)
def create_cycle_scope_sku(
    cycle_id: int,
    data: CreateScopeSkuRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Adds a SKU to this cycle's scope specifically. If the cycle was still
    inheriting live from entity templates (or materialized-but-not-custom),
    this is the cycle's first scope edit: the current effective scope is
    materialized into cycle rows and scope_is_custom is set, before the new
    row is added. 409 if the scope is already frozen — to change a frozen
    cycle's scope, clone into a new cycle.
    """
    with session_factory() as session:
        cycle = _load_cycle_for_org(session, cycle_id, current_user["organization_id"])
        if cycle.scope_frozen_at is not None:
            raise HTTPException(
                status_code=409,
                detail="This cycle's scope is frozen. Clone into a new cycle to change it.",
            )

        fields = _run_async(_resolve_listing_fields(data))
        entity_id = data.entity_id
        if entity_id is None:
            entity_id = _auto_link_entity_id(fields.get("brand"))

        row = add_scope_sku_to_cycle(
            cycle, session,
            entity_id=entity_id, role=data.role, is_active=True, **fields,
        )
        session.commit()
        session.refresh(row)
        return _row_to_scope_sku(row)


@router.delete("/cycles/{cycle_id}/scope-skus/{scope_sku_id}", status_code=200)
def delete_cycle_scope_sku(
    cycle_id: int,
    scope_sku_id: int,
    current_user: dict = Depends(get_current_user),
):
    """
    Removes a SKU from this cycle's scope. scope_sku_id may be the id of
    an already-materialized cycle row, or — if the cycle is still
    inheriting live — the id of the template row the UI is currently
    displaying; see scope_resolution.remove_scope_sku_from_cycle for how
    that's resolved without mutating the template. 409 if the scope is
    already frozen.
    """
    with session_factory() as session:
        cycle = _load_cycle_for_org(session, cycle_id, current_user["organization_id"])
        if cycle.scope_frozen_at is not None:
            raise HTTPException(
                status_code=409,
                detail="This cycle's scope is frozen. Clone into a new cycle to change it.",
            )

        removed = remove_scope_sku_from_cycle(cycle, session, scope_sku_id)
        session.commit()

        if removed is None:
            raise HTTPException(
                status_code=404,
                detail=f"Scope SKU {scope_sku_id} not found in cycle {cycle_id}'s scope",
            )

    return {"id": removed.id, "deleted": True}
