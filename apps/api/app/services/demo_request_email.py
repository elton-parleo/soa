"""
demo_request_email.py — Leadgen session: notification email for a new
soa_demo_requests row, sent from the API service (apps/api).

apps/api never imports apps/pipeline (see app/routers/public_lite.py's
module docstring — the two communicate only through Postgres), so this
cannot reuse apps/pipeline/email_sender.py directly. This is a minimal,
self-contained sender with the SAME contract as that module: never
raises, masks the email address in logs, logs resp.text[:300]
alongside the status on a non-2xx Resend response. Deliberately not
promoted into soa_shared — unlike the DB model, an email sender isn't
schema, and this module is genuinely API-only (the worker sends its
own, different, report-ready email).
"""
import logging
import os

import httpx

log = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
SEND_TIMEOUT_SECONDS = 10.0
DEFAULT_NOTIFY_ADDRESS = "elton@parleo.io"


def mask_email(email: str) -> str:
    """'a***@company.com' — never the real address in a log line. Never
    raises on malformed input. Duplicated from apps/pipeline/
    email_sender.py rather than imported — see module docstring."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    masked_local = f"{local[0]}***" if local else "***"
    return f"{masked_local}@{domain}"


def _subject(company: str, source: str) -> str:
    return f"Demo request — {company} ({source})"


def _text_body(fields: dict) -> str:
    lines = [
        "New demo request.",
        "",
        f"Name: {fields['name']}",
        f"Email: {fields['email']}",
        f"Company: {fields['company']}",
        f"Source: {fields['source']}",
        f"Page: {fields['page_url']}",
    ]
    if fields.get("brand_name"):
        lines.append(f"Brand: {fields['brand_name']}")
    if fields.get("report_token") and fields.get("report_url"):
        lines.append(f"Report: {fields['report_url']}")
    lines += [
        "",
        f"Message: {fields['message'] or '(none)'}",
        "",
        f"Submitted: {fields['created_at']}",
    ]
    return "\n".join(lines)


def _row(label: str, value: str) -> str:
    return (
        f'<tr><td style="padding: 6px 12px 6px 0; font-size: 13px; color: #8B90A0; '
        f'white-space: nowrap; vertical-align: top;">{label}</td>'
        f'<td style="padding: 6px 0; font-size: 14px; color: #1B1E23;">{value}</td></tr>'
    )


def _html_body(fields: dict) -> str:
    rows = [
        _row("Name", fields["name"]),
        _row("Email", fields["email"]),
        _row("Company", fields["company"]),
        _row("Source", fields["source"]),
        _row("Page", f'<a href="{fields["page_url"]}" style="color: #2563EB;">{fields["page_url"]}</a>'),
    ]
    if fields.get("brand_name"):
        rows.append(_row("Brand", fields["brand_name"]))
    if fields.get("report_token") and fields.get("report_url"):
        rows.append(_row("Report", f'<a href="{fields["report_url"]}" style="color: #2563EB;">{fields["report_url"]}</a>'))
    rows.append(_row("Submitted", fields["created_at"]))

    message = (fields.get("message") or "(none)").replace("\n", "<br />")

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
                <p style="margin: 0 0 4px; font-size: 11px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: #2563EB;">New demo request</p>
                <h1 style="margin: 0 0 20px; font-size: 20px; font-weight: 700; color: #1B1E23;">{fields['company']}</h1>
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width: 100%; border-collapse: collapse;">
                  {''.join(rows)}
                </table>
                <p style="margin: 20px 0 0; font-size: 13px; font-weight: 600; color: #4A4F5C;">Message</p>
                <p style="margin: 6px 0 0; font-size: 14px; line-height: 1.6; color: #1B1E23;">{message}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def send_demo_request_notification(fields: dict) -> bool:
    """fields: name, email, company, message, source, page_url,
    created_at (all str), brand_name/report_token/report_url (str or
    None). Never raises — returns True/False so the caller can decide
    whether to stamp notified_at. reply_to is the submitter's own
    email, so replying to the notification starts the conversation
    with them directly."""
    api_key = os.environ.get("RESEND_API_KEY")
    from_address = os.environ.get("EMAIL_FROM")
    to_address = os.environ.get("DEMO_REQUEST_NOTIFY") or DEFAULT_NOTIFY_ADDRESS

    if not api_key or not from_address:
        log.warning(
            "[demo_request_email] RESEND_API_KEY/EMAIL_FROM not set — "
            "not sending demo-request notification for %s",
            mask_email(fields["email"]),
        )
        return False

    resp = None
    try:
        resp = httpx.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": from_address,
                "to": [to_address],
                "reply_to": fields["email"],
                "subject": _subject(fields["company"], fields["source"]),
                "html": _html_body(fields),
                "text": _text_body(fields),
            },
            timeout=SEND_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        log.info(
            "[demo_request_email] sent notification for %s to %s",
            mask_email(fields["email"]), mask_email(to_address),
        )
        return True
    except Exception:
        if resp is not None:
            log.error(
                "[demo_request_email] failed to send notification for %s — status=%s body=%s",
                mask_email(fields["email"]), getattr(resp, "status_code", "?"), getattr(resp, "text", "")[:300],
            )
        else:
            log.exception(
                "[demo_request_email] failed to send notification for %s",
                mask_email(fields["email"]),
            )
        return False
