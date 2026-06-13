"""
Pipeline polling worker.

Railway runs this as a continuously running process. It polls soa_cycles
every 30 seconds for rows with status = 'planned' and executes each one
through PipelineOrchestrator.

The API (Vercel) writes status='planned' when a user launches a cycle in
the UI. This worker picks it up and runs it. The two services communicate
only through the database — no direct coupling.
"""
import os
import sys
import time
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
    Returns a Row with (cycle_code, study_type, platforms, runs_per_query) or None.
    """
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT
              cycle_code,
              study_type,
              platforms,
              runs_per_query
            FROM soa_cycles
            WHERE status = 'planned'
            ORDER BY created_at ASC
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


async def execute_cycle(
    cycle_code: str,
    study_type: str,
    platforms: list,
    runs_per_query: int,
):
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

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        _mark_generation_failed(job_id, "OPENAI_API_KEY not set")
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

                # Fallback for pre-migration cycles with NULL columns
                if not platforms:
                    log.warning(
                        f"{cycle_code}: platforms is NULL — using default [chatgpt, gemini]"
                    )
                    platforms = ['chatgpt', 'gemini']

                if not runs_per_query:
                    log.warning(
                        f"{cycle_code}: runs_per_query is NULL — using default 5"
                    )
                    runs_per_query = 5

                log.info(f"Dequeued: {cycle_code}")
                try:
                    asyncio.run(execute_cycle(cycle_code, study_type, platforms, runs_per_query))
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
