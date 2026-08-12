"""
Tests for Full Analysis coexistence, Phase 4 backend — the report-copy
assembly layer (app/services/full_analysis_extras.py) and the per-pillar
continuation delta (app/routers/full_analysis.py::_compute_pillar_deltas).
Each builder is a group-by/lookup over stored rows; these tests seed two
platforms (one with a blocked crawler) and assert the matrix, competitor
stage slices, fix ranking, and evidence selection all read real numbers,
never a hardcoded/estimated one.
"""
import json

import pytest
from sqlalchemy import create_engine, text

from app.routers.full_analysis import _compute_pillar_deltas
from app.services.full_analysis_extras import (
    build_competitor_set,
    build_fixes,
    build_platform_matrix,
    build_what_if,
    select_evidence_exemplar,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_entities (id INTEGER PRIMARY KEY, name TEXT, slug TEXT, website_url TEXT)
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycle_entities (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                comparison_code TEXT, role TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_queries (id INTEGER PRIMARY KEY, stage TEXT, persona TEXT, query_text TEXT)
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, query_id INTEGER, status TEXT, platform TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_coded_mentions (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                mentioned BOOLEAN, deal_cited BOOLEAN, deal_types TEXT,
                member_value_cited BOOLEAN, strength TEXT, evidence TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_price_observations (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                stated_price FLOAT, member_price_claimed BOOLEAN
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_incentive_scores (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                scoring_grain TEXT, status TEXT, measurement_status TEXT,
                stated_price FLOAT, ground_truth_true_cost FLOAT,
                ground_truth_applied_deals TEXT, ground_truth_available_deals TEXT,
                net_price_accuracy BOOLEAN
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_metrics_results (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                slice_type TEXT, slice_value TEXT, total_mentions INTEGER
            )
        """)
    return engine


CYCLE_ID = 900
PRIMARY_ID = 901
COMPETITOR_ID = 902


def _seed_entities(conn):
    conn.exec_driver_sql("INSERT INTO soa_entities (id, name, slug) VALUES (?, 'Allbirds', 'allbirds')", (PRIMARY_ID,))
    conn.exec_driver_sql("INSERT INTO soa_entities (id, name, slug) VALUES (?, 'Nike', 'nike')", (COMPETITOR_ID,))
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (?, ?, 'M001', 'primary')",
        (CYCLE_ID, PRIMARY_ID),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (?, ?, 'M002', 'competitor')",
        (CYCLE_ID, COMPETITOR_ID),
    )


def _run(conn, run_id, platform, stage="Ready to Buy", persona="Value-Conscious", query_text="Q?"):
    conn.exec_driver_sql(
        "INSERT INTO soa_queries (id, stage, persona, query_text) VALUES (?, ?, ?, ?)",
        (run_id, stage, persona, query_text),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_runs (id, cycle_id, query_id, status, platform) VALUES (?, ?, ?, 'success', ?)",
        (run_id, CYCLE_ID, run_id, platform),
    )


# ─── 1a: platform matrix ───────────────────────────────────────────────────

def test_platform_matrix_two_platforms_one_blocked_crawler(db):
    with db.begin() as conn:
        _seed_entities(conn)
        # chatgpt: primary named-pick, admitted crawler, accurate price
        _run(conn, 1, "chatgpt")
        conn.exec_driver_sql(
            "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, deal_cited, strength) VALUES (1, ?, 1, 1, 'Primary')",
            (PRIMARY_ID,),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, deal_cited) VALUES (1, ?, 1, 0)",
            (COMPETITOR_ID,),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_incentive_scores (run_id, entity_id, scoring_grain, status, measurement_status, "
            " stated_price, ground_truth_true_cost, ground_truth_applied_deals, ground_truth_available_deals, net_price_accuracy) "
            "VALUES (1, ?, 'observation', 'scored', 'measured', 100, 98, '[]', '[]', 1)",
            (PRIMARY_ID,),
        )
        # a second chatgpt run — price_truth_said needs >= MIN_OPPORTUNITY_
        # SET_MENTIONS measured observations before it reports a rate
        # rather than an honest 'na' (too few to mean anything).
        _run(conn, 3, "chatgpt")
        conn.exec_driver_sql(
            "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, deal_cited) VALUES (3, ?, 1, 0)",
            (PRIMARY_ID,),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, deal_cited) VALUES (3, ?, 1, 0)",
            (COMPETITOR_ID,),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_incentive_scores (run_id, entity_id, scoring_grain, status, measurement_status, "
            " stated_price, ground_truth_true_cost, ground_truth_applied_deals, ground_truth_available_deals, net_price_accuracy) "
            "VALUES (3, ?, 'observation', 'scored', 'measured', 100, 98, '[]', '[]', 1)",
            (PRIMARY_ID,),
        )
        # perplexity: primary mentioned but never the named pick, blocked crawler
        _run(conn, 2, "perplexity")
        conn.exec_driver_sql(
            "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, deal_cited) VALUES (2, ?, 1, 0)",
            (PRIMARY_ID,),
        )

    dimensions_raw = {
        "agent_access_matrix": [
            {"agent": "ChatGPT-User", "platform": "OpenAI", "root": "allowed", "product_pages": "allowed"},
            {"agent": "PerplexityBot", "platform": "Perplexity", "root": "blocked", "product_pages": "blocked"},
        ],
    }

    with db.connect() as conn:
        matrix = build_platform_matrix(conn, CYCLE_ID, PRIMARY_ID, dimensions_raw)

    assert {r["platform"] for r in matrix} == {"chatgpt", "perplexity"}
    chatgpt = next(r for r in matrix if r["platform"] == "chatgpt")
    perplexity = next(r for r in matrix if r["platform"] == "perplexity")

    assert chatgpt["agent_access"] == "allowed"
    assert chatgpt["recommendation_strength_band"] == "1st + endorsed"
    assert chatgpt["share_of_mentions"]["value"] == 50.0  # 1 of 2 total mentions on this platform
    assert chatgpt["price_truth_said"]["state"] == "measured"
    assert chatgpt["price_truth_said"]["value"] == 100.0  # net_price_accuracy=1

    assert perplexity["agent_access"] == "blocked"
    assert perplexity["recommendation_strength_band"] == "Listed"  # mentioned, never Primary
    assert perplexity["price_truth_said"]["state"] == "na"  # no incentive_scores rows at all


def test_platform_matrix_unknown_agent_access_when_platform_has_no_known_crawler(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, "gemini")
        conn.exec_driver_sql(
            "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned) VALUES (1, ?, 1)", (PRIMARY_ID,),
        )

    with db.connect() as conn:
        # No agent_access_matrix at all — an honest 'unknown', never a
        # guessed allowed/blocked.
        matrix = build_platform_matrix(conn, CYCLE_ID, PRIMARY_ID, {})

    assert matrix[0]["agent_access"] == "unknown"


def test_platform_matrix_never_includes_a_platform_the_cycle_did_not_run(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, "claude")
        conn.exec_driver_sql(
            "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned) VALUES (1, ?, 1)", (PRIMARY_ID,),
        )

    with db.connect() as conn:
        matrix = build_platform_matrix(conn, CYCLE_ID, PRIMARY_ID, {})

    assert [r["platform"] for r in matrix] == ["claude"]


# ─── 1b: competitor set (overall + by_stage) ──────────────────────────────

def test_competitor_set_overall_and_by_stage(db):
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results (cycle_id, entity_id, slice_type, slice_value, total_mentions) "
            "VALUES (?, ?, 'stage', 'Awareness', 40)",
            (CYCLE_ID, PRIMARY_ID),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results (cycle_id, entity_id, slice_type, slice_value, total_mentions) "
            "VALUES (?, ?, 'stage', 'Awareness', 60)",
            (CYCLE_ID, COMPETITOR_ID),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results (cycle_id, entity_id, slice_type, slice_value, total_mentions) "
            "VALUES (?, ?, 'stage', 'Ready to Buy', 10)",
            (CYCLE_ID, PRIMARY_ID),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results (cycle_id, entity_id, slice_type, slice_value, total_mentions) "
            "VALUES (?, ?, 'stage', 'Ready to Buy', 90)",
            (CYCLE_ID, COMPETITOR_ID),
        )
        _seed_entities(conn)

    overall_entity_info = {"M001": {"name": "Allbirds", "role": "primary"}, "M002": {"name": "Nike", "role": "competitor"}}
    overall_metrics = {
        "M001": {"total_mentions": 30, "total_runs": 100},
        "M002": {"total_mentions": 70, "total_runs": 100},
    }

    with db.connect() as conn:
        cs = build_competitor_set(conn, CYCLE_ID, overall_entity_info, overall_metrics)

    overall_primary = next(r for r in cs["overall"] if r["is_primary"])
    assert overall_primary["share_pct"] == 30.0

    awareness_primary = next(r for r in cs["by_stage"]["Awareness"] if r["is_primary"])
    assert awareness_primary["share_pct"] == 40.0  # 40/(40+60)

    ready_primary = next(r for r in cs["by_stage"]["Ready to Buy"] if r["is_primary"])
    assert ready_primary["share_pct"] == 10.0  # 10/(10+90) — the funnel leak the mock's headline describes


# ─── 1e: ranked fixes ──────────────────────────────────────────────────────

def test_build_fixes_ranks_by_gap_and_skips_dimensions_with_nothing_to_fix():
    dimensions_raw = {
        "agent_access": {"score": 5, "max": 5, "coverage": "full", "fix_human": "should never appear"},  # at max — skipped
        "catalog_context": {"score": 3, "max": 8, "coverage": "full", "fix_human": "Add structured data."},
        "deal_citability_seen": {"score": 0, "max": 7, "coverage": "full", "fix_human": "Expose your promotions."},
        "value_protocols_seen": {"score": 10, "max": 14, "coverage": "na", "fix_human": "should never appear (na)"},
    }
    fixes = build_fixes(dimensions_raw)

    assert [f["code"] for f in fixes] == ["deal_citability_seen", "catalog_context"]  # gap 7 then gap 5
    assert fixes[0]["modeled_points"] == 7.0
    assert fixes[0]["body"] == "Expose your promotions."
    assert fixes[0]["owner"] in ("ENG", "TRUESYNC")


def test_build_fixes_empty_when_nothing_has_a_real_gap():
    dimensions_raw = {"agent_access": {"score": 5, "max": 5, "coverage": "full", "fix_human": "n/a"}}
    assert build_fixes(dimensions_raw) == []


# ─── 1g: evidence exemplar determinism ────────────────────────────────────

def test_evidence_exemplar_selects_the_largest_price_gap_deterministically(db):
    with db.begin() as conn:
        _seed_entities(conn)
        for run_id, stated, truth in [(1, 100, 90), (2, 150, 100), (3, 105, 100)]:
            _run(conn, run_id, "perplexity", persona="Value-Conscious", query_text=f"Q{run_id}?")
            conn.exec_driver_sql(
                "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, evidence) VALUES (?, ?, 1, ?)",
                (run_id, PRIMARY_ID, f"evidence-{run_id}"),
            )
            conn.exec_driver_sql(
                "INSERT INTO soa_incentive_scores (run_id, entity_id, scoring_grain, status, measurement_status, "
                " stated_price, ground_truth_true_cost, ground_truth_applied_deals, ground_truth_available_deals, net_price_accuracy) "
                "VALUES (?, ?, 'observation', 'scored', 'measured', ?, ?, '[{\"id\":1}]', '[{\"id\":2}]', 0)",
                (run_id, PRIMARY_ID, stated, truth),
            )

    with db.connect() as conn:
        evidence = select_evidence_exemplar(conn, CYCLE_ID, PRIMARY_ID)

    assert evidence["run_id"] == 2  # 50% gap — the worst offender
    assert evidence["price_observation"]["delta_pct"] == 50.0
    assert evidence["price_observation"]["accurate"] is False
    assert evidence["uncited_eligible_offers"] == 1
    assert evidence["answer_excerpt"] == "evidence-2"


def test_evidence_exemplar_none_when_nothing_is_inaccurate(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, "chatgpt")
        conn.exec_driver_sql(
            "INSERT INTO soa_incentive_scores (run_id, entity_id, scoring_grain, status, measurement_status, "
            " stated_price, ground_truth_true_cost, net_price_accuracy) "
            "VALUES (1, ?, 'observation', 'scored', 'measured', 100, 100, 1)",
            (PRIMARY_ID,),
        )

    with db.connect() as conn:
        assert select_evidence_exemplar(conn, CYCLE_ID, PRIMARY_ID) is None


# ─── 1h: what-if (optional) ────────────────────────────────────────────────

def test_what_if_extends_ready_to_buy_share_when_present():
    competitor_set = {"by_stage": {"Ready to Buy": [{"name": "Allbirds", "is_primary": True, "share_pct": 15.0}]}}
    what_if = build_what_if(competitor_set)
    assert what_if["illustrative"] is True
    assert what_if["current_share_pct"] == 15.0
    assert what_if["illustrative_share_pct"] > what_if["current_share_pct"]


def test_what_if_omitted_when_no_ready_to_buy_stage_data():
    assert build_what_if({"by_stage": {}}) is None
    assert build_what_if({}) is None


# ─── 1f: continuation per-pillar deltas ───────────────────────────────────

def test_pillar_deltas_comparable_dimensions_get_a_real_delta():
    audit = {"visibility": {"score": 40}, "accessibility": {"score": 60}, "true_value": {"score": 20}}
    full = {"visibility": {"score": 55}, "accessibility": {"score": 60}, "true_value": {"score": 38}}

    deltas = {d["pillar"]: d for d in _compute_pillar_deltas(audit, full)}

    assert deltas["visibility"]["comparable"] is True
    assert deltas["visibility"]["delta"] == 15
    assert deltas["accessibility"]["delta"] == 0
    # true_value is never comparable — the rate-band rescore at
    # full-cycle volume makes a point delta misleading, even though
    # both scores are present.
    assert deltas["true_value"]["comparable"] is False
    assert deltas["true_value"]["delta"] is None


def test_pillar_deltas_not_comparable_when_a_score_is_missing():
    audit = {"visibility": {"score": None}, "accessibility": {}, "true_value": {"score": 20}}
    full = {"visibility": {"score": 55}, "accessibility": {"score": 60}, "true_value": {"score": 38}}

    deltas = {d["pillar"]: d for d in _compute_pillar_deltas(audit, full)}
    assert deltas["visibility"]["comparable"] is False
    assert deltas["accessibility"]["comparable"] is False
