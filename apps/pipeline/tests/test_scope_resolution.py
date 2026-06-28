"""
Tests for soa_shared/scope_resolution.py — the effective-scope resolution
rules (frozen / custom / inherited / materialized), the freeze-on-run hook
(materialize_and_freeze, idempotent), and the entity-template /
cycle-snapshot row invariants the entity-template endpoints rely on.

Uses a real in-memory SQLite database (via SQLAlchemy) rather than mocks,
since scope_resolution.py issues real ORM queries against SoaScopeSku /
SoaCycleEntity. Each test gets a fresh schema.
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import soa_shared.config as config
from soa_shared.models.soa_models import SoaCycle, SoaCycleEntity, SoaEntity, SoaScopeSku
from soa_shared.scope_resolution import (
    add_scope_sku_to_cycle,
    ensure_materialized_for_edit,
    get_effective_scope,
    materialize_and_freeze,
    remove_scope_sku_from_cycle,
    SOURCE_CUSTOM,
    SOURCE_FROZEN,
    SOURCE_INHERITED,
    SOURCE_MATERIALIZED,
)


@pytest.fixture
def session():
    # Raw DDL for just the tables scope_resolution.py touches, rather than
    # Base.metadata.create_all(): several tables (soa_queries, soa_cycles)
    # define the same index both via Column(index=True) and an explicit
    # Index(...) in __table_args__, which Alembic's hand-written migrations
    # never hit but a single create_all() pass does ("index already
    # exists"). That's a pre-existing, unrelated modeling quirk — sidestep
    # it here rather than fixing it as a side effect of this test.
    # Columns mirror every column the ORM models declare (not just the ones
    # these tests touch) — SQLAlchemy ORM SELECTs all mapped columns, so a
    # narrower table would fail with "no such column" at query time.
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_entities (
                id INTEGER PRIMARY KEY, name TEXT, slug TEXT, entity_type TEXT,
                category TEXT, merchant_id INTEGER, website_url TEXT, aliases TEXT,
                created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, cycle_code TEXT, start_date DATE,
                end_date DATE, total_runs_planned INTEGER, completed_runs INTEGER,
                status TEXT, notes TEXT, platforms TEXT, runs_per_query INTEGER,
                study_type TEXT, study_pattern TEXT,
                scope_frozen_at TIMESTAMP, scope_is_custom BOOLEAN,
                organization_id INTEGER, created_by TEXT,
                cycle_mode TEXT DEFAULT 'query', truecost_tiers TEXT,
                created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycle_entities (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                comparison_code TEXT, role TEXT, display_name TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_scope_skus (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                role TEXT, dealengine_listing_id INTEGER,
                dealengine_catalog_product_id INTEGER, merchant_slug TEXT,
                merchant_sku TEXT, brand TEXT, category TEXT, product_url TEXT,
                listed_price NUMERIC, currency TEXT, display_name TEXT,
                is_active BOOLEAN, created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _make_entity(session, name="Oral-B", slug="oral-b") -> SoaEntity:
    e = SoaEntity(name=name, slug=slug, entity_type="brand")
    session.add(e)
    session.flush()
    return e


def _make_cycle(session, status="planned", scope_is_custom=False, scope_frozen_at=None, cycle_code="C001") -> SoaCycle:
    c = SoaCycle(
        cycle_code=cycle_code,
        start_date=datetime.date(2026, 1, 1),
        study_type="brand_oral_b",
        study_pattern="brand_at_retail",
        status=status,
        organization_id=1,
        scope_is_custom=scope_is_custom,
        scope_frozen_at=scope_frozen_at,
    )
    session.add(c)
    session.flush()
    return c


def _link(session, cycle, entity, comparison_code="M001", role="primary"):
    ce = SoaCycleEntity(cycle_id=cycle.id, entity_id=entity.id, comparison_code=comparison_code, role=role)
    session.add(ce)
    session.flush()
    return ce


def _template(session, entity, merchant_sku="SKU-1", dealengine_listing_id=1, brand="Oral-B", display_name="Toothbrush") -> SoaScopeSku:
    t = SoaScopeSku(
        entity_id=entity.id, cycle_id=None, role="target", is_active=True,
        merchant_sku=merchant_sku, dealengine_listing_id=dealengine_listing_id,
        brand=brand, display_name=display_name,
    )
    session.add(t)
    session.flush()
    return t


# ─────────────────────────────────────────────────────────────────────────────
# get_effective_scope — the four resolution rules
# ─────────────────────────────────────────────────────────────────────────────

def test_frozen_returns_materialized_rows_and_is_not_editable(session):
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="complete", scope_frozen_at=datetime.datetime.now(datetime.timezone.utc))
    _link(session, cycle, entity)
    snapshot = SoaScopeSku(cycle_id=cycle.id, entity_id=entity.id, role="target", merchant_sku="frozen-1")
    session.add(snapshot)
    session.flush()
    # A template added AFTER freeze must NOT show up in the frozen scope.
    _template(session, entity, merchant_sku="added-after-freeze")

    effective = get_effective_scope(cycle, session)

    assert effective.source == SOURCE_FROZEN
    assert effective.is_editable is False
    assert [s.merchant_sku for s in effective.skus] == ["frozen-1"]


def test_custom_returns_materialized_rows_editable_while_planned(session):
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned", scope_is_custom=True)
    _link(session, cycle, entity)
    session.add(SoaScopeSku(cycle_id=cycle.id, entity_id=entity.id, role="target", merchant_sku="custom-1"))
    session.flush()

    effective = get_effective_scope(cycle, session)

    assert effective.source == SOURCE_CUSTOM
    assert effective.is_editable is True
    assert [s.merchant_sku for s in effective.skus] == ["custom-1"]


def test_custom_not_editable_once_cycle_is_running(session):
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="running", scope_is_custom=True)
    _link(session, cycle, entity)
    session.add(SoaScopeSku(cycle_id=cycle.id, entity_id=entity.id, role="target", merchant_sku="custom-1"))
    session.flush()

    effective = get_effective_scope(cycle, session)
    assert effective.is_editable is False


def test_inherited_live_when_resync_on_and_planned(session, monkeypatch):
    monkeypatch.setattr(config, "PLANNED_CYCLE_SCOPE_RESYNC", True)
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned")
    _link(session, cycle, entity)
    _template(session, entity, merchant_sku="tpl-1")

    effective = get_effective_scope(cycle, session)
    assert effective.source == SOURCE_INHERITED
    assert effective.is_editable is True
    assert [s.merchant_sku for s in effective.skus] == ["tpl-1"]

    # Live: a template added later shows up without any cycle-row mutation.
    _template(session, entity, merchant_sku="tpl-2", dealengine_listing_id=2)
    effective2 = get_effective_scope(cycle, session)
    assert sorted(s.merchant_sku for s in effective2.skus) == ["tpl-1", "tpl-2"]


def test_materialized_when_resync_off_even_if_planned(session, monkeypatch):
    monkeypatch.setattr(config, "PLANNED_CYCLE_SCOPE_RESYNC", False)
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned")
    _link(session, cycle, entity)
    _template(session, entity, merchant_sku="tpl-1")
    # Materialized at creation (simulating the cycle-creation hook).
    materialize_and_freeze(cycle, session, freeze=False)

    effective = get_effective_scope(cycle, session)
    assert effective.source == SOURCE_MATERIALIZED
    assert effective.is_editable is True
    assert [s.merchant_sku for s in effective.skus] == ["tpl-1"]

    # New template additions do NOT flow into a non-resync cycle.
    _template(session, entity, merchant_sku="tpl-2", dealengine_listing_id=2)
    effective2 = get_effective_scope(cycle, session)
    assert [s.merchant_sku for s in effective2.skus] == ["tpl-1"]


def test_resync_on_but_not_planned_falls_back_to_materialized(session, monkeypatch):
    monkeypatch.setattr(config, "PLANNED_CYCLE_SCOPE_RESYNC", True)
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="failed")
    _link(session, cycle, entity)
    _template(session, entity, merchant_sku="tpl-1")

    effective = get_effective_scope(cycle, session)
    # Not planned -> inherited-live branch does not apply; falls through to
    # the materialized branch, which is empty since nothing materialized yet.
    assert effective.source == SOURCE_MATERIALIZED
    assert effective.skus == []
    assert effective.is_editable is False


def test_entity_with_no_templates_yields_empty_inherited_scope(session, monkeypatch):
    monkeypatch.setattr(config, "PLANNED_CYCLE_SCOPE_RESYNC", True)
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned")
    _link(session, cycle, entity)

    effective = get_effective_scope(cycle, session)
    assert effective.skus == []
    assert effective.source == SOURCE_INHERITED


# ─────────────────────────────────────────────────────────────────────────────
# materialize_and_freeze — the freeze-on-run hook, idempotent
# ─────────────────────────────────────────────────────────────────────────────

def test_materialize_and_freeze_copies_templates_and_stamps_frozen_at(session):
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned")
    _link(session, cycle, entity)
    _template(session, entity, merchant_sku="tpl-1", dealengine_listing_id=42, brand="Oral-B", display_name="Toothbrush")

    rows = materialize_and_freeze(cycle, session, freeze=True)

    assert len(rows) == 1
    assert rows[0].cycle_id == cycle.id
    assert rows[0].merchant_sku == "tpl-1"
    assert rows[0].dealengine_listing_id == 42
    assert rows[0].brand == "Oral-B"
    assert rows[0].display_name == "Toothbrush"
    assert cycle.scope_frozen_at is not None


def test_materialize_and_freeze_is_idempotent(session):
    """
    Simulates the run-start hook firing twice (e.g. a resumed/retried run):
    the second call must not duplicate rows or change the freeze timestamp.
    """
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned")
    _link(session, cycle, entity)
    _template(session, entity, merchant_sku="tpl-1")

    first_rows = materialize_and_freeze(cycle, session, freeze=True)
    first_frozen_at = cycle.scope_frozen_at
    assert len(first_rows) == 1

    second_rows = materialize_and_freeze(cycle, session, freeze=True)

    assert len(second_rows) == 1
    assert second_rows[0].id == first_rows[0].id
    assert cycle.scope_frozen_at == first_frozen_at

    all_cycle_rows = session.query(SoaScopeSku).filter_by(cycle_id=cycle.id).all()
    assert len(all_cycle_rows) == 1


def test_materialize_and_freeze_with_no_templates_still_freezes(session):
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned")
    _link(session, cycle, entity)

    rows = materialize_and_freeze(cycle, session, freeze=True)

    assert rows == []
    assert cycle.scope_frozen_at is not None


def test_materialize_without_freeze_leaves_frozen_at_null(session):
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned")
    _link(session, cycle, entity)
    _template(session, entity)

    materialize_and_freeze(cycle, session, freeze=False)

    assert cycle.scope_frozen_at is None


def test_template_row_untouched_by_materialize(session):
    """A completed cycle's frozen snapshot must never mutate the brand's template."""
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned")
    _link(session, cycle, entity)
    template = _template(session, entity, merchant_sku="tpl-1")

    materialize_and_freeze(cycle, session, freeze=True)

    session.refresh(template)
    assert template.cycle_id is None
    assert template.is_active is True


# ─────────────────────────────────────────────────────────────────────────────
# ensure_materialized_for_edit / add / remove — editing a Planned cycle's scope
# ─────────────────────────────────────────────────────────────────────────────

def test_ensure_materialized_for_edit_sets_custom_flag(session):
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned")
    _link(session, cycle, entity)
    _template(session, entity, merchant_sku="tpl-1")

    assert cycle.scope_is_custom is False
    ensure_materialized_for_edit(cycle, session)

    assert cycle.scope_is_custom is True
    assert cycle.scope_frozen_at is None
    materialized = session.query(SoaScopeSku).filter_by(cycle_id=cycle.id).all()
    assert len(materialized) == 1


def test_add_scope_sku_to_cycle_materializes_inherited_set_first(session, monkeypatch):
    monkeypatch.setattr(config, "PLANNED_CYCLE_SCOPE_RESYNC", True)
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned")
    _link(session, cycle, entity)
    _template(session, entity, merchant_sku="tpl-1", dealengine_listing_id=1)

    new_row = add_scope_sku_to_cycle(cycle, session, entity_id=entity.id, role="target", merchant_sku="added-1", dealengine_listing_id=99)

    assert cycle.scope_is_custom is True
    cycle_rows = session.query(SoaScopeSku).filter_by(cycle_id=cycle.id, is_active=True).all()
    skus = sorted(r.merchant_sku for r in cycle_rows)
    assert skus == ["added-1", "tpl-1"]
    assert new_row.merchant_sku == "added-1"


def test_remove_scope_sku_from_cycle_when_already_materialized(session):
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned", scope_is_custom=True)
    _link(session, cycle, entity)
    row = SoaScopeSku(cycle_id=cycle.id, entity_id=entity.id, role="target", merchant_sku="custom-1", is_active=True)
    session.add(row)
    session.flush()

    removed = remove_scope_sku_from_cycle(cycle, session, row.id)

    assert removed is not None
    assert removed.id == row.id
    session.refresh(row)
    assert row.is_active is False


def test_remove_scope_sku_from_cycle_resolves_template_id_by_content_match(session, monkeypatch):
    """
    The UI shows template rows while a cycle is inherited-live. Removing
    "by template id" must materialize the full set, then deactivate only
    the materialized counterpart of that template — never the template
    itself, and never the OTHER inherited SKU.
    """
    monkeypatch.setattr(config, "PLANNED_CYCLE_SCOPE_RESYNC", True)
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned")
    _link(session, cycle, entity)
    template_to_remove = _template(session, entity, merchant_sku="tpl-1", dealengine_listing_id=11)
    template_to_keep = _template(session, entity, merchant_sku="tpl-2", dealengine_listing_id=22)

    removed = remove_scope_sku_from_cycle(cycle, session, template_to_remove.id)

    assert removed is not None
    assert removed.cycle_id == cycle.id  # the materialized clone, not the template
    assert removed.dealengine_listing_id == 11

    # Original templates are untouched.
    session.refresh(template_to_remove)
    session.refresh(template_to_keep)
    assert template_to_remove.is_active is True
    assert template_to_remove.cycle_id is None
    assert template_to_keep.is_active is True

    # Cycle now has both materialized, but only tpl-2's clone remains active.
    active_cycle_rows = session.query(SoaScopeSku).filter_by(cycle_id=cycle.id, is_active=True).all()
    assert [r.dealengine_listing_id for r in active_cycle_rows] == [22]
    assert cycle.scope_is_custom is True


def test_remove_scope_sku_from_cycle_falls_back_to_merchant_slug_and_sku_match(session, monkeypatch):
    monkeypatch.setattr(config, "PLANNED_CYCLE_SCOPE_RESYNC", True)
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned")
    _link(session, cycle, entity)
    # No dealengine_listing_id -> must match on merchant_slug + merchant_sku.
    template = SoaScopeSku(
        entity_id=entity.id, cycle_id=None, role="target", is_active=True,
        merchant_slug="sephora", merchant_sku="SKU-NO-LISTING-ID",
    )
    session.add(template)
    session.flush()

    removed = remove_scope_sku_from_cycle(cycle, session, template.id)

    assert removed is not None
    assert removed.cycle_id == cycle.id
    assert removed.merchant_sku == "SKU-NO-LISTING-ID"


def test_remove_scope_sku_from_cycle_returns_none_for_unknown_id(session):
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned")
    _link(session, cycle, entity)

    removed = remove_scope_sku_from_cycle(cycle, session, 999999)
    assert removed is None
    # Still flips to custom — an edit attempt occurred even if nothing matched.
    assert cycle.scope_is_custom is True


# ─────────────────────────────────────────────────────────────────────────────
# Entity-template row invariants (what the entity-template endpoints rely on)
# ─────────────────────────────────────────────────────────────────────────────

def test_template_rows_are_scoped_to_their_own_entity(session):
    e1 = _make_entity(session, name="Oral-B", slug="oral-b")
    e2 = _make_entity(session, name="Gillette", slug="gillette")
    cycle = _make_cycle(session, status="planned")
    _link(session, cycle, e1)
    _template(session, e1, merchant_sku="oral-b-1")
    _template(session, e2, merchant_sku="gillette-1", dealengine_listing_id=2)

    effective = get_effective_scope(cycle, session)
    assert [s.merchant_sku for s in effective.skus] == ["oral-b-1"]


def test_inactive_template_rows_are_excluded(session):
    entity = _make_entity(session)
    cycle = _make_cycle(session, status="planned")
    _link(session, cycle, entity)
    t = _template(session, entity, merchant_sku="tpl-1")
    t.is_active = False
    session.flush()

    effective = get_effective_scope(cycle, session)
    assert effective.skus == []
