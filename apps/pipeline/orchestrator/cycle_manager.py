"""
Creates and manages SoaCycle records.
"""
import datetime

from sqlalchemy.orm import Session

from soa_shared.models.soa_models import SoaCycle, SoaQuery


def create_cycle(cycle_code: str, session: Session) -> SoaCycle:
    """
    Creates a new planned cycle. total_runs_planned is calculated as:
      active_queries × 3 platforms × 5 runs_each
    """
    active_queries = (
        session.query(SoaQuery)
        .filter(SoaQuery.status == "Active")
        .count()
    )
    total_planned = active_queries * 3 * 5

    cycle = SoaCycle(
        cycle_code=cycle_code,
        start_date=datetime.date.today(),
        total_runs_planned=total_planned,
        status="planned",
    )
    session.add(cycle)
    session.flush()
    return cycle
