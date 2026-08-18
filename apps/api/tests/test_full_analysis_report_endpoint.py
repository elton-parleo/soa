"""
Tests for GET /full-analysis/report/{cycle_code} (app/routers/
full_analysis.py::get_full_analysis_report) — the Phase 4 render-gate:
rendered=True only with an attached, complete crawl; otherwise
rendered=False with a reason, never a partial render. Calls the route
function directly, same pattern as test_full_analysis_router.py.
"""
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine

import app.routers.full_analysis as full_analysis_router
import soa_shared.config as config

CURRENT_USER = {"organization_id": 1, "user_id": "u1"}


@pytest.fixture
def patched_engine(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, cycle_code TEXT UNIQUE, organization_id INTEGER,
                source_lite_request_id INTEGER, platforms TEXT, runs_per_query INTEGER
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_scan_results (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, lite_request_id INTEGER,
                status TEXT, total_score INTEGER, integrity_capped BOOLEAN,
                dimensions TEXT, pages_fetched TEXT, membership_probe TEXT,
                revenue_probe TEXT, fetch_probe TEXT, input_url TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_entities (id INTEGER PRIMARY KEY, name TEXT, slug TEXT, website_url TEXT, aliases TEXT)
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycle_entities (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                comparison_code TEXT, role TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_metrics_results (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                slice_type TEXT, slice_value TEXT, total_runs INTEGER, total_mentions INTEGER,
                mention_rate FLOAT, soa_pct FLOAT, position_index FLOAT, rsi_score FLOAT,
                deal_citation_rate FLOAT, platform_dist_index FLOAT
            )
        """)
        conn.exec_driver_sql("CREATE TABLE soa_queries (id INTEGER PRIMARY KEY, stage TEXT, persona TEXT, query_text TEXT)")
        conn.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, query_id INTEGER, status TEXT, platform TEXT,
                raw_response TEXT, run_at TEXT, run_number INTEGER
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_coded_mentions (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                mentioned BOOLEAN, deal_cited BOOLEAN, deal_types TEXT, member_value_cited BOOLEAN,
                strength TEXT, evidence TEXT, position INTEGER
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_price_observations (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                stated_price FLOAT, claimed_net_price FLOAT, member_price_claimed BOOLEAN,
                merchant_name TEXT, merchant_slug TEXT, attribution_status TEXT
            )
        """)
        conn.exec_driver_sql("CREATE TABLE soa_pass2_coding_log (id INTEGER PRIMARY KEY, run_id INTEGER, coding_pass_version INTEGER)")
        conn.exec_driver_sql("""
            CREATE TABLE soa_incentive_scores (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER, price_observation_id INTEGER,
                scoring_grain TEXT, status TEXT, measurement_status TEXT,
                stated_price FLOAT, ground_truth_true_cost FLOAT,
                ground_truth_applied_deals TEXT, ground_truth_available_deals TEXT,
                net_price_accuracy BOOLEAN
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_requests (
                id INTEGER PRIMARY KEY, token TEXT UNIQUE, email TEXT, status TEXT, cycle_id INTEGER,
                competitor_names TEXT, competitor_source TEXT, created_at TIMESTAMP
            )
        """)
        # 3b: select_also_worth_doing's read-only source — AC3 Actions'
        # own tables (finding_detector.py/recommendation_mapper.py).
        # Deliberately empty in every fixture below unless a test seeds
        # a row itself: nothing generates these automatically.
        conn.exec_driver_sql("""
            CREATE TABLE soa_playbook (
                play_id TEXT PRIMARY KEY, pillar TEXT, failure_mode TEXT, owner TEXT, play_text TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_recommendations (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, play_id TEXT,
                priority_score FLOAT, status TEXT, suppressed BOOLEAN
            )
        """)
    monkeypatch.setattr(full_analysis_router, "engine", engine)
    return engine


_DIMENSIONS = {
    "scorer_version": "5",
    "agent_access": {"score": 5, "max": 5, "coverage": "full", "evidence": []},
    "catalog_context": {"score": 8, "max": 8, "coverage": "full", "evidence": []},
    "protocol_feed": {"score": 5, "max": 5, "coverage": "full", "evidence": []},
    "price_truth_seen": {"score": 7, "max": 7, "coverage": "full", "evidence": []},
    "member_value_seen": {"score": 5, "max": 5, "coverage": "full", "evidence": []},
    "deal_citability_seen": {"score": 7, "max": 7, "coverage": "full", "evidence": []},
    "value_protocols_seen": {"score": 14, "max": 14, "coverage": "full", "evidence": []},
    # A LIST of rows (apps/pipeline/scan/offer_feed.py::build_offer_feed's
    # real output shape) — seeded on every test in this file so the
    # actual FullAnalysisReportResponse(...) Pydantic construction always
    # exercises offers with real list data, not just None. Regression
    # guard: offers was typed Optional[dict] in schemas.py originally,
    # which 500'd with a ValidationError on every real request (dict_type,
    # "Input should be a valid dictionary") the instant a scored cycle
    # actually had offers — no test caught it because every fixture left
    # this key absent, so offers was always None and the mismatched type
    # never got validated against real data.
    "offers": [
        {"name": "List price", "value": "$110.00", "channel": "SCHEMA.ORG", "eligibility": "1 of 1", "freshness": "live", "readable": "seen"},
    ],
    "product_image_url": None,
    "product_name": "Men's Wool Runner",
}


def _seed_scored_cycle(conn, cycle_code="fc-1", cycle_id=10, org_id=1, source_lite_request_id=None):
    conn.exec_driver_sql(
        "INSERT INTO soa_cycles (id, cycle_code, organization_id, source_lite_request_id, platforms, runs_per_query) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (cycle_id, cycle_code, org_id, source_lite_request_id, json.dumps(["chatgpt", "gemini"]), 5),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (id, name, slug) VALUES (?, 'Full Cycle Brand', ?)",
        (cycle_id * 10 + 1, f"brand-{cycle_id}"),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (?, ?, 'M001', 'primary')",
        (cycle_id, cycle_id * 10 + 1),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_metrics_results "
        "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
        " mention_rate, soa_pct, position_index, rsi_score) "
        "VALUES (?, ?, 'overall', 'overall', 10, 10, 1.0, 1.0, 1.0, 3.0)",
        (cycle_id, cycle_id * 10 + 1),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_scan_results "
        "(cycle_id, lite_request_id, status, total_score, integrity_capped, dimensions, membership_probe, input_url) "
        "VALUES (?, NULL, 'complete', 100, 0, ?, ?, 'https://example.com')",
        (cycle_id, json.dumps(_DIMENSIONS), json.dumps({"result": "yes", "raw_evidence": None})),
    )
    for i in range(10):
        qid = cycle_id * 1000 + i
        platform = "chatgpt" if i % 2 == 0 else "gemini"
        conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (?, 'Ready to Buy')", (qid,))
        conn.exec_driver_sql(
            "INSERT INTO soa_runs (id, cycle_id, query_id, status, platform) VALUES (?, ?, ?, 'success', ?)",
            (qid, cycle_id, qid, platform),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, deal_cited, deal_types, member_value_cited, strength) "
            "VALUES (?, ?, 1, 1, ?, 1, 'Primary')",
            (qid, cycle_id * 10 + 1, json.dumps(["member_price"])),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_price_observations (run_id, entity_id, stated_price, member_price_claimed) VALUES (?, ?, 10.0, 1)",
            (qid, cycle_id * 10 + 1),
        )
        conn.exec_driver_sql("INSERT INTO soa_pass2_coding_log (run_id, coding_pass_version) VALUES (?, 2)", (qid,))
        conn.exec_driver_sql(
            "INSERT INTO soa_incentive_scores "
            "(run_id, entity_id, scoring_grain, status, measurement_status, stated_price, "
            " ground_truth_true_cost, ground_truth_applied_deals, ground_truth_available_deals, net_price_accuracy) "
            "VALUES (?, ?, 'observation', 'scored', 'measured', 10.0, 8.5, ?, '[]', 0)",
            (qid, cycle_id * 10 + 1, json.dumps([{"id": "promo"}])),
        )


def test_renders_true_for_a_cycle_with_a_complete_crawl(patched_engine):
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn)

    result = full_analysis_router.get_full_analysis_report("fc-1", current_user=CURRENT_USER)

    assert result.rendered is True
    assert result.composite == 100
    assert result.verdict == "AGENT-READY"
    assert result.scorer_version == "6"
    assert result.continuation is None

    # Phase 1: the full payload schema, end to end — every new key
    # present and shaped from real seeded rows, nothing hardcoded.
    assert {r["platform"] for r in result.platform_matrix} == {"chatgpt", "gemini"}
    chatgpt_row = next(r for r in result.platform_matrix if r["platform"] == "chatgpt")
    assert chatgpt_row["share_of_mentions"]["value"] == 100.0  # only entity tracked, always mentioned
    assert chatgpt_row["recommendation_strength_band"] == "1st + endorsed"  # strength='Primary' seeded
    assert chatgpt_row["price_truth_said"]["state"] == "measured"
    assert chatgpt_row["price_truth_said"]["value"] == 0.0  # net_price_accuracy=0 seeded throughout

    assert result.competitor_set["overall"][0]["entity"] == "Full Cycle Brand"
    assert result.scan["status"] == "complete"
    assert result.revenue_estimate_usd is None  # no revenue_probe seeded this cycle
    # Regression guard (see _DIMENSIONS' own comment): offers must build
    # as a real Pydantic list, not silently coerce/reject a list where a
    # dict was expected.
    assert result.offers == _DIMENSIONS["offers"]
    assert result.product_name == "Men's Wool Runner"
    # Every seeded dimension is already at full credit (score == max) —
    # nothing to fix, so an honestly empty list, not a fabricated one.
    # Ranked fixes live on pillars['fixes'] (FixesTable.jsx's real
    # read path), not a separate top-level field.
    assert result.pillars["fixes"] == {"visible": [], "remaining_count": 0, "also_worth_doing": []}
    assert result.evidence is not None
    assert result.evidence["price_observation"]["accurate"] is False


def test_falls_back_to_classic_when_no_crawl_attached(patched_engine):
    with patched_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_cycles (id, cycle_code, organization_id) VALUES (11, 'no-crawl', 1)"
        )

    result = full_analysis_router.get_full_analysis_report("no-crawl", current_user=CURRENT_USER)

    assert result.rendered is False
    assert result.reason == "no crawl attached yet"
    assert result.pillars is None


def test_404_for_unknown_or_foreign_cycle(patched_engine):
    with pytest.raises(HTTPException) as exc_info:
        full_analysis_router.get_full_analysis_report("nope", current_user=CURRENT_USER)
    assert exc_info.value.status_code == 404


def test_continuation_banner_present_when_cycle_traces_back_to_an_audit(patched_engine):
    with patched_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (id, token, status, cycle_id, created_at) "
            "VALUES (5, 'audit-tok', 'complete', 20, '2026-07-01 00:00:00')"
        )
        _seed_scored_cycle(conn, cycle_code="fc-continuation", cycle_id=20, source_lite_request_id=5)

    result = full_analysis_router.get_full_analysis_report("fc-continuation", current_user=CURRENT_USER)

    assert result.rendered is True
    assert result.continuation is not None
    assert result.continuation.source_lite_request_id == 5
    assert result.continuation.audit_composite == 100
    assert result.continuation.audit_date == "2026-07-01"
    assert "chatgpt" in result.continuation.audit_platforms_note
    # This fixture's soa_lite_scan_results row is keyed by cycle_id, not
    # lite_request_id (_fetch_scan_row's actual lookup key) — the audit
    # side of _build_continuation resolves no scan row here, so pillars
    # stays unset and pillar_deltas is None. _compute_pillar_deltas
    # itself (the real 1f logic) is covered directly in
    # test_full_analysis_extras.py, not through this heavier fixture.
    assert result.continuation.pillar_deltas is None


def test_continuation_banner_absent_for_a_cycle_created_the_ordinary_way(patched_engine):
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn, cycle_code="fc-ordinary", cycle_id=30, source_lite_request_id=None)

    result = full_analysis_router.get_full_analysis_report("fc-ordinary", current_user=CURRENT_USER)

    assert result.rendered is True
    assert result.continuation is None


# ─── Part A: generated pillar headlines, extended to Full Analysis ────────

def test_generated_headlines_reach_the_full_analysis_report_when_present(patched_engine):
    headlines = {
        "visibility": {"headline": "You hold 35% share of all brand mentions.", "source": "generated"},
        "accessibility": {"headline": "Agent Access earns 5 of 5 points.", "source": "generated"},
        "true_value": {"headline": "Price Truth earns full points on your site.", "source": "generated"},
    }
    dims = {**_DIMENSIONS, "generated_headlines": headlines}
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn, cycle_code="fc-headlines", cycle_id=50)
        conn.exec_driver_sql(
            "UPDATE soa_lite_scan_results SET dimensions = ? WHERE cycle_id = 50", (json.dumps(dims),),
        )

    result = full_analysis_router.get_full_analysis_report("fc-headlines", current_user=CURRENT_USER)

    assert result.rendered is True
    assert result.generated_headlines == headlines


def test_generated_headlines_null_when_the_sweep_has_not_reached_this_cycle_yet(patched_engine):
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn, cycle_code="fc-no-headlines", cycle_id=51)

    result = full_analysis_router.get_full_analysis_report("fc-no-headlines", current_user=CURRENT_USER)

    assert result.rendered is True
    assert result.generated_headlines is None


# ─── "From the transcript" widget — same service as the lite report ───────

def test_transcript_wired_into_the_full_analysis_report(patched_engine, monkeypatch):
    # Pinned explicitly (not relying on the ambient config.py default) —
    # this test's whole point is the OFF state, so it must hold
    # regardless of which branch/deploy it runs on.
    monkeypatch.setattr(config, "TRANSCRIPT_NARRATIVE_ENABLED", False)
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn, cycle_code="fc-transcript", cycle_id=40)
        # _seed_scored_cycle's own runs never set raw_response — give
        # exactly one of them a verbatim answer so select_transcript has
        # something to pick.
        conn.exec_driver_sql(
            "UPDATE soa_runs SET raw_response = 'Full Cycle Brand is the top pick here.', run_at = '2026-08-07' "
            "WHERE id = 40000"
        )

    result = full_analysis_router.get_full_analysis_report("fc-transcript", current_user=CURRENT_USER)

    assert result.rendered is True
    assert result.transcript is not None
    assert result.transcript["run_id"] == 40000
    assert "Full Cycle Brand" in result.transcript["response_text"]
    # TRANSCRIPT_NARRATIVE_ENABLED defaults off — same gate, same
    # service, as the lite report (see test_public_lite_report.py's
    # equivalent pair of tests).
    assert "right" not in result.transcript
    assert "leaked" not in result.transcript


def test_transcript_narrative_boxes_present_when_the_flag_is_on(patched_engine, monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIPT_NARRATIVE_ENABLED", True)
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn, cycle_code="fc-transcript-on", cycle_id=41)
        conn.exec_driver_sql(
            "UPDATE soa_runs SET raw_response = 'Full Cycle Brand is the top pick here.', run_at = '2026-08-07' "
            "WHERE id = 41000"
        )

    result = full_analysis_router.get_full_analysis_report("fc-transcript-on", current_user=CURRENT_USER)

    assert result.transcript["right"]
    assert result.transcript["leaked"]


# ─── 1a: continuation cycles inherit the audit's own revenue seed ─────────

def test_continuation_cycle_inherits_the_audits_own_revenue_estimate(patched_engine):
    """The continuation cycle's own scan row never gets a revenue_probe
    (apps/pipeline/worker.py::process_cycle_crawls skips it deliberately
    for a continuation, to avoid a second OpenAI call for the same
    brand) — the audit's own lite-owned scan row already has one."""
    with patched_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (id, token, status, cycle_id, created_at) "
            "VALUES (6, 'audit-tok-2', 'complete', 21, '2026-07-01 00:00:00')"
        )
        # The audit's OWN scan row — keyed by lite_request_id, not the
        # continuation cycle's cycle_id, exactly like a real audit run.
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_scan_results (lite_request_id, cycle_id, status, revenue_probe, input_url) "
            "VALUES (6, NULL, 'complete', ?, 'https://example.com')",
            (json.dumps({"annual_revenue_usd": 42_000_000.0, "basis": "estimated", "quote": None}),),
        )
        _seed_scored_cycle(conn, cycle_code="fc-continuation-revenue", cycle_id=21, source_lite_request_id=6)

    result = full_analysis_router.get_full_analysis_report("fc-continuation-revenue", current_user=CURRENT_USER)

    assert result.rendered is True
    assert result.revenue_estimate_usd == 42_000_000.0


def test_continuation_cycle_with_no_audit_revenue_probe_stays_null(patched_engine):
    with patched_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (id, token, status, cycle_id, created_at) "
            "VALUES (7, 'audit-tok-3', 'complete', 22, '2026-07-01 00:00:00')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_scan_results (lite_request_id, cycle_id, status, input_url) "
            "VALUES (7, NULL, 'complete', 'https://example.com')"
        )
        _seed_scored_cycle(conn, cycle_code="fc-continuation-no-revenue", cycle_id=22, source_lite_request_id=7)

    result = full_analysis_router.get_full_analysis_report("fc-continuation-no-revenue", current_user=CURRENT_USER)

    assert result.rendered is True
    assert result.revenue_estimate_usd is None


def test_non_continuation_cycle_never_looks_up_an_audit_revenue_estimate(patched_engine):
    """A standalone cycle (source_lite_request_id is None) has no audit
    to fall back to — its own (null, in this fixture) revenue_probe is
    the only source, never a lookup by coincidental id."""
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn, cycle_code="fc-standalone", cycle_id=23, source_lite_request_id=None)

    result = full_analysis_router.get_full_analysis_report("fc-standalone", current_user=CURRENT_USER)

    assert result.rendered is True
    assert result.revenue_estimate_usd is None
