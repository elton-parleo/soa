"""
Regression tests for two bugs found and fixed while pressure-testing the
Actions v1 detector/mapper against cycle 55, plus a determinism check on
the detector entry point.

Uses a real in-memory SQLite database (matching the convention in
tests/test_truecost_snapshots_endpoint.py and apps/pipeline's
test_scope_resolution.py) rather than mocks, since finding_detector.py and
recommendation_mapper.py issue real ORM queries. Columns mirror every
column each ORM model declares (not just the ones a given test touches) —
the ORM SELECTs all mapped columns, so a narrower table fails with "no
such column" at query time. Base.metadata.create_all() is deliberately
not used here either, for the same reason documented in
apps/pipeline/tests/test_scope_resolution.py (double-index creation
errors on soa_cycles/soa_queries).
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.finding_detector as finding_detector
import app.services.recommendation_mapper as recommendation_mapper
from app.services.finding_detector import detect_vis_07, detect_findings
from app.services.recommendation_mapper import generate_recommendations
from soa_shared.models.soa_models import (
    SoaCycle,
    SoaFinding,
    SoaMetricsResult,
    SoaPlaybook,
    SoaRecommendation,
)


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
            CREATE TABLE soa_entities (
                id INTEGER PRIMARY KEY, name TEXT, slug TEXT, entity_type TEXT,
                category TEXT, merchant_id INTEGER, website_url TEXT, aliases TEXT,
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
            CREATE TABLE soa_coded_mentions (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                merchant_id INTEGER, mentioned BOOLEAN, position INTEGER,
                strength TEXT, deal_cited BOOLEAN, deal_types TEXT, evidence TEXT,
                coded_by TEXT, confidence FLOAT, needs_review BOOLEAN,
                reviewed_by TEXT, reviewed_at TIMESTAMP,
                created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_metrics_results (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                slice_type TEXT, slice_value TEXT, total_runs INTEGER,
                total_mentions INTEGER, mention_rate FLOAT, soa_pct FLOAT,
                position_index FLOAT, rsi_score FLOAT, deal_citation_rate FLOAT,
                platform_dist_index FLOAT, calculated_at TIMESTAMP
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
        conn.exec_driver_sql("""
            CREATE TABLE soa_playbook (
                play_id TEXT PRIMARY KEY, pillar TEXT, failure_mode TEXT,
                detection_trigger TEXT, dimensions TEXT, owner TEXT, play_text TEXT,
                mechanism_text TEXT, effort TEXT, expected_impact_text TEXT,
                evidence_spec TEXT, detector_status TEXT, active BOOLEAN,
                created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_findings (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                play_id TEXT, dimension TEXT, surface TEXT, persona TEXT, stage TEXT,
                severity FLOAT, cells_affected INTEGER, metric_snapshot TEXT,
                evidence_run_ids TEXT, created_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_recommendations (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, play_id TEXT,
                finding_ids TEXT, priority_score FLOAT, status TEXT,
                suppressed BOOLEAN, created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
    return sessionmaker(bind=engine)


@pytest.fixture
def patched_detector_session(Session, monkeypatch):
    monkeypatch.setattr(finding_detector, "session_factory", Session)
    return Session


@pytest.fixture
def patched_mapper_session(Session, monkeypatch):
    monkeypatch.setattr(recommendation_mapper, "session_factory", Session)
    return Session


def _make_cycle(Session, cycle_code="TC001", status="complete"):
    with Session() as session:
        cycle = SoaCycle(
            cycle_code=cycle_code, start_date=datetime.date(2026, 6, 1),
            status=status, organization_id=1, cycle_mode="query",
            study_type="brand_pampers", study_pattern="mixed",
            scope_is_custom=False,
        )
        session.add(cycle)
        session.commit()
        session.refresh(cycle)
        return cycle.id


def _add_metrics_row(Session, cycle_id, entity_id, slice_type, slice_value,
                      total_runs=10, mention_rate=0.5, position_index=0.5):
    with Session() as session:
        session.add(SoaMetricsResult(
            cycle_id=cycle_id, entity_id=entity_id, slice_type=slice_type,
            slice_value=slice_value, total_runs=total_runs,
            total_mentions=int(total_runs * mention_rate),
            mention_rate=mention_rate, position_index=position_index,
        ))
        session.commit()


# ---------------------------------------------------------------------------
# Test 1 — VIS-07 leader selection and gap direction
# ---------------------------------------------------------------------------

THRESHOLDS = {
    "presence_min": 0.60,
    "position_gap_min": 0.15,
    "min_deficient_surfaces": 1,
    "min_sample_size": 3,
}


def test_vis_07_picks_highest_position_index_as_leader(patched_detector_session):
    Session = patched_detector_session
    cycle_id = _make_cycle(Session)

    # entity 1: strong presence, high (best) position_index -> the leader.
    _add_metrics_row(Session, cycle_id, entity_id=1, slice_type="platform",
                      slice_value="chatgpt", mention_rate=0.90, position_index=0.85)
    # entity 2: also above the presence floor, but clearly trailing.
    _add_metrics_row(Session, cycle_id, entity_id=2, slice_type="platform",
                      slice_value="chatgpt", mention_rate=0.70, position_index=0.30)

    with Session() as session:
        drafts = detect_vis_07(cycle_id, session, THRESHOLDS)

    # Only the trailing entity gets a finding — never the leader.
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.entity_id == 2

    surface = draft.metric_snapshot["surfaces"]["chatgpt"]
    assert surface["leader_entity_id"] == 1  # highest position_index, not lowest
    # gap = leader.position_index - entity.position_index, must be positive
    # and match the two fixture values exactly (0.85 - 0.30).
    assert surface["gap"] == pytest.approx(0.55, abs=1e-4)
    assert surface["leader_position_index"] == pytest.approx(0.85, abs=1e-4)
    assert surface["position_index"] == pytest.approx(0.30, abs=1e-4)


def test_vis_07_leader_itself_gets_no_finding(patched_detector_session):
    """Inverse case: an entity that IS the leader must never get a finding,
    even though it clears presence_min — there's no one for it to be
    behind."""
    Session = patched_detector_session
    cycle_id = _make_cycle(Session)

    _add_metrics_row(Session, cycle_id, entity_id=1, slice_type="platform",
                      slice_value="chatgpt", mention_rate=0.90, position_index=0.85)
    _add_metrics_row(Session, cycle_id, entity_id=2, slice_type="platform",
                      slice_value="chatgpt", mention_rate=0.70, position_index=0.30)

    with Session() as session:
        drafts = detect_vis_07(cycle_id, session, THRESHOLDS)

    leader_drafts = [d for d in drafts if d.entity_id == 1]
    assert leader_drafts == []


# ---------------------------------------------------------------------------
# Test 2 — recommendation status preserved across regenerate
# ---------------------------------------------------------------------------

def _seed_playbook_row(Session, play_id="VIS-01", effort="low"):
    with Session() as session:
        session.add(SoaPlaybook(
            play_id=play_id, pillar="Visibility", failure_mode="x",
            detection_trigger="x", dimensions=["Presence"], owner="brand",
            play_text="x", mechanism_text="x", effort=effort,
            expected_impact_text="x", evidence_spec="x",
            detector_status="implemented", active=True,
        ))
        session.commit()


def _add_finding(Session, cycle_id, play_id="VIS-01", entity_id=1, severity=0.5, cells=1):
    with Session() as session:
        f = SoaFinding(
            cycle_id=cycle_id, entity_id=entity_id, play_id=play_id,
            dimension="Presence", severity=severity, cells_affected=cells,
            metric_snapshot={"x": 1}, evidence_run_ids=[1, 2, 3],
        )
        session.add(f)
        session.commit()
        session.refresh(f)
        return f.id


def test_recommendation_status_survives_regenerate_when_play_still_fires(patched_mapper_session):
    Session = patched_mapper_session
    cycle_id = _make_cycle(Session)
    _seed_playbook_row(Session, "VIS-01")
    _add_finding(Session, cycle_id, "VIS-01")

    summary1 = generate_recommendations(cycle_id)
    assert summary1 == {"VIS-01": 1}

    with Session() as session:
        rec = session.query(SoaRecommendation).filter_by(cycle_id=cycle_id).one()
        rec_id = rec.id
        rec.status = "accepted"
        session.commit()

    # Regenerate with the same finding still present.
    summary2 = generate_recommendations(cycle_id)
    assert summary2 == {"VIS-01": 1}

    with Session() as session:
        rec = session.get(SoaRecommendation, rec_id)
        assert rec is not None
        assert rec.id == rec_id  # same row, not a new one
        assert rec.status == "accepted"  # not reset to 'proposed'


def test_recommendation_deleted_when_its_play_stops_firing(patched_mapper_session):
    """Documents current behavior: when a play's findings disappear, its
    recommendation is deleted outright (not orphaned, not kept in a
    stale state) — generate_recommendations only keeps rows for plays
    that still have findings this run."""
    Session = patched_mapper_session
    cycle_id = _make_cycle(Session)
    _seed_playbook_row(Session, "VIS-01")
    finding_id = _add_finding(Session, cycle_id, "VIS-01")

    generate_recommendations(cycle_id)
    with Session() as session:
        rec = session.query(SoaRecommendation).filter_by(cycle_id=cycle_id).one()
        rec_id = rec.id
        rec.status = "accepted"
        session.commit()

    # The finding backing this play is gone — simulates a re-run where the
    # underlying metrics no longer trip VIS-01's trigger.
    with Session() as session:
        session.query(SoaFinding).filter_by(id=finding_id).delete()
        session.commit()

    summary = generate_recommendations(cycle_id)
    assert summary == {}

    with Session() as session:
        assert session.get(SoaRecommendation, rec_id) is None


# ---------------------------------------------------------------------------
# Test 3 — detect_findings is idempotent
# ---------------------------------------------------------------------------

def test_detect_findings_idempotent_on_unchanged_data(patched_detector_session):
    Session = patched_detector_session
    cycle_id = _make_cycle(Session)

    # Drives VIS-06 (persona variance): two personas, wide gap.
    _add_metrics_row(Session, cycle_id, entity_id=1, slice_type="persona",
                      slice_value="Value-Conscious", mention_rate=0.85, position_index=0.5)
    _add_metrics_row(Session, cycle_id, entity_id=1, slice_type="persona",
                      slice_value="Beauty Enthusiast", mention_rate=0.10, position_index=0.5)

    summary1 = detect_findings(cycle_id)
    with Session() as session:
        findings1 = session.query(SoaFinding).filter_by(cycle_id=cycle_id).order_by(SoaFinding.play_id).all()
        snapshot1 = [(f.play_id, f.entity_id, f.severity) for f in findings1]

    summary2 = detect_findings(cycle_id)
    with Session() as session:
        findings2 = session.query(SoaFinding).filter_by(cycle_id=cycle_id).order_by(SoaFinding.play_id).all()
        snapshot2 = [(f.play_id, f.entity_id, f.severity) for f in findings2]

    assert summary1 == summary2
    assert len(findings1) == len(findings2)
    assert snapshot1 == snapshot2
    assert summary1.get("VIS-06") == 1  # sanity: the fixture actually fired something
