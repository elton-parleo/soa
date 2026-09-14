"""
Tests for app/services/lead_notification_email.py — the API-side Resend
sender for the internal "new lead" notification, fired when a visitor
attaches their email to an audit run. Mirrors
test_demo_request_email.py: same never-raises / masked-logging contract,
verified independently because apps/api cannot import apps/pipeline's
email_sender.py (see that module's own docstring).
"""
import httpx
import pytest

from app.services import lead_notification_email as lne


FIELDS = {
    "brand_name": "Allbirds",
    "email": "visitor@company.com",
    "competitors": ["Rothys", "Vessi"],
    "status": "running",
    "token": "tok123",
    "submitted_at": "2026-09-14 12:00:00",
}


@pytest.fixture(autouse=True)
def _pinned_audit_base(monkeypatch):
    """The report link is built from PUBLIC_AUDIT_BASE_URL — pin it so
    these assertions don't depend on the ambient environment."""
    monkeypatch.delenv("PUBLIC_AUDIT_BASE_URL", raising=False)


class _OkResponse:
    def raise_for_status(self):
        pass


def _capture_post(monkeypatch):
    captured = {}

    def _fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _OkResponse()

    monkeypatch.setattr(httpx, "post", _fake_post)
    return captured


def _configured(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "key123")
    monkeypatch.setenv("EMAIL_FROM", "reports@parleo.io")


# ─── mask_email ──────────────────────────────────────────────────────────

def test_mask_email_masks_local_part():
    assert lne.mask_email("visitor@example.com") == "v***@example.com"


@pytest.mark.parametrize("bad", ["", None, "not-an-email"])
def test_mask_email_never_raises_on_malformed_input(bad):
    assert lne.mask_email(bad) == "***"


# ─── never crashes ───────────────────────────────────────────────────────

def test_returns_false_and_logs_when_env_not_configured(monkeypatch, caplog):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)

    with caplog.at_level("WARNING"):
        result = lne.send_lead_notification(FIELDS)

    assert result is False
    assert "visitor@company.com" not in caplog.text
    assert "v***@company.com" in caplog.text


def test_never_raises_on_http_error(monkeypatch):
    _configured(monkeypatch)

    def _boom(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _boom)

    assert lne.send_lead_notification(FIELDS) is False


def test_logs_status_and_body_on_non_2xx(monkeypatch, caplog):
    _configured(monkeypatch)

    class _FakeResponse:
        status_code = 403
        text = "forbidden: domain not verified"

        def raise_for_status(self):
            raise httpx.HTTPStatusError("bad request", request=None, response=None)

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse())

    with caplog.at_level("ERROR"):
        result = lne.send_lead_notification(FIELDS)

    assert result is False
    assert "403" in caplog.text
    assert "forbidden: domain not verified" in caplog.text
    assert "visitor@company.com" not in caplog.text


def test_never_raises_when_fake_response_lacks_status_or_text(monkeypatch):
    _configured(monkeypatch)

    class _BareFakeResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError("bad request", request=None, response=None)

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _BareFakeResponse())

    assert lne.send_lead_notification(FIELDS) is False


# ─── payload ─────────────────────────────────────────────────────────────

def test_success_sends_correct_recipient_subject_reply_to_and_fields(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setenv("LEAD_NOTIFY_EMAIL", "leads@parleo.io")
    captured = _capture_post(monkeypatch)

    result = lne.send_lead_notification(FIELDS)

    assert result is True
    payload = captured["json"]
    assert payload["from"] == "reports@parleo.io"
    assert payload["to"] == ["leads@parleo.io"]
    # reply_to is the visitor, so replying starts the conversation with them
    assert payload["reply_to"] == "visitor@company.com"
    assert payload["subject"] == "New audit lead — Allbirds"
    assert captured["headers"]["Authorization"] == "Bearer key123"
    for expected in [
        "Allbirds", "visitor@company.com", "Rothys, Vessi", "running",
        "tok123", "https://audit.parleo.io/r/tok123", "2026-09-14 12:00:00",
    ]:
        assert expected in payload["text"], expected
        assert expected in payload["html"], expected


def test_report_url_honours_public_audit_base_url(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setenv("PUBLIC_AUDIT_BASE_URL", "https://parleo.io/audit/")
    captured = _capture_post(monkeypatch)

    lne.send_lead_notification(FIELDS)

    assert "https://parleo.io/audit/r/tok123" in captured["json"]["text"]


@pytest.mark.parametrize("competitors", [None, []])
def test_competitors_render_as_none_when_absent(monkeypatch, competitors):
    _configured(monkeypatch)
    captured = _capture_post(monkeypatch)

    lne.send_lead_notification(dict(FIELDS, competitors=competitors))

    assert "Competitors: (none)" in captured["json"]["text"]
    assert "(none)" in captured["json"]["html"]


# ─── recipient fallback chain ────────────────────────────────────────────

def test_lead_notify_email_wins_over_demo_request_notify(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setenv("LEAD_NOTIFY_EMAIL", "leads@parleo.io")
    monkeypatch.setenv("DEMO_REQUEST_NOTIFY", "elton@parleo.io")
    captured = _capture_post(monkeypatch)

    lne.send_lead_notification(FIELDS)

    assert captured["json"]["to"] == ["leads@parleo.io"]


def test_falls_back_to_demo_request_notify(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.delenv("LEAD_NOTIFY_EMAIL", raising=False)
    monkeypatch.setenv("DEMO_REQUEST_NOTIFY", "elton@parleo.io")
    captured = _capture_post(monkeypatch)

    lne.send_lead_notification(FIELDS)

    assert captured["json"]["to"] == ["elton@parleo.io"]


def test_falls_back_to_default_address_when_neither_env_is_set(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.delenv("LEAD_NOTIFY_EMAIL", raising=False)
    monkeypatch.delenv("DEMO_REQUEST_NOTIFY", raising=False)
    captured = _capture_post(monkeypatch)

    lne.send_lead_notification(FIELDS)

    assert captured["json"]["to"] == [lne.DEFAULT_NOTIFY_ADDRESS]
    assert lne.DEFAULT_NOTIFY_ADDRESS == "leads@parleo.io"
