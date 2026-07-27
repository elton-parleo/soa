"""
email_sender.py — Stage 12 (E3) email delivery for the SoA Lite
"report ready" notification.

EmailSender is a small abstraction with exactly two implementations,
chosen by environment presence rather than a config flag, so a missing
RESEND_API_KEY fails safe to logging instead of silently not sending:
  ResendSender — RESEND_API_KEY + EMAIL_FROM set: sends via Resend's
    plain HTTP API (httpx directly, already a dependency — no SDK, no
    new paid dependency, rule 8).
  LogSender — the default/dev fallback: logs what WOULD have been sent
    instead of sending anything.

Both implementations never raise — send_report_ready() returns True/
False so the caller (worker.py::_sweep_lite_completions) can log a
failure and simply retry on the next sweep pass, never propagate.

No templates engine — one hardcoded, plain HTML+text email. The link is
the entire payload: no score numbers anywhere in the body (Stage 9 U4 —
link unfurls must stay score-free), one call to action, one line noting
the link is private.
"""
import logging
import os
from abc import ABC, abstractmethod

import httpx

log = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
SEND_TIMEOUT_SECONDS = 10.0


def mask_email(email: str) -> str:
    """Stage 12 (E4): 'a***@company.com' — never the real address in a
    log line. Never raises on malformed input."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    masked_local = f"{local[0]}***" if local else "***"
    return f"{masked_local}@{domain}"


def _email_subject(brand_name: str) -> str:
    return f"Your {brand_name} visibility report is ready"


def _email_text(report_url: str, brand_name: str) -> str:
    return (
        f"Your {brand_name} visibility report is ready.\n\n"
        "See how AI shopping agents read and price your store:\n"
        f"{report_url}\n\n"
        "This link is private until you share it."
    )


def _email_html(report_url: str, brand_name: str) -> str:
    return f"""\
<!DOCTYPE html>
<html>
  <body style="font-family: -apple-system, Helvetica, Arial, sans-serif; color: #12161F; max-width: 480px; margin: 0 auto; padding: 32px 20px;">
    <p style="font-size: 16px; line-height: 1.5; margin: 0 0 12px;">Your {brand_name} visibility report is ready.</p>
    <p style="font-size: 15px; line-height: 1.6; color: #4A4F5C; margin: 0 0 24px;">
      See how AI shopping agents read and price your store.
    </p>
    <p style="margin: 0 0 28px;">
      <a href="{report_url}" style="background: #3D5AFE; color: #ffffff; padding: 12px 24px; border-radius: 24px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
        View your report
      </a>
    </p>
    <p style="font-size: 12px; color: #8B90A0; margin: 0;">This link is private until you share it.</p>
  </body>
</html>"""


class EmailSender(ABC):
    @abstractmethod
    def send_report_ready(self, to: str, report_url: str, brand_name: str) -> bool:
        """Returns True once the email was (or, for LogSender, would be)
        successfully handed off. Never raises — a failure to send
        returns False so the caller can retry on the next sweep pass."""
        raise NotImplementedError


class LogSender(EmailSender):
    """Dev/default fallback — logs what would have been sent instead of
    actually sending anything. Never fails."""

    def send_report_ready(self, to: str, report_url: str, brand_name: str) -> bool:
        log.info(
            "[email:log] would send %r to %s -> %s",
            _email_subject(brand_name), mask_email(to), report_url,
        )
        return True


class ResendSender(EmailSender):
    def __init__(self, api_key: str, from_address: str):
        self.api_key = api_key
        self.from_address = from_address

    def send_report_ready(self, to: str, report_url: str, brand_name: str) -> bool:
        try:
            resp = httpx.post(
                RESEND_API_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "from": self.from_address,
                    "to": [to],
                    "subject": _email_subject(brand_name),
                    "html": _email_html(report_url, brand_name),
                    "text": _email_text(report_url, brand_name),
                },
                timeout=SEND_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            log.info("[email:resend] sent report-ready email to %s", mask_email(to))
            return True
        except Exception:
            log.exception("[email:resend] failed to send report-ready email to %s", mask_email(to))
            return False


def get_email_sender() -> EmailSender:
    """
    Provider choice by env presence: RESEND_API_KEY + EMAIL_FROM both
    set means Resend; anything else (local dev, or a misconfiguration
    missing one of the two) falls back to LogSender so nothing crashes
    and every attempt is still visible in logs.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    from_address = os.environ.get("EMAIL_FROM")
    if api_key and from_address:
        return ResendSender(api_key=api_key, from_address=from_address)
    if api_key and not from_address:
        log.warning("[email] RESEND_API_KEY set but EMAIL_FROM missing — falling back to LogSender")
    return LogSender()
