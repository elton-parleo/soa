"""
Batch driver for pass-2 re-coding (parser/response_coder_v2.py) — re-codes
a given list of already-coded soa_runs rows from stored raw_response and
pass-1's existing soa_coded_mentions only (no agent re-query, no
re-derivation of mentioned/position/strength/deal_cited), writing to
soa_price_observations / soa_citations. Never touches pass-1
soa_coded_mentions, never calls the incentive scorer.

Usage:
    from scripts.recode_cycle_pass2 import recode_runs
    summary = await recode_runs(run_ids, concurrency=5)

Each run gets one retry on failure (api_error/db_error) — a genuinely
failed run after its retry is recorded, never aborts the batch.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import List

from parser.coding_client_v2 import CodingClientV2
from parser.response_coder_v2 import CodeRunV2Result, ResponseCoderV2

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = {"api_error", "db_error"}


@dataclass
class RecodeBatchSummary:
    total: int
    succeeded: int
    failed: int
    skipped: int
    retried: int
    results: List[CodeRunV2Result] = field(default_factory=list)
    failures: List[CodeRunV2Result] = field(default_factory=list)


async def recode_runs(run_ids: List[int], concurrency: int = 5, progress_every: int = 50) -> RecodeBatchSummary:
    coder = ResponseCoderV2(CodingClientV2())
    semaphore = asyncio.Semaphore(concurrency)
    results: List[CodeRunV2Result] = []
    retried_count = 0
    done_count = 0
    lock = asyncio.Lock()

    async def _run_one(run_id: int) -> CodeRunV2Result:
        nonlocal retried_count, done_count
        async with semaphore:
            result = await coder.code_run(run_id)
            if result.status in RETRYABLE_STATUSES:
                retried_count += 1
                logger.warning("[recode_batch] run_id=%d %s, retrying once", run_id, result.status)
                result = await coder.code_run(run_id)
            async with lock:
                done_count += 1
                if progress_every and done_count % progress_every == 0:
                    logger.info("[recode_batch] progress: %d/%d", done_count, len(run_ids))
            return result

    results = await asyncio.gather(*[_run_one(rid) for rid in run_ids])

    succeeded = sum(1 for r in results if r.status == "success")
    skipped = sum(1 for r in results if r.status.startswith("skipped"))
    failures = [r for r in results if r.status not in ("success",) and not r.status.startswith("skipped")]

    return RecodeBatchSummary(
        total=len(run_ids),
        succeeded=succeeded,
        failed=len(failures),
        skipped=skipped,
        retried=retried_count,
        results=results,
        failures=failures,
    )
