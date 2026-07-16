"""
Tests for the SoaLiteRequest model's DB-enforced constraints: the status
CHECK and token uniqueness. Uses a real in-memory SQLite database (via
SQLAlchemy) rather than mocks, same convention as test_scope_resolution.py,
so the constraints declared on the ORM model are actually exercised.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from soa_shared.models.soa_models import Organization, SoaLiteRequest


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Organization.__table__.create(engine)
    SoaLiteRequest.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    org = Organization(name="Parleo Lead Gen")
    s.add(org)
    s.commit()
    s.org_id = org.id
    yield s
    s.close()


def _make_request(session, **overrides):
    defaults = dict(
        token="a" * 32,
        brand_name="Acme Co",
        status="pending",
        organization_id=session.org_id,
    )
    defaults.update(overrides)
    return SoaLiteRequest(**defaults)


def test_valid_row_inserts_successfully(session):
    session.add(_make_request(session))
    session.commit()
    assert session.query(SoaLiteRequest).count() == 1


def test_valid_statuses_are_all_accepted(session):
    for i, status in enumerate(
        ("pending", "generating", "running", "complete", "failed")
    ):
        session.add(_make_request(session, token=f"token-{i}", status=status))
    session.commit()
    assert session.query(SoaLiteRequest).count() == 5


def test_invalid_status_rejected(session):
    session.add(_make_request(session, status="bogus"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_duplicate_token_rejected(session):
    session.add(_make_request(session, token="dupe-token"))
    session.commit()

    session.add(_make_request(session, token="dupe-token"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_null_brand_name_rejected(session):
    session.add(_make_request(session, brand_name=None))
    with pytest.raises(IntegrityError):
        session.commit()
