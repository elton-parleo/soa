"""
Recommendation mapper for the AC3 Actions feature (v1).

Groups soa_findings by play_id per cycle into one soa_recommendations row
per (cycle, play) — the "aggregate all cells where the play fired" step
described in docs/playbook_v1.md. Always recomputes from the current
soa_findings rows rather than reading soa_recommendations mid-run, so a
re-run is deterministic and idempotent per cycle.
"""
import logging
from typing import Dict, List, Set, Tuple

from sqlalchemy.orm import Session

from soa_shared.database import session_factory
from soa_shared.models.soa_models import SoaCycle, SoaFinding, SoaPlaybook, SoaRecommendation

logger = logging.getLogger(__name__)

EFFORT_WEIGHTS = {"low": 1, "medium": 2, "high": 3}

# TVD-07 is a composite play — see docs/playbook_v1.md "Seeding notes":
# suppress it as a standalone recommendation when its constituent plays
# fire on the same cells, and present it as the outcome framing instead.
# (TVD-07 has no detector in v1, so this is currently a no-op — kept so
# the mapper is already correct once that detector is added.)
COMPOSITE_SUPPRESSION: Dict[str, List[str]] = {
    "TVD-07": ["TVD-01", "TVD-02", "TVD-04", "TVD-06"],
}


def _priority_score(findings: List[SoaFinding], effort: str) -> float:
    """
    priority_score = mean(severity) x cells_affected / effort_weight

    mean(severity) is the average severity (0-1) across every finding
    grouped into this recommendation. cells_affected is the sum of each
    finding's cell count, so a play firing wide outweighs one firing
    narrow. effort_weight (low=1, medium=2, high=3) divides the score
    down for costlier remediations. Simple and explainable by design,
    not a model: higher severity, wider blast radius, and lower effort
    all push a recommendation up the list.
    """
    mean_severity = sum(f.severity for f in findings) / len(findings)
    total_cells = sum(f.cells_affected for f in findings)
    weight = EFFORT_WEIGHTS[effort]
    return (mean_severity * total_cells) / weight


def _is_suppressed(
    play_id: str,
    findings: List[SoaFinding],
    findings_index: Set[Tuple[str, int]],
) -> bool:
    constituent_plays = COMPOSITE_SUPPRESSION.get(play_id)
    if not constituent_plays:
        return False
    for finding in findings:
        for constituent in constituent_plays:
            if (constituent, finding.entity_id) in findings_index:
                return True
    return False


def generate_recommendations(cycle_id: int) -> Dict[str, int]:
    """
    Entry point. Rebuilds this cycle's recommendations from the current
    soa_findings rows. Idempotent per cycle in the sense that matters for
    a repeatedly-clicked "Regenerate": re-running with unchanged findings
    produces the same rows with the same ids, and a play_id that keeps
    firing keeps its existing status (e.g. 'accepted') rather than
    resetting to 'proposed' — only plays that stop firing are deleted,
    and only newly-firing plays are inserted as 'proposed'.

    Returns {play_id: 1} for every play with a recommendation this run
    (each play maps to at most one recommendation per cycle, per the
    uq_soa_recommendations_cycle_play constraint).
    """
    session: Session = session_factory()
    try:
        cycle = session.get(SoaCycle, cycle_id)
        if cycle is None:
            raise ValueError(f"Cycle {cycle_id} not found")

        findings = session.query(SoaFinding).filter(SoaFinding.cycle_id == cycle_id).all()

        existing = {
            r.play_id: r
            for r in session.query(SoaRecommendation).filter(SoaRecommendation.cycle_id == cycle_id).all()
        }

        if not findings:
            for rec in existing.values():
                session.delete(rec)
            session.commit()
            return {}

        by_play: Dict[str, List[SoaFinding]] = {}
        for f in findings:
            by_play.setdefault(f.play_id, []).append(f)

        findings_index: Set[Tuple[str, int]] = {(f.play_id, f.entity_id) for f in findings}

        play_ids = sorted(by_play.keys())
        plays = {
            p.play_id: p
            for p in session.query(SoaPlaybook).filter(SoaPlaybook.play_id.in_(play_ids)).all()
        }

        summary: Dict[str, int] = {}
        for play_id in play_ids:
            play = plays.get(play_id)
            if play is None:
                logger.warning(
                    "[recommendation_mapper] play_id=%s has findings but no soa_playbook row", play_id,
                )
                continue

            play_findings = by_play[play_id]
            suppressed = _is_suppressed(play_id, play_findings, findings_index)
            priority_score = _priority_score(play_findings, play.effort)
            finding_ids = [f.id for f in play_findings]

            rec = existing.pop(play_id, None)
            if rec is not None:
                rec.finding_ids = finding_ids
                rec.priority_score = priority_score
                rec.suppressed = suppressed
                # rec.status is intentionally left untouched — a play that
                # keeps firing keeps whatever status the user set on it.
            else:
                session.add(SoaRecommendation(
                    cycle_id=cycle_id,
                    play_id=play_id,
                    finding_ids=finding_ids,
                    priority_score=priority_score,
                    suppressed=suppressed,
                ))
            summary[play_id] = 1

        # Any recommendation left in `existing` is for a play that no
        # longer fires this run — its findings are gone, so it goes too.
        for rec in existing.values():
            session.delete(rec)

        session.commit()
        return summary
    finally:
        session.close()
