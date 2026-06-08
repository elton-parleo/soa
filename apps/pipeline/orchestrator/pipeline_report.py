from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _fmt_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs:02d}s"


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


@dataclass
class PipelineReport:
    # Identity
    cycle_code: str
    pipeline_start: datetime
    pipeline_end: datetime
    total_duration_seconds: float

    # Runner stage (Stage 1)
    runner_skipped: bool
    runner_duration_seconds: Optional[float]
    runner_completed_runs: Optional[int]
    runner_error_runs: Optional[int]
    runner_timeout_runs: Optional[int]
    runner_skip_reason: Optional[str]

    # Coding stage (Stage 2)
    coding_skipped: bool
    coding_duration_seconds: Optional[float]
    coding_coded_runs: Optional[int]
    coding_needs_review: Optional[int]
    coding_validation_errors: Optional[int]
    coding_api_errors: Optional[int]
    coding_skip_reason: Optional[str]

    # Overall status — non-default fields must appear before default fields
    pipeline_status: str = "complete"       # complete / failed / partial
    failure_stage: Optional[str] = None     # runner / coding / metrics / None
    failure_reason: Optional[str] = None
    estimated_runner_cost_usd: Optional[float] = None
    estimated_coder_cost_usd: Optional[float] = None
    estimated_total_cost_usd: Optional[float] = None

    # Metrics stage (Stage 3) — all have defaults so existing call-sites don't break
    metrics_skipped: bool = True
    metrics_duration_seconds: Optional[float] = None
    metrics_rows_written: Optional[int] = None
    metrics_export_path: Optional[str] = None
    metrics_skip_reason: Optional[str] = None

    def print_report(self) -> None:
        sep_heavy = "═" * 44
        sep_light = "─" * 44

        status_line = self.pipeline_status.upper()
        if self.pipeline_status == "failed" and self.failure_stage:
            status_line = f"FAILED at {self.failure_stage}"

        print(f"\n{sep_heavy}")
        print(f"Pipeline Report — Cycle {self.cycle_code}")
        print(sep_heavy)
        print(f"Status:    {status_line}")
        print(f"Duration:  {_fmt_duration(self.total_duration_seconds)}")
        print(f"Started:   {_fmt_dt(self.pipeline_start)}")
        print(f"Finished:  {_fmt_dt(self.pipeline_end)}")

        # Stage 1 — Runner
        print(f"\nSTAGE 1 — RUNNER")
        print(sep_light)
        if self.runner_skipped:
            print(f"Status:      skipped ({self.runner_skip_reason})")
        else:
            print(f"Status:      complete")
            print(f"Duration:    {_fmt_duration(self.runner_duration_seconds or 0)}")
            print(f"Completed:   {self.runner_completed_runs or 0} runs")
            print(f"Errors:      {self.runner_error_runs or 0} runs")
            print(f"Timeouts:    {self.runner_timeout_runs or 0} runs")

        # Stage 2 — Coding
        print(f"\nSTAGE 2 — CODING")
        print(sep_light)
        if self.coding_skipped:
            print(f"Status:      skipped ({self.coding_skip_reason})")
        else:
            print(f"Status:      complete")
            print(f"Duration:    {_fmt_duration(self.coding_duration_seconds or 0)}")
            print(f"Coded:       {self.coding_coded_runs or 0} runs")
            print(f"Needs review: {self.coding_needs_review or 0} runs")
            print(f"Val. errors:  {self.coding_validation_errors or 0} runs")
            print(f"API errors:   {self.coding_api_errors or 0} runs")

        # Stage 3 — Metrics
        print(f"\nSTAGE 3 — METRICS")
        print(sep_light)
        if self.metrics_skipped:
            reason = self.metrics_skip_reason or "skipped"
            print(f"Status:      skipped ({reason})")
        else:
            print(f"Status:      complete")
            print(f"Duration:    {_fmt_duration(self.metrics_duration_seconds or 0)}")
            print(f"Rows written: {self.metrics_rows_written or 0}")
            if self.metrics_export_path:
                print(f"Export:      {self.metrics_export_path}")

        # Failure details
        if self.pipeline_status == "failed" and self.failure_reason:
            print(f"\nFAILURE REASON")
            print(sep_light)
            print(f"Stage:  {self.failure_stage}")
            print(f"Reason: {self.failure_reason}")

        # Cost
        if self.estimated_total_cost_usd is not None:
            print(f"\nESTIMATED COST")
            print(sep_light)
            runner_cost = self.estimated_runner_cost_usd or 0
            coder_cost = self.estimated_coder_cost_usd or 0
            total_cost = self.estimated_total_cost_usd or 0
            print(f"Runner API:  ~${runner_cost:.2f}")
            print(f"Coder API:   ~${coder_cost:.2f}")
            print(f"Total:       ~${total_cost:.2f}")

        print(sep_heavy + "\n")
