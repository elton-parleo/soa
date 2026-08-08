"""
email_sender.py — Stage 12 (E3) email delivery for the SoA Lite
"report ready" notification.

EmailSender is a small abstraction with exactly two implementations,
chosen by environment presence rather than a config flag, so a missing
RESEND_API_KEY fails safe to logging instead of silently not sending:
  ResendSender — RESEND_API_KEY + EMAIL_FROM set: sends via Resend's
    plain HTTP API (httpx directly, already a dependency — no SDK, no
    new paid dependency, rule 8). EMAIL_REPLY_TO, if set, is passed
    through to Resend's reply_to field so a prospect replying to their
    audit email reaches a monitored inbox instead of the send address.
  LogSender — the default/dev fallback: logs what WOULD have been sent
    instead of sending anything.

Both implementations never raise — send_report_ready() returns True/
False so the caller (worker.py::_sweep_lite_completions) can log a
failure and simply retry on the next sweep pass, never propagate.

No templates engine — one hardcoded, plain HTML+text email, table-based
and inline-styled throughout (email clients are not browsers: no
webfonts, no CSS classes, no flex/grid). The link is the entire
payload: no score numbers anywhere in the body (Stage 9 U4 — link
unfurls must stay score-free), one call to action, one line noting the
link is private.
"""
import logging
import os
from abc import ABC, abstractmethod

import httpx

log = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
SEND_TIMEOUT_SECONDS = 10.0

# Brand tokens — kept here rather than imported from the web app's
# design system, which this worker-side module has no dependency on.
PARLEO_BLUE = "#2563EB"
PARLEO_BLUE_LIGHT = "#93B8FA"
INK = "#1B1E23"
MUTED = "#4A4F5C"
FAINT = "#8B90A0"
OUTER_BG = "#F7F6F3"
HAIRLINE = "#EDEBE7"
FONT_STACK = "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

PARLEO_URL = "https://parleo.io"
PREHEADER_TEXT = "Your agent-readiness results are in — one link, no login."


def mask_email(email: str) -> str:
    """Stage 12 (E4): 'a***@company.com' — never the real address in a
    log line. Never raises on malformed input."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    masked_local = f"{local[0]}***" if local else "***"
    return f"{masked_local}@{domain}"


def _email_subject(brand_name: str) -> str:
    return f"Your {brand_name} agentic value audit is ready"


def _email_text(report_url: str, brand_name: str) -> str:
    return (
        "Your audit is ready.\n\n"
        f"We measured how AI shopping agents see {brand_name} — whether "
        "they mention you, what they can read, and whether your real "
        "value survives into their answers.\n\n"
        "View your report:\n"
        f"{report_url}\n\n"
        "This link is private until you share it.\n\n"
        "— Parleo\n"
        f"{PARLEO_URL}"
    )


def _email_html(report_url: str, brand_name: str) -> str:
    return f"""\
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  </head>
  <body style="margin: 0; padding: 0; background-color: {OUTER_BG};">
    <span style="display: none; font-size: 0; line-height: 0; max-height: 0; max-width: 0; opacity: 0; overflow: hidden; mso-hide: all;">{PREHEADER_TEXT}</span>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: {OUTER_BG};">
      <tr>
        <td align="center" style="padding: 32px 16px;">
          <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="max-width: 560px; width: 100%; background-color: #FFFFFF; border-radius: 12px;">
            <tr>
              <td style="padding: 36px 40px 32px;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin: 0 0 28px;">
                  <tr>
                    <td style="padding: 0;">
                      <span style="display: inline-block; width: 7px; height: 18px; background-color: {PARLEO_BLUE}; border-radius: 2px; margin-right: 2px; vertical-align: middle;">&nbsp;</span>
                      <span style="display: inline-block; width: 5px; height: 12px; background-color: {PARLEO_BLUE_LIGHT}; border-radius: 2px; margin-right: 8px; vertical-align: middle;">&nbsp;</span>
                      <span style="font-family: {FONT_STACK}; font-weight: 800; font-size: 15px; letter-spacing: 0.05em; color: {INK}; vertical-align: middle;">PARLEO</span>
                    </td>
                  </tr>
                </table>
                <p style="margin: 0 0 14px; font-family: {FONT_STACK}; font-size: 11px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: {PARLEO_BLUE};">Free Agentic Value Audit</p>
                <p style="margin: 0 0 16px; font-family: {FONT_STACK}; font-size: 22px; font-weight: 700; color: {INK}; line-height: 1.3;">Your audit is ready.</p>
                <p style="margin: 0 0 28px; font-family: {FONT_STACK}; font-size: 15px; line-height: 1.6; color: {MUTED};">
                  We measured how AI shopping agents see {brand_name} — whether they mention you, what they can read, and whether your real value survives into their answers.
                </p>
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin: 0 0 14px;">
                  <tr>
                    <td style="border-radius: 8px; background-color: {PARLEO_BLUE};">
                      <a href="{report_url}" style="display: inline-block; padding: 13px 26px; font-family: {FONT_STACK}; font-size: 15px; font-weight: 600; color: #FFFFFF; text-decoration: none; border-radius: 8px;">View your report</a>
                    </td>
                  </tr>
                </table>
                <p style="margin: 0 0 24px; font-family: {FONT_STACK}; font-size: 13px; line-height: 1.5; color: {MUTED}; word-break: break-all;">{report_url}</p>
                <p style="margin: 0 0 28px; font-family: {FONT_STACK}; font-size: 12px; color: {FAINT};">This link is private until you share it.</p>
                <p style="margin: 0; font-family: {FONT_STACK}; font-size: 14px; color: {INK};">
                  — Parleo<br />
                  <a href="{PARLEO_URL}" style="color: {PARLEO_BLUE}; text-decoration: none;">parleo.io</a>
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding: 20px 40px 32px; border-top: 1px solid {HAIRLINE};">
                <p style="margin: 0 0 4px; font-family: {FONT_STACK}; font-size: 11px; color: {FAINT};">Live agent queries + a crawl of your store &middot; a sample, not a category study</p>
                <p style="margin: 0; font-family: {FONT_STACK}; font-size: 11px; color: {FAINT};">Parleo &middot; parleo.io</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
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
    def __init__(self, api_key: str, from_address: str, reply_to: str | None = None):
        self.api_key = api_key
        self.from_address = from_address
        self.reply_to = reply_to

    def send_report_ready(self, to: str, report_url: str, brand_name: str) -> bool:
        resp = None
        try:
            payload = {
                "from": self.from_address,
                "to": [to],
                "subject": _email_subject(brand_name),
                "html": _email_html(report_url, brand_name),
                "text": _email_text(report_url, brand_name),
            }
            if self.reply_to:
                payload["reply_to"] = self.reply_to
            resp = httpx.post(
                RESEND_API_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=SEND_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            log.info("[email:resend] sent report-ready email to %s", mask_email(to))
            return True
        except Exception:
            # Part 3: log the response body alongside the status so a
            # 403/422 from Resend diagnoses itself from the log line
            # instead of needing a repro — defensive getattr since a
            # transport-level failure (e.g. ConnectError) never assigns
            # resp, or assigns something without .text/.status_code.
            if resp is not None:
                log.error(
                    "[email:resend] failed to send report-ready email to %s — status=%s body=%s",
                    mask_email(to), getattr(resp, "status_code", "?"), getattr(resp, "text", "")[:300],
                )
            else:
                log.exception("[email:resend] failed to send report-ready email to %s", mask_email(to))
            return False


def get_email_sender() -> EmailSender:
    """
    Provider choice by env presence: RESEND_API_KEY + EMAIL_FROM both
    set means Resend; anything else (local dev, or a misconfiguration
    missing one of the two) falls back to LogSender so nothing crashes
    and every attempt is still visible in logs.

    EMAIL_REPLY_TO is optional and independent of provider choice — set
    it to a monitored inbox so replies to the audit email reach a human
    instead of bouncing into the from-address void.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    from_address = os.environ.get("EMAIL_FROM")
    reply_to = os.environ.get("EMAIL_REPLY_TO")
    if api_key and from_address:
        log.info(
            "[email] reply-to %s",
            "configured" if reply_to else "not configured — replies land at the from-address",
        )
        return ResendSender(api_key=api_key, from_address=from_address, reply_to=reply_to)
    if api_key and not from_address:
        log.warning("[email] RESEND_API_KEY set but EMAIL_FROM missing — falling back to LogSender")
    return LogSender()
