"""
When a "Run full loop" request has stopped making progress.

One rule, read by both halves: the worker (fullloop/coordinator.py) marks a
stale request failed with a `timed_out:` error, and the API's
GET /full-loop/{id} reports the same verdict for a request the worker has
not reached yet (a stopped worker never will), so the console's button
re-enables either way.

Progress is the newest of:
  * the request row's updated_at (every state change, every supply status
    change while polling, writes it);
  * the newest soa_runs.run_at of the request's own cycle;
  * while the request is waiting on the worker (not yet sent to supply, or
    its cycle still `planned`), the newest soa_runs.run_at of ANY cycle:
    the worker runs one cycle at a time, so a request queued behind a long
    cycle is waiting, not stuck.

STALE_MINUTES = 60: the longest Wiggle & Snug cycle on record
(20260915-113207-wiggle-snug-full, 516 runs) took 56 minutes from its first
run to its last, and its longest gap between two runs was under 3 minutes.
FULL_LOOP_STALE_MINUTES overrides it.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

ACTIVE = ('reference_pending', 'reference_done', 'cycle_planned')


def _minutes() -> int:
    try:
        return max(1, int(os.environ.get('FULL_LOOP_STALE_MINUTES', 60)))
    except (TypeError, ValueError):
        return 60


STALE_MINUTES = _minutes()


def _utc(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def last_progress(conn, row) -> Optional[datetime]:
    marks = [_utc(row.get('updated_at')), _utc(row.get('created_at'))]
    waiting_on_worker = row.get('supply_run_id') is None
    if row.get('cycle_id'):
        cycle = conn.execute(text(
            "SELECT status, (SELECT MAX(run_at) FROM soa_runs WHERE cycle_id = :c) "
            "FROM soa_cycles WHERE id = :c"), {'c': row['cycle_id']}).fetchone()
        if cycle is not None:
            marks.append(_utc(cycle[1]))
            waiting_on_worker = waiting_on_worker or cycle[0] == 'planned'
    if waiting_on_worker:
        marks.append(_utc(conn.execute(text("SELECT MAX(run_at) FROM soa_runs")).scalar()))
    marks = [m for m in marks if m is not None]
    return max(marks) if marks else None


def stale_error(conn, row, now: datetime, minutes: Optional[int] = None) -> Optional[str]:
    """The `timed_out:` error for an active request with no progress for
    `minutes`, or None while it is still moving (or already terminal)."""
    if row.get('status') not in ACTIVE:
        return None
    minutes = minutes or STALE_MINUTES
    last = last_progress(conn, row)
    if last is None or _utc(now) - last < timedelta(minutes=minutes):
        return None
    return (f"timed_out: no progress for {minutes} minutes while {row['status']} "
            f"(last progress {last.isoformat()})")
