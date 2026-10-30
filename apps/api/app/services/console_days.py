"""
2U-5 (B3): the one day formatter of the console's dated labels, in the
workspace's timezone.

"Compiled Oct 28" for a press at 20:05 PDT Oct 27: supply's stamps are UTC
(naive, or with +00:00) and each builder cut their first ten characters. A
stamp (a value with a time) is now turned into the workspace's local date;
a bare date ("2026-10-24", a read day) has no time to convert and reads as
it is.

The zone is set once per request where the merchant is resolved
(console_merchants.resolve -> use_zone_for): the merchant's own setting (its
study's tier_config.merchant.timezone, set in the Create Study wizard) when
one exists, else the org's default (SOA_DEFAULT_TIMEZONE, else
America/Los_Angeles: soa_shared.local_time). Every /truesync, /publishing,
/approvals and /overview label reads short_day.
"""
import contextvars
import json
from datetime import date
from typing import Optional

from sqlalchemy import text

from soa_shared import local_time

_zone: contextvars.ContextVar = contextvars.ContextVar('console_zone', default=None)


def zone() -> str:
    return _zone.get() or local_time.default_timezone()


def use_zone(name: Optional[str]) -> None:
    _zone.set(name if local_time.is_timezone(name) else None)


def merchant_zone(conn, org_id: int, slug: Optional[str]) -> str:
    """The merchant's study timezone when one of the org's studies names one, else the default."""
    try:
        rows = conn.execute(text("""
            SELECT syndicated_merchant, tier_config FROM soa_query_generation_jobs
            WHERE COALESCE(customer_organization_id, organization_id) = :org ORDER BY id DESC
        """), {'org': org_id}).mappings().all()
    except Exception:  # noqa: BLE001 - a schema without the table (a test's): the default
        conn.rollback()
        return local_time.default_timezone()
    for row in rows:
        config = row['tier_config']
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except ValueError:
                config = None
        merchant = (config or {}).get('merchant') if isinstance(config, dict) else None
        owner = row['syndicated_merchant'] or (merchant or {}).get('slug')
        tz = (merchant or {}).get('timezone') if isinstance(merchant, dict) else None
        if (slug is None or owner == slug) and local_time.is_timezone(tz):
            return tz.strip()
    return local_time.default_timezone()


def use_zone_for(org_id: int, slug: Optional[str]) -> None:
    from soa_shared.database import engine
    try:
        with engine.connect() as conn:
            use_zone(merchant_zone(conn, org_id, slug))
    except Exception:  # noqa: BLE001 - no database (a unit test): the default
        use_zone(None)


def local_day(value) -> Optional[date]:
    """The workspace-local date of a stamp; a bare date as it is. 2V-3: the
    rule is soa_shared.local_time.local_day, which the narrative writer uses too."""
    return local_time.local_day(value, zone())


def short_day(value) -> Optional[str]:
    """"Oct 27": the workspace-local day of a stamp or a date, None when there is none."""
    return local_time.short_day(value, zone())
