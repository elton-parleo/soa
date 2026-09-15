"""
Drift guard for app/services/lite_score_batch.py.

The Audits list scores a whole page with six queries instead of six per
row, by gathering the same primitives in bulk and handing them to the
same lite_pillars.build_pillars_payload the public report calls. That is
only safe for as long as the two paths agree, so this file runs BOTH
over every cycle in the report fixtures and asserts the composite and
all three pillar scores are identical, scenario by scenario.

If you change build_cycle_report's composite branching (or the SQL
behind its primitives) without making the same change in
lite_score_batch, this file fails. Fix both or neither — the public
report at /r/{token} and the internal Audits list must never show a
different score for the same audit.
"""
import json

import pytest
from sqlalchemy import text

from tests.test_public_lite_report import (  # noqa: F401 — db is a fixture
    db,
    _V3_CRAWL_DIMENSIONS,
    _lite_request_id,
    _seed_scan_row,
    _seed_v3_full_credit_scan,
)
from tests.test_cycle_scoring_parity import _seed_program_less_scan

import app.routers.public_lite as public_lite
from app.services.cycle_scoring import build_cycle_report
from app.services.lite_score_batch import (
    SCORE_EXPIRED,
    pillar_breakdown,
    score_cycles,
)

_PILLARS = ("visibility", "accessibility", "true_value")


# ─── Extra scenarios, beyond the two the report fixtures already carry ───


def _seed_generic_cycle(
    conn, token, cycle_id, entity_id, *, scan=True, dimensions=None,
    scan_status="complete", total_score=80,
):
    slug = f"parity-{token}"
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_requests (token, status, cycle_id) VALUES (?, 'complete', ?)",
        (token, cycle_id),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (?, ?, ?, 'brand')",
        (entity_id, f"Brand {token}", slug),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) "
        "VALUES (?, ?, 'M001', 'primary')",
        (cycle_id, entity_id),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_metrics_results "
        "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
        " mention_rate, soa_pct, position_index, rsi_score) "
        "VALUES (?, ?, 'overall', 'overall', 4, 2, 0.5, 0.5, 1.0, 2.0)",
        (cycle_id, entity_id),
    )
    for offset, stage in enumerate(("Comparison", "Ready to Buy")):
        run_id = cycle_id * 100 + offset
        conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (?, ?)", (run_id, stage))
        conn.exec_driver_sql(
            "INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (?, ?, ?, 'success')",
            (run_id, cycle_id, run_id),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, deal_cited) "
            "VALUES (?, ?, 1, 0)",
            (run_id, entity_id),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_pass2_coding_log (run_id, coding_pass_version) VALUES (?, 2)",
            (run_id,),
        )
    if scan:
        _seed_scan_row(
            conn, _lite_request_id(conn, token), status=scan_status,
            total_score=total_score, dimensions=dimensions,
        )


def _stale_pillars_dimensions():
    """scorer_version "4" — pillars-capable but behind the current "5",
    which build_cycle_report retires to the 'expired' state."""
    dimensions = dict(_V3_CRAWL_DIMENSIONS)
    dimensions["scorer_version"] = "4"
    return dimensions


def _legacy_dimensions():
    """No scorer_version at all — defaults to "1", which was never
    pillars-shaped and keeps using the historical composite formula."""
    dimensions = {k: v for k, v in _V3_CRAWL_DIMENSIONS.items() if k != "scorer_version"}
    return dimensions


@pytest.fixture
def seeded(db):
    """Every scenario that can reach the scorer, in one database."""
    with db.begin() as conn:
        # 1. Current scorer version, full credit across every pillar.
        _seed_v3_full_credit_scan(conn, token="parity-healthy")
        # 2. Current scorer version, member_value N/A (the /92 rescale).
        _seed_program_less_scan(conn)
        # 3. Retired scorer version -> expired, no score at all.
        _seed_generic_cycle(
            conn, "parity-stale", cycle_id=71, entity_id=501,
            dimensions=_stale_pillars_dimensions(),
        )
        # 4. Pre-pillars scorer version -> historical 0.6/0.4 fallback.
        _seed_generic_cycle(
            conn, "parity-legacy", cycle_id=72, entity_id=502,
            dimensions=_legacy_dimensions(),
        )
        # 5. No scan row at all -> fallback with accessibility unknown.
        _seed_generic_cycle(conn, "parity-noscan", cycle_id=73, entity_id=503, scan=False)
        # 6. A blocked crawl at the current scorer version.
        blocked = dict(_V3_CRAWL_DIMENSIONS)
        blocked["catalog_context"] = {
            **(blocked.get("catalog_context") or {}), "coverage": "blocked",
        }
        _seed_generic_cycle(
            conn, "parity-blocked", cycle_id=74, entity_id=504,
            dimensions=blocked, scan_status="blocked",
        )
    return db


def _both_paths(engine):
    """(expected_by_cycle, actual_by_cycle) for every cycle in the DB."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, cycle_id FROM soa_lite_requests WHERE cycle_id IS NOT NULL"
        )).fetchall()

        scan_by_cycle = {}
        expected = {}
        for lite_request_id, cycle_id in rows:
            scan_row = public_lite._fetch_scan_row(conn, lite_request_id)
            # The identical input object goes to both paths.
            scan_tuple = tuple(scan_row) if scan_row is not None else None
            scan_by_cycle[cycle_id] = scan_tuple
            expected[cycle_id] = build_cycle_report(conn, cycle_id, scan_tuple)

        actual = score_cycles(conn, scan_by_cycle)

    assert expected, "fixture seeded no cycles — this test would prove nothing"
    return expected, actual


def test_every_fixture_cycle_scores_identically_on_both_paths(seeded):
    expected, actual = _both_paths(seeded)
    assert set(expected) == set(actual)

    for cycle_id, report in expected.items():
        batched = actual[cycle_id]

        if report.get("status") == "expired":
            assert batched["score_state"] == SCORE_EXPIRED, cycle_id
            assert batched["composite_score"] is None, cycle_id
            assert batched["pillars"] is None, cycle_id
            continue

        assert batched["composite_score"] == report.get("composite"), (
            f"composite diverged for cycle {cycle_id}"
        )

        report_pillars = report.get("pillars")
        batched_pillars = batched["pillars"]
        assert (report_pillars is None) == (batched_pillars is None), cycle_id
        if report_pillars is None:
            continue

        for pillar in _PILLARS:
            assert batched_pillars[pillar]["score"] == report_pillars[pillar]["score"], (
                f"{pillar} diverged for cycle {cycle_id}"
            )
        assert batched_pillars["member_value_na"] == report_pillars["member_value_na"], cycle_id
        assert batched_pillars["state"] == report_pillars["state"], cycle_id


def test_the_fixture_actually_covers_every_scoring_branch(seeded):
    """Guards the guard: a parity test that only ever exercised one
    branch would pass while proving almost nothing."""
    _, actual = _both_paths(seeded)
    states = {row["score_state"] for row in actual.values()}
    versions = {row["scorer_version"] for row in actual.values()}

    assert SCORE_EXPIRED in states, "no retired-scorer row in the fixture"
    assert "available" in states
    assert "5" in versions and "1" in versions, "both current and legacy scorers must be covered"
    assert any(row["pillars"] is not None for row in actual.values())
    assert any(row["pillars"] is None for row in actual.values())


def test_pillar_breakdown_reproduces_the_payloads_own_normalized_score(seeded):
    """
    The drawer shows "21 / 32" — raw earned over applicable max — which
    build_pillars_payload does not return; pillar_breakdown re-derives it
    from the dimension rows. This asserts the derivation is right, by
    checking it reproduces the one figure the payload DOES carry.
    """
    _, actual = _both_paths(seeded)
    checked = 0

    for cycle_id, row in actual.items():
        breakdown = pillar_breakdown(row["pillars"])
        if breakdown is None:
            continue
        for pillar in _PILLARS:
            earned = breakdown[pillar]["earned"]
            applicable_max = breakdown[pillar]["applicable_max"]
            expected_score = round(earned / applicable_max * 100) if applicable_max else 0
            assert expected_score == breakdown[pillar]["score"], (
                f"{pillar} breakdown does not reproduce its own score for cycle {cycle_id}: "
                f"{earned}/{applicable_max} -> {expected_score}, payload says {breakdown[pillar]['score']}"
            )
            assert earned <= applicable_max + 1e-6, f"{pillar} earned exceeds its applicable max"
            checked += 1

    assert checked, "no pillars in the fixture — this test would prove nothing"


def test_batched_path_issues_a_fixed_number_of_queries_regardless_of_page_size(seeded):
    """
    The whole reason this module exists: six statements for the whole
    page rather than six per row. Asserted by counting executions, so
    a future refactor that quietly reintroduces a per-row query fails
    here even though its output would still be correct.
    """
    statements = []

    with seeded.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, cycle_id FROM soa_lite_requests WHERE cycle_id IS NOT NULL"
        )).fetchall()
        scan_by_cycle = {
            cycle_id: tuple(public_lite._fetch_scan_row(conn, lite_request_id) or ()) or None
            for lite_request_id, cycle_id in rows
        }

        original_execute = conn.execute

        def counting_execute(statement, *args, **kwargs):
            statements.append(str(statement))
            return original_execute(statement, *args, **kwargs)

        conn.execute = counting_execute
        score_cycles(conn, scan_by_cycle)

    assert len(scan_by_cycle) >= 5, "need several cycles for this to mean anything"
    assert len(statements) <= 6, (
        f"expected at most 6 statements for the whole page, got {len(statements)}:\n"
        + "\n---\n".join(statements)
    )
