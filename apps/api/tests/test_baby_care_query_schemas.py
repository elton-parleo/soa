"""
Pydantic validation tests for Baby Care query attributes.
Asserts that QueryCreate and QueryUpdate accept the new category, stage, and
personas introduced for the first non-beauty vertical (Pampers/Baby Care).
"""
import pytest
from pydantic import ValidationError

from app.schemas import QueryCreate, QueryUpdate

# ── category ──────────────────────────────────────────────────────────────────

def test_query_create_accepts_baby_care_category():
    q = QueryCreate(query_text="best diaper for newborn", category="Baby Care")
    assert q.category == "Baby Care"


def test_query_update_accepts_baby_care_category():
    q = QueryUpdate(category="Baby Care")
    assert q.category == "Baby Care"


def test_existing_category_still_accepted():
    q = QueryCreate(query_text="best serum", category="Skincare")
    assert q.category == "Skincare"


def test_bogus_category_rejected():
    with pytest.raises(ValidationError, match="category"):
        QueryCreate(query_text="test", category="Pet Care")


# ── stage ─────────────────────────────────────────────────────────────────────

def test_query_create_accepts_awareness_stage():
    q = QueryCreate(query_text="newborn keeps leaking overnight, what do I do",
                    stage="Awareness")
    assert q.stage == "Awareness"


def test_query_update_accepts_awareness_stage():
    q = QueryUpdate(stage="Awareness")
    assert q.stage == "Awareness"


def test_existing_stages_still_accepted():
    for stage in ("Research", "Comparison", "Ready to Buy"):
        q = QueryCreate(query_text="test", stage=stage)
        assert q.stage == stage


def test_bogus_stage_rejected():
    with pytest.raises(ValidationError, match="stage"):
        QueryCreate(query_text="test", stage="Discovery")


# ── personas ──────────────────────────────────────────────────────────────────

NEW_PERSONAS = [
    "New / First-Time Parent",
    "Value-Conscious Parent",
    "Sensitive-Skin Baby Parent",
    "Subscription / Replenishment Parent",
    "Eco-Conscious Parent",
]


@pytest.mark.parametrize("persona", NEW_PERSONAS)
def test_query_create_accepts_baby_care_persona(persona):
    q = QueryCreate(query_text="best diaper", persona=persona)
    assert q.persona == persona


@pytest.mark.parametrize("persona", NEW_PERSONAS)
def test_query_update_accepts_baby_care_persona(persona):
    q = QueryUpdate(persona=persona)
    assert q.persona == persona


def test_existing_personas_still_accepted():
    for persona in ("Casual / Gift Buyer", "Value-Conscious", "Beauty Enthusiast",
                    "Problem-Skin Sufferer", "Eco-Conscious / Minimalist",
                    "Oral Health Symptom Sufferer"):
        q = QueryCreate(query_text="test", persona=persona)
        assert q.persona == persona


def test_bogus_persona_rejected():
    with pytest.raises(ValidationError, match="persona"):
        QueryCreate(query_text="test", persona="Diaper Hoarder")
