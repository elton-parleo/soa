"""
MetricsWriter — idempotent write of MetricResult rows to soa_metrics_results.

Uses bulk SQLAlchemy Core insert (not ORM add()) for speed.
Always deletes existing rows for the cycle before inserting — guarantees
rerunning metrics recalculates cleanly.
"""
import logging
from typing import List

from sqlalchemy import insert, text

from soa_shared.database import engine
from metrics.metric_result import EligibilityMetricResult, MetricResult
from soa_shared.models.soa_models import SoaEligibilityMetricsResult, SoaMetricsResult

logger = logging.getLogger(__name__)


class MetricsWriter:

    def __init__(self, cycle_id: int) -> None:
        self.cycle_id = cycle_id

    def write(self, results: List[MetricResult]) -> int:
        """
        Delete existing rows for this cycle, then bulk-insert all MetricResult
        objects. Returns the count of rows written.
        """
        if not results:
            logger.warning("MetricsWriter.write() called with empty results list.")
            return 0

        row_dicts = [
            {
                "cycle_id":           r.cycle_id,
                "entity_id":          r.entity_id,
                "slice_type":         r.slice_type,
                "slice_value":        r.slice_value,
                "total_runs":         r.total_runs,
                "total_mentions":     r.total_mentions,
                "mention_rate":       r.mention_rate,
                "soa_pct":            r.soa_pct,
                "position_index":     r.position_index,
                "rsi_score":          r.rsi_score,
                "deal_citation_rate": r.deal_citation_rate,
                "platform_dist_index": r.platform_dist_index,
                # calculated_at uses server_default = NOW()
            }
            for r in results
        ]

        with engine.connect() as conn:
            # Step 1: Delete existing rows for idempotency
            deleted = conn.execute(
                text("DELETE FROM soa_metrics_results WHERE cycle_id = :cycle_id"),
                {"cycle_id": self.cycle_id},
            )
            logger.debug(
                "MetricsWriter: deleted %d existing rows for cycle_id=%d",
                deleted.rowcount,
                self.cycle_id,
            )

            # Step 2: Bulk insert
            conn.execute(insert(SoaMetricsResult), row_dicts)
            conn.commit()

        logger.info(
            "MetricsWriter: wrote %d rows for cycle_id=%d",
            len(row_dicts),
            self.cycle_id,
        )
        return len(row_dicts)

    def write_eligibility_metrics(self, results: List[EligibilityMetricResult]) -> int:
        """
        Delete existing soa_eligibility_metrics rows for this cycle, then
        bulk-insert all EligibilityMetricResult objects. Additive — never
        touches soa_metrics_results. Returns the count of rows written.
        """
        if not results:
            logger.warning("MetricsWriter.write_eligibility_metrics() called with empty results list.")
            return 0

        row_dicts = [
            {
                "cycle_id":                     r.cycle_id,
                "entity_id":                    r.entity_id,
                "slice_type":                   r.slice_type,
                "slice_value":                  r.slice_value,
                "total_eligible_runs":          r.total_eligible_runs,
                "surfaced_eligible_count":      r.surfaced_eligible_count,
                "considered_eligible_count":    r.considered_eligible_count,
                "eligible_surfacing_rate":      r.eligible_surfacing_rate,
                "incentive_consideration_rate": r.incentive_consideration_rate,
                # calculated_at uses server_default = NOW()
            }
            for r in results
        ]

        with engine.connect() as conn:
            deleted = conn.execute(
                text("DELETE FROM soa_eligibility_metrics WHERE cycle_id = :cycle_id"),
                {"cycle_id": self.cycle_id},
            )
            logger.debug(
                "MetricsWriter: deleted %d existing eligibility rows for cycle_id=%d",
                deleted.rowcount,
                self.cycle_id,
            )
            conn.execute(insert(SoaEligibilityMetricsResult), row_dicts)
            conn.commit()

        logger.info(
            "MetricsWriter: wrote %d eligibility rows for cycle_id=%d",
            len(row_dicts),
            self.cycle_id,
        )
        return len(row_dicts)

    def refresh_materialized_view(self) -> None:
        """
        Refresh the soa_dashboard_summary materialized view.
        Uses CONCURRENTLY to allow reads during refresh (requires unique index).
        Falls back to a non-concurrent refresh if CONCURRENTLY is unavailable
        (e.g., first ever population of an empty view).
        Must run outside a transaction block — uses AUTOCOMMIT isolation.
        """
        import datetime

        start = datetime.datetime.now()
        try:
            with engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as conn:
                conn.execute(
                    text("REFRESH MATERIALIZED VIEW CONCURRENTLY soa_dashboard_summary")
                )
            elapsed = (datetime.datetime.now() - start).total_seconds()
            logger.info(
                "Materialized view soa_dashboard_summary refreshed (CONCURRENTLY) in %.1fs",
                elapsed,
            )
        except Exception as exc:
            # Fall back to non-concurrent refresh (e.g. view was never populated)
            logger.warning(
                "CONCURRENTLY refresh failed (%s) — retrying without CONCURRENTLY", exc
            )
            with engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as conn:
                conn.execute(
                    text("REFRESH MATERIALIZED VIEW soa_dashboard_summary")
                )
            elapsed = (datetime.datetime.now() - start).total_seconds()
            logger.info(
                "Materialized view soa_dashboard_summary refreshed in %.1fs", elapsed
            )
