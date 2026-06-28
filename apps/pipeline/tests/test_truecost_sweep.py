"""
Tests for sweep/truecost_sweep.py — the Deal Engine sweep executor for
cycle_mode='truecost' cycles.

Uses a real in-memory SQLite database (mirrors test_scope_resolution.py's
pattern) since materialize_and_freeze and the sweep's own queries issue
real ORM queries against SoaCycle / SoaScopeSku / SoaTruecostSnapshot.
The Deal Engine client itself is mocked — these tests assert the sweep's
orchestration (one scrape per SKU, one row per tier, the unavailable
path, resume), not HTTP behavior (covered by test_deal_engine_client.py).
"""
import asyncio
import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from clients.deal_engine_client import ListingTrueCostResult
from soa_shared.models.soa_models import SoaCycle, SoaScopeSku, SoaTruecostSnapshot
import sweep.truecost_sweep as truecost_sweep


@pytest.fixture
def Session():
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
    monkeypatch.setattr(truecost_sweep, "session_factory", Session)
    return Session


def _make_cycle(Session, cycle_mode="truecost", truecost_tiers=None, cycle_code="TC001"):
    with Session() as session:
        cycle = SoaCycle(
            cycle_code=cycle_code,
            start_date=datetime.date(2026, 6, 1),
            status="planned",
            organization_id=1,
            cycle_mode=cycle_mode,
            truecost_tiers=truecost_tiers,
        )
        session.add(cycle)
        session.commit()
        session.refresh(cycle)
        return cycle.id


def _add_scope_sku(Session, cycle_id, listing_id=101, brand="NARS", merchant_slug="sephora"):
    with Session() as session:
        sku = SoaScopeSku(
            cycle_id=cycle_id,
            role="target",
            dealengine_listing_id=listing_id,
            merchant_slug=merchant_slug,
            brand=brand,
            category="Skincare",
            is_active=True,
        )
        session.add(sku)
        session.commit()
        session.refresh(sku)
        return sku.id


def _ok_result(true_cost, tier, refreshed):
    return ListingTrueCostResult(
        available=True,
        true_cost=true_cost,
        listed_price=100.0,
        currency="USD",
        total_savings=10.0,
        total_points_earned=5,
        applied_deals=[{"deal_type": "member_price"}],
        available_deals=[],
        confidence=0.9,
        user_tier_name=tier,
        price_was_refreshed=refreshed,
        price_refreshed_at="2026-06-28T00:00:00+00:00" if refreshed else None,
    )


def _fail_result(error="Deal Engine unreachable"):
    return ListingTrueCostResult(available=False, error=error)


# ---------------------------------------------------------------------------
# Rejects non-truecost cycles
# ---------------------------------------------------------------------------

def test_refuses_to_sweep_a_query_mode_cycle(patched_session_factory):
    Session = patched_session_factory
    _make_cycle(Session, cycle_mode="query", cycle_code="QC001")

    with pytest.raises(ValueError, match="not 'truecost'"):
        asyncio.run(truecost_sweep.run_truecost_sweep("QC001"))


# ---------------------------------------------------------------------------
# One scrape per SKU, one row per tier
# ---------------------------------------------------------------------------

def test_sweep_scrapes_once_per_sku_and_writes_one_row_per_tier(patched_session_factory):
    Session = patched_session_factory
    cycle_id = _make_cycle(Session, truecost_tiers=["Rouge", "Insider"], cycle_code="TC002")
    sku1 = _add_scope_sku(Session, cycle_id, listing_id=101)
    sku2 = _add_scope_sku(Session, cycle_id, listing_id=102)

    client = AsyncMock()
    client.listing_true_cost = AsyncMock(
        side_effect=lambda listing_id, user_tier_name, refresh_price: _ok_result(
            true_cost=50.0, tier=user_tier_name, refreshed=refresh_price,
        )
    )

    summary = asyncio.run(
        truecost_sweep.run_truecost_sweep("TC002", client=client)
    )

    assert summary.sku_count == 2
    assert summary.tier_count == 2
    assert summary.total_planned == 4
    assert summary.captured == 4
    assert summary.unavailable == 0

    # Exactly one refresh_price=True call per SKU (one scrape per SKU).
    refresh_calls = [c for c in client.listing_true_cost.call_args_list if c.kwargs["refresh_price"]]
    assert len(refresh_calls) == 2
    refreshed_listing_ids = {c.kwargs["listing_id"] if "listing_id" in c.kwargs else c.args[0] for c in refresh_calls}
    assert refreshed_listing_ids == {101, 102}

    no_refresh_calls = [c for c in client.listing_true_cost.call_args_list if not c.kwargs["refresh_price"]]
    assert len(no_refresh_calls) == 2

    with Session() as session:
        rows = session.query(SoaTruecostSnapshot).filter_by(cycle_id=cycle_id).all()
        assert len(rows) == 4
        tiers_for_sku1 = {r.user_tier_name for r in rows if r.scope_sku_id == sku1}
        assert tiers_for_sku1 == {"Rouge", "Insider"}
        assert all(r.status == "captured" for r in rows)


def test_sweep_defaults_to_baseline_only_when_tiers_empty(patched_session_factory):
    Session = patched_session_factory
    cycle_id = _make_cycle(Session, truecost_tiers=None, cycle_code="TC003")
    _add_scope_sku(Session, cycle_id, listing_id=201)

    client = AsyncMock()
    client.listing_true_cost = AsyncMock(return_value=_ok_result(true_cost=80.0, tier=None, refreshed=True))

    summary = asyncio.run(truecost_sweep.run_truecost_sweep("TC003", client=client))

    assert summary.tier_count == 1
    assert summary.total_planned == 1
    client.listing_true_cost.assert_awaited_once()
    _, kwargs = client.listing_true_cost.call_args
    assert kwargs["user_tier_name"] is None
    assert kwargs["refresh_price"] is True


# ---------------------------------------------------------------------------
# Deal Engine failure path
# ---------------------------------------------------------------------------

def test_sweep_continues_past_deal_engine_failure_for_a_sku(patched_session_factory):
    Session = patched_session_factory
    cycle_id = _make_cycle(Session, truecost_tiers=["Rouge"], cycle_code="TC004")
    failing_sku = _add_scope_sku(Session, cycle_id, listing_id=301)
    ok_sku = _add_scope_sku(Session, cycle_id, listing_id=302)

    async def _side_effect(listing_id, user_tier_name, refresh_price):
        if listing_id == 301:
            return _fail_result("timeout")
        return _ok_result(true_cost=40.0, tier=user_tier_name, refreshed=refresh_price)

    client = AsyncMock()
    client.listing_true_cost = AsyncMock(side_effect=_side_effect)

    summary = asyncio.run(truecost_sweep.run_truecost_sweep("TC004", client=client))

    assert summary.captured == 1
    assert summary.unavailable == 1

    with Session() as session:
        failing_row = (
            session.query(SoaTruecostSnapshot)
            .filter_by(cycle_id=cycle_id, scope_sku_id=failing_sku)
            .first()
        )
        assert failing_row.status == "ground_truth_unavailable"
        assert failing_row.error_message == "timeout"

        ok_row = (
            session.query(SoaTruecostSnapshot)
            .filter_by(cycle_id=cycle_id, scope_sku_id=ok_sku)
            .first()
        )
        assert ok_row.status == "captured"


def test_sweep_marks_unavailable_when_sku_has_no_listing_id(patched_session_factory):
    Session = patched_session_factory
    cycle_id = _make_cycle(Session, truecost_tiers=["Rouge"], cycle_code="TC005")
    with Session() as session:
        sku = SoaScopeSku(cycle_id=cycle_id, role="target", dealengine_listing_id=None, is_active=True)
        session.add(sku)
        session.commit()

    client = AsyncMock()
    client.listing_true_cost = AsyncMock()

    summary = asyncio.run(truecost_sweep.run_truecost_sweep("TC005", client=client))

    assert summary.unavailable == 1
    client.listing_true_cost.assert_not_awaited()

    with Session() as session:
        row = session.query(SoaTruecostSnapshot).filter_by(cycle_id=cycle_id).first()
        assert row.status == "ground_truth_unavailable"
        assert "dealengine_listing_id" in row.error_message


# ---------------------------------------------------------------------------
# Resume — skip (sku, tier) pairs already captured
# ---------------------------------------------------------------------------

def test_sweep_resumes_skipping_already_captured_pairs(patched_session_factory):
    Session = patched_session_factory
    cycle_id = _make_cycle(Session, truecost_tiers=["Rouge", "Insider"], cycle_code="TC006")
    sku_id = _add_scope_sku(Session, cycle_id, listing_id=401)

    with Session() as session:
        session.add(SoaTruecostSnapshot(
            cycle_id=cycle_id, scope_sku_id=sku_id, user_tier_name="Rouge",
            status="captured", true_cost=60.0,
        ))
        session.commit()

    client = AsyncMock()
    client.listing_true_cost = AsyncMock(
        return_value=_ok_result(true_cost=55.0, tier="Insider", refreshed=False)
    )

    summary = asyncio.run(truecost_sweep.run_truecost_sweep("TC006", client=client))

    assert summary.skipped_already_done == 1
    assert summary.captured == 1
    client.listing_true_cost.assert_awaited_once()
    _, kwargs = client.listing_true_cost.call_args
    assert kwargs["user_tier_name"] == "Insider"

    with Session() as session:
        rows = session.query(SoaTruecostSnapshot).filter_by(cycle_id=cycle_id).all()
        assert len(rows) == 2


def test_resolve_tiers_dedupes_preserving_order_and_defaults_to_baseline():
    cycle = SoaCycle(truecost_tiers=["Rouge", "Rouge", None, "Insider"])
    assert truecost_sweep.resolve_tiers(cycle) == ["Rouge", None, "Insider"]

    cycle_empty = SoaCycle(truecost_tiers=[])
    assert truecost_sweep.resolve_tiers(cycle_empty) == [None]

    cycle_none = SoaCycle(truecost_tiers=None)
    assert truecost_sweep.resolve_tiers(cycle_none) == [None]
