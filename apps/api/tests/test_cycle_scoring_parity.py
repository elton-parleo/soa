"""
Phase 3a snapshot parity: proves app/services/cycle_scoring.py's
extraction out of public_lite.py is behavior-preserving — GET
/api/public/soa-lite/{token}/report returns the same shape and values
after the extraction as it did when _build_report_payload computed
everything inline.

Two scenarios, per the extraction plan: one healthy (full credit across
every pillar) and one with member_value N/A + the composite normalized
onto the reduced /85 basis (Part 4 P4) — reusing the exact seed helpers
test_public_lite_report.py already exercises these scenarios with, so
this isn't a second, drifting definition of "healthy"/"N/A" fixtures.
These assertions were captured by running the same seeds against the
pre-extraction code; keep them as regression tests — any future change
to scoring output shape must be a deliberate SCORER_VERSION bump
(Phase 3b), never a silent drift caught only here.
"""
import json

from tests.test_public_lite_report import (  # noqa: F401 — db is a fixture
    db,
    _V3_CRAWL_DIMENSIONS,
    _lite_request_id,
    _seed_v3_full_credit_scan,
)

import app.routers.public_lite as public_lite


def test_healthy_full_credit_report_matches_pre_extraction_snapshot(db):
    with db.begin() as conn:
        _seed_v3_full_credit_scan(conn, token="parity-healthy")

    report = public_lite.get_lite_report("parity-healthy")

    assert report["status"] == "complete"
    assert report["composite"] == 100
    assert report["pillars"]["verdict"] == "AGENT-READY"
    assert report["pillars"]["true_value"]["score"] == 100
    assert report["pillars"]["member_value_na"] is False
    assert report["visibility_breakdown"]["totals"]["total_mentions"] == 2
    assert report["overall"][0]["metrics"]["som"] == 100.0
    assert report["competitor_source"] is None


def test_na_member_value_report_matches_pre_extraction_snapshot(db):
    with db.begin() as conn:
        _seed_program_less_scan(conn)

    report = public_lite.get_lite_report("parity-na")

    assert report["status"] == "complete"
    assert report["composite"] == 100  # /85 basis (Part 4 P4) — see docstring
    assert report["pillars"]["member_value_na"] is True
    member_value_row = next(d for d in report["pillars"]["true_value"]["dimensions"] if d["code"] == "member_value")
    assert member_value_row["na"] is True
    assert member_value_row["earned"] == 0.0


def _seed_program_less_scan(conn):
    """Mirrors test_public_lite_report.py::
    test_v3_program_less_store_normalizes_member_value_na_onto_81's own
    seed, at a distinct token/cycle/entity id so the two test files'
    fixtures never collide when both run in the same session."""
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_requests (token, email, status, cycle_id) "
        "VALUES ('parity-na', 'visitor@example.com', 'complete', 61)"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (401, 'Program-less Store', 'programless-parity', 'brand')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (61, 401, 'M001', 'primary')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_metrics_results "
        "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
        " mention_rate, soa_pct, position_index, rsi_score) "
        "VALUES (61, 401, 'overall', 'overall', 2, 2, 1.0, 1.0, 1.0, 3.0)"
    )
    no_program_dimensions = dict(_V3_CRAWL_DIMENSIONS)
    no_program_dimensions["member_value_seen"] = {
        "score": 0, "max": 12, "coverage": "full",
        "evidence": ["no loyalty/rewards page found in nav/footer"],
    }
    rid = _lite_request_id(conn, "parity-na")
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_scan_results "
        "(lite_request_id, status, total_score, integrity_capped, dimensions, membership_probe) "
        "VALUES (?, 'complete', 81, 0, ?, ?)",
        (rid, json.dumps(no_program_dimensions), json.dumps({"result": "no", "raw_evidence": None})),
    )
    for qid, stage in [(9210, 'Comparison'), (9211, 'Ready to Buy'), (9212, 'Comparison'), (9213, 'Ready to Buy')]:
        conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (?, ?)", (qid, stage))
        conn.exec_driver_sql("INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (?, 61, ?, 'success')", (qid, qid))
        conn.exec_driver_sql(
            "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, deal_cited, deal_types, member_value_cited) "
            "VALUES (?, 401, 1, 1, ?, 1)",
            (qid, json.dumps(["member_price"])),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_price_observations (run_id, entity_id, stated_price, member_price_claimed) "
            "VALUES (?, 401, 10.0, 1)",
            (qid,),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_pass2_coding_log (run_id, coding_pass_version) VALUES (?, 2)", (qid,),
        )
