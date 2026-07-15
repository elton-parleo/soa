"""
Tests for the validity gate: measurement_status on soa_incentive_scores
and its consumption by TVD-01/TVD-03 and compute_coverage_gaps().

An 'unmeasured' row is one where the Deal Engine had no deal data at all
for that merchant/category and echoed the input price back as
ground_truth_true_cost — a 0% gap that looks like perfect accuracy but is
not a real measurement. These tests document that:
  1. A cell where every row is unmeasured never fires TVD-01/TVD-03 and
     is reported as an insufficient-coverage gap instead of a compliant
     (0% gap) cell.
  2. A mixed cell (some measured, some unmeasured) computes findings only
     over the measured rows.
  3. compute_coverage_gaps() only flags cells with zero measured rows,
     not cells that have at least one measured row (even if others in
     the same cell are unmeasured).

Uses a real in-memory SQLite database, same convention as
test_actions_regressions.py — columns mirror every column the ORM model
declares, since the ORM SELECTs all mapped columns.
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.finding_detector import compute_coverage_gaps, detect_tvd_01, detect_tvd_03
from soa_shared.models.soa_models import SoaCycle, SoaIncentiveScore, SoaQuery, SoaRun


@pytest.fixture
def Session():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, cycle_code TEXT UNIQUE, start_date DATE,
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
            CREATE TABLE soa_queries (
                id INTEGER PRIMARY KEY, query_code TEXT, query_text TEXT,
                category TEXT, stage TEXT, specificity TEXT, persona TEXT,
                soa_focus TEXT, rationale TEXT, status TEXT,
                study_type TEXT, study_pattern TEXT, organization_id INTEGER,
                created_by TEXT, membership_program TEXT, tier_name TEXT,
                subscription_state TEXT, expected_incentive TEXT, new_customer BOOLEAN,
                created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, query_id INTEGER,
                platform TEXT, run_number INTEGER, run_at TIMESTAMP,
                raw_response TEXT, response_tokens INTEGER, latency_ms INTEGER,
                status TEXT, error_message TEXT, search_triggered BOOLEAN,
                retrieved_sources TEXT, created_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_incentive_scores (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                merchant_id INTEGER, merchant_slug TEXT, price_observation_id INTEGER,
                scoring_grain TEXT DEFAULT 'legacy',
                scope_sku_id INTEGER, dealengine_listing_id INTEGER,
                stated_price FLOAT, claimed_net_price FLOAT, claimed_discount_value FLOAT,
                claimed_discount_pct FLOAT, claimed_terms TEXT, member_price_claimed BOOLEAN,
                subscription_offer_claimed BOOLEAN, ground_truth_true_cost FLOAT,
                ground_truth_applied_deals TEXT, ground_truth_available_deals TEXT,
                ground_truth_confidence FLOAT,
                user_tier_name TEXT, net_price_reflected BOOLEAN, net_price_accuracy BOOLEAN,
                term_fidelity FLOAT, member_price_reflected BOOLEAN, status TEXT,
                measurement_status TEXT,
                error_message TEXT, created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
    return sessionmaker(bind=engine)


def _make_cycle(Session, cycle_code="TC-VG"):
    with Session() as session:
        cycle = SoaCycle(
            cycle_code=cycle_code, start_date=datetime.date(2026, 6, 1),
            status="complete", organization_id=1, cycle_mode="query",
            study_type="brand_pampers", study_pattern="mixed",
            scope_is_custom=False,
        )
        session.add(cycle)
        session.commit()
        session.refresh(cycle)
        return cycle.id


def _make_run(Session, cycle_id, query_id=None, platform="chatgpt"):
    with Session() as session:
        run = SoaRun(cycle_id=cycle_id, query_id=query_id, platform=platform, status="success")
        session.add(run)
        session.commit()
        session.refresh(run)
        return run.id


def _make_account_linked_query(Session, tier_name="Gold"):
    with Session() as session:
        q = SoaQuery(query_text="x", status="active", tier_name=tier_name)
        session.add(q)
        session.commit()
        session.refresh(q)
        return q.id


def _add_score(
    Session, run_id, entity_id, merchant_slug, stated_price, true_cost,
    measurement_status, applied_deals=None, member_price_reflected=None,
):
    with Session() as session:
        session.add(SoaIncentiveScore(
            run_id=run_id, entity_id=entity_id, merchant_slug=merchant_slug,
            scoring_grain="observation", status="scored",
            stated_price=stated_price, ground_truth_true_cost=true_cost,
            ground_truth_applied_deals=applied_deals or [],
            measurement_status=measurement_status,
            member_price_reflected=member_price_reflected,
        ))
        session.commit()


TVD01_THRESHOLDS = {"price_gap_pct_min": 0.05, "min_sample_size": 2}
TVD03_THRESHOLDS = {"min_sample_size": 2}


def test_tvd01_skips_cell_with_only_unmeasured_rows(Session):
    """An echo-only cell (engine had zero deal data every time) must never
    be read as a compliant 0% gap — TVD-01 should not fire on it at all."""
    cycle_id = _make_cycle(Session)
    run1 = _make_run(Session, cycle_id)
    run2 = _make_run(Session, cycle_id)

    # stated_price way above true_cost, but true_cost is just an echo
    # (measurement_status='unmeasured') — would look like a huge gap if
    # read naively, but must be excluded entirely.
    _add_score(Session, run1, entity_id=1, merchant_slug="rite-aid",
               stated_price=20.0, true_cost=20.0, measurement_status="unmeasured",
               applied_deals=[{"id": 1}])
    _add_score(Session, run2, entity_id=1, merchant_slug="rite-aid",
               stated_price=20.0, true_cost=20.0, measurement_status="unmeasured",
               applied_deals=[{"id": 1}])

    with Session() as session:
        drafts = detect_tvd_01(cycle_id, session, TVD01_THRESHOLDS)

    assert drafts == []


def test_tvd01_computes_only_over_measured_rows_in_mixed_cell(Session):
    """A cell with both measured and unmeasured rows must fire (or not)
    based solely on the measured subset."""
    cycle_id = _make_cycle(Session)
    run1 = _make_run(Session, cycle_id)
    run2 = _make_run(Session, cycle_id)
    run3 = _make_run(Session, cycle_id)

    # Two measured, overpriced rows (20% gap, active promo) -> should fire.
    _add_score(Session, run1, entity_id=1, merchant_slug="amazon",
               stated_price=24.0, true_cost=20.0, measurement_status="measured",
               applied_deals=[{"id": 1}])
    _add_score(Session, run2, entity_id=1, merchant_slug="amazon",
               stated_price=24.0, true_cost=20.0, measurement_status="measured",
               applied_deals=[{"id": 1}])
    # One unmeasured row in the same cell, priced to look "compliant" if
    # it leaked in (stated == true_cost) — must not dilute the overpriced
    # rate computed from the measured rows.
    _add_score(Session, run3, entity_id=1, merchant_slug="amazon",
               stated_price=20.0, true_cost=20.0, measurement_status="unmeasured",
               applied_deals=[{"id": 1}])

    with Session() as session:
        drafts = detect_tvd_01(cycle_id, session, TVD01_THRESHOLDS)

    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.metric_snapshot["n_active_promo_scored_observations"] == 2
    assert draft.metric_snapshot["n_overpriced"] == 2
    assert draft.metric_snapshot["overpriced_rate"] == pytest.approx(1.0)


def test_tvd03_skips_cell_with_only_unmeasured_rows(Session):
    cycle_id = _make_cycle(Session)
    query_id = _make_account_linked_query(Session)
    run1 = _make_run(Session, cycle_id, query_id=query_id)
    run2 = _make_run(Session, cycle_id, query_id=query_id)

    _add_score(Session, run1, entity_id=1, merchant_slug="rite-aid",
               stated_price=10.0, true_cost=10.0, measurement_status="unmeasured",
               member_price_reflected=False)
    _add_score(Session, run2, entity_id=1, merchant_slug="rite-aid",
               stated_price=10.0, true_cost=10.0, measurement_status="unmeasured",
               member_price_reflected=False)

    with Session() as session:
        drafts = detect_tvd_03(cycle_id, session, TVD03_THRESHOLDS)

    assert drafts == []


def test_coverage_gaps_flags_cell_with_zero_measured_rows(Session):
    cycle_id = _make_cycle(Session)
    run1 = _make_run(Session, cycle_id)
    run2 = _make_run(Session, cycle_id)

    _add_score(Session, run1, entity_id=1, merchant_slug="rite-aid",
               stated_price=10.0, true_cost=10.0, measurement_status="unmeasured")
    _add_score(Session, run2, entity_id=1, merchant_slug="rite-aid",
               stated_price=12.0, true_cost=12.0, measurement_status="unmeasured")

    with Session() as session:
        gaps = compute_coverage_gaps(cycle_id, session)

    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["entity_id"] == 1
    assert gap["merchant_slug"] == "rite-aid"
    assert gap["scored_rows"] == 2
    assert gap["measured_rows"] == 0
    assert gap["status"] == "insufficient_ground_truth_coverage"


def test_coverage_gaps_does_not_flag_cell_with_at_least_one_measured_row(Session):
    """A cell is only a coverage gap when NONE of its rows were measured —
    a mixed cell has real ground-truth signal, even if partial, so it must
    not be reported as insufficient coverage."""
    cycle_id = _make_cycle(Session)
    run1 = _make_run(Session, cycle_id)
    run2 = _make_run(Session, cycle_id)

    _add_score(Session, run1, entity_id=1, merchant_slug="amazon",
               stated_price=20.0, true_cost=20.0, measurement_status="measured")
    _add_score(Session, run2, entity_id=1, merchant_slug="amazon",
               stated_price=22.0, true_cost=20.0, measurement_status="unmeasured")

    with Session() as session:
        gaps = compute_coverage_gaps(cycle_id, session)

    assert gaps == []
