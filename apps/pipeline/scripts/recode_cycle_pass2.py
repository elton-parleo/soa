"""
Thin re-export — the real pass-2 batch orchestration lives in
parser/pass2_recode_batch.py, so this script and the live pipeline
(orchestrator/pipeline.py's lite-gated pass-2 stage) call the exact same
function, never two copies of the batching/retry logic.

Usage (unchanged):
    from scripts.recode_cycle_pass2 import recode_runs
    summary = await recode_runs(run_ids, concurrency=5)
"""
from parser.pass2_recode_batch import RecodeBatchSummary, recode_runs

__all__ = ["RecodeBatchSummary", "recode_runs"]
