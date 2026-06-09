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
                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            log.info("Worker stopped.")
            break
        except Exception as e:
            log.exception(f"Unexpected worker error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
