"""
truecost_sweep.py — sweep executor for cycle_mode='truecost' cycles.

Instead of running LLM queries, this sweeps the cycle's frozen scope SKUs
through the Deal Engine: for each scope SKU, triggers one fresh price
scrape (refresh_price=True on the first tier only — subsequent tiers reuse
that just-written snapshot), then computes true cost for every selected
tier and persists one soa_truecost_snapshots row per (SKU x tier).

No soa_runs rows, no coder, no LLM calls. A Deal Engine failure for a SKU
writes status='ground_truth_unavailable' rows and the sweep continues —
it never aborts.
"""
import asyncio
import datetime
import logging
from dataclasses import dataclass
from typing import List, Optional

import soa_shared.config as config
from soa_shared.database import session_factory
from soa_shared.models.soa_models import SoaCycle, SoaScopeSku, SoaTruecostSnapshot
from soa_shared.scope_resolution import materialize_and_freeze
from clients.deal_engine_client import DealEngineClient, ListingTrueCostResult

logger = logging.getLogger(__name__)


@dataclass
class TruecostSweepSummary:
    cycle_code: str
    total_planned: int
    captured: int
    unavailable: int
    skipped_already_done: int
    sku_count: int
    tier_count: int


def _load_cycle(cycle_code: str) -> SoaCycle:
    with session_factory() as session:
        cycle = session.query(SoaCycle).filter_by(cycle_code=cycle_code).first()
        if cycle is None:
            raise ValueError(f"Cycle '{cycle_code}' not found in soa_cycles.")
        if cycle.cycle_mode != "truecost":
            raise ValueError(
                f"Cycle '{cycle_code}' has cycle_mode='{cycle.cycle_mode}', "
                "not 'truecost' — refusing to run the sweep executor."
            )
        session.expunge(cycle)
        return cycle


def resolve_tiers(cycle: SoaCycle) -> List[Optional[str]]:
    """[] or None -> [None] (non-member baseline only). De-dupes, preserves order."""
    tiers = cycle.truecost_tiers
    if not tiers:
        return [None]
    seen = set()
    resolved: List[Optional[str]] = []
    for t in tiers:
        if t not in seen:
            seen.add(t)
            resolved.append(t)
    return resolved or [None]


def _parse_datetime(value: Optional[str]) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


def _write_snapshot(
    cycle_id: int,
    sku: SoaScopeSku,
    tier: Optional[str],
    result: Optional[ListingTrueCostResult],
    error_message: Optional[str] = None,
) -> None:
    """Persists one soa_truecost_snapshots row in its own session."""
    common = dict(
        cycle_id=cycle_id,
        scope_sku_id=sku.id,
        entity_id=sku.entity_id,
        dealengine_listing_id=sku.dealengine_listing_id,
        merchant_slug=sku.merchant_slug,
        brand=sku.brand,
        category=sku.category,
        user_tier_name=tier,
    )

    if result is not None and result.available:
        snapshot = SoaTruecostSnapshot(
            **common,
            listed_price=result.listed_price,
            currency=result.currency,
            true_cost=result.true_cost,
            total_savings=result.total_savings,
            total_points_earned=(
                int(result.total_points_earned)
                if result.total_points_earned is not None else None
            ),
            applied_deals=result.applied_deals,
            available_deals=result.available_deals,
            confidence=result.confidence,
            price_was_refreshed=result.price_was_refreshed,
            price_refreshed_at=_parse_datetime(result.price_refreshed_at),
            status="captured",
        )
    else:
        err = error_message or (result.error if result is not None else None)
        snapshot = SoaTruecostSnapshot(
            **common,
            status="ground_truth_unavailable",
            error_message=err,
        )

    with session_factory() as session:
        session.add(snapshot)
        session.commit()


async def run_truecost_sweep(
    cycle_code: str,
    max_concurrent: Optional[int] = None,
    client: Optional[DealEngineClient] = None,
) -> TruecostSweepSummary:
    cycle = _load_cycle(cycle_code)

    # Freeze the scope exactly like the query pipeline does at run start, so
    # the sweep records exactly the frozen SKU set.
    with session_factory() as session:
        cycle_row = session.query(SoaCycle).filter_by(id=cycle.id).first()
        materialize_and_freeze(cycle_row, session, freeze=True)
        session.commit()

    with session_factory() as session:
        scope_skus: List[SoaScopeSku] = (
            session.query(SoaScopeSku)
            .filter(
                SoaScopeSku.cycle_id == cycle.id,
                SoaScopeSku.is_active.is_(True),
            )
            .order_by(SoaScopeSku.id)
            .all()
        )
        for sku in scope_skus:
            session.expunge(sku)

    tiers = resolve_tiers(cycle)
    total_planned = len(scope_skus) * len(tiers)

    # Resume support: skip (sku_id, tier) pairs already captured.
    with session_factory() as session:
        done_keys = {
            (row.scope_sku_id, row.user_tier_name)
            for row in session.query(
                SoaTruecostSnapshot.scope_sku_id, SoaTruecostSnapshot.user_tier_name
            ).filter(SoaTruecostSnapshot.cycle_id == cycle.id).all()
        }

    counters = {"captured": 0, "unavailable": 0}
    skipped = 0

    deal_engine_client = client or DealEngineClient()
    sem = asyncio.Semaphore(max_concurrent or config.SOA_TRUECOST_MAX_CONCURRENT)

    async def _sweep_one_sku(sku: SoaScopeSku) -> None:
        nonlocal skipped
        async with sem:
            if sku.dealengine_listing_id is None:
                # No ground-truth listing to scrape — every planned tier
                # for this SKU is unavailable.
                for tier in tiers:
                    if (sku.id, tier) in done_keys:
                        skipped += 1
                        continue
                    _write_snapshot(
                        cycle.id, sku, tier,
                        result=None,
                        error_message="scope SKU has no dealengine_listing_id",
                    )
                    counters["unavailable"] += 1
                return

            for i, tier in enumerate(tiers):
                if (sku.id, tier) in done_keys:
                    skipped += 1
                    continue
                # Only the first tier swept for this SKU triggers a fresh
                # scrape; remaining tiers reuse that snapshot.
                refresh = i == 0
                result = await deal_engine_client.listing_true_cost(
                    sku.dealengine_listing_id,
                    user_tier_name=tier,
                    refresh_price=refresh,
                )
                _write_snapshot(cycle.id, sku, tier, result=result)
                if result.available:
                    counters["captured"] += 1
                else:
                    counters["unavailable"] += 1
                    logger.warning(
                        "[truecost_sweep] cycle=%s sku_id=%s tier=%s unavailable: %s",
                        cycle_code, sku.id, tier, result.error,
                    )

    await asyncio.gather(*[_sweep_one_sku(sku) for sku in scope_skus])

    return TruecostSweepSummary(
        cycle_code=cycle_code,
        total_planned=total_planned,
        captured=counters["captured"],
        unavailable=counters["unavailable"],
        skipped_already_done=skipped,
        sku_count=len(scope_skus),
        tier_count=len(tiers),
    )
