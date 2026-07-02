"""
Actions API — the AC3 recommendation engine (v1). Runs the deterministic
finding detector and recommendation mapper over a completed cycle's
existing metrics, and serves the resulting findings/recommendations to
the Actions page in the frontend.

See apps/api/app/services/finding_detector.py and
apps/api/app/services/recommendation_mapper.py for the detection/mapping
logic itself — this router only orchestrates them and shapes responses.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from soa_shared.database import session_factory
from soa_shared.models.soa_models import SoaCycle, SoaEntity, SoaFinding, SoaPlaybook, SoaRecommendation
from app.auth import get_current_user
from app.services.finding_detector import detect_findings
from app.services.recommendation_mapper import generate_recommendations
from app.schemas import (
    FindingResponse,
    GenerateActionsResponse,
    RecommendationResponse,
    RecommendationStatusUpdate,
)

router = APIRouter()


def _load_cycle_for_org(session, cycle_id: int, org_id: int) -> SoaCycle:
    cycle = session.get(SoaCycle, cycle_id)
    if cycle is None or cycle.organization_id != org_id:
        raise HTTPException(status_code=404, detail=f"Cycle {cycle_id} not found")
    return cycle


def _row_to_finding(finding: SoaFinding, entity_name: Optional[str]) -> FindingResponse:
    return FindingResponse(
        id=finding.id,
        cycle_id=finding.cycle_id,
        entity_id=finding.entity_id,
        entity_name=entity_name,
        play_id=finding.play_id,
        dimension=finding.dimension,
        surface=finding.surface,
        persona=finding.persona,
        stage=finding.stage,
        severity=finding.severity,
        cells_affected=finding.cells_affected,
        metric_snapshot=finding.metric_snapshot,
        evidence_run_ids=finding.evidence_run_ids or [],
        created_at=str(finding.created_at)[:19] if finding.created_at else None,
    )


@router.post("/cycles/{cycle_id}/actions/generate", response_model=GenerateActionsResponse)
def generate_actions(
    cycle_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Runs the detector then the mapper for this cycle. Idempotent — safe to re-run."""
    with session_factory() as session:
        _load_cycle_for_org(session, cycle_id, current_user["organization_id"])

    try:
        findings_by_play = detect_findings(cycle_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    recommendations_by_play = generate_recommendations(cycle_id)

    return GenerateActionsResponse(
        cycle_id=cycle_id,
        findings_by_play=findings_by_play,
        recommendations_by_play=recommendations_by_play,
        total_findings=sum(findings_by_play.values()),
        total_recommendations=len(recommendations_by_play),
    )


@router.get("/cycles/{cycle_id}/findings", response_model=list[FindingResponse])
def get_findings(
    cycle_id: int,
    play_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    with session_factory() as session:
        _load_cycle_for_org(session, cycle_id, current_user["organization_id"])

        q = session.query(SoaFinding).filter(SoaFinding.cycle_id == cycle_id)
        if play_id:
            q = q.filter(SoaFinding.play_id == play_id)
        findings = q.order_by(SoaFinding.severity.desc()).all()

        entity_ids = {f.entity_id for f in findings if f.entity_id is not None}
        entity_names = {}
        if entity_ids:
            for e in session.query(SoaEntity).filter(SoaEntity.id.in_(entity_ids)).all():
                entity_names[e.id] = e.name

        return [_row_to_finding(f, entity_names.get(f.entity_id)) for f in findings]


@router.get("/cycles/{cycle_id}/recommendations", response_model=list[RecommendationResponse])
def get_recommendations(
    cycle_id: int,
    include_suppressed: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    with session_factory() as session:
        _load_cycle_for_org(session, cycle_id, current_user["organization_id"])

        q = (
            session.query(SoaRecommendation, SoaPlaybook)
            .join(SoaPlaybook, SoaPlaybook.play_id == SoaRecommendation.play_id)
            .filter(SoaRecommendation.cycle_id == cycle_id)
        )
        if not include_suppressed:
            q = q.filter(SoaRecommendation.suppressed.is_(False))
        rows = q.order_by(SoaRecommendation.priority_score.desc()).all()

        if not rows:
            return []

        all_finding_ids = sorted({fid for rec, _ in rows for fid in (rec.finding_ids or [])})
        findings_by_id = {
            f.id: f
            for f in session.query(SoaFinding).filter(SoaFinding.id.in_(all_finding_ids)).all()
        }

        results = []
        for rec, play in rows:
            rec_findings = [findings_by_id[fid] for fid in (rec.finding_ids or []) if fid in findings_by_id]
            evidence_run_ids = sorted({rid for f in rec_findings for rid in (f.evidence_run_ids or [])})
            cells_affected = sum(f.cells_affected for f in rec_findings)

            results.append(RecommendationResponse(
                id=rec.id,
                cycle_id=rec.cycle_id,
                play_id=rec.play_id,
                pillar=play.pillar,
                owner=play.owner,
                effort=play.effort,
                detector_status=play.detector_status,
                play_text=play.play_text,
                mechanism_text=play.mechanism_text,
                expected_impact_text=play.expected_impact_text,
                evidence_spec=play.evidence_spec,
                dimensions=play.dimensions,
                finding_count=len(rec_findings),
                cells_affected=cells_affected,
                evidence_run_ids=evidence_run_ids,
                priority_score=rec.priority_score,
                status=rec.status,
                suppressed=rec.suppressed,
                created_at=str(rec.created_at)[:19] if rec.created_at else None,
                updated_at=str(rec.updated_at)[:19] if rec.updated_at else None,
            ))
        return results


@router.patch("/recommendations/{recommendation_id}", response_model=RecommendationResponse)
def update_recommendation(
    recommendation_id: int,
    data: RecommendationStatusUpdate,
    current_user: dict = Depends(get_current_user),
):
    with session_factory() as session:
        rec = session.get(SoaRecommendation, recommendation_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"Recommendation {recommendation_id} not found")

        cycle = session.get(SoaCycle, rec.cycle_id)
        if cycle is None or cycle.organization_id != current_user["organization_id"]:
            raise HTTPException(status_code=404, detail=f"Recommendation {recommendation_id} not found")

        rec.status = data.status
        session.commit()
        session.refresh(rec)

        play = session.get(SoaPlaybook, rec.play_id)
        findings = (
            session.query(SoaFinding)
            .filter(SoaFinding.id.in_(rec.finding_ids or []))
            .all()
        )
        evidence_run_ids = sorted({rid for f in findings for rid in (f.evidence_run_ids or [])})
        cells_affected = sum(f.cells_affected for f in findings)

        return RecommendationResponse(
            id=rec.id,
            cycle_id=rec.cycle_id,
            play_id=rec.play_id,
            pillar=play.pillar,
            owner=play.owner,
            effort=play.effort,
            detector_status=play.detector_status,
            play_text=play.play_text,
            mechanism_text=play.mechanism_text,
            expected_impact_text=play.expected_impact_text,
            evidence_spec=play.evidence_spec,
            dimensions=play.dimensions,
            finding_count=len(findings),
            cells_affected=cells_affected,
            evidence_run_ids=evidence_run_ids,
            priority_score=rec.priority_score,
            status=rec.status,
            suppressed=rec.suppressed,
            created_at=str(rec.created_at)[:19] if rec.created_at else None,
            updated_at=str(rec.updated_at)[:19] if rec.updated_at else None,
        )
