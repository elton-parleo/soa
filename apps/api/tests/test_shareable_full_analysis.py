"""
1d: tests for shareable Full Analysis reports — the owner endpoints
(full_analysis.py's create/get/revoke share link) and the public,
token-scoped read endpoint (public_full_analysis.py). Reuses
test_full_analysis_report_endpoint.py's schema/seed helper (same
_assemble_full_analysis_report both the owner and public routes read
through) rather than duplicating it — same convention
test_cycle_scoring_full.py already uses to import lite_pillars
fixtures.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text

import app.routers.full_analysis as full_analysis_router
import app.routers.public_full_analysis as public_full_analysis_router
from app.services.share_tokens import generate_public_token
from tests.test_full_analysis_report_endpoint import _seed_scored_cycle

CURRENT_USER = {"organization_id": 1, "user_id": "u1"}
OTHER_ORG_USER = {"organization_id": 2, "user_id": "u2"}


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, ip="1.2.3.4"):
        self.headers = {}
        self.client = _FakeClient(ip)


@pytest.fixture
def patched_engine(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, cycle_code TEXT UNIQUE, organization_id INTEGER,
                source_lite_request_id INTEGER, platforms TEXT, runs_per_query INTEGER
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_scan_results (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, lite_request_id INTEGER,
                status TEXT, total_score INTEGER, integrity_capped BOOLEAN,
                dimensions TEXT, pages_fetched TEXT, membership_probe TEXT,
                revenue_probe TEXT, fetch_probe TEXT, input_url TEXT
            )
        """)
        conn.exec_driver_sql("CREATE TABLE soa_entities (id INTEGER PRIMARY KEY, name TEXT, slug TEXT, website_url TEXT, aliases TEXT)")
        conn.exec_driver_sql("CREATE TABLE soa_cycle_entities (id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER, comparison_code TEXT, role TEXT)")
        conn.exec_driver_sql("""
            CREATE TABLE soa_metrics_results (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                slice_type TEXT, slice_value TEXT, total_runs INTEGER, total_mentions INTEGER,
                mention_rate FLOAT, soa_pct FLOAT, position_index FLOAT, rsi_score FLOAT,
                deal_citation_rate FLOAT, platform_dist_index FLOAT
            )
        """)
        conn.exec_driver_sql("CREATE TABLE soa_queries (id INTEGER PRIMARY KEY, stage TEXT, persona TEXT, query_text TEXT)")
        conn.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, query_id INTEGER, status TEXT, platform TEXT,
                raw_response TEXT, run_at TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_coded_mentions (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                mentioned BOOLEAN, deal_cited BOOLEAN, deal_types TEXT, member_value_cited BOOLEAN,
                strength TEXT, evidence TEXT, position INTEGER
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_price_observations (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                stated_price FLOAT, claimed_net_price FLOAT, member_price_claimed BOOLEAN,
                merchant_name TEXT, merchant_slug TEXT, attribution_status TEXT
            )
        """)
        conn.exec_driver_sql("CREATE TABLE soa_pass2_coding_log (id INTEGER PRIMARY KEY, run_id INTEGER, coding_pass_version INTEGER)")
        conn.exec_driver_sql("""
            CREATE TABLE soa_incentive_scores (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER, price_observation_id INTEGER,
                scoring_grain TEXT, status TEXT, measurement_status TEXT,
                stated_price FLOAT, ground_truth_true_cost FLOAT,
                ground_truth_applied_deals TEXT, ground_truth_available_deals TEXT,
                net_price_accuracy BOOLEAN
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_requests (
                id INTEGER PRIMARY KEY, token TEXT UNIQUE, email TEXT, status TEXT, cycle_id INTEGER,
                competitor_names TEXT, competitor_source TEXT, created_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycle_shares (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, token TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, created_by TEXT,
                revoked_at TIMESTAMP, expires_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_public_share_views (
                id INTEGER PRIMARY KEY, share_id INTEGER, ip_hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    monkeypatch.setattr(full_analysis_router, "engine", engine)
    monkeypatch.setattr(public_full_analysis_router, "engine", engine)
    return engine


# ─── Token scheme ───────────────────────────────────────────────────────────

def test_generate_public_token_matches_lite_scheme():
    """Same scheme soa_lite_requests.token already used inline
    (uuid.uuid4().hex): 32 lowercase hex chars, a valid uuid4, and never
    the same value twice."""
    token = generate_public_token()
    assert len(token) == 32
    assert token == token.lower()
    assert all(c in "0123456789abcdef" for c in token)
    parsed = uuid.UUID(token)
    assert parsed.version == 4
    assert generate_public_token() != token


# ─── Owner endpoints ────────────────────────────────────────────────────────

def test_create_share_link_then_get_returns_the_same_token(patched_engine):
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn)

    created = full_analysis_router.create_share_link("fc-1", current_user=CURRENT_USER)
    fetched = full_analysis_router.get_share_link("fc-1", current_user=CURRENT_USER)

    assert fetched.token == created.token


def test_get_share_link_is_none_before_any_link_is_created(patched_engine):
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn)

    assert full_analysis_router.get_share_link("fc-1", current_user=CURRENT_USER) is None


def test_create_share_link_is_idempotent_never_mints_a_second_live_token(patched_engine):
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn)

    first = full_analysis_router.create_share_link("fc-1", current_user=CURRENT_USER)
    second = full_analysis_router.create_share_link("fc-1", current_user=CURRENT_USER)

    assert first.token == second.token


def test_revoke_is_permanent_and_a_fresh_share_gets_a_new_token(patched_engine):
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn)

    first = full_analysis_router.create_share_link("fc-1", current_user=CURRENT_USER)
    full_analysis_router.revoke_share_link("fc-1", current_user=CURRENT_USER)

    assert full_analysis_router.get_share_link("fc-1", current_user=CURRENT_USER) is None

    second = full_analysis_router.create_share_link("fc-1", current_user=CURRENT_USER)
    assert second.token != first.token


def test_revoke_with_nothing_active_is_a_no_op_not_an_error(patched_engine):
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn)

    response = full_analysis_router.revoke_share_link("fc-1", current_user=CURRENT_USER)
    assert response == {"revoked": True}


def test_owner_endpoints_are_org_scoped(patched_engine):
    """Another org's user gets the same 404 shape as an unknown
    cycle_code — never a 403 that would confirm the cycle_code exists at
    all, matching get_full_analysis_report's own guarantee."""
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn)
    full_analysis_router.create_share_link("fc-1", current_user=CURRENT_USER)

    with pytest.raises(HTTPException) as get_exc:
        full_analysis_router.get_share_link("fc-1", current_user=OTHER_ORG_USER)
    assert get_exc.value.status_code == 404

    with pytest.raises(HTTPException) as create_exc:
        full_analysis_router.create_share_link("fc-1", current_user=OTHER_ORG_USER)
    assert create_exc.value.status_code == 404

    with pytest.raises(HTTPException) as revoke_exc:
        full_analysis_router.revoke_share_link("fc-1", current_user=OTHER_ORG_USER)
    assert revoke_exc.value.status_code == 404

    # And the original owner's link must still be untouched by the
    # other org's failed revoke attempt.
    assert full_analysis_router.get_share_link("fc-1", current_user=CURRENT_USER) is not None


# ─── Public read endpoint ───────────────────────────────────────────────────

def test_public_read_renders_the_same_report_the_owner_sees(patched_engine):
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn)
    share = full_analysis_router.create_share_link("fc-1", current_user=CURRENT_USER)

    owner_view = full_analysis_router.get_full_analysis_report("fc-1", current_user=CURRENT_USER)
    public_view = public_full_analysis_router.get_public_full_analysis_report(share.token, _FakeRequest())

    assert public_view.rendered is True
    assert public_view.composite == owner_view.composite
    assert public_view.verdict == owner_view.verdict
    assert public_view.pillars == owner_view.pillars
    assert public_view.competitor_set == owner_view.competitor_set


def test_token_scoped_to_only_its_own_cycle(patched_engine):
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn, cycle_code="fc-a", cycle_id=10)
        _seed_scored_cycle(conn, cycle_code="fc-b", cycle_id=20)
        conn.exec_driver_sql(
            "UPDATE soa_entities SET name = 'Cycle B Brand' WHERE id = 201",
        )

    share_a = full_analysis_router.create_share_link("fc-a", current_user=CURRENT_USER)
    share_b = full_analysis_router.create_share_link("fc-b", current_user=CURRENT_USER)
    assert share_a.token != share_b.token

    report_a = public_full_analysis_router.get_public_full_analysis_report(share_a.token, _FakeRequest())
    report_b = public_full_analysis_router.get_public_full_analysis_report(share_b.token, _FakeRequest())

    assert report_a.cycle_code == "fc-a"
    assert report_b.cycle_code == "fc-b"
    assert report_a.competitor_set["overall"][0]["entity"] == "Full Cycle Brand"
    assert report_b.competitor_set["overall"][0]["entity"] == "Cycle B Brand"


def test_unknown_token_404s(patched_engine):
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn)

    with pytest.raises(HTTPException) as exc_info:
        public_full_analysis_router.get_public_full_analysis_report("no-such-token", _FakeRequest())
    assert exc_info.value.status_code == 404


def test_revoked_token_404s(patched_engine):
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn)
    share = full_analysis_router.create_share_link("fc-1", current_user=CURRENT_USER)
    full_analysis_router.revoke_share_link("fc-1", current_user=CURRENT_USER)

    with pytest.raises(HTTPException) as exc_info:
        public_full_analysis_router.get_public_full_analysis_report(share.token, _FakeRequest())
    assert exc_info.value.status_code == 404


def test_expired_token_404s(patched_engine):
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn)
    share = full_analysis_router.create_share_link("fc-1", current_user=CURRENT_USER)
    with patched_engine.begin() as conn:
        conn.execute(text(
            "UPDATE soa_cycle_shares SET expires_at = :expiry WHERE token = :token"
        ), {"expiry": datetime.now(timezone.utc) - timedelta(days=1), "token": share.token})

    with pytest.raises(HTTPException) as exc_info:
        public_full_analysis_router.get_public_full_analysis_report(share.token, _FakeRequest())
    assert exc_info.value.status_code == 404


def test_unexpired_token_still_renders(patched_engine):
    """The boundary case next to the expiry test above — a future
    expires_at must not itself 404 the link."""
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn)
    share = full_analysis_router.create_share_link("fc-1", current_user=CURRENT_USER)
    with patched_engine.begin() as conn:
        conn.execute(text(
            "UPDATE soa_cycle_shares SET expires_at = :expiry WHERE token = :token"
        ), {"expiry": datetime.now(timezone.utc) + timedelta(days=1), "token": share.token})

    report = public_full_analysis_router.get_public_full_analysis_report(share.token, _FakeRequest())
    assert report.rendered is True


def test_render_gate_applies_on_the_public_path_too(patched_engine):
    """A cycle with a live, unrevoked share token but no complete crawl
    (e.g. shared before the crawl finished, or the crawl was reset) must
    404 publicly — never a 200 with rendered=False, unlike the owner's
    own authenticated view which is allowed to show that state."""
    with patched_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_cycles (id, cycle_code, organization_id) VALUES (99, 'no-crawl', 1)"
        )
    share = full_analysis_router.create_share_link("no-crawl", current_user=CURRENT_USER)

    owner_view = full_analysis_router.get_full_analysis_report("no-crawl", current_user=CURRENT_USER)
    assert owner_view.rendered is False

    with pytest.raises(HTTPException) as exc_info:
        public_full_analysis_router.get_public_full_analysis_report(share.token, _FakeRequest())
    assert exc_info.value.status_code == 404


def test_public_read_rate_limited_per_ip(patched_engine):
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn)
    share = full_analysis_router.create_share_link("fc-1", current_user=CURRENT_USER)

    ip = "9.9.9.9"
    for _ in range(public_full_analysis_router.RATE_LIMIT_PER_IP_HOUR):
        public_full_analysis_router.get_public_full_analysis_report(share.token, _FakeRequest(ip))

    with pytest.raises(HTTPException) as exc_info:
        public_full_analysis_router.get_public_full_analysis_report(share.token, _FakeRequest(ip))
    assert exc_info.value.status_code == 429

    # A different IP is unaffected by the first one's limit.
    other = public_full_analysis_router.get_public_full_analysis_report(share.token, _FakeRequest("8.8.8.8"))
    assert other.rendered is True


def test_invalid_tokens_still_count_against_the_rate_limit(patched_engine):
    """share_id is nullable on soa_public_share_views specifically so an
    unresolvable token still gets logged — otherwise hammering the
    endpoint with garbage tokens would be exempt from the very limit
    meant to stop it."""
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn)

    ip = "5.5.5.5"
    for _ in range(public_full_analysis_router.RATE_LIMIT_PER_IP_HOUR):
        with pytest.raises(HTTPException) as exc_info:
            public_full_analysis_router.get_public_full_analysis_report("garbage", _FakeRequest(ip))
        assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        public_full_analysis_router.get_public_full_analysis_report("garbage", _FakeRequest(ip))
    assert exc_info.value.status_code == 429


# ─── Public payload denylist ────────────────────────────────────────────────

_DENYLISTED_KEYS = {
    "organization_id", "org_id", "created_by", "user_id", "email",
    "ip_hash", "password", "api_key", "access_token", "billing",
}


def _find_denylisted_keys(value, path=""):
    hits = []
    if isinstance(value, dict):
        for k, v in value.items():
            key_path = f"{path}.{k}" if path else k
            if k in _DENYLISTED_KEYS:
                hits.append(key_path)
            hits.extend(_find_denylisted_keys(v, key_path))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            hits.extend(_find_denylisted_keys(item, f"{path}[{i}]"))
    return hits


def test_public_payload_never_carries_a_denylisted_key(patched_engine):
    with patched_engine.begin() as conn:
        _seed_scored_cycle(conn)
    share = full_analysis_router.create_share_link("fc-1", current_user=CURRENT_USER)

    report = public_full_analysis_router.get_public_full_analysis_report(share.token, _FakeRequest())

    hits = _find_denylisted_keys(report.model_dump())
    assert hits == [], f"public payload leaked denylisted key(s): {hits}"
