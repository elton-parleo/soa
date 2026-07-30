"""
Tests for GET /api/public/soa-lite/{token}/report
(app/routers/public_lite.py::get_lite_report) — 409-if-not-complete,
teaser (email null) vs full (email set) shaping, that no internal id
(cycle_id, entity_id, organization_id, comparison_code, soa_lite_requests.id)
ever appears in either payload, and (Stage 3) the Agent Scan 'scan' object,
visibility/accessibility/composite subscores, and the crosswalk 'linked'
attachment.
"""
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine

import app.routers.public_lite as public_lite


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_requests (
                id INTEGER PRIMARY KEY, token TEXT UNIQUE, email TEXT,
                status TEXT, cycle_id INTEGER,
                competitor_names TEXT, competitor_source TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_entities (
                id INTEGER PRIMARY KEY, name TEXT, slug TEXT UNIQUE, entity_type TEXT
            )
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
            CREATE TABLE soa_lite_scan_results (
                id INTEGER PRIMARY KEY, lite_request_id INTEGER UNIQUE, status TEXT,
                total_score INTEGER, integrity_capped BOOLEAN, dimensions TEXT, pages_fetched TEXT,
                membership_probe TEXT, revenue_probe TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_queries (
                id INTEGER PRIMARY KEY, stage TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, query_id INTEGER, status TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_coded_mentions (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                mentioned BOOLEAN, deal_cited BOOLEAN, deal_types TEXT,
                member_value_cited BOOLEAN
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_price_observations (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                stated_price FLOAT, claimed_net_price FLOAT, member_price_claimed BOOLEAN
            )
        """)
    monkeypatch.setattr(public_lite, "engine", engine)
    return engine


def _seed_complete_cycle(conn, token="t1", email=None, competitor_source=None):
    """
    One brand (M001/primary, entity_id=101, id=1001) + one competitor
    (M002/competitor, entity_id=102, id=1002) for cycle_id=1, with overall
    and two stage-slice metrics rows each.
    """
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_requests (token, email, status, cycle_id, competitor_source) "
        "VALUES (?, ?, 'complete', 1, ?)",
        (token, email, competitor_source),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (101, 'Acme Co', 'acme-co', 'brand')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (102, 'Rival Co', 'rival-co', 'brand')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) "
        "VALUES (1, 101, 'M001', 'primary')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) "
        "VALUES (1, 102, 'M002', 'competitor')"
    )
    # deal_citation_rate: Acme 50% (3 of 6 mentions cited), Rival Co 0%
    # (mentioned 6 times, never with a qualifying incentive) — a realistic
    # shape for the Stage 8 incentive_citation tests below.
    for entity_id, soa_pct, mention_rate, deal_citation_rate in [
        (101, 0.6, 0.5, 0.5), (102, 0.3, 0.2, 0.0),
    ]:
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score, deal_citation_rate) "
            "VALUES (1, ?, 'overall', 'overall', 12, 6, ?, ?, 0.4, 1.2, ?)",
            (entity_id, mention_rate, soa_pct, deal_citation_rate),
        )
        for stage in ("Awareness", "Research", "Comparison", "Ready to Buy"):
            conn.exec_driver_sql(
                "INSERT INTO soa_metrics_results "
                "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
                " mention_rate, soa_pct, position_index, rsi_score, deal_citation_rate) "
                "VALUES (1, ?, 'stage', ?, 3, 2, ?, ?, 0.4, 1.0, ?)",
                (entity_id, stage, mention_rate, soa_pct, deal_citation_rate),
            )


# ─── 409 when not complete ───────────────────────────────────────────────

def test_404_for_unknown_token(db):
    with pytest.raises(HTTPException) as exc_info:
        public_lite.get_lite_report("nope")
    assert exc_info.value.status_code == 404


@pytest.mark.parametrize("status", ["pending", "generating", "running", "failed"])
def test_409_when_not_complete(db, status):
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, status) VALUES ('t1', ?)", (status,)
        )
    with pytest.raises(HTTPException) as exc_info:
        public_lite.get_lite_report("t1")
    assert exc_info.value.status_code == 409


# ─── email de-gating (Report redesign, Part 8, E1) ───────────────────────
# A valid, complete token always renders the full report — never gated
# on whether an email is on file. These replace the old teaser (email
# null -> locked/reduced-shape response) tests removed this stage.

def test_full_report_returned_when_email_is_null(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email=None)

    result = public_lite.get_lite_report("t1")

    assert result["locked"] is False
    assert len(result["overall"]) == 2
    names = {e["name"] for e in result["overall"]}
    assert names == {"Acme Co", "Rival Co"}
    for entity in result["overall"]:
        assert {"name", "role", "metrics"}.issubset(entity.keys())
    assert result["by_stage"] is None  # DEPRECATED key, always null — present, not absent


def test_report_payload_is_byte_identical_with_and_without_email(db):
    """The acceptance criterion, directly: attaching an email to an
    already-complete request must not change a single byte of what
    GET /report returns."""
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email=None)

    without_email = public_lite.get_lite_report("t1")

    with db.begin() as conn:
        conn.exec_driver_sql("UPDATE soa_lite_requests SET email = ? WHERE token = ?", ("visitor@example.com", "t1"))

    with_email = public_lite.get_lite_report("t1")

    assert without_email == with_email


def test_teaser_primary_role_present(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email=None)

    result = public_lite.get_lite_report("t1")
    roles = {e["name"]: e["role"] for e in result["overall"]}
    assert roles["Acme Co"] == "primary"
    assert roles["Rival Co"] == "competitor"


def test_teaser_carries_competitor_source(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email=None, competitor_source="generated")

    result = public_lite.get_lite_report("t1")
    assert result["competitor_source"] == "generated"


# ─── full report (email set) ─────────────────────────────────────────────

def test_full_report_returned_when_email_is_set(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")

    result = public_lite.get_lite_report("t1")

    assert result["locked"] is False
    assert len(result["overall"]) == 2
    for entity in result["overall"]:
        assert set(entity["metrics"].keys()) >= {
            "mention_rate", "som", "rsi", "position_index",
        }
    assert result["by_stage"] is None  # deprecated Stage 7 — see test_full_report_never_leaks_stage_level_mention_data


def test_full_report_metric_values_correct(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")

    result = public_lite.get_lite_report("t1")
    acme = next(e for e in result["overall"] if e["name"] == "Acme Co")
    assert acme["metrics"]["som"] == 60.0  # normalize_metric(0.6) -> 0-100 scale


def test_full_report_carries_competitor_source(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com", competitor_source="mixed")

    result = public_lite.get_lite_report("t1")
    assert result["competitor_source"] == "mixed"


def test_report_competitor_source_null_when_not_yet_generated(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com", competitor_source=None)

    result = public_lite.get_lite_report("t1")
    assert result["competitor_source"] is None


# ─── no internal ids anywhere in either payload ─────────────────────────

def _scan_for_internal_ids(obj, path=""):
    """Recursively asserts no dict key is 'id', 'cycle_id', 'entity_id',
    'organization_id', or 'comparison_code' anywhere in the payload."""
    forbidden = {"id", "cycle_id", "entity_id", "organization_id", "comparison_code"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k not in forbidden, f"internal id key '{k}' found at {path}.{k}"
            _scan_for_internal_ids(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _scan_for_internal_ids(item, f"{path}[{i}]")


def test_teaser_payload_has_no_internal_ids(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email=None)
    result = public_lite.get_lite_report("t1")
    _scan_for_internal_ids(result)


def test_full_report_payload_has_no_internal_ids(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")
    result = public_lite.get_lite_report("t1")
    _scan_for_internal_ids(result)


# ─── G3: stage-level mention data must never leak into the public report ──

_STAGE_NAMES = ("awareness", "research", "comparison", "ready to buy")


def _seed_cycle_with_rich_stage_variance(conn, token="t1", email="visitor@example.com"):
    """
    Same primary/competitor pair as _seed_complete_cycle, but every stage
    gets a genuinely different mention_rate/soa_pct/deal_citation_rate per
    entity (not the same value repeated) — a real per-stage leak would
    surface as one of these distinctive numbers appearing somewhere in
    the response. deal_citation_rate is included here (Stage 8, A2) to
    re-assert Stage 7's stage nulling is slice-wide, not field-specific —
    it was never fetched by field name, so any metric column gets the
    same protection for free.
    """
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_requests (token, email, status, cycle_id) VALUES (?, ?, 'complete', 1)",
        (token, email),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (101, 'Acme Co', 'acme-co', 'brand')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (102, 'Rival Co', 'rival-co', 'brand')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) "
        "VALUES (1, 101, 'M001', 'primary')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) "
        "VALUES (1, 102, 'M002', 'competitor')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_metrics_results "
        "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
        " mention_rate, soa_pct, position_index, rsi_score, deal_citation_rate) "
        "VALUES (1, 101, 'overall', 'overall', 12, 6, 0.5, 0.6, 0.4, 1.2, 0.5)"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_metrics_results "
        "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
        " mention_rate, soa_pct, position_index, rsi_score, deal_citation_rate) "
        "VALUES (1, 102, 'overall', 'overall', 12, 3, 0.25, 0.3, 0.3, 0.5, 0.2)"
    )
    # Distinct, easily-fingerprinted stage-level rates — none of these
    # numbers (or their *100 percent forms) may appear anywhere below.
    stage_rates = {
        "Awareness":    (0.9166, 0.0833),
        "Research":     (0.1234, 0.8765),
        "Comparison":   (0.4567, 0.6789),
        "Ready to Buy": (0.7531, 0.2468),
    }
    # A separate fingerprint set for deal_citation_rate so a leak there
    # is unambiguous (not confusable with a mention_rate leak).
    stage_deal_citation_rates = {
        "Awareness":    (0.1357, 0.9642),
        "Research":     (0.8642, 0.1357),
        "Comparison":   (0.2589, 0.7413),
        "Ready to Buy": (0.6314, 0.3697),
    }
    for stage, (primary_rate, rival_rate) in stage_rates.items():
        primary_deal_rate, rival_deal_rate = stage_deal_citation_rates[stage]
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score, deal_citation_rate) "
            "VALUES (1, 101, 'stage', ?, 3, 2, ?, ?, 0.4, 1.0, ?)",
            (stage, primary_rate, primary_rate, primary_deal_rate),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score, deal_citation_rate) "
            "VALUES (1, 102, 'stage', ?, 3, 2, ?, ?, 0.4, 1.0, ?)",
            (stage, rival_rate, rival_rate, rival_deal_rate),
        )
    return stage_rates, stage_deal_citation_rates


def _flatten_leaf_values(obj, out):
    if isinstance(obj, dict):
        for v in obj.values():
            _flatten_leaf_values(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _flatten_leaf_values(item, out)
    else:
        out.append(obj)


def test_full_report_never_leaks_stage_level_mention_data(db):
    with db.begin() as conn:
        stage_rates, stage_deal_citation_rates = _seed_cycle_with_rich_stage_variance(
            conn, token="t1", email="visitor@example.com"
        )

    result = public_lite.get_lite_report("t1")

    # The deprecated key is kept (additive-contract) but always null.
    assert result["by_stage"] is None

    # No stage name anywhere in the payload...
    serialized = json.dumps(result).lower()
    for stage_name in _STAGE_NAMES:
        assert stage_name not in serialized, f"stage name '{stage_name}' leaked into the report"

    # ...and none of the distinctive per-stage rate values leaked through
    # as a bare number either (guards against a future refactor that
    # drops the stage *key* but still serializes the stage *values*).
    # Slice-wide, not field-specific (Stage 8 A2): both mention_rate's
    # and deal_citation_rate's stage fingerprints are checked here.
    leaves = []
    _flatten_leaf_values(result, leaves)
    numeric_leaves = {round(float(v), 4) for v in leaves if isinstance(v, (int, float))}
    for primary_rate, rival_rate in stage_rates.values():
        for rate in (primary_rate, rival_rate):
            assert round(rate, 4) not in numeric_leaves
            assert round(rate * 100, 1) not in {round(n, 1) for n in numeric_leaves}
    for primary_deal_rate, rival_deal_rate in stage_deal_citation_rates.values():
        for rate in (primary_deal_rate, rival_deal_rate):
            assert round(rate, 4) not in numeric_leaves, f"stage-sliced deal_citation_rate {rate} leaked"
            assert round(rate * 100, 1) not in {round(n, 1) for n in numeric_leaves}


def test_report_never_leaks_stage_level_mention_data(db):
    with db.begin() as conn:
        _seed_cycle_with_rich_stage_variance(conn, token="t1", email=None)

    result = public_lite.get_lite_report("t1")

    assert result["by_stage"] is None  # DEPRECATED key, always null
    serialized = json.dumps(result).lower()
    for stage_name in _STAGE_NAMES:
        assert stage_name not in serialized


def _seed_v3_scan_with_stage_tagged_mentions(conn, cycle_id=1, primary_entity_id=101, token="t1"):
    """Stage 16 (Part 7 leak check): a scorer_version '3' scan plus one
    coded mention PER STAGE for the primary entity — build_pillars_
    payload's said sub-lenses filter run_signals BY stage internally
    (PURCHASE_INTENT_STAGES) to compute opportunity sets; this proves
    that filtering never lets a stage name or a stage-keyed breakdown
    escape into the serialized pillars block."""
    rid = _lite_request_id(conn, token)
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_scan_results "
        "(lite_request_id, status, total_score, integrity_capped, dimensions, membership_probe) "
        "VALUES (?, 'complete', 88, 0, ?, ?)",
        (rid, json.dumps(_V3_CRAWL_DIMENSIONS), json.dumps({"result": "yes", "raw_evidence": None})),
    )
    for i, stage in enumerate(("Awareness", "Research", "Comparison", "Ready to Buy")):
        qid = 8100 + i
        conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (?, ?)", (qid, stage))
        conn.exec_driver_sql(
            "INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (?, ?, ?, 'success')",
            (qid, cycle_id, qid),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, deal_cited, deal_types, member_value_cited) "
            "VALUES (?, ?, 1, 1, ?, 1)",
            (qid, primary_entity_id, json.dumps(["member_price"])),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_price_observations (run_id, entity_id, stated_price, member_price_claimed) "
            "VALUES (?, ?, 10.0, 1)",
            (qid, primary_entity_id),
        )


def test_v3_pillars_block_never_leaks_stage_names(db):
    with db.begin() as conn:
        _seed_cycle_with_rich_stage_variance(conn, token="t1", email="visitor@example.com")
        _seed_v3_scan_with_stage_tagged_mentions(conn)

    result = public_lite.get_lite_report("t1")

    assert result["scan"]["scorer_version"] == "4"
    assert result["pillars"] is not None
    serialized = json.dumps(result).lower()
    for stage_name in _STAGE_NAMES:
        assert stage_name not in serialized, f"stage name '{stage_name}' leaked into the v3 pillars report"


def test_v3_pillars_block_has_no_internal_ids(db):
    with db.begin() as conn:
        _seed_v3_full_credit_scan(conn)

    result = public_lite.get_lite_report("v3full")
    assert result["pillars"] is not None
    _scan_for_internal_ids(result)


# ─── Agent Scan: dimensions, locking, degraded statuses ─────────────────

def _lite_request_id(conn, token):
    return conn.exec_driver_sql(
        "SELECT id FROM soa_lite_requests WHERE token = ?", (token,)
    ).fetchone()[0]


def _seed_scan_row(
    conn, lite_request_id, status="complete", total_score=None,
    integrity_capped=False, dimensions=None, pages_fetched=None,
):
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_scan_results "
        "(lite_request_id, status, total_score, integrity_capped, dimensions, pages_fetched) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            lite_request_id, status, total_score, integrity_capped,
            json.dumps(dimensions) if dimensions is not None else None,
            json.dumps(pages_fetched) if pages_fetched is not None else None,
        ),
    )


def _seed_run_signals_for_v1(conn, cycle_id=1, primary_entity_id=101):
    """Two successful runs where the primary entity is mentioned but no
    price is ever observed for it — triggers the V1 crosswalk rule."""
    conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (1, 'Awareness')")
    conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (2, 'Awareness')")
    conn.exec_driver_sql(
        "INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (1, ?, 1, 'success')", (cycle_id,)
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (2, ?, 2, 'success')", (cycle_id,)
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, deal_cited) VALUES (1, ?, 1, 0)",
        (primary_entity_id,),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, deal_cited) VALUES (2, ?, 1, 0)",
        (primary_entity_id,),
    )


# Gaps (max - score) are all distinct: V1=9, V2=8, V3=7, V4=6, F2=5, V5=3, F1=2, F3=1.
# Ranked desc: V1, V2, V3 (free, rank<=3), then V4, F2, V5, F1, F3 (locked).
_FULL_DIMENSIONS = {
    "F1": {"score": 8,  "max": 10, "evidence": ["e1"], "fix": "fix F1"},
    "F2": {"score": 10, "max": 15, "evidence": ["e2"], "fix": "fix F2"},
    "F3": {"score": 9,  "max": 10, "evidence": ["e3"], "fix": "fix F3"},
    "V1": {"score": 6,  "max": 15, "evidence": ["e4"], "fix": "fix V1"},
    "V2": {"score": 6,  "max": 14, "evidence": ["e5"], "fix": "fix V2"},
    "V3": {"score": 7,  "max": 14, "evidence": ["e6"], "fix": "fix V3"},
    "V4": {"score": 4,  "max": 10, "evidence": ["e7"], "fix": "fix V4"},
    "V5": {"score": 9,  "max": 12, "evidence": ["e8"], "fix": "fix V5"},
}


def test_scan_complete_has_exactly_eight_dimensions(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(
            conn, rid, status="complete", total_score=59, dimensions=_FULL_DIMENSIONS,
            pages_fetched=[{"url": "https://acme.com", "status": "fetched"}],
        )

    result = public_lite.get_lite_report("t1")

    assert result["scan"]["status"] == "complete"
    assert len(result["scan"]["dimensions"]) == 8
    assert {d["code"] for d in result["scan"]["dimensions"]} == set(_FULL_DIMENSIONS.keys())


def test_scan_locks_fix_text_below_top_three_by_gap(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(conn, rid, status="complete", total_score=59, dimensions=_FULL_DIMENSIONS)

    result = public_lite.get_lite_report("t1")
    by_code = {d["code"]: d for d in result["scan"]["dimensions"]}

    for code in ("V1", "V2", "V3"):  # top 3 by gap -> free
        assert by_code[code]["locked"] is False
        assert by_code[code]["fix"] == f"fix {code}"

    for code in ("F1", "F2", "F3", "V4", "V5"):  # remaining 5 -> locked
        assert by_code[code]["locked"] is True
        assert by_code[code]["fix"] is None
        assert by_code[code]["score"] == _FULL_DIMENSIONS[code]["score"]  # score itself still shown
        assert by_code[code]["evidence"] == _FULL_DIMENSIONS[code]["evidence"]  # evidence still shown


def test_scan_foundation_and_value_subtotals(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(conn, rid, status="complete", total_score=59, dimensions=_FULL_DIMENSIONS)

    result = public_lite.get_lite_report("t1")
    # Stage 10: applicable_max equals the nominal max here since none of
    # _FULL_DIMENSIONS is 'na' (no coverage key at all -> defaults to 'full').
    assert result["scan"]["foundation"] == {"subtotal": 27.0, "max": 35, "applicable_max": 35.0}
    assert result["scan"]["value"] == {"subtotal": 32.0, "max": 65, "applicable_max": 65.0}


# ─── Stage 10: scorer_version, coverage/na, deferred_items, cap_basis ────

def test_pre_stage10_row_has_no_scorer_version_or_coverage_keys_and_still_renders(db):
    """A row scanned before Stage 10 has no 'scorer_version' sibling key
    and no per-dimension 'coverage'/'deferred_items'/'cap_basis' keys at
    all — everything must default sanely (scorer_version '1', coverage
    'full', empty lists) rather than crash or leave a stray key missing."""
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(conn, rid, status="complete", total_score=59, dimensions=_FULL_DIMENSIONS)

    result = public_lite.get_lite_report("t1")

    assert result["scan"]["scorer_version"] == "1"
    for d in result["scan"]["dimensions"]:
        assert d["coverage"] == "full"
        assert d["deferred_items"] == []
        assert d["cap_basis"] == []


def test_scorer_version_2_is_serialized_when_present(db):
    dimensions = dict(_FULL_DIMENSIONS)
    dimensions["scorer_version"] = "2"
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(conn, rid, status="complete", total_score=59, dimensions=dimensions)

    result = public_lite.get_lite_report("t1")
    assert result["scan"]["scorer_version"] == "2"


def test_scorer_version_3_row_has_deprecated_always_empty_cap_fields(db):
    """Stage 16 (Part 6): integrity_capped/cap_basis are deprecated for
    scorer_version '3' — v3 never caps, so integrity_capped stays False
    and cap_basis stays empty regardless of whatever v3-shaped dimension
    codes (price_truth_seen, price_honesty_advisory, ...) are on the row.
    This locks in that deprecated-always-empty contract as an explicit
    regression guard, independent of the full v3 payload shape landing
    (Part 7)."""
    v3_dimensions = {
        "scorer_version": "3",
        "agent_access": {"score": 5, "max": 6, "evidence": ["e"], "fix": None},
        "price_truth_seen": {"score": 4, "max": 6, "evidence": ["e"], "fix": None},
        "price_honesty_advisory": {
            "scored": False, "would_have_capped": True,
            "evidence": ["was-price signal present"], "fix": None,
            "cap_basis": ["discount depth averaging 80.0% across pages with a was-price signal"],
        },
    }
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(
            conn, rid, status="complete", total_score=72,
            integrity_capped=False, dimensions=v3_dimensions,
        )

    result = public_lite.get_lite_report("t1")

    assert result["scan"]["scorer_version"] == "3"
    assert result["scan"]["integrity_capped"] is False
    for d in result["scan"]["dimensions"]:
        assert d["cap_basis"] == []


_FORBIDDEN_CAP_PHRASES = ("score cap", "59-point", "59 point", "capped the score", "score is capped")


def test_no_score_cap_language_anywhere_in_api_app_source():
    """Stage 16 (Part 6) grep-test: static sweep over apps/api/app/*.py
    (routers + schemas) — a regression guard against reintroducing
    cap-the-score copy anywhere in the API layer."""
    app_dir = Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in app_dir.rglob("*.py"):
        text = path.read_text().lower()
        for phrase in _FORBIDDEN_CAP_PHRASES:
            if phrase in text:
                offenders.append((str(path.relative_to(app_dir)), phrase))
    assert offenders == []


# ─── Stage 16 (Part 7): pillars block + composite versioning ────────────

_V3_CRAWL_DIMENSIONS = {
    "scorer_version": "4",
    "agent_access": {"score": 6, "max": 6, "coverage": "full", "evidence": [], "fix": "fix agent_access"},
    "catalog_context": {"score": 8, "max": 8, "coverage": "full", "evidence": [], "fix": "fix catalog_context"},
    "protocol_feed": {"score": 6, "max": 6, "coverage": "full", "evidence": [], "fix": "fix protocol_feed"},
    "price_truth_seen": {"score": 5, "max": 5, "coverage": "full", "evidence": [], "fix": "fix price_truth"},
    "member_value_seen": {"score": 9, "max": 9, "coverage": "full", "evidence": [], "fix": "fix member_value"},
    "deal_citability_seen": {"score": 4, "max": 4, "coverage": "full", "evidence": [], "fix": "fix deal_citability"},
    "value_protocols_seen": {"score": 7, "max": 7, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
}


def _seed_v3_full_credit_scan(conn, token="v3full", email="visitor@example.com", dimensions=None, revenue_probe=None):
    """A current-scorer-version scan + 4 purchase-intent mentions that
    cite everything — mirrors test_lite_pillars.py's 'full credit'
    fixture, so the resulting composite/pillars are exactly known (100
    across every pillar) without re-deriving the arithmetic here. Needs
    4 mentions (not 2): deal_citability.said is count-banded (Stage 25's
    4-tier COUNT_BAND_TABLE), and only reaches its 100% band at a cited
    count of 4+ — 2/2 would land in the 70% band instead."""
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_requests (token, email, status, cycle_id) VALUES (?, ?, 'complete', 5)",
        (token, email),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (201, 'V3 Brand', 'v3-brand', 'brand')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (5, 201, 'M001', 'primary')"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_metrics_results "
        "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
        " mention_rate, soa_pct, position_index, rsi_score) "
        "VALUES (5, 201, 'overall', 'overall', 2, 2, 1.0, 1.0, 1.0, 3.0)"
    )
    rid = _lite_request_id(conn, token)
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_scan_results (lite_request_id, status, total_score, integrity_capped, dimensions, membership_probe, revenue_probe) "
        "VALUES (?, 'complete', 90, 0, ?, ?, ?)",
        (
            rid, json.dumps(dimensions if dimensions is not None else _V3_CRAWL_DIMENSIONS),
            json.dumps({"result": "yes", "raw_evidence": None}),
            json.dumps(revenue_probe) if revenue_probe is not None else None,
        ),
    )
    conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (901, 'Comparison')")
    conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (902, 'Ready to Buy')")
    conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (903, 'Comparison')")
    conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (904, 'Ready to Buy')")
    conn.exec_driver_sql("INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (901, 5, 901, 'success')")
    conn.exec_driver_sql("INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (902, 5, 902, 'success')")
    conn.exec_driver_sql("INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (903, 5, 903, 'success')")
    conn.exec_driver_sql("INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (904, 5, 904, 'success')")
    for run_id in (901, 902, 903, 904):
        conn.exec_driver_sql(
            "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, deal_cited, deal_types, member_value_cited) "
            "VALUES (?, 201, 1, 1, ?, 1)",
            (run_id, json.dumps(["member_price"])),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_price_observations (run_id, entity_id, stated_price, member_price_claimed) "
            "VALUES (?, 201, 10.0, 1)",
            (run_id,),
        )
    return token


def test_v3_full_report_composite_uses_pillars_not_the_old_blend(db):
    with db.begin() as conn:
        _seed_v3_full_credit_scan(conn)

    result = public_lite.get_lite_report("v3full")

    assert result["scan"]["scorer_version"] == "4"
    assert result["visibility"] == 100
    assert result["accessibility"] == 100
    assert result["composite"] == 100
    assert result["pillars"]["visibility"]["score"] == 100
    assert result["pillars"]["accessibility"]["score"] == 100
    assert result["pillars"]["true_value"]["score"] == 100
    assert result["pillars"]["member_value_na"] is False


def test_v3_full_credit_scan_verdict_reaches_the_full_report_as_agent_ready(db):
    """Stage 25 (Part 5, G1): the verdict gate travels end to end through
    PublicLitePillars — a full-credit scan (composite 100, True Value
    100%) clears both thresholds and reads AGENT-READY in the actual API
    response, not just inside build_pillars_payload's own return dict."""
    with db.begin() as conn:
        _seed_v3_full_credit_scan(conn)

    result = public_lite.get_lite_report("v3full")

    assert result["pillars"]["verdict"] == "AGENT-READY"


def test_v3_weak_scan_verdict_reaches_the_full_report_as_not_agent_ready(db):
    """Same wiring check, opposite gate outcome: a scan with almost
    nothing crawlable and no mentions clears neither threshold."""
    weak_dimensions = {
        "scorer_version": "4",
        "agent_access": {"score": 0, "max": 6, "coverage": "full", "evidence": []},
        "catalog_context": {"score": 0, "max": 8, "coverage": "full", "evidence": []},
        "protocol_feed": {"score": 0, "max": 6, "coverage": "full", "evidence": []},
        "price_truth_seen": {"score": 0, "max": 5, "coverage": "full", "evidence": []},
        "member_value_seen": {"score": 0, "max": 9, "coverage": "full", "evidence": []},
        "deal_citability_seen": {"score": 0, "max": 4, "coverage": "full", "evidence": []},
        "value_protocols_seen": {"score": 0, "max": 7, "coverage": "full", "evidence": []},
    }
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, email, status, cycle_id) "
            "VALUES ('v3weak', 'visitor@example.com', 'complete', 10)"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (501, 'Weak Co', 'weak-co', 'brand')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (10, 501, 'M001', 'primary')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score) "
            "VALUES (10, 501, 'overall', 'overall', 0, 0, 0.0, 0.0, 0.0, NULL)"
        )
        rid = _lite_request_id(conn, "v3weak")
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_scan_results "
            "(lite_request_id, status, total_score, integrity_capped, dimensions, membership_probe) "
            "VALUES (?, 'complete', 0, 0, ?, ?)",
            (rid, json.dumps(weak_dimensions), json.dumps({"result": "no", "raw_evidence": None})),
        )

    result = public_lite.get_lite_report("v3weak")

    assert result["composite"] == 0
    assert result["pillars"]["verdict"] == "NOT AGENT-READY"


def test_v3_pillars_fix_text_reaches_the_full_report(db):
    """Stage 19 (R5): scan.dimensions is unusable for a v3 row (F1-V5
    keys never match a v3-keyed dimensions dict) — fix text for the
    ranked-fixes table has to travel through pillars instead. This just
    proves it's wired end to end; test_lite_pillars.py covers the
    ranking rules themselves."""
    with db.begin() as conn:
        _seed_v3_full_credit_scan(conn)

    result = public_lite.get_lite_report("v3full")

    all_dims = result["pillars"]["accessibility"]["dimensions"] + result["pillars"]["true_value"]["dimensions"]
    assert any(d["fix"] is not None for d in all_dims)
    assert any(d["locked"] for d in all_dims)


# ─── Part 3 (F1): report.pillars.fixes end to end ────────────────────────

_V3_CRAWL_DIMENSIONS_WITH_FIX_HUMAN = {
    "scorer_version": "4",
    "agent_access": {"score": 6, "max": 6, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
    "catalog_context": {
        "score": 3, "max": 8, "coverage": "full", "evidence": [],
        "fix": "fix catalog_context", "fix_human": "Add product identifiers so agents can match your listings.",
    },
    "protocol_feed": {
        "score": 0, "max": 6, "coverage": "full", "evidence": [],
        "fix": "fix protocol_feed", "fix_human": "Publish the files that let AI agents discover your store.",
    },
    "price_truth_seen": {"score": 5, "max": 5, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
    "member_value_seen": {"score": 9, "max": 9, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
    "deal_citability_seen": {"score": 4, "max": 4, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
    "value_protocols_seen": {"score": 7, "max": 7, "coverage": "full", "evidence": [], "fix": None, "fix_human": None},
}


def test_v3_report_fixes_field_reaches_the_full_report_end_to_end(db):
    with db.begin() as conn:
        _seed_v3_full_credit_scan(conn, dimensions=_V3_CRAWL_DIMENSIONS_WITH_FIX_HUMAN)

    result = public_lite.get_lite_report("v3full")

    fixes = result["pillars"]["fixes"]
    # Only two dims have a gap here — both visible, nothing left over.
    assert [v["code"] for v in fixes["visible"]] == ["protocol_feed", "catalog_context"]
    assert fixes["remaining_count"] == 0
    assert fixes["visible"][0]["fix_human"] == "Publish the files that let AI agents discover your store."
    assert "fix" not in fixes["visible"][0]  # no markup key on a visible entry


def test_v3_report_includes_pillars_fixes_even_when_email_is_null(db):
    with db.begin() as conn:
        _seed_v3_full_credit_scan(conn, email=None, dimensions=_V3_CRAWL_DIMENSIONS_WITH_FIX_HUMAN)

    result = public_lite.get_lite_report("v3full")
    assert result.get("pillars") is not None
    assert result["pillars"]["fixes"] is not None


# ─── Part 5 (R3): revenue_estimate_usd end to end ────────────────────────

def test_revenue_estimate_usd_reaches_the_full_report_when_probe_ran(db):
    with db.begin() as conn:
        _seed_v3_full_credit_scan(conn, revenue_probe={"annual_revenue_usd": 24_000_000.0, "basis": "b", "quote": "b"})

    result = public_lite.get_lite_report("v3full")
    assert result["revenue_estimate_usd"] == 24_000_000.0


def test_revenue_estimate_usd_is_null_when_probe_never_ran(db):
    with db.begin() as conn:
        _seed_v3_full_credit_scan(conn)  # no revenue_probe passed -> column stays NULL

    result = public_lite.get_lite_report("v3full")
    assert result["revenue_estimate_usd"] is None


def test_revenue_estimate_usd_is_null_when_probe_ran_but_found_nothing(db):
    with db.begin() as conn:
        _seed_v3_full_credit_scan(conn, revenue_probe={"annual_revenue_usd": None, "basis": None, "quote": None})

    result = public_lite.get_lite_report("v3full")
    assert result["revenue_estimate_usd"] is None


def test_v3_crosswalk_reason_remaps_onto_the_v3_dimension(db):
    """Stage 19 (R4): lite_crosswalk.py still reasons in v1/v2 codes
    (V1 'mentioned but no price surfaced') — a v3 row's report must
    show that chip on price_truth, the v3 dimension a visitor actually
    sees, not on a retired code that appears nowhere in the payload."""
    with db.begin() as conn:
        _seed_v3_full_credit_scan(conn, token="v3link")
        # No soa_price_observations rows at all -> primary_price_quoted
        # is False for every run -> link_dimensions() sets V1.
        conn.exec_driver_sql("DELETE FROM soa_price_observations")

    result = public_lite.get_lite_report("v3link")

    price_truth_row = next(d for d in result["pillars"]["true_value"]["dimensions"] if d["code"] == "price_truth")
    assert price_truth_row["linked"] == {"reason": "mentioned but no price surfaced"}
    # The retired code itself must never leak into the pillars block —
    # scan.dimensions (the v1/v2-keyed fallback array, unused by a v3
    # report) is a separate, pre-existing part of the payload and is
    # out of scope for this remap.
    assert '"V1"' not in json.dumps(result["pillars"])


def test_v3_crosswalk_never_attaches_a_chip_to_a_dimension_that_is_not_failing(db):
    """Stage 21 (bug fix 1) regression fixture: the real allbirds row's
    exact shape — agent_access scoring 4.8/6 (80%, genuinely fine) while
    research/comparison absence is high enough to fire F1's crosswalk
    rule. The old remap attached the chip anyway because it only checked
    "is this dimension na", never "is it actually failing" — a
    misleading alarm next to a dimension that's doing well. No mentions
    of the primary at all (0 of 12) is what fires F1/F2's absence rule
    here, matching the real row (primary was named in some but not most
    research/comparison-stage answers)."""
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, email, status, cycle_id) "
            "VALUES ('v3nochip', 'visitor@example.com', 'complete', 8)"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (401, 'Good Access Co', 'good-access', 'brand')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (8, 401, 'M001', 'primary')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score) "
            "VALUES (8, 401, 'overall', 'overall', 12, 0, 0.0, 0.0, 0.0, NULL)"
        )
        crawl = dict(_V3_CRAWL_DIMENSIONS)
        crawl["agent_access"] = {"score": 4.8, "max": 6, "coverage": "full", "evidence": []}
        rid = _lite_request_id(conn, 'v3nochip')
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_scan_results (lite_request_id, status, total_score, integrity_capped, dimensions, membership_probe) "
            "VALUES (?, 'complete', 60, 0, ?, ?)",
            (rid, json.dumps(crawl), json.dumps({"result": "no", "raw_evidence": None})),
        )
        # Every run's the primary entity absent (0 mentions total) ->
        # link_dimensions() fires "absent from most answers" on both F1/F2.
        for i, stage in enumerate(("Research", "Comparison")):
            qid = 950 + i
            conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (?, ?)", (qid, stage))
            conn.exec_driver_sql("INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (?, 8, ?, 'success')", (qid, qid))

    result = public_lite.get_lite_report("v3nochip")

    agent_access_row = next(d for d in result["pillars"]["accessibility"]["dimensions"] if d["code"] == "agent_access")
    assert agent_access_row["earned"] == 4.8
    assert agent_access_row["linked"] is None


def test_v3_crosswalk_attaches_a_chip_when_the_keyed_dimension_is_genuinely_failing(db):
    """Same absence-firing scenario as above, but catalog_context (F2's
    v3 target) is actually failing (0/8) — the chip belongs there."""
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, email, status, cycle_id) "
            "VALUES ('v3haschip', 'visitor@example.com', 'complete', 9)"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (402, 'Bad Catalog Co', 'bad-catalog', 'brand')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (9, 402, 'M001', 'primary')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score) "
            "VALUES (9, 402, 'overall', 'overall', 12, 0, 0.0, 0.0, 0.0, NULL)"
        )
        crawl = dict(_V3_CRAWL_DIMENSIONS)
        crawl["catalog_context"] = {"score": 0, "max": 8, "coverage": "full", "evidence": []}
        rid = _lite_request_id(conn, 'v3haschip')
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_scan_results (lite_request_id, status, total_score, integrity_capped, dimensions, membership_probe) "
            "VALUES (?, 'complete', 60, 0, ?, ?)",
            (rid, json.dumps(crawl), json.dumps({"result": "no", "raw_evidence": None})),
        )
        for i, stage in enumerate(("Research", "Comparison")):
            qid = 960 + i
            conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (?, ?)", (qid, stage))
            conn.exec_driver_sql("INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (?, 9, ?, 'success')", (qid, qid))

    result = public_lite.get_lite_report("v3haschip")

    catalog_row = next(d for d in result["pillars"]["accessibility"]["dimensions"] if d["code"] == "catalog_context")
    assert catalog_row["earned"] == 0
    assert catalog_row["linked"] == {"reason": "absent from most answers"}


def test_v3_report_has_full_pillars_block_even_when_email_is_null(db):
    with db.begin() as conn:
        _seed_v3_full_credit_scan(conn, token="v3teaser", email=None)

    result = public_lite.get_lite_report("v3teaser")

    assert result["locked"] is False
    assert result["visibility"] == 100
    assert result["accessibility"] == 100
    assert result["composite"] == 100
    assert result["pillars"] is not None
    assert result["scan"]["scorer_version"] == "4"


def test_v1_row_composite_still_uses_the_pre_stage16_blend(db):
    """Regression guard: a non-v3 scan must render byte-identically to
    before Part 7 — no pillars block, old 0.6/0.4 blend formula."""
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(conn, rid, status="complete", total_score=80, dimensions=_FULL_DIMENSIONS)

    result = public_lite.get_lite_report("t1")

    assert result["scan"]["scorer_version"] == "1"
    assert result["visibility"] == 60.0
    assert result["accessibility"] == 80
    assert result["composite"] == round(0.6 * 60.0 + 0.4 * 80)
    assert result["pillars"] is None


def test_v3_program_less_store_normalizes_member_value_na_onto_81(db):
    """Acceptance fixture: a program-less store — the crawl found no
    loyalty surface at all (member_value_seen score 0) and the
    membership probe came back 'no' — so member_value is N/A end to
    end. price_truth/deal_citability/value_protocols still earn full
    credit, so true_value's 25 applicable points (of the normal 40:
    price_truth 12 + deal_citability 6 + value_protocols 7) are all
    earned, and the /85 composite normalization (Part 4 P4, Stage 25:
    100 - member_value's 15) still reaches 100 — proving a program-less
    store isn't penalized for a dimension that was correctly excluded,
    not scored as zero."""
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, email, status, cycle_id) "
            "VALUES ('v3na', 'visitor@example.com', 'complete', 6)"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (301, 'Program-less Store', 'programless', 'brand')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (6, 301, 'M001', 'primary')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score) "
            "VALUES (6, 301, 'overall', 'overall', 2, 2, 1.0, 1.0, 1.0, 3.0)"
        )
        no_program_dimensions = dict(_V3_CRAWL_DIMENSIONS)
        no_program_dimensions["member_value_seen"] = {
            "score": 0, "max": 12, "coverage": "full",
            "evidence": ["no loyalty/rewards page found in nav/footer"],
        }
        rid = _lite_request_id(conn, "v3na")
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_scan_results "
            "(lite_request_id, status, total_score, integrity_capped, dimensions, membership_probe) "
            "VALUES (?, 'complete', 81, 0, ?, ?)",
            (rid, json.dumps(no_program_dimensions), json.dumps({"result": "no", "raw_evidence": None})),
        )
        conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (911, 'Comparison')")
        conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (912, 'Ready to Buy')")
        conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (913, 'Comparison')")
        conn.exec_driver_sql("INSERT INTO soa_queries (id, stage) VALUES (914, 'Ready to Buy')")
        conn.exec_driver_sql("INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (911, 6, 911, 'success')")
        conn.exec_driver_sql("INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (912, 6, 912, 'success')")
        conn.exec_driver_sql("INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (913, 6, 913, 'success')")
        conn.exec_driver_sql("INSERT INTO soa_runs (id, cycle_id, query_id, status) VALUES (914, 6, 914, 'success')")
        # 4 purchase-intent mentions (not 2): deal_citability.said is
        # count-banded and only reaches its 100% band at a cited count of
        # 4+ (Stage 25's 4-tier COUNT_BAND_TABLE) — same reasoning as
        # _seed_v3_full_credit_scan above.
        for run_id in (911, 912, 913, 914):
            # deal_cited/deal_types drive price_truth/deal_citability's said
            # halves; nothing here claims member value, so member_value_
            # said would be N/A on its own too — moot, since P3 already
            # excludes the whole dimension.
            conn.exec_driver_sql(
                "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, deal_cited, deal_types, member_value_cited) "
                "VALUES (?, 301, 1, 1, '[]', 0)",
                (run_id,),
            )
            conn.exec_driver_sql(
                "INSERT INTO soa_price_observations (run_id, entity_id, stated_price, member_price_claimed) "
                "VALUES (?, 301, 10.0, 0)",
                (run_id,),
            )

    result = public_lite.get_lite_report("v3na")

    assert result["pillars"]["member_value_na"] is True
    member_value_row = next(d for d in result["pillars"]["true_value"]["dimensions"] if d["code"] == "member_value")
    assert member_value_row["na"] is True
    assert member_value_row["max"] == 0.0
    assert result["pillars"]["true_value"]["score"] == 100  # 21/21 applicable points
    assert result["composite"] == 100  # 81/81 applicable points, not penalized for the na dimension


def test_v3_member_value_na_row_quotes_the_probe_as_evidence(db):
    """Stage 19 (R2): when member_value is N/A, its evidence is the
    probe's own verbatim answer (`probe: '...'`), not fabricated or
    silently empty — reusing the same program-less fixture as the /81
    normalization test above, just with a real raw_evidence string."""
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, email, status, cycle_id) "
            "VALUES ('v3naquote', 'visitor@example.com', 'complete', 7)"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (302, 'Quote Store', 'quotestore', 'brand')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (7, 302, 'M001', 'primary')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score) "
            "VALUES (7, 302, 'overall', 'overall', 0, 0, 0.0, 0.0, 0.0, NULL)"
        )
        no_program_dimensions = dict(_V3_CRAWL_DIMENSIONS)
        no_program_dimensions["member_value_seen"] = {"score": 0, "max": 12, "coverage": "full", "evidence": []}
        rid = _lite_request_id(conn, "v3naquote")
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_scan_results "
            "(lite_request_id, status, total_score, integrity_capped, dimensions, membership_probe) "
            "VALUES (?, 'complete', 60, 0, ?, ?)",
            (rid, json.dumps(no_program_dimensions),
             json.dumps({"result": "no", "raw_evidence": "No, we do not have a loyalty or membership program."})),
        )

    result = public_lite.get_lite_report("v3naquote")

    member_value_row = next(d for d in result["pillars"]["true_value"]["dimensions"] if d["code"] == "member_value")
    assert member_value_row["na"] is True
    assert member_value_row["evidence"] == [
        "probe: 'No, we do not have a loyalty or membership program.'"
    ]


def test_na_dimension_excluded_from_applicable_max_and_never_locked(db):
    dimensions = {
        **_FULL_DIMENSIONS,
        "F3": {
            "score": 0, "max": 10, "evidence": ["not applicable"], "fix": None,
            "coverage": "na", "deferred_items": [], "cap_basis": [],
        },
        "scorer_version": "2",
    }
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(conn, rid, status="complete", total_score=59, dimensions=dimensions)

    result = public_lite.get_lite_report("t1")
    by_code = {d["code"]: d for d in result["scan"]["dimensions"]}

    assert by_code["F3"]["coverage"] == "na"
    assert by_code["F3"]["locked"] is False
    # F3's nominal max (10) is dropped from Foundation's applicable_max
    # (35 - 10 = 25), but the family `max` field itself stays 35 (rule 6).
    assert result["scan"]["foundation"]["max"] == 35
    assert result["scan"]["foundation"]["applicable_max"] == 25.0


def test_na_dimension_never_occupies_a_free_fix_slot(db):
    """Mechanism check: marking the single biggest-gap dimension (V1) as
    'na' must reallocate its free-fix slot to the next real dimension by
    gap (V4) rather than leaving only 2 dimensions unlocked or crashing
    on a missing rank. (Spec only ever marks F3/V3 na in practice — this
    exercises the ranking mechanism in isolation.)"""
    dimensions = {
        **_FULL_DIMENSIONS,
        "V1": {
            "score": 0, "max": 15, "evidence": ["not applicable"], "fix": None,
            "coverage": "na", "deferred_items": [], "cap_basis": [],
        },
    }
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(conn, rid, status="complete", total_score=59, dimensions=dimensions)

    result = public_lite.get_lite_report("t1")
    by_code = {d["code"]: d for d in result["scan"]["dimensions"]}

    assert by_code["V1"]["locked"] is False  # na dims are never "locked"
    for code in ("V2", "V3", "V4"):  # V1's slot reallocates to V4 (next biggest gap)
        assert by_code[code]["locked"] is False
    for code in ("F1", "F2", "F3", "V5"):
        assert by_code[code]["locked"] is True


@pytest.mark.parametrize("scan_status", ["blocked", "failed", "skipped", "running"])
def test_degraded_scan_status_never_blocks_the_report(db, scan_status):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(conn, rid, status=scan_status)

    result = public_lite.get_lite_report("t1")  # must not raise

    assert result["status"] == "complete"  # the lite report itself
    assert result["scan"]["status"] == scan_status
    assert result["scan"]["total_score"] is None
    assert result["scan"]["dimensions"] == []


def test_no_scan_row_at_all_yields_scan_none(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")

    result = public_lite.get_lite_report("t1")
    assert result["scan"] is None
    assert result["scan_status"] is None


def test_report_includes_the_full_scan_object_even_when_email_is_null(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email=None)
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(conn, rid, status="complete", total_score=59, dimensions=_FULL_DIMENSIONS)

    result = public_lite.get_lite_report("t1")
    assert result["scan"] is not None


def test_report_attaches_linked_reason_from_crosswalk(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(conn, rid, status="complete", total_score=59, dimensions=_FULL_DIMENSIONS)
        _seed_run_signals_for_v1(conn)

    result = public_lite.get_lite_report("t1")
    by_code = {d["code"]: d for d in result["scan"]["dimensions"]}
    assert by_code["V1"]["linked"] == {"reason": "mentioned but no price surfaced"}
    assert by_code["F1"]["linked"] is None


def test_report_attaches_incentive_citation_linked_reason_end_to_end(db):
    """
    Stage 8 (A4), integration-level: proves the router actually merges
    link_incentive_citation's result into scan.dimensions[].linked, not
    just that the pure function returns the right dict in isolation
    (see test_lite_crosswalk.py for that).
    """
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, email, status, cycle_id) VALUES ('t1', 'visitor@example.com', 'complete', 1)"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (101, 'Acme Co', 'acme-co', 'brand')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (102, 'Rival Co', 'rival-co', 'brand')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (1, 101, 'M001', 'primary')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (1, 102, 'M002', 'competitor')"
        )
        # Acme: 2 mentions, 0% incentive citation. Rival: 4 mentions, 50%
        # citation rate -> Acme's 0% trails the rival by 50pts (>=25).
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score, deal_citation_rate) "
            "VALUES (1, 101, 'overall', 'overall', 12, 2, 0.17, 0.3, 0.4, 1.0, 0.0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score, deal_citation_rate) "
            "VALUES (1, 102, 'overall', 'overall', 12, 4, 0.33, 0.7, 0.4, 1.0, 0.5)"
        )
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(conn, rid, status="complete", total_score=59, dimensions=_FULL_DIMENSIONS)

    result = public_lite.get_lite_report("t1")
    by_code = {d["code"]: d for d in result["scan"]["dimensions"]}

    # V2 (score 6/14) and V3 (score 7/14) both have gaps; V2 scores lower
    # -> V2 wins. Acme's rate is literally 0 with 2 mentions -> zero_condition.
    assert by_code["V2"]["linked"] == {"reason": "value never cited"}


# ─── visibility / accessibility / composite subscores ───────────────────

def test_teaser_visibility_present_without_scan(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email=None)

    result = public_lite.get_lite_report("t1")
    assert result["visibility"] == 60.0  # normalize_metric(0.6) for Acme's som
    assert result["accessibility"] is None
    assert result["composite"] == 60.0  # visibility alone, no scan yet
    assert result["scan_status"] is None


def test_teaser_composite_blends_visibility_and_accessibility_when_scan_complete(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email=None)
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(conn, rid, status="complete", total_score=80, dimensions=_FULL_DIMENSIONS)

    result = public_lite.get_lite_report("t1")
    assert result["visibility"] == 60.0
    assert result["accessibility"] == 80
    assert result["composite"] == round(0.6 * 60.0 + 0.4 * 80)  # 68
    assert result["scan_status"] == "complete"


# ─── visibility_breakdown (Stage 7, A1) ──────────────────────────────────

def test_full_report_has_visibility_breakdown_shaped_correctly(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")

    result = public_lite.get_lite_report("t1")
    vb = result["visibility_breakdown"]

    # _seed_complete_cycle gives both entities total_mentions=6, total_runs=12.
    assert {r["entity"]: r["rate_pct"] for r in vb["mention_rate"]} == {
        "Acme Co": 50.0, "Rival Co": 50.0,
    }
    acme_rate = next(r for r in vb["mention_rate"] if r["entity"] == "Acme Co")
    assert acme_rate["is_primary"] is True
    assert acme_rate["mentioned_queries"] == 6
    assert acme_rate["total_queries"] == 12

    # 6 + 6 = 12 total mentions -> 50/50 share.
    assert {r["entity"]: r["share_pct"] for r in vb["share_of_mentions"]} == {
        "Acme Co": 50.0, "Rival Co": 50.0,
    }
    assert vb["totals"] == {"total_mentions": 12, "total_queries": 12}


def test_report_includes_visibility_breakdown_even_when_email_is_null(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email=None)

    result = public_lite.get_lite_report("t1")
    assert result["visibility_breakdown"] is not None


# ─── Stage 8 (A1): visibility_breakdown.incentive_citation ───────────────

def test_full_report_has_incentive_citation_shaped_correctly(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")

    result = public_lite.get_lite_report("t1")
    ic = result["visibility_breakdown"]["incentive_citation"]

    by_entity = {r["entity"]: r for r in ic}
    assert by_entity["Acme Co"]["is_primary"] is True
    assert by_entity["Acme Co"]["mentions"] == 6
    assert by_entity["Acme Co"]["rate_pct"] == 50.0
    assert by_entity["Acme Co"]["cited_answers"] == 3  # round(0.5 * 6)

    assert by_entity["Rival Co"]["is_primary"] is False
    assert by_entity["Rival Co"]["mentions"] == 6
    assert by_entity["Rival Co"]["rate_pct"] == 0.0
    assert by_entity["Rival Co"]["cited_answers"] == 0

    # primary-first ordering, same convention as mention_rate/share_of_mentions.
    assert [r["entity"] for r in ic] == ["Acme Co", "Rival Co"]


def test_incentive_citation_null_rate_for_zero_mention_entity(db):
    with db.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_requests (token, email, status, cycle_id) VALUES ('t1', 'visitor@example.com', 'complete', 1)"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (101, 'Acme Co', 'acme-co', 'brand')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (102, 'Rival Co', 'rival-co', 'brand')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (1, 101, 'M001', 'primary')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (1, 102, 'M002', 'competitor')"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score, deal_citation_rate) "
            "VALUES (1, 101, 'overall', 'overall', 12, 0, 0.0, 0.0, NULL, NULL, NULL)"
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score, deal_citation_rate) "
            "VALUES (1, 102, 'overall', 'overall', 12, 4, 0.33, 1.0, 0.4, 1.0, 0.5)"
        )

    result = public_lite.get_lite_report("t1")
    ic = {r["entity"]: r for r in result["visibility_breakdown"]["incentive_citation"]}

    assert ic["Acme Co"]["mentions"] == 0
    assert ic["Acme Co"]["rate_pct"] is None
    assert ic["Acme Co"]["cited_answers"] is None


def test_report_includes_incentive_citation_even_when_email_is_null(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email=None)

    result = public_lite.get_lite_report("t1")
    assert result["visibility_breakdown"]["incentive_citation"] is not None


def test_full_report_carries_same_subscores_as_teaser(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(conn, rid, status="complete", total_score=80, dimensions=_FULL_DIMENSIONS)

    result = public_lite.get_lite_report("t1")
    assert result["visibility"] == 60.0
    assert result["accessibility"] == 80
    assert result["composite"] == 68


# ─── additive-only: pre-Stage-3 response shape is unchanged/subset ──────

_PRE_STAGE3_REPORT_KEYS = {"status", "locked", "overall", "by_stage"}


def test_full_report_response_is_additive_over_pre_stage3_shape(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email="visitor@example.com")

    result = public_lite.get_lite_report("t1")
    assert _PRE_STAGE3_REPORT_KEYS.issubset(result.keys())
    # by_stage is kept (key present, additive contract) but deprecated as
    # of Stage 7 — always null, never a dict, now that per-stage mention
    # data is paid-diagnostic material.
    assert result["by_stage"] is None
    for entity in result["overall"]:
        assert {"name", "role", "metrics"}.issubset(entity.keys())
    # Stage 8: incentive_citation is additive on visibility_breakdown —
    # present, non-empty, and every row has the full field set.
    ic = result["visibility_breakdown"]["incentive_citation"]
    assert len(ic) == 2
    for row in ic:
        assert {"entity", "is_primary", "mentions", "cited_answers", "rate_pct"}.issubset(row.keys())
