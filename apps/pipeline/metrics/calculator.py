"""
MetricsCalculator — SQL-based metrics computation.

All six SoA metrics are calculated via PostgreSQL aggregations.
Python handles orchestration only — no raw row iteration for metric math.
"""
import logging
import statistics
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text

from soa_shared.database import engine
from metrics.metric_result import MetricResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Slice configuration: (slice_type, dimension_col)
# dimension_col is the SQL column expression to GROUP BY and SELECT.
# None means "overall" (no slice dimension beyond merchant).
# ---------------------------------------------------------------------------

SLICE_CONFIGS: List[Tuple[str, Optional[str]]] = [
    ("overall",     None),
    ("category",    "q.category"),
    ("stage",       "q.stage"),
    ("specificity", "q.specificity"),
    ("persona",     "q.persona"),
    ("platform",    "r.platform"),
]

# Per-entity aggregation SQL.
# Placeholders: {slice_select}, {group_by_extra}, {order_extra}
_MERCHANT_SQL = """
SELECT
    cm.entity_id,
    {slice_select}
    COUNT(*)                                                   AS total_runs,
    SUM(CASE WHEN cm.mentioned THEN 1 ELSE 0 END)             AS total_mentions,
    SUM(CASE
            WHEN cm.position = 1 THEN 5
            WHEN cm.position = 2 THEN 3
            WHEN cm.position = 3 THEN 2
            WHEN cm.position >= 4 THEN 1
            ELSE 0
        END)                                                   AS position_score_sum,
    COUNT(*) * 5                                               AS position_score_max,
    SUM(CASE
            WHEN cm.strength = 'Primary'  THEN 3
            WHEN cm.strength = 'Positive' THEN 1
            WHEN cm.strength = 'Neutral'  THEN 0
            WHEN cm.strength = 'Negative' THEN -1
            ELSE 0
        END)                                                   AS rsi_score_sum,
    SUM(CASE WHEN cm.deal_cited THEN 1 ELSE 0 END)            AS deal_cited_count
FROM soa_coded_mentions cm
JOIN soa_runs r ON r.id = cm.run_id
JOIN soa_queries q ON q.id = r.query_id
WHERE r.cycle_id = :cycle_id
  AND r.status = 'success'
  AND cm.entity_id IS NOT NULL
GROUP BY cm.entity_id{group_by_extra}
ORDER BY cm.entity_id{order_extra}
"""

# Total mentions across ALL tracked merchants per slice — denominator for SoA%.
# Placeholders: {slice_select}, {group_by}
_TOTALS_SQL = """
SELECT
    {slice_select}
    SUM(CASE WHEN cm.mentioned THEN 1 ELSE 0 END) AS all_mentions
FROM soa_coded_mentions cm
JOIN soa_runs r ON r.id = cm.run_id
JOIN soa_queries q ON q.id = r.query_id
WHERE r.cycle_id = :cycle_id
  AND r.status = 'success'
{group_by}
"""


class MetricsCalculator:
    """
    Computes all six SoA metrics for every merchant × slice combination.
    All aggregation SQL runs in PostgreSQL; Python only maps results.
    """

    def __init__(self, cycle_id: int) -> None:
        self.cycle_id = cycle_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate(self) -> List[MetricResult]:
        """
        Compute all metrics across all slice types.
        Returns the full list of MetricResult objects ready to write.
        """
        all_results: List[MetricResult] = []
        # merchant_id → {platform_name: soa_pct} — for PDI calculation
        platform_soa: Dict[int, Dict[str, float]] = {}

        for slice_type, dim_col in SLICE_CONFIGS:
            rows = self._run_slice(slice_type, dim_col)
            all_results.extend(rows)

            if slice_type == "platform":
                for r in rows:
                    if r.soa_pct is not None:
                        platform_soa.setdefault(r.entity_id, {})[r.slice_value] = r.soa_pct

        # Attach Platform Distribution Index to overall rows
        overall_rows = [r for r in all_results if r.slice_type == "overall"]
        self._attach_pdi(overall_rows, platform_soa)

        # Sanity-check SoA% sums
        self._validate_soa_sum(overall_rows)

        logger.info(
            "MetricsCalculator: %d result rows across %d slice types for cycle_id=%d",
            len(all_results),
            len(SLICE_CONFIGS),
            self.cycle_id,
        )
        return all_results

    # ------------------------------------------------------------------
    # Per-slice computation
    # ------------------------------------------------------------------

    def _run_slice(
        self, slice_type: str, dim_col: Optional[str]
    ) -> List[MetricResult]:
        """
        Run merchant-metrics SQL and totals SQL for one slice type.
        Joins results in Python to derive SoA% and computed metrics.
        """
        is_overall = dim_col is None

        if is_overall:
            slice_select_m = ""
            group_by_extra = ""
            order_extra    = ""
            totals_select  = ""
            totals_group   = ""
        else:
            slice_select_m = f"{dim_col} AS slice_val,"
            group_by_extra = f", {dim_col}"
            order_extra    = f", {dim_col}"
            totals_select  = f"{dim_col} AS slice_val,"
            totals_group   = f"GROUP BY {dim_col}"

        merchant_sql = _MERCHANT_SQL.format(
            slice_select=slice_select_m,
            group_by_extra=group_by_extra,
            order_extra=order_extra,
        )
        totals_sql = _TOTALS_SQL.format(
            slice_select=totals_select,
            group_by=totals_group,
        )
        params = {"cycle_id": self.cycle_id}

        with engine.connect() as conn:
            merchant_rows = conn.execute(text(merchant_sql), params).fetchall()
            totals_rows   = conn.execute(text(totals_sql),   params).fetchall()

        # Build totals lookup: slice_value → all_mentions
        if is_overall:
            raw_total = totals_rows[0][0] if totals_rows else 0
            totals_map: Dict[str, int] = {"all": int(raw_total or 0)}
        else:
            totals_map = {
                str(row[0]): int(row[1] or 0)
                for row in totals_rows
                if row[0] is not None
            }

        results: List[MetricResult] = []
        for row in merchant_rows:
            if row[0] is None:
                logger.warning(
                    "Skipping row with NULL entity_id in slice '%s' — row: %s",
                    slice_type, row,
                )
                continue
            entity_id = int(row[0])

            if is_overall:
                slice_value = "all"
                col_offset  = 1   # data columns start at index 1
            else:
                slice_value = str(row[1]) if row[1] is not None else "unknown"
                col_offset  = 2   # data columns start at index 2

            total_runs        = int(row[col_offset + 0] or 0)
            total_mentions    = int(row[col_offset + 1] or 0)
            pos_score_sum     = int(row[col_offset + 2] or 0)
            pos_score_max     = int(row[col_offset + 3] or 0)
            rsi_score_sum_val = int(row[col_offset + 4] or 0)
            deal_cited_count  = int(row[col_offset + 5] or 0)

            # Metric 1: Mention Rate
            mention_rate = (
                round(total_mentions / total_runs, 4) if total_runs > 0 else None
            )
            # Metric 3: Position Index
            position_index = (
                round(pos_score_sum / pos_score_max, 4) if pos_score_max > 0 else None
            )
            # Metric 4: RSI Score — divide by total_mentions (quality signal)
            # NULL when no mentions: entity was never mentioned in this slice,
            # so recommendation quality cannot be measured.
            rsi_score = (
                round(rsi_score_sum_val / total_mentions, 4)
                if total_mentions > 0
                else None
            )
            # Metric 5: Deal Citation Rate
            deal_citation_rate = (
                round(deal_cited_count / total_mentions, 4)
                if total_mentions > 0
                else None
            )

            # Metric 2: SoA%
            all_mentions = totals_map.get(slice_value, 0)
            soa_pct = (
                round(total_mentions / all_mentions, 4)
                if all_mentions > 0
                else None
            )

            results.append(MetricResult(
                cycle_id=self.cycle_id,
                entity_id=entity_id,
                slice_type=slice_type,
                slice_value=slice_value,
                total_runs=total_runs,
                total_mentions=total_mentions,
                mention_rate=mention_rate,
                soa_pct=soa_pct,
                position_index=position_index,
                rsi_score=rsi_score,
                deal_citation_rate=deal_citation_rate,
                platform_dist_index=None,  # patched later for overall rows
            ))

        return results

    # ------------------------------------------------------------------
    # Metric 6: Platform Distribution Index
    # ------------------------------------------------------------------

    def _attach_pdi(
        self,
        overall_rows: List[MetricResult],
        platform_soa: Dict[int, Dict[str, float]],
    ) -> None:
        """
        Compute PDI = 1 - (stdev / mean) across per-platform SoA% values
        and attach to each merchant's overall MetricResult.
        Requires >= 2 platforms with SoA% data; otherwise None.
        """
        for row in overall_rows:
            soa_by_platform = platform_soa.get(row.entity_id, {})
            values = list(soa_by_platform.values())
            if len(values) < 2:
                row.platform_dist_index = None
                continue
            mean = statistics.mean(values)
            if mean <= 0:
                row.platform_dist_index = None
                continue
            stdev = statistics.stdev(values)
            row.platform_dist_index = round(1.0 - (stdev / mean), 4)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_soa_sum(self, overall_rows: List[MetricResult]) -> None:
        """Warn if SoA% across all tracked merchants doesn't sum to ~100%."""
        total_soa = sum(r.soa_pct for r in overall_rows if r.soa_pct is not None)
        if total_soa == 0:
            return  # no mentions at all — skip check
        if not (0.95 <= total_soa <= 1.05):
            logger.warning(
                "SoA%% sum across all merchants is %.1f%% (expected ~100%%)."
                " Check for missing merchant rows in soa_coded_mentions.",
                total_soa * 100,
            )
        else:
            logger.debug(
                "SoA%% validation passed: sum = %.2f%%", total_soa * 100
            )
