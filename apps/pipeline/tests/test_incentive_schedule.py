"""
Tests for orchestrator/incentive_schedule.py — schedule builder math
(launch/mid_window/pre_expiry/post_expiry trigger points) and the
unreachable-Deal-Engine path. The DealEngineClient is mocked.
"""
import asyncio
import datetime

from clients.deal_engine_client import ActiveDealsResult
from orchestrator.incentive_schedule import (
    IncentiveScheduleBuilder,
    _LAUNCH_DELTA,
    _POST_EXPIRY_DELTA,
    _PRE_EXPIRY_DELTA,
)


class FakeClient:
    def __init__(self, result: ActiveDealsResult):
        self.result = result

    async def active_deals(self, merchant_slug=None):
        return self.result


def test_builds_four_triggers_for_a_deal_with_full_window():
    valid_from = datetime.datetime(2026, 7, 1, 0, 0, tzinfo=datetime.timezone.utc)
    valid_until = datetime.datetime(2026, 7, 8, 0, 0, tzinfo=datetime.timezone.utc)
    deal = {
        "id": "d1",
        "merchant_slug": "sephora",
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(),
    }
    client = FakeClient(ActiveDealsResult(available=True, deals=[deal]))
    builder = IncentiveScheduleBuilder(deal_engine_client=client)

    samples = asyncio.run(builder.build_schedule())

    assert len(samples) == 4
    by_trigger = {s.trigger: s for s in samples}
    assert set(by_trigger) == {"launch", "mid_window", "pre_expiry", "post_expiry"}

    assert by_trigger["launch"].scheduled_at == valid_from + _LAUNCH_DELTA
    assert by_trigger["mid_window"].scheduled_at == valid_from + (valid_until - valid_from) / 2
    assert by_trigger["pre_expiry"].scheduled_at == valid_until - _PRE_EXPIRY_DELTA
    assert by_trigger["post_expiry"].scheduled_at == valid_until + _POST_EXPIRY_DELTA

    for s in samples:
        assert s.deal_id == "d1"
        assert s.merchant_slug == "sephora"


def test_deal_with_only_valid_until_skips_launch_and_mid_window():
    valid_until = datetime.datetime(2026, 7, 8, tzinfo=datetime.timezone.utc)
    deal = {"id": "d2", "merchant_slug": "ulta", "valid_until": valid_until.isoformat()}
    client = FakeClient(ActiveDealsResult(available=True, deals=[deal]))
    builder = IncentiveScheduleBuilder(deal_engine_client=client)

    samples = asyncio.run(builder.build_schedule())

    triggers = {s.trigger for s in samples}
    assert triggers == {"pre_expiry", "post_expiry"}


def test_deal_with_only_valid_from_skips_window_dependent_triggers():
    valid_from = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)
    deal = {"id": "d3", "merchant_slug": "sephora", "valid_from": valid_from.isoformat()}
    client = FakeClient(ActiveDealsResult(available=True, deals=[deal]))
    builder = IncentiveScheduleBuilder(deal_engine_client=client)

    samples = asyncio.run(builder.build_schedule())

    triggers = {s.trigger for s in samples}
    assert triggers == {"launch"}


def test_deal_with_no_window_at_all_is_skipped():
    deal = {"id": "d4", "merchant_slug": "sephora"}
    client = FakeClient(ActiveDealsResult(available=True, deals=[deal]))
    builder = IncentiveScheduleBuilder(deal_engine_client=client)

    samples = asyncio.run(builder.build_schedule())
    assert samples == []


def test_unreachable_deal_engine_yields_empty_schedule_never_raises():
    client = FakeClient(ActiveDealsResult(available=False, error="connection refused"))
    builder = IncentiveScheduleBuilder(deal_engine_client=client)

    samples = asyncio.run(builder.build_schedule())
    assert samples == []


def test_multiple_deals_produce_independent_schedules():
    valid_from = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)
    valid_until = datetime.datetime(2026, 7, 8, tzinfo=datetime.timezone.utc)
    deals = [
        {"id": "d1", "merchant_slug": "sephora", "valid_from": valid_from.isoformat(),
         "valid_until": valid_until.isoformat()},
        {"id": "d2", "merchant_slug": "ulta", "valid_from": valid_from.isoformat(),
         "valid_until": valid_until.isoformat()},
    ]
    client = FakeClient(ActiveDealsResult(available=True, deals=deals))
    builder = IncentiveScheduleBuilder(deal_engine_client=client)

    samples = asyncio.run(builder.build_schedule())
    assert len(samples) == 8
    deal_ids = {s.deal_id for s in samples}
    assert deal_ids == {"d1", "d2"}


def test_dry_run_prints_plan_and_returns_samples(capsys):
    valid_from = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)
    valid_until = datetime.datetime(2026, 7, 8, tzinfo=datetime.timezone.utc)
    deal = {"id": "d1", "merchant_slug": "sephora", "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat()}
    client = FakeClient(ActiveDealsResult(available=True, deals=[deal]))
    builder = IncentiveScheduleBuilder(deal_engine_client=client)

    samples = asyncio.run(builder.dry_run())

    captured = capsys.readouterr()
    assert "Lifecycle-triggered sample plan" in captured.out
    assert "sephora" in captured.out
    assert len(samples) == 4
