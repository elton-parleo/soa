"""
Helpers for resolving well-known organizations by name.
"""
from sqlalchemy.orm import Session

from soa_shared.models.soa_models import Organization

LEADGEN_ORG_NAME = "Parleo Lead Gen"


def get_or_create_leadgen_org(session: Session) -> int:
    """
    Returns the id of the dedicated 'Parleo Lead Gen' organization, creating
    it if it does not exist yet. All SoA Lite data (soa_lite_requests and the
    soa_queries/soa_cycles/soa_entities rows it generates) lives under this
    org, kept separate from authenticated-product organizations.

    Flushes but does not commit — the caller owns the transaction.
    """
    org = session.query(Organization).filter_by(name=LEADGEN_ORG_NAME).first()
    if org:
        return org.id

    org = Organization(name=LEADGEN_ORG_NAME)
    session.add(org)
    session.flush()
    return org.id
