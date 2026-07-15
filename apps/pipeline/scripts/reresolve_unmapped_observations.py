"""
Pure lookup pass: re-runs merchant_name -> merchant_slug resolution over
EXISTING pass-2 coded soa_price_observations rows currently
attribution_status='unmapped', using the improved normalization in
parser/merchant_resolution.py (apostrophe variants, trailing punctuation).
No LLM calls, no re-coding — merchant_name is already persisted verbatim
from the original coding pass; this just re-checks it against the
current merchants table (which now includes sams-club/kroger/ebay).

Only unmapped -> mapped transitions happen. A row is left exactly as-is
(still 'unmapped') if classify_attribution() resolves it to anything
other than 'mapped' (including 'brand_self_reference') — the task scope
is strictly "recover names that now resolve", not "reclassify into new
buckets". 'mapped', 'unattributed', and 'brand_self_reference' rows are
never read or touched at all.

Usage:
    from scripts.reresolve_unmapped_observations import reresolve_cycle
    summary = reresolve_cycle(cycle_id)
"""
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List

from soa_shared.database import session_factory
from soa_shared.models.soa_models import SoaCitation, SoaEntity, SoaPriceObservation, SoaRun
from parser.merchant_resolution import classify_attribution, load_known_merchants

logger = logging.getLogger(__name__)


@dataclass
class ReresolveSummary:
    cycle_id: int
    before_counts: Dict[str, int]
    after_counts: Dict[str, int]
    newly_mapped: int
    remaining_unmapped_names: Dict[str, int]


def reresolve_cycle(cycle_id: int) -> ReresolveSummary:
    with session_factory() as session:
        before_counts = dict(Counter(
            status for (status,) in
            session.query(SoaPriceObservation.attribution_status)
            .join(SoaRun, SoaRun.id == SoaPriceObservation.run_id)
            .filter(SoaRun.cycle_id == cycle_id)
            .all()
        ))

        known_merchants = load_known_merchants(session)

        unmapped: List[SoaPriceObservation] = (
            session.query(SoaPriceObservation)
            .join(SoaRun, SoaRun.id == SoaPriceObservation.run_id)
            .filter(SoaRun.cycle_id == cycle_id, SoaPriceObservation.attribution_status == "unmapped")
            .all()
        )

        entity_ids = {obs.entity_id for obs in unmapped}
        entity_names = {
            e.id: e.name for e in session.query(SoaEntity).filter(SoaEntity.id.in_(entity_ids)).all()
        }

        run_ids = {obs.run_id for obs in unmapped}
        citation_domains_by_run: Dict[int, set] = {}
        for run_id, domain in (
            session.query(SoaCitation.run_id, SoaCitation.domain)
            .filter(SoaCitation.run_id.in_(run_ids))
            .all()
        ):
            citation_domains_by_run.setdefault(run_id, set()).add(domain)

        newly_mapped = 0
        remaining_unmapped_names: Counter = Counter()

        for obs in unmapped:
            entity_name = entity_names.get(obs.entity_id, "")
            run_citation_domains = citation_domains_by_run.get(obs.run_id, set())

            new_slug, new_status = classify_attribution(
                entity_name, obs.merchant_name, known_merchants, run_citation_domains,
            )

            if new_status == "mapped" and new_slug:
                obs.merchant_slug = new_slug
                obs.attribution_status = "mapped"
                newly_mapped += 1
            else:
                remaining_unmapped_names[obs.merchant_name] += 1

        session.commit()

        after_counts = dict(Counter(
            status for (status,) in
            session.query(SoaPriceObservation.attribution_status)
            .join(SoaRun, SoaRun.id == SoaPriceObservation.run_id)
            .filter(SoaRun.cycle_id == cycle_id)
            .all()
        ))

    logger.info(
        "[reresolve] cycle=%s newly_mapped=%d before=%s after=%s",
        cycle_id, newly_mapped, before_counts, after_counts,
    )

    return ReresolveSummary(
        cycle_id=cycle_id,
        before_counts=before_counts,
        after_counts=after_counts,
        newly_mapped=newly_mapped,
        remaining_unmapped_names=dict(remaining_unmapped_names),
    )
