"""
Dataclasses for metrics computation results.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class MetricResult:
    """One calculated metric row, ready to be written to soa_metrics_results."""
    cycle_id: int
    entity_id: int
    slice_type: str
    slice_value: str
    total_runs: int
    total_mentions: int
    mention_rate: Optional[float]
    soa_pct: Optional[float]
    position_index: Optional[float]
    rsi_score: Optional[float]
    deal_citation_rate: Optional[float]
    platform_dist_index: Optional[float]


@dataclass
class MetricsSummary:
    """Summary returned by MetricsOrchestrator.run_metrics()."""
    cycle_code: str
    merchants_calculated: int
    slices_calculated: int
    total_rows_written: int
    duration_seconds: float

    def print_summary(self) -> None:
        sep = "━" * 32
        print(f"\n{sep}")
        print(f"Metrics Cycle {self.cycle_code} Complete")
        print(sep)
        print(f"Merchants:    {self.merchants_calculated}")
        print(f"Slices:      {self.slices_calculated}"
              f"  (overall + category + stage + specificity + persona + platform)")
        print(f"Rows written: {self.total_rows_written}"
              f"  ({self.slices_calculated} slices × {self.merchants_calculated} merchants)")
        print(f"Duration:    {self.duration_seconds:.1f}s")
        print(sep + "\n")
