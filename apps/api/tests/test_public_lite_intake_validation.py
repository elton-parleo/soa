"""
Intake validation: a store URL that cannot be a storefront is rejected
before it costs anything.

Two audits in the 30-day review — a bit.ly link and a synthetic .example
domain — were accepted, queued, ran 24 LLM queries each, and then failed
at the crawl. The queries were real spend on a store that does not exist.

These tests hold the three rejections and, just as importantly, the
allow: a DNS lookup that TIMES OUT must never block a real store, because
a slow resolver on our side is our problem and not something a visitor
can do anything about.

Same harness as test_public_lite_submit.py — the route function called
directly against in-memory SQLite, captcha mocked. socket.getaddrinfo is
always patched here: nothing in this file may make a real DNS query.
"""
import socket
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

import app.routers.public_lite as public_lite
from app.schemas import PublicLiteSubmitRequest


class _FakeClient:
    def __init__(self, host):
        self.host = host


class FakeRequest:
    def __init__(self, ip="203.0.113.5"):
        self.headers = {}
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
    monkeypatch.setattr(public_lite, "CAPTCHA_SECRET", "")
    monkeypatch.setattr(public_lite, "CAPTCHA_VERIFY_URL", "")
    return engine


@pytest.fixture(autouse=True)
def _no_emails_and_no_real_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    monkeypatch.delenv(public_lite.ALLOW_TEST_DOMAINS_ENV, raising=False)
    with patch.object(public_lite, "send_audit_started_notification", return_value=False):
        yield


def _submit(store_url=None, **overrides):
    data = dict(brand_name="Acme Co", competitor_names=["Rival Co"], captcha_token="tok")
    if store_url is not None:
        data["store_url"] = store_url
    data.update(overrides)
    return PublicLiteSubmitRequest(**data)


def _row_count(db):
    with db.connect() as conn:
        return conn.exec_driver_sql("SELECT COUNT(*) FROM soa_lite_requests").scalar()


# ─── shorteners ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("host", sorted(public_lite.URL_SHORTENER_HOSTS))
def test_every_known_shortener_is_rejected(db, host):
    with pytest.raises(HTTPException) as exc:
        public_lite.submit_lite_request(_submit(f"https://{host}/abc123"), FakeRequest())

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == public_lite.REJECT_CODE_SHORTENER
    assert exc.value.detail["message"]
    assert _row_count(db) == 0


def test_a_shortener_named_inside_a_real_domain_is_not_rejected(db):
    """Host equality, never a substring test — bitly-shoes.com is a
    store, not a shortener."""
    result = public_lite.submit_lite_request(_submit("https://bitly-shoes.com"), FakeRequest())
    assert result.status == "pending"


# ─── reserved TLDs ───────────────────────────────────────────────────────

@pytest.mark.parametrize("host", ["store.example", "shop.invalid", "thing.test", "box.localhost"])
def test_reserved_tlds_are_rejected(db, host):
    with pytest.raises(HTTPException) as exc:
        public_lite.submit_lite_request(_submit(f"https://{host}"), FakeRequest())

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == public_lite.REJECT_CODE_RESERVED_TLD
    assert _row_count(db) == 0


def test_allow_test_domains_lets_a_reserved_tld_through(db, monkeypatch):
    """The tracking test in the export used a .example domain on
    purpose — the flag is what keeps that possible without reopening
    the door for everyone."""
    monkeypatch.setenv(public_lite.ALLOW_TEST_DOMAINS_ENV, "1")

    result = public_lite.submit_lite_request(_submit("https://store.example"), FakeRequest())

    assert result.status == "pending"
    assert _row_count(db) == 1


# ─── DNS ─────────────────────────────────────────────────────────────────

def test_a_host_that_does_not_resolve_is_rejected(db, monkeypatch):
    def _nxdomain(*a, **k):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", _nxdomain)

    with pytest.raises(HTTPException) as exc:
        public_lite.submit_lite_request(_submit("https://not-a-real-store-xyz.com"), FakeRequest())

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == public_lite.REJECT_CODE_UNRESOLVABLE
    assert _row_count(db) == 0


def test_a_dns_timeout_allows_the_submission(db, monkeypatch):
    """A slow resolver on our side is our problem. Rejecting here would
    block real stores during exactly the moments we are least able to
    tell a real store from a fake one."""
    def _timeout(*a, **k):
        raise socket.timeout("timed out")

    monkeypatch.setattr(socket, "getaddrinfo", _timeout)

    result = public_lite.submit_lite_request(_submit("https://allbirds.com"), FakeRequest())

    assert result.status == "pending"
    assert _row_count(db) == 1


def test_any_other_resolver_failure_also_allows(db, monkeypatch):
    def _boom(*a, **k):
        raise OSError("resolver exploded")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)

    result = public_lite.submit_lite_request(_submit("https://allbirds.com"), FakeRequest())
    assert result.status == "pending"


def test_the_dns_lookup_is_bounded(db, monkeypatch):
    """The POST must stay fast — a resolver that hangs cannot hold the
    request open indefinitely."""
    seen = []
    real_setdefaulttimeout = socket.setdefaulttimeout
    monkeypatch.setattr(socket, "setdefaulttimeout", lambda t: (seen.append(t), real_setdefaulttimeout(t))[1])

    public_lite.submit_lite_request(_submit("https://allbirds.com"), FakeRequest())

    assert public_lite.DNS_RESOLVE_TIMEOUT_SECONDS in seen
    assert public_lite.DNS_RESOLVE_TIMEOUT_SECONDS <= 2.0


# ─── the ordinary path is untouched ──────────────────────────────────────

def test_a_real_store_url_still_submits(db):
    result = public_lite.submit_lite_request(_submit("https://allbirds.com"), FakeRequest())
    assert result.status == "pending"
    assert _row_count(db) == 1


def test_no_store_url_at_all_is_still_accepted(db, monkeypatch):
    """An audit with no crawl is an existing, supported shape — these
    checks must not turn it into a rejection."""
    called = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: called.append(a) or [])

    result = public_lite.submit_lite_request(_submit(), FakeRequest())

    assert result.status == "pending"
    assert called == []  # no lookup for a submission with nothing to look up


def test_validation_runs_after_the_rate_limit(db, monkeypatch):
    """Ordering matters: a caller who trips the rate limit must never
    reach a DNS lookup, or the limit stops limiting what it costs us."""
    looked_up = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: looked_up.append(a) or [])

    def _limited(*a, **k):
        raise HTTPException(status_code=429, detail="slow down")

    monkeypatch.setattr(public_lite, "_enforce_rate_limits", _limited)

    with pytest.raises(HTTPException) as exc:
        public_lite.submit_lite_request(_submit("https://allbirds.com"), FakeRequest())

    assert exc.value.status_code == 429
    assert looked_up == []
