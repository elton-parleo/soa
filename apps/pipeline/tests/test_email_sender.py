"""
Tests for email_sender.py — Stage 12 (E3) report-ready email delivery.

Covers mask_email edge cases, provider selection by env presence
(get_email_sender), and that ResendSender never raises even when the
HTTP call fails (worker.py::_sweep_lite_completions relies on
send_report_ready always returning a bool, never propagating).
"""
import httpx
import pytest

from email_sender import (
    LogSender,
    ResendSender,
    get_email_sender,
    mask_email,
)


def test_mask_email_masks_local_part():
    assert mask_email("visitor@example.com") == "v***@example.com"


def test_mask_email_handles_empty_local_part():
    assert mask_email("@example.com") == "***@example.com"


@pytest.mark.parametrize("bad", ["", None, "not-an-email"])
def test_mask_email_never_raises_on_malformed_input(bad):
    assert mask_email(bad) == "***"


def test_get_email_sender_defaults_to_logsender_when_env_missing(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)

    assert isinstance(get_email_sender(), LogSender)


def test_get_email_sender_falls_back_when_only_api_key_set(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "key123")
    monkeypatch.delenv("EMAIL_FROM", raising=False)

    assert isinstance(get_email_sender(), LogSender)


def test_get_email_sender_returns_resend_when_both_env_vars_set(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "key123")
    monkeypatch.setenv("EMAIL_FROM", "reports@parleo.io")

    sender = get_email_sender()
    assert isinstance(sender, ResendSender)
    assert sender.api_key == "key123"
    assert sender.from_address == "reports@parleo.io"


def test_logsender_send_report_ready_always_returns_true():
    sender = LogSender()
    assert sender.send_report_ready("visitor@example.com", "https://parleo.io/report/tok", "Acme") is True


def test_resend_sender_returns_false_and_never_raises_on_http_error(monkeypatch):
    def _boom(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _boom)

    sender = ResendSender(api_key="key123", from_address="reports@parleo.io")
    result = sender.send_report_ready("visitor@example.com", "https://parleo.io/report/tok", "Acme")

    assert result is False


def test_resend_sender_returns_false_on_non_2xx_response(monkeypatch):
    class _FakeResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError("bad request", request=None, response=None)

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse())

    sender = ResendSender(api_key="key123", from_address="reports@parleo.io")
    result = sender.send_report_ready("visitor@example.com", "https://parleo.io/report/tok", "Acme")

    assert result is False


def test_resend_sender_returns_true_on_success(monkeypatch):
    class _FakeResponse:
        def raise_for_status(self):
            pass

    captured = {}

    def _fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", _fake_post)

    sender = ResendSender(api_key="key123", from_address="reports@parleo.io")
    result = sender.send_report_ready("visitor@example.com", "https://parleo.io/report/tok", "Acme")

    assert result is True
    assert captured["json"]["to"] == ["visitor@example.com"]
    assert captured["json"]["from"] == "reports@parleo.io"
    assert "tok" in captured["json"]["html"]
    assert "tok" in captured["json"]["text"]
    assert captured["headers"]["Authorization"] == "Bearer key123"
