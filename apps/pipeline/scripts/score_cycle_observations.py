"""
Driver for observation-grain incentive scoring
(scoring/observation_scorer.py). Checks the merchant-resolution
assertion first; only calls the Deal Engine if it passes.

Usage:
    from scripts.score_cycle_observations import score_cycle_with_assertion
    summary = await score_cycle_with_assertion(cycle_id, threshold=0.80)
"""
import logging
from dataclasses import dataclass
from typing import Dict, Optional

from soa_shared.database import session_factory
from scoring.observation_scorer import AttributionAssertion, ObservationScorer, check_attribution_rate

logger = logging.getLogger(__name__)


@dataclass
class ScoreCycleResult:
    cycle_id: int
    assertion: AttributionAssertion
    passed_assertion: bool
    scoring_summary: Optional[Dict[str, int]] = None


async def score_cycle_with_assertion(cycle_id: int, threshold: float = 0.80) -> ScoreCycleResult:
    with session_factory() as session:
        assertion = await check_attribution_rate(session, cycle_id)

    passed = assertion.resolution_rate >= threshold
    if not passed:
        logger.warning(
            "[score_cycle] cycle=%s resolution_rate=%.1f%% < threshold=%.1f%% — not scoring",
            cycle_id, assertion.resolution_rate * 100, threshold * 100,
        )
        return ScoreCycleResult(cycle_id=cycle_id, assertion=assertion, passed_assertion=False)

    logger.info(
        "[score_cycle] cycle=%s resolution_rate=%.1f%% >= threshold=%.1f%% — scoring",
        cycle_id, assertion.resolution_rate * 100, threshold * 100,
    )

    scorer = ObservationScorer()
    with session_factory() as session:
        scoring_summary = await scorer.score_cycle(session, cycle_id)
        session.commit()

    return ScoreCycleResult(
        cycle_id=cycle_id, assertion=assertion, passed_assertion=True, scoring_summary=scoring_summary,
    )
