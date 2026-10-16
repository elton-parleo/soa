"""
2I: combined_status as it was on main before 2I (a4a095a.. b08e242), frozen,
for the byte-identity test: a request with a study must read exactly as it
did (tests/test_full_loop_2i.py). Code, not a fixture of a site; do not edit.
"""
import json
from typing import Optional

from sqlalchemy import text

from soa_shared import surfaces


def _iso(value):
    return value.isoformat() if hasattr(value, 'isoformat') else value


def combined_status(row, *, supply_view: Optional[dict], supply_error: Optional[str]) -> dict:
    """The one object the console's button and status strip read."""
    cycle = None
    if row.get('cycle_id'):
        with _engine().connect() as conn:
            c = conn.execute(text(
                "SELECT id, cycle_code, status, completed_runs, total_runs_planned, full_loop_run_id "
                "FROM soa_cycles WHERE id = :id"), {"id": row['cycle_id']}).mappings().fetchone()
        cycle = dict(c) if c else None
    supply_status = (supply_view or {}).get('status') or row.get('supply_status')
    status = row['status']
    reference = ('failed' if supply_status == 'failed' or (status == 'failed' and not row.get('supply_run_id')) else
                 'done' if supply_status in ('reference_done', 'scored') or status not in ('reference_pending',)
                 else 'running')
    study = ('waiting' if cycle is None else
             {'planned': 'queued', 'running': 'running', 'complete': 'done', 'failed': 'failed'}
             .get(cycle['status'], cycle['status']))
    scoring = {'scored': 'done', 'failed': 'failed'}.get(status, 'waiting')
    return {
        'id': row['id'],
        'status': status,
        'merchant': row['merchant_slug'],
        'study_type': row['study_type'],
        'platforms': json.loads(row['platforms']) if isinstance(row['platforms'], str) else row['platforms'],
        'surfaces': [surfaces.get(p).as_dict() if surfaces.get(p) else {'id': p}
                     for p in (json.loads(row['platforms']) if isinstance(row['platforms'], str)
                               else row['platforms'])],
        'runs_per_query': row['runs_per_query'],
        'error': row.get('error'),
        'created_at': _iso(row.get('created_at')),
        'updated_at': _iso(row.get('updated_at')),
        'supply': {
            'run_id': row.get('supply_run_id'),
            'status': supply_status,
            'run': supply_view,
            'read_error': supply_error,
        },
        'cycle': cycle,
        'strip': [
            {'step': 'reference', 'label': 'Access and reference reads', 'state': reference},
            {'step': 'study', 'label': 'Study on the chosen surfaces', 'state': study},
            {'step': 'scoring', 'label': 'Scored and reported to TrueSync', 'state': scoring},
        ],
    }


def _engine():
    from app.routers import full_loop
    return full_loop.engine
