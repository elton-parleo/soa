"""
EligibilityMetricsCalculator — Rung-0 metrics conditioned on the Deal
Engine's "live AND eligible" deal set.

  M1  incentive_consideration_rate = considered / (live AND eligible)
  M3  eligible_surfacing_rate      = surfaced   / (live AND eligible)

"considered" reuses the F4 deal_cited signal already coded onto
soa_coded_mentions. "surfaced" reuses mentioned. Eligibility is resolved
per (merchant, persona tier, category, brand) via EligibilityResolver,
which is responsible for treating a null tier as base/non-member.

Additive: reads soa_coded_mentions/soa_runs/soa_queries but writes only to
the new soa_eligibility_metrics table. Never touches soa_metrics_results
or any existing metric.
"""
import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text

from soa_shared.database import engine
from eligibility.resolver import EligibilityResolver
from metrics.metric_result import EligibilityMetricResult

logger = logging.getLogger(__name__)

# (slice_type, SQL column expression) — None means "overall".
SLICE_CONFIGS: List[Tuple[str, Optional[str]]] = [
    ("overall",     None),
    ("category",    "q.category"),
    ("stage",       "q.stage"),
    ("specificity", "q.specificity"),
    ("persona",     "q.persona"),
    ("platform",    "r.platform"),
]

_ROWS_SQL = """
SELECT
    cm.entity_id,
    q.category,
    q.stage,
    q.specificity,
    q.persona,
    r.platform,
    q.tier_name,
    m.slug AS merchant_slug,
    cm.mentioned,
    cm.deal_cited
FROM soa_coded_mentions cm
JOIN soa_runs r ON r.id = cm.run_id
JOIN soa_queries q ON q.id = r.query_id
JOIN soa_entities e ON e.id = cm.entity_id
LEFT JOIN merchants m ON m.id = e.merchant_id
WHERE r.cycle_id = :cycle_id
  AND r.status = 'success'
  AND cm.entity_id IS NOT NULL
"""

_SLICE_VALUE_COL = {
    "category": "category",
    "stage": "stage",
    "specificity": "specificity",
    "persona": "persona",
    "platform": "platform",
}


class _Accumulator:
    __slots__ = ("total_eligible", "surfaced", "considered")

    def __init__(self) -> None:
        self.total_eligible = 0
        self.surfaced = 0
        self.considered = 0


class EligibilityMetricsCalculator:

    def __init__(self, cycle_id: int, resolver: Optional[EligibilityResolver] = None) -> None:
        self.cycle_id = cycle_id
        self.resolver = resolver or EligibilityResolver()

    async def calculate(self) -> List[EligibilityMetricResult]:
        with engine.connect() as conn:
            rows = conn.execute(text(_ROWS_SQL), {"cycle_id": self.cycle_id}).fetchall()

        # accumulators[(slice_type, slice_value)][entity_id] -> _Accumulator
        accumulators: Dict[Tuple[str, str], Dict[int, _Accumulator]] = {}

        for row in rows:
            (
                entity_id, category, stage, specificity, persona, platform,
                tier_name, merchant_slug, mentioned, deal_cited,
            ) = row

            if not merchant_slug:
                continue  # cannot resolve eligibility without a merchant slug

            eligible = await self.resolver.is_eligible(
                merchant_slug=merchant_slug,
                category=category,
                brand=None,
                tier_name=tier_name,
            )
            if not eligible:
                continue

            row_slice_values = {
                "overall": "all",
                "category": category,
                "stage": stage,
                "specificity": specificity,
                "persona": persona,
                "platform": platform,
            }

            for slice_type, _ in SLICE_CONFIGS:
                slice_value = row_slice_values[slice_type]
                if slice_value is None:
                    continue
                bucket = accumulators.setdefault((slice_type, slice_value), {})
                acc = bucket.setdefault(entity_id, _Accumulator())
                acc.total_eligible += 1
                if mentioned:
                    acc.surfaced += 1
                if deal_cited:
                    acc.considered += 1

        results: List[EligibilityMetricResult] = []
        for (slice_type, slice_value), by_entity in accumulators.items():
            for entity_id, acc in by_entity.items():
                eligible_surfacing_rate = (
                    round(acc.surfaced / acc.total_eligible, 4)
                    if acc.total_eligible > 0 else None
                )
                incentive_consideration_rate = (
                    round(acc.considered / acc.total_eligible, 4)
                    if acc.total_eligible > 0 else None
                )
                results.append(EligibilityMetricResult(
                    cycle_id=self.cycle_id,
                    entity_id=entity_id,
                    slice_type=slice_type,
                    slice_value=slice_value,
                    total_eligible_runs=acc.total_eligible,
                    surfaced_eligible_count=acc.surfaced,
                    considered_eligible_count=acc.considered,
                    eligible_surfacing_rate=eligible_surfacing_rate,
                    incentive_consideration_rate=incentive_consideration_rate,
                ))

        logger.info(
            "EligibilityMetricsCalculator: %d result rows for cycle_id=%d",
            len(results), self.cycle_id,
        )
        return results
