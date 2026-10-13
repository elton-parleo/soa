"""
2B §5: "Run full loop" from soa.

    POST /api/full-loop          start it: supply's run, then a request row
    GET  /api/full-loop/{id}     the combined status (supply run + soa cycle)

Operator or org member, server-side: the org's tenant token is opened here
and attached upstream, never sent to the browser. Scoped like every console
read (app/console_scope.py): a member acts for their own org, an operator
may name one with ?org=.

POST calls supply's POST /api/truesync/merchants/{slug}/full-loop, which
answers 200 with the finished run up to 25 pages and 202 with the run in
`running` above that. Either way the rest happens on the worker
(apps/pipeline/fullloop/coordinator.py): poll to reference_done, create the
cycle with full_loop_run_id, run and score it on the chosen surfaces, PATCH
supply with soa_cycle_id and scored|failed. This route returns as soon as
the request is recorded. Manual trigger only; nothing schedules it.
"""
import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.auth import verify_token
from app.console_scope import console_scope
from app.customer_context import CustomerScope
from clients.truesync_client import TrueSyncClient
from soa_shared import surfaces
from soa_shared.database import engine

router = APIRouter(tags=["full-loop"])

#: Injection point for tests, which may not reach supply.
client_factory = None


def _client(scope: CustomerScope) -> TrueSyncClient:
    return (client_factory or (lambda token: TrueSyncClient(token=token)))(scope.token)


class FullLoopStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_slug: str
    study_type: str
    platforms: List[str] = Field(min_length=1)
    runs_per_query: int = Field(default=1, ge=1, le=10)
    allow_hosted_render: bool = True


def _iso(value):
    return value.isoformat() if hasattr(value, 'isoformat') else value


def _study_org(conn, study_type: str):
    row = conn.execute(text(
        "SELECT customer_organization_id, organization_id FROM soa_query_generation_jobs "
        "WHERE study_type = :st"), {"st": study_type}).fetchone()
    if row is None:
        return None
    return row[0] if row[0] is not None else row[1]


def combined_status(row, *, supply_view: Optional[dict], supply_error: Optional[str]) -> dict:
    """The one object the console's button and status strip read."""
    cycle = None
    if row.get('cycle_id'):
        with engine.connect() as conn:
            c = conn.execute(text(
                "SELECT id, cycle_code, status, completed_runs, total_runs_planned, full_loop_run_id "
                "FROM soa_cycles WHERE id = :id"), {"id": row['cycle_id']}).mappings().fetchone()
        cycle = dict(c) if c else None
    supply_status = (supply_view or {}).get('status') or row.get('supply_status')
    status = row['status']
    reference = ('failed' if supply_status == 'failed' else
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


@router.post("/full-loop", status_code=202)
async def start_full_loop(body: FullLoopStart, scope: CustomerScope = Depends(console_scope),
                          user: dict = Depends(verify_token)):
    with engine.connect() as conn:
        owner = _study_org(conn, body.study_type)
    if owner != scope.org.id:
        raise HTTPException(status_code=404, detail=f"study {body.study_type!r} not found")
    for platform in body.platforms:
        reason = surfaces.unavailable_reason(platform)
        if reason:
            raise HTTPException(status_code=422, detail=f"surface {platform!r} cannot run: {reason}")

    status, payload, error = await _client(scope).post_full_loop(
        body.merchant_slug, allow_hosted_render=body.allow_hosted_render)
    if error is not None or not isinstance(payload, dict):
        if status == 404:
            raise HTTPException(status_code=404, detail=f"merchant {body.merchant_slug!r} not found")
        raise HTTPException(status_code=502, detail=f"TrueSync full loop did not start: {error}")

    supply_status = payload.get('status')
    request_status = {'reference_done': 'reference_done', 'failed': 'failed'}.get(
        supply_status, 'reference_pending')
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        request_id = conn.execute(text("""
            INSERT INTO soa_full_loop_requests (organization_id, merchant_slug, study_type, platforms,
                runs_per_query, supply_run_id, supply_status, status, error, created_by,
                created_at, updated_at)
            VALUES (:org, :slug, :st, :p, :rpq, :run, :ss, :status, :err, :by, :now, :now)
            RETURNING id
        """), {"org": scope.org.id, "slug": body.merchant_slug, "st": body.study_type,
               "p": json.dumps(body.platforms), "rpq": body.runs_per_query,
               "run": payload.get('id'), "ss": supply_status, "status": request_status,
               "err": (f"supply full loop failed: {payload.get('error')}"
                       if request_status == 'failed' else None),
               "by": user.get('email') or user.get('sub'), "now": now}).scalar()
        row = conn.execute(text("SELECT * FROM soa_full_loop_requests WHERE id = :id"),
                           {"id": request_id}).mappings().one()
    return combined_status(dict(row), supply_view=payload, supply_error=None)


async def read_full_loop(request_id: int, scope: CustomerScope) -> dict:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM soa_full_loop_requests WHERE id = :id"),
                           {"id": request_id}).mappings().fetchone()
    if row is None or row['organization_id'] != scope.org.id:
        raise HTTPException(status_code=404, detail=f"full loop {request_id} not found")
    supply_view, supply_error = None, None
    if row['supply_run_id']:
        _status, payload, error = await _client(scope).get_full_loop_run(
            row['merchant_slug'], row['supply_run_id'])
        supply_view, supply_error = (payload if isinstance(payload, dict) else None), error
    return combined_status(dict(row), supply_view=supply_view, supply_error=supply_error)


@router.get("/full-loop/{request_id}")
async def get_full_loop(request_id: int, scope: CustomerScope = Depends(console_scope)):
    return await read_full_loop(request_id, scope)
