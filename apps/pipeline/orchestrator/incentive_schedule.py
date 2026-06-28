"""
IncentiveScheduleBuilder — lifecycle-triggered sampling, keyed to Deal
Engine incentive windows instead of plain cycle-based sampling.

This is a NEW, optional entry point. It does not modify cycle_manager.py
or any cycle-based scheduling — it only reads GET /api/deals/active (via
the existing DealEngineClient) and computes a sample plan: four trigger
points per live deal (launch, mid-window, pre-expiry, post-expiry).

Gated by INCENTIVE_SCHEDULING_ENABLED (default False). With the flag off,
build_schedule()/dry_run() still work if called directly (this module is
never imported by cycle_manager or run_orchestrator), but the CLI entry
point refuses to run so operators don't accidentally treat this as the
default scheduling path.
"""
import argparse
import asyncio
import datetime
import logging
from dataclasses import dataclass
from typing import List, Optional

import soa_shared.config as config
from clients.deal_engine_client import DealEngineClient

logger = logging.getLogger(__name__)

# How long before valid_until to sample the "pre_expiry" trigger, and how
# long after to sample "post_expiry".
_PRE_EXPIRY_DELTA = datetime.timedelta(hours=6)
_POST_EXPIRY_DELTA = datetime.timedelta(hours=6)
# How soon after valid_from to sample the "launch" trigger.
_LAUNCH_DELTA = datetime.timedelta(hours=1)


@dataclass
class ScheduledSample:
    deal_id: Optional[str]
    merchant_slug: Optional[str]
    trigger: str  # launch | mid_window | pre_expiry | post_expiry
    scheduled_at: datetime.datetime
    valid_from: Optional[datetime.datetime]
    valid_until: Optional[datetime.datetime]


def _parse_dt(value) -> Optional[datetime.datetime]:
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        logger.warning("[incentive_schedule] Could not parse datetime: %r", value)
        return None


class IncentiveScheduleBuilder:

    def __init__(self, deal_engine_client: Optional[DealEngineClient] = None) -> None:
        self.client = deal_engine_client or DealEngineClient()

    async def build_schedule(
        self, merchant_slug: Optional[str] = None
    ) -> List[ScheduledSample]:
        """
        Reads GET /api/deals/active and builds the lifecycle-triggered
        sample plan: one ScheduledSample per (deal, trigger) for each of
        launch / mid_window / pre_expiry / post_expiry. Deals missing both
        valid_from and valid_until are skipped — there is no window to key
        sampling to. Never raises: an unreachable Deal Engine yields an
        empty schedule.
        """
        result = await self.client.active_deals(merchant_slug=merchant_slug)
        if not result.available:
            logger.warning(
                "[incentive_schedule] Deal Engine unavailable: %s — empty schedule",
                result.error,
            )
            return []

        samples: List[ScheduledSample] = []
        for deal in result.deals:
            samples.extend(self._samples_for_deal(deal))
        return samples

    def _samples_for_deal(self, deal: dict) -> List[ScheduledSample]:
        deal_id = deal.get("id") or deal.get("deal_id")
        merchant_slug = deal.get("merchant_slug")
        valid_from = _parse_dt(deal.get("valid_from"))
        valid_until = _parse_dt(deal.get("valid_until"))

        if valid_from is None and valid_until is None:
            logger.debug(
                "[incentive_schedule] Deal %s has no valid_from/valid_until — skipped",
                deal_id,
            )
            return []

        triggers: List[tuple] = []
        if valid_from is not None:
            triggers.append(("launch", valid_from + _LAUNCH_DELTA))
        if valid_from is not None and valid_until is not None:
            midpoint = valid_from + (valid_until - valid_from) / 2
            triggers.append(("mid_window", midpoint))
        if valid_until is not None:
            triggers.append(("pre_expiry", valid_until - _PRE_EXPIRY_DELTA))
            triggers.append(("post_expiry", valid_until + _POST_EXPIRY_DELTA))

        return [
            ScheduledSample(
                deal_id=str(deal_id) if deal_id is not None else None,
                merchant_slug=merchant_slug,
                trigger=trigger,
                scheduled_at=scheduled_at,
                valid_from=valid_from,
                valid_until=valid_until,
            )
            for trigger, scheduled_at in triggers
        ]

    async def dry_run(self, merchant_slug: Optional[str] = None) -> List[ScheduledSample]:
        """Builds the schedule and prints it without scheduling/running anything."""
        samples = await self.build_schedule(merchant_slug=merchant_slug)
        self._print_schedule(samples)
        return samples

    @staticmethod
    def _print_schedule(samples: List[ScheduledSample]) -> None:
        if not samples:
            print("No lifecycle-triggered samples — no active deals with a window.")
            return

        print(f"\nLifecycle-triggered sample plan ({len(samples)} samples):")
        print("-" * 78)
        for s in sorted(samples, key=lambda x: x.scheduled_at):
            print(
                f"{s.scheduled_at.isoformat():26}  {s.trigger:12}  "
                f"deal={s.deal_id or '?':10}  merchant={s.merchant_slug or '?'}"
            )
        print("-" * 78 + "\n")


def main() -> None:
    """CLI entry point: python -m orchestrator.incentive_schedule --dry-run"""
    parser = argparse.ArgumentParser(description="Lifecycle-triggered sampling (incentive windows)")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without scheduling")
    parser.add_argument("--merchant-slug", default=None)
    args = parser.parse_args()

    if not config.INCENTIVE_SCHEDULING_ENABLED:
        print(
            "INCENTIVE_SCHEDULING_ENABLED is false. Set it to true to use "
            "lifecycle-triggered sampling. Cycle-based scheduling (cycle_manager.py) "
            "is unaffected either way."
        )
        return

    builder = IncentiveScheduleBuilder()
    asyncio.run(builder.dry_run(merchant_slug=args.merchant_slug))


if __name__ == "__main__":
    main()
