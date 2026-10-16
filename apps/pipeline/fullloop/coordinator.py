"""
2B §5: "Run full loop" from soa, the worker half.

The API (POST /api/full-loop) only records one soa_full_loop_requests row
and answers 202: supply's POST answers with the finished run up to 25 pages,
which took longer than a Vercel request may. Everything happens here, on
the worker's poll, because the API and the pipeline meet only in the
database (the same way a planned cycle reaches the worker):

  reference_pending  with no supply_run_id: queued. POST supply's full
                     loop, then record its run id (supply_status
                     'starting' while the POST is in flight).
                     With a supply_run_id: supply's run is still running
                     its access series and reference reads (it ran as a
                     background job: more than 25 pages). Poll
                     GET .../full-loop/{run_id}.
  reference_done     supply finished the reads. Create the soa cycle,
                     with full_loop_run_id, on the request's surfaces.
  cycle_planned      the cycle exists; the worker's ordinary planned-cycle
                     path runs and scores it (orchestrator Stage 1-2c).
                     When it is complete or failed, PATCH supply.
  scored | failed    terminal. `error` says why on failed.

The supply calls, with the org's tenant token (customers.token_for_org),
exactly as access-series.md "5. Run full loop" specifies:

  POST  /api/truesync/merchants/{slug}/full-loop  {"allow_hosted_render": bool}
  GET   /api/truesync/merchants/{slug}/full-loop/{run_id}
  PATCH /api/truesync/merchants/{slug}/full-loop/{run_id}  {"soa_cycle_id": "<id>", "status": "scored"|"failed"}

The PATCH may only move reference_done -> scored | failed; repeating the
same cycle id is idempotent; a DIFFERENT cycle id is a 409, and so is any
other transition. A 409 fails the request with supply's reason and is never
retried: it means the run belongs to another cycle. Manual trigger only:
nothing here starts a full loop on a schedule.

A request with no progress for soa_shared.full_loop_staleness.STALE_MINUTES
is failed with a `timed_out:` error: its cycle, if still planned or
running, is failed too, and supply's run is PATCHed failed where supply
allows it (reference_done). A POST the worker was killed in the middle of
is failed `orphaned_by_restart:` and never re-sent: supply may already
hold a run for it, and a second POST would start another.
"""
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Optional

import httpx
from sqlalchemy import text

import soa_shared.config as config
from soa_shared.full_loop_staleness import ACTIVE, stale_error

logger = logging.getLogger(__name__)

#: Supply's POST runs the whole loop inline up to 25 pages: 19 pages took
#: 45-47 seconds for Wiggle & Snug (2026-10-14). Generous, so a slow read is
#: never mistaken for a failure.
START_TIMEOUT_SECONDS = float(os.environ.get('FULL_LOOP_START_TIMEOUT_SECONDS', 900))


@dataclass
class SupplyResult:
    status_code: Optional[int]
    body: Optional[dict]
    error: Optional[str]
    #: False only when the request never reached supply (no connection), so
    #: repeating it cannot start a second run.
    sent: bool = True


class SupplyFullLoopClient:
    """Synchronous; the worker's loop is synchronous. Never raises."""

    def __init__(self, token: str, base_url: Optional[str] = None, timeout: float = 30.0,
                 transport=None) -> None:
        self.token = token
        self.base_url = (base_url or config.TRUESYNC_API_BASE).rstrip('/')
        self.timeout = timeout
        self.transport = transport

    def _call(self, method: str, path: str, body: Optional[dict] = None,
              timeout: Optional[float] = None) -> SupplyResult:
        try:
            with httpx.Client(transport=self.transport, timeout=timeout or self.timeout) as client:
                response = client.request(method, f"{self.base_url}{path}", json=body,
                                          headers={'X-TrueSync-Key': self.token})
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            return SupplyResult(None, None, f"{type(exc).__name__}: {exc}".replace(self.token, '***'),
                                sent=False)
        except httpx.HTTPError as exc:
            return SupplyResult(None, None, f"{type(exc).__name__}: {exc}".replace(self.token, '***'))
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code >= 400:
            detail = payload.get('detail') if isinstance(payload, dict) else response.text[:300]
            return SupplyResult(response.status_code, payload,
                                str(detail).replace(self.token, '***'))
        return SupplyResult(response.status_code, payload, None)

    def start(self, slug: str, *, allow_hosted_render: bool = True) -> SupplyResult:
        """200 with the finished run up to 25 pages, 202 with it running above."""
        return self._call('POST', f"/api/truesync/merchants/{slug}/full-loop",
                          {'allow_hosted_render': bool(allow_hosted_render)},
                          timeout=START_TIMEOUT_SECONDS)

    def run(self, slug: str, run_id: int) -> SupplyResult:
        return self._call('GET', f"/api/truesync/merchants/{slug}/full-loop/{run_id}")

    def patch(self, slug: str, run_id: int, *, soa_cycle_id: Optional[str], status: str) -> SupplyResult:
        body = {'status': status}
        if soa_cycle_id is not None:
            body = {'soa_cycle_id': soa_cycle_id, **body}
        return self._call('PATCH', f"/api/truesync/merchants/{slug}/full-loop/{run_id}", body)


def _default_client_for(org_id: int) -> SupplyFullLoopClient:
    from soa_shared import customers
    return SupplyFullLoopClient(customers.token_for_org(org_id))


def _json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


class Coordinator:
    def __init__(self, engine=None, client_for: Callable[[int], SupplyFullLoopClient] = None,
                 clock: Callable[[], datetime] = None) -> None:
        if engine is None:
            from soa_shared.database import engine as default_engine
            engine = default_engine
        self.engine = engine
        self.client_for = client_for or _default_client_for
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ─── rows ────────────────────────────────────────────────────────

    def _set(self, request_id: int, **fields) -> None:
        fields['updated_at'] = self.clock()
        assignments = ', '.join(f"{k} = :{k}" for k in fields)
        with self.engine.begin() as conn:
            conn.execute(text(f"UPDATE soa_full_loop_requests SET {assignments} WHERE id = :id"),
                         {**fields, 'id': request_id})

    def active(self) -> list:
        with self.engine.connect() as conn:
            return conn.execute(text(
                "SELECT * FROM soa_full_loop_requests WHERE status IN "
                "('reference_pending', 'reference_done', 'cycle_planned') ORDER BY id"
            )).mappings().all()

    def get(self, request_id: int):
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT * FROM soa_full_loop_requests WHERE id = :id"),
                                {'id': request_id}).mappings().fetchone()

    # ─── the machine ─────────────────────────────────────────────────

    def tick(self) -> int:
        """Advance every active request one step. Returns how many moved."""
        moved = 0
        for row in self.active():
            try:
                if self.time_out(row):
                    moved += 1
                    continue
                if self.advance(row):
                    moved += 1
            except Exception as exc:  # noqa: BLE001 - one request never stops the others
                logger.exception("[full-loop] request %s", row['id'])
                self._set(row['id'], status='failed', error=f"coordinator error: {exc}"[:1000])
        return moved

    def time_out(self, row) -> bool:
        """Fail a request with no progress for STALE_MINUTES. True if it did."""
        with self.engine.connect() as conn:
            error = stale_error(conn, row, self.clock())
        if error is None:
            return False
        logger.warning("[full-loop] request %s: %s", row['id'], error)
        if row['cycle_id']:
            with self.engine.begin() as conn:
                conn.execute(text(
                    "UPDATE soa_cycles SET status = 'failed', notes = COALESCE(notes, '') || :n "
                    "WHERE id = :c AND status IN ('planned', 'running')"),
                    {'c': row['cycle_id'], 'n': f"\n[full loop {row['id']}] {error}"})
        supply_status = row['supply_status']
        if row['supply_run_id'] and row['status'] in ('reference_done', 'cycle_planned'):
            # Supply's run is reference_done: the one state it lets us fail.
            result = self.client_for(row['organization_id']).patch(
                row['merchant_slug'], row['supply_run_id'],
                soa_cycle_id=str(row['cycle_id']) if row['cycle_id'] else None, status='failed')
            if result.error is None:
                supply_status = (result.body or {}).get('status', 'failed')
            else:
                logger.warning("[full-loop] request %s: PATCH failed on time-out (%s)",
                               row['id'], result.error)
        self._set(row['id'], status='failed', supply_status=supply_status, error=error)
        return True

    def advance(self, row) -> bool:
        status = row['status']
        if status == 'reference_pending' and row['supply_run_id'] is None:
            return self._start(row)
        if status == 'reference_pending':
            return self._poll_reference(row)
        if status == 'reference_done':
            return self._create_cycle(row)
        if status == 'cycle_planned':
            return self._finish(row)
        return False

    def _start(self, row) -> bool:
        """POST supply's full loop for a queued request."""
        if row['supply_status'] == 'starting':
            # A POST was in flight when the worker stopped. Supply may hold
            # a run this request never learned the id of; a second POST
            # would start another, so this one is not re-sent.
            self._set(row['id'], status='failed',
                      error="orphaned_by_restart: the worker stopped while supply's full loop "
                            "was starting; press Run full loop again")
            return True
        self._set(row['id'], supply_status='starting')
        client = self.client_for(row['organization_id'])
        allow = row.get('allow_hosted_render')
        result = client.start(row['merchant_slug'], allow_hosted_render=True if allow is None else allow)
        if result.error is not None:
            if not result.sent:
                logger.warning("[full-loop] request %s: supply unreachable (%s); will retry",
                               row['id'], result.error)
                self._set(row['id'], supply_status=None)
                return False
            why = (f"merchant {row['merchant_slug']!r} not found" if result.status_code == 404
                   else f"TrueSync full loop did not start: {result.error}")
            self._set(row['id'], status='failed', supply_status=None, error=why)
            return True
        payload = result.body if isinstance(result.body, dict) else {}
        if payload.get('id') is None:
            self._set(row['id'], status='failed', supply_status=None,
                      error=f"TrueSync full loop did not start: no run in its answer ({result.status_code})")
            return True
        supply_status = payload.get('status')
        status = {'reference_done': 'reference_done', 'failed': 'failed'}.get(
            supply_status, 'reference_pending')
        self._set(row['id'], supply_run_id=payload['id'], supply_status=supply_status, status=status,
                  error=(f"supply full loop failed: {payload.get('error')}" if status == 'failed' else None))
        return True

    def _poll_reference(self, row) -> bool:
        client = self.client_for(row['organization_id'])
        result = client.run(row['merchant_slug'], row['supply_run_id'])
        if result.error is not None:
            if result.status_code in (401, 403, 404):
                self._set(row['id'], status='failed',
                          error=f"supply refused the run read ({result.status_code}): {result.error}")
                return True
            logger.warning("[full-loop] request %s: supply read failed (%s); will retry",
                           row['id'], result.error)
            return False
        supply_status = (result.body or {}).get('status')
        if supply_status == 'reference_done':
            self._set(row['id'], status='reference_done', supply_status=supply_status)
            return True
        if supply_status == 'failed':
            self._set(row['id'], status='failed', supply_status=supply_status,
                      error=f"supply full loop failed: {(result.body or {}).get('error')}")
            return True
        if supply_status != row['supply_status']:
            self._set(row['id'], supply_status=supply_status)
        return False

    def _comparison_set(self, conn, row) -> list:
        """The study's latest cycle's comparison set, in this org's hands."""
        prior = conn.execute(text(
            "SELECT id FROM soa_cycles WHERE study_type = :st ORDER BY start_date DESC, id DESC LIMIT 1"
        ), {'st': row['study_type']}).fetchone()
        if prior is None:
            return []
        entities = conn.execute(text(
            "SELECT entity_id, comparison_code, role FROM soa_cycle_entities WHERE cycle_id = :c "
            "ORDER BY comparison_code"
        ), {'c': prior[0]}).mappings().all()
        return [dict(e) for e in entities]

    def _create_cycle(self, row) -> bool:
        from soa_shared import surfaces
        from soa_shared.cycle_creation import create_cycle_with_comparison_set

        # 2D: resolved before the count, as the insert resolves them: a
        # request stored before 2D may hold "gemini", which is gemini_api now
        try:
            platforms = surfaces.resolve_platforms(_json(row['platforms']) or [])
        except surfaces.UnknownSurface as exc:
            self._set(row['id'], status='failed', error=f"could not create the cycle: {exc}")
            return True
        today = self.clock().date()
        cycle_code = f"FL{row['supply_run_id']}-{row['merchant_slug']}-{today:%Y%m%d}"
        with self.engine.begin() as conn:
            pattern = conn.execute(text(
                "SELECT study_pattern FROM soa_queries WHERE study_type = :st AND status = 'Active' "
                "LIMIT 1"), {'st': row['study_type']}).fetchone()
            queries = conn.execute(text(
                "SELECT COUNT(*) FROM soa_queries WHERE study_type = :st AND status = 'Active'"),
                {'st': row['study_type']}).scalar() or 0
            comparison = self._comparison_set(conn, row)
            if pattern is None or not comparison:
                why = ('the study has no active questions' if pattern is None else
                       'the study has no earlier cycle to take a comparison set from')
                conn.execute(text(
                    "UPDATE soa_full_loop_requests SET status = 'failed', error = :e, "
                    "updated_at = :u WHERE id = :id"),
                    {'e': f"could not create the cycle: {why}", 'u': self.clock(), 'id': row['id']})
                return True
            cycle_id, _created = create_cycle_with_comparison_set(
                conn, cycle_code=cycle_code, study_type=row['study_type'],
                study_pattern=pattern[0], cycle_mode='query', truecost_tiers=None,
                total_runs_planned=queries * len(platforms) * (row['runs_per_query'] or 1),
                start_date=today, platforms=json.dumps(platforms),
                runs_per_query=row['runs_per_query'] or 1,
                organization_id=row['organization_id'], created_by=row['created_by'],
                notes=f"Full loop: supply run {row['supply_run_id']} for {row['merchant_slug']}",
                comparison_set=comparison,
            )
            conn.execute(text("UPDATE soa_cycles SET full_loop_run_id = :r WHERE id = :c"),
                         {'r': row['supply_run_id'], 'c': cycle_id})
            conn.execute(text(
                "UPDATE soa_full_loop_requests SET status = 'cycle_planned', cycle_id = :c, "
                "updated_at = :u WHERE id = :id"), {'c': cycle_id, 'u': self.clock(), 'id': row['id']})
        return True

    def _finish(self, row) -> bool:
        with self.engine.connect() as conn:
            cycle = conn.execute(text("SELECT id, status, notes FROM soa_cycles WHERE id = :c"),
                                 {'c': row['cycle_id']}).fetchone()
        if cycle is None:
            self._set(row['id'], status='failed', error='the cycle this request created is gone')
            return True
        if cycle[1] not in ('complete', 'failed'):
            return False
        outcome = 'scored' if cycle[1] == 'complete' else 'failed'
        client = self.client_for(row['organization_id'])
        result = client.patch(row['merchant_slug'], row['supply_run_id'],
                              soa_cycle_id=str(cycle[0]), status=outcome)
        if result.error is not None:
            if result.status_code == 409:
                # Another cycle owns the run, or the transition is not
                # allowed. Never retried: retrying cannot make it true.
                self._set(row['id'], status='failed', supply_status='conflict',
                          error=f"supply refused the PATCH (409): {result.error}")
                return True
            if result.status_code in (401, 403, 404):
                self._set(row['id'], status='failed',
                          error=f"supply refused the PATCH ({result.status_code}): {result.error}")
                return True
            logger.warning("[full-loop] request %s: PATCH failed (%s); will retry",
                           row['id'], result.error)
            return False
        error = None if outcome == 'scored' else f"cycle failed: {cycle[2] or 'see the cycle'}"
        self._set(row['id'], status=outcome, supply_status=(result.body or {}).get('status', outcome),
                  error=error)
        return True


def process_full_loops(coordinator: Coordinator = None) -> int:
    """The worker's hook: one step for every active request."""
    return (coordinator or Coordinator()).tick()
