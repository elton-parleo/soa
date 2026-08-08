"""
Public, unauthenticated API for the leadgen RequestFormModal — "Book
your walkthrough" / "Talk to us about TrueSync" on the audit landing +
report. Mounted at /api/public in app.py, same as public_lite.router;
deliberately its own file rather than added to public_lite.py, which
that file's own module docstring already frames as specifically the
SoA Lite widget (matches the one-feature-per-router pattern the rest
of app.py uses: studies/entities/cycles/metrics/scope/actions are each
their own file).

The insert into soa_demo_requests is the source of truth and always
happens before the notification email; an email failure must never
fail the request (Part 3b/4c of the leadgen brief) — see
_send_notification's own try/except and the fact that its result only
ever affects notified_at, never the HTTP response.
"""
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from soa_shared.database import engine

from app.schemas import PublicDemoRequestRequest, PublicDemoRequestResponse
from app.services.demo_request_email import send_demo_request_notification

log = logging.getLogger(__name__)
router = APIRouter()

# "A handful per minute is plenty for a demo form" — deliberately a much
# tighter window than soa-lite's hour/day tiers (public_lite.py), since
# this form is low-volume by nature and doesn't need the same shape of
# guard.
RATE_LIMIT_PER_IP_MINUTE = 5


def _get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _hash_ip(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()


def _rate_limited() -> HTTPException:
    return HTTPException(
        status_code=429,
        detail="Too many requests — try again in a minute.",
        headers={"Retry-After": "60"},
    )


def _enforce_rate_limit(conn, ip_hash: str, now: datetime) -> None:
    minute_count = conn.execute(text("""
        SELECT COUNT(*) FROM soa_demo_requests WHERE ip_hash = :h AND created_at > :cutoff
    """), {"h": ip_hash, "cutoff": now - timedelta(minutes=1)}).scalar()
    if minute_count >= RATE_LIMIT_PER_IP_MINUTE:
        raise _rate_limited()


def _report_url(report_token):
    if not report_token:
        return None
    base = os.getenv("PUBLIC_AUDIT_BASE_URL", "https://audit.parleo.io").rstrip("/")
    return f"{base}/r/{report_token}"


# ─── POST /api/public/demo-request ────────────────────────────────────────

@router.post("/demo-request", response_model=PublicDemoRequestResponse)
def submit_demo_request(data: PublicDemoRequestRequest, request: Request):
    # Honeypot (Part 3a): the client shouldn't send this field at all —
    # a non-empty value means whatever submitted this never rendered/
    # read the real form. Respond exactly as if it succeeded and store
    # nothing, so the trap gives no signal back to whatever tripped it.
    if data.website:
        log.info("[public_demo] honeypot tripped — discarding submission, no row written")
        return PublicDemoRequestResponse()

    ip_hash = _hash_ip(_get_client_ip(request))
    now = datetime.now(timezone.utc)

    with engine.connect() as conn:
        _enforce_rate_limit(conn, ip_hash, now)

    with engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO soa_demo_requests
              (name, email, company, message, source, page_url, brand_name, report_token, ip_hash)
            VALUES
              (:name, :email, :company, :message, :source, :page_url, :brand_name, :report_token, :ip_hash)
            RETURNING id, created_at
        """), {
            "name":         data.name,
            "email":        data.email,
            "company":      data.company,
            "message":      data.message,
            "source":       data.source,
            "page_url":     data.page_url,
            "brand_name":   data.brand_name,
            "report_token": data.report_token,
            "ip_hash":      ip_hash,
        }).first()
        demo_request_id, created_at = row[0], row[1]

    sent = send_demo_request_notification({
        "name": data.name,
        "email": data.email,
        "company": data.company,
        "message": data.message,
        "source": data.source,
        "page_url": data.page_url or "",
        "brand_name": data.brand_name,
        "report_token": data.report_token,
        "report_url": _report_url(data.report_token),
        "created_at": str(created_at),
    })

    if sent:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE soa_demo_requests SET notified_at = :now WHERE id = :id"),
                {"now": datetime.now(timezone.utc), "id": demo_request_id},
            )

    return PublicDemoRequestResponse()
