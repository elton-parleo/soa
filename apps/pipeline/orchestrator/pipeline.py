"""
PipelineOrchestrator — top-level coordinator for the SoA measurement pipeline.

Chains RunOrchestrator (Stage 1) and CodingOrchestrator (Stage 2) in sequence,
manages cycle state transitions, handles stage failures, and produces a unified
PipelineReport. Does not reimplement any runner or coding logic.
"""
import asyncio
import datetime
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from sqlalchemy import func

import lite_events
import soa_shared.config as config
from soa_shared.database import session_factory
from soa_shared.models.soa_models import SoaCycle, SoaCodedMention, SoaCycleEntity, SoaLiteRequest, SoaQuery, SoaRun
from orchestrator.pipeline_report import PipelineReport
from runners.run_orchestrator import RunOrchestrator
from parser.coding_orchestrator import CodingOrchestrator
from parser.pass2_recode_batch import recode_runs

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Supporting dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RunnerStageResult:
    completed: int
    errors: int
    timeouts: int
    duration_seconds: float
    skipped: bool
    skip_reason: Optional[str]


@dataclass
class CodingStageResult:
    coded: int
    needs_review: int
    validation_errors: int
    api_errors: int
    duration_seconds: float
    input_tokens_total: int
    output_tokens_total: int
    skipped: bool
    skip_reason: Optional[str]


@dataclass
class MetricsStageResult:
    rows_written: int
    duration_seconds: float
    export_path: Optional[str]
    skipped: bool
    skip_reason: Optional[str]


class PipelineStageError(Exception):
    def __init__(self, stage: str, reason: str, is_fatal: bool = True) -> None:
        self.stage = stage
        self.reason = reason
        self.is_fatal = is_fatal
        super().__init__(f"Pipeline stage '{stage}' failed: {reason}")


# ---------------------------------------------------------------------------
# PipelineOrchestrator
# ---------------------------------------------------------------------------

class PipelineOrchestrator:

    def __init__(
        self,
        cycle_code: str,
        study_type: str = "retailer_sephora",
        study_pattern: Optional[str] = None,
        platforms: Optional[List[str]] = None,
        runs_per_query: Optional[int] = None,
        max_concurrent_runner: Optional[int] = None,
        max_concurrent_coder: Optional[int] = None,
        skip_runner: bool = False,
        skip_coding: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.cycle_code = cycle_code
        self.study_type = study_type
        self.study_pattern = study_pattern
        self.platforms = platforms or [
            p.strip() for p in config.SOA_PLATFORMS.split(",") if p.strip()
        ]
        self.runs_per_query = runs_per_query or config.SOA_DEFAULT_RUNS_PER_QUERY
        self.max_concurrent_runner = max_concurrent_runner or config.SOA_MAX_CONCURRENT
        self.max_concurrent_coder = max_concurrent_coder or config.SOA_MAX_CODING_CONCURRENT
        self.skip_runner = skip_runner
        self.skip_coding = skip_coding
        self.dry_run = dry_run

        self.cycle = self._load_or_create_cycle()

        # Part 1 (E1), lite-gated: same zero-cost-for-non-lite pattern as
        # RunOrchestrator._resolve_lite_request_id — a cheap cycle_code
        # prefix check short-circuits before any DB round trip for every
        # non-lite cycle.
        self._lite_request_id = self._resolve_lite_request_id()
        # Part 1 (P3): total soa_price_observations rows pass-2 wrote this
        # run, threaded from _run_stage_coding (where pass-2 executes)
        # into _run_stage_metrics (where the scoring done-event chip is
        # emitted) — the two are separate stage methods on the same
        # instance, called in sequence by run_pipeline().
        self._pass2_observations_written = 0

        # Guard: refuse to rerun a fully complete cycle unless user passed explicit override flags
        if (
            self.cycle.status == "complete"
            and not self.dry_run
            and not self.skip_runner
            and not self.skip_coding
        ):
            skip_c, _ = self._should_skip_coding()
            if skip_c:
                raise ValueError(
                    f"Cycle '{cycle_code}' is fully complete (runner + coding done).\n"
                    "Create a new cycle_code to run again, e.g.:\n"
                    f"  python main.py pipeline --cycle {cycle_code}-v2"
                )
            # Runner done (cycle.status=complete set by RunOrchestrator) but coding incomplete
            logger.info(
                "Cycle %s: runner complete but coding not finished — resuming",
                cycle_code,
            )

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def run_pipeline(self) -> PipelineReport:
        from datetime import timezone
        pipeline_start = datetime.datetime.now(tz=timezone.utc)

        if self.dry_run:
            return self._dry_run_report(pipeline_start)

        # Transition to running
        self._update_cycle_status("running")
        logger.info("Pipeline started for cycle %s", self.cycle_code)

        runner_result: Optional[RunnerStageResult] = None
        coding_result: Optional[CodingStageResult] = None
        metrics_result: Optional[MetricsStageResult] = None
        failure_stage: Optional[str] = None
        failure_reason: Optional[str] = None
        pipeline_status = "complete"

        # Preflight check — verify cycle entities and queries are ready
        try:
            self._preflight_check()
        except PipelineStageError as exc:
            logger.error("Pipeline aborted at preflight: %s", exc.reason)
            self._update_cycle_status("failed")
            now = datetime.datetime.now(tz=datetime.timezone.utc)
            return PipelineReport(
                cycle_code=self.cycle_code,
                pipeline_start=pipeline_start,
                pipeline_end=now,
                total_duration_seconds=(now - pipeline_start).total_seconds(),
                runner_skipped=True, runner_duration_seconds=None,
                runner_completed_runs=None, runner_error_runs=None,
                runner_timeout_runs=None, runner_skip_reason="preflight failed",
                coding_skipped=True, coding_duration_seconds=None,
                coding_coded_runs=None, coding_needs_review=None,
                coding_validation_errors=None, coding_api_errors=None,
                coding_skip_reason="preflight failed",
                pipeline_status="failed",
                failure_stage=exc.stage,
                failure_reason=exc.reason,
                estimated_runner_cost_usd=None,
                estimated_coder_cost_usd=None,
                estimated_total_cost_usd=None,
            )

        # Stage 1 — Runner
        try:
            runner_result = await self._run_stage_runner()
        except PipelineStageError as exc:
            logger.error("Pipeline aborted at runner stage: %s", exc.reason)
            failure_stage = exc.stage
            failure_reason = exc.reason
            pipeline_status = "failed"
            self._update_cycle_status("failed")

        # Stage 2 — Coding
        if pipeline_status != "failed":
            # Reset status to 'running' — RunOrchestrator sets it 'complete' after Stage 1
            self._update_cycle_status("running")
            try:
                coding_result = await self._run_stage_coding()
            except PipelineStageError as exc:
                logger.error("Pipeline aborted at coding stage: %s", exc.reason)
                failure_stage = exc.stage
                failure_reason = exc.reason
                pipeline_status = "failed"
                self._update_cycle_status("failed")

        # Stage 3 — Metrics (runs even if coding was skipped, as long as coded data exists)
        if pipeline_status != "failed":
            metrics_result = await self._run_stage_metrics()

        if pipeline_status != "failed":
            self._update_cycle_status("complete")
            logger.info("Pipeline complete for cycle %s", self.cycle_code)

        pipeline_end = datetime.datetime.now(tz=datetime.timezone.utc)
        total_duration = (pipeline_end - pipeline_start).total_seconds()

        runner_cost, coder_cost = self._estimate_costs(
            runner_result, coding_result
        )

        return PipelineReport(
            cycle_code=self.cycle_code,
            pipeline_start=pipeline_start,
            pipeline_end=pipeline_end,
            total_duration_seconds=total_duration,

            runner_skipped=runner_result.skipped if runner_result else True,
            runner_duration_seconds=runner_result.duration_seconds if runner_result and not runner_result.skipped else None,
            runner_completed_runs=runner_result.completed if runner_result and not runner_result.skipped else None,
            runner_error_runs=runner_result.errors if runner_result and not runner_result.skipped else None,
            runner_timeout_runs=runner_result.timeouts if runner_result and not runner_result.skipped else None,
            runner_skip_reason=runner_result.skip_reason if runner_result else "pipeline aborted",

            coding_skipped=coding_result.skipped if coding_result else True,
            coding_duration_seconds=coding_result.duration_seconds if coding_result and not coding_result.skipped else None,
            coding_coded_runs=coding_result.coded if coding_result and not coding_result.skipped else None,
            coding_needs_review=coding_result.needs_review if coding_result and not coding_result.skipped else None,
            coding_validation_errors=coding_result.validation_errors if coding_result and not coding_result.skipped else None,
            coding_api_errors=coding_result.api_errors if coding_result and not coding_result.skipped else None,
            coding_skip_reason=coding_result.skip_reason if coding_result else "pipeline aborted",

            pipeline_status=pipeline_status,
            failure_stage=failure_stage,
            failure_reason=failure_reason,
            estimated_runner_cost_usd=runner_cost,
            estimated_coder_cost_usd=coder_cost,
            estimated_total_cost_usd=(runner_cost + coder_cost) if runner_cost is not None and coder_cost is not None else None,

            metrics_skipped=metrics_result.skipped if metrics_result else True,
            metrics_duration_seconds=metrics_result.duration_seconds if metrics_result and not metrics_result.skipped else None,
            metrics_rows_written=metrics_result.rows_written if metrics_result and not metrics_result.skipped else None,
            metrics_export_path=metrics_result.export_path if metrics_result and not metrics_result.skipped else None,
            metrics_skip_reason=metrics_result.skip_reason if metrics_result else "pipeline aborted",
        )

    # ------------------------------------------------------------------
    # Skip detection
    # ------------------------------------------------------------------

    def _should_skip_runner(self) -> Tuple[bool, str]:
        if self.skip_runner:
            return True, "skip_runner flag set"

        total_planned = self.cycle.total_runs_planned or 0
        if not total_planned:
            return False, ""

        with session_factory() as session:
            done_count = (
                session.query(SoaRun)
                .filter(
                    SoaRun.cycle_id == self.cycle.id,
                    SoaRun.status.in_(["success", "error"]),
                )
                .count()
            )

        if done_count >= total_planned:
            return True, "all runs already completed"
        return False, ""

    def _should_skip_coding(self) -> Tuple[bool, str]:
        if self.skip_coding:
            return True, "skip_coding flag set"

        with session_factory() as session:
            success_count = (
                session.query(SoaRun)
                .filter(
                    SoaRun.cycle_id == self.cycle.id,
                    SoaRun.status == "success",
                )
                .count()
            )
            if success_count == 0:
                return False, ""

            coded_count = (
                session.query(SoaCodedMention.run_id)
                .join(SoaRun, SoaCodedMention.run_id == SoaRun.id)
                .filter(SoaRun.cycle_id == self.cycle.id)
                .distinct()
                .count()
            )

        if coded_count >= success_count:
            return True, "all runs already coded"
        return False, ""

    # ------------------------------------------------------------------
    # Stage runners
    # ------------------------------------------------------------------

    async def _run_stage_runner(self) -> RunnerStageResult:
        should_skip, reason = self._should_skip_runner()
        if should_skip:
            logger.info("Stage 1 (runner) skipped: %s", reason)
            return RunnerStageResult(
                completed=0, errors=0, timeouts=0,
                duration_seconds=0.0, skipped=True, skip_reason=reason,
            )

        logger.info("Stage 1 (runner) starting for cycle %s", self.cycle_code)
        orchestrator = RunOrchestrator(
            cycle_code=self.cycle_code,
            platforms=self.platforms,
            runs_per_query=self.runs_per_query,
            max_concurrent=self.max_concurrent_runner,
        )
        summary = await orchestrator.run_cycle()

        total = summary.total_planned or 1
        error_rate = (summary.errors + summary.timeouts) / total
        if error_rate > config.SOA_RUNNER_ERROR_ABORT_THRESHOLD:
            raise PipelineStageError(
                stage="runner",
                reason=(
                    f"Error rate {error_rate:.0%} exceeds abort threshold "
                    f"{config.SOA_RUNNER_ERROR_ABORT_THRESHOLD:.0%}. "
                    "Coding aborted to avoid processing bad data."
                ),
                is_fatal=True,
            )

        logger.info(
            "Stage 1 (runner) complete: %d completed, %d errors, %d timeouts",
            summary.completed, summary.errors, summary.timeouts,
        )
        return RunnerStageResult(
            completed=summary.completed,
            errors=summary.errors,
            timeouts=summary.timeouts,
            duration_seconds=summary.duration_seconds,
            skipped=False,
            skip_reason=None,
        )

    async def _run_stage_coding(self) -> CodingStageResult:
        should_skip, reason = self._should_skip_coding()
        if should_skip:
            logger.info("Stage 2 (coding) skipped: %s", reason)
            return CodingStageResult(
                coded=0, needs_review=0, validation_errors=0, api_errors=0,
                duration_seconds=0.0, input_tokens_total=0, output_tokens_total=0,
                skipped=True, skip_reason=reason,
            )

        logger.info("Stage 2 (coding) starting for cycle %s", self.cycle_code)
        if self._lite_request_id is not None:
            lite_events.emit_log(
                self._lite_request_id, lite_events.TASK_SCORING,
                "coding answers — mentions, then price observations…",
            )
        orchestrator = CodingOrchestrator(
            cycle_code=self.cycle_code,
            max_concurrent=self.max_concurrent_coder,
        )
        summary = await orchestrator.code_cycle()

        total_attempted = summary.coded + summary.api_errors + summary.validation_errors
        if total_attempted:
            error_rate = summary.api_errors / total_attempted
            if error_rate > config.SOA_CODER_ERROR_WARN_THRESHOLD:
                logger.warning(
                    "Stage 2 (coding) API error rate %.0f%% exceeds warn threshold %.0f%%."
                    " Partial coding — rerun code-cycle to complete.",
                    error_rate * 100,
                    config.SOA_CODER_ERROR_WARN_THRESHOLD * 100,
                )

        if summary.needs_review_count and summary.coded:
            review_rate = summary.needs_review_count / summary.coded
            if review_rate > 0.20:
                logger.warning(
                    "Stage 2 (coding) needs_review rate %.0f%% — above 20%% threshold.",
                    review_rate * 100,
                )

        logger.info(
            "Stage 2 (coding) complete: %d coded, %d needs review",
            summary.coded, summary.needs_review_count,
        )

        if self._lite_request_id is not None:
            await self._run_pass2_recode()

        return CodingStageResult(
            coded=summary.coded,
            needs_review=summary.needs_review_count,
            validation_errors=summary.validation_errors,
            api_errors=summary.api_errors,
            duration_seconds=summary.duration_seconds,
            input_tokens_total=summary.input_tokens_total,
            output_tokens_total=summary.output_tokens_total,
            skipped=False,
            skip_reason=None,
        )

    async def _run_pass2_recode(self) -> None:
        """
        Part 1 (P1/P2), lite-gated: pass-2 price/citation extraction
        (parser/response_coder_v2.py) for every run this cycle has
        pass-1-coded — not just runs freshly coded THIS call, since a
        resumed cycle's earlier-coded runs need pass-2 too.
        ResponseCoderV2.code_run's own soa_pass2_coding_log sentinel
        check makes calling it on an already-processed run a cheap,
        idempotent no-op, so re-scanning the full coded set on every
        resume is safe.

        Joins LITE_QUERY_CONCURRENCY — not max_concurrent_coder — since
        this runs AFTER pass-1 coding is done and isn't latency-critical;
        it must never compete with answer generation for API headroom.
        Cost note (P5): adds ~one coding call per answered query
        (~LITE_QUERY_COUNT/audit), so a lite audit's total OpenAI call
        count roughly doubles (~24 -> ~52). Daily rate limits are
        unchanged this stage — see public_lite.py's RATE_LIMIT_* — flag
        for a deliberate review if audit volume grows.

        Never raises: a bug here (or in recode_runs/ResponseCoderV2,
        which already isolate per-response failures) must never fail
        Stage 2 or the pipeline — pass-2 is enrichment, not on the
        critical path to a report existing at all.
        """
        try:
            with session_factory() as session:
                run_ids = [
                    row[0] for row in session.query(SoaCodedMention.run_id)
                    .join(SoaRun, SoaRun.id == SoaCodedMention.run_id)
                    .filter(SoaRun.cycle_id == self.cycle.id)
                    .distinct()
                    .all()
                ]
            if not run_ids:
                return

            summary = await recode_runs(run_ids, concurrency=config.LITE_QUERY_CONCURRENCY)
            self._pass2_observations_written = sum(r.observations_written for r in summary.results)
            logger.info(
                "Stage 2b (pass-2 recode) complete for cycle %s: %d/%d succeeded, %d observations written",
                self.cycle_code, summary.succeeded, summary.total, self._pass2_observations_written,
            )
        except Exception:
            logger.exception("Stage 2b (pass-2 recode) failed unexpectedly for cycle %s", self.cycle_code)

    async def _run_stage_metrics(self) -> MetricsStageResult:
        """
        Stage 3: compute metrics from coded data and write to soa_metrics_results.
        MetricsOrchestrator is synchronous — run in a thread executor so it
        doesn't block the event loop.
        """
        from metrics.metrics_orchestrator import MetricsOrchestrator

        logger.info("Stage 3 (metrics) starting for cycle %s", self.cycle_code)

        # Check if there is any coded data; if not, skip gracefully
        from sqlalchemy import text
        from soa_shared.database import engine
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT COUNT(*) FROM soa_coded_mentions cm
                    JOIN soa_runs r ON r.id = cm.run_id
                    WHERE r.cycle_id = :cid
                """),
                {"cid": self.cycle.id},
            ).fetchone()
        coded_count = int(row[0] or 0) if row else 0

        if coded_count == 0:
            reason = "no coded data available"
            logger.info("Stage 3 (metrics) skipped: %s", reason)
            return MetricsStageResult(
                rows_written=0,
                duration_seconds=0.0,
                export_path=None,
                skipped=True,
                skip_reason=reason,
            )

        orch = MetricsOrchestrator(
            cycle_code=self.cycle_code,
            export=True,
        )

        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(None, orch.run_metrics)

        logger.info(
            "Stage 3 (metrics) complete: %d rows written in %.1fs",
            summary.total_rows_written,
            summary.duration_seconds,
        )

        # Reconstruct export path for the report
        import soa_shared.config as cfg
        import os
        export_path = os.path.join(
            cfg.SOA_EXPORTS_DIR, f"soa_metrics_{self.cycle_code}.xlsx"
        )

        if self._lite_request_id is not None:
            # Part 1 (P3): names the pass-2 yield when there is one —
            # never a chip claiming "0 price observations" when pass-2
            # simply never ran (e.g. a non-lite path or a skipped stage).
            chips = (
                [f"{self._pass2_observations_written} price observations"]
                if self._pass2_observations_written > 0 else None
            )
            lite_events.emit_done(
                self._lite_request_id, lite_events.TASK_SCORING,
                "Scored across Visibility, Accessibility, and True Value",
                chips=chips,
            )

        return MetricsStageResult(
            rows_written=summary.total_rows_written,
            duration_seconds=summary.duration_seconds,
            export_path=export_path if os.path.exists(export_path) else None,
            skipped=False,
            skip_reason=None,
        )

    # ------------------------------------------------------------------
    # Dry run
    # ------------------------------------------------------------------

    def _dry_run_report(self, pipeline_start: datetime.datetime) -> PipelineReport:
        with session_factory() as session:
            active_q = (
                session.query(SoaQuery)
                .filter_by(status="Active", study_type=self.cycle.study_type)
                .count()
            )

        total_calls = active_q * len(self.platforms) * self.runs_per_query
        total_coded = total_calls  # all success runs coded

        # Rough cost estimate — pro-rata across platforms
        n_platforms = len(self.platforms)
        per_platform = (total_calls // n_platforms) if n_platforms > 1 else total_calls
        openai_runs      = per_platform if "chatgpt"    in self.platforms else 0
        perplexity_runs  = per_platform if "perplexity" in self.platforms else 0
        gemini_runs      = per_platform if "gemini"     in self.platforms else 0
        claude_runs      = per_platform if "claude"     in self.platforms else 0

        runner_cost = (
            openai_runs     * 1500 * 0.000005  + openai_runs     * 800 * 0.000030
            + perplexity_runs * 1500 * 0.000001  + perplexity_runs * 800 * 0.000001
            + gemini_runs     * 1500 * 0.00000015 + gemini_runs     * 800 * 0.0000006
            + claude_runs     * 800  * 0.000003   + claude_runs     * 600 * 0.000015
        )
        coder_cost = total_coded * 1500 * 0.0000002 + total_coded * 300 * 0.00000125

        skip_r, skip_r_reason = self._should_skip_runner()
        skip_c, skip_c_reason = self._should_skip_coding()

        print("\n[DRY RUN] — no API calls will be made, no data will be written\n")
        print(f"  Cycle:           {self.cycle_code}")
        print(f"  Cycle status:    {self.cycle.status}")
        print(f"  Active queries:  {active_q}")
        print(f"  Platforms:       {', '.join(self.platforms)}")
        print(f"  Runs per query:  {self.runs_per_query}")
        print(f"  Total API calls: {total_calls}")
        print(f"  Stage 1 (runner): {'SKIP — ' + skip_r_reason if skip_r else 'would run'}")
        print(f"  Stage 2 (coding): {'SKIP — ' + skip_c_reason if skip_c else 'would run'}")
        print(f"  Stage 3 (metrics): would run")
        print(f"  Est. runner cost: ~${runner_cost:.2f}")
        print(f"  Est. coder cost:  ~${coder_cost:.2f}")
        print(f"  Est. total cost:  ~${runner_cost + coder_cost:.2f}\n")

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        return PipelineReport(
            cycle_code=self.cycle_code,
            pipeline_start=pipeline_start,
            pipeline_end=now,
            total_duration_seconds=0.0,
            runner_skipped=True,
            runner_duration_seconds=None,
            runner_completed_runs=None,
            runner_error_runs=None,
            runner_timeout_runs=None,
            runner_skip_reason="dry_run",
            coding_skipped=True,
            coding_duration_seconds=None,
            coding_coded_runs=None,
            coding_needs_review=None,
            coding_validation_errors=None,
            coding_api_errors=None,
            coding_skip_reason="dry_run",
            pipeline_status="complete",
            failure_stage=None,
            failure_reason=None,
            estimated_runner_cost_usd=runner_cost,
            estimated_coder_cost_usd=coder_cost,
            estimated_total_cost_usd=runner_cost + coder_cost,
        )

    # ------------------------------------------------------------------
    # Cost estimation
    # ------------------------------------------------------------------

    def _estimate_costs(
        self,
        runner_result: Optional[RunnerStageResult],
        coding_result: Optional[CodingStageResult],
    ) -> Tuple[Optional[float], Optional[float]]:
        with session_factory() as session:
            platform_counts = dict(
                session.query(SoaRun.platform, func.count(SoaRun.id))
                .filter(
                    SoaRun.cycle_id == self.cycle.id,
                    SoaRun.status == "success",
                )
                .group_by(SoaRun.platform)
                .all()
            )

        openai_runs     = platform_counts.get("chatgpt",    0)
        perplexity_runs = platform_counts.get("perplexity", 0)
        gemini_runs     = platform_counts.get("gemini",     0)
        claude_runs     = platform_counts.get("claude",     0)

        # Per-run cost estimates (input_tokens * rate + output_tokens * rate)
        # OpenAI gpt-5.5:          $5/M input,  $30/M output
        # Perplexity sonar-large:  $1/M input,  $1/M output
        # Gemini 2.5 flash:        $0.15/M input, $0.60/M output
        # Claude Sonnet 4.6:       $3/M input,  $15/M output
        runner_cost = (
            openai_runs     * 1500 * 0.000005  + openai_runs     * 800 * 0.000030
            + perplexity_runs * 1500 * 0.000001  + perplexity_runs * 800 * 0.000001
            + gemini_runs     * 1500 * 0.00000015 + gemini_runs     * 800 * 0.0000006
            + claude_runs     * 800  * 0.000003   + claude_runs     * 600 * 0.000015
        )

        coded_runs = coding_result.coded if coding_result and not coding_result.skipped else 0
        if coding_result and coding_result.skipped:
            # Count from DB for already-coded cycles
            with session_factory() as session:
                coded_runs = (
                    session.query(SoaCodedMention.run_id)
                    .join(SoaRun, SoaCodedMention.run_id == SoaRun.id)
                    .filter(SoaRun.cycle_id == self.cycle.id)
                    .distinct()
                    .count()
                )

        coder_cost = coded_runs * 1500 * 0.0000002 + coded_runs * 300 * 0.00000125

        return runner_cost, coder_cost

    # ------------------------------------------------------------------
    # Cycle management
    # ------------------------------------------------------------------

    def _preflight_check(self) -> None:
        """Verifies all prerequisites before running any API calls."""
        with session_factory() as session:
            entity_count = (
                session.query(SoaCycleEntity)
                .filter_by(cycle_id=self.cycle.id)
                .count()
            )
        if entity_count == 0:
            raise PipelineStageError(
                stage="preflight",
                reason=(
                    f"No entities configured for cycle '{self.cycle_code}'. "
                    "Add entries to soa_cycle_entities before running."
                ),
                is_fatal=True,
            )

        with session_factory() as session:
            query_count = (
                session.query(SoaQuery)
                .filter_by(status="Active", study_type=self.cycle.study_type)
                .count()
            )
        if query_count == 0:
            raise PipelineStageError(
                stage="preflight",
                reason=(
                    f"No Active queries found for study_type='{self.cycle.study_type}'. "
                    "Seed queries before running."
                ),
                is_fatal=True,
            )

        VALID_PATTERNS = {
            "retailer",
            "brand_at_retail",
            "brand_vs_brand",
        }

        with session_factory() as session:
            patterns = {
                row[0]
                for row in session.query(SoaQuery.study_pattern)
                .filter_by(study_type=self.cycle.study_type, status="Active")
                .distinct()
                .all()
            }

        invalid = patterns - VALID_PATTERNS
        if invalid:
            raise PipelineStageError(
                stage="preflight",
                reason=(
                    f"Queries contain unrecognised "
                    f"study_pattern values: "
                    f"{invalid}. "
                    f"Valid values are: "
                    f"{VALID_PATTERNS}"
                ),
                is_fatal=True,
            )

        # Mixed patterns are valid — log info only
        if len(patterns) > 1:
            logger.info(
                f"Cycle '{self.cycle_code}' has "
                f"mixed study_pattern values: "
                f"{patterns}. Coding prompt rubric "
                f"will be set per query at coding "
                f"time, not per cycle."
            )
        elif len(patterns) == 1:
            logger.info(
                f"Cycle '{self.cycle_code}' "
                f"study_pattern: "
                f"'{list(patterns)[0]}'"
            )

    def _load_or_create_cycle(self) -> SoaCycle:
        with session_factory() as session:
            cycle = (
                session.query(SoaCycle)
                .filter(SoaCycle.cycle_code == self.cycle_code)
                .first()
            )
            if cycle is None:
                active_q = (
                    session.query(SoaQuery)
                    .filter_by(status="Active", study_type=self.study_type)
                    .count()
                )
                total_planned = active_q * len(self.platforms) * self.runs_per_query

                # Auto-detect study_pattern from the query library
                pattern_rows = (
                    session.query(SoaQuery.study_pattern)
                    .filter_by(study_type=self.study_type, status="Active")
                    .distinct()
                    .all()
                )
                detected_patterns = {
                    row[0] for row in pattern_rows if row[0] is not None
                }

                if len(detected_patterns) == 0:
                    # No queries found yet — use passed arg or fall back to 'retailer'
                    resolved_pattern = self.study_pattern or "retailer"
                elif len(detected_patterns) == 1:
                    # All queries share one pattern
                    resolved_pattern = list(detected_patterns)[0]
                    if (
                        self.study_pattern
                        and self.study_pattern != "mixed"
                        and self.study_pattern != resolved_pattern
                    ):
                        logger.warning(
                            f"--study-pattern='{self.study_pattern}' passed but "
                            f"query library has pattern '{resolved_pattern}'. "
                            f"Using detected value."
                        )
                else:
                    # Multiple patterns in query library
                    resolved_pattern = "mixed"
                    logger.info(
                        f"Auto-detected study_pattern='mixed' for study_type="
                        f"'{self.study_type}' "
                        f"(patterns found: {detected_patterns})"
                    )

                cycle = SoaCycle(
                    cycle_code=self.cycle_code,
                    start_date=datetime.date.today(),
                    total_runs_planned=total_planned,
                    status="planned",
                    study_type=self.study_type,
                    study_pattern=resolved_pattern,
                )
                session.add(cycle)
                session.commit()
                logger.info(
                    "Created cycle %s study_type=%s study_pattern=%s (planned %d runs)",
                    self.cycle_code, self.study_type, resolved_pattern, total_planned,
                )
            else:
                # Verify study_type match for existing cycle
                if cycle.study_type != self.study_type:
                    raise ValueError(
                        f"Cycle '{self.cycle_code}' exists with study_type="
                        f"'{cycle.study_type}' but '{self.study_type}' was passed. "
                        "Use the correct study_type or create a new cycle_code."
                    )
                # study_pattern mismatch is only an error when the caller explicitly
                # passed a non-None value that conflicts with the stored pattern
                if (
                    self.study_pattern is not None
                    and cycle.study_pattern != self.study_pattern
                ):
                    raise ValueError(
                        f"Cycle '{self.cycle_code}' exists with study_pattern="
                        f"'{cycle.study_pattern}' but '{self.study_pattern}' was passed."
                    )
            session.expunge(cycle)
        return cycle

    def _resolve_lite_request_id(self) -> Optional[int]:
        if not self.cycle_code.startswith("lite-"):
            return None
        with session_factory() as session:
            row = (
                session.query(SoaLiteRequest.id)
                .filter(SoaLiteRequest.cycle_id == self.cycle.id)
                .first()
            )
            return row[0] if row else None

    def _update_cycle_status(self, status: str) -> None:
        try:
            with session_factory() as session:
                cycle = session.get(SoaCycle, self.cycle.id)
                if cycle:
                    cycle.status = status
                    session.commit()
                    logger.info(
                        "Cycle %s status → %s", self.cycle_code, status
                    )
        except Exception as exc:
            logger.error(
                "Failed to update cycle %s status to %s: %s",
                self.cycle_code, status, exc,
            )
