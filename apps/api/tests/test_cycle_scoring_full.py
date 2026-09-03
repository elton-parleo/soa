"""
Tests for Full Analysis coexistence, Phase 3b — full-cycle scoring
under FULL_CYCLE_SCORER_VERSION: the new rate-banded deal_citability
said scorer, the envelope shape, and build_full_cycle_report scored
end-to-end. Mirrors the parametrize/boundary-case style of
test_scan_dimensions_parity.py.
"""
import json

import pytest
from sqlalchemy import create_engine, text

import app.services.cycle_scoring_full as cycle_scoring_full
from app.services.cycle_scoring_full import (
    STATE_MEASURED,
    STATE_NA,
    STATE_NOT_MEASURED,
    _build_full_fixes_section,
    build_full_cycle_pillars,
    build_full_cycle_report,
    said_result_to_envelope,
    score_deal_citability_said_full,
)
from app.services.lite_crosswalk import RunSignal
from tests.test_lite_pillars import (  # noqa: F401 — fixture reuse, not re-tested here
    _FULL_CRAWL_DIMS,
    _SIX_FIX_CRAWL_DIMS,
    _NO_MANIFEST_VP_CRAWL_DIMS,
    _full_credit_signals,
    _no_manifest_signals,
)
from soa_shared.scan_dimensions import (
    DEAL_CITABILITY_RATE_BAND_TABLE,
    FULL_CYCLE_SCORER_VERSION,
    SCORER_VERSION,
    DIMENSIONS_BY_CODE,
    PILLAR_WEIGHTS,
    apply_deal_citability_rate_band,
)


# ─── SCORER_VERSION distinctness ──────────────────────────────────────────

def test_full_cycle_scorer_version_is_distinct_from_lite():
    """Never the same string — a full-cycle report and a lite report
    must never compare equal on scorer_version, or a version-gate
    written for one could accidentally accept the other's row."""
    assert FULL_CYCLE_SCORER_VERSION != SCORER_VERSION


def test_full_cycle_scoring_reuses_the_same_registry_weights():
    """Weight-ordering invariant, mirrored from test_scan_dimensions_
    parity.py: Phase 3b does not reweight anything — the registry
    build_full_cycle_pillars reads is the exact same DIMENSIONS_BY_CODE/
    PILLAR_WEIGHTS lite reads, so True Value still carries half the
    composite and member_value is still the lowest-weighted True Value
    dimension."""
    assert PILLAR_WEIGHTS["true_value"] == 50
    assert DIMENSIONS_BY_CODE["member_value"].weight < DIMENSIONS_BY_CODE["deal_citability"].weight
    assert DIMENSIONS_BY_CODE["member_value"].weight < DIMENSIONS_BY_CODE["value_protocols"].weight


# ─── Rate-band boundary cases ─────────────────────────────────────────────

@pytest.mark.parametrize("rate_pct,expected_fraction", [
    (0, 0.0),
    (0.01, 0.40),
    (24.99, 0.40),
    (25, 0.40),
    (25.01, 0.70),
    (49.99, 0.70),
    (50, 0.70),
    (50.01, 1.0),
    (100, 1.0),
    (None, 0.0),
])
def test_apply_deal_citability_rate_band_edges(rate_pct, expected_fraction):
    assert apply_deal_citability_rate_band(rate_pct) == expected_fraction


def test_deal_citability_rate_band_table_is_monotonically_increasing():
    fractions = [f for _, f in DEAL_CITABILITY_RATE_BAND_TABLE]
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1.0


def _signal(stage="Ready to Buy", mentioned=True, deal_cited=False):
    return RunSignal(stage=stage, primary_mentioned=mentioned, primary_deal_cited=deal_cited)


def test_deal_citability_said_full_saturates_at_full_cycle_volume_where_count_band_would_not():
    """The volume-invariance point of Phase 3b: 200 purchase-intent
    mentions with only 20% citing a deal is a WEAK signal, but lite's
    count table would have scored 20 raw citations as max (4+ -> 100%).
    The rate table correctly bands this as the low tier instead."""
    signals = [_signal(deal_cited=(i < 40)) for i in range(200)]  # 40/200 = 20%
    result = score_deal_citability_said_full(signals)
    assert result["na"] is False
    assert result["cited"] == 40
    assert result["total"] == 200
    assert result["your_value"] == 20.0
    # 20% falls in the (0, 25] band -> 0.40 fraction of said_max (5)
    assert result["earned"] == round(0.40 * DIMENSIONS_BY_CODE["deal_citability"].said_max)


def test_deal_citability_said_full_rewards_a_high_rate_regardless_of_raw_volume():
    signals = [_signal(deal_cited=(i < 150)) for i in range(200)]  # 75%
    result = score_deal_citability_said_full(signals)
    assert result["your_value"] == 75.0
    assert result["earned"] == DIMENSIONS_BY_CODE["deal_citability"].said_max  # 100% band


def test_deal_citability_said_full_na_below_min_opportunity_set():
    result = score_deal_citability_said_full([_signal(mentioned=False)])
    assert result["na"] is True
    assert result["earned"] == 0.0


# ─── Envelope shape ────────────────────────────────────────────────────────

def test_envelope_measured_state():
    said = {"na": False, "cited": 30, "total": 100, "evidence": ["30/100 (30%) cited a deal"]}
    env = said_result_to_envelope(said)
    assert env == {"value": 30.0, "numerator": 30, "denominator": 100, "state": STATE_MEASURED}


def test_envelope_na_state_for_thin_opportunity_set():
    said = {"na": True, "evidence": ["fewer than 2 mentions in the relevant opportunity set"]}
    env = said_result_to_envelope(said)
    assert env["state"] == STATE_NA
    assert env["value"] is None


def test_envelope_not_measured_state_for_zero_denominator():
    said = {"na": False, "cited": 0, "total": 0, "evidence": []}
    env = said_result_to_envelope(said)
    assert env["state"] == STATE_NOT_MEASURED
    assert env["value"] is None


# ─── Ranked fixes (1e) ─────────────────────────────────────────────────────
#
# _build_full_fixes_section is the full-cycle counterpart to lite_
# pillars.py::_build_fixes_section — same {visible, remaining_count}
# shape FixesTable.jsx reads for both reports, same ranking rule
# (opportunity size, max - earned, descending, code tiebreak), but
# WITHOUT lite's FREE_FIX_VISIBLE_RANK=2 truncation or forced-TrueSync-
# swap: this is the paid, unlocked report, so remaining_count is always
# 0 and every fixable dimension is visible.

def _dim(code, earned, max_, fix_human="Fix it.", na=False, blocked=False):
    return {"code": code, "name": code, "earned": earned, "max": max_, "na": na, "blocked": blocked, "fix_human": fix_human}


def test_full_fixes_section_ranks_by_gap_descending():
    dims = [
        _dim("catalog_context", 3, 8),   # gap 5
        _dim("deal_citability", 0, 7),   # gap 7
        # At max — the scan engine never writes fix_human for a
        # dimension with nothing to fix, same real-world shape as
        # test_full_analysis_report_endpoint.py's _DIMENSIONS fixture.
        _dim("agent_access", 5, 5, fix_human=None),
    ]
    fixes = _build_full_fixes_section(dims)
    assert [f["code"] for f in fixes["visible"]] == ["deal_citability", "catalog_context"]
    assert fixes["visible"][0]["impact"] == 7.0
    assert fixes["visible"][0]["fix_owner"] == DIMENSIONS_BY_CODE["deal_citability"].fix_owner


def test_full_fixes_section_never_truncates_or_hides_anything():
    """Unlike lite's FREE_FIX_VISIBLE_RANK=2 cap, the paid report shows
    every fixable dimension — remaining_count is always 0."""
    dims = [_dim(code, 0, 5) for code in ("agent_access", "catalog_context", "protocol_feed", "value_protocols")]
    fixes = _build_full_fixes_section(dims)
    assert len(fixes["visible"]) == 4
    assert fixes["remaining_count"] == 0


def test_full_fixes_section_skips_na_blocked_and_nothing_to_fix():
    dims = [
        _dim("agent_access", 0, 5, na=True),
        _dim("catalog_context", 0, 5, blocked=True),
        _dim("protocol_feed", 5, 5, fix_human=None),  # at max, no fix text either
    ]
    assert _build_full_fixes_section(dims) == {"visible": [], "remaining_count": 0}


def test_full_fixes_section_carries_empty_sub_fixes_when_dims_have_no_checks_key():
    """_dim() below never sets 'checks' — the hand-built fixture style
    every other test in this section uses — so sub_fixes must default to
    an empty list, not KeyError, and every one of those tests stays
    valid unchanged."""
    dims = [_dim("deal_citability", 0, 7)]
    fixes = _build_full_fixes_section(dims)
    assert fixes["visible"][0]["sub_fixes"] == []


def test_sub_fixes_derive_from_failed_checks_only():
    dims = [{
        **_dim("catalog_context", 3, 8),
        "checks": [
            {"code": "product_data", "label": "l1", "state": "pass"},
            {"code": "completeness", "label": "l2", "state": "fail", "evidence": None},
            {"code": "identifiers", "label": "l3", "state": "na"},
        ],
    }]
    fixes = _build_full_fixes_section(dims)
    assert [s["code"] for s in fixes["visible"][0]["sub_fixes"]] == ["completeness"]


def test_sub_fixes_share_parent_fix_owner_and_carry_no_invented_points():
    dims = [{
        **_dim("deal_citability", 0, 7),
        "checks": [{"code": "concrete_amount", "label": "l", "state": "fail", "evidence": "e"}],
    }]
    fixes = _build_full_fixes_section(dims)
    sub = fixes["visible"][0]["sub_fixes"][0]
    assert sub["fix_owner"] == DIMENSIONS_BY_CODE["deal_citability"].fix_owner
    assert "impact" not in sub and "points" not in sub
    assert sub["evidence"] == "e"


# ─── True Value checks[] wiring (3b) ───────────────────────────────────────
#
# Before this, a full-cycle report's True Value dims never got a checks[]
# array at all — accessibility_dims got it for free via the shared
# _crawl_dim_row, but true_value_dims (built inline in build_full_cycle_
# pillars) never called lite_pillars.py's _price_truth_checks/_member_
# value_checks/_deal_citability_checks/_value_protocols_checks. Reusing
# those functions unchanged is presentation-only — it must never move
# earned/max/composite (guarded by the existing end-to-end/reconciliation
# tests below still passing unchanged).

def test_true_value_dims_now_carry_checks_like_accessibility_already_did():
    result = build_full_cycle_pillars(
        som_pct=100.0, rsi_score=3.0, total_mentions=6, total_queries=6,
        crawl_dimensions=_SIX_FIX_CRAWL_DIMS, run_signals=_full_credit_signals(),
        membership_probe_result="yes",
    )
    for d in result["true_value"]["dimensions"]:
        if d["na"]:
            continue
        assert d["checks"] is not None, f"{d['code']} should carry structured checks, like accessibility already does"


def test_member_value_na_dim_still_has_no_live_checks():
    # member_value_applicable is False only when NEITHER signal found a
    # program: probe didn't say 'yes' AND the crawl's own seen score is
    # 0 — _NO_MANIFEST_VP_CRAWL_DIMS's member_value_seen.score=3 doesn't
    # hit that (crawl alone makes it applicable), so this test builds
    # its own minimal fixture rather than reusing that one.
    crawl = {**_SIX_FIX_CRAWL_DIMS, "member_value_seen": {"score": 0, "max": 5, "coverage": "full"}}
    result = build_full_cycle_pillars(
        som_pct=100.0, rsi_score=3.0, total_mentions=6, total_queries=6,
        crawl_dimensions=crawl, run_signals=_full_credit_signals(),
        membership_probe_result="no",
    )
    mv = next(d for d in result["true_value"]["dimensions"] if d["code"] == "member_value")
    assert mv["na"] is True
    assert mv["checks"] is None


def test_fetch_probe_flows_into_price_truth_checks_evidence_line():
    """fetch_probe_result (build_full_cycle_report's own scan_row[7],
    now threaded through the same way it already reaches lite's
    build_pillars_payload) reaches _price_truth_checks — the
    price_in_code check's evidence line carries ChatGPT's own fetch-
    probe sentence when a probe ran."""
    probe = {"kind": "product", "outcome": "quoted_price", "price": "$42.00", "url": "https://example.com/p/1"}
    result = build_full_cycle_pillars(
        som_pct=100.0, rsi_score=3.0, total_mentions=6, total_queries=6,
        crawl_dimensions=_SIX_FIX_CRAWL_DIMS, run_signals=_full_credit_signals(),
        membership_probe_result="yes", fetch_probe_result=probe,
    )
    pt = next(d for d in result["true_value"]["dimensions"] if d["code"] == "price_truth")
    price_check = next(c for c in pt["checks"] if c["code"] == "price_in_code")
    assert price_check.get("evidence") and "$42.00" in price_check["evidence"]


def test_full_fixes_section_shares_lite_pillars_is_fixable_gap_floor():
    """_build_full_fixes_section used to carry its own inline eligibility
    filter (na/blocked/fix_human, no gap floor) instead of calling
    lite_pillars._is_fixable — harmless only because the scorer never
    emits a sub-0.05 gap with real fix_human text, i.e. correct by luck,
    not by construction. Now that it imports _is_fixable directly, a
    dimension a rounding error away from full credit (gap 0.02, under
    the 0.05 floor) is excluded here exactly like it already is on the
    lite side."""
    dims = [
        _dim("catalog_context", 7.98, 8),  # gap 0.02, under the 0.05 floor
        _dim("deal_citability", 0, 7),
    ]
    fixes = _build_full_fixes_section(dims)
    assert [f["code"] for f in fixes["visible"]] == ["deal_citability"]


# ─── N/A member-value rescale at full-cycle volume ────────────────────────

def test_full_cycle_pillars_member_value_na_still_normalizes_composite_onto_reduced_basis():
    """Same /92 (not /100) normalization as lite's Part 4 P4 — a
    program-less store at FULL-CYCLE volume (hundreds of mentions, not
    a handful) must still be excluded from member_value entirely, not
    scored as zero, and the composite must still reach 100 when every
    OTHER applicable dimension earns full credit."""
    crawl_dimensions = {
        "agent_access": {"score": 5, "max": 5, "coverage": "full", "evidence": []},
        "catalog_context": {"score": 8, "max": 8, "coverage": "full", "evidence": []},
        "protocol_feed": {"score": 5, "max": 5, "coverage": "full", "evidence": []},
        "price_truth_seen": {"score": 7, "max": 7, "coverage": "full", "evidence": []},
        "member_value_seen": {"score": 0, "max": 5, "coverage": "full", "evidence": []},
        "deal_citability_seen": {"score": 7, "max": 7, "coverage": "full", "evidence": []},
        "value_protocols_seen": {"score": 14, "max": 14, "coverage": "full", "evidence": []},
    }
    # 300 purchase-intent mentions, all citing a price and a deal — full
    # credit on price_truth.said and deal_citability.said at volume no
    # lite audit could ever reach.
    signals = [
        RunSignal(
            stage="Ready to Buy", primary_mentioned=True, primary_deal_cited=True,
            primary_price_quoted=True, pass2_coded=True,
        )
        for _ in range(300)
    ]

    pillars = build_full_cycle_pillars(
        som_pct=100.0, rsi_score=3.0, total_mentions=300, total_queries=300,
        crawl_dimensions=crawl_dimensions, run_signals=signals,
        membership_probe_result="no",
    )

    assert pillars["member_value_na"] is True
    assert pillars["composite"] == 100
    assert pillars["scorer_version"] == FULL_CYCLE_SCORER_VERSION
    member_value_row = next(d for d in pillars["true_value"]["dimensions"] if d["code"] == "member_value")
    assert member_value_row["na"] is True
    assert member_value_row["earned"] == 0.0


# ─── End-to-end: build_full_cycle_report ──────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_scan_results (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, lite_request_id INTEGER,
                status TEXT, total_score INTEGER, integrity_capped BOOLEAN,
                dimensions TEXT, pages_fetched TEXT, membership_probe TEXT,
                revenue_probe TEXT, fetch_probe TEXT, input_url TEXT
            )
        """)
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
            CREATE TABLE soa_metrics_results (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                slice_type TEXT, slice_value TEXT, total_runs INTEGER, total_mentions INTEGER,
                mention_rate FLOAT, soa_pct FLOAT, position_index FLOAT, rsi_score FLOAT,
                deal_citation_rate FLOAT, platform_dist_index FLOAT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_queries (id INTEGER PRIMARY KEY, stage TEXT)
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_runs (id INTEGER PRIMARY KEY, cycle_id INTEGER, query_id INTEGER, status TEXT)
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_coded_mentions (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                mentioned BOOLEAN, deal_cited BOOLEAN, deal_types TEXT, member_value_cited BOOLEAN
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_price_observations (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                stated_price FLOAT, claimed_net_price FLOAT, member_price_claimed BOOLEAN
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_pass2_coding_log (id INTEGER PRIMARY KEY, run_id INTEGER, coding_pass_version INTEGER)
        """)
    return engine


_FULL_CYCLE_DIMENSIONS = {
    "scorer_version": "5",
    "agent_access": {"score": 5, "max": 5, "coverage": "full", "evidence": []},
    "catalog_context": {"score": 8, "max": 8, "coverage": "full", "evidence": []},
    "protocol_feed": {"score": 5, "max": 5, "coverage": "full", "evidence": []},
    "price_truth_seen": {"score": 7, "max": 7, "coverage": "full", "evidence": []},
    "member_value_seen": {"score": 5, "max": 5, "coverage": "full", "evidence": []},
    "deal_citability_seen": {"score": 7, "max": 7, "coverage": "full", "evidence": []},
    "value_protocols_seen": {"score": 14, "max": 14, "coverage": "full", "evidence": []},
}


def test_build_full_cycle_report_scores_end_to_end(db):
    with db.begin() as conn:
        conn.exec_driver_sql("INSERT INTO soa_entities (id, name, slug) VALUES (501, 'Full Cycle Brand', 'full-cycle-brand')")
        conn.exec_driver_sql(
            "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (77, 501, 'M001', 'primary')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score) "
            "VALUES (77, 501, 'overall', 'overall', 40, 40, 1.0, 1.0, 1.0, 3.0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_scan_results "
            "(cycle_id, lite_request_id, status, total_score, integrity_capped, dimensions, membership_probe, input_url) "
            "VALUES (77, NULL, 'complete', 100, 0, ?, ?, 'https://full-cycle-brand.example.com')",
            (json.dumps(_FULL_CYCLE_DIMENSIONS), json.dumps({"result": "yes", "raw_evidence": None})),
        )
        for i in range(40):
            qid = 5000 + i
            stage = "Ready to Buy" if i % 2 == 0 else "Comparison"
            conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (?, ?)", (qid, stage))
            conn.exec_driver_sql("INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (?, 77, ?, 'success')", (qid, qid))
            conn.exec_driver_sql(
                "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, deal_cited, deal_types, member_value_cited) "
                "VALUES (?, 501, 1, 1, ?, 1)",
                (qid, json.dumps(["member_price"])),
            )
            conn.exec_driver_sql(
                "INSERT INTO soa_price_observations (run_id, entity_id, stated_price, member_price_claimed) "
                "VALUES (?, 501, 10.0, 1)",
                (qid,),
            )
            conn.exec_driver_sql("INSERT INTO soa_pass2_coding_log (run_id, coding_pass_version) VALUES (?, 2)", (qid,))

    with db.connect() as conn:
        report = build_full_cycle_report(conn, 77)

    assert report["status"] == "complete"
    assert report["scorer_version"] == FULL_CYCLE_SCORER_VERSION
    assert report["total_queries"] == 40
    assert report["pillars"]["composite"] == 100
    assert report["pillars"]["verdict"] == "AGENT-READY"
    assert report["pillars"]["member_value_na"] is False
    dc_row = next(d for d in report["pillars"]["true_value"]["dimensions"] if d["code"] == "deal_citability")
    assert dc_row["said_envelope"]["state"] == STATE_MEASURED
    # Both seeded stages (Ready to Buy, Comparison) are purchase-intent —
    # all 40 runs land in deal_citability's opportunity set.
    assert dc_row["said_envelope"]["denominator"] == 40
    # TrueValueSection.jsx reads both of these directly (state to pick
    # its "why not agent-ready" vs "verdict withheld" branch, tv_pct for
    # the former's copy) — a complete, scored full-cycle report is
    # always 'scored', never withheld.
    assert report["pillars"]["state"] == "scored"
    assert report["pillars"]["tv_pct"] == 100
    # FixableHook.jsx's headline band — every dimension is at full
    # credit in this fixture, so nothing is TrueSync-fixable this run.
    assert report["pillars"]["gap_areas_total"] == 4
    assert report["pillars"]["gap_areas_parleo_fixes"] == 2
    assert report["pillars"]["parleo_fixable_points"] == 0.0


def test_build_full_cycle_report_not_scored_without_a_complete_crawl(db):
    report = build_full_cycle_report(db.connect(), 999)
    assert report["status"] == "not_scored"


# ─── 2b, extended: the same guard over full-cycle fixtures ────────────────
#
# test_lite_pillars.py's test_every_truesync_gap_on_every_fixture_carries_
# a_fix_human guards build_pillars_payload against a TrueSync-owned
# dimension with a real, measured gap but no fix_human — the exact defect
# 3f92fab fixed (a dimension like that inflates the headline pool while
# being unrankable). That guard never ran build_full_cycle_pillars, so a
# future scorer change could reintroduce the same shape on the full-cycle
# path without either guard catching it. Reuses the lite fixtures
# directly (same crawl_dimensions/run_signals shape both scorers read)
# rather than duplicating them.

def test_every_truesync_gap_on_every_full_cycle_fixture_carries_a_fix_human():
    fixtures = {
        "full credit": (_FULL_CRAWL_DIMS, _full_credit_signals()),
        "six fixes": (_SIX_FIX_CRAWL_DIMS, _full_credit_signals()),
        "no manifest": (_NO_MANIFEST_VP_CRAWL_DIMS, _no_manifest_signals()),
    }
    for label, (crawl, signals) in fixtures.items():
        result = build_full_cycle_pillars(
            som_pct=100.0, rsi_score=3.0, total_mentions=4, total_queries=4,
            crawl_dimensions=crawl, run_signals=signals,
            membership_probe_result="yes",
        )
        for d in result["true_value"]["dimensions"] + result["accessibility"]["dimensions"]:
            if DIMENSIONS_BY_CODE[d["code"]].fix_owner != "TRUESYNC":
                continue
            if d["na"] or d.get("blocked"):
                continue
            gap = d["max"] - d["earned"]
            if gap < 0.05:
                continue
            assert d.get("fix_human"), (
                f"{label}: {d['code']} has a {gap:.1f}-point fixable gap but no fix_human — "
                "it would count toward the full-cycle headline's TrueSync pool while being unrankable"
            )


def test_no_manifest_fixture_reconciles_on_the_full_cycle_path_too():
    """The invariant 3f92fab pinned for lite (VP ranks #1 at its full
    gap, the ranked list's visible TrueSync impact equals the pool) held
    by construction there because _build_fixes_section and
    _parleo_fixable_points already shared _is_fixable. Pins the same
    reconciliation on build_full_cycle_pillars now that
    _build_full_fixes_section shares it too."""
    result = build_full_cycle_pillars(
        som_pct=100.0, rsi_score=3.0, total_mentions=4, total_queries=4,
        crawl_dimensions=_NO_MANIFEST_VP_CRAWL_DIMS, run_signals=_no_manifest_signals(),
        membership_probe_result="yes",
    )
    visible = result["fixes"]["visible"]
    assert visible[0]["code"] == "value_protocols"
    assert visible[0]["impact"] == 14.0
    assert visible[1]["code"] == "deal_citability"
    assert visible[1]["impact"] == 9.7
    assert result["parleo_fixable_points"] == 23.7
    visible_truesync = round(sum(v["impact"] for v in visible if v["fix_owner"] == "TRUESYNC"), 1)
    assert visible_truesync == result["parleo_fixable_points"]


# ─── Degraded (blocked/failed) crawls ────────────────────────────────────
#
# A store that refuses our reader used to get NO Full Analysis at all:
# build_full_cycle_report required status == 'complete', so the render
# gate fell back to the classic MetricsDashboard and said nothing about
# why. These lock the widened gate (lite's own scan_scorable set) plus
# the three-state withholding that has to come with it — scoring a
# blocked run WITHOUT withholding would be worse than the fallback,
# since compute_composite's denominator never shrinks for an unmeasured
# dimension and compute_verdict would then assert a failing verdict from
# data that was never measured.

_DEGRADED_REASON = (
    "the store root and every sampled product page were rate-limited or "
    "blocked this run — nothing could be measured on-site"
)

# Mirrors scan/engine.py's real degraded output: the five PDP-dependent
# dimensions synthesized as coverage='blocked', and the two that need no
# product page (agent_access, value_protocols — requires_pdp=False)
# real-scored exactly as on a complete run. agent_access scores a
# genuine 0 here: a store that 403s a cryptographically verified reader
# has actually failed agent access, and that refusal IS the measurement.
_BLOCKED_DIMENSIONS = {
    "scorer_version": "5",
    "degraded_reason": "blocked",
    "agent_access": {"score": 0, "max": 5, "coverage": "full", "evidence": ["robots.txt itself refused our reader (HTTP 403)"]},
    "value_protocols_seen": {"score": 0, "max": 14, "coverage": "full", "evidence": ["no protocol profile found"]},
    "catalog_context": {"score": 0.0, "max": 8, "coverage": "blocked", "evidence": [_DEGRADED_REASON], "fix": None, "fix_human": None},
    "protocol_feed": {"score": 0.0, "max": 5, "coverage": "blocked", "evidence": [_DEGRADED_REASON], "fix": None, "fix_human": None},
    "price_truth_seen": {"score": 0.0, "max": 7, "coverage": "blocked", "evidence": [_DEGRADED_REASON], "fix": None, "fix_human": None},
    "member_value_seen": {"score": 0.0, "max": 5, "coverage": "blocked", "evidence": [_DEGRADED_REASON], "fix": None, "fix_human": None},
    "deal_citability_seen": {"score": 0.0, "max": 7, "coverage": "blocked", "evidence": [_DEGRADED_REASON], "fix": None, "fix_human": None},
}


def _seed_cycle(conn, cycle_id, *, scan_status, dimensions, runs=40, entity_id=601):
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (id, name, slug) VALUES (?, 'Blocked Brand', 'blocked-brand')", (entity_id,)
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (?, ?, 'M001', 'primary')",
        (cycle_id, entity_id),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_metrics_results "
        "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
        " mention_rate, soa_pct, position_index, rsi_score) "
        "VALUES (?, ?, 'overall', 'overall', ?, ?, 1.0, 1.0, 1.0, 3.0)",
        (cycle_id, entity_id, runs, runs),
    )
    if scan_status is not None:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_scan_results "
            "(cycle_id, lite_request_id, status, dimensions, membership_probe, input_url) "
            "VALUES (?, NULL, ?, ?, ?, 'https://blocked-brand.example.com')",
            (cycle_id, scan_status, json.dumps(dimensions) if dimensions else None,
             json.dumps({"result": "yes", "raw_evidence": None})),
        )
    base = cycle_id * 1000
    for i in range(runs):
        qid = base + i
        conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (?, 'Ready to Buy')", (qid,))
        conn.exec_driver_sql(
            "INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (?, ?, ?, 'success')", (qid, cycle_id, qid)
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, deal_cited, deal_types, member_value_cited) "
            "VALUES (?, ?, 1, 1, ?, 1)",
            (qid, entity_id, json.dumps(["member_price"])),
        )
        conn.exec_driver_sql("INSERT INTO soa_pass2_coding_log (run_id, coding_pass_version) VALUES (?, 2)", (qid,))


@pytest.mark.parametrize("scan_status", ["blocked", "failed"])
def test_degraded_crawl_scores_instead_of_refusing_to_render(db, scan_status):
    """The widened gate: a blocked/failed crawl carries real degraded
    dimensions, so it scores through the same pillars machinery rather
    than falling back to the classic dashboard with no explanation."""
    with db.begin() as conn:
        _seed_cycle(conn, 88, scan_status=scan_status, dimensions=_BLOCKED_DIMENSIONS)

    with db.connect() as conn:
        report = build_full_cycle_report(conn, 88)

    assert report["status"] == "complete"
    assert report["degraded_reason"] == "blocked"
    pillars = report["pillars"]

    # Visibility is answer-side and entirely unaffected by the crawl —
    # it must still carry real, scored numbers. This is the whole reason
    # rendering a degraded report beats falling back.
    assert pillars["visibility"]["score"] > 0

    # Withheld, not fabricated.
    assert pillars["state"] == "unverified"
    assert pillars["composite"] is None
    assert pillars["verdict"] is None
    assert pillars["tv_pct"] is None
    assert pillars["unmeasured_count"] == 2


def test_degraded_crawl_marks_dimensions_not_measurable(db):
    with db.begin() as conn:
        _seed_cycle(conn, 89, scan_status="blocked", dimensions=_BLOCKED_DIMENSIONS)
    with db.connect() as conn:
        pillars = build_full_cycle_report(conn, 89)["pillars"]

    acc = {d["code"]: d for d in pillars["accessibility"]["dimensions"]}
    assert acc["catalog_context"]["blocked"] is True
    assert acc["protocol_feed"]["blocked"] is True
    # Excluded from the applicable max rather than averaged in as zeros:
    # only agent_access (real-scored, requires_pdp=False) counts.
    assert pillars["accessibility"]["dimensions"] is not None
    assert acc["agent_access"]["blocked"] is False

    tv = {d["code"]: d for d in pillars["true_value"]["dimensions"]}
    for code in ("price_truth", "member_value", "deal_citability"):
        assert tv[code]["blocked"] is True, code
        # max 0.0 == out of the applicable denominator entirely.
        assert tv[code]["max"] == 0.0, code
        assert tv[code]["checks"], f"{code} should carry NOT MEASURABLE checks"

    # The said side is REAL on a blocked run — measured from run signals,
    # which have nothing to do with whether a product page was fetchable.
    # It stays attached and visible, uncounted, rather than vanishing.
    assert tv["deal_citability"]["said"]["earned"] > 0
    assert tv["deal_citability"]["said_envelope"] is not None
    assert tv["price_truth"]["said"] is not None


def test_degraded_crawl_never_recommends_fixes_for_unread_dimensions(db):
    """_build_full_fixes_section skips na/blocked (see the existing
    unit coverage above) — end-to-end here, so a blocked dimension can
    never surface a ranked fix telling the client to repair something we
    never actually looked at."""
    with db.begin() as conn:
        _seed_cycle(conn, 90, scan_status="blocked", dimensions=_BLOCKED_DIMENSIONS)
    with db.connect() as conn:
        pillars = build_full_cycle_report(conn, 90)["pillars"]

    fixed_codes = {f["code"] for f in pillars["fixes"]["visible"]}
    assert not (fixed_codes & {"catalog_context", "protocol_feed", "price_truth", "member_value", "deal_citability"})


def test_composite_withheld_when_only_accessibility_is_blocked(db):
    """The middle state: True Value is clean, so tv_pct stays real while
    composite/verdict are withheld."""
    dims = dict(_FULL_CYCLE_DIMENSIONS)
    dims["catalog_context"] = {"score": 0.0, "max": 8, "coverage": "blocked", "evidence": [_DEGRADED_REASON], "fix": None, "fix_human": None}
    with db.begin() as conn:
        _seed_cycle(conn, 91, scan_status="complete", dimensions=dims)
    with db.connect() as conn:
        pillars = build_full_cycle_report(conn, 91)["pillars"]

    assert pillars["state"] == "composite_withheld"
    assert pillars["composite"] is None
    assert pillars["verdict"] is None
    assert pillars["tv_pct"] is not None
    assert pillars["unmeasured_count"] == 1


# ─── Gate reasons ────────────────────────────────────────────────────────
#
# The gate used to answer "no crawl attached yet" for every not_scored,
# including runs whose crawl was demonstrably attached and finished.

def test_reason_distinguishes_no_scan_row_from_a_non_scorable_one(db):
    with db.begin() as conn:
        _seed_cycle(conn, 92, scan_status=None, dimensions=None, entity_id=602)

    with db.connect() as conn:
        no_row = build_full_cycle_report(conn, 92)
    assert no_row["status"] == "not_scored"
    assert no_row["reason"] == "no crawl attached yet"

    with db.begin() as conn:
        _seed_cycle(conn, 93, scan_status="running", dimensions=None, entity_id=603)
    with db.connect() as conn:
        running = build_full_cycle_report(conn, 93)
    assert running["status"] == "not_scored"
    assert running["reason"] == "crawl still in progress"
    assert "no crawl attached" not in running["reason"]


def test_blocked_scan_reports_its_own_degraded_reason_not_a_missing_crawl(db):
    """The bug this replaces: a blocked crawl reported 'no crawl attached
    yet', which was both wrong and unactionable."""
    with db.begin() as conn:
        _seed_cycle(conn, 94, scan_status="blocked", dimensions=_BLOCKED_DIMENSIONS)
    with db.connect() as conn:
        report = build_full_cycle_report(conn, 94)

    assert report["status"] == "complete"
    assert report["degraded_reason"] == "blocked"
    assert report.get("reason") is None
