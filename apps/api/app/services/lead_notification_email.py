"""
lead_notification_email.py — internal "new lead" notification, sent when
a visitor attaches their email to an audit run (PATCH /api/public/
soa-lite/{token}/email, app/routers/public_lite.py::set_lite_email).

Deliberately a sibling of demo_request_email.py rather than a shared
helper: apps/api never imports apps/pipeline (the two communicate only
through Postgres — see public_lite.py's module docstring), so neither
can reuse apps/pipeline/email_sender.py, and an email sender isn't
schema, so it doesn't belong in soa_shared either. Same contract as
demo_request_email.py in every respect: sends via Resend's HTTP API
with httpx (no SDK), NEVER raises — returns True/False so the caller
decides whether to stamp lead_notified_at — masks the visitor's
address in every log line, and logs resp.text[:300] with the status on
a non-2xx response.

The report URL is built here rather than passed in, because unlike a
demo request (where the report token is optional) a lite request
always has exactly one token: the caller has nothing to decide.
"""
import logging
import os

import httpx

log = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
SEND_TIMEOUT_SECONDS = 10.0
DEFAULT_NOTIFY_ADDRESS = "leads@parleo.io"


def mask_email(email: str) -> str:
    """'a***@company.com' — never the real address in a log line. Never
    raises on malformed input. Duplicated from demo_request_email.py
    rather than imported — see module docstring."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    masked_local = f"{local[0]}***" if local else "***"
    return f"{masked_local}@{domain}"


def _notify_address() -> str:
    """LEAD_NOTIFY_EMAIL first, so lead notifications can be routed to a
    different alias than demo requests; DEMO_REQUEST_NOTIFY next, so a
    deploy that only ever set that one keeps working unchanged."""
    return (
        os.environ.get("LEAD_NOTIFY_EMAIL")
        or os.environ.get("DEMO_REQUEST_NOTIFY")
        or DEFAULT_NOTIFY_ADDRESS
    )


def _report_url(token: str) -> str:
    base = os.getenv("PUBLIC_AUDIT_BASE_URL", "https://audit.parleo.io").rstrip("/")
    return f"{base}/r/{token}"


def _competitors(fields: dict) -> str:
    names = fields.get("competitors") or []
    return ", ".join(str(n) for n in names) if names else "(none)"


def _subject(brand_name: str) -> str:
    return f"New audit lead — {brand_name}"


def _text_body(fields: dict, report_url: str) -> str:
    return "\n".join([
        "New audit lead.",
        "",
        f"Brand: {fields['brand_name']}",
        f"Email: {fields['email']}",
        f"Competitors: {_competitors(fields)}",
        f"Audit status: {fields['status']}",
        f"Report: {report_url}",
        f"Token: {fields['token']}",
        "",
        f"Submitted: {fields['submitted_at']}",
    ])


def _row(label: str, value: str) -> str:
    return (
        f'<tr><td style="padding: 6px 12px 6px 0; font-size: 13px; color: #8B90A0; '
        f'white-space: nowrap; vertical-align: top;">{label}</td>'
        f'<td style="padding: 6px 0; font-size: 14px; color: #1B1E23;">{value}</td></tr>'
    )


def _html_body(fields: dict, report_url: str) -> str:
    rows = [
        _row("Brand", fields["brand_name"]),
        _row("Email", fields["email"]),
        _row("Competitors", _competitors(fields)),
        _row("Audit status", fields["status"]),
        _row("Report", f'<a href="{report_url}" style="color: #2563EB;">{report_url}</a>'),
        _row("Token", fields["token"]),
        _row("Submitted", fields["submitted_at"]),
    ]

    return f"""\
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
  </head>
  <body style="margin: 0; padding: 0; background-color: #F7F6F3;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #F7F6F3;">
      <tr>
        <td align="center" style="padding: 32px 16px;">
          <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="max-width: 560px; width: 100%; background-color: #FFFFFF; border-radius: 12px;">
            <tr>
              <td style="padding: 32px 32px 28px; font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
                <p style="margin: 0 0 4px; font-size: 11px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: #2563EB;">New audit lead</p>
                <h1 style="margin: 0 0 20px; font-size: 20px; font-weight: 700; color: #1B1E23;">{fields['brand_name']}</h1>
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width: 100%; border-collapse: collapse;">
                  {''.join(rows)}
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def send_lead_notification(fields: dict) -> bool:
    """fields: brand_name, email, status, token, submitted_at (all str),
    competitors (list of str, or None). Never raises — returns
    True/False so the caller can decide whether to stamp
    lead_notified_at. reply_to is the visitor's own email, so replying
    to the notification starts the conversation with them directly."""
    api_key = os.environ.get("RESEND_API_KEY")
    from_address = os.environ.get("EMAIL_FROM")
    to_address = _notify_address()

    if not api_key or not from_address:
        log.warning(
            "[lead_notification_email] RESEND_API_KEY/EMAIL_FROM not set — "
            "not sending lead notification for %s",
            mask_email(fields["email"]),
        )
        return False

    report_url = _report_url(fields["token"])

    resp = None
    try:
        resp = httpx.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": from_address,
                "to": [to_address],
                "reply_to": fields["email"],
                "subject": _subject(fields["brand_name"]),
                "html": _html_body(fields, report_url),
                "text": _text_body(fields, report_url),
            },
            timeout=SEND_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        log.info(
            "[lead_notification_email] sent notification for %s to %s",
            mask_email(fields["email"]), mask_email(to_address),
        )
        return True
    except Exception:
        if resp is not None:
            log.error(
                "[lead_notification_email] failed to send notification for %s — status=%s body=%s",
                mask_email(fields["email"]), getattr(resp, "status_code", "?"), getattr(resp, "text", "")[:300],
            )
        else:
            log.exception(
                "[lead_notification_email] failed to send notification for %s",
                mask_email(fields["email"]),
            )
        return False
