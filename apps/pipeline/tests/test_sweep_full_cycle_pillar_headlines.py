"""
Tests for worker.py::_sweep_full_cycle_pillar_headlines — Part A
(pillar-headline generation extended to Full Analysis, previously
lite-only via _run_pillar_headlines). generate_pillar_headlines itself
is mocked, same convention as test_process_lite_requests.py's own
pillar-headline coverage.
"""
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, text

import worker


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, cycle_code TEXT, status TEXT, cycle_mode TEXT DEFAULT 'query'
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_scan_results (
                id INTEGER PRIMARY KEY, lite_request_id INTEGER, cycle_id INTEGER,
                input_url TEXT, status TEXT, dimensions TEXT, updated_at TIMESTAMP
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
                slice_type TEXT, soa_pct REAL, mention_rate REAL, rsi_score REAL
            )
        """)
    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setenv("OPEN_AI_API_KEY", "test-key")
    return engine


_CRAWL_DIMENSIONS = {
    "agent_access": {"score": 5, "max": 6, "coverage": "full", "evidence": []},
    "catalog_context": {"score": 2, "max": 8, "coverage": "full", "evidence": []},
    "protocol_feed": {"score": 1, "max": 6, "coverage": "full", "evidence": []},
    "price_truth_seen": {"score": 2, "max": 5, "coverage": "full", "evidence": []},
    "member_value_seen": {"score": 0, "max": 9, "coverage": "na", "evidence": []},
    "deal_citability_seen": {"score": 0, "max": 4, "coverage": "full", "evidence": []},
    "value_protocols_seen": {"score": 0, "max": 7, "coverage": "full", "evidence": []},
}


def _seed_full_cycle(conn, cycle_id=41, cycle_status="complete", scan_status="complete",
                      cycle_mode="query", dimensions=None, generated_headlines=None):
    conn.exec_driver_sql(
        "INSERT INTO soa_cycles (id, cycle_code, status, cycle_mode) VALUES (?, ?, ?, ?)",
        (cycle_id, f"cycle-{cycle_id}", cycle_status, cycle_mode),
    )
    dims = dict(dimensions if dimensions is not None else _CRAWL_DIMENSIONS)
    if generated_headlines is not None:
        dims["generated_headlines"] = generated_headlines
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_scan_results (lite_request_id, cycle_id, input_url, status, dimensions) "
        "VALUES (NULL, ?, 'https://acme.example.com', ?, ?)",
        (cycle_id, scan_status, json.dumps(dims)),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (name, slug, entity_type) VALUES ('Acme', ?, 'brand')", (f"acme-{cycle_id}",),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (name, slug, entity_type) VALUES ('Rival', ?, 'brand')", (f"rival-{cycle_id}",),
    )
    primary_id = conn.exec_driver_sql("SELECT id FROM soa_entities WHERE slug = ?", (f"acme-{cycle_id}",)).fetchone()[0]
    competitor_id = conn.exec_driver_sql("SELECT id FROM soa_entities WHERE slug = ?", (f"rival-{cycle_id}",)).fetchone()[0]
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (?, ?, 'M001', 'primary')",
        (cycle_id, primary_id),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) VALUES (?, ?, 'M002', 'competitor')",
        (cycle_id, competitor_id),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_metrics_results (cycle_id, entity_id, slice_type, soa_pct, mention_rate, rsi_score) "
        "VALUES (?, ?, 'overall', 35.0, 42.0, 3.2)",
        (cycle_id, primary_id),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_metrics_results (cycle_id, entity_id, slice_type, soa_pct, mention_rate, rsi_score) "
        "VALUES (?, ?, 'overall', 55.0, 60.0, 4.0)",
        (cycle_id, competitor_id),
    )


def _dims(conn, cycle_id=41):
    row = conn.execute(text(
        "SELECT dimensions FROM soa_lite_scan_results WHERE cycle_id = :cid ORDER BY id DESC LIMIT 1"
    ), {"cid": cycle_id}).fetchone()
    dimensions = row[0]
    return json.loads(dimensions) if isinstance(dimensions, str) else dimensions


_FAKE_HEADLINES = {
    "visibility": {"headline": "You hold 35% share of all brand mentions.", "source": "generated"},
    "accessibility": {"headline": "Agent Access earns 5 of 6 points.", "source": "generated"},
    "true_value": {"headline": "Price Truth earns 2 of 5 points on your site.", "source": "generated"},
}


def test_generates_headlines_for_a_complete_full_cycle_with_a_complete_crawl(db):
    with db.begin() as conn:
        _seed_full_cycle(conn)

    with patch("generation.pillar_headlines.generate_pillar_headlines", return_value=_FAKE_HEADLINES) as mock_gen:
        worker._sweep_full_cycle_pillar_headlines()

    assert mock_gen.call_count == 1
    # Cycle-wide facts (not platform-scoped) reached the generator via
    # _fetch_visibility_metrics, unchanged from the lite path.
    _, visibility_metrics_arg, _ = mock_gen.call_args[0]
    assert visibility_metrics_arg["som_pct"] == 35.0
    assert visibility_metrics_arg["rank_line"] == "2nd of 2 in the competitor set"

    with db.connect() as conn:
        stored = _dims(conn)
    assert stored["generated_headlines"] == _FAKE_HEADLINES
    # additive: the crawl dimensions already on the row are untouched.
    assert stored["agent_access"]["score"] == 5


def test_skips_a_cycle_whose_crawl_is_not_complete_yet(db):
    with db.begin() as conn:
        _seed_full_cycle(conn, scan_status="running")

    with patch("generation.pillar_headlines.generate_pillar_headlines") as mock_gen:
        worker._sweep_full_cycle_pillar_headlines()

    mock_gen.assert_not_called()


def test_skips_a_cycle_whose_pipeline_is_not_complete_yet(db):
    with db.begin() as conn:
        _seed_full_cycle(conn, cycle_status="running")

    with patch("generation.pillar_headlines.generate_pillar_headlines") as mock_gen:
        worker._sweep_full_cycle_pillar_headlines()

    mock_gen.assert_not_called()


def test_skips_a_truecost_cycle(db):
    with db.begin() as conn:
        _seed_full_cycle(conn, cycle_mode="truecost")

    with patch("generation.pillar_headlines.generate_pillar_headlines") as mock_gen:
        worker._sweep_full_cycle_pillar_headlines()

    mock_gen.assert_not_called()


def test_never_touches_a_scan_row_owned_by_a_lite_request(db):
    with db.begin() as conn:
        conn.exec_driver_sql("INSERT INTO soa_cycles (id, cycle_code, status, cycle_mode) VALUES (7, 'lite-x', 'complete', 'query')")
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_scan_results (lite_request_id, cycle_id, input_url, status, dimensions) "
            "VALUES (99, 7, 'https://acme.example.com', 'complete', ?)",
            (json.dumps(_CRAWL_DIMENSIONS),),
        )

    with patch("generation.pillar_headlines.generate_pillar_headlines") as mock_gen:
        worker._sweep_full_cycle_pillar_headlines()

    mock_gen.assert_not_called()


def test_idempotent_never_regenerates_a_cycle_that_already_has_headlines(db):
    with db.begin() as conn:
        _seed_full_cycle(conn, generated_headlines=_FAKE_HEADLINES)

    with patch("generation.pillar_headlines.generate_pillar_headlines") as mock_gen:
        worker._sweep_full_cycle_pillar_headlines()

    mock_gen.assert_not_called()


def test_one_cycle_per_pass_the_next_pass_picks_up_the_rest(db):
    with db.begin() as conn:
        _seed_full_cycle(conn, cycle_id=41)
        _seed_full_cycle(conn, cycle_id=42)

    with patch("generation.pillar_headlines.generate_pillar_headlines", return_value=_FAKE_HEADLINES) as mock_gen:
        worker._sweep_full_cycle_pillar_headlines()
        assert mock_gen.call_count == 1
        with db.connect() as conn:
            assert _dims(conn, 41)["generated_headlines"] == _FAKE_HEADLINES
            assert "generated_headlines" not in _dims(conn, 42)

        worker._sweep_full_cycle_pillar_headlines()
        assert mock_gen.call_count == 2
        with db.connect() as conn:
            assert _dims(conn, 42)["generated_headlines"] == _FAKE_HEADLINES


def test_never_raises_on_generation_failure_and_leaves_no_partial_write(db):
    with db.begin() as conn:
        _seed_full_cycle(conn)

    with patch("generation.pillar_headlines.generate_pillar_headlines", side_effect=RuntimeError("boom")):
        worker._sweep_full_cycle_pillar_headlines()  # must not raise

    with db.connect() as conn:
        stored = _dims(conn)
    assert "generated_headlines" not in stored


def test_skips_entirely_without_an_api_key(db, monkeypatch):
    monkeypatch.delenv("OPEN_AI_API_KEY", raising=False)
    with db.begin() as conn:
        _seed_full_cycle(conn)

    with patch("generation.pillar_headlines.generate_pillar_headlines") as mock_gen:
        worker._sweep_full_cycle_pillar_headlines()

    mock_gen.assert_not_called()
