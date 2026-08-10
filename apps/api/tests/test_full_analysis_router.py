"""
Tests for apps/api/app/routers/full_analysis.py — NewCycleFlow's own
additive endpoints (continuation-mode audit resolve, competitor
auto-suggestion, crawl launch). Calls the route functions directly, same
pattern as test_create_cycle_truecost.py — a real in-memory SQLite
database stands in for engine.begin()/engine.connect().
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine

import app.routers.full_analysis as full_analysis_router
from app.schemas import LaunchCrawlRequest, SuggestCompetitorsRequest
from app.services.competitor_suggestion import CompetitorCandidate

CURRENT_USER = {"organization_id": 1, "user_id": "u1"}


@pytest.fixture
def patched_engine(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_requests (
                id INTEGER PRIMARY KEY, token TEXT UNIQUE, status TEXT,
                cycle_id INTEGER, brand_name TEXT, brand_entity_id INTEGER,
                competitor_entity_ids TEXT, competitor_names TEXT,
                store_url TEXT, created_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_entities (
                id INTEGER PRIMARY KEY, category TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, organization_id INTEGER
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_scan_results (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, lite_request_id INTEGER,
                input_url TEXT, status TEXT
            )
        """)
    monkeypatch.setattr(full_analysis_router, "engine", engine)
    return engine


# ─── GET /full-analysis/audit/{token} ────────────────────────────────────

def test_get_audit_continuation_resolves_brand_and_composite(patched_engine, monkeypatch):
    with patched_engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO soa_entities (id, category) VALUES (1, 'beauty')")
        conn.exec_driver_sql("""
            INSERT INTO soa_lite_requests
              (id, token, status, cycle_id, brand_name, brand_entity_id,
               competitor_entity_ids, competitor_names, store_url, created_at)
            VALUES
              (1, 'tok123', 'complete', 42, 'Acme', 1,
               '[2, 3]', '["Rival A", "Rival B"]', 'https://acme.com', '2026-08-01 00:00:00')
        """)

    monkeypatch.setattr(
        full_analysis_router, "_build_report_payload",
        lambda conn, lite_request_id, cycle_id: {
            "composite": 74, "pillars": {"verdict": "AGENT-READY"}, "store_domain": "acme.com",
        },
    )

    result = full_analysis_router.get_audit_continuation(token="tok123", current_user=CURRENT_USER)

    assert result.brand_name == "Acme"
    assert result.brand_entity_id == 1
    assert result.category == "beauty"
    assert result.composite == 74
    assert result.verdict == "AGENT-READY"
    assert result.store_domain == "acme.com"
    assert result.audited_at == "2026-08-01"
    assert [c.name for c in result.competitors] == ["Rival A", "Rival B"]
    assert [c.entity_id for c in result.competitors] == [2, 3]


def test_get_audit_continuation_404_unknown_token(patched_engine):
    with pytest.raises(HTTPException) as exc_info:
        full_analysis_router.get_audit_continuation(token="nope", current_user=CURRENT_USER)
    assert exc_info.value.status_code == 404


def test_get_audit_continuation_409_when_not_complete(patched_engine):
    with patched_engine.begin() as conn:
        conn.exec_driver_sql("""
            INSERT INTO soa_lite_requests
              (id, token, status, cycle_id, brand_name, brand_entity_id,
               competitor_entity_ids, competitor_names, store_url, created_at)
            VALUES
              (1, 'tok456', 'running', NULL, 'Acme', NULL, NULL, NULL, NULL, NULL)
        """)

    with pytest.raises(HTTPException) as exc_info:
        full_analysis_router.get_audit_continuation(token="tok456", current_user=CURRENT_USER)
    assert exc_info.value.status_code == 409


# ─── POST /full-analysis/suggest-competitors ─────────────────────────────

def test_suggest_competitors_degrades_to_manual_only_without_api_key(monkeypatch):
    monkeypatch.delenv("OPEN_AI_API_KEY", raising=False)

    req = SuggestCompetitorsRequest(brand_name="Acme", manual_names=["Rival A"])
    result = full_analysis_router.suggest_competitors(req, current_user=CURRENT_USER)

    assert result.status == "degraded"
    assert result.reason == "suggestions_unavailable"
    assert result.source == "manual"
    assert [c.name for c in result.competitors] == ["Rival A"]


def test_suggest_competitors_degraded_reason_never_leaks_the_env_var_name(monkeypatch):
    monkeypatch.delenv("OPEN_AI_API_KEY", raising=False)

    req = SuggestCompetitorsRequest(brand_name="Acme")
    result = full_analysis_router.suggest_competitors(req, current_user=CURRENT_USER)

    assert "OPEN_AI_API_KEY" not in (result.reason or "")


def test_suggest_competitors_merges_generated_with_manual(monkeypatch):
    monkeypatch.setenv("OPEN_AI_API_KEY", "test-key")
    monkeypatch.setattr(
        full_analysis_router, "generate_competitors",
        lambda brand_name, api_key, **kw: [CompetitorCandidate(name="Generated Co", domain="gen.co")],
    )

    req = SuggestCompetitorsRequest(brand_name="Acme", manual_names=["Rival A"])
    result = full_analysis_router.suggest_competitors(req, current_user=CURRENT_USER)

    assert result.status == "ok"
    assert result.reason is None
    assert result.source == "mixed"
    names = {c.name for c in result.competitors}
    assert names == {"Rival A", "Generated Co"}


def test_suggest_competitors_ok_status_even_when_generation_legitimately_finds_none(monkeypatch):
    """A configured, working suggestion service that genuinely found no
    competitors is NOT a degraded state — status stays 'ok' so the client
    never shows the "suggestions unavailable" notice for an honest empty
    result."""
    monkeypatch.setenv("OPEN_AI_API_KEY", "test-key")
    monkeypatch.setattr(full_analysis_router, "generate_competitors", lambda brand_name, api_key, **kw: [])

    req = SuggestCompetitorsRequest(brand_name="Acme")
    result = full_analysis_router.suggest_competitors(req, current_user=CURRENT_USER)

    assert result.status == "ok"
    assert result.reason is None
    assert result.competitors == []


# ─── POST /full-analysis/launch-crawl ────────────────────────────────────

def test_launch_crawl_creates_pending_scan_row(patched_engine):
    with patched_engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO soa_cycles (id, organization_id) VALUES (42, 1)")

    req = LaunchCrawlRequest(cycle_id=42, store_url="https://acme.com")
    result = full_analysis_router.launch_crawl(req, current_user=CURRENT_USER)

    assert result.status == "pending"
    assert result.cycle_id == 42

    with patched_engine.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT cycle_id, lite_request_id, input_url, status FROM soa_lite_scan_results WHERE id = ?",
            (result.scan_id,),
        ).fetchone()
    assert row == (42, None, "https://acme.com", "pending")


def test_launch_crawl_404_for_unknown_or_foreign_cycle(patched_engine):
    with patched_engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO soa_cycles (id, organization_id) VALUES (42, 999)")

    req = LaunchCrawlRequest(cycle_id=42, store_url="https://acme.com")
    with pytest.raises(HTTPException) as exc_info:
        full_analysis_router.launch_crawl(req, current_user=CURRENT_USER)
    assert exc_info.value.status_code == 404
