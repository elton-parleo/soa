"""
Scope-authoring API — lets a user designate specific SKUs (a catalog
product at a specific retailer) as the measurement scope for a cycle.

Additive: a brand-anchored cycle with no scope SKUs is completely
unaffected by this router. soa_scope_skus rows are optional and nest
under entities (entity_id may be null).

Uses DealEngineClient (mirrored from apps/pipeline/clients/ — see that
file's header) to browse and resolve catalog listings on the supply app's
Deal Engine. Catalog-Engine-reference columns are stored BY VALUE, the
same pattern as soa_shared/models/merchant_ref.py — no cross-DB FK.
"""
import asyncio
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from soa_shared.database import engine
from app.auth import get_current_user
from app.schemas import CreateScopeSkuRequest, ScopeSkuResponse
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


def _row_to_scope_sku(row) -> ScopeSkuResponse:
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


@router.post("/cycles/{cycle_id}/scope-skus", response_model=ScopeSkuResponse, status_code=201)
def create_scope_sku(
    cycle_id: int,
    data: CreateScopeSkuRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Creates a soa_scope_skus row for this cycle. Two input shapes:

      Path A — a picked listing: listing_id + the CatalogListing fields the
      frontend already has from /scope/catalog/search. No Deal Engine call
      needed; persists directly from the payload (works even if the Deal
      Engine is unreachable at write time).

      Path B — { product_url, entity_id, role }: calls resolve_listing()
      first (registers the SKU on the Deal Engine side), then persists the
      returned listing fields. Raises 502 if the Deal Engine is unreachable
      — there is no listing_id to fall back to.
    """
    org_id = _get_cycle_org_id(cycle_id)
    if org_id is None:
        raise HTTPException(status_code=404, detail=f"Cycle {cycle_id} not found")
    if org_id != current_user["organization_id"]:
        raise HTTPException(status_code=404, detail=f"Cycle {cycle_id} not found")

    if data.listing_id is not None:
        # Path A — picked listing, persist from the payload directly.
        listing_id = data.listing_id
        catalog_product_id = data.catalog_product_id
        merchant_slug = data.merchant_slug
        merchant_sku = data.merchant_sku
        brand = data.brand
        category = data.category
        product_url = data.product_url
        listed_price = data.listed_price
        currency = data.currency
        display_name = data.display_name
    else:
        # Path B — resolve from a bare product URL via the Deal Engine.
        client = DealEngineClient()
        result = _run_async(client.resolve_listing(
            data.product_url, user_tier_name=data.user_tier_name,
        ))
        if not result.available or result.listing is None:
            raise HTTPException(
                status_code=502,
                detail=f"Could not resolve product_url via the Deal Engine: {result.error}",
            )
        listing = result.listing
        listing_id = listing.get("listing_id")
        catalog_product_id = listing.get("catalog_product_id")
        merchant_slug = listing.get("merchant_slug")
        merchant_sku = listing.get("merchant_sku")
        brand = listing.get("brand")
        category = listing.get("category")
        product_url = listing.get("product_url") or data.product_url
        listed_price = listing.get("listed_price")
        currency = listing.get("currency")
        display_name = listing.get("name")

    entity_id = data.entity_id
    if entity_id is None:
        entity_id = _auto_link_entity_id(brand)

    with engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO soa_scope_skus (
                cycle_id, entity_id, role,
                dealengine_listing_id, dealengine_catalog_product_id,
                merchant_slug, merchant_sku, brand, category, product_url,
                listed_price, currency, display_name, is_active
            ) VALUES (
                :cycle_id, :entity_id, :role,
                :listing_id, :catalog_product_id,
                :merchant_slug, :merchant_sku, :brand, :category, :product_url,
                :listed_price, :currency, :display_name, TRUE
            )
            RETURNING
                id, cycle_id, entity_id, role,
                dealengine_listing_id, dealengine_catalog_product_id,
                merchant_slug, merchant_sku, brand, category, product_url,
                listed_price, currency, display_name, is_active,
                created_at, updated_at
        """), {
            "cycle_id": cycle_id,
            "entity_id": entity_id,
            "role": data.role,
            "listing_id": listing_id,
            "catalog_product_id": catalog_product_id,
            "merchant_slug": merchant_slug,
            "merchant_sku": merchant_sku,
            "brand": brand,
            "category": category,
            "product_url": product_url,
            "listed_price": listed_price,
            "currency": currency,
            "display_name": display_name,
        }).fetchone()

    return _row_to_scope_sku(row)


@router.get("/cycles/{cycle_id}/scope-skus", response_model=list[ScopeSkuResponse])
def list_scope_skus(
    cycle_id: int,
    current_user: dict = Depends(get_current_user),
):
    org_id = _get_cycle_org_id(cycle_id)
    if org_id is None:
        raise HTTPException(status_code=404, detail=f"Cycle {cycle_id} not found")
    if org_id != current_user["organization_id"]:
        raise HTTPException(status_code=404, detail=f"Cycle {cycle_id} not found")

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                id, cycle_id, entity_id, role,
                dealengine_listing_id, dealengine_catalog_product_id,
                merchant_slug, merchant_sku, brand, category, product_url,
                listed_price, currency, display_name, is_active,
                created_at, updated_at
            FROM soa_scope_skus
            WHERE cycle_id = :cycle_id AND is_active = TRUE
            ORDER BY id
        """), {"cycle_id": cycle_id}).fetchall()

    return [_row_to_scope_sku(r) for r in rows]


@router.delete("/scope-skus/{scope_sku_id}", status_code=200)
def delete_scope_sku(
    scope_sku_id: int,
    current_user: dict = Depends(get_current_user),
):
    """
    Soft-deletes (is_active = FALSE) a scope SKU. 404 if it doesn't exist
    or its cycle belongs to a different organization. Scope SKUs with no
    cycle_id yet (authored but not attached) have no organization to check
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
