"""
Tests for POST /api/public/soa-lite (app/routers/public_lite.py::submit_lite_request).
Calls the route function directly, same convention as test_create_cycle_truecost.py.
Real in-memory SQLite for organizations/soa_lite_requests; captcha verification
is mocked directly since it's an outbound HTTP call.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.routers.public_lite as public_lite
from app.schemas import PublicLiteSubmitRequest


class _FakeClient:
    def __init__(self, host):
        self.host = host


class FakeRequest:
    def __init__(self, headers=None, ip="203.0.113.5"):
        self.headers = headers or {}
        self.client = _FakeClient(ip)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE organizations (
                id INTEGER PRIMARY KEY, name TEXT UNIQUE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_lite_requests (
                id INTEGER PRIMARY KEY, token TEXT UNIQUE, email TEXT, brand_name TEXT,
                competitor_names TEXT, brand_entity_id INTEGER, competitor_entity_ids TEXT,
                study_type TEXT, store_url TEXT, cycle_id INTEGER, status TEXT DEFAULT 'pending',
                error_message TEXT, ip_hash TEXT, organization_id INTEGER,
                competitor_source TEXT, events TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP
            )
        """)
    monkeypatch.setattr(public_lite, "engine", engine)
    monkeypatch.setattr(public_lite, "session_factory", sessionmaker(bind=engine))
    return engine


def _submit_data(**overrides):
    data = dict(brand_name="Acme Co", competitor_names=["Rival Co"], captcha_token="tok")
    data.update(overrides)
    return PublicLiteSubmitRequest(**data)


def _insert_lite_row(conn, ip_hash, created_at, token=None):
    conn.exec_driver_sql(
        "INSERT INTO soa_lite_requests (token, brand_name, ip_hash, status, created_at) "
        "VALUES (?, 'Acme', ?, 'pending', ?)",
        (token or f"tok-{created_at}", ip_hash, created_at),
    )


# ─── captcha skipped when unset (dev mode) ──────────────────────────────

def test_submits_successfully_with_captcha_unset(db, monkeypatch):
    monkeypatch.setattr(public_lite, "CAPTCHA_SECRET", "")
    monkeypatch.setattr(public_lite, "CAPTCHA_VERIFY_URL", "")

    result = public_lite.submit_lite_request(_submit_data(), FakeRequest())

    assert result.status == "pending"
    assert len(result.token) == 32  # uuid4().hex


# ─── captcha verification ────────────────────────────────────────────────

def test_rejects_when_captcha_verification_fails(db, monkeypatch):
    monkeypatch.setattr(public_lite, "CAPTCHA_SECRET", "secret")
    monkeypatch.setattr(public_lite, "CAPTCHA_VERIFY_URL", "https://captcha.example/verify")

    with patch.object(public_lite, "_verify_captcha", return_value=False):
        with pytest.raises(HTTPException) as exc_info:
            public_lite.submit_lite_request(_submit_data(), FakeRequest())

    assert exc_info.value.status_code == 400


def test_accepts_when_captcha_verification_succeeds(db, monkeypatch):
    monkeypatch.setattr(public_lite, "CAPTCHA_SECRET", "secret")
    monkeypatch.setattr(public_lite, "CAPTCHA_VERIFY_URL", "https://captcha.example/verify")

    with patch.object(public_lite, "_verify_captcha", return_value=True):
        result = public_lite.submit_lite_request(_submit_data(), FakeRequest())

    assert result.status == "pending"


# ─── successful submission persists correctly ───────────────────────────

def test_persists_brand_and_competitors_and_org(db):
    result = public_lite.submit_lite_request(
        _submit_data(brand_name="Acme Co", competitor_names=["Rival Co"]),
        FakeRequest(ip="203.0.113.9"),
    )

    with db.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT brand_name, competitor_names, status, organization_id, ip_hash "
            "FROM soa_lite_requests WHERE token = ?",
            (result.token,),
        ).fetchone()
        org_name = conn.exec_driver_sql(
            "SELECT name FROM organizations WHERE id = ?", (row[3],)
        ).fetchone()[0]

    assert row[0] == "Acme Co"
    assert json.loads(row[1]) == ["Rival Co"]
    assert row[2] == "pending"
    assert org_name == "Parleo Lead Gen"
    assert row[4] is not None  # ip_hash stored, never the raw IP


def test_store_url_persisted_when_given(db):
    result = public_lite.submit_lite_request(
        _submit_data(store_url="acme.com"), FakeRequest(ip="203.0.113.9"),
    )
    with db.connect() as conn:
        stored = conn.exec_driver_sql(
            "SELECT store_url FROM soa_lite_requests WHERE token = ?", (result.token,)
        ).fetchone()[0]
    assert stored == "https://acme.com"


def test_store_url_null_when_omitted(db):
    result = public_lite.submit_lite_request(_submit_data(), FakeRequest(ip="203.0.113.10"))
    with db.connect() as conn:
        stored = conn.exec_driver_sql(
            "SELECT store_url FROM soa_lite_requests WHERE token = ?", (result.token,)
        ).fetchone()[0]
    assert stored is None


def test_reuses_leadgen_org_across_submissions(db):
    public_lite.submit_lite_request(_submit_data(), FakeRequest(ip="203.0.113.1"))
    public_lite.submit_lite_request(
        _submit_data(brand_name="Other Brand"), FakeRequest(ip="203.0.113.2"),
    )

    with db.connect() as conn:
        count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM organizations WHERE name = 'Parleo Lead Gen'"
        ).fetchone()[0]
    assert count == 1


def test_x_forwarded_for_used_when_present(db):
    result = public_lite.submit_lite_request(
        _submit_data(),
        FakeRequest(headers={"x-forwarded-for": "198.51.100.7, 10.0.0.1"}, ip="10.0.0.1"),
    )
    with db.connect() as conn:
        ip_hash = conn.exec_driver_sql(
            "SELECT ip_hash FROM soa_lite_requests WHERE token = ?", (result.token,)
        ).fetchone()[0]
    assert ip_hash == public_lite._hash_ip("198.51.100.7")


# ─── rate limiting ───────────────────────────────────────────────────────

def test_per_ip_hourly_limit_enforced(db):
    ip_hash = public_lite._hash_ip("203.0.113.42")
    now = datetime.now(timezone.utc)
    with db.begin() as conn:
        for i in range(3):
            _insert_lite_row(conn, ip_hash, now - timedelta(minutes=i))

    with pytest.raises(HTTPException) as exc_info:
        public_lite.submit_lite_request(_submit_data(), FakeRequest(ip="203.0.113.42"))

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"] == "3600"


def test_per_ip_hourly_limit_ignores_requests_older_than_an_hour(db):
    ip_hash = public_lite._hash_ip("203.0.113.42")
    now = datetime.now(timezone.utc)
    with db.begin() as conn:
        for i in range(3):
            _insert_lite_row(conn, ip_hash, now - timedelta(hours=2, minutes=i))

    result = public_lite.submit_lite_request(_submit_data(), FakeRequest(ip="203.0.113.42"))
    assert result.status == "pending"


def test_per_ip_daily_limit_enforced_across_the_hourly_window(db):
    ip_hash = public_lite._hash_ip("203.0.113.42")
    now = datetime.now(timezone.utc)
    # RATE_LIMIT_PER_IP_DAY requests spread across the day (outside the
    # 1-hour window, inside the 1-day window).
    with db.begin() as conn:
        for i in range(public_lite.RATE_LIMIT_PER_IP_DAY):
            _insert_lite_row(conn, ip_hash, now - timedelta(hours=2 + i))

    with pytest.raises(HTTPException) as exc_info:
        public_lite.submit_lite_request(_submit_data(), FakeRequest(ip="203.0.113.42"))

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"] == "86400"


def test_global_hourly_cap_enforced_across_different_ips(db):
    now = datetime.now(timezone.utc)
    with db.begin() as conn:
        for i in range(20):
            _insert_lite_row(
                conn, public_lite._hash_ip(f"10.0.0.{i}"), now - timedelta(minutes=1),
                token=f"tok-global-{i}",
            )

    with pytest.raises(HTTPException) as exc_info:
        public_lite.submit_lite_request(_submit_data(), FakeRequest(ip="203.0.113.200"))

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"] == "3600"


def test_under_all_limits_succeeds(db):
    ip_hash = public_lite._hash_ip("203.0.113.42")
    now = datetime.now(timezone.utc)
    with db.begin() as conn:
        for i in range(2):  # under the 3/hour cap
            _insert_lite_row(conn, ip_hash, now - timedelta(minutes=i))

    result = public_lite.submit_lite_request(_submit_data(), FakeRequest(ip="203.0.113.42"))
    assert result.status == "pending"
