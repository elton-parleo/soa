"""
Tests for apps/api/app/routers/lite_requests.py — the internal Audits
list.

Route functions are called directly against an in-memory SQLite database
standing in for engine.connect(), the same pattern
test_full_analysis_router.py and test_public_lite_status.py use. The
auth gate itself is asserted against app.py's source, because this app
has no TestClient harness — importing the full FastAPI app pulls in
routers that need a live DATABASE_URL at import time (see
test_cors_audit_origin.py's note on the same constraint).
"""
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine

import app.routers.lite_requests as lite_requests
from app.services.lite_score_batch import (
    SCORE_NOT_MEASURABLE,
    SCORE_PARTIAL_READ,
    SCORE_PENDING,
    SCORE_UNAVAILABLE,
    degraded_reason_for,
)
from soa_shared.org_helpers import LEADGEN_ORG_NAME

LEADGEN_ORG_ID = 7
OTHER_ORG_ID = 1

NOW = datetime(2026, 9, 15, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE organizations (
                id INTEGER PRIMARY KEY, name TEXT UNIQUE
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_requests (
                id INTEGER PRIMARY KEY, token TEXT UNIQUE, email TEXT,
                brand_name TEXT, competitor_names TEXT, competitor_source TEXT,
                brand_entity_id INTEGER, competitor_entity_ids TEXT,
                study_type TEXT, store_url TEXT, cycle_id INTEGER,
                status TEXT, error_message TEXT, events TEXT DEFAULT '[]',
                report_email_sent_at TIMESTAMP, lead_notified_at TIMESTAMP,
                ip_hash TEXT, organization_id INTEGER,
                created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_scan_results (
                id INTEGER PRIMARY KEY, lite_request_id INTEGER UNIQUE, status TEXT,
                total_score INTEGER, integrity_capped BOOLEAN, dimensions TEXT,
                pages_fetched TEXT, membership_probe TEXT, revenue_probe TEXT,
                fetch_probe TEXT, input_url TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, cycle_code TEXT, status TEXT,
                source_lite_request_id INTEGER, study_series_id TEXT
            )
        """)
        # Scoring tables — a complete row carrying a cycle_id reaches the
        # batched scorer, which queries all of these.
        conn.exec_driver_sql("""
            CREATE TABLE soa_entities (
                id INTEGER PRIMARY KEY, name TEXT, slug TEXT UNIQUE,
                entity_type TEXT, website_url TEXT
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
                slice_type TEXT, slice_value TEXT, total_runs INTEGER,
                total_mentions INTEGER, mention_rate FLOAT, soa_pct FLOAT,
                position_index FLOAT, rsi_score FLOAT, deal_citation_rate FLOAT,
                platform_dist_index FLOAT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_queries (id INTEGER PRIMARY KEY, stage TEXT)
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
        conn.exec_driver_sql("""
            CREATE TABLE soa_pass2_coding_log (
                id INTEGER PRIMARY KEY, run_id INTEGER, coding_pass_version INTEGER
            )
        """)
        conn.exec_driver_sql(
            "INSERT INTO organizations (id, name) VALUES (?, ?)",
            (LEADGEN_ORG_ID, LEADGEN_ORG_NAME),
        )
        conn.exec_driver_sql(
            "INSERT INTO organizations (id, name) VALUES (?, 'Parleo')", (OTHER_ORG_ID,),
        )
    monkeypatch.setattr(lite_requests, "engine", engine)
    return engine


def _insert(conn, **kwargs):
    row = {
        "token": "tok-1",
        "brand_name": "Acme Co",
        "status": "complete",
        "organization_id": LEADGEN_ORG_ID,
        "created_at": NOW,
        "events": "[]",
    }
    row.update(kwargs)
    for key in ("competitor_names", "competitor_entity_ids", "events"):
        if isinstance(row.get(key), (list, dict)):
            row[key] = json.dumps(row[key])
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.exec_driver_sql(
        f"INSERT INTO soa_lite_requests ({cols}) VALUES ({marks})", tuple(row.values()),
    )


# Route functions are called directly, so FastAPI never resolves the
# Query(...) defaults — every parameter is passed explicitly here, the
# same way the repo's other direct-call router tests do it.
_LIST_DEFAULTS = dict(
    page=1,
    page_size=lite_requests.DEFAULT_PAGE_SIZE,
    q=None,
    status=None,
    leads_only=False,
    competitor_source=None,
    created_after=None,
    created_before=None,
    sort=lite_requests.SORT_CREATED_DESC,
)


def _list(**kwargs):
    params = dict(_LIST_DEFAULTS)
    params.update(kwargs)
    return lite_requests.list_lite_requests(**params)


# ─── Auth ────────────────────────────────────────────────────────────────


def test_router_is_registered_behind_verify_token():
    """The gate is applied in app.py, not per-route, so assert it there."""
    src = (Path(__file__).resolve().parents[1] / "app" / "app.py").read_text()
    assert "lite_requests," in src, "router not imported in app.py"
    # Everything from the router argument to the closing paren of that
    # include_router call (a bare ")" at the start of a line).
    registration = src.split("lite_requests.router,")[1].split("\n)")[0]
    assert 'prefix="/api"' in registration
    assert "dependencies=[Depends(verify_token)]" in registration


def test_router_never_calls_the_org_creating_helper():
    """
    The read-only guarantee: this router resolves the Lead Gen org with
    a SELECT, never get_or_create_leadgen_org (which INSERTs).
    """
    src = (Path(__file__).resolve().parents[1] / "app" / "routers" / "lite_requests.py").read_text()
    assert "get_or_create_leadgen_org" not in src.split('"""', 2)[2]
    for write in ("INSERT ", "UPDATE ", "DELETE ", "engine.begin("):
        assert write not in src, f"{write!r} found — this router must stay read-only"


# ─── Org scoping ─────────────────────────────────────────────────────────


def test_only_leadgen_org_rows_are_returned(db):
    with db.begin() as conn:
        _insert(conn, token="mine", organization_id=LEADGEN_ORG_ID)
        _insert(conn, token="theirs", organization_id=OTHER_ORG_ID)

    result = _list()
    assert [i.token for i in result.items] == ["mine"]
    assert result.total_count == 1
    assert result.summary.audits_count == 1


def test_detail_404s_for_a_row_in_another_org(db):
    with db.begin() as conn:
        _insert(conn, token="theirs", organization_id=OTHER_ORG_ID)

    with pytest.raises(HTTPException) as excinfo:
        lite_requests.get_lite_request(1)
    assert excinfo.value.status_code == 404


def test_missing_leadgen_org_returns_an_empty_page_not_an_error(db):
    with db.begin() as conn:
        conn.exec_driver_sql("DELETE FROM organizations WHERE name = ?", (LEADGEN_ORG_NAME,))
        _insert(conn, token="orphan")

    result = _list()
    assert result.items == []
    assert result.total_count == 0
    assert result.summary.audits_count == 0


# ─── Filters ─────────────────────────────────────────────────────────────


def test_q_matches_brand_email_token_and_store_url_case_insensitively(db):
    with db.begin() as conn:
        _insert(conn, token="t-brand", brand_name="Vuori")
        _insert(conn, token="t-email", brand_name="Other", email="m@VUORI.com")
        _insert(conn, token="vuori-token", brand_name="Other")
        _insert(conn, token="t-url", brand_name="Other", store_url="https://VuoriClothing.com")
        _insert(conn, token="t-miss", brand_name="Unrelated")

    tokens = {i.token for i in _list(q="vuori").items}
    assert tokens == {"t-brand", "t-email", "vuori-token", "t-url"}
    assert _list(q="vuori").total_count == 4


def test_status_filter_accepts_a_real_status(db):
    with db.begin() as conn:
        _insert(conn, token="ok", status="complete")
        _insert(conn, token="bad", status="failed")

    assert [i.token for i in _list(status="failed").items] == ["bad"]


def test_in_progress_pseudo_status_covers_all_four_non_terminal_statuses(db):
    with db.begin() as conn:
        for i, status in enumerate(lite_requests.LITE_IN_PROGRESS_STATUSES):
            _insert(conn, token=f"wip-{i}", status=status)
        _insert(conn, token="done", status="complete")
        _insert(conn, token="dead", status="failed")

    result = _list(status="in_progress")
    assert len(result.items) == 4
    assert "done" not in {i.token for i in result.items}
    assert result.summary.in_progress_count == 4


def test_unknown_status_and_competitor_source_and_sort_are_rejected(db):
    for kwargs in (
        {"status": "nonsense"},
        {"competitor_source": "nonsense"},
        {"sort": "nonsense"},
    ):
        with pytest.raises(HTTPException) as excinfo:
            _list(**kwargs)
        assert excinfo.value.status_code == 422


def test_leads_only_filters_to_rows_with_an_email(db):
    with db.begin() as conn:
        _insert(conn, token="lead", email="a@b.com")
        _insert(conn, token="nolead")

    assert [i.token for i in _list(leads_only=True).items] == ["lead"]
    assert _list().summary.leads_count == 1


@pytest.mark.parametrize("source", ["generated", "manual", "mixed", "none"])
def test_competitor_source_filter(db, source):
    with db.begin() as conn:
        for candidate in ("generated", "manual", "mixed", "none"):
            _insert(conn, token=f"t-{candidate}", competitor_source=candidate)

    result = _list(competitor_source=source)
    assert [i.token for i in result.items] == [f"t-{source}"]


def test_created_after_and_before_bound_the_window(db):
    with db.begin() as conn:
        _insert(conn, token="old", created_at=NOW - timedelta(days=10))
        _insert(conn, token="mid", created_at=NOW - timedelta(days=5))
        _insert(conn, token="new", created_at=NOW)

    result = _list(
        created_after=NOW - timedelta(days=7), created_before=NOW - timedelta(days=1),
    )
    assert [i.token for i in result.items] == ["mid"]


def test_sort_defaults_to_newest_first_and_asc_is_allowed(db):
    with db.begin() as conn:
        _insert(conn, token="old", created_at=NOW - timedelta(days=2))
        _insert(conn, token="new", created_at=NOW)

    assert [i.token for i in _list().items] == ["new", "old"]
    assert [i.token for i in _list(sort="created_at_asc").items] == ["old", "new"]


# ─── Pagination ──────────────────────────────────────────────────────────


def test_pagination_pages_through_and_reports_unpaginated_totals(db):
    with db.begin() as conn:
        for i in range(5):
            _insert(conn, token=f"t{i}", created_at=NOW - timedelta(minutes=i))

    first = _list(page=1, page_size=2)
    assert [i.token for i in first.items] == ["t0", "t1"]
    assert first.total_count == 5
    assert first.summary.audits_count == 5

    third = _list(page=3, page_size=2)
    assert [i.token for i in third.items] == ["t4"]
    assert third.total_count == 5

    assert _list(page=99, page_size=2).items == []


def test_page_size_bounds_are_enforced_by_the_query_signature():
    """FastAPI enforces ge/le at the boundary, so assert the declared
    bounds rather than trying to smuggle an out-of-range value past a
    direct call that never validates."""
    assert lite_requests.DEFAULT_PAGE_SIZE == 25
    assert lite_requests.MAX_PAGE_SIZE == 100

    params = inspect.signature(lite_requests.list_lite_requests).parameters

    def _bounds(name):
        # Pydantic v2 keeps Query()'s ge/le as annotated-types metadata.
        return {
            type(m).__name__.lower(): getattr(m, type(m).__name__.lower())
            for m in params[name].default.metadata
        }

    assert params["page_size"].default.default == 25
    assert _bounds("page_size") == {"ge": 1, "le": 100}
    assert _bounds("page") == {"ge": 1}


# ─── ip_hash ─────────────────────────────────────────────────────────────


def test_ip_hash_is_absent_from_every_list_item(db):
    with db.begin() as conn:
        _insert(conn, token="t1", ip_hash="9f3a" + "b" * 56 + "c21e")

    item = _list().items[0]
    assert not hasattr(item, "ip_hash")
    assert "ip_hash" not in item.model_dump()
    assert "c21e" not in json.dumps(item.model_dump(), default=str)


def test_detail_truncates_ip_hash_to_first_four_and_last_four(db):
    with db.begin() as conn:
        _insert(conn, token="t1", ip_hash="9f3a" + "b" * 56 + "c21e")

    detail = lite_requests.get_lite_request(1)
    assert detail.ip_hash_truncated == "9f3a…c21e"
    assert "ip_hash" not in detail.model_dump()


def test_short_or_missing_ip_hash_is_withheld_entirely():
    assert lite_requests.truncate_ip_hash(None) is None
    assert lite_requests.truncate_ip_hash("") is None
    assert lite_requests.truncate_ip_hash("abcd1234") is None
    assert lite_requests.truncate_ip_hash("abcd12345") == "abcd…2345"


# ─── Derived: current task ───────────────────────────────────────────────


def test_current_task_comes_from_the_latest_state_or_done_event(db):
    events = [
        {"seq": 1, "ts": "2026-09-15T09:00:00+00:00", "kind": "state", "task": "run", "text": "queued"},
        {"seq": 2, "ts": "2026-09-15T09:01:00+00:00", "kind": "done", "task": "crawl", "text": "42 pages read"},
        {"seq": 3, "ts": "2026-09-15T09:02:00+00:00", "kind": "log", "task": "queries", "text": "writing…"},
    ]
    with db.begin() as conn:
        _insert(conn, token="t1", status="running", events=events)

    item = _list().items[0]
    assert item.current_task == "crawl"
    assert item.current_task_text == "42 pages read"


def test_state_events_keep_their_run_task_id(db):
    events = [{"seq": 1, "ts": "2026-09-15T09:00:00+00:00", "kind": "state", "task": "run", "text": "queued"}]
    with db.begin() as conn:
        _insert(conn, token="t1", status="pending", events=events)

    item = _list().items[0]
    assert item.current_task == "run"
    assert item.current_task_text == "queued"


def test_empty_events_row_renders_with_null_derivations(db):
    """A pre-events row: the column defaults to '[]' and nothing breaks."""
    with db.begin() as conn:
        _insert(conn, token="t1", status="complete", events="[]", updated_at=None)

    item = _list().items[0]
    assert item.current_task is None
    assert item.current_task_text is None
    assert item.queries_done is None
    assert item.queries_total is None
    assert item.duration_seconds is None
    assert item.duration_is_estimate is False


# ─── Derived: queries progress ───────────────────────────────────────────


def test_queries_progress_parses_the_in_flight_format():
    events = [
        {"seq": 1, "kind": "log", "task": "queries", "text": "q3/24 answered"},
        {"seq": 2, "kind": "log", "task": "queries", "text": "q7/24 answered"},
    ]
    assert lite_requests.parse_queries_progress(events) == (7, 24)


def test_queries_progress_parses_the_done_format_as_complete():
    events = [
        {"seq": 1, "kind": "log", "task": "queries", "text": "q7/24 answered"},
        {"seq": 2, "kind": "done", "task": "queries", "text": "All 24 answers collected"},
    ]
    assert lite_requests.parse_queries_progress(events) == (24, 24)


@pytest.mark.parametrize("bad_text", [
    "q7 of 24 answered",
    "answered q7/24",
    "All twenty-four answers collected",
    "q7/24 answered now",
    "scoring the answers",
    "",
])
def test_queries_progress_falls_back_to_null_on_any_mismatch(bad_text):
    events = [{"seq": 1, "kind": "log", "task": "queries", "text": bad_text}]
    assert lite_requests.parse_queries_progress(events) == (None, None)


def test_queries_progress_ignores_other_tasks_and_chip_only_events():
    events = [
        {"seq": 1, "kind": "done", "task": "competitors", "text": "q5/5 answered"},
        {"seq": 2, "kind": "done", "task": "scoring", "text": "All 12 answers collected"},
    ]
    assert lite_requests.parse_queries_progress(events) == (None, None)


# ─── Derived: duration ───────────────────────────────────────────────────


def test_duration_prefers_the_report_done_event_and_is_not_an_estimate(db):
    events = [
        {"seq": 1, "ts": "2026-09-15T10:00:00+00:00", "kind": "state", "task": "run", "text": "queued"},
        {"seq": 2, "ts": "2026-09-15T10:06:12+00:00", "kind": "done", "task": "report", "text": "ready"},
    ]
    with db.begin() as conn:
        _insert(conn, token="t1", events=events, created_at=NOW, updated_at=NOW + timedelta(hours=3))

    item = _list().items[0]
    assert item.duration_seconds == pytest.approx(372.0)
    assert item.duration_is_estimate is False


def test_duration_falls_back_to_updated_at_and_is_flagged_an_estimate(db):
    with db.begin() as conn:
        _insert(conn, token="t1", created_at=NOW, updated_at=NOW + timedelta(seconds=400))

    item = _list().items[0]
    assert item.duration_seconds == pytest.approx(400.0)
    assert item.duration_is_estimate is True


def test_duration_is_null_when_the_worker_has_not_touched_the_row(db):
    with db.begin() as conn:
        _insert(conn, token="t1", status="pending", created_at=NOW, updated_at=None)

    item = _list().items[0]
    assert item.duration_seconds is None


# ─── Continuation join ───────────────────────────────────────────────────


def test_continuation_cycle_is_joined_when_one_exists(db):
    with db.begin() as conn:
        _insert(conn, token="t1")
        conn.exec_driver_sql(
            "INSERT INTO soa_cycles (id, cycle_code, status, source_lite_request_id, study_series_id) "
            "VALUES (412, 'CYC-0412', 'running', 1, 'allbirds-2026q3')"
        )

    item = _list().items[0]
    assert item.continuation_cycle_id == 412
    assert item.continuation_cycle_code == "CYC-0412"
    assert item.continuation_cycle_status == "running"
    assert _list().summary.continuation_count == 1

    detail = lite_requests.get_lite_request(1)
    assert detail.study_series_id == "allbirds-2026q3"


def test_continuation_fields_are_null_when_no_cycle_points_at_the_row(db):
    with db.begin() as conn:
        _insert(conn, token="t1", cycle_id=99)
        # The audit's OWN cycle is not a continuation — only
        # source_lite_request_id makes one.
        conn.exec_driver_sql(
            "INSERT INTO soa_cycles (id, cycle_code, status) VALUES (99, 'CYC-LITE', 'complete')"
        )

    item = _list().items[0]
    assert item.continuation_cycle_id is None
    assert item.continuation_cycle_code is None
    assert item.continuation_cycle_status is None
    assert _list().summary.continuation_count == 0


# ─── Competitors ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("source,names,expected", [
    (None, ["A", "B"], 2),
    ("manual", ["A", "B"], 2),
    ("generated", ["A", "B", "C"], 0),
    ("none", [], 0),
    ("mixed", ["A", "B", "C"], None),
])
def test_manual_competitor_count_only_when_exactly_derivable(source, names, expected):
    assert lite_requests.manual_competitor_count(names, source) == expected


def test_competitor_names_and_source_reach_the_list_item(db):
    with db.begin() as conn:
        _insert(conn, token="t1", competitor_names=["Rothy's", "Veja"], competitor_source="mixed")

    item = _list().items[0]
    assert item.competitor_names == ["Rothy's", "Veja"]
    assert item.competitor_source == "mixed"
    assert item.manual_competitor_count is None


# ─── Scan join ───────────────────────────────────────────────────────────


def test_scan_fields_are_joined_and_pages_are_counted(db):
    with db.begin() as conn:
        _insert(conn, token="t1")
        conn.exec_driver_sql(
            "INSERT INTO soa_lite_scan_results "
            "(lite_request_id, status, total_score, integrity_capped, pages_fetched) "
            "VALUES (1, 'complete', 71, 0, ?)",
            (json.dumps([{"url": "a"}, {"url": "b"}, {"url": "c"}]),),
        )

    item = _list().items[0]
    assert item.scan_status == "complete"
    assert item.scan_total_score == 71
    assert item.scan_integrity_capped is False
    assert item.scan_pages_fetched_count == 3


def test_scan_fields_are_null_without_a_scan_row(db):
    with db.begin() as conn:
        _insert(conn, token="t1")

    item = _list().items[0]
    assert item.scan_status is None
    assert item.scan_pages_fetched_count is None


# ─── Score states ────────────────────────────────────────────────────────


def test_in_progress_rows_report_pending_and_failed_rows_not_measurable(db):
    with db.begin() as conn:
        _insert(conn, token="wip", status="running", cycle_id=1)
        _insert(conn, token="dead", status="failed", cycle_id=2, error_message="FetchError: blocked")

    by_token = {i.token: i for i in _list().items}
    assert by_token["wip"].score_state == SCORE_PENDING
    assert by_token["wip"].composite_score is None
    assert by_token["dead"].score_state == SCORE_NOT_MEASURABLE
    assert by_token["dead"].error_message == "FetchError: blocked"


def test_complete_row_without_a_cycle_is_unavailable_not_pending(db):
    with db.begin() as conn:
        _insert(conn, token="t1", status="complete", cycle_id=None)

    item = _list().items[0]
    assert item.score_state == SCORE_UNAVAILABLE
    assert item.composite_score is None


# ─── Partial read (degraded crawl) ───────────────────────────────────────

# engine.py writes degraded_reason as a sibling key inside the same
# `dimensions` jsonb, and build_scan_payload only reads it for a scan
# that reached a non-'complete' terminal state.
_DEGRADED_DIMENSIONS = {
    "degraded_reason": "every sampled product URL returned a challenge page",
    "degraded_banner_facts": {"sampled": 14, "readable": 0},
    "scorer_version": "5",
}


def _insert_scan(conn, lite_request_id, status="complete", dimensions=None, total_score=None):
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_scan_results "
        "(lite_request_id, status, total_score, integrity_capped, dimensions) "
        "VALUES (?, ?, ?, 0, ?)",
        (
            lite_request_id, status, total_score,
            json.dumps(dimensions) if dimensions is not None else None,
        ),
    )


def test_degraded_scan_reports_partial_read_with_its_reason(db):
    with db.begin() as conn:
        _insert(conn, token="t1", status="complete", cycle_id=None)
        _insert_scan(conn, 1, status="blocked", dimensions=_DEGRADED_DIMENSIONS)

    item = _list().items[0]
    assert item.score_state == SCORE_PARTIAL_READ
    assert item.degraded_reason == _DEGRADED_DIMENSIONS["degraded_reason"]
    assert item.scan_status == "blocked"


def test_non_degraded_scan_does_not_report_partial_read(db):
    with db.begin() as conn:
        _insert(conn, token="t1", status="complete", cycle_id=None)
        # A completed scan: build_scan_payload never populates
        # degraded_reason on this path, whatever the dimensions hold.
        _insert_scan(conn, 1, status="complete", dimensions=_DEGRADED_DIMENSIONS, total_score=71)

    item = _list().items[0]
    assert item.degraded_reason is None
    assert item.score_state != SCORE_PARTIAL_READ
    assert item.score_state == SCORE_UNAVAILABLE


def test_row_with_no_scan_row_at_all_is_not_partial_read(db):
    """A LEFT JOIN that matched nothing yields a tuple of Nones, which is
    truthy — the guard in degraded_reason_for is what keeps that from
    being read as a degraded scan."""
    with db.begin() as conn:
        _insert(conn, token="t1", status="complete", cycle_id=None)

    item = _list().items[0]
    assert item.degraded_reason is None
    assert item.score_state == SCORE_UNAVAILABLE


def test_failed_row_still_reports_why_its_crawl_came_up_short(db):
    """The request's own status wins the score_state, but the reason
    still rides along so the drawer can show it."""
    with db.begin() as conn:
        _insert(conn, token="t1", status="failed", cycle_id=None, error_message="FetchError")
        _insert_scan(conn, 1, status="blocked", dimensions=_DEGRADED_DIMENSIONS)

    item = _list().items[0]
    assert item.score_state == SCORE_NOT_MEASURABLE
    assert item.degraded_reason == _DEGRADED_DIMENSIONS["degraded_reason"]


def test_in_progress_row_never_reports_a_degraded_reason(db):
    """Mid-run the crawl has not come up short — it has not finished."""
    with db.begin() as conn:
        _insert(conn, token="t1", status="running", cycle_id=None)
        _insert_scan(conn, 1, status="running", dimensions=_DEGRADED_DIMENSIONS)

    item = _list().items[0]
    assert item.score_state == SCORE_PENDING
    assert item.degraded_reason is None


def test_detail_carries_the_degraded_reason_too(db):
    with db.begin() as conn:
        _insert(conn, token="t1", status="complete", cycle_id=None)
        _insert_scan(conn, 1, status="blocked", dimensions=_DEGRADED_DIMENSIONS)

    detail = lite_requests.get_lite_request(1)
    assert detail.score_state == SCORE_PARTIAL_READ
    assert detail.degraded_reason == _DEGRADED_DIMENSIONS["degraded_reason"]


def test_detail_carries_the_discovery_outcome_for_triage(db):
    """Discovery follow-up (Part 3): code + summary reach the admin
    drawer straight off dimensions["discovery_outcome"], independent of
    whether a pillars payload was ever built (this row has no cycle_id
    at all) — so a zero-PDP run can be triaged without opening the raw
    dimensions JSON."""
    discovery_outcome = {
        "code": "product_sitemap_unrecognized",
        "summary": "we read 5 of your sitemaps, including sitemap_0-product.xml (1,110 URLs)...",
        "found_candidates": 0, "product_pages_attempted": 0, "product_pages_fetched": 0,
        "sitemaps": [], "child_chosen": None, "example_urls": [], "tiers": [],
        "robots_excluded": 0, "llm": None, "short_circuited": False,
    }
    with db.begin() as conn:
        _insert(conn, token="t1", status="complete", cycle_id=None)
        _insert_scan(conn, 1, status="complete", dimensions={
            **_DEGRADED_DIMENSIONS, "discovery_outcome": discovery_outcome,
        })

    detail = lite_requests.get_lite_request(1)
    assert detail.discovery_outcome == discovery_outcome


def test_detail_discovery_outcome_is_none_with_no_scan_row(db):
    with db.begin() as conn:
        _insert(conn, token="t1", status="pending", cycle_id=None)

    detail = lite_requests.get_lite_request(1)
    assert detail.discovery_outcome is None


def test_degraded_reason_for_guards_the_empty_join_tuple():
    assert degraded_reason_for(None) is None
    assert degraded_reason_for((None,) * 9) is None
    assert degraded_reason_for(
        ("blocked", None, None, json.dumps(_DEGRADED_DIMENSIONS), None, None, None, None, None)
    ) == _DEGRADED_DIMENSIONS["degraded_reason"]
