"""
Run-manifest event contract (Part 1, E1-E3) — the append-only events[]
log on soa_lite_requests that drives the status page's always-visible
console and arrival-order completion feed (apps/api/web/src/lite/
LiteProgress.jsx).

TASK ids are stable and registered ONCE, here — display names live in
this dict, not scattered across worker.py/run_orchestrator.py/
orchestrator/pipeline.py, so every call site passes a task id plus
whatever dynamic text is true for that moment, never invents its own
label for a task's identity. The frontend keeps its own small,
manually-synced copy of these ids (JS can't import Python — same
precedent as BOT_NAME/BOT_UA in BotsPage.jsx).

emit_event() is a synchronous read-modify-write with NO `await`
between the SELECT and the UPDATE — safe even under RunOrchestrator's
asyncio.gather()/semaphore concurrency (the queries task emits from
inside concurrently-scheduled coroutines), because asyncio only ever
switches which coroutine is running at an `await` point; a synchronous
DB call made directly (not through run_in_executor) blocks the single
event loop for its own duration, so no other coroutine's emit_event()
call can interleave with an in-flight one. This is the exact same
single-process-concurrency assumption run_orchestrator.py already
relies on for `counters["completed"] += 1` inside that same
asyncio.gather() — see its docstring.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from soa_shared.database import engine

log = logging.getLogger(__name__)

MAX_LOG_EVENTS = 200

TASK_CRAWL = "crawl"
TASK_PROBE_MEMBERSHIP = "probe_membership"
TASK_PROBE_REVENUE = "probe_revenue"
TASK_PROBE_FETCH = "probe_fetch"
TASK_COMPETITORS = "competitors"
TASK_QUERIES = "queries"
TASK_SCORING = "scoring"
TASK_REPORT = "report"

TASKS = {
    TASK_CRAWL: "Reading your store",
    TASK_PROBE_MEMBERSHIP: "Membership check",
    TASK_PROBE_REVENUE: "Revenue estimate",
    TASK_PROBE_FETCH: "Fetch probe",
    TASK_COMPETITORS: "Competitor set",
    TASK_QUERIES: "Shopper questions",
    TASK_SCORING: "Scoring the answers",
    TASK_REPORT: "Your report",
}

# Pseudo-task for kind=state events (queued/running/done/failed/
# degraded-blocked/no-product-pages) — these describe the OVERALL run
# transitioning, not any one task in TASKS, but the event shape always
# carries a `task` field, so state events use this stable sentinel
# rather than leaving it null.
RUN_TASK = "run"

KIND_LOG = "log"
KIND_DONE = "done"
KIND_STATE = "state"


def _decode_events(raw) -> list:
    """Same defensive str-vs-already-decoded idiom as
    worker.py::process_lite_requests' competitor_names handling —
    psycopg2 decodes JSON/JSONB natively; a raw string only shows up
    against a driver (or SQLite test setup) that doesn't."""
    if isinstance(raw, str):
        return json.loads(raw) if raw else []
    return list(raw) if raw is not None else []


def _valid_task(task: str, kind: str) -> bool:
    if kind == KIND_STATE:
        return task == RUN_TASK
    return task in TASKS


def emit_event(
    request_id: int,
    task: str,
    event_text: str,
    kind: str = KIND_LOG,
    chips: list | None = None,
) -> None:
    """
    Appends one event to soa_lite_requests.events for `request_id`.
    Never raises out to the caller — a bug in event narration must
    never break the stage it's narrating (mirrors this codebase's
    never-throw philosophy for anything that isn't the pipeline's own
    state machine; see worker.py's probe isolation).

    E2: log-kind events are capped at the most recent MAX_LOG_EVENTS —
    done/state events are never trimmed. The cap is applied AFTER
    appending, so the just-written event is never itself the one
    dropped, and re-sorted by seq afterward so trimmed log events and
    always-kept done/state events stay in a single seq-ordered array.
    """
    if not _valid_task(task, kind):
        log.error(f"[lite_events] invalid task {task!r} for kind={kind!r} — dropping event")
        return
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT events FROM soa_lite_requests WHERE id = :id"),
                {"id": request_id},
            ).fetchone()
            if row is None:
                return
            events = _decode_events(row[0])
            seq = (events[-1]["seq"] + 1) if events else 1
            new_event = {
                "seq": seq,
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": kind,
                "task": task,
                "text": event_text,
            }
            if chips is not None:
                new_event["chips"] = chips
            events.append(new_event)

            if kind == KIND_LOG:
                logs = [e for e in events if e["kind"] == KIND_LOG]
                others = [e for e in events if e["kind"] != KIND_LOG]
                if len(logs) > MAX_LOG_EVENTS:
                    logs = logs[-MAX_LOG_EVENTS:]
                events = sorted(logs + others, key=lambda e: e["seq"])

            conn.execute(
                text("UPDATE soa_lite_requests SET events = :events WHERE id = :id"),
                {"events": json.dumps(events), "id": request_id},
            )
    except Exception:
        log.exception(
            f"[lite_events] failed to emit {kind} event for request {request_id} (task={task})"
        )


def emit_log(request_id: int, task: str, event_text: str) -> None:
    emit_event(request_id, task, event_text, kind=KIND_LOG)


def emit_done(request_id: int, task: str, event_text: str, chips: list | None = None) -> None:
    emit_event(request_id, task, event_text, kind=KIND_DONE, chips=chips)


def emit_state(request_id: int, event_text: str) -> None:
    emit_event(request_id, RUN_TASK, event_text, kind=KIND_STATE)
