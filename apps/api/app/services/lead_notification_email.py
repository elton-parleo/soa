"""
lead_notification_email.py — the two internal notifications that tell us
about an audit, both sent from apps/api:

  * send_audit_started_notification — POST /api/public/soa-lite created a
    run (public_lite.py::submit_lite_request). No visitor email exists
    yet; this is the "someone is auditing X right now" heads-up.
  * send_lead_notification — the visitor later attached their email
    (PATCH /api/public/soa-lite/{token}/email, set_lite_email). This is
    the one that turns an anonymous run into a lead, so it carries
    reply_to.

Deliberately a sibling of demo_request_email.py rather than a shared
helper: apps/api never imports apps/pipeline (the two communicate only
through Postgres — see public_lite.py's module docstring), so neither
can reuse apps/pipeline/email_sender.py, and an email sender isn't
schema, so it doesn't belong in soa_shared either. Same contract as
demo_request_email.py in every respect: sends via Resend's HTTP API
with httpx (no SDK), NEVER raises — returns True/False so the caller
decides what to record — masks every address it logs, and logs
resp.text[:300] with the status on a non-2xx response.

Both senders share one POST implementation (_post_to_resend): the
never-raises/masked-logging contract is the whole point of this module,
so it lives in exactly one place and neither sender can drift from it.

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
    """LEAD_NOTIFY_EMAIL first, so audit/lead notifications can be routed
    to a different alias than demo requests; DEMO_REQUEST_NOTIFY next, so
    a deploy that only ever set that one keeps working unchanged."""
    return (
        os.environ.get("LEAD_NOTIFY_EMAIL")
        or os.environ.get("DEMO_REQUEST_NOTIFY")
        or DEFAULT_NOTIFY_ADDRESS
    )


def _report_url(token: str) -> str:
    base = os.getenv("PUBLIC_AUDIT_BASE_URL", "https://parleo.io/audit").rstrip("/")
    return f"{base}/r/{token}"


# ─── the one Resend call ─────────────────────────────────────────────────

def _post_to_resend(payload: dict, log_context: str) -> bool:
    """POSTs an already-built Resend payload (everything except `from`,
    which comes from the environment alongside the API key). Never
    raises — returns True/False.

    log_context is a short, ALREADY-SAFE description of what is being
    sent, e.g. "lead notification for v***@company.com": it goes
    straight into the log line, so any address in it must already have
    been through mask_email.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    from_address = os.environ.get("EMAIL_FROM")

    if not api_key or not from_address:
        log.warning(
            "[lead_notification_email] RESEND_API_KEY/EMAIL_FROM not set — "
            "not sending %s",
            log_context,
        )
        return False

    resp = None
    try:
        resp = httpx.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"from": from_address, **payload},
            timeout=SEND_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        log.info(
            "[lead_notification_email] sent %s to %s",
            log_context, mask_email((payload.get("to") or [""])[0]),
        )
        return True
    except Exception:
        if resp is not None:
            log.error(
                "[lead_notification_email] failed to send %s — status=%s body=%s",
                log_context, getattr(resp, "status_code", "?"), getattr(resp, "text", "")[:300],
            )
        else:
            log.exception("[lead_notification_email] failed to send %s", log_context)
        return False


# ─── shared body formatting ──────────────────────────────────────────────

def _competitors(fields: dict) -> str:
    names = fields.get("competitors") or []
    return ", ".join(str(n) for n in names) if names else "(none)"


def _store_url_text(fields: dict) -> str:
    return fields.get("store_url") or "(none)"


def _link(url: str) -> str:
    return f'<a href="{url}" style="color: #2563EB;">{url}</a>'


def _store_url_html(fields: dict) -> str:
    """A link only when there is one — store_url is optional on the row,
    and an empty <a href=""> is worse than saying so in words."""
    url = fields.get("store_url")
    return _link(url) if url else "(none)"


def _row(label: str, value: str) -> str:
    return (
        f'<tr><td style="padding: 6px 12px 6px 0; font-size: 13px; color: #8B90A0; '
        f'white-space: nowrap; vertical-align: top;">{label}</td>'
        f'<td style="padding: 6px 0; font-size: 14px; color: #1B1E23;">{value}</td></tr>'
    )


def _html_document(eyebrow: str, heading: str, rows: list) -> str:
    """The shared shell for both notifications — same table-based,
    inline-styled layout as demo_request_email.py, since these land in
    the same inbox and mail clients strip <style> blocks."""
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
                <p style="margin: 0 0 4px; font-size: 11px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: #2563EB;">{eyebrow}</p>
                <h1 style="margin: 0 0 20px; font-size: 20px; font-weight: 700; color: #1B1E23;">{heading}</h1>
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


# ─── "new lead": the visitor attached their email ────────────────────────

def _lead_subject(brand_name: str) -> str:
    return f"New audit lead — {brand_name}"


def _lead_text_body(fields: dict, report_url: str) -> str:
    return "\n".join([
        "New audit lead.",
        "",
        f"Brand: {fields['brand_name']}",
        f"Email: {fields['email']}",
        f"Store URL: {_store_url_text(fields)}",
        f"Competitors: {_competitors(fields)}",
        f"Audit status: {fields['status']}",
        f"Report: {report_url}",
        f"Token: {fields['token']}",
        "",
        f"Submitted: {fields['submitted_at']}",
    ])


def _lead_html_body(fields: dict, report_url: str) -> str:
    return _html_document("New audit lead", fields["brand_name"], [
        _row("Brand", fields["brand_name"]),
        _row("Email", fields["email"]),
        _row("Store URL", _store_url_html(fields)),
        _row("Competitors", _competitors(fields)),
        _row("Audit status", fields["status"]),
        _row("Report", _link(report_url)),
        _row("Token", fields["token"]),
        _row("Submitted", fields["submitted_at"]),
    ])


def _lead_email_payload(fields: dict) -> dict:
    report_url = _report_url(fields["token"])
    return {
        "to": [_notify_address()],
        # reply_to is the visitor's own email, so replying to the
        # notification starts the conversation with them directly.
        "reply_to": fields["email"],
        "subject": _lead_subject(fields["brand_name"]),
        "html": _lead_html_body(fields, report_url),
        "text": _lead_text_body(fields, report_url),
    }


def send_lead_notification(fields: dict) -> bool:
    """fields: brand_name, email, status, token, submitted_at (all str),
    store_url (str or None), competitors (list of str, or None). Never
    raises — returns True/False so the caller can decide whether to
    stamp lead_notified_at."""
    return _post_to_resend(
        _lead_email_payload(fields),
        f"lead notification for {mask_email(fields['email'])}",
    )


# ─── "audit started": the run was just created ───────────────────────────

def _audit_started_subject(brand_name: str) -> str:
    return f"New audit started — {brand_name}"


def _audit_started_text_body(fields: dict, report_url: str) -> str:
    return "\n".join([
        "New audit started.",
        "",
        f"Brand: {fields['brand_name']}",
        f"Store URL: {_store_url_text(fields)}",
        f"Competitors: {_competitors(fields)}",
        f"Report: {report_url}",
        f"Token: {fields['token']}",
        "",
        f"Submitted: {fields['submitted_at']}",
    ])


def _audit_started_html_body(fields: dict, report_url: str) -> str:
    return _html_document("New audit started", fields["brand_name"], [
        _row("Brand", fields["brand_name"]),
        _row("Store URL", _store_url_html(fields)),
        _row("Competitors", _competitors(fields)),
        _row("Report", _link(report_url)),
        _row("Token", fields["token"]),
        _row("Submitted", fields["submitted_at"]),
    ])


def _audit_started_payload(fields: dict) -> dict:
    report_url = _report_url(fields["token"])
    # No reply_to: at this point in the flow there is no visitor email to
    # reply to — that only arrives with the PATCH the lead notification
    # hangs off.
    return {
        "to": [_notify_address()],
        "subject": _audit_started_subject(fields["brand_name"]),
        "html": _audit_started_html_body(fields, report_url),
        "text": _audit_started_text_body(fields, report_url),
    }


def send_audit_started_notification(fields: dict) -> bool:
    """fields: brand_name, token, submitted_at (all str), store_url (str
    or None), competitors (list of str, or None). Never raises —
    returns True/False. The report link points at a run that has only
    just been queued, so it will 'not ready yet' until the pipeline
    finishes; it is there so a run can be opened later from the same
    email."""
    return _post_to_resend(
        _audit_started_payload(fields),
        f"audit-started notification for token={fields['token']}",
    )
