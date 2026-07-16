"""
Tests for soa_shared/entity_helpers.py. get_or_create_entity_by_slug is the
new SoA Lite dedup path — reuses an existing entity on an exact slug match
instead of unique_slug's disambiguate-and-always-insert behavior (which
entities.py keeps using unchanged). Uses a real in-memory SQLite database,
same convention as test_scope_resolution.py.
"""
import pytest
from sqlalchemy import create_engine

from soa_shared.entity_helpers import get_or_create_entity_by_slug, slugify, unique_slug


@pytest.fixture
def conn():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as c:
        c.exec_driver_sql("""
            CREATE TABLE soa_entities (
                id INTEGER PRIMARY KEY, name TEXT, slug TEXT UNIQUE, entity_type TEXT,
                category TEXT, merchant_id INTEGER, website_url TEXT, aliases TEXT,
                created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
    with engine.connect() as c:
        yield c
    engine.dispose()


# ── slugify ──────────────────────────────────────────────────────────────

def test_slugify_lowercases_and_hyphenates():
    assert slugify("Drunk Elephant") == "drunk-elephant"


def test_slugify_strips_apostrophes_and_parens():
    assert slugify("L'Oreal (Paris)") == "loreal-paris"


# ── get_or_create_entity_by_slug ────────────────────────────────────────

def test_creates_new_entity_when_slug_absent(conn):
    eid = get_or_create_entity_by_slug(conn, "Pampers", "brand")
    conn.commit()

    row = conn.exec_driver_sql(
        "SELECT name, slug, entity_type FROM soa_entities WHERE id = ?", (eid,)
    ).fetchone()
    assert row == ("Pampers", "pampers", "brand")


def test_reuses_existing_entity_for_same_slug(conn):
    first_id = get_or_create_entity_by_slug(conn, "Pampers", "brand")
    conn.commit()

    second_id = get_or_create_entity_by_slug(conn, "Pampers", "brand")

    assert first_id == second_id
    count = conn.exec_driver_sql("SELECT COUNT(*) FROM soa_entities").fetchone()[0]
    assert count == 1


def test_reuses_existing_entity_across_casing_and_punctuation_variants(conn):
    first_id = get_or_create_entity_by_slug(conn, "Pampers", "brand")
    conn.commit()

    second_id = get_or_create_entity_by_slug(conn, "PAMPERS", "brand")

    assert first_id == second_id


def test_different_names_create_different_entities(conn):
    pampers_id = get_or_create_entity_by_slug(conn, "Pampers", "brand")
    conn.commit()
    huggies_id = get_or_create_entity_by_slug(conn, "Huggies", "brand")

    assert pampers_id != huggies_id
    count = conn.exec_driver_sql("SELECT COUNT(*) FROM soa_entities").fetchone()[0]
    assert count == 2


# ── unique_slug (unchanged behavior, moved not modified) ────────────────

def test_unique_slug_disambiguates_on_collision(conn):
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (name, slug, entity_type) VALUES ('Pampers', 'pampers', 'brand')"
    )
    conn.commit()

    slug = unique_slug(conn, "pampers")

    assert slug == "pampers-2"
