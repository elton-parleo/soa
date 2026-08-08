"""
Tests for email_sender.py — Stage 12 (E3) report-ready email delivery.

Covers mask_email edge cases, provider selection by env presence
(get_email_sender), that ResendSender never raises even when the HTTP
call fails (worker.py::_sweep_lite_completions relies on
send_report_ready always returning a bool, never propagating), and the
audit-rename/branding/reply-to redesign session: subject and body
wording, the email-safe HTML template's shape (no <img>, no external
fonts, no CSS classes), the preheader, and EMAIL_REPLY_TO wiring.
"""
import re

import httpx
import pytest

from email_sender import (
    LogSender,
    ResendSender,
    _email_html,
    _email_subject,
    _email_text,
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
    monkeypatch.delenv("EMAIL_REPLY_TO", raising=False)

    sender = get_email_sender()
    assert isinstance(sender, ResendSender)
    assert sender.api_key == "key123"
    assert sender.from_address == "reports@parleo.io"
    assert sender.reply_to is None


def test_get_email_sender_reads_reply_to_when_set(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "key123")
    monkeypatch.setenv("EMAIL_FROM", "reports@parleo.io")
    monkeypatch.setenv("EMAIL_REPLY_TO", "leads@parleo.io")

    sender = get_email_sender()
    assert sender.reply_to == "leads@parleo.io"


def test_get_email_sender_logs_reply_to_mode_without_the_address(monkeypatch, caplog):
    monkeypatch.setenv("RESEND_API_KEY", "key123")
    monkeypatch.setenv("EMAIL_FROM", "reports@parleo.io")
    monkeypatch.setenv("EMAIL_REPLY_TO", "leads@parleo.io")

    with caplog.at_level("INFO"):
        get_email_sender()

    assert "leads@parleo.io" not in caplog.text
    assert "configured" in caplog.text


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
        status_code = 403
        text = "forbidden: domain not verified"

        def raise_for_status(self):
            raise httpx.HTTPStatusError("bad request", request=None, response=None)

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse())

    sender = ResendSender(api_key="key123", from_address="reports@parleo.io")
    result = sender.send_report_ready("visitor@example.com", "https://parleo.io/report/tok", "Acme")

    assert result is False


def test_resend_sender_logs_status_and_body_on_non_2xx_response(monkeypatch, caplog):
    class _FakeResponse:
        status_code = 403
        text = "forbidden: domain not verified"

        def raise_for_status(self):
            raise httpx.HTTPStatusError("bad request", request=None, response=None)

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse())

    sender = ResendSender(api_key="key123", from_address="reports@parleo.io")
    with caplog.at_level("ERROR"):
        sender.send_report_ready("visitor@example.com", "https://parleo.io/report/tok", "Acme")

    assert "403" in caplog.text
    assert "forbidden: domain not verified" in caplog.text


def test_resend_sender_never_raises_when_fake_response_lacks_status_or_text(monkeypatch):
    """The error-logging path must stay defensive: a response object
    that never got as far as a real Resend response (e.g. a transport
    stub in a test, or a future httpx change) must not turn a send
    failure into an unhandled AttributeError."""
    class _BareFakeResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError("bad request", request=None, response=None)

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _BareFakeResponse())

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
    assert "reply_to" not in captured["json"]


def test_resend_sender_passes_reply_to_when_set(monkeypatch):
    class _FakeResponse:
        def raise_for_status(self):
            pass

    captured = {}

    def _fake_post(url, headers, json, timeout):
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", _fake_post)

    sender = ResendSender(api_key="key123", from_address="reports@parleo.io", reply_to="leads@parleo.io")
    sender.send_report_ready("visitor@example.com", "https://parleo.io/report/tok", "Acme")

    assert captured["json"]["reply_to"] == "leads@parleo.io"


def test_resend_sender_omits_reply_to_when_unset(monkeypatch):
    class _FakeResponse:
        def raise_for_status(self):
            pass

    captured = {}

    def _fake_post(url, headers, json, timeout):
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", _fake_post)

    sender = ResendSender(api_key="key123", from_address="reports@parleo.io")
    sender.send_report_ready("visitor@example.com", "https://parleo.io/report/tok", "Acme")

    assert "reply_to" not in captured["json"]


# ── Redesign session: audit wording, branding, email-safe HTML ───────────

REPORT_URL = "https://parleo.io/report/abc123token"
BRAND = "Acme"


def test_subject_and_body_use_agentic_value_audit_wording():
    subject = _email_subject(BRAND)
    text = _email_text(REPORT_URL, BRAND)
    html = _email_html(REPORT_URL, BRAND)

    assert "agentic value audit" in subject.lower()
    assert "agentic value audit" in text.lower() or "agentic value audit" in html.lower()


def test_visibility_report_wording_never_appears_in_the_module():
    import email_sender

    src = open(email_sender.__file__).read()
    assert "visibility report" not in src.lower()


def test_preheader_present_and_hidden():
    from email_sender import PREHEADER_TEXT

    assert len(PREHEADER_TEXT) < 90

    html = _email_html(REPORT_URL, BRAND)
    # The preheader text appears once, inside a span carrying the
    # standard email-client hidden-preheader styling.
    preheader_pos = html.index(PREHEADER_TEXT)
    preceding_tag = html[:preheader_pos].rsplit("<span", 1)[-1]
    assert "display: none" in preceding_tag
    assert PREHEADER_TEXT not in _email_text(REPORT_URL, BRAND)


def test_button_href_and_plain_url_line_match_report_url():
    html = _email_html(REPORT_URL, BRAND)

    match = re.search(r'<a href="([^"]+)"[^>]*>View your report</a>', html)
    assert match is not None
    assert match.group(1) == REPORT_URL

    # The full URL is also printed as plain text beneath the button, for
    # clients that strip buttons/anchors entirely.
    assert html.count(REPORT_URL) >= 2


def test_html_has_no_img_tags():
    html = _email_html(REPORT_URL, BRAND)
    assert "<img" not in html.lower()


def test_html_has_no_external_font_references():
    html = _email_html(REPORT_URL, BRAND)
    assert "fonts.googleapis" not in html
    assert "fonts.gstatic" not in html
    assert "@import" not in html
    assert "Inter" not in html
    assert "Instrument Serif" not in html


def test_html_has_no_css_classes():
    html = _email_html(REPORT_URL, BRAND)
    assert 'class="' not in html
    assert "<style" not in html.lower()


def test_html_uses_system_font_stack_only():
    html = _email_html(REPORT_URL, BRAND)
    assert "-apple-system" in html
    assert "Segoe UI" in html


def test_wordmark_renders_as_text_not_image():
    html = _email_html(REPORT_URL, BRAND)
    assert "PARLEO" in html
    assert "<img" not in html.lower()
