"""
scope_resolution.py — effective-scope rules for SKU-level measurement
scope (soa_scope_skus), nested under entities.

Two kinds of soa_scope_skus rows:
  - ENTITY TEMPLATE rows: entity_id set, cycle_id NULL. The brand's living,
    editable measured-SKU set — the source of truth, edited over time.
  - CYCLE SNAPSHOT rows: cycle_id set, entity_id set. A copy of the
    templates captured for a specific cycle, so history stays intact.

A cycle's "effective scope" depends on its freeze/custom state:
  - scope_frozen_at set       -> the materialized cycle_id rows (frozen, read-only)
  - scope_is_custom true      -> the materialized cycle_id rows (custom, editable while Planned)
  - PLANNED_CYCLE_SCOPE_RESYNC and status == 'planned'
                               -> the live union of measured entities' active
                                  template rows (NOT persisted as cycle rows)
  - else                      -> the materialized cycle_id rows captured at creation

This module is shared by apps/api (authoring) and apps/pipeline (the coder
reads effective scope when SKU_SCOPE_ENABLED). Mirrored into both
soa_shared copies — edit apps/pipeline/soa_shared/ first, then re-copy.
"""
import datetime
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.orm import Session

import soa_shared.config as config
from soa_shared.models.soa_models import SoaCycle, SoaCycleEntity, SoaScopeSku

SOURCE_FROZEN = "frozen"
SOURCE_CUSTOM = "custom"
SOURCE_INHERITED = "inherited"
SOURCE_MATERIALIZED = "materialized"


@dataclass
class EffectiveScope:
    skus: List[SoaScopeSku]
    source: str  # frozen | custom | inherited | materialized
    is_editable: bool


def _template_rows_for_cycle_entities(session: Session, cycle_id: int) -> List[SoaScopeSku]:
    """Live union of the active template rows of every entity this cycle measures."""
    entity_ids = [
        row[0] for row in
        session.query(SoaCycleEntity.entity_id).filter_by(cycle_id=cycle_id).all()
    ]
    if not entity_ids:
        return []
    return (
        session.query(SoaScopeSku)
        .filter(
            SoaScopeSku.entity_id.in_(entity_ids),
            SoaScopeSku.cycle_id.is_(None),
            SoaScopeSku.is_active.is_(True),
        )
        .order_by(SoaScopeSku.id)
        .all()
    )


def _materialized_rows_for_cycle(session: Session, cycle_id: int) -> List[SoaScopeSku]:
    return (
        session.query(SoaScopeSku)
        .filter(
            SoaScopeSku.cycle_id == cycle_id,
            SoaScopeSku.is_active.is_(True),
        )
        .order_by(SoaScopeSku.id)
        .all()
    )


def get_effective_scope(cycle: SoaCycle, session: Session) -> EffectiveScope:
    """
    Resolves which soa_scope_skus rows apply to this cycle right now, per
    the rules in the module docstring. Never mutates the database.
    """
    if cycle.scope_frozen_at is not None:
        return EffectiveScope(
            skus=_materialized_rows_for_cycle(session, cycle.id),
            source=SOURCE_FROZEN,
            is_editable=False,
        )

    if cycle.scope_is_custom:
        return EffectiveScope(
            skus=_materialized_rows_for_cycle(session, cycle.id),
            source=SOURCE_CUSTOM,
            is_editable=cycle.status == "planned",
        )

    if config.PLANNED_CYCLE_SCOPE_RESYNC and cycle.status == "planned":
        return EffectiveScope(
            skus=_template_rows_for_cycle_entities(session, cycle.id),
            source=SOURCE_INHERITED,
            is_editable=True,
        )

    return EffectiveScope(
        skus=_materialized_rows_for_cycle(session, cycle.id),
        source=SOURCE_MATERIALIZED,
        is_editable=cycle.status == "planned",
    )


def materialize_and_freeze(
    cycle: SoaCycle,
    session: Session,
    freeze: bool = True,
) -> List[SoaScopeSku]:
    """
    Copies the current effective scope into cycle_id rows if none exist
    yet, then (when freeze=True) stamps scope_frozen_at. Idempotent: if
    cycle_id rows already exist, never re-copies them, and never re-stamps
    scope_frozen_at once set. Returns the materialized rows.

    Called with freeze=True at run start (the scope is locked in for the
    run that's about to happen) and with freeze=False at cycle creation
    when PLANNED_CYCLE_SCOPE_RESYNC is off, and whenever a Planned cycle's
    scope is edited for the first time (which also flips scope_is_custom).
    """
    existing = _materialized_rows_for_cycle(session, cycle.id)

    if not existing:
        templates = _template_rows_for_cycle_entities(session, cycle.id)
        new_rows = [
            SoaScopeSku(
                cycle_id=cycle.id,
                entity_id=tpl.entity_id,
                role=tpl.role,
                dealengine_listing_id=tpl.dealengine_listing_id,
                dealengine_catalog_product_id=tpl.dealengine_catalog_product_id,
                merchant_slug=tpl.merchant_slug,
                merchant_sku=tpl.merchant_sku,
                brand=tpl.brand,
                category=tpl.category,
                product_url=tpl.product_url,
                listed_price=tpl.listed_price,
                currency=tpl.currency,
                display_name=tpl.display_name,
                is_active=True,
            )
            for tpl in templates
        ]
        for row in new_rows:
            session.add(row)
        if new_rows:
            session.flush()
        existing = new_rows

    if freeze and cycle.scope_frozen_at is None:
        cycle.scope_frozen_at = datetime.datetime.now(datetime.timezone.utc)

    return existing


def ensure_materialized_for_edit(cycle: SoaCycle, session: Session) -> None:
    """
    Materializes (if not already) and marks scope_is_custom=True, without
    freezing. Call before any write to a cycle's scope. Callers must check
    get_effective_scope(cycle, session).is_editable first — this function
    does not itself reject edits to a frozen cycle.
    """
    materialize_and_freeze(cycle, session, freeze=False)
    if not cycle.scope_is_custom:
        cycle.scope_is_custom = True


def add_scope_sku_to_cycle(cycle: SoaCycle, session: Session, **fields) -> SoaScopeSku:
    """
    Adds a new cycle-snapshot row, materializing the inherited template
    set first if this is the cycle's first scope edit.
    """
    ensure_materialized_for_edit(cycle, session)
    row = SoaScopeSku(cycle_id=cycle.id, **fields)
    session.add(row)
    session.flush()
    return row


def remove_scope_sku_from_cycle(
    cycle: SoaCycle, session: Session, sku_id: int,
) -> Optional[SoaScopeSku]:
    """
    Removes a SKU from this cycle's effective scope. sku_id may be either
    an already-materialized cycle row's id, or — when the cycle is still
    showing its live inherited template set — a template row's id (since
    that's what the caller was shown before any cycle rows existed).

    In the latter case, materializes first (copying ALL templates, per
    materialize_and_freeze), then finds the materialized counterpart of
    the referenced template by content (dealengine_listing_id, falling
    back to merchant_slug + merchant_sku) and removes that one instead —
    the original template row is never touched.
    """
    target = (
        session.query(SoaScopeSku)
        .filter_by(id=sku_id, cycle_id=cycle.id)
        .first()
    )
    if target is not None:
        target.is_active = False
        session.flush()
        return target

    template = (
        session.query(SoaScopeSku)
        .filter_by(id=sku_id, cycle_id=None)
        .first()
    )

    ensure_materialized_for_edit(cycle, session)

    if template is None:
        return None

    match_query = session.query(SoaScopeSku).filter_by(cycle_id=cycle.id, is_active=True)
    if template.dealengine_listing_id is not None:
        match = match_query.filter_by(dealengine_listing_id=template.dealengine_listing_id).first()
    else:
        match = match_query.filter_by(
            merchant_slug=template.merchant_slug, merchant_sku=template.merchant_sku,
        ).first()

    if match is not None:
        match.is_active = False
        session.flush()
    return match
