"""
Batch driver for Layer 2 scoring.

Same shape and the same reasons as parser/pass2_recode_batch.py: bounded
concurrency, one retry for a run that failed retryably, and a genuinely
failed run is recorded rather than aborting the batch. Lives beside the
scorer so both the live pipeline and an ops re-score call the same
orchestration rather than two copies of the batching logic.

One HistoryCache for the whole batch. A hundred runs of one study all
ground in one brand, and reading its publication history a hundred times
would be a hundred identical requests to a third-party service inside a
scoring loop.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import List

from parser.expectation_client import ExpectationClient
from scoring.expectation_scorer import (
    ExpectationScorer,
    HistoryCache,
    ScoreRunResult,
    scoreable_run_ids,
)

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = {"db_error"}


@dataclass
class ScoreBatchSummary:
    total: int
    succeeded: int
    failed: int
    skipped: int
    retried: int
    by_outcome: dict = field(default_factory=dict)
    results: List[ScoreRunResult] = field(default_factory=list)
    failures: List[ScoreRunResult] = field(default_factory=list)


async def score_runs(run_ids: List[int], *, concurrency: int = 5,
                     progress_every: int = 50,
                     scorer: ExpectationScorer = None) -> ScoreBatchSummary:
    scorer = scorer or ExpectationScorer(ExpectationClient(), HistoryCache())
    semaphore = asyncio.Semaphore(concurrency)
    retried = 0
    done = 0
    lock = asyncio.Lock()

    async def _one(run_id: int) -> ScoreRunResult:
        nonlocal retried, done
        async with semaphore:
            result = await scorer.score_run(run_id)
            if result.status in RETRYABLE_STATUSES:
                retried += 1
                logger.warning(
                    "[expectation] run_id=%d %s, retrying once", run_id, result.status,
                )
                result = await scorer.score_run(run_id)
            async with lock:
                done += 1
                if progress_every and done % progress_every == 0:
                    logger.info(
                        "[expectation] progress: %d/%d", done, len(run_ids),
                    )
            return result

    results = await asyncio.gather(*[_one(rid) for rid in run_ids])

    by_outcome = {}
    for result in results:
        if result.outcome:
            by_outcome[result.outcome] = by_outcome.get(result.outcome, 0) + 1

    succeeded = sum(1 for r in results if r.status == "success")
    skipped = sum(1 for r in results if r.status.startswith("skipped"))
    failures = [
        r for r in results
        if r.status != "success" and not r.status.startswith("skipped")
    ]

    return ScoreBatchSummary(
        total=len(run_ids),
        succeeded=succeeded,
        failed=len(failures),
        skipped=skipped,
        retried=retried,
        by_outcome=by_outcome,
        results=list(results),
        failures=failures,
    )


async def score_cycle(cycle_id: int, **kwargs) -> ScoreBatchSummary:
    """Every scoreable run in one cycle. A cycle with no grounded
    questions returns an empty summary rather than doing nothing quietly
    — the zero is the answer."""
    run_ids = scoreable_run_ids(cycle_id)
    if not run_ids:
        logger.info(
            "[expectation] cycle %s has no questions carrying a typed "
            "expectation — nothing to score", cycle_id,
        )
        return ScoreBatchSummary(0, 0, 0, 0, 0)
    return await score_runs(run_ids, **kwargs)
