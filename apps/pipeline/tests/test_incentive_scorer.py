"""
Tests for scoring/incentive_scorer.py — math correctness (including the
tolerance boundary) and the ground-truth-unavailable path. The Deal Engine
client and DB session are mocked; SoaIncentiveScore rows are inspected via
the objects added to a fake session.
"""
import asyncio
from unittest.mock import MagicMock

import pytest

import soa_shared.config as config
from clients.deal_engine_client import TrueCostResult
from parser.coding_response import MerchantCoding
from scoring.incentive_scorer import IncentiveScorer


class FakeSession:
    def __init__(self, merchant_slug_by_id=None):
        self.added = []
        self._merchant_slug_by_id = merchant_slug_by_id or {}

    def add(self, obj):
        self.added.append(obj)

    def get(self, model, merchant_id):
        slug = self._merchant_slug_by_id.get(merchant_id)
        if slug is None:
            return None
        m = MagicMock()
        m.slug = slug
        return m


def _mc(**overrides):
    base = dict(
        merchant_id="M001",
        mentioned=True,
        position=1,
        strength="Positive",
        deal_cited=True,
        deal_types=["member_price"],
        evidence="ev",
        confidence=0.9,
        stated_price=89.0,
        claimed_net_price=74.0,
        claimed_discount_value=15.0,
        claimed_discount_pct=None,
        claimed_terms=["Rouge members only"],
        member_price_claimed=True,
        subscription_offer_claimed=None,
    )
    base.update(overrides)
    return MerchantCoding(**base)


class FakeClient:
    def __init__(self, result: TrueCostResult):
        self.result = result
        self.calls = []

    async def true_cost(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def test_scores_within_tolerance_marks_reflected_true():
    config.SOA_INCENTIVE_PRICE_TOLERANCE_PCT = 0.01
    mc = _mc(claimed_net_price=74.0)
    true_cost_result = TrueCostResult(
        available=True,
        true_cost=74.5,  # within 1% of 74.5 -> tol = 0.745; |74-74.5|=0.5 <= 0.745
        applied_deals=[{"deal_type": "member_price", "terms": ["Rouge members only"]}],
        confidence=0.9,
        user_tier_name="Rouge",
    )
    scorer = IncentiveScorer(deal_engine_client=FakeClient(true_cost_result))
    session = FakeSession(merchant_slug_by_id={101: "sephora"})

    scores = asyncio.run(scorer.score_run(
        session=session,
        run_id=1,
        merchants={"M001": mc},
        code_to_entity_id={"M001": 5},
        entity_id_to_merchant_id={5: 101},
        tier="Rouge",
    ))

    assert len(scores) == 1
    s = scores[0]
    assert s.status == "scored"
    assert s.net_price_reflected is True
    assert s.net_price_accuracy is True  # deal_cited=True
    assert s.term_fidelity == 1.0
    assert s.member_price_reflected is True


def test_tolerance_boundary_exact_edge_is_reflected():
    config.SOA_INCENTIVE_PRICE_TOLERANCE_PCT = 0.01
    # true_cost=100, tol=1.0 -> claimed_net_price=99.0 is exactly at boundary (<=)
    mc = _mc(claimed_net_price=99.0, deal_cited=True)
    true_cost_result = TrueCostResult(available=True, true_cost=100.0, applied_deals=[])
    scorer = IncentiveScorer(deal_engine_client=FakeClient(true_cost_result))
    session = FakeSession(merchant_slug_by_id={101: "sephora"})

    scores = asyncio.run(scorer.score_run(
        session=session,
        run_id=1,
        merchants={"M001": mc},
        code_to_entity_id={"M001": 5},
        entity_id_to_merchant_id={5: 101},
    ))

    assert scores[0].net_price_reflected is True


def test_tolerance_boundary_just_outside_is_not_reflected():
    config.SOA_INCENTIVE_PRICE_TOLERANCE_PCT = 0.01
    # true_cost=100, tol=1.0 -> claimed_net_price=98.99 is outside boundary
    mc = _mc(claimed_net_price=98.99, deal_cited=True)
    true_cost_result = TrueCostResult(available=True, true_cost=100.0, applied_deals=[])
    scorer = IncentiveScorer(deal_engine_client=FakeClient(true_cost_result))
    session = FakeSession(merchant_slug_by_id={101: "sephora"})

    scores = asyncio.run(scorer.score_run(
        session=session,
        run_id=1,
        merchants={"M001": mc},
        code_to_entity_id={"M001": 5},
        entity_id_to_merchant_id={5: 101},
    ))

    assert scores[0].net_price_reflected is False


def test_net_price_accuracy_null_when_not_deal_cited():
    mc = _mc(claimed_net_price=74.0, deal_cited=False, deal_types=[])
    true_cost_result = TrueCostResult(available=True, true_cost=74.0, applied_deals=[])
    scorer = IncentiveScorer(deal_engine_client=FakeClient(true_cost_result))
    session = FakeSession(merchant_slug_by_id={101: "sephora"})

    scores = asyncio.run(scorer.score_run(
        session=session,
        run_id=1,
        merchants={"M001": mc},
        code_to_entity_id={"M001": 5},
        entity_id_to_merchant_id={5: 101},
    ))

    assert scores[0].net_price_reflected is True
    assert scores[0].net_price_accuracy is None


def test_ground_truth_unavailable_path_writes_status_and_completes():
    mc = _mc()
    unavailable_result = TrueCostResult(available=False, error="connection refused")
    scorer = IncentiveScorer(deal_engine_client=FakeClient(unavailable_result))
    session = FakeSession(merchant_slug_by_id={101: "sephora"})

    scores = asyncio.run(scorer.score_run(
        session=session,
        run_id=1,
        merchants={"M001": mc},
        code_to_entity_id={"M001": 5},
        entity_id_to_merchant_id={5: 101},
    ))

    assert len(scores) == 1
    assert scores[0].status == "ground_truth_unavailable"
    assert scores[0].error_message == "connection refused"
    assert scores[0].net_price_reflected is None


def test_no_merchant_mapping_when_slug_cannot_be_resolved():
    mc = _mc()
    scorer = IncentiveScorer(deal_engine_client=FakeClient(TrueCostResult(available=True, true_cost=1.0)))
    session = FakeSession(merchant_slug_by_id={})  # no slug for merchant 101

    scores = asyncio.run(scorer.score_run(
        session=session,
        run_id=1,
        merchants={"M001": mc},
        code_to_entity_id={"M001": 5},
        entity_id_to_merchant_id={5: 101},
    ))

    assert scores[0].status == "no_merchant_mapping"


def test_skips_merchants_with_no_signal():
    mc = _mc(deal_cited=False, deal_types=[], stated_price=None, claimed_net_price=None)
    scorer = IncentiveScorer(deal_engine_client=FakeClient(TrueCostResult(available=True, true_cost=1.0)))
    session = FakeSession(merchant_slug_by_id={101: "sephora"})

    scores = asyncio.run(scorer.score_run(
        session=session,
        run_id=1,
        merchants={"M001": mc},
        code_to_entity_id={"M001": 5},
        entity_id_to_merchant_id={5: 101},
    ))

    assert scores == []
