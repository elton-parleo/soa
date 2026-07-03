"""
ObservationScorer — observation-grain incentive scoring, additive to
scoring/incentive_scorer.py (the legacy entity-grain scorer, untouched).

Reads soa_price_observations (pass-2 coding output — see
parser/response_coder_v2.py) and calls the Deal Engine per unique
(merchant_slug, product_price, category, brand, tier) payload, writing
soa_incentive_scores rows with scoring_grain='observation'. Never
touches scoring_grain='legacy' rows.

Merchant resolution order per observation:
  1. attribution_status='mapped' -> use merchant_slug directly.
  2. attribution_status='unmapped' -> skip, status='no_merchant_mapping'
     (the raw merchant_name stays queryable on soa_price_observations).
  3. attribution_status='brand_self_reference' -> skip, status='skipped'
     (confirmed not a retailer).
  4. attribution_status='unattributed' -> fall back to the entity's own
     soa_entities.merchant_id, but ONLY when this run has no "contrary
     retailer signal" — no OTHER 'mapped' observation anywhere in the
     same run naming a different merchant. Otherwise skip,
     status='skipped'. (soa_entities.merchant_id is null for every
     cycle-55 entity today, so this fallback is currently a no-op there
     — implemented for entities that do have one configured.)
"""
import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

import soa_shared.config as config
from clients.deal_engine_client import DealEngineClient, TrueCostResult
from soa_shared.models.merchant_ref import Merchant
from soa_shared.models.soa_models import SoaEntity, SoaIncentiveScore, SoaPriceObservation, SoaRun

logger = logging.getLogger(__name__)

CachePayload = Tuple[str, Optional[float], Optional[str], Optional[str], Optional[str]]


class ObservationScorer:

    def __init__(self, deal_engine_client: Optional[DealEngineClient] = None) -> None:
        self.client = deal_engine_client or DealEngineClient()

    async def score_cycle(self, session: Session, cycle_id: int) -> Dict[str, int]:
        """
        Idempotent per cycle: deletes this cycle's scoring_grain='observation'
        rows before recomputing (scoring_grain='legacy' rows are never
        touched, regardless of cycle). Returns a status-count summary.
        """
        observations: List[SoaPriceObservation] = (
            session.query(SoaPriceObservation)
            .join(SoaRun, SoaRun.id == SoaPriceObservation.run_id)
            .filter(SoaRun.cycle_id == cycle_id)
            .all()
        )

        # Delete this cycle's prior observation-grain rows.
        (
            session.query(SoaIncentiveScore)
            .filter(
                SoaIncentiveScore.scoring_grain == "observation",
                SoaIncentiveScore.run_id.in_(
                    session.query(SoaRun.id).filter(SoaRun.cycle_id == cycle_id)
                ),
            )
            .delete(synchronize_session=False)
        )

        # Group by run for the "contrary retailer signal" check.
        by_run: Dict[int, List[SoaPriceObservation]] = {}
        for obs in observations:
            by_run.setdefault(obs.run_id, []).append(obs)

        entity_ids = {obs.entity_id for obs in observations}
        entities = {e.id: e for e in session.query(SoaEntity).filter(SoaEntity.id.in_(entity_ids)).all()}
        merchant_id_by_slug = {
            m.slug: m.id for m in session.query(Merchant.id, Merchant.slug).all() if m.slug
        }
        slug_by_merchant_id = {v: k for k, v in merchant_id_by_slug.items()}

        cache: Dict[CachePayload, TrueCostResult] = {}
        engine_calls = 0
        cache_hits = 0
        summary: Dict[str, int] = {}

        for run_id, run_observations in by_run.items():
            mapped_slugs_in_run = {
                obs.merchant_slug for obs in run_observations
                if obs.attribution_status == "mapped" and obs.merchant_slug
            }

            for obs in run_observations:
                entity = entities.get(obs.entity_id)
                merchant_slug, resolution_status = self._resolve_merchant(
                    obs, entity, mapped_slugs_in_run, slug_by_merchant_id,
                )

                if merchant_slug is None:
                    score = SoaIncentiveScore(
                        run_id=obs.run_id,
                        entity_id=obs.entity_id,
                        merchant_id=None,
                        merchant_slug=None,
                        price_observation_id=obs.id,
                        scoring_grain="observation",
                        stated_price=obs.stated_price,
                        claimed_net_price=obs.claimed_net_price,
                        claimed_discount_value=obs.claimed_discount_value,
                        claimed_discount_pct=obs.claimed_discount_pct,
                        claimed_terms=obs.claimed_terms,
                        member_price_claimed=obs.member_price_claimed,
                        subscription_offer_claimed=obs.subscription_offer_claimed,
                        status=resolution_status,
                        error_message=f"attribution_status={obs.attribution_status}",
                    )
                    session.add(score)
                    summary[resolution_status] = summary.get(resolution_status, 0) + 1
                    continue

                product_price = obs.stated_price if obs.stated_price is not None else obs.claimed_net_price
                category = entity.category if entity else None
                brand = entity.name if entity else None
                payload_key: CachePayload = (merchant_slug, product_price, category, brand, None)

                if payload_key in cache:
                    result = cache[payload_key]
                    cache_hits += 1
                else:
                    result = await self.client.true_cost(
                        merchant_slug=merchant_slug,
                        product_price=product_price or 0.0,
                        product_category=category,
                        brand=brand,
                    )
                    cache[payload_key] = result
                    engine_calls += 1

                merchant_id = merchant_id_by_slug.get(merchant_slug)

                if not result.available:
                    score = SoaIncentiveScore(
                        run_id=obs.run_id,
                        entity_id=obs.entity_id,
                        merchant_id=merchant_id,
                        merchant_slug=merchant_slug,
                        price_observation_id=obs.id,
                        scoring_grain="observation",
                        stated_price=obs.stated_price,
                        claimed_net_price=obs.claimed_net_price,
                        claimed_discount_value=obs.claimed_discount_value,
                        claimed_discount_pct=obs.claimed_discount_pct,
                        claimed_terms=obs.claimed_terms,
                        member_price_claimed=obs.member_price_claimed,
                        subscription_offer_claimed=obs.subscription_offer_claimed,
                        status="ground_truth_unavailable",
                        error_message=result.error,
                    )
                    session.add(score)
                    summary["ground_truth_unavailable"] = summary.get("ground_truth_unavailable", 0) + 1
                    continue

                score = self._build_scored_row(obs, entity, merchant_id, merchant_slug, result)
                session.add(score)
                summary["scored"] = summary.get("scored", 0) + 1

        summary["_engine_calls"] = engine_calls
        summary["_cache_hits"] = cache_hits
        return summary

    @staticmethod
    def _resolve_merchant(
        obs: SoaPriceObservation,
        entity: Optional[SoaEntity],
        mapped_slugs_in_run: set,
        slug_by_merchant_id: Dict[int, str],
    ) -> Tuple[Optional[str], str]:
        """
        Returns (merchant_slug, "") when resolved — safe to score — or
        (None, status) naming the soa_incentive_scores.status to record
        instead.
        """
        if obs.attribution_status == "mapped" and obs.merchant_slug:
            return obs.merchant_slug, ""

        if obs.attribution_status == "unmapped":
            return None, "no_merchant_mapping"

        if obs.attribution_status == "brand_self_reference":
            return None, "skipped"

        # unattributed — fall back to the entity's own configured merchant,
        # but only when nothing else in this run named a *different*
        # retailer (a contrary signal that this response does distinguish
        # retailers, making a same-brand-site guess riskier).
        if entity is not None and entity.merchant_id is not None:
            fallback_slug = slug_by_merchant_id.get(entity.merchant_id)
            contrary_signal = bool(mapped_slugs_in_run - {fallback_slug})
            if fallback_slug and not contrary_signal:
                return fallback_slug, ""

        return None, "skipped"

    @staticmethod
    def _build_scored_row(
        obs: SoaPriceObservation,
        entity: Optional[SoaEntity],
        merchant_id: Optional[int],
        merchant_slug: str,
        result: TrueCostResult,
    ) -> SoaIncentiveScore:
        tol_pct = config.SOA_INCENTIVE_PRICE_TOLERANCE_PCT
        true_cost = result.true_cost

        net_price_reflected = None
        net_price_accuracy = None
        if obs.claimed_net_price is not None and true_cost is not None:
            tol = tol_pct * true_cost
            within_tol = abs(obs.claimed_net_price - true_cost) <= tol
            net_price_reflected = within_tol
            net_price_accuracy = within_tol

        return SoaIncentiveScore(
            run_id=obs.run_id,
            entity_id=obs.entity_id,
            merchant_id=merchant_id,
            merchant_slug=merchant_slug,
            price_observation_id=obs.id,
            scoring_grain="observation",
            stated_price=obs.stated_price,
            claimed_net_price=obs.claimed_net_price,
            claimed_discount_value=obs.claimed_discount_value,
            claimed_discount_pct=obs.claimed_discount_pct,
            claimed_terms=obs.claimed_terms,
            member_price_claimed=obs.member_price_claimed,
            subscription_offer_claimed=obs.subscription_offer_claimed,
            ground_truth_true_cost=true_cost,
            ground_truth_applied_deals=result.applied_deals,
            ground_truth_confidence=result.confidence,
            net_price_reflected=net_price_reflected,
            net_price_accuracy=net_price_accuracy,
            status="scored",
        )


async def check_attribution_rate(session: Session, cycle_id: int) -> Tuple[float, Dict[str, int]]:
    """
    Pre-flight assertion check: fraction of this cycle's price observations
    that resolved a merchant (attribution_status='mapped'). Returns
    (rate, status_counts) — the caller decides whether to proceed with
    scoring or stop and report.
    """
    observations = (
        session.query(SoaPriceObservation)
        .join(SoaRun, SoaRun.id == SoaPriceObservation.run_id)
        .filter(SoaRun.cycle_id == cycle_id)
        .all()
    )
    counts: Dict[str, int] = {}
    for obs in observations:
        counts[obs.attribution_status] = counts.get(obs.attribution_status, 0) + 1

    total = len(observations)
    mapped = counts.get("mapped", 0)
    rate = mapped / total if total else 0.0
    return rate, counts
