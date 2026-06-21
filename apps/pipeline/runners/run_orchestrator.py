"""
RunOrchestrator — manages the complete run loop for a measurement cycle.

Responsibilities:
  - Load the cycle and all active queries from the database
  - Build the full (query × platform × run_number) work list
  - Skip already-completed runs (resume support)
  - Execute remaining runs with asyncio.Semaphore(max_concurrent)
  - Apply a 2-second inter-run gap between repetitions of the same
    (query, platform) slot to prevent correlated variance
  - Write each result to soa_runs in its own isolated session
  - Update soa_cycles.completed_runs, status, and end_date
  - Return a CycleSummary
"""
import asyncio
import datetime
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import soa_shared.config as config
from soa_shared.database import session_factory
from soa_shared.models.soa_models import SoaCycle, SoaQuery, SoaRun
from runners.base_runner import BasePlatformRunner
from runners.claude_runner import ClaudeRunner
from runners.cycle_summary import CycleSummary
from runners.gemini_runner import GeminiRunner
from runners.gemini_grounded_runner import GeminiGroundedRunner
from runners.openai_runner import OpenAIRunner
from runners.perplexity_runner import PerplexityRunner
from runners.platform_response import PlatformResponse

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    status: str  # 'success', 'error', 'timeout', 'skipped'
    skip_reason: Optional[str] = None


_RUNNER_CLASSES: Dict[str, type] = {
    "chatgpt": OpenAIRunner,
    "perplexity": PerplexityRunner,
    "gemini": GeminiRunner,
    "claude": ClaudeRunner,
}

# Per-platform max concurrent connections (claude=1 to avoid 429 rate-limit)
_PLATFORM_MAX_CONCURRENT: Dict[str, int] = {
    "chatgpt":    config.SOA_OPENAI_MAX_CONCURRENT,
    "perplexity": config.SOA_PERPLEXITY_MAX_CONCURRENT,
    "gemini":     config.SOA_GEMINI_MAX_CONCURRENT,
    "claude":     config.SOA_CLAUDE_MAX_CONCURRENT,
}

# Additive, flagged: "gemini_grounded" only becomes a valid/runnable platform
# when ENABLE_GEMINI_GROUNDED is set. With the flag off, requesting it raises
# the same "Unknown platforms" error as before this runner existed.
if config.ENABLE_GEMINI_GROUNDED:
    _RUNNER_CLASSES["gemini_grounded"] = GeminiGroundedRunner
    _PLATFORM_MAX_CONCURRENT["gemini_grounded"] = config.SOA_GEMINI_MAX_CONCURRENT

# Per-platform inter-run delays (claude needs a wider gap to avoid burst limits)
_PLATFORM_INTER_RUN_DELAY: Dict[str, float] = {
    "claude": config.SOA_CLAUDE_INTER_RUN_DELAY,
}


class RunOrchestrator:

    def __init__(
        self,
        cycle_code: str,
        platforms: Optional[List[str]] = None,
        runs_per_query: int = None,
        max_concurrent: int = None,
    ):
        self.cycle_code = cycle_code
        self.platforms = platforms or ["chatgpt", "perplexity", "gemini", "claude"]
        self.runs_per_query = runs_per_query or config.SOA_DEFAULT_RUNS_PER_QUERY
        self.max_concurrent = max_concurrent or config.SOA_MAX_CONCURRENT

        # Validate platforms
        unknown = set(self.platforms) - set(_RUNNER_CLASSES)
        if unknown:
            raise ValueError(f"Unknown platforms: {unknown}. Valid: {set(_RUNNER_CLASSES)}")

        # Load cycle
        with session_factory() as session:
            self.cycle = (
                session.query(SoaCycle)
                .filter(SoaCycle.cycle_code == cycle_code)
                .first()
            )
            if self.cycle is None:
                raise ValueError(f"Cycle '{cycle_code}' not found in soa_cycles.")
            session.expunge(self.cycle)

        # Validate prerequisites before any API calls
        self._validate_prerequisites()

        # Instantiate one runner per requested platform
        self.runners: Dict[str, BasePlatformRunner] = {
            p: _RUNNER_CLASSES[p]() for p in self.platforms
        }

    def _validate_prerequisites(self) -> None:
        from soa_shared.models.soa_models import SoaCycleEntity
        with session_factory() as session:
            entity_count = (
                session.query(SoaCycleEntity)
                .filter_by(cycle_id=self.cycle.id)
                .count()
            )
        if entity_count == 0:
            raise ValueError(
                f"No entities configured for cycle '{self.cycle_code}'. "
                "Populate soa_cycle_entities before running."
            )

        with session_factory() as session:
            query_count = (
                session.query(SoaQuery)
                .filter_by(status="Active", study_type=self.cycle.study_type)
                .count()
            )
        if query_count == 0:
            raise ValueError(
                f"No Active queries found for study_type='{self.cycle.study_type}'. "
                "Seed queries before running."
            )

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def run_cycle(self) -> CycleSummary:
        t_start = time.monotonic()

        # 1. Load active queries filtered by study_type
        with session_factory() as session:
            queries: List[SoaQuery] = (
                session.query(SoaQuery)
                .filter(
                    SoaQuery.status == "Active",
                    SoaQuery.study_type == self.cycle.study_type,
                )
                .order_by(SoaQuery.id)
                .all()
            )
            for q in queries:
                session.expunge(q)

        if not queries:
            logger.warning("No active queries found in soa_queries.")

        # 2. Build full work list
        work_items: List[Tuple[SoaQuery, str, int]] = [
            (query, platform, run_num)
            for query in queries
            for platform in self.platforms
            for run_num in range(1, self.runs_per_query + 1)
        ]
        total_planned = len(work_items)

        # 3. Filter already-completed runs
        with session_factory() as session:
            done_keys = {
                (row.query_id, row.platform, row.run_number)
                for row in session.query(
                    SoaRun.query_id, SoaRun.platform, SoaRun.run_number
                )
                .filter(
                    SoaRun.cycle_id == self.cycle.id,
                    SoaRun.status == "success",
                )
                .all()
            }

        pending = [
            item for item in work_items
            if (item[0].id, item[1], item[2]) not in done_keys
        ]
        skipped = total_planned - len(pending)

        logger.info(
            "Cycle %s: %d total, %d to run, %d already done",
            self.cycle_code, total_planned, len(pending), skipped,
        )

        # 4-6. Execute with per-platform semaphores + inter-run delay
        counters = {"completed": 0, "errors": 0, "timeouts": 0}
        first_run_done = False

        # One semaphore per platform — claude=1 to avoid concurrent 429s
        sems: Dict[str, asyncio.Semaphore] = {
            p: asyncio.Semaphore(
                _PLATFORM_MAX_CONCURRENT.get(p, self.max_concurrent)
            )
            for p in self.platforms
        }

        logger.info(
            "Cycle %s: semaphore limits — %s",
            self.cycle_code,
            {p: _PLATFORM_MAX_CONCURRENT.get(p, self.max_concurrent) for p in self.platforms},
        )

        # Group pending by (query_id, platform) to apply inter-run delay
        # between repetitions of the same slot
        slot_last_run: Dict[Tuple[int, str], float] = {}

        async def _run_one(item: Tuple[SoaQuery, str, int]) -> None:
            nonlocal first_run_done
            query, platform, run_num = item
            slot_key = (query.id, platform)
            inter_run_delay = _PLATFORM_INTER_RUN_DELAY.get(
                platform, config.SOA_DEFAULT_INTER_RUN_DELAY
            )

            async with sems[platform]:
                # Apply inter-run delay if this (query, platform) ran recently
                last = slot_last_run.get(slot_key, 0.0)
                gap = time.monotonic() - last
                if last and gap < inter_run_delay:
                    await asyncio.sleep(inter_run_delay - gap)

                result = await self._execute_single_run(query, platform, run_num)
                slot_last_run[slot_key] = time.monotonic()

                if result.status == "success":
                    counters["completed"] += 1
                    # 7. Update cycle status after first successful run
                    if not first_run_done:
                        first_run_done = True
                        self._update_cycle_status("running")
                elif result.status == "timeout":
                    counters["timeouts"] += 1
                elif result.status == "error":
                    counters["errors"] += 1
                # 'skipped' does not update any counter — already counted in pre-filter

        await asyncio.gather(*[_run_one(item) for item in pending])

        # 8. Finalize cycle
        self._finalize_cycle(counters["completed"])

        duration = time.monotonic() - t_start

        # Collect Gemini 503 recovery stats from the runner (if present)
        gemini_runner = self.runners.get("gemini")
        gemini_503_count = getattr(gemini_runner, "gemini_503_count", 0)
        gemini_503_fallback_successes = getattr(
            gemini_runner, "gemini_503_fallback_successes", 0
        )
        if gemini_503_count > 0:
            logger.info(
                "Cycle %s: Gemini 503s encountered=%d, recovered via fallback=%d",
                self.cycle_code, gemini_503_count, gemini_503_fallback_successes,
            )

        summary = CycleSummary(
            cycle_code=self.cycle_code,
            total_planned=total_planned,
            completed=counters["completed"],
            skipped_already_done=skipped,
            errors=counters["errors"],
            timeouts=counters["timeouts"],
            duration_seconds=duration,
            platforms_used=self.platforms,
            queries_run=len({item[0].id for item in pending}),
            gemini_503_count=gemini_503_count,
            gemini_503_fallback_successes=gemini_503_fallback_successes,
        )
        return summary

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _execute_single_run(
        self,
        query: SoaQuery,
        platform: str,
        run_number: int,
    ) -> RunResult:

        # ── STEP 1: Check for existing run ──
        # Do this BEFORE any API call.
        # Never make an API call if the run already has a success record.
        existing = self._get_existing_run(
            query_id=query.id,
            platform=platform,
            run_number=run_number,
        )

        if existing is not None:
            if existing.status == "success":
                logger.debug(
                    "Skipping %s/%s/%s/%d: already completed successfully",
                    self.cycle_code, query.query_code, platform, run_number,
                )
                return RunResult(status="skipped", skip_reason="already_success")
            elif existing.status in ("error", "timeout", "pending"):
                logger.info(
                    "Retrying %s/%s/%s/%d: previous attempt had status=%s",
                    self.cycle_code, query.query_code, platform, run_number,
                    existing.status,
                )
                # Fall through to API call below.
                # _upsert_run() will UPDATE the existing row, not INSERT.

        # ── STEP 2: Make the API call ──
        # Only reached if no success record exists.
        runner = self.runners[platform]
        response: PlatformResponse = await runner.run(query.query_text)

        # ── STEP 3: Write to database ──
        # Use upsert — update if row exists (for retries), insert if new.
        # UniqueViolation cannot occur here because _execute_single_run()
        # checks for existing records before calling the API, and
        # _upsert_run() uses update-or-insert logic. If a DB error occurs
        # here it is a genuine unexpected failure and should propagate.
        self._upsert_run(
            existing=existing,
            query=query,
            platform=platform,
            run_number=run_number,
            response=response,
        )

        logger.info(
            "Run %s/%s/%s/%d: %s in %dms",
            self.cycle_code, query.query_code, platform, run_number,
            response.status, response.latency_ms,
        )

        return RunResult(status=response.status)

    def _get_existing_run(
        self,
        query_id: int,
        platform: str,
        run_number: int,
    ) -> Optional[SoaRun]:
        """
        Returns the existing SoaRun record for this slot if one exists, or None.
        The returned object is expunged so it remains accessible after session close.
        """
        with session_factory() as session:
            run = session.query(SoaRun).filter_by(
                cycle_id=self.cycle.id,
                query_id=query_id,
                platform=platform,
                run_number=run_number,
            ).first()
            if run is not None:
                session.expunge(run)
            return run

    def _upsert_run(
        self,
        existing: Optional[SoaRun],
        query: SoaQuery,
        platform: str,
        run_number: int,
        response: PlatformResponse,
    ) -> None:
        """
        Writes the run result to soa_runs.
        If a row already exists (e.g. previous error/timeout being retried),
        updates it in place. If no row exists, inserts. Never raises UniqueViolation.
        """
        with session_factory() as session:
            if existing is not None:
                # UPDATE the existing row
                run = session.query(SoaRun).filter_by(id=existing.id).first()
                if run is None:
                    # Row was deleted between check and write — insert instead
                    run = SoaRun(
                        cycle_id=self.cycle.id,
                        query_id=query.id,
                        platform=platform,
                        run_number=run_number,
                    )
                    session.add(run)
            else:
                # INSERT new row
                run = SoaRun(
                    cycle_id=self.cycle.id,
                    query_id=query.id,
                    platform=platform,
                    run_number=run_number,
                )
                session.add(run)

            # Set all result fields
            run.raw_response = response.response_text
            run.response_tokens = response.completion_tokens
            run.latency_ms = response.latency_ms
            run.status = response.status
            run.error_message = response.error
            run.search_triggered = response.search_triggered
            run.retrieved_sources = response.retrieved_sources

            session.commit()

    def _update_cycle_status(self, status: str) -> None:
        try:
            with session_factory() as session:
                cycle = session.get(SoaCycle, self.cycle.id)
                if cycle:
                    cycle.status = status
                    session.commit()
        except Exception as exc:
            logger.error("Failed to update cycle status to %s: %s", status, exc)

    def _finalize_cycle(self, completed_count: int) -> None:
        try:
            with session_factory() as session:
                cycle = session.get(SoaCycle, self.cycle.id)
                if cycle:
                    cycle.status = "complete"
                    cycle.end_date = datetime.date.today()
                    cycle.completed_runs = completed_count
                    session.commit()
        except Exception as exc:
            logger.error("Failed to finalize cycle: %s", exc)
