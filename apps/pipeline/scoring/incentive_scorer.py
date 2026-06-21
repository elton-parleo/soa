"""
IncentiveScorer — Rung-0 fidelity scoring.

For each coded merchant mention where the agent cited a deal or stated a
price, calls the Deal Engine for ground truth and compares it against what
the agent actually said. Writes one soa_incentive_scores row per scored
merchant. Never raises — Deal Engine failures are recorded as
status=ground_truth_unavailable so the run still completes.

score_scope_skus() is the SKU-scoped counterpart: when a cycle has scope
SKUs (soa_scope_skus), it scores constrained-resolution codings against an
exact Deal Engine listing's true cost instead of a brand x category
lookup. Additive — score_run() above is unchanged.
"""
import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

import soa_shared.config as config
from clients.deal_engine_client import DealEngineClient, ListingTrueCostResult, TrueCostResult
from parser.coding_response import MerchantCoding, ScopeSkuCoding
from soa_shared.models.merchant_ref import Merchant
from soa_shared.models.soa_models import SoaIncentiveScore, SoaScopeSku

logger = logging.getLogger(__name__)


def _has_signal(mc: MerchantCoding) -> bool:
    return bool(
        mc.mentioned
        and (mc.deal_cited or mc.stated_price is not None or mc.claimed_net_price is not None)
    )


def _parse_slug_fallback_map() -> Dict[int, str]:
    raw = config.SOA_MERCHANT_SLUG_FALLBACK_MAP
    if not raw:
        return {}
    mapping: Dict[int, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        mid_str, slug = pair.split(":", 1)
        try:
            mapping[int(mid_str.strip())] = slug.strip()
        except ValueError:
            continue
    return mapping


def _terms_match(claimed: str, ground_truth_terms: List[str]) -> bool:
    claimed_lower = claimed.strip().lower()
    if not claimed_lower:
        return False
    return any(
        claimed_lower in gt.lower() or gt.lower() in claimed_lower
        for gt in ground_truth_terms
    )


def _extract_ground_truth_terms(applied_deals: List[dict]) -> List[str]:
    terms: List[str] = []
    for deal in applied_deals:
        deal_terms = deal.get("terms") or deal.get("deal_details", {}).get("terms") or []
        if isinstance(deal_terms, str):
            terms.append(deal_terms)
        elif isinstance(deal_terms, list):
            terms.extend(deal_terms)
    return terms


def _has_member_price_deal(deals: List[dict]) -> bool:
    return any(
        (deal.get("deal_type") == "member_price" or deal.get("type") == "member_price")
        for deal in deals
    )


class IncentiveScorer:

    def __init__(self, deal_engine_client: Optional[DealEngineClient] = None) -> None:
        self.client = deal_engine_client or DealEngineClient()
        self._slug_fallback = _parse_slug_fallback_map()

    def resolve_merchant_slug(self, session: Session, merchant_id: Optional[int]) -> Optional[str]:
        if merchant_id is None:
            return None
        merchant = session.get(Merchant, merchant_id)
        if merchant is not None and merchant.slug:
            return merchant.slug
        return self._slug_fallback.get(merchant_id)

    async def score_run(
        self,
        session: Session,
        run_id: int,
        merchants: Dict[str, MerchantCoding],
        code_to_entity_id: Dict[str, int],
        entity_id_to_merchant_id: Dict[int, Optional[int]],
        product_category: Optional[str] = None,
        brand: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> List[SoaIncentiveScore]:
        """
        Scores every merchant mention with a price/deal signal for this run
        and persists one SoaIncentiveScore row each. Caller owns the
        transaction (commit/rollback).
        """
        scores: List[SoaIncentiveScore] = []

        for code, mc in merchants.items():
            if not _has_signal(mc):
                continue

            entity_id = code_to_entity_id.get(code)
            merchant_id = entity_id_to_merchant_id.get(entity_id) if entity_id else None
            slug = self.resolve_merchant_slug(session, merchant_id)

            base_kwargs = dict(
                run_id=run_id,
                entity_id=entity_id,
                merchant_id=merchant_id,
                stated_price=mc.stated_price,
                claimed_net_price=mc.claimed_net_price,
                claimed_discount_value=mc.claimed_discount_value,
                claimed_discount_pct=mc.claimed_discount_pct,
                claimed_terms=mc.claimed_terms or None,
                member_price_claimed=mc.member_price_claimed,
                subscription_offer_claimed=mc.subscription_offer_claimed,
            )

            if not slug:
                score = SoaIncentiveScore(
                    **base_kwargs,
                    status="no_merchant_mapping",
                    error_message="Could not resolve merchant_slug for this entity.",
                )
                session.add(score)
                scores.append(score)
                continue

            product_price = mc.stated_price if mc.stated_price is not None else mc.claimed_net_price

            result: TrueCostResult = await self.client.true_cost(
                merchant_slug=slug,
                product_price=product_price or 0.0,
                product_category=product_category,
                brand=brand,
                user_tier_name=tier,
            )

            if not result.available:
                score = SoaIncentiveScore(
                    **base_kwargs,
                    status="ground_truth_unavailable",
                    error_message=result.error,
                )
                session.add(score)
                scores.append(score)
                continue

            score = self._build_scored_row(base_kwargs, mc, result, tier)
            session.add(score)
            scores.append(score)

        return scores

    def _build_scored_row(
        self,
        base_kwargs: dict,
        mc: MerchantCoding,
        result: TrueCostResult,
        tier: Optional[str],
    ) -> SoaIncentiveScore:
        tol_pct = config.SOA_INCENTIVE_PRICE_TOLERANCE_PCT
        true_cost = result.true_cost

        net_price_reflected = None
        net_price_accuracy = None
        if mc.claimed_net_price is not None and true_cost is not None:
            tol = tol_pct * true_cost
            within_tol = abs(mc.claimed_net_price - true_cost) <= tol
            net_price_reflected = within_tol
            if mc.deal_cited:
                net_price_accuracy = within_tol

        term_fidelity = None
        if mc.claimed_terms:
            gt_terms = _extract_ground_truth_terms(result.applied_deals)
            if gt_terms:
                matched = sum(1 for t in mc.claimed_terms if _terms_match(t, gt_terms))
                term_fidelity = matched / len(mc.claimed_terms)
            else:
                term_fidelity = 0.0

        member_price_reflected = None
        if tier:
            member_price_live = _has_member_price_deal(result.applied_deals) or _has_member_price_deal(
                result.available_deals
            )
            if member_price_live:
                member_price_reflected = bool(mc.member_price_claimed)

        return SoaIncentiveScore(
            **base_kwargs,
            ground_truth_true_cost=true_cost,
            ground_truth_applied_deals=result.applied_deals,
            ground_truth_confidence=result.confidence,
            user_tier_name=result.user_tier_name or tier,
            net_price_reflected=net_price_reflected,
            net_price_accuracy=net_price_accuracy,
            term_fidelity=term_fidelity,
            member_price_reflected=member_price_reflected,
            status="scored",
        )

    # ------------------------------------------------------------------
    # SKU-level scoring — scores scope_sku_codings against an exact Deal
    # Engine listing instead of a brand x category lookup. Additive: only
    # invoked by response_coder.py when SKU_SCOPE_ENABLED and the cycle has
    # scope SKUs; the brand-level score_run() path above is untouched.
    # ------------------------------------------------------------------

    async def score_scope_skus(
        self,
        session: Session,
        run_id: int,
        scope_sku_codings: List[ScopeSkuCoding],
        code_to_scope_sku: Dict[str, SoaScopeSku],
        tier: Optional[str] = None,
    ) -> List[SoaIncentiveScore]:
        """
        For each surfaced scope SKU coding, calls listing_true_cost() for
        its dealengine_listing_id and persists one SoaIncentiveScore row
        keyed by scope_sku_id/dealengine_listing_id. Non-surfaced codings
        are skipped — there is nothing to score. Caller owns the
        transaction (commit/rollback).
        """
        scores: List[SoaIncentiveScore] = []

        for coding in scope_sku_codings:
            if not coding.surfaced:
                continue

            sku = code_to_scope_sku.get(coding.scope_sku_code)
            if sku is None:
                continue

            base_kwargs = dict(
                run_id=run_id,
                entity_id=sku.entity_id,
                scope_sku_id=sku.id,
                dealengine_listing_id=sku.dealengine_listing_id,
                stated_price=coding.stated_price,
                claimed_terms=coding.claimed_terms or None,
                member_price_claimed=coding.member_price_claimed,
            )

            if sku.dealengine_listing_id is None:
                score = SoaIncentiveScore(
                    **base_kwargs,
                    status="no_merchant_mapping",
                    error_message="Scope SKU has no dealengine_listing_id.",
                )
                session.add(score)
                scores.append(score)
                continue

            result: ListingTrueCostResult = await self.client.listing_true_cost(
                sku.dealengine_listing_id, user_tier_name=tier,
            )

            if not result.available:
                score = SoaIncentiveScore(
                    **base_kwargs,
                    status="ground_truth_unavailable",
                    error_message=result.error,
                )
                session.add(score)
                scores.append(score)
                continue

            score = self._build_scope_sku_scored_row(base_kwargs, coding, result, tier)
            session.add(score)
            scores.append(score)

        return scores

    def _build_scope_sku_scored_row(
        self,
        base_kwargs: dict,
        coding: ScopeSkuCoding,
        result: ListingTrueCostResult,
        tier: Optional[str],
    ) -> SoaIncentiveScore:
        tol_pct = config.SOA_INCENTIVE_PRICE_TOLERANCE_PCT
        true_cost = result.true_cost
        listed_price = result.listed_price
        stated_price = coding.stated_price

        net_price_reflected = None
        net_price_accuracy = None
        if stated_price is not None and true_cost is not None:
            tol = tol_pct * true_cost
            dist_true = abs(stated_price - true_cost)

            # M12: does the stated price match the true cost at all?
            net_price_accuracy = dist_true <= tol

            # M2: does the stated price reflect the incentive specifically —
            # i.e. is it closer to true_cost than to listed_price (not just
            # coincidentally close to true_cost because there's no discount)?
            if listed_price is not None:
                dist_listed = abs(stated_price - listed_price)
                net_price_reflected = dist_true <= tol and dist_true < dist_listed
            else:
                net_price_reflected = net_price_accuracy

        term_fidelity = None
        if coding.claimed_terms:
            gt_terms = _extract_ground_truth_terms(result.applied_deals)
            if gt_terms:
                matched = sum(1 for t in coding.claimed_terms if _terms_match(t, gt_terms))
                term_fidelity = matched / len(coding.claimed_terms)
            else:
                term_fidelity = 0.0

        member_price_reflected = None
        if tier:
            member_price_live = _has_member_price_deal(result.applied_deals) or _has_member_price_deal(
                result.available_deals
            )
            if member_price_live:
                member_price_reflected = bool(coding.member_price_claimed)

        return SoaIncentiveScore(
            **base_kwargs,
            ground_truth_true_cost=true_cost,
            ground_truth_applied_deals=result.applied_deals,
            ground_truth_confidence=result.confidence,
            user_tier_name=result.user_tier_name or tier,
            net_price_reflected=net_price_reflected,
            net_price_accuracy=net_price_accuracy,
            term_fidelity=term_fidelity,
            member_price_reflected=member_price_reflected,
            status="scored",
        )
