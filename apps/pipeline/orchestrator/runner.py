"""
Orchestrator — executes all platform calls for a cycle concurrently.

Runs all (query × platform × run_number) combinations using asyncio.gather
so 675 calls execute concurrently rather than sequentially.
"""
import asyncio
from typing import Sequence

from sqlalchemy.orm import Session

from soa_shared.models.soa_models import SoaCycle, SoaQuery, SoaRun
from runners.base_runner import BasePlatformRunner


async def run_cycle(
    cycle: SoaCycle,
    queries: Sequence[SoaQuery],
    runners: dict[str, BasePlatformRunner],
    runs_per_slot: int,
    session: Session,
) -> None:
    """
    Fires all platform calls concurrently and persists results to soa_runs.
    """
    async def _one_run(
        query: SoaQuery,
        runner: BasePlatformRunner,
        run_number: int,
    ) -> None:
        result = await runner.generate(query.query_text)

        run = SoaRun(
            cycle_id=cycle.id,
            query_id=query.id,
            platform=runner.platform,
            run_number=run_number,
            raw_response=result.response_text,
            response_tokens=result.completion_tokens,
            latency_ms=result.latency_ms,
            status="error" if result.error else "success",
            error_message=result.error,
        )
        session.add(run)

    tasks = [
        _one_run(query, runner, run_num)
        for query in queries
        for runner in runners.values()
        for run_num in range(1, runs_per_slot + 1)
    ]

    await asyncio.gather(*tasks)
    session.flush()
