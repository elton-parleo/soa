"""
Tests for GET /api/public/soa-lite/{token}/report
(app/routers/public_lite.py::get_lite_report) — 409-if-not-complete,
teaser (email null) vs full (email set) shaping, and that no internal id
(cycle_id, entity_id, organization_id, comparison_code, soa_lite_requests.id)
ever appears in either payload.
"""
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
    assert set(result["by_stage"].keys()) == {"Awareness", "Research", "Comparison", "Ready to Buy"}
    for stage_entities in result["by_stage"].values():
        assert len(stage_entities) == 2


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
