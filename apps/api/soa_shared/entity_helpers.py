"""
Slug helpers for soa_entities, shared by apps/api/app/routers/entities.py
(explicit entity CRUD) and the SoA Lite worker (implicit entity resolution
from freeform visitor input).

slugify/unique_slug always produce a NEW, disambiguated slug (name -> name,
name-2, name-3, ...) — correct for entities.py, where a user explicitly
asks to create a distinct entity even if the name looks similar to an
existing one. get_or_create_entity_by_slug is the opposite: it reuses an
existing entity whenever the slug matches exactly, so repeat SoA Lite
submissions of the same brand name don't create duplicate soa_entities rows.
"""
import re

from sqlalchemy import text


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


def get_or_create_entity_by_slug(conn, name: str, entity_type: str) -> int:
    """
    Returns the id of the soa_entities row whose slug exactly matches
    slugify(name), creating one with the given entity_type if none exists.
    Caller owns the transaction (pass an open conn from engine.begin()).
    """
    slug = slugify(name)

    existing = conn.execute(text("""
        SELECT id FROM soa_entities WHERE slug = :slug
    """), {"slug": slug}).fetchone()
    if existing:
        return existing[0]

    result = conn.execute(text("""
        INSERT INTO soa_entities (name, slug, entity_type)
        VALUES (:name, :slug, :entity_type)
        RETURNING id
    """), {"name": name, "slug": slug, "entity_type": entity_type}).fetchone()
    return result[0]
