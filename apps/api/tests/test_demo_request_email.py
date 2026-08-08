"""
Tests for app/services/demo_request_email.py — the leadgen session's
minimal, API-side Resend sender for the demo-request notification.
Same never-raises/masked-logging contract as apps/pipeline/
email_sender.py, verified independently since apps/api cannot import
that module (see this file's own module docstring).
"""
import httpx
import pytest

from app.services import demo_request_email as dre


FIELDS = {
    "name": "Jane Smith",
    "email": "jane@company.com",
    "company": "Acme Corp",
    "message": "Tell me about TrueSync",
    "source": "truesync",
    "page_url": "https://audit.parleo.io/r/tok123",
    "brand_name": "Allbirds",
    "report_token": "tok123",
    "report_url": "https://audit.parleo.io/r/tok123",
    "created_at": "2026-08-08 12:00:00",
}


def test_mask_email_masks_local_part():
    assert dre.mask_email("visitor@example.com") == "v***@example.com"


@pytest.mark.parametrize("bad", ["", None, "not-an-email"])
def test_mask_email_never_raises_on_malformed_input(bad):
    assert dre.mask_email(bad) == "***"


def test_returns_false_and_logs_when_env_not_configured(monkeypatch, caplog):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)

    with caplog.at_level("WARNING"):
        result = dre.send_demo_request_notification(FIELDS)

    assert result is False
    assert "jane@company.com" not in caplog.text


def test_never_raises_on_http_error(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "key123")
    monkeypatch.setenv("EMAIL_FROM", "reports@parleo.io")

    def _boom(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _boom)

    result = dre.send_demo_request_notification(FIELDS)
    assert result is False


def test_logs_status_and_body_on_non_2xx(monkeypatch, caplog):
    monkeypatch.setenv("RESEND_API_KEY", "key123")
    monkeypatch.setenv("EMAIL_FROM", "reports@parleo.io")

    class _FakeResponse:
        status_code = 403
        text = "forbidden: domain not verified"

        def raise_for_status(self):
            raise httpx.HTTPStatusError("bad request", request=None, response=None)

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse())

    with caplog.at_level("ERROR"):
        result = dre.send_demo_request_notification(FIELDS)

    assert result is False
    assert "403" in caplog.text
    assert "forbidden: domain not verified" in caplog.text


def test_never_raises_when_fake_response_lacks_status_or_text(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "key123")
    monkeypatch.setenv("EMAIL_FROM", "reports@parleo.io")

    class _BareFakeResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError("bad request", request=None, response=None)

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _BareFakeResponse())

    result = dre.send_demo_request_notification(FIELDS)
    assert result is False


def test_success_sends_correct_recipient_subject_reply_to_and_fields(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "key123")
    monkeypatch.setenv("EMAIL_FROM", "reports@parleo.io")
    monkeypatch.setenv("DEMO_REQUEST_NOTIFY", "elton@parleo.io")

    class _FakeResponse:
        def raise_for_status(self):
            pass

    captured = {}

    def _fake_post(url, headers, json, timeout):
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", _fake_post)

    result = dre.send_demo_request_notification(FIELDS)

    assert result is True
    payload = captured["json"]
    assert payload["to"] == ["elton@parleo.io"]
    assert payload["reply_to"] == "jane@company.com"
    assert payload["subject"] == "Demo request — Acme Corp (truesync)"
    for expected in ["Jane Smith", "jane@company.com", "Acme Corp", "truesync", "Tell me about TrueSync", "tok123", "Allbirds", "2026-08-08 12:00:00"]:
        assert expected in payload["text"]
        assert expected in payload["html"]


def test_defaults_recipient_to_elton_when_notify_env_unset(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "key123")
    monkeypatch.setenv("EMAIL_FROM", "reports@parleo.io")
    monkeypatch.delenv("DEMO_REQUEST_NOTIFY", raising=False)

    class _FakeResponse:
        def raise_for_status(self):
            pass

    captured = {}

    def _fake_post(url, headers, json, timeout):
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", _fake_post)

    dre.send_demo_request_notification(FIELDS)
    assert captured["json"]["to"] == ["elton@parleo.io"]


def test_report_link_omitted_when_no_report_token(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "key123")
    monkeypatch.setenv("EMAIL_FROM", "reports@parleo.io")

    class _FakeResponse:
        def raise_for_status(self):
            pass

    captured = {}

    def _fake_post(url, headers, json, timeout):
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", _fake_post)

    landing_fields = dict(FIELDS, page_url="https://audit.parleo.io/", brand_name=None, report_token=None, report_url=None, source="landing_truesync")
    dre.send_demo_request_notification(landing_fields)

    assert "Report:" not in captured["json"]["text"]
    assert "tok123" not in captured["json"]["html"]
