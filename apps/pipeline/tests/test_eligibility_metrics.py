"""
Tests for metrics/eligibility_metrics.py — M1 (incentive_consideration_rate)
and M3 (eligible_surfacing_rate) math, with the DB query and the Deal
Engine resolver both mocked.
"""
import asyncio
from unittest.mock import MagicMock, patch

from clients.deal_engine_client import TrueCostResult
from metrics.eligibility_metrics import EligibilityMetricsCalculator


class FakeResolver:
    """Member tiers see the member-gated deal; base/non-member tiers do not."""

    def __init__(self, eligible_for_tiers=None, always_eligible=False):
        self.eligible_for_tiers = eligible_for_tiers or set()
        self.always_eligible = always_eligible
        self.calls = []

    async def is_eligible(self, merchant_slug, category=None, brand=None, tier_name=None, deal_id=None, as_of=None):
        self.calls.append((merchant_slug, tier_name))
        if self.always_eligible:
            return True
        return tier_name in self.eligible_for_tiers


def _row(entity_id, category, stage, specificity, persona, platform, tier_name,
         merchant_slug, mentioned, deal_cited):
    return (
        entity_id, category, stage, specificity, persona, platform,
        tier_name, merchant_slug, mentioned, deal_cited,
    )


def _patched_engine(rows):
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_result
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_conn)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def test_eligible_surfacing_rate_and_incentive_consideration_rate_basic():
    rows = [
        # entity 1: mentioned + deal_cited, eligible (Rouge member)
        _row(1, "Skincare", "Research", "Mid", "Beauty Enthusiast", "chatgpt",
             "Rouge", "sephora", True, True),
        # entity 1: mentioned but no deal_cited, eligible
        _row(1, "Skincare", "Research", "Mid", "Beauty Enthusiast", "claude",
             "Rouge", "sephora", True, False),
        # entity 1: not mentioned at all, still eligible -> counts in denominator only
        _row(1, "Skincare", "Research", "Mid", "Beauty Enthusiast", "gemini",
             "Rouge", "sephora", False, False),
    ]
    resolver = FakeResolver(eligible_for_tiers={"Rouge"})
    calc = EligibilityMetricsCalculator(cycle_id=1, resolver=resolver)

    with patch("metrics.eligibility_metrics.engine") as mock_engine:
        mock_engine.connect.return_value = _patched_engine(rows)
        results = asyncio.run(calc.calculate())

    overall = [r for r in results if r.slice_type == "overall" and r.entity_id == 1]
    assert len(overall) == 1
    r = overall[0]
    assert r.total_eligible_runs == 3
    assert r.surfaced_eligible_count == 2
    assert r.considered_eligible_count == 1
    assert r.eligible_surfacing_rate == round(2 / 3, 4)
    assert r.incentive_consideration_rate == round(1 / 3, 4)


def test_non_member_persona_excludes_member_gated_runs_from_denominator():
    rows = [
        # Non-member persona (tier_name=None) — resolver says not eligible
        # for this combination, so this run must NOT enter the denominator.
        _row(1, "Skincare", "Research", "Mid", "Value-Conscious", "chatgpt",
             None, "sephora", True, True),
        # Member persona — eligible, enters denominator.
        _row(1, "Skincare", "Research", "Mid", "Beauty Enthusiast", "chatgpt",
             "Rouge", "sephora", True, True),
    ]
    resolver = FakeResolver(eligible_for_tiers={"Rouge"})
    calc = EligibilityMetricsCalculator(cycle_id=1, resolver=resolver)

    with patch("metrics.eligibility_metrics.engine") as mock_engine:
        mock_engine.connect.return_value = _patched_engine(rows)
        results = asyncio.run(calc.calculate())

    overall = [r for r in results if r.slice_type == "overall" and r.entity_id == 1][0]
    assert overall.total_eligible_runs == 1
    assert overall.surfaced_eligible_count == 1
    assert overall.incentive_consideration_rate == 1.0


def test_rows_with_no_merchant_slug_are_skipped():
    rows = [
        _row(1, "Skincare", "Research", "Mid", "Beauty Enthusiast", "chatgpt",
             "Rouge", None, True, True),  # no merchant_slug
    ]
    resolver = FakeResolver(always_eligible=True)
    calc = EligibilityMetricsCalculator(cycle_id=1, resolver=resolver)

    with patch("metrics.eligibility_metrics.engine") as mock_engine:
        mock_engine.connect.return_value = _patched_engine(rows)
        results = asyncio.run(calc.calculate())

    assert results == []
    assert resolver.calls == []  # never even called the resolver


def test_persona_slice_computed_alongside_overall():
    rows = [
        _row(1, "Skincare", "Research", "Mid", "Beauty Enthusiast", "chatgpt",
             "Rouge", "sephora", True, False),
    ]
    resolver = FakeResolver(always_eligible=True)
    calc = EligibilityMetricsCalculator(cycle_id=1, resolver=resolver)

    with patch("metrics.eligibility_metrics.engine") as mock_engine:
        mock_engine.connect.return_value = _patched_engine(rows)
        results = asyncio.run(calc.calculate())

    slice_types = {r.slice_type for r in results}
    assert "overall" in slice_types
    assert "persona" in slice_types
    persona_row = [r for r in results if r.slice_type == "persona"][0]
    assert persona_row.slice_value == "Beauty Enthusiast"


def test_zero_eligible_runs_yields_no_result_row():
    rows = [
        _row(1, "Skincare", "Research", "Mid", "Value-Conscious", "chatgpt",
             None, "sephora", True, True),
    ]
    resolver = FakeResolver(eligible_for_tiers=set())  # nothing is ever eligible
    calc = EligibilityMetricsCalculator(cycle_id=1, resolver=resolver)

    with patch("metrics.eligibility_metrics.engine") as mock_engine:
        mock_engine.connect.return_value = _patched_engine(rows)
        results = asyncio.run(calc.calculate())

    assert results == []
