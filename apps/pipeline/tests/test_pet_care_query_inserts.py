"""
Insert tests for the Pet Care category and personas against the
soa_queries CHECK constraints as declared in soa_models (built from
soa_shared.constants). test_pet_care_migration.py pins the migration's
lists to the same constants, so together these cover the migrated schema.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

from soa_shared.models.soa_models import Organization, SoaQuery

_PET_CARE_PERSONAS = [
    "New Pet Parent",
    "Value-Conscious Pet Parent",
    "Health-Focused Pet Parent",
    "Subscription / Replenishment Pet Parent",
    "Premium / Quality-First Pet Parent",
]


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    # CreateTable rather than create_all: the model declares
    # ix_soa_queries_study_pattern twice (index=True and __table_args__),
    # and indexes are irrelevant to the CHECK constraints under test.
    with engine.begin() as conn:
        conn.execute(CreateTable(Organization.__table__))
        conn.execute(CreateTable(SoaQuery.__table__))
        conn.exec_driver_sql("INSERT INTO organizations (id, name) VALUES (1, 'test')")
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


def _query(code, **overrides):
    fields = dict(
        query_code=code,
        query_text="What is the best food for a new puppy?",
        category="Pet Care",
        stage="Research",
        specificity="Broad",
        persona="New Pet Parent",
        organization_id=1,
    )
    fields.update(overrides)
    return SoaQuery(**fields)


@pytest.mark.parametrize("persona", _PET_CARE_PERSONAS)
def test_pet_care_row_inserts_with_each_new_persona(session, persona):
    session.add(_query(f"PET-{persona}", persona=persona))
    session.commit()
    row = session.query(SoaQuery).one()
    assert (row.category, row.persona) == ("Pet Care", persona)


def test_unknown_category_still_rejected(session):
    session.add(_query("PET-BAD-CAT", category="Aquarium Care"))
    with pytest.raises(IntegrityError, match="ck_soa_queries_category"):
        session.commit()


def test_unknown_persona_still_rejected(session):
    session.add(_query("PET-BAD-PERSONA", persona="Cat Person"))
    with pytest.raises(IntegrityError, match="ck_soa_queries_persona"):
        session.commit()
