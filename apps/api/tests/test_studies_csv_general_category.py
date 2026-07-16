"""
Tests that 'General' — added to QUERY_CATEGORIES for SoA Lite — passes the
CSV upload validator, since it's sourced from QUERY_CONSTRAINTS without any
dedicated category logic.
"""
from app.routers.studies import _validate_csv_row


def _valid_row(**overrides):
    row = dict(
        query_text="What is the best general product for me?",
        category="General",
        stage="Awareness",
        specificity="Broad",
        persona="Casual / Gift Buyer",
        study_type="lite-abcd1234",
        study_pattern="brand_vs_brand",
        status="Active",
    )
    row.update(overrides)
    return row


def test_general_category_passes_csv_validation():
    cleaned, errors = _validate_csv_row(_valid_row(), row_num=1)
    assert errors == []
    assert cleaned["category"] == "General"
