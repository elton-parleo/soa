"""
Tests that 'General' — added to QUERY_CATEGORIES for SoA Lite — passes the
AI-generation row validator, since it's sourced from QUERY_CONSTRAINTS
without any dedicated category logic.
"""
from generation.query_generator import _validate_generated_row


def _valid_row(**overrides):
    row = dict(
        query_text="What is the best general product for me?",
        category="General",
        stage="Awareness",
        specificity="Broad",
        persona="Casual / Gift Buyer",
        status="Active",
        study_pattern="brand_vs_brand",
        subscription_state="not_subscribed",
        soa_focus="Mention Rate",
        rationale="Tests general category acceptance.",
    )
    row.update(overrides)
    return row


def test_general_category_passes_validation():
    cleaned, errors = _validate_generated_row(_valid_row())
    assert errors == []
    assert cleaned["category"] == "General"
