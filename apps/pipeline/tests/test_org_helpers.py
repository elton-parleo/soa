"""
Tests for soa_shared/org_helpers.py — resolving/creating the dedicated
'Parleo Lead Gen' organization used by all SoA Lite data.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from soa_shared.models.soa_models import Organization
from soa_shared.org_helpers import get_or_create_leadgen_org, LEADGEN_ORG_NAME


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Organization.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_creates_org_when_absent(session):
    org_id = get_or_create_leadgen_org(session)
    session.commit()

    org = session.get(Organization, org_id)
    assert org.name == LEADGEN_ORG_NAME


def test_returns_existing_org_id_without_duplicating(session):
    first_id = get_or_create_leadgen_org(session)
    session.commit()

    second_id = get_or_create_leadgen_org(session)

    assert first_id == second_id
    assert session.query(Organization).filter_by(name=LEADGEN_ORG_NAME).count() == 1


def test_does_not_commit_the_session(session):
    get_or_create_leadgen_org(session)
    session.rollback()

    assert session.query(Organization).count() == 0
