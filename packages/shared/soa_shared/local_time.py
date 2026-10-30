"""
2K-1: the merchant's local date, for cycle codes and a study's display date.
Sync copies to apps/api/soa_shared/, apps/pipeline/soa_shared/ and
packages/shared/soa_shared/.

FL12-pampers-20261020 ran on Oct 19 in Los Angeles: its code carried the UTC
date, and the console called the study generated that evening "the Oct 20
study". A NEW cycle code and the study's display date read the merchant's
local time instead: the study's tier_config.merchant.timezone (an IANA name,
set in the Create Study wizard) when set, else SOA_DEFAULT_TIMEZONE, else
America/Los_Angeles. Existing codes are not renamed; stored timestamps stay
UTC, and the API serves `created_at_local` beside them.
"""
import json
import os
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = 'America/Los_Angeles'
TIMEZONE_ENV = 'SOA_DEFAULT_TIMEZONE'


def is_timezone(name) -> bool:
    """An IANA zone name this Python can resolve."""
    if not isinstance(name, str) or not name.strip():
        return False
    try:
        ZoneInfo(name.strip())
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def default_timezone() -> str:
    """SOA_DEFAULT_TIMEZONE when it names a zone, else America/Los_Angeles."""
    env = os.getenv(TIMEZONE_ENV)
    return env.strip() if is_timezone(env) else DEFAULT_TIMEZONE


def merchant_timezone(tier_config=None) -> str:
    """tier_config.merchant.timezone when set and valid, else the default."""
    if isinstance(tier_config, str):
        try:
            tier_config = json.loads(tier_config)
        except ValueError:
            tier_config = None
    merchant = (tier_config or {}).get('merchant') if isinstance(tier_config, dict) else None
    tz = (merchant or {}).get('timezone') if isinstance(merchant, dict) else None
    return tz.strip() if is_timezone(tz) else default_timezone()


def _aware(value) -> Optional[datetime]:
    """A stored timestamp as an aware datetime; a naive one is UTC (soa
    writes UTC), a string is ISO 8601."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return None   # a date carries no time to convert
    return None


def local_datetime(value, tz: Optional[str] = None) -> Optional[datetime]:
    moment = _aware(value)
    return moment.astimezone(ZoneInfo(tz or default_timezone())) if moment else None


def local_date(value, tz: Optional[str] = None) -> Optional[date]:
    """The merchant-local calendar date of a UTC moment."""
    moment = local_datetime(value, tz)
    return moment.date() if moment else None


def local_iso(value, tz: Optional[str] = None) -> Optional[str]:
    """`created_at_local`: the moment in the merchant's zone, ISO 8601 with
    its offset (2026-10-19T21:26:00-07:00)."""
    moment = local_datetime(value, tz)
    return moment.isoformat() if moment else None


def local_day(value, tz: Optional[str] = None) -> Optional[date]:
    """2V-3: the local date of a stamp (a value with a time) in `tz`, else
    the default zone; a bare date ("2026-10-24", a read day) has no time to
    convert and reads as it is. The one day rule of the console's labels
    (2U-5, apps/api/app/services/console_days.py) and the narrative lines."""
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        return local_date(value, tz)
    if isinstance(value, date):
        return value
    text_ = str(value).strip()
    if len(text_) > 10 and text_[10] in 'T ':
        day = local_date(text_.replace(' ', 'T', 1), tz)
        if day is not None:
            return day
    try:
        return date.fromisoformat(text_[:10])
    except ValueError:
        return None


def short_day(value, tz: Optional[str] = None) -> Optional[str]:
    """"Oct 29": local_day as the labels write it, None when there is none."""
    d = local_day(value, tz)
    return f"{d.strftime('%b')} {d.day}" if d else None
