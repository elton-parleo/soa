"""
CodingOrchestrator — processes all uncoded success runs for a cycle.
"""
import asyncio
import logging
import time
from dataclasses import dataclass

from soa_shared.database import session_factory
from soa_shared.models.soa_models import SoaCycle, SoaCodedMention, SoaCycleEntity, SoaRun
from parser.coding_client import CodingClient
from parser.response_coder import CodeRunResult, ResponseCoder
from parser.validator import CodingValidator

logger = logging.getLogger(__name__)

_CODING_MODEL = "gpt-5.4-nano-2026-03-17"
_INPUT_COST_PER_TOKEN = 0.0000002
_OUTPUT_COST_PER_TOKEN = 0.00000125


@dataclass
class CodingSummary:
    cycle_code: str
    total_runs_found: int
    coded: int
    skipped_already_coded: int
    skipped_not_success: int
    validation_errors: int
    api_errors: int
    needs_review_count: int
    duration_seconds: float
    input_tokens_total: int = 0
    output_tokens_total: int = 0

    def print_summary(self) -> None:
        est_cost = (
            self.input_tokens_total * _INPUT_COST_PER_TOKEN
            + self.output_tokens_total * _OUTPUT_COST_PER_TOKEN
        )
        minutes = int(self.duration_seconds // 60)
        seconds = int(self.duration_seconds % 60)
        duration_str = f"{minutes}m {seconds:02d}s"

        print("\n" + "━" * 34)
        print(f"Coding Cycle {self.cycle_code} Complete")
        print("━" * 34)
        print(f"Model:           {_CODING_MODEL}")
        print(f"Runs found:      {self.total_runs_found:>10}")
        print(f"Coded:           {self.coded:>10}")
        print(f"Already coded:   {self.skipped_already_coded:>10}")
        print(f"Skipped (no success): {self.skipped_not_success:>5}")
        print(f"Validation errors: {self.validation_errors:>7}")
        print(f"API errors:      {self.api_errors:>10}")
        print(f"Needs review:    {self.needs_review_count:>10}")
        print(f"Est. cost:       ${est_cost:>9.2f}")
        print(f"Duration:        {duration_str:>10}")
        print("━" * 34 + "\n")


class CodingOrchestrator:

    def __init__(self, cycle_code: str, max_concurrent: int = 5) -> None:
        self.cycle_code = cycle_code
        self.max_concurrent = max_concurrent

        # Load cycle
        with session_factory() as session:
            cycle = (
                session.query(SoaCycle)
                .filter(SoaCycle.cycle_code == cycle_code)
                .first()
            )
            if cycle is None:
                raise ValueError(f"Cycle '{cycle_code}' not found in soa_cycles.")
            session.expunge(cycle)
        self.cycle = cycle

        # Verify cycle entities are configured before processing any runs
        with session_factory() as session:
            entity_count = (
                session.query(SoaCycleEntity)
                .filter_by(cycle_id=self.cycle.id)
                .count()
            )
        if entity_count == 0:
            raise ValueError(
                f"No entities configured for cycle '{cycle_code}'. "
                "Populate soa_cycle_entities before running coding."
            )

        self._client = CodingClient()
        self._validator = CodingValidator()
        self._coder = ResponseCoder(self._client, self._validator)

    async def code_cycle(self) -> CodingSummary:
        t_start = time.monotonic()

        # 1. Load all success runs for this cycle
        with session_factory() as session:
            runs = (
                session.query(SoaRun)
                .filter(
                    SoaRun.cycle_id == self.cycle.id,
                    SoaRun.status == "success",
                )
                .order_by(SoaRun.id)
                .all()
            )
            for r in runs:
                session.expunge(r)

        total_runs = len(runs)

        # 2. Batch idempotency check — which runs already have coded mentions
        with session_factory() as session:
            coded_run_ids = {
                row[0]
                for row in session.query(SoaCodedMention.run_id)
                .filter(SoaCodedMention.run_id.in_([r.id for r in runs]))
                .distinct()
                .all()
            }

        to_code = [r for r in runs if r.id not in coded_run_ids]
        already_coded_count = len(coded_run_ids)

        logger.info(
            "Cycle %s: %d total success runs, %d to code, %d already coded",
            self.cycle_code, total_runs, len(to_code), already_coded_count,
        )

        # 3. Process with semaphore
        counters = {
            "coded": 0,
            "skipped_not_success": 0,
            "validation_errors": 0,
            "api_errors": 0,
            "needs_review": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
        sem = asyncio.Semaphore(self.max_concurrent)

        async def _code_one(run: SoaRun) -> None:
            async with sem:
                result: CodeRunResult = await self._coder.code_run(run.id)

            if result.status == "success":
                counters["coded"] += 1
                if result.needs_review:
                    counters["needs_review"] += 1
                counters["input_tokens"] += result.input_tokens
                counters["output_tokens"] += result.output_tokens
            elif result.status == "validation_error":
                counters["validation_errors"] += 1
            elif result.status == "api_error":
                counters["api_errors"] += 1
            elif result.status.startswith("skipped"):
                counters["skipped_not_success"] += 1

        await asyncio.gather(*[_code_one(r) for r in to_code])

        duration = time.monotonic() - t_start

        return CodingSummary(
            cycle_code=self.cycle_code,
            total_runs_found=total_runs,
            coded=counters["coded"],
            skipped_already_coded=already_coded_count,
            skipped_not_success=counters["skipped_not_success"],
            validation_errors=counters["validation_errors"],
            api_errors=counters["api_errors"],
            needs_review_count=counters["needs_review"],
            duration_seconds=duration,
            input_tokens_total=counters["input_tokens"],
            output_tokens_total=counters["output_tokens"],
        )
