from dataclasses import dataclass, field
from typing import List


@dataclass
class CycleSummary:
    """Return value of RunOrchestrator.run_cycle()."""

    cycle_code: str
    total_planned: int
    completed: int
    skipped_already_done: int
    errors: int
    timeouts: int
    duration_seconds: float
    platforms_used: List[str] = field(default_factory=list)
    queries_run: int = 0
    # Gemini 503 UNAVAILABLE recovery statistics
    gemini_503_count: int = 0
    gemini_503_fallback_successes: int = 0

    def print_summary(self) -> None:
        mins, secs = divmod(int(self.duration_seconds), 60)
        duration_str = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
        platforms_str = ", ".join(self.platforms_used)
        bar = "━" * 34
        print(f"\n{bar}")
        print(f"Cycle {self.cycle_code} Complete")
        print(bar)
        print(f"{'Planned runs:':<20} {self.total_planned:>6}")
        print(f"{'Completed:':<20} {self.completed:>6}")
        print(f"{'Already done:':<20} {self.skipped_already_done:>6}")
        print(f"{'Errors:':<20} {self.errors:>6}")
        print(f"{'Timeouts:':<20} {self.timeouts:>6}")
        print(f"{'Duration:':<20} {duration_str:>6}")
        print(f"{'Platforms:':<20} {platforms_str}")
        if self.gemini_503_count > 0:
            recovered = self.gemini_503_fallback_successes
            total = self.gemini_503_count
            print(
                f"{'Gemini 503s recovered:':<20} {recovered:>3} of {total}"
            )
        print(bar)
