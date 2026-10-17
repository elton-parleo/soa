"""
2B §5: "Run full loop" from soa.

    POST /api/full-loop          queue it: one request row, 202 {full_loop_id, status: 'queued'}
    GET  /api/full-loop/{id}     the combined status (supply run + soa cycle)

Operator or org member, server-side: the org's tenant token is opened here
and attached upstream, never sent to the browser. Scoped like every console
read (app/console_scope.py): a member acts for their own org, an operator
may name one with ?org=.

POST validates the study and the surfaces, records the request with no
supply_run_id, and returns. It does not call supply: supply's
POST .../full-loop answers with the finished run up to 25 pages, which took
longer than a Vercel request may (a 504). The worker
(apps/pipeline/fullloop/coordinator.py) picks the row up the way it picks
up a planned cycle, from the database: POST supply, poll to reference_done,
create the cycle with full_loop_run_id, run and score it on the chosen
surfaces, PATCH supply with soa_cycle_id and scored|failed. Manual trigger
only; nothing schedules it.

GET reports a request with no progress for full_loop_staleness.STALE_MINUTES
as failed (timed_out) even before the worker has marked it so, so a stopped
worker never leaves the console's button disabled.
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
from app import worker_surfaces
from soa_shared.full_loop_staleness import stale_error

router = APIRouter(tags=["full-loop"])

#: Injection point for tests, which may not reach supply.
client_factory = None


def _client(scope: CustomerScope) -> TrueSyncClient:
    return (client_factory or (lambda token: TrueSyncClient(token=token)))(scope.token)


class FullLoopStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_slug: str
    #: 2I: absent on a merchant with no study: a reads-only request (the
    #: access series and the reference reads, supply's stage one), no surfaces
    study_type: Optional[str] = None
    platforms: List[str] = Field(default_factory=list)
    runs_per_query: int = Field(default=1, ge=1, le=10)
    allow_hosted_render: bool = True

    @property
    def reads_only(self) -> bool:
        return not self.study_type


def _iso(value):
    return value.isoformat() if hasattr(value, 'isoformat') else value


def _study_org(conn, study_type: str):
    row = conn.execute(text(
        "SELECT customer_organization_id, organization_id FROM soa_query_generation_jobs "
        "WHERE study_type = :st"), {"st": study_type}).fetchone()
    if row is None:
        return None
    return row[0] if row[0] is not None else row[1]


def _platforms(value) -> list:
    """The stored platform list, [] when null (a reads-only request)."""
    if value is None:
        return []
    return json.loads(value) if isinstance(value, str) else list(value)


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
    reference = ('failed' if supply_status == 'failed' or (status == 'failed' and not row.get('supply_run_id')) else
                 'done' if supply_status in ('reference_done', 'scored') or status not in ('reference_pending',)
                 else 'running')
    reads_only = not row.get('study_type')
    study = ('none_yet' if reads_only else 'waiting' if cycle is None else
             {'planned': 'queued', 'running': 'running', 'complete': 'done', 'failed': 'failed'}
             .get(cycle['status'], cycle['status']))
    scoring = 'not_applicable' if reads_only else {'scored': 'done', 'failed': 'failed'}.get(status, 'waiting')
    platforms = _platforms(row.get('platforms'))
    # 2I-2: availability from the worker's report, not the API's environment
    report = worker_surfaces.configured(engine) if platforms else {}
    # 2I: when the pages were read: supply's run finished_at, else (a row the
    # worker closed) the request's own last update
    read_at = ((supply_view or {}).get('finished_at') or (_iso(row.get('updated_at')) if status == 'reads_done' else None)) \
        if reference == 'done' else None
    out = {
        'id': row['id'],
        'status': status,
        'merchant': row['merchant_slug'],
        'study_type': row['study_type'],
        'platforms': platforms,
        'surfaces': [surfaces.get(p).as_dict(configured=report) if surfaces.get(p) else {'id': p} for p in platforms],
        'runs_per_query': row['runs_per_query'],
        # 2I: what the run dialog compares against, named as /api/console/runs
        # names them (platforms are stored resolved since 2D)
        'surface_ids': list(platforms),
        'runs_per_question': row['runs_per_query'],
        'study_id': row['study_type'],
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
            {'step': 'study', 'label': 'Study: none yet' if reads_only else 'Study on the chosen surfaces', 'state': study},
            {'step': 'scoring', 'label': 'Scored and reported to TrueSync', 'state': scoring},
        ],
    }
    if reads_only:
        # 2I: only on a reads-only request, so a request with a study reads
        # exactly as before (tests/fixtures/full_loop_pre_2i.py)
        out.update(mode='reads_only', read_at=read_at)
    return out


@router.post("/full-loop", status_code=202)
async def start_full_loop(body: FullLoopStart, scope: CustomerScope = Depends(console_scope),
                          user: dict = Depends(verify_token)):
    if body.reads_only:
        return _queue_reads_only(body, scope, user)
    if not body.platforms:
        raise HTTPException(status_code=422, detail="a full loop with a study needs at least one surface")
    with engine.connect() as conn:
        owner = _study_org(conn, body.study_type)
    if owner != scope.org.id:
        raise HTTPException(status_code=404, detail=f"study {body.study_type!r} not found")
    # 2H: a study is generated for one merchant, and the loop runs for that
    # one: the coordinator keys every step on merchant_slug. Checked from the
    # study's job, not supply, so starting a loop still makes no supply call.
    # A study with no merchant recorded predates 2H and is not checked.
    from app.console_merchants import study_merchants
    with engine.connect() as conn:
        study_merchant = study_merchants(conn, scope.org.id).get(body.study_type)
    if study_merchant and study_merchant != body.merchant_slug:
        raise HTTPException(status_code=404, detail=f"merchant {body.merchant_slug!r} not found for study {body.study_type!r}")
    # 2D: the request stores resolved ids, never an alias ("gemini" is
    # gemini_api); an unknown name is a 422. 229 was created from a request
    # that stored "gemini". 2I: grounded surfaces only, and only those the
    # worker has a key for (app/worker_surfaces.py).
    platforms = worker_surfaces.check_dispatch(body.platforms, engine)
    for platform in platforms:
        reason = surfaces.reported_reason(platform)
        if reason:
            raise HTTPException(status_code=422, detail=f"surface {platform!r} cannot run: {reason}")

    with engine.begin() as conn:
        request_id = conn.execute(text("""
            INSERT INTO soa_full_loop_requests (organization_id, merchant_slug, study_type, platforms,
                runs_per_query, allow_hosted_render, status, created_by, created_at, updated_at)
            VALUES (:org, :slug, :st, :p, :rpq, :ahr, 'reference_pending', :by, :now, :now)
            RETURNING id
        """), {"org": scope.org.id, "slug": body.merchant_slug, "st": body.study_type,
               "p": json.dumps(platforms), "rpq": body.runs_per_query,
               "ahr": body.allow_hosted_render, "by": user.get('email') or user.get('sub'),
               "now": datetime.now(timezone.utc)}).scalar()
    return {'full_loop_id': request_id, 'id': request_id, 'status': 'queued'}


def _queue_reads_only(body: FullLoopStart, scope: CustomerScope, user: dict) -> dict:
    """2I: a merchant with no study reads its pages first. No study, no
    surfaces, no cycle: the worker POSTs supply and stops at its
    reference_done (`reads_done` here). The merchant is not checked against
    the org here, which would be a supply call: the worker's POST is refused
    by supply (404) for a merchant that is not the token's, and the request
    fails with that reason."""
    if body.platforms:
        raise HTTPException(status_code=422, detail="a reads-only request runs no surface: send no platforms")
    with engine.begin() as conn:
        request_id = conn.execute(text("""
            INSERT INTO soa_full_loop_requests (organization_id, merchant_slug, study_type, platforms,
                runs_per_query, allow_hosted_render, status, created_by, created_at, updated_at)
            VALUES (:org, :slug, NULL, :p, 1, :ahr, 'reference_pending', :by, :now, :now)
            RETURNING id
        """), {"org": scope.org.id, "slug": body.merchant_slug, "p": json.dumps([]),
               "ahr": body.allow_hosted_render, "by": user.get('email') or user.get('sub'),
               "now": datetime.now(timezone.utc)}).scalar()
    return {'full_loop_id': request_id, 'id': request_id, 'status': 'queued', 'mode': 'reads_only'}


async def read_full_loop(request_id: int, scope: CustomerScope) -> dict:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM soa_full_loop_requests WHERE id = :id"),
                           {"id": request_id}).mappings().fetchone()
    if row is None or row['organization_id'] != scope.org.id:
        raise HTTPException(status_code=404, detail=f"full loop {request_id} not found")
    row = dict(row)
    with engine.connect() as conn:
        timed_out = stale_error(conn, row, datetime.now(timezone.utc))
    if timed_out:
        row.update(status='failed', error=timed_out)
    supply_view, supply_error = None, None
    if row['supply_run_id']:
        _status, payload, error = await _client(scope).get_full_loop_run(
            row['merchant_slug'], row['supply_run_id'])
        supply_view, supply_error = (payload if isinstance(payload, dict) else None), error
    return combined_status(row, supply_view=supply_view, supply_error=supply_error)


@router.get("/full-loop/{request_id}")
async def get_full_loop(request_id: int, scope: CustomerScope = Depends(console_scope)):
    return await read_full_loop(request_id, scope)
