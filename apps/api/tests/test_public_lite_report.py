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
                status TEXT, cycle_id INTEGER
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
                total_score INTEGER, integrity_capped BOOLEAN, dimensions TEXT, pages_fetched TEXT
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
                mentioned BOOLEAN, deal_cited BOOLEAN, deal_types TEXT
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


def _seed_complete_cycle(conn, token="t1", email=None):
    """
    One brand (M001/primary, entity_id=101, id=1001) + one competitor
    (M002/competitor, entity_id=102, id=1002) for cycle_id=1, with overall
    and two stage-slice metrics rows each.
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
    for entity_id, soa_pct, mention_rate in [(101, 0.6, 0.5), (102, 0.3, 0.2)]:
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score) "
            "VALUES (1, ?, 'overall', 'overall', 12, 6, ?, ?, 0.4, 1.2)",
            (entity_id, mention_rate, soa_pct),
        )
        for stage in ("Awareness", "Research", "Comparison", "Ready to Buy"):
            conn.exec_driver_sql(
                "INSERT INTO soa_metrics_results "
                "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
                " mention_rate, soa_pct, position_index, rsi_score) "
                "VALUES (1, ?, 'stage', ?, 3, 2, ?, ?, 0.4, 1.0)",
                (entity_id, stage, mention_rate, soa_pct),
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


# ─── teaser (email null) ─────────────────────────────────────────────────

def test_teaser_returned_when_email_is_null(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email=None)

    result = public_lite.get_lite_report("t1")

    assert result["locked"] is True
    assert len(result["overall"]) == 2
    names = {e["name"] for e in result["overall"]}
    assert names == {"Acme Co", "Rival Co"}
    for entity in result["overall"]:
        assert set(entity.keys()) == {"name", "role", "som"}
    assert "by_stage" not in result


def test_teaser_primary_role_present(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email=None)

    result = public_lite.get_lite_report("t1")
    roles = {e["name"]: e["role"] for e in result["overall"]}
    assert roles["Acme Co"] == "primary"
    assert roles["Rival Co"] == "competitor"


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
    gets a genuinely different mention_rate/soa_pct per entity (not the
    same value repeated) — a real per-stage leak would surface as one of
    these distinctive numbers appearing somewhere in the response.
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
        " mention_rate, soa_pct, position_index, rsi_score) "
        "VALUES (1, 101, 'overall', 'overall', 12, 6, 0.5, 0.6, 0.4, 1.2)"
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_metrics_results "
        "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
        " mention_rate, soa_pct, position_index, rsi_score) "
        "VALUES (1, 102, 'overall', 'overall', 12, 3, 0.25, 0.3, 0.3, 0.5)"
    )
    # Distinct, easily-fingerprinted stage-level rates — none of these
    # numbers (or their *100 percent forms) may appear anywhere below.
    stage_rates = {
        "Awareness":    (0.9166, 0.0833),
        "Research":     (0.1234, 0.8765),
        "Comparison":   (0.4567, 0.6789),
        "Ready to Buy": (0.7531, 0.2468),
    }
    for stage, (primary_rate, rival_rate) in stage_rates.items():
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score) "
            "VALUES (1, 101, 'stage', ?, 3, 2, ?, ?, 0.4, 1.0)",
            (stage, primary_rate, primary_rate),
        )
        conn.exec_driver_sql(
            "INSERT INTO soa_metrics_results "
            "(cycle_id, entity_id, slice_type, slice_value, total_runs, total_mentions, "
            " mention_rate, soa_pct, position_index, rsi_score) "
            "VALUES (1, 102, 'stage', ?, 3, 2, ?, ?, 0.4, 1.0)",
            (stage, rival_rate, rival_rate),
        )
    return stage_rates


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
        stage_rates = _seed_cycle_with_rich_stage_variance(conn, token="t1", email="visitor@example.com")

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
    leaves = []
    _flatten_leaf_values(result, leaves)
    numeric_leaves = {round(float(v), 4) for v in leaves if isinstance(v, (int, float))}
    for primary_rate, rival_rate in stage_rates.values():
        for rate in (primary_rate, rival_rate):
            assert round(rate, 4) not in numeric_leaves
            assert round(rate * 100, 1) not in {round(n, 1) for n in numeric_leaves}


def test_teaser_never_leaks_stage_level_mention_data(db):
    with db.begin() as conn:
        _seed_cycle_with_rich_stage_variance(conn, token="t1", email=None)

    result = public_lite.get_lite_report("t1")

    assert "by_stage" not in result  # teaser never had this key at all
    serialized = json.dumps(result).lower()
    for stage_name in _STAGE_NAMES:
        assert stage_name not in serialized


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
    assert result["scan"]["foundation"] == {"subtotal": 27.0, "max": 35}
    assert result["scan"]["value"] == {"subtotal": 32.0, "max": 65}


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


def test_teaser_never_includes_the_full_scan_object(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email=None)
        rid = _lite_request_id(conn, "t1")
        _seed_scan_row(conn, rid, status="complete", total_score=59, dimensions=_FULL_DIMENSIONS)

    result = public_lite.get_lite_report("t1")
    assert "scan" not in result


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


def test_teaser_never_includes_visibility_breakdown(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email=None)

    result = public_lite.get_lite_report("t1")
    assert "visibility_breakdown" not in result


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

_PRE_STAGE3_TEASER_KEYS = {"status", "locked", "overall"}
_PRE_STAGE3_REPORT_KEYS = {"status", "locked", "overall", "by_stage"}


def test_teaser_response_is_additive_over_pre_stage3_shape(db):
    with db.begin() as conn:
        _seed_complete_cycle(conn, token="t1", email=None)

    result = public_lite.get_lite_report("t1")
    assert _PRE_STAGE3_TEASER_KEYS.issubset(result.keys())
    assert isinstance(result["locked"], bool)
    assert isinstance(result["overall"], list)
    for entity in result["overall"]:
        assert {"name", "role", "som"}.issubset(entity.keys())


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
