"""
Pipeline polling worker.

Railway runs this as a continuously running process. It polls soa_cycles
every 30 seconds for rows with status = 'planned' and executes each one
through PipelineOrchestrator.

The API (Vercel) writes status='planned' when a user launches a cycle in
the UI. This worker picks it up and runs it. The two services communicate
only through the database — no direct coupling.

Also polls soa_lite_requests (status='pending') for SoA Lite, the public
unauthenticated lead-gen flow: process_lite_requests resolves entities,
generates a fixed 12-query study, and creates a cycle for it, which then
flows through the SAME planned-cycle poll/execute_cycle path as any other
cycle (prioritized — see get_next_planned_cycle). _sweep_lite_completions
mirrors that cycle's terminal state back onto soa_lite_requests.
"""
import os
import sys
import time
import json
import asyncio
import logging
from datetime import datetime, timezone

# Add pipeline root to path so local modules resolve correctly
sys.path.insert(0, os.path.dirname(__file__))

from soa_shared.database import engine
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [worker] %(levelname)s %(message)s',
)
log = logging.getLogger(__name__)

POLL_INTERVAL = 30  # seconds when idle


def get_next_planned_cycle():
    """
    Fetch the oldest planned cycle.
    Returns a Row with (cycle_code, study_type, platforms, runs_per_query,
    cycle_mode) or None.

    SoA Lite cycles (cycle_code prefix 'lite-') jump the queue ahead of
    everything else: they run in ~2 minutes (1 platform, 1 run/query, 12
    queries) versus hours for a full client cycle, and a lead-gen visitor
    is waiting live on the result. Within each priority tier, oldest first.
    """
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT
              cycle_code,
              study_type,
              platforms,
              runs_per_query,
              cycle_mode
            FROM soa_cycles
            WHERE status = 'planned'
            ORDER BY (CASE WHEN cycle_code LIKE 'lite-%' THEN 0 ELSE 1 END), created_at ASC
            LIMIT 1
        """)).fetchone()
    return row


def mark_failed(cycle_code: str, error: str):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE soa_cycles
            SET status = 'failed',
                notes = COALESCE(notes,'') || :suffix
            WHERE cycle_code = :code
        """), {
            "code":   cycle_code,
            "suffix": (
                f"\n[worker error "
                f"{datetime.now(timezone.utc).isoformat()}] {error}"
            ),
        })
    log.error(f"Marked {cycle_code} as failed: {error}")


async def execute_truecost_sweep(cycle_code: str):
    """
    cycle_mode='truecost' path — sweeps the cycle's scoped SKUs through the
    Deal Engine instead of running LLM queries. No soa_runs, no coder.
    """
    from sqlalchemy import text as _text
    from soa_shared.models.soa_models import SoaCycle
    from soa_shared.database import session_factory
    from sweep.truecost_sweep import run_truecost_sweep

    log.info(f"Starting truecost sweep for {cycle_code}")
    with session_factory() as session:
        cycle = session.query(SoaCycle).filter_by(cycle_code=cycle_code).first()
        cycle.status = "running"
        session.commit()

    summary = await run_truecost_sweep(cycle_code)

    with session_factory() as session:
        cycle = session.query(SoaCycle).filter_by(cycle_code=cycle_code).first()
        cycle.status = "complete"
        cycle.total_runs_planned = summary.total_planned
        cycle.completed_runs = summary.captured + summary.unavailable
        cycle.end_date = datetime.now(timezone.utc).date()
        session.commit()

    log.info(
        f"Truecost sweep done: {cycle_code} — "
        f"captured={summary.captured} unavailable={summary.unavailable} "
        f"skipped={summary.skipped_already_done} "
        f"({summary.sku_count} SKUs x {summary.tier_count} tiers)"
    )


async def execute_cycle(
    cycle_code: str,
    study_type: str,
    platforms: list,
    runs_per_query: int,
    cycle_mode: str = "query",
):
    if cycle_mode == "truecost":
        await execute_truecost_sweep(cycle_code)
        return

    from orchestrator.pipeline import PipelineOrchestrator
    log.info(f"Starting pipeline for {cycle_code} ({study_type})")
    log.info(f"Platforms: {platforms}")
    log.info(f"Runs per query: {runs_per_query}")
    orch = PipelineOrchestrator(
        cycle_code=cycle_code,
        study_type=study_type,
        platforms=platforms,
        runs_per_query=runs_per_query,
    )
    await orch.run_pipeline()
    log.info(f"Pipeline done: {cycle_code}")


def _mark_generation_failed(job_id: int, error: str):
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE soa_query_generation_jobs
            SET status = 'failed',
                error_message = :err,
                updated_at = NOW()
            WHERE id = :id
        """), {"id": job_id, "err": error[:1000]})
        conn.commit()


def _insert_generated_rows(
    rows: list,
    study_type: str,
    organization_id: int,
    created_by: str | None,
):
    """
    Bulk inserts validated generated rows into soa_queries with
    auto-generated query_codes. Uses _query_code_prefix logic.
    organization_id and created_by are taken from the generation job row
    so every inserted query is correctly scoped to the requesting org.
    """
    name = study_type
    for pfx in ('brand_', 'retailer_', 'sonic_', 'senso_'):
        if name.startswith(pfx):
            name = name[len(pfx):]
            break
    prefix = name.split('_')[0][:3].upper()

    with engine.connect() as conn:
        count_row = conn.execute(
            text("SELECT COUNT(*) FROM soa_queries WHERE study_type = :st"),
            {"st": study_type},
        ).fetchone()
        counter = count_row[0] or 0

        for row in rows:
            counter += 1
            query_code = f"{prefix}_{counter:03d}"
            # Collision check (global — query_code must be globally unique)
            while conn.execute(
                text("SELECT 1 FROM soa_queries WHERE query_code = :code"),
                {"code": query_code},
            ).fetchone():
                counter += 1
                query_code = f"{prefix}_{counter:03d}"

            conn.execute(text("""
                INSERT INTO soa_queries (
                    query_code, query_text, category, stage,
                    specificity, persona, study_type, study_pattern,
                    soa_focus, rationale, status,
                    organization_id, created_by,
                    created_at
                ) VALUES (
                    :query_code, :query_text, :category, :stage,
                    :specificity, :persona, :study_type, :study_pattern,
                    :soa_focus, :rationale, :status,
                    :organization_id, :created_by,
                    NOW()
                )
            """), {
                "query_code":      query_code,
                "query_text":      row['query_text'],
                "category":        row['category'],
                "stage":           row['stage'],
                "specificity":     row['specificity'],
                "persona":         row['persona'],
                "study_type":      study_type,
                "study_pattern":   row['study_pattern'],
                "soa_focus":       row.get('soa_focus'),
                "rationale":       row.get('rationale'),
                "status":          row['status'],
                "organization_id": organization_id,
                "created_by":      created_by,
            })
        conn.commit()


def process_generation_jobs():
    """
    Polls soa_query_generation_jobs for status='pending', processes one job
    per call (one at a time to avoid OpenAI rate limits and DB contention
    with cycle processing).
    """
    import os

    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT id, study_type, study_name, description, target_count,
                   organization_id, created_by
            FROM soa_query_generation_jobs
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT 1
        """)).fetchone()

        if not row:
            return

        (job_id, study_type, study_name, description, target_count,
         organization_id, created_by) = row

        # Mark running
        conn.execute(text("""
            UPDATE soa_query_generation_jobs
            SET status = 'running', updated_at = NOW()
            WHERE id = :id
        """), {"id": job_id})
        conn.commit()

    log.info(
        f"[generation] Starting job {job_id} for '{study_type}' "
        f"({target_count} queries)"
    )

    from generation.query_generator import generate_query_batch, BATCH_SIZE

    api_key = os.environ.get("OPEN_AI_API_KEY")
    if not api_key:
        _mark_generation_failed(job_id, "OPEN_AI_API_KEY not set")
        return

    created_count = 0
    generated_texts = []

    try:
        while created_count < target_count:
            remaining = target_count - created_count
            batch_size = min(BATCH_SIZE, remaining)

            rows = generate_query_batch(
                study_name=study_name,
                description=description,
                batch_size=batch_size,
                already_generated=generated_texts,
                api_key=api_key,
            )

            if not rows:
                log.warning(
                    f"[generation] job {job_id}: batch returned 0 valid rows — retrying once"
                )
                rows = generate_query_batch(
                    study_name=study_name,
                    description=description,
                    batch_size=batch_size,
                    already_generated=generated_texts,
                    api_key=api_key,
                )
                if not rows:
                    log.error(
                        f"[generation] job {job_id}: second attempt also 0 rows — stopping early"
                    )
                    break

            _insert_generated_rows(rows, study_type, organization_id, created_by)
            created_count += len(rows)
            generated_texts.extend(r['query_text'] for r in rows)

            # Update progress incrementally
            with engine.connect() as conn:
                conn.execute(text("""
                    UPDATE soa_query_generation_jobs
                    SET created_count = :cc, updated_at = NOW()
                    WHERE id = :id
                """), {"cc": created_count, "id": job_id})
                conn.commit()

            log.info(f"[generation] job {job_id}: {created_count}/{target_count}")

        # Mark complete
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE soa_query_generation_jobs
                SET status = 'complete', updated_at = NOW()
                WHERE id = :id
            """), {"id": job_id})
            conn.commit()

        log.info(f"[generation] job {job_id} complete: {created_count} queries")

    except Exception as e:
        log.exception(f"[generation] job {job_id} failed")
        _mark_generation_failed(job_id, str(e))


LITE_CREATED_BY = "soa-lite"


def _mark_lite_failed(request_id: int, error: str):
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE soa_lite_requests
            SET status = 'failed',
                error_message = :err,
                updated_at = NOW()
            WHERE id = :id
        """), {"id": request_id, "err": error[:1000]})
        conn.commit()
    log.error(f"[lite] request {request_id} failed: {error}")


def process_lite_requests():
    """
    Polls soa_lite_requests for status='pending', processes one row per
    call — same one-at-a-time, oldest-first semantics as
    process_generation_jobs (avoids OpenAI rate limits and DB contention
    with cycle processing).

    State machine: pending -> generating -> running. The cycle this
    creates is picked up and executed by the existing planned-cycle poll
    unchanged (get_next_planned_cycle/execute_cycle) — running -> complete/
    failed is mirrored onto this row by _sweep_lite_completions once the
    cycle finishes, not written here. Any exception while resolving
    entities, generating queries, or creating the cycle marks this row
    'failed' directly (mirrors _mark_generation_failed).
    """
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT id, token, brand_name, competitor_names
            FROM soa_lite_requests
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT 1
        """)).fetchone()

        if not row:
            return

        request_id, token, brand_name, competitor_names = row

        conn.execute(text("""
            UPDATE soa_lite_requests
            SET status = 'generating', updated_at = NOW()
            WHERE id = :id
        """), {"id": request_id})
        conn.commit()

    log.info(f"[lite] Starting request {request_id} for brand '{brand_name}'")

    # JSON columns normally come back already-decoded (psycopg2 parses
    # json/jsonb natively); defensively handle a driver that returns the
    # raw string instead, same idiom as cycles.py::_row_to_cycle.
    if isinstance(competitor_names, str):
        competitor_names = json.loads(competitor_names)
    competitor_names = competitor_names or []
    token8 = token[:8]
    study_type = f"lite-{token8}"
    cycle_code = f"lite-{token8}"

    try:
        api_key = os.environ.get("OPEN_AI_API_KEY")
        if not api_key:
            raise RuntimeError("OPEN_AI_API_KEY not set")

        from soa_shared.database import session_factory
        from soa_shared.org_helpers import get_or_create_leadgen_org
        from soa_shared.entity_helpers import get_or_create_entity_by_slug
        from soa_shared.cycle_creation import create_cycle_with_comparison_set
        from generation.query_generator import generate_lite_queries

        with session_factory() as session:
            org_id = get_or_create_leadgen_org(session)
            session.commit()

        # b. Resolve entities — upsert-by-slug so repeat submissions of the
        # same brand reuse the existing soa_entities row.
        with engine.begin() as conn:
            brand_entity_id = get_or_create_entity_by_slug(conn, brand_name, "brand")
            competitor_entity_ids = [
                get_or_create_entity_by_slug(conn, name, "brand")
                for name in competitor_names
            ]
            conn.execute(text("""
                UPDATE soa_lite_requests
                SET brand_entity_id = :bid,
                    competitor_entity_ids = :cids,
                    updated_at = NOW()
                WHERE id = :id
            """), {
                "bid":  brand_entity_id,
                "cids": json.dumps(competitor_entity_ids),
                "id":   request_id,
            })

        # c. Generate the fixed 12-query study and insert into soa_queries.
        # _insert_generated_rows' query_code prefixing (first 3 chars up to
        # the first underscore) naturally yields 'LIT' for study_type
        # 'lite-{token8}' — no lite-specific insert logic needed.
        rows = generate_lite_queries(brand_name, competitor_names, api_key)

        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE soa_lite_requests
                SET study_type = :st, updated_at = NOW()
                WHERE id = :id
            """), {"st": study_type, "id": request_id})
            conn.commit()

        _insert_generated_rows(rows, study_type, org_id, LITE_CREATED_BY)

        # d. Create the cycle + comparison set (brand=M001 primary,
        # competitors M002.. competitor) via the helper shared with
        # apps/api/app/routers/cycles.py::create_cycle.
        comparison_set = [
            {"entity_id": brand_entity_id, "comparison_code": "M001", "role": "primary"},
        ] + [
            {"entity_id": eid, "comparison_code": f"M{i + 2:03d}", "role": "competitor"}
            for i, eid in enumerate(competitor_entity_ids)
        ]

        with engine.begin() as conn:
            cycle_id, _ = create_cycle_with_comparison_set(
                conn,
                cycle_code=cycle_code,
                study_type=study_type,
                study_pattern="brand_vs_brand",
                cycle_mode="query",
                truecost_tiers=None,
                total_runs_planned=len(rows),  # 1 platform x 1 run/query
                start_date=datetime.now(timezone.utc).date(),
                platforms=json.dumps(["chatgpt"]),
                runs_per_query=1,
                organization_id=org_id,
                created_by=LITE_CREATED_BY,
                notes=None,
                comparison_set=comparison_set,
            )

            conn.execute(text("""
                UPDATE soa_lite_requests
                SET cycle_id = :cid, status = 'running', updated_at = NOW()
                WHERE id = :id
            """), {"cid": cycle_id, "id": request_id})

        log.info(f"[lite] request {request_id}: cycle {cycle_code} queued (id={cycle_id})")

    except Exception as e:
        log.exception(f"[lite] request {request_id} failed")
        _mark_lite_failed(request_id, str(e))


def _sweep_lite_completions():
    """
    Lite rows in status='running' track their cycle's terminal state —
    the existing planned-cycle poll executes the cycle unchanged, so this
    just mirrors the outcome back onto soa_lite_requests once it lands.
    """
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT lr.id, c.status
            FROM soa_lite_requests lr
            JOIN soa_cycles c ON c.id = lr.cycle_id
            WHERE lr.status = 'running'
              AND c.status IN ('complete', 'failed')
        """)).fetchall()

        for lite_id, cycle_status in rows:
            if cycle_status == 'complete':
                conn.execute(text("""
                    UPDATE soa_lite_requests
                    SET status = 'complete', updated_at = NOW()
                    WHERE id = :id
                """), {"id": lite_id})
            else:
                conn.execute(text("""
                    UPDATE soa_lite_requests
                    SET status = 'failed',
                        error_message = 'Cycle failed during execution.',
                        updated_at = NOW()
                    WHERE id = :id
                """), {"id": lite_id})


def main():
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("SoA Pipeline Worker started")
    log.info(f"Poll interval: {POLL_INTERVAL}s")
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    while True:
        try:
            row = get_next_planned_cycle()

            if row:
                cycle_code     = row[0]
                study_type     = row[1]
                platforms      = row[2]
                runs_per_query = row[3]
                cycle_mode     = row[4] or "query"

                # Fallback for pre-migration cycles with NULL columns
                if cycle_mode != "truecost" and not platforms:
                    log.warning(
                        f"{cycle_code}: platforms is NULL — using default [chatgpt, gemini]"
                    )
                    platforms = ['chatgpt', 'gemini']

                if cycle_mode != "truecost" and not runs_per_query:
                    log.warning(
                        f"{cycle_code}: runs_per_query is NULL — using default 5"
                    )
                    runs_per_query = 5

                log.info(f"Dequeued: {cycle_code} (cycle_mode={cycle_mode})")
                try:
                    asyncio.run(
                        execute_cycle(cycle_code, study_type, platforms, runs_per_query, cycle_mode)
                    )
                except Exception as e:
                    log.exception(f"Cycle {cycle_code} failed: {e}")
                    mark_failed(cycle_code, str(e))
            else:
                log.debug("Queue empty.")

            # Poll generation jobs in same loop iteration — isolated try/except
            # so a generation failure never crashes cycle processing
            try:
                process_generation_jobs()
            except Exception:
                log.exception("[generation] poll iteration failed")

            # Same isolation for SoA Lite: claiming a pending request, and
            # sweeping running requests whose cycle has finished.
            try:
                process_lite_requests()
            except Exception:
                log.exception("[lite] poll iteration failed")

            try:
                _sweep_lite_completions()
            except Exception:
                log.exception("[lite] completion sweep failed")

            if not row:
                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            log.info("Worker stopped.")
            break
        except Exception as e:
            log.exception(f"Unexpected worker error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
