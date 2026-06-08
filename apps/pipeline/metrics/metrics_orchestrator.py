"""
MetricsOrchestrator — coordinates calculator → writer → exporter
for one complete metrics run. Synchronous (no async).
"""
import logging
import time
from typing import Optional

from sqlalchemy import text

from soa_shared.database import engine, session_factory
from metrics.calculator import MetricsCalculator
from metrics.exporter import MetricsExporter
from metrics.metric_result import MetricsSummary
from metrics.writer import MetricsWriter
from soa_shared.models.soa_models import SoaCycle

logger = logging.getLogger(__name__)


class MetricsOrchestrator:

    def __init__(
        self,
        cycle_code: str,
        export: bool = True,
        export_path: Optional[str] = None,
    ) -> None:
        self.cycle_code = cycle_code
        self.export = export
        self.export_path = export_path

    def run_metrics(self) -> MetricsSummary:
        """
        Full metrics pipeline: calculate → write → refresh view → (export).
        Returns MetricsSummary with row counts and timing.
        """
        start = time.perf_counter()

        # 1. Load cycle
        cycle = self._load_cycle()

        # 2. Verify prerequisite: coded data must exist
        self._verify_coded_data(cycle.id)

        # 3. Calculate
        calc_start = time.perf_counter()
        calculator = MetricsCalculator(cycle_id=cycle.id)
        results = calculator.calculate()
        calc_duration = time.perf_counter() - calc_start
        logger.info(
            "MetricsOrchestrator: calculation complete in %.1fs — %d rows",
            calc_duration,
            len(results),
        )

        # 4. Write
        writer = MetricsWriter(cycle_id=cycle.id)
        rows_written = writer.write(results)

        # 5. Refresh materialized view
        writer.refresh_materialized_view()

        # 6. Derive summary counts
        merchants_calculated = len({r.entity_id for r in results})
        slices_calculated = len({(r.slice_type, r.slice_value) for r in results})

        # 7. Export to xlsx
        if self.export:
            try:
                exporter = MetricsExporter(cycle_code=self.cycle_code)
                out_path = exporter.export(output_path=self.export_path)
                logger.info("MetricsOrchestrator: xlsx export → %s", out_path)
            except Exception as exc:
                logger.warning("MetricsOrchestrator: xlsx export failed: %s", exc)

        total_duration = time.perf_counter() - start
        summary = MetricsSummary(
            cycle_code=self.cycle_code,
            merchants_calculated=merchants_calculated,
            slices_calculated=slices_calculated,
            total_rows_written=rows_written,
            duration_seconds=round(total_duration, 2),
        )
        return summary

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_cycle(self) -> SoaCycle:
        with session_factory() as session:
            cycle = (
                session.query(SoaCycle)
                .filter(SoaCycle.cycle_code == self.cycle_code)
                .first()
            )
            if cycle is None:
                raise ValueError(
                    f"Cycle '{self.cycle_code}' not found in soa_cycles. "
                    "Run the pipeline first to create the cycle."
                )
            session.expunge(cycle)
        return cycle

    def _verify_coded_data(self, cycle_id: int) -> None:
        sql = """
            SELECT COUNT(*) AS coded_count
            FROM soa_coded_mentions cm
            JOIN soa_runs r ON r.id = cm.run_id
            WHERE r.cycle_id = :cycle_id
        """
        with engine.connect() as conn:
            row = conn.execute(text(sql), {"cycle_id": cycle_id}).fetchone()
        coded_count = int(row[0] or 0)
        if coded_count == 0:
            raise ValueError(
                f"No coded mentions found for cycle '{self.cycle_code}' "
                "(cycle_id={cycle_id}). Run the coding stage first before "
                "calculating metrics."
            )
        logger.debug(
            "MetricsOrchestrator: found %d coded mention rows for cycle_id=%d",
            coded_count,
            cycle_id,
        )
