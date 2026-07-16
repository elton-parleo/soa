"""
Tests for scoring/observation_scorer.py's merchant resolution logic —
the four-way attribution_status dispatch plus the "contrary retailer
signal" fallback rule — and check_attribution_rate's assertion formula.
Pure logic, no DB/API needed for _resolve_merchant.
"""
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scoring.observation_scorer import ObservationScorer, check_attribution_rate

SLUG_BY_MERCHANT_ID = {80: "pampers", 6: "target"}


def _obs(attribution_status, merchant_slug=None):
    return SimpleNamespace(attribution_status=attribution_status, merchant_slug=merchant_slug)


def _entity(merchant_id=None):
    return SimpleNamespace(merchant_id=merchant_id)


def test_mapped_resolves_directly():
    slug, status = ObservationScorer._resolve_merchant(
        _obs("mapped", "target"), _entity(), set(), SLUG_BY_MERCHANT_ID,
    )
    assert slug == "target"
    assert status == ""


def test_unmapped_skips_with_no_merchant_mapping_status():
    slug, status = ObservationScorer._resolve_merchant(
        _obs("unmapped"), _entity(), set(), SLUG_BY_MERCHANT_ID,
    )
    assert slug is None
    assert status == "no_merchant_mapping"


def test_brand_self_reference_skips():
    slug, status = ObservationScorer._resolve_merchant(
        _obs("brand_self_reference"), _entity(), set(), SLUG_BY_MERCHANT_ID,
    )
    assert slug is None
    assert status == "skipped"


def test_unattributed_with_no_entity_merchant_configured_skips():
    slug, status = ObservationScorer._resolve_merchant(
        _obs("unattributed"), _entity(merchant_id=None), set(), SLUG_BY_MERCHANT_ID,
    )
    assert slug is None
    assert status == "skipped"


def test_unattributed_falls_back_when_no_contrary_signal():
    slug, status = ObservationScorer._resolve_merchant(
        _obs("unattributed"), _entity(merchant_id=80), set(), SLUG_BY_MERCHANT_ID,
    )
    assert slug == "pampers"
    assert status == ""


def test_unattributed_does_not_fall_back_with_contrary_signal():
    # Same run has a confidently-mapped OTHER retailer -> too risky to
    # assume the entity's own brand site for this ambiguous observation.
    slug, status = ObservationScorer._resolve_merchant(
        _obs("unattributed"), _entity(merchant_id=80), {"target"}, SLUG_BY_MERCHANT_ID,
    )
    assert slug is None
    assert status == "skipped"


def test_unattributed_falls_back_when_contrary_signal_is_the_same_merchant():
    # The only "mapped" observation in this run IS the entity's own brand
    # site — not actually a contrary signal.
    slug, status = ObservationScorer._resolve_merchant(
        _obs("unattributed"), _entity(merchant_id=80), {"pampers"}, SLUG_BY_MERCHANT_ID,
    )
    assert slug == "pampers"
    assert status == ""


# --- check_attribution_rate ----------------------------------------------

@pytest.fixture
def Session():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
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
            CREATE TABLE soa_price_observations (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                stated_price FLOAT, claimed_net_price FLOAT, claimed_discount_value FLOAT,
                claimed_discount_pct FLOAT, claimed_terms TEXT, member_price_claimed BOOLEAN,
                subscription_offer_claimed BOOLEAN, merchant_name TEXT, merchant_slug TEXT,
                attribution_status TEXT, evidence TEXT, coding_pass_version INTEGER,
                created_at TIMESTAMP
            )
        """)
    return sessionmaker(bind=engine)


def _seed_observations(Session, cycle_id, statuses):
    """statuses: list of attribution_status strings, one row per entry."""
    from soa_shared.models.soa_models import SoaPriceObservation, SoaRun
    with Session() as session:
        session.add(SoaRun(id=1, cycle_id=cycle_id))
        for i, status in enumerate(statuses):
            session.add(SoaPriceObservation(
                run_id=1, entity_id=1, attribution_status=status, coding_pass_version=2,
            ))
        session.commit()


def test_resolution_rate_excludes_unattributed_and_brand_self_reference(Session):
    # Mirrors real cycle-55 shape: mapped=1343, unmapped=209 -> 1343/1552
    # regardless of the 439 unattributed + 81 brand_self_reference rows
    # also present.
    _seed_observations(Session, cycle_id=55, statuses=(
        ["mapped"] * 13 + ["unmapped"] * 2 + ["unattributed"] * 4 + ["brand_self_reference"] * 1
    ))
    with Session() as session:
        result = asyncio.run(check_attribution_rate(session, 55))

    assert result.status_counts == {
        "mapped": 13, "unmapped": 2, "unattributed": 4, "brand_self_reference": 1,
    }
    assert result.resolution_rate == pytest.approx(13 / 15)  # mapped / (mapped + unmapped)
    assert result.raw_mapped_share == pytest.approx(13 / 20)  # mapped / total


def test_resolution_rate_matches_real_cycle_55_numbers(Session):
    _seed_observations(Session, cycle_id=55, statuses=(
        ["mapped"] * 1343 + ["unmapped"] * 209 + ["unattributed"] * 439 + ["brand_self_reference"] * 81
    ))
    with Session() as session:
        result = asyncio.run(check_attribution_rate(session, 55))

    assert result.resolution_rate == pytest.approx(1343 / 1552, abs=1e-4)  # 86.5%, passes 80%
    assert result.raw_mapped_share == pytest.approx(1343 / 2072, abs=1e-4)  # 64.8%, logged only


def test_resolution_rate_zero_when_no_named_retailers_at_all(Session):
    _seed_observations(Session, cycle_id=55, statuses=["unattributed"] * 5)
    with Session() as session:
        result = asyncio.run(check_attribution_rate(session, 55))
    assert result.resolution_rate == 0.0
    assert result.raw_mapped_share == 0.0


def test_resolution_rate_scoped_to_cycle(Session):
    from soa_shared.models.soa_models import SoaPriceObservation, SoaRun
    with Session() as session:
        session.add(SoaRun(id=1, cycle_id=55))
        session.add(SoaRun(id=2, cycle_id=56))
        session.add(SoaPriceObservation(run_id=1, entity_id=1, attribution_status="mapped", coding_pass_version=2))
        session.add(SoaPriceObservation(run_id=2, entity_id=1, attribution_status="unmapped", coding_pass_version=2))
        session.commit()

    with Session() as session:
        result = asyncio.run(check_attribution_rate(session, 55))
    assert result.status_counts == {"mapped": 1}
    assert result.resolution_rate == 1.0
