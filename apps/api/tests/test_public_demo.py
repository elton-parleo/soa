"""
Tests for POST /api/public/demo-request (app/routers/public_demo.py).
Calls the route function directly, same convention as
test_public_lite_submit.py — real in-memory SQLite for
soa_demo_requests, Resend send mocked directly (outbound HTTP).
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event

import app.routers.public_demo as public_demo
from app.schemas import PublicDemoRequestRequest


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
            CREATE TABLE soa_demo_requests (
                id INTEGER PRIMARY KEY, name TEXT, email TEXT, company TEXT, message TEXT,
                source TEXT, page_url TEXT, brand_name TEXT, report_token TEXT, ip_hash TEXT,
                notified_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    monkeypatch.setattr(public_demo, "engine", engine)
    return engine


def _data(**overrides):
    d = dict(name="Jane Smith", email="jane@company.com", company="Acme Corp", message="Tell me more", source="truesync", page_url="https://audit.parleo.io/")
    d.update(overrides)
    return PublicDemoRequestRequest(**d)


def _row(conn, email="jane@company.com"):
    return conn.exec_driver_sql(
        "SELECT name, email, company, message, source, page_url, brand_name, report_token, ip_hash, notified_at "
        "FROM soa_demo_requests WHERE email = ?",
        (email,),
    ).fetchone()


# ─── happy path ──────────────────────────────────────────────────────────

def test_happy_path_inserts_a_row_with_all_fields(db):
    with patch.object(public_demo, "send_demo_request_notification", return_value=True):
        result = public_demo.submit_demo_request(
            _data(brand_name="Allbirds", report_token="tok123"), FakeRequest(),
        )

    assert result.ok is True
    with db.connect() as conn:
        row = _row(conn)
    assert row[0] == "Jane Smith"
    assert row[1] == "jane@company.com"
    assert row[2] == "Acme Corp"
    assert row[3] == "Tell me more"
    assert row[4] == "truesync"
    assert row[5] == "https://audit.parleo.io/"
    assert row[6] == "Allbirds"
    assert row[7] == "tok123"
    assert row[8] is not None  # ip_hash stored, never the raw IP
    assert row[9] is not None  # notified_at stamped on successful send


def test_email_failure_still_returns_200_and_leaves_notified_at_null(db):
    with patch.object(public_demo, "send_demo_request_notification", return_value=False):
        result = public_demo.submit_demo_request(_data(), FakeRequest(ip="203.0.113.6"))

    assert result.ok is True
    with db.connect() as conn:
        row = _row(conn)
    assert row is not None  # the row is the backstop — it still exists
    assert row[9] is None


def test_email_called_with_recipient_subject_reply_to_and_all_fields(db):
    with patch.object(public_demo, "send_demo_request_notification", return_value=True) as mock_send:
        public_demo.submit_demo_request(
            _data(brand_name="Allbirds", report_token="tok123", message="Loyalty program details"),
            FakeRequest(),
        )

    assert mock_send.call_count == 1
    fields = mock_send.call_args[0][0]
    assert fields["name"] == "Jane Smith"
    assert fields["email"] == "jane@company.com"
    assert fields["company"] == "Acme Corp"
    assert fields["message"] == "Loyalty program details"
    assert fields["source"] == "truesync"
    assert fields["brand_name"] == "Allbirds"
    assert fields["report_token"] == "tok123"
    assert fields["report_url"] and "tok123" in fields["report_url"]
    assert fields["created_at"]


# ─── validation ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("field", ["name", "email", "company"])
def test_required_fields_422_when_missing(field):
    kwargs = {"name": "Jane Smith", "email": "jane@company.com", "company": "Acme Corp", "source": "truesync"}
    kwargs[field] = ""
    with pytest.raises(ValidationError):
        PublicDemoRequestRequest(**kwargs)


def test_email_shape_validated():
    with pytest.raises(ValidationError):
        PublicDemoRequestRequest(name="Jane", email="not-an-email", company="Acme", source="truesync")


def test_message_length_capped_at_2000():
    with pytest.raises(ValidationError):
        PublicDemoRequestRequest(name="Jane", email="jane@company.com", company="Acme", source="truesync", message="x" * 2001)


def test_name_length_capped_at_200():
    with pytest.raises(ValidationError):
        PublicDemoRequestRequest(name="x" * 201, email="jane@company.com", company="Acme", source="truesync")


def test_optional_fields_omitted_are_fine():
    req = PublicDemoRequestRequest(name="Jane", email="jane@company.com", company="Acme", source="truesync")
    assert req.message is None
    assert req.brand_name is None
    assert req.report_token is None


# ─── honeypot ────────────────────────────────────────────────────────────

def test_honeypot_tripped_stores_nothing_and_returns_success_shaped_200(db):
    with patch.object(public_demo, "send_demo_request_notification") as mock_send:
        result = public_demo.submit_demo_request(_data(website="http://spam.example"), FakeRequest())

    assert result.ok is True
    mock_send.assert_not_called()
    with db.connect() as conn:
        count = conn.exec_driver_sql("SELECT COUNT(*) FROM soa_demo_requests").fetchone()[0]
    assert count == 0


# ─── rate limit ──────────────────────────────────────────────────────────

def _insert_demo_row(conn, ip_hash, created_at):
    conn.exec_driver_sql(
        "INSERT INTO soa_demo_requests (name, email, company, source, ip_hash, created_at) "
        "VALUES ('Jane', 'jane@company.com', 'Acme', 'truesync', ?, ?)",
        (ip_hash, created_at),
    )


def test_rate_limit_fires_after_a_handful_per_minute(db):
    ip_hash = public_demo._hash_ip("203.0.113.7")
    now = datetime.now(timezone.utc)
    with db.begin() as conn:
        for _ in range(public_demo.RATE_LIMIT_PER_IP_MINUTE):
            _insert_demo_row(conn, ip_hash, str(now))

    with patch.object(public_demo, "send_demo_request_notification", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            public_demo.submit_demo_request(_data(), FakeRequest(ip="203.0.113.7"))

    assert exc_info.value.status_code == 429


def test_rate_limit_does_not_fire_for_a_different_ip(db):
    ip_hash = public_demo._hash_ip("203.0.113.7")
    now = datetime.now(timezone.utc)
    with db.begin() as conn:
        for _ in range(public_demo.RATE_LIMIT_PER_IP_MINUTE):
            _insert_demo_row(conn, ip_hash, str(now))

    with patch.object(public_demo, "send_demo_request_notification", return_value=True):
        result = public_demo.submit_demo_request(_data(), FakeRequest(ip="203.0.113.8"))

    assert result.ok is True


def test_rate_limit_ignores_requests_older_than_a_minute(db):
    ip_hash = public_demo._hash_ip("203.0.113.7")
    stale = datetime.now(timezone.utc) - timedelta(minutes=5)
    with db.begin() as conn:
        for _ in range(public_demo.RATE_LIMIT_PER_IP_MINUTE):
            _insert_demo_row(conn, ip_hash, str(stale))

    with patch.object(public_demo, "send_demo_request_notification", return_value=True):
        result = public_demo.submit_demo_request(_data(), FakeRequest(ip="203.0.113.7"))

    assert result.ok is True
