"""
Tests for GET /api/cycles/{cycle_code}/truecost-snapshots
(apps/api/app/routers/cycles.py::get_cycle_truecost_snapshots).

Calls the route function directly (FastAPI's @router.get decorator
returns the underlying function unchanged) rather than spinning up a
TestClient + JWT auth, since this app has no existing test harness for
that. Uses a real in-memory SQLite database for the ORM queries the
endpoint issues, mirroring the pattern in apps/pipeline's migration/
scope-resolution tests.
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.routers.cycles as cycles_router
from soa_shared.models.soa_models import SoaCycle, SoaScopeSku, SoaTruecostSnapshot


@pytest.fixture
def Session():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
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
            CREATE TABLE soa_scope_skus (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                role TEXT, dealengine_listing_id INTEGER,
                dealengine_catalog_product_id INTEGER, merchant_slug TEXT,
                merchant_sku TEXT, brand TEXT, category TEXT, product_url TEXT,
                listed_price NUMERIC, currency TEXT, display_name TEXT,
                is_active BOOLEAN, created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_truecost_snapshots (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, scope_sku_id INTEGER,
                entity_id INTEGER, dealengine_listing_id INTEGER,
                merchant_slug TEXT, brand TEXT, category TEXT, user_tier_name TEXT,
                listed_price NUMERIC, currency TEXT, true_cost NUMERIC,
                total_savings NUMERIC, total_points_earned INTEGER,
                applied_deals TEXT, available_deals TEXT, confidence FLOAT,
                price_was_refreshed BOOLEAN, price_refreshed_at TIMESTAMP,
                status TEXT, error_message TEXT, captured_at TIMESTAMP
            )
        """)
    return sessionmaker(bind=engine)


@pytest.fixture
def patched_session_factory(Session, monkeypatch):
    monkeypatch.setattr(cycles_router, "session_factory", Session)
    return Session


def _make_cycle(Session, cycle_code="TC001", org_id=1):
    with Session() as session:
        cycle = SoaCycle(
            cycle_code=cycle_code,
            start_date=datetime.date(2026, 6, 1),
            status="complete",
            organization_id=org_id,
            cycle_mode="truecost",
        )
        session.add(cycle)
        session.commit()
        session.refresh(cycle)
        return cycle.id


def _add_scope_sku(Session, cycle_id, listing_id=101, display_name="NARS Serum"):
    with Session() as session:
        sku = SoaScopeSku(
            cycle_id=cycle_id, role="target", dealengine_listing_id=listing_id,
            merchant_slug="sephora", brand="NARS", category="Skincare",
            display_name=display_name, is_active=True,
        )
        session.add(sku)
        session.commit()
        session.refresh(sku)
        return sku.id


def _add_snapshot(Session, cycle_id, sku_id, tier, true_cost, status="captured", **kwargs):
    with Session() as session:
        snap = SoaTruecostSnapshot(
            cycle_id=cycle_id, scope_sku_id=sku_id, user_tier_name=tier,
            true_cost=true_cost, listed_price=kwargs.get("listed_price", 100.0),
            currency="USD", status=status, error_message=kwargs.get("error_message"),
            total_savings=kwargs.get("total_savings"),
        )
        session.add(snap)
        session.commit()


CURRENT_USER = {"organization_id": 1, "user_id": "u1"}


def test_returns_404_for_unknown_cycle(patched_session_factory):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        cycles_router.get_cycle_truecost_snapshots("NOPE", current_user=CURRENT_USER)
    assert exc_info.value.status_code == 404


def test_returns_404_for_cycle_in_another_org(patched_session_factory):
    from fastapi import HTTPException

    Session = patched_session_factory
    _make_cycle(Session, cycle_code="OTHERORG", org_id=2)

    with pytest.raises(HTTPException) as exc_info:
        cycles_router.get_cycle_truecost_snapshots("OTHERORG", current_user=CURRENT_USER)
    assert exc_info.value.status_code == 404


def test_grid_groups_snapshots_by_sku_with_one_tier_each(patched_session_factory):
    Session = patched_session_factory
    cycle_id = _make_cycle(Session)
    sku1 = _add_scope_sku(Session, cycle_id, listing_id=101, display_name="NARS Serum")
    sku2 = _add_scope_sku(Session, cycle_id, listing_id=102, display_name="NARS Cream")
    _add_snapshot(Session, cycle_id, sku1, tier=None, true_cost=90.0)
    _add_snapshot(Session, cycle_id, sku2, tier=None, true_cost=70.0)

    result = cycles_router.get_cycle_truecost_snapshots("TC001", current_user=CURRENT_USER)

    assert result.cycle_code == "TC001"
    assert len(result.skus) == 2
    by_sku = {row.scope_sku_id: row for row in result.skus}
    assert by_sku[sku1].display_name == "NARS Serum"
    assert by_sku[sku1].tiers[0].true_cost == 90.0
    assert by_sku[sku1].member_vs_baseline_delta == {}  # only one tier — no delta


def test_grid_computes_member_vs_baseline_delta_when_multiple_tiers(patched_session_factory):
    Session = patched_session_factory
    cycle_id = _make_cycle(Session)
    sku = _add_scope_sku(Session, cycle_id)
    _add_snapshot(Session, cycle_id, sku, tier=None, true_cost=100.0)
    _add_snapshot(Session, cycle_id, sku, tier="Rouge", true_cost=85.0)
    _add_snapshot(Session, cycle_id, sku, tier="Insider", true_cost=95.0)

    result = cycles_router.get_cycle_truecost_snapshots("TC001", current_user=CURRENT_USER)

    row = result.skus[0]
    assert len(row.tiers) == 3
    assert row.member_vs_baseline_delta == {"Rouge": 15.0, "Insider": 5.0}


def test_grid_skips_delta_when_baseline_unavailable(patched_session_factory):
    Session = patched_session_factory
    cycle_id = _make_cycle(Session)
    sku = _add_scope_sku(Session, cycle_id)
    _add_snapshot(
        Session, cycle_id, sku, tier=None, true_cost=None,
        status="ground_truth_unavailable", error_message="timeout",
    )
    _add_snapshot(Session, cycle_id, sku, tier="Rouge", true_cost=85.0)

    result = cycles_router.get_cycle_truecost_snapshots("TC001", current_user=CURRENT_USER)

    row = result.skus[0]
    assert row.member_vs_baseline_delta == {}
    baseline_tier = next(t for t in row.tiers if t.user_tier_name is None)
    assert baseline_tier.status == "ground_truth_unavailable"
    assert baseline_tier.error_message == "timeout"


def test_empty_grid_for_cycle_with_no_snapshots(patched_session_factory):
    Session = patched_session_factory
    _make_cycle(Session)

    result = cycles_router.get_cycle_truecost_snapshots("TC001", current_user=CURRENT_USER)

    assert result.skus == []
