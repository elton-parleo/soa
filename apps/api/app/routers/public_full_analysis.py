"""
Public, unauthenticated — shareable Full Analysis reports. Same
treatment as public_lite.py/public_demo.py (mounted at /api/public, no
verify_token dependency — see app/app.py).

A share link is owner-initiated (full_analysis.py's create_share_link)
and revocable; this router is the read-only, token-scoped surface
anyone with the link uses, no login. Reuses full_analysis.py's own
render gate/assembly (_assemble_full_analysis_report) so a cycle that
wouldn't render Full Analysis for its owner can't render it publicly
either — never a second, divergent rendering path.

Unknown, revoked, and expired tokens all resolve to the exact same 404
— the single JOIN below filters all three out identically, so there's
no separate branch that could accidentally leak which case a given
token falls into.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from soa_shared.database import engine
from app.routers.full_analysis import _assemble_full_analysis_report
from app.routers.public_lite import _get_client_ip, _hash_ip, _rate_limited
from app.schemas import FullAnalysisReportResponse

router = APIRouter()

# A read is cheap (no LLM spend, unlike lite's submit endpoint) so this
# is far looser than RATE_LIMIT_PER_IP_HOUR in public_lite.py — it
# exists to stop scripted hammering of the public endpoint, not to
# ration a scarce resource.
RATE_LIMIT_PER_IP_HOUR = 120


def _enforce_read_rate_limit(conn, ip_hash: str, now: datetime) -> None:
    hour_count = conn.execute(text("""
        SELECT COUNT(*) FROM soa_public_share_views WHERE ip_hash = :h AND created_at > :cutoff
    """), {"h": ip_hash, "cutoff": now - timedelta(hours=1)}).scalar()
    if hour_count >= RATE_LIMIT_PER_IP_HOUR:
        raise _rate_limited(3600, "Too many requests — try again in an hour.")


@router.get("/full-analysis/{token}", response_model=FullAnalysisReportResponse)
def get_public_full_analysis_report(token: str, request: Request):
    ip_hash = _hash_ip(_get_client_ip(request))
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        _enforce_read_rate_limit(conn, ip_hash, now)

        # revoked_at IS NULL and the expiry check both live in the WHERE
        # clause (not a Python-side comparison after fetch) so an
        # unknown, a revoked, and an expired token all just fail to
        # match a row — one code path, one 404, no case that could
        # diverge in shape from the others.
        row = conn.execute(text("""
            SELECT cs.id, cs.cycle_id, c.cycle_code, c.source_lite_request_id
            FROM soa_cycle_shares cs
            JOIN soa_cycles c ON c.id = cs.cycle_id
            WHERE cs.token = :token
              AND cs.revoked_at IS NULL
              AND (cs.expires_at IS NULL OR cs.expires_at > :now)
        """), {"token": token, "now": now}).fetchone()

        share_id = row[0] if row else None
        conn.execute(text("""
            INSERT INTO soa_public_share_views (share_id, ip_hash, created_at)
            VALUES (:share_id, :ip_hash, :now)
        """), {"share_id": share_id, "ip_hash": ip_hash, "now": now})

        if not row:
            raise HTTPException(status_code=404, detail="Not found.")
        _, cycle_id, cycle_code, source_lite_request_id = row

        report = _assemble_full_analysis_report(conn, cycle_id, cycle_code, source_lite_request_id)

        # A cycle whose crawl was later deleted/reset, or that never
        # reached 'complete', must not render publicly even with a live,
        # unrevoked token — the render gate is the same for both
        # audiences (module docstring), so this falls back to the same
        # 404 rather than a 200 with rendered=False.
        if not report.rendered:
            raise HTTPException(status_code=404, detail="Not found.")

    return report
