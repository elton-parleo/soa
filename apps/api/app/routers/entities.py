from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import text
from soa_shared.database import engine
from app.schemas import (
    EntityResponse,
    CreateEntityRequest,
    EntityUpdateRequest,
    ENTITY_TYPE_DISPLAY,
    ENTITY_TYPE_INTERNAL,
)
import re

router = APIRouter()


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"['\(\)]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def unique_slug(conn, base_slug: str) -> str:
    slug = base_slug
    n = 2
    while True:
        row = conn.execute(text("""
            SELECT 1 FROM soa_entities WHERE slug = :s
        """), {"s": slug}).fetchone()
        if not row:
            return slug
        slug = f"{base_slug}-{n}"
        n += 1


@router.get("/entities", response_model=list[EntityResponse])
def get_entities(
    category: str = Query(None),
    type:     str = Query(None),
    search:   str = Query(None),
):
    sql = """
        SELECT id, name, slug, entity_type, category
        FROM soa_entities
        WHERE 1=1
    """
    params = {}

    if category:
        sql += " AND LOWER(category) = LOWER(:cat)"
        params["cat"] = category

    if type:
        internal = ENTITY_TYPE_INTERNAL.get(type, type.lower())
        sql += " AND entity_type = :et"
        params["et"] = internal

    if search:
        sql += " AND LOWER(name) LIKE :s"
        params["s"] = f"%{search.lower()}%"

    sql += " ORDER BY name"

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()

    return [
        EntityResponse(
            id=r[0],
            name=r[1],
            slug=r[2],
            type=ENTITY_TYPE_DISPLAY.get(r[3], r[3].title()),
            category=r[4] or "",
        )
        for r in rows
    ]


@router.post("/entities", response_model=EntityResponse, status_code=201)
def create_entity(data: CreateEntityRequest):
    internal_type = ENTITY_TYPE_INTERNAL.get(data.type, data.type.lower())
    base_slug = slugify(data.name)

    with engine.begin() as conn:
        slug = unique_slug(conn, base_slug)

        result = conn.execute(text("""
            INSERT INTO soa_entities
              (name, slug, entity_type, category, website_url, aliases)
            VALUES
              (:name, :slug, :et, :cat, :url, :aliases)
            RETURNING id, name, slug, entity_type, category
        """), {
            "name":    data.name,
            "slug":    slug,
            "et":      internal_type,
            "cat":     data.category,
            "url":     data.website_url,
            "aliases": str(data.aliases) if data.aliases else None,
        }).fetchone()

    return EntityResponse(
        id=result[0],
        name=result[1],
        slug=result[2],
        type=ENTITY_TYPE_DISPLAY.get(result[3], result[3].title()),
        category=result[4] or "",
    )


@router.put("/entities/{entity_id}", response_model=EntityResponse)
def update_entity(entity_id: int, data: EntityUpdateRequest):
    internal_type = ENTITY_TYPE_INTERNAL.get(data.type, data.type.lower()) if data.type else None

    with engine.begin() as conn:
        existing = conn.execute(text("""
            SELECT id, name, slug, entity_type, category
            FROM soa_entities WHERE id = :id
        """), {"id": entity_id}).fetchone()

        if not existing:
            raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")

        new_name = data.name if data.name is not None else existing[1]
        new_et   = internal_type if internal_type is not None else existing[3]
        new_cat  = data.category if data.category is not None else existing[4]

        # Re-slug only if name changed
        if data.name is not None and data.name != existing[1]:
            base_slug = slugify(data.name)
            new_slug  = unique_slug(conn, base_slug)
        else:
            new_slug = existing[2]

        result = conn.execute(text("""
            UPDATE soa_entities
            SET name        = :name,
                slug        = :slug,
                entity_type = :et,
                category    = :cat,
                website_url = :url,
                aliases     = :aliases,
                updated_at  = NOW()
            WHERE id = :id
            RETURNING id, name, slug, entity_type, category
        """), {
            "id":      entity_id,
            "name":    new_name,
            "slug":    new_slug,
            "et":      new_et,
            "cat":     new_cat,
            "url":     data.website_url,
            "aliases": str(data.aliases) if data.aliases else None,
        }).fetchone()

    return EntityResponse(
        id=result[0],
        name=result[1],
        slug=result[2],
        type=ENTITY_TYPE_DISPLAY.get(result[3], result[3].title()),
        category=result[4] or "",
    )
