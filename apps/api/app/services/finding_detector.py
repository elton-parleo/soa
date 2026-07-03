"""
Deterministic finding detector for the AC3 Actions feature (v1).

Reads existing cycle metrics (soa_metrics_results, soa_coded_mentions,
soa_incentive_scores) and soa_queries — never writes to any table the
pipeline owns. Writes only to soa_findings. See docs/playbook_v1.md for
the plays this implements.

Six of the 22 seeded plays have a detector: VIS-01, VIS-05, VIS-06,
VIS-07, TVD-01, TVD-03. The other 16 are seeded with
detector_status='not_implemented' because the data their detection
trigger depends on does not exist anywhere in this codebase yet
(citation extraction, coding-stage contradiction/version-mismatch flags,
Entity Registry launch/supersession fields, link-resolution/routing
data, or Deal Engine basket/subscription/expiry signals — see
apps/pipeline/seeds/playbook_v1.json for the play-by-play reasoning).
Adding a detector for one of those plays first requires adding the
underlying data capture — this module must never guess at a trigger.

Determinism: every detector function has the signature
(cycle_id, session, thresholds) -> list[FindingDraft] and reads only
already-committed rows. Same cycle input, same findings output, always.
"""
import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import yaml
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from soa_shared.database import session_factory
from soa_shared.models.soa_models import (
    SoaCodedMention,
    SoaCycle,
    SoaCycleEntity,
    SoaFinding,
    SoaIncentiveScore,
    SoaMetricsResult,
    SoaQuery,
    SoaRun,
)

logger = logging.getLogger(__name__)

THRESHOLDS_PATH = Path(__file__).resolve().parents[1] / "config" / "detector_thresholds.yaml"

MAX_EVIDENCE_RUN_IDS = 50


@dataclass
class FindingDraft:
    entity_id: Optional[int]
    play_id: str
    dimension: str
    severity: float
    cells_affected: int
    metric_snapshot: dict
    evidence_run_ids: List[int] = field(default_factory=list)
    surface: Optional[str] = None
    persona: Optional[str] = None
    stage: Optional[str] = None


def load_thresholds() -> dict:
    with open(THRESHOLDS_PATH) as f:
        return yaml.safe_load(f)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _play_thresholds(thresholds: dict, play_id: str) -> dict:
    merged = dict(thresholds.get("_defaults", {}))
    merged.update(thresholds.get(play_id, {}))
    return merged


def _cycle_entity_ids(session: Session, cycle_id: int) -> List[int]:
    rows = (
        session.query(SoaCycleEntity.entity_id)
        .filter(SoaCycleEntity.cycle_id == cycle_id)
        .all()
    )
    return sorted({r[0] for r in rows})


def _matching_run_ids(
    session: Session,
    cycle_id: int,
    entity_id: int,
    mentioned: bool,
    limit: int,
    stage: Optional[str] = None,
    persona: Optional[str] = None,
    platforms: Optional[List[str]] = None,
) -> List[int]:
    """Evidence run IDs for a finding — runs backing the metric_snapshot."""
    q = (
        session.query(SoaRun.id)
        .join(SoaCodedMention, SoaCodedMention.run_id == SoaRun.id)
        .join(SoaQuery, SoaQuery.id == SoaRun.query_id)
        .filter(
            SoaRun.cycle_id == cycle_id,
            SoaRun.status == "success",
            SoaCodedMention.entity_id == entity_id,
            SoaCodedMention.mentioned.is_(mentioned),
        )
    )
    if stage:
        q = q.filter(SoaQuery.stage == stage)
    if persona:
        q = q.filter(SoaQuery.persona == persona)
    if platforms:
        q = q.filter(SoaRun.platform.in_(platforms))
    return [r[0] for r in q.order_by(SoaRun.id).limit(limit).all()]


# ---------------------------------------------------------------------------
# VIS-01 — Structured data completeness
# ---------------------------------------------------------------------------

def detect_vis_01(cycle_id: int, session: Session, thresholds: dict) -> List[FindingDraft]:
    """
    Presence rate < presence_rate_max for an entity across
    >= min_deficient_surfaces platforms on `stage`-stage intents, while
    >= 1 other entity in the same cycle exceeds competitor_presence_min
    on at least one of those same (platform, stage) cells.

    soa_metrics_results does not cross platform x stage in a single
    slice, so this queries soa_coded_mentions/soa_runs/soa_queries
    directly — same r.status='success' join shape as
    apps/pipeline/metrics/calculator.py — rather than a pre-aggregated
    table.
    """
    stage = thresholds["stage"]
    presence_max = thresholds["presence_rate_max"]
    min_surfaces = thresholds["min_deficient_surfaces"]
    competitor_min = thresholds["competitor_presence_min"]
    min_sample = thresholds["min_sample_size"]

    rows = (
        session.query(
            SoaCodedMention.entity_id,
            SoaRun.platform,
            func.count(SoaCodedMention.id),
            func.sum(case((SoaCodedMention.mentioned.is_(True), 1), else_=0)),
        )
        .join(SoaRun, SoaRun.id == SoaCodedMention.run_id)
        .join(SoaQuery, SoaQuery.id == SoaRun.query_id)
        .filter(
            SoaRun.cycle_id == cycle_id,
            SoaRun.status == "success",
            SoaQuery.stage == stage,
            SoaCodedMention.entity_id.isnot(None),
        )
        .group_by(SoaCodedMention.entity_id, SoaRun.platform)
        .all()
    )

    presence: Dict[int, Dict[str, float]] = {}
    for entity_id, platform, total, mentioned in rows:
        if total < min_sample:
            continue
        presence.setdefault(entity_id, {})[platform] = mentioned / total

    drafts: List[FindingDraft] = []
    for entity_id in sorted(presence.keys()):
        surfaces = presence[entity_id]
        deficient = {p: r for p, r in surfaces.items() if r < presence_max}
        if len(deficient) < min_surfaces:
            continue

        leader_id, leader_rate = None, 0.0
        for other_id, other_surfaces in presence.items():
            if other_id == entity_id:
                continue
            for platform in deficient:
                other_rate = other_surfaces.get(platform)
                if other_rate is not None and other_rate > competitor_min and other_rate > leader_rate:
                    leader_id, leader_rate = other_id, other_rate
        if leader_id is None:
            continue

        avg_deficient_rate = statistics.mean(deficient.values())
        severity = _clamp01((presence_max - avg_deficient_rate) / presence_max)

        drafts.append(FindingDraft(
            entity_id=entity_id,
            play_id="VIS-01",
            dimension="Presence",
            stage=stage,
            severity=severity,
            cells_affected=len(deficient),
            metric_snapshot={
                "surfaces": {p: round(r, 4) for p, r in deficient.items()},
                "presence_rate_max": presence_max,
                "competitor_entity_id": leader_id,
                "competitor_presence_rate": round(leader_rate, 4),
            },
            evidence_run_ids=_matching_run_ids(
                session, cycle_id, entity_id, mentioned=False, limit=MAX_EVIDENCE_RUN_IDS,
                stage=stage, platforms=list(deficient.keys()),
            ),
        ))
    return drafts


# ---------------------------------------------------------------------------
# VIS-05 — Funnel-stage content gap
# ---------------------------------------------------------------------------

def detect_vis_05(cycle_id: int, session: Session, thresholds: dict) -> List[FindingDraft]:
    """
    Presence rate on `awareness_stage` < awareness_to_purchase_ratio_max
    of the same entity's presence rate on `purchase_stage`. Reads the
    pre-aggregated slice_type='stage' rows in soa_metrics_results.
    """
    awareness_stage = thresholds["awareness_stage"]
    purchase_stage = thresholds["purchase_stage"]
    ratio_max = thresholds["awareness_to_purchase_ratio_max"]
    min_sample = thresholds["min_sample_size"]

    rows = (
        session.query(SoaMetricsResult)
        .filter(
            SoaMetricsResult.cycle_id == cycle_id,
            SoaMetricsResult.slice_type == "stage",
            SoaMetricsResult.slice_value.in_([awareness_stage, purchase_stage]),
        )
        .all()
    )
    by_entity: Dict[int, Dict[str, SoaMetricsResult]] = {}
    for r in rows:
        by_entity.setdefault(r.entity_id, {})[r.slice_value] = r

    drafts: List[FindingDraft] = []
    for entity_id in sorted(by_entity.keys()):
        stages = by_entity[entity_id]
        awareness = stages.get(awareness_stage)
        purchase = stages.get(purchase_stage)
        if not awareness or not purchase:
            continue
        if awareness.total_runs < min_sample or purchase.total_runs < min_sample:
            continue

        purchase_rate = purchase.mention_rate or 0.0
        awareness_rate = awareness.mention_rate or 0.0
        if purchase_rate <= 0:
            continue

        ratio = awareness_rate / purchase_rate
        if ratio >= ratio_max:
            continue
        severity = _clamp01((ratio_max - ratio) / ratio_max)

        drafts.append(FindingDraft(
            entity_id=entity_id,
            play_id="VIS-05",
            dimension="Presence (stage-sliced)",
            stage=awareness_stage,
            severity=severity,
            cells_affected=1,
            metric_snapshot={
                "awareness_stage": awareness_stage,
                "purchase_stage": purchase_stage,
                "awareness_presence_rate": round(awareness_rate, 4),
                "purchase_presence_rate": round(purchase_rate, 4),
                "ratio": round(ratio, 4),
                "ratio_max": ratio_max,
            },
            evidence_run_ids=_matching_run_ids(
                session, cycle_id, entity_id, mentioned=False, limit=MAX_EVIDENCE_RUN_IDS,
                stage=awareness_stage,
            ),
        ))
    return drafts


# ---------------------------------------------------------------------------
# VIS-06 — Persona coverage gap
# ---------------------------------------------------------------------------

def detect_vis_06(cycle_id: int, session: Session, thresholds: dict) -> List[FindingDraft]:
    """
    Presence rate variance across personas > persona_variance_max_points
    for the same entity.

    Simplification: the playbook trigger says "for the same entity and
    stage", but soa_metrics_results' persona slice is not additionally
    cross-sliced by stage — this compares across the persona slice only
    (all stages combined).
    """
    variance_max = thresholds["persona_variance_max_points"]
    min_sample = thresholds["min_sample_size"]

    rows = (
        session.query(SoaMetricsResult)
        .filter(SoaMetricsResult.cycle_id == cycle_id, SoaMetricsResult.slice_type == "persona")
        .all()
    )
    by_entity: Dict[int, List[SoaMetricsResult]] = {}
    for r in rows:
        if r.total_runs >= min_sample and r.mention_rate is not None:
            by_entity.setdefault(r.entity_id, []).append(r)

    drafts: List[FindingDraft] = []
    for entity_id in sorted(by_entity.keys()):
        persona_results = by_entity[entity_id]
        if len(persona_results) < 2:
            continue
        rates = {r.slice_value: r.mention_rate for r in persona_results}
        variance_points = max(rates.values()) - min(rates.values())
        if variance_points <= variance_max:
            continue
        severity = _clamp01((variance_points - variance_max) / (1.0 - variance_max)) if variance_max < 1.0 else 0.0

        weakest_persona = min(rates, key=rates.get)
        drafts.append(FindingDraft(
            entity_id=entity_id,
            play_id="VIS-06",
            dimension="Presence",
            severity=severity,
            cells_affected=len(rates),
            metric_snapshot={
                "persona_presence_rates": {p: round(v, 4) for p, v in rates.items()},
                "variance_points": round(variance_points, 4),
                "variance_max": variance_max,
                "weakest_persona": weakest_persona,
            },
            evidence_run_ids=_matching_run_ids(
                session, cycle_id, entity_id, mentioned=False, limit=MAX_EVIDENCE_RUN_IDS,
                persona=weakest_persona,
            ),
        ))
    return drafts


# ---------------------------------------------------------------------------
# VIS-07 — Prominence deficit
# ---------------------------------------------------------------------------

def detect_vis_07(cycle_id: int, session: Session, thresholds: dict) -> List[FindingDraft]:
    """
    Presence >= presence_min but position_index >= position_gap_min below
    the category leader's, across >= min_deficient_surfaces platforms.

    Reads slice_type='platform' rows in soa_metrics_results.
    soa_metrics_results.position_index (apps/pipeline/metrics/calculator.py)
    is a normalized 0-1 score — position 1 mentions weight 5, position 2
    weight 3, position 3 weight 2, position >=4 weight 1, not-mentioned
    weight 0, divided by (total_runs x 5) — so HIGHER is better (closer to
    consistently ranking #1). "Category leader" = the entity with the
    highest position_index on that platform. The playbook trigger is
    phrased in raw rank positions ("2 positions behind"), which this table
    does not store; position_gap_min is therefore a position_index-unit
    threshold, not a raw rank count — tune it against real gaps, not the
    literal "2".
    """
    presence_min = thresholds["presence_min"]
    gap_min = thresholds["position_gap_min"]
    min_surfaces = thresholds["min_deficient_surfaces"]
    min_sample = thresholds["min_sample_size"]

    rows = (
        session.query(SoaMetricsResult)
        .filter(SoaMetricsResult.cycle_id == cycle_id, SoaMetricsResult.slice_type == "platform")
        .all()
    )
    by_platform: Dict[str, List[SoaMetricsResult]] = {}
    for r in rows:
        if r.total_runs >= min_sample:
            by_platform.setdefault(r.slice_value, []).append(r)

    leader_by_platform: Dict[str, SoaMetricsResult] = {}
    for platform, results in by_platform.items():
        candidates = [r for r in results if r.position_index is not None]
        if candidates:
            leader_by_platform[platform] = max(candidates, key=lambda r: r.position_index)

    by_entity: Dict[int, Dict[str, SoaMetricsResult]] = {}
    for platform, results in by_platform.items():
        for r in results:
            by_entity.setdefault(r.entity_id, {})[platform] = r

    drafts: List[FindingDraft] = []
    for entity_id in sorted(by_entity.keys()):
        deficient = {}
        for platform, r in by_entity[entity_id].items():
            leader = leader_by_platform.get(platform)
            if not leader or leader.entity_id == entity_id:
                continue
            if r.mention_rate is None or r.position_index is None:
                continue
            if r.mention_rate < presence_min:
                continue
            gap = leader.position_index - r.position_index
            if gap >= gap_min:
                deficient[platform] = {
                    "presence_rate": round(r.mention_rate, 4),
                    "position_index": round(r.position_index, 4),
                    "leader_entity_id": leader.entity_id,
                    "leader_position_index": round(leader.position_index, 4),
                    "gap": round(gap, 4),
                }
        if len(deficient) < min_surfaces:
            continue

        avg_gap = statistics.mean(d["gap"] for d in deficient.values())
        severity = _clamp01((avg_gap - gap_min) / max(gap_min, 1.0))

        drafts.append(FindingDraft(
            entity_id=entity_id,
            play_id="VIS-07",
            dimension="Prominence",
            severity=severity,
            cells_affected=len(deficient),
            metric_snapshot={
                "surfaces": deficient,
                "presence_min": presence_min,
                "position_gap_min": gap_min,
            },
            evidence_run_ids=_matching_run_ids(
                session, cycle_id, entity_id, mentioned=True, limit=MAX_EVIDENCE_RUN_IDS,
                platforms=list(deficient.keys()),
            ),
        ))
    return drafts


# ---------------------------------------------------------------------------
# TVD-01 — Active-promo exposure
# ---------------------------------------------------------------------------

def detect_tvd_01(cycle_id: int, session: Session, thresholds: dict) -> List[FindingDraft]:
    """
    Agent-quoted price (soa_incentive_scores.stated_price) exceeds
    validated true price (ground_truth_true_cost) by more than
    price_gap_pct_min, on runs where a promo was active (ground truth
    has >=1 applied deal).

    Reads scoring_grain='observation' rows only — one row per (entity,
    merchant, run, observation), from real coded merchant attribution
    (parser/response_coder_v2.py) rather than the always-null
    soa_entities.merchant_id default the legacy grain used. Findings are
    grouped by (entity, merchant) — a genuine retailer, not an assumed
    one — with a per-surface (platform) breakdown in metric_snapshot.
    """
    gap_min = thresholds["price_gap_pct_min"]
    min_sample = thresholds["min_sample_size"]

    rows = (
        session.query(SoaIncentiveScore, SoaRun.platform)
        .join(SoaRun, SoaRun.id == SoaIncentiveScore.run_id)
        .filter(
            SoaRun.cycle_id == cycle_id,
            SoaIncentiveScore.scoring_grain == "observation",
            SoaIncentiveScore.status == "scored",
            SoaIncentiveScore.entity_id.isnot(None),
            SoaIncentiveScore.merchant_slug.isnot(None),
            SoaIncentiveScore.stated_price.isnot(None),
            SoaIncentiveScore.ground_truth_true_cost.isnot(None),
        )
        .all()
    )

    by_cell: Dict[tuple, List[tuple]] = {}
    for score, platform in rows:
        if not score.ground_truth_applied_deals:
            continue  # no promo active on this observation — not in scope for TVD-01
        by_cell.setdefault((score.entity_id, score.merchant_slug), []).append((score, platform))

    drafts: List[FindingDraft] = []
    for entity_id, merchant_slug in sorted(by_cell.keys()):
        cell_rows = by_cell[(entity_id, merchant_slug)]
        if len(cell_rows) < min_sample:
            continue

        overpriced = []
        for s, platform in cell_rows:
            if s.ground_truth_true_cost <= 0:
                continue
            gap = (s.stated_price - s.ground_truth_true_cost) / s.ground_truth_true_cost
            if gap > gap_min:
                overpriced.append((s, platform, gap))
        if not overpriced:
            continue

        overpriced_rate = len(overpriced) / len(cell_rows)
        severity = _clamp01(overpriced_rate)

        by_surface: Dict[str, int] = {}
        for _, platform, _ in overpriced:
            by_surface[platform] = by_surface.get(platform, 0) + 1

        drafts.append(FindingDraft(
            entity_id=entity_id,
            play_id="TVD-01",
            dimension="Net Price Accuracy",
            severity=severity,
            cells_affected=len(overpriced),
            metric_snapshot={
                "merchant_slug": merchant_slug,
                "n_active_promo_scored_observations": len(cell_rows),
                "n_overpriced": len(overpriced),
                "overpriced_rate": round(overpriced_rate, 4),
                "price_gap_pct_min": gap_min,
                "mean_gap_pct": round(statistics.mean(g for _, _, g in overpriced), 4),
                "surfaces": by_surface,
            },
            evidence_run_ids=sorted({s.run_id for s, _, _ in overpriced})[:MAX_EVIDENCE_RUN_IDS],
        ))
    return drafts


# ---------------------------------------------------------------------------
# TVD-03 — Loyalty and member value exposure
# ---------------------------------------------------------------------------

def detect_tvd_03(cycle_id: int, session: Session, thresholds: dict) -> List[FindingDraft]:
    """
    Member-value mentions = 0 (soa_incentive_scores.member_price_reflected
    never true) on account-linked runs (soa_queries.tier_name or
    membership_program set) where the fidelity scorer could evaluate
    member pricing.

    Reads scoring_grain='observation' rows only. Findings are grouped by
    (entity, merchant) with a per-surface (platform) breakdown in
    metric_snapshot — see detect_tvd_01's docstring for why.
    """
    min_sample = thresholds["min_sample_size"]

    rows = (
        session.query(SoaIncentiveScore, SoaRun.platform)
        .join(SoaRun, SoaRun.id == SoaIncentiveScore.run_id)
        .join(SoaQuery, SoaQuery.id == SoaRun.query_id)
        .filter(
            SoaRun.cycle_id == cycle_id,
            SoaIncentiveScore.scoring_grain == "observation",
            SoaIncentiveScore.status == "scored",
            SoaIncentiveScore.entity_id.isnot(None),
            SoaIncentiveScore.merchant_slug.isnot(None),
            SoaIncentiveScore.member_price_reflected.isnot(None),
            or_(SoaQuery.tier_name.isnot(None), SoaQuery.membership_program.isnot(None)),
        )
        .all()
    )

    by_cell: Dict[tuple, List[tuple]] = {}
    for score, platform in rows:
        by_cell.setdefault((score.entity_id, score.merchant_slug), []).append((score, platform))

    drafts: List[FindingDraft] = []
    for entity_id, merchant_slug in sorted(by_cell.keys()):
        cell_rows = by_cell[(entity_id, merchant_slug)]
        if len(cell_rows) < min_sample:
            continue
        if any(s.member_price_reflected for s, _ in cell_rows):
            continue  # trigger requires member-value mentions = 0

        by_surface: Dict[str, int] = {}
        for _, platform in cell_rows:
            by_surface[platform] = by_surface.get(platform, 0) + 1

        drafts.append(FindingDraft(
            entity_id=entity_id,
            play_id="TVD-03",
            dimension="Offer Completeness",
            severity=1.0,
            cells_affected=len(cell_rows),
            metric_snapshot={
                "merchant_slug": merchant_slug,
                "n_account_linked_scored_observations": len(cell_rows),
                "n_member_value_reflected": 0,
                "surfaces": by_surface,
            },
            evidence_run_ids=sorted({s.run_id for s, _ in cell_rows})[:MAX_EVIDENCE_RUN_IDS],
        ))
    return drafts


DETECTORS: Dict[str, Callable[[int, Session, dict], List[FindingDraft]]] = {
    "VIS-01": detect_vis_01,
    "VIS-05": detect_vis_05,
    "VIS-06": detect_vis_06,
    "VIS-07": detect_vis_07,
    "TVD-01": detect_tvd_01,
    "TVD-03": detect_tvd_03,
}


def detect_findings(cycle_id: int) -> Dict[str, int]:
    """
    Entry point. Validates the cycle is complete, runs every implemented
    detector, and (re)writes soa_findings for this cycle.

    Idempotent per cycle: deletes this cycle's prior findings before
    inserting the freshly computed set, so re-running produces identical
    counts for unchanged underlying data.

    Returns {play_id: findings_written} for every implemented play,
    including plays that fired zero findings this run.
    """
    session = session_factory()
    try:
        cycle = session.get(SoaCycle, cycle_id)
        if cycle is None:
            raise ValueError(f"Cycle {cycle_id} not found")
        if cycle.status != "complete":
            raise ValueError(f"Cycle {cycle_id} is not complete (status={cycle.status})")

        thresholds = load_thresholds()

        session.query(SoaFinding).filter(SoaFinding.cycle_id == cycle_id).delete()

        summary: Dict[str, int] = {}
        for play_id, detector_fn in DETECTORS.items():
            play_thresholds = _play_thresholds(thresholds, play_id)
            drafts = detector_fn(cycle_id, session, play_thresholds)

            for draft in drafts:
                if not draft.evidence_run_ids:
                    logger.warning(
                        "[finding_detector] %s finding for cycle=%s entity=%s has no evidence_run_ids",
                        play_id, cycle_id, draft.entity_id,
                    )
                session.add(SoaFinding(
                    cycle_id=cycle_id,
                    entity_id=draft.entity_id,
                    play_id=draft.play_id,
                    dimension=draft.dimension,
                    surface=draft.surface,
                    persona=draft.persona,
                    stage=draft.stage,
                    severity=draft.severity,
                    cells_affected=draft.cells_affected,
                    metric_snapshot=draft.metric_snapshot,
                    evidence_run_ids=draft.evidence_run_ids,
                ))
            summary[play_id] = len(drafts)

        session.commit()
        return summary
    finally:
        session.close()
