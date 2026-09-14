"""
Tests for transcript browsing (2a/2f) — transcript_pick.py's
list_transcript_index and get_transcript_detail. select_transcript's
own cascade/tests (test_transcript_pick.py) are untouched; these two
functions are the additive "browse every query" surface behind it.
Own fixture (not test_transcript_pick.py's _run helper) since these
tests need multiple runs sharing one query_id, across platforms and
run_numbers, which _run's 1:1 run_id<->query_id convention doesn't
support without risking its own 35 passing tests.
"""
import pytest
from sqlalchemy import create_engine, text

import soa_shared.config as config
from app.services.transcript_pick import list_transcript_index, get_transcript_detail

CYCLE_ID = 500
OTHER_CYCLE_ID = 501
PRIMARY_ID = 700
COMPETITOR_ID = 701


@pytest.fixture(autouse=True)
def _narrative_enabled(monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIPT_NARRATIVE_ENABLED", True)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE soa_entities (id INTEGER PRIMARY KEY, name TEXT, slug TEXT, aliases TEXT, website_url TEXT)")
        conn.exec_driver_sql("CREATE TABLE soa_cycle_entities (id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER, role TEXT)")
        conn.exec_driver_sql("CREATE TABLE soa_queries (id INTEGER PRIMARY KEY, stage TEXT, persona TEXT, query_text TEXT, tier TEXT, expected_answer TEXT, provenance TEXT, source_ref TEXT)")
        conn.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, query_id INTEGER, status TEXT,
                platform TEXT, raw_response TEXT, run_at TEXT, run_number INTEGER
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_coded_mentions (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                mentioned BOOLEAN, position INTEGER, strength TEXT,
                deal_cited BOOLEAN, deal_types TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_price_observations (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                stated_price FLOAT, claimed_net_price FLOAT, merchant_name TEXT, merchant_slug TEXT,
                attribution_status TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_incentive_scores (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER, price_observation_id INTEGER,
                scoring_grain TEXT, status TEXT, measurement_status TEXT,
                stated_price FLOAT, ground_truth_true_cost FLOAT, net_price_accuracy BOOLEAN,
                ground_truth_applied_deals TEXT
            )
        """)
        conn.execute(text(
            "INSERT INTO soa_entities (id, name, slug, aliases, website_url) VALUES (:pid, 'Allbirds', 'allbirds', '[]', 'https://allbirds.com')"
        ), {"pid": PRIMARY_ID})
        conn.execute(text("INSERT INTO soa_entities (id, name, slug) VALUES (:cid, 'Nike', 'nike')"), {"cid": COMPETITOR_ID})
        conn.execute(text(
            "INSERT INTO soa_cycle_entities (cycle_id, entity_id, role) VALUES (:cid, :pid, 'primary')"
        ), {"cid": CYCLE_ID, "pid": PRIMARY_ID})
        conn.execute(text(
            "INSERT INTO soa_cycle_entities (cycle_id, entity_id, role) VALUES (:cid, :cid2, 'competitor')"
        ), {"cid": CYCLE_ID, "cid2": COMPETITOR_ID})
    return engine


def _query(conn, query_id, stage="Ready to Buy", persona="Value-Conscious", query_text="Best shoes?"):
    conn.execute(text(
        "INSERT INTO soa_queries (id, stage, persona, query_text) VALUES (:id, :stage, :persona, :text)"
    ), {"id": query_id, "stage": stage, "persona": persona, "text": query_text})


def _run(conn, run_id, query_id, platform="chatgpt", run_number=1, raw_response="A generic answer.", cycle_id=CYCLE_ID, status="success"):
    conn.execute(text(
        "INSERT INTO soa_runs (id, cycle_id, query_id, status, platform, raw_response, run_at, run_number) "
        "VALUES (:id, :cid, :qid, :status, :platform, :resp, '2026-08-07T00:00:00', :rn)"
    ), {"id": run_id, "cid": cycle_id, "qid": query_id, "status": status, "platform": platform, "resp": raw_response, "rn": run_number})


def _mention(conn, run_id, entity_id, mentioned=1, position=None, strength=None, deal_cited=0):
    conn.execute(text(
        "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, position, strength, deal_cited, deal_types) "
        "VALUES (:rid, :eid, :m, :pos, :str, :dc, '[]')"
    ), {"rid": run_id, "eid": entity_id, "m": mentioned, "pos": position, "str": strength, "dc": deal_cited})


# ─── list_transcript_index ─────────────────────────────────────────────────

def test_index_is_empty_for_a_cycle_with_no_successful_runs(db):
    result = list_transcript_index(db.connect(), CYCLE_ID, PRIMARY_ID)
    assert result == {"queries": [], "page": 1, "page_size": 25, "total_queries": 0, "curated_run_id": None}


def test_index_groups_multiple_runs_under_one_query_row(db):
    with db.begin() as conn:
        _query(conn, 1)
        _run(conn, 101, query_id=1, platform="chatgpt", run_number=1)
        _run(conn, 102, query_id=1, platform="gemini", run_number=1)
        _mention(conn, 101, PRIMARY_ID, mentioned=1, strength="Primary")
        _mention(conn, 102, PRIMARY_ID, mentioned=1, strength="Primary")

    result = list_transcript_index(db.connect(), CYCLE_ID, PRIMARY_ID)

    assert len(result["queries"]) == 1
    row = result["queries"][0]
    assert row["query_id"] == 1
    assert row["index"] == 1
    assert row["total_queries"] == 1
    assert {r["platform"] for r in row["runs"]} == {"chatgpt", "gemini"}
    assert {r["run_id"] for r in row["runs"]} == {101, 102}


def test_index_narrative_case_is_the_strongest_signal_across_a_querys_runs(db):
    """One platform shows a clean mention, the other a real leak — the
    query-level chip must show the leak, not average it away."""
    with db.begin() as conn:
        _query(conn, 1)
        _run(conn, 101, query_id=1, platform="chatgpt", run_number=1)
        _run(conn, 102, query_id=1, platform="gemini", run_number=1)
        _mention(conn, 101, PRIMARY_ID, mentioned=1, strength="Primary")  # clean
        _mention(conn, 102, PRIMARY_ID, mentioned=0)  # not mentioned on gemini

    result = list_transcript_index(db.connect(), CYCLE_ID, PRIMARY_ID)

    assert result["queries"][0]["narrative_case"] == "not_mentioned"


def test_index_is_ordered_and_1_indexed_by_query(db):
    with db.begin() as conn:
        for qid in (3, 1, 2):
            _query(conn, qid)
            _run(conn, qid * 10, query_id=qid)
            _mention(conn, qid * 10, PRIMARY_ID, mentioned=1)

    result = list_transcript_index(db.connect(), CYCLE_ID, PRIMARY_ID)

    assert [r["query_id"] for r in result["queries"]] == [1, 2, 3]
    assert [r["index"] for r in result["queries"]] == [1, 2, 3]


def test_index_paginates(db):
    with db.begin() as conn:
        for qid in range(1, 6):
            _query(conn, qid)
            _run(conn, qid * 10, query_id=qid)
            _mention(conn, qid * 10, PRIMARY_ID, mentioned=1)

    page1 = list_transcript_index(db.connect(), CYCLE_ID, PRIMARY_ID, page=1, page_size=2)
    page2 = list_transcript_index(db.connect(), CYCLE_ID, PRIMARY_ID, page=2, page_size=2)
    page3 = list_transcript_index(db.connect(), CYCLE_ID, PRIMARY_ID, page=3, page_size=2)

    assert [r["query_id"] for r in page1["queries"]] == [1, 2]
    assert [r["query_id"] for r in page2["queries"]] == [3, 4]
    assert [r["query_id"] for r in page3["queries"]] == [5]
    assert page1["total_queries"] == 5


def test_index_page_size_is_capped(db):
    with db.begin() as conn:
        _query(conn, 1)
        _run(conn, 10, query_id=1)
        _mention(conn, 10, PRIMARY_ID, mentioned=1)

    result = list_transcript_index(db.connect(), CYCLE_ID, PRIMARY_ID, page_size=999)
    assert result["page_size"] == 50


def test_index_never_crosses_a_different_cycles_boundary(db):
    with db.begin() as conn:
        _query(conn, 1)
        _run(conn, 10, query_id=1, cycle_id=OTHER_CYCLE_ID)
        _mention(conn, 10, PRIMARY_ID, mentioned=1)

    result = list_transcript_index(db.connect(), CYCLE_ID, PRIMARY_ID)
    assert result["queries"] == []


# ─── get_transcript_detail ──────────────────────────────────────────────────

def test_detail_returns_none_for_an_unknown_run_id(db):
    result = get_transcript_detail(db.connect(), CYCLE_ID, PRIMARY_ID, run_id=999)
    assert result is None


def test_detail_returns_none_for_a_run_id_from_a_different_cycle(db):
    with db.begin() as conn:
        _query(conn, 1)
        _run(conn, 10, query_id=1, cycle_id=OTHER_CYCLE_ID)
        _mention(conn, 10, PRIMARY_ID, mentioned=1)

    result = get_transcript_detail(db.connect(), CYCLE_ID, PRIMARY_ID, run_id=10)
    assert result is None


def test_detail_matches_the_widgets_existing_payload_shape(db):
    with db.begin() as conn:
        _query(conn, 1, query_text="Are these worth it?")
        _run(conn, 101, query_id=1, platform="gemini", run_number=2, raw_response="Yes, Allbirds are great.")
        _mention(conn, 101, PRIMARY_ID, mentioned=1, strength="Primary")

    result = get_transcript_detail(db.connect(), CYCLE_ID, PRIMARY_ID, run_id=101)

    assert result["run_id"] == 101
    assert result["platform"] == "gemini"
    assert result["query_text"] == "Are these worth it?"
    assert result["query_index"] == 1
    assert result["total_queries"] == 1
    assert result["response_text"] == "Yes, Allbirds are great."
    assert result["narrative_case"] == "mentioned_no_leak"
    assert result["selection_tier"] == 0
    assert "facts" in result and "spans" in result
    assert result["facts"]["mentioned"] is True


def test_detail_classification_matches_the_index_chip_for_the_same_run(db):
    """The index's per-query chip and a run's own detail classification
    must agree — both derive from the same _narrative_case_for."""
    with db.begin() as conn:
        _query(conn, 1)
        _run(conn, 101, query_id=1)
        _mention(conn, 101, PRIMARY_ID, mentioned=0)

    index = list_transcript_index(db.connect(), CYCLE_ID, PRIMARY_ID)
    detail = get_transcript_detail(db.connect(), CYCLE_ID, PRIMARY_ID, run_id=101)

    assert index["queries"][0]["narrative_case"] == detail["narrative_case"] == "not_mentioned"


def test_detail_respects_the_narrative_flag_exactly_like_the_curated_pick(db, monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIPT_NARRATIVE_ENABLED", False)
    with db.begin() as conn:
        _query(conn, 1)
        _run(conn, 101, query_id=1)
        _mention(conn, 101, PRIMARY_ID, mentioned=1, strength="Primary")

    result = get_transcript_detail(db.connect(), CYCLE_ID, PRIMARY_ID, run_id=101)

    assert "right" not in result
    assert "leaked" not in result


def test_index_curated_run_id_matches_select_transcripts_own_pick(db):
    from app.services.transcript_pick import select_transcript

    with db.begin() as conn:
        _query(conn, 1)
        _run(conn, 101, query_id=1, platform="chatgpt")
        _mention(conn, 101, PRIMARY_ID, mentioned=1, strength="Primary")
        _query(conn, 2)
        _run(conn, 102, query_id=2, platform="chatgpt")
        _mention(conn, 102, PRIMARY_ID, mentioned=0)

    index = list_transcript_index(db.connect(), CYCLE_ID, PRIMARY_ID)
    curated = select_transcript(db.connect(), CYCLE_ID, PRIMARY_ID)

    assert index["curated_run_id"] == curated["run_id"] == 101  # tier 3 (mentioned_no_leak) outranks tier 4 (not_mentioned)
