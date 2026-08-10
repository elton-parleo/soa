"""
Tests for generation/query_generator.py::_validate_generated_row and
_deterministic_failure_reason — the guard against a repeat of the
subscription_state regression: a field added to QUERY_CONSTRAINTS with
an allowed-values check, nullable in the DB, that the general generation
prompt doesn't request, silently rejected 100% of every generated row.

test_a_row_shaped_like_the_actual_general_prompt_output_is_valid is the
recurrence guard specifically: it mirrors _build_prompt's own documented
JSON key list byte for byte (query_text, category, stage, specificity,
persona, study_pattern, status, soa_focus, rationale — no
subscription_state) rather than a hand-picked "valid" fixture, so the
next constrained field added to the model without updating this list
(or _NULLABLE_CONSTRAINED_FIELDS) breaks this test instead of silently
zeroing out production generation.
"""
from generation.query_generator import (
    _NULLABLE_CONSTRAINED_FIELDS,
    _deterministic_failure_reason,
    _validate_generated_row,
)


# Exactly the JSON keys _build_prompt's docstring/prompt text asks the
# model for — see query_generator.py:
#   "query_text, category, stage, specificity, persona, study_pattern,
#    status, soa_focus, rationale"
_GENERAL_PROMPT_OUTPUT_KEYS = (
    'query_text', 'category', 'stage', 'specificity',
    'persona', 'study_pattern', 'status', 'soa_focus', 'rationale',
)


def _general_prompt_row(**overrides):
    row = dict(
        query_text="What's the best lightweight moisturizer for oily skin?",
        category="Skincare",
        stage="Research",
        specificity="Mid",
        persona="Beauty Enthusiast",
        study_pattern="brand_vs_brand",
        status="Active",
        soa_focus="Mention Rate, RSI",
        rationale="Tests research-stage discovery.",
    )
    row.update(overrides)
    return row


def test_a_row_shaped_like_the_actual_general_prompt_output_is_valid():
    """The recurrence guard: this row has EXACTLY the keys _build_prompt
    actually requests — no subscription_state, no extra field — so a
    future constrained field added to the model without updating
    _NULLABLE_CONSTRAINED_FIELDS (or the prompt) fails this assertion
    instead of silently zeroing out production generation."""
    row = _general_prompt_row()
    assert set(row.keys()) == set(_GENERAL_PROMPT_OUTPUT_KEYS)

    cleaned, errors = _validate_generated_row(row)
    assert errors == []
    assert cleaned['subscription_state'] is None


def test_subscription_state_is_nullable_and_defaults_to_none_when_absent():
    cleaned, errors = _validate_generated_row(_general_prompt_row())
    assert errors == []
    assert 'subscription_state' in _NULLABLE_CONSTRAINED_FIELDS
    assert cleaned['subscription_state'] is None


def test_subscription_state_is_still_validated_when_a_value_is_present():
    """Nullable doesn't mean unchecked — a garbage non-null value must
    still be rejected, only its absence is treated as valid."""
    cleaned, errors = _validate_generated_row(_general_prompt_row(subscription_state="maybe"))
    assert any(field == 'subscription_state' for field, _ in errors)


def test_subscription_state_valid_value_passes():
    cleaned, errors = _validate_generated_row(_general_prompt_row(subscription_state="not_subscribed"))
    assert errors == []
    assert cleaned['subscription_state'] == "not_subscribed"


def test_a_genuinely_required_field_missing_is_still_rejected():
    """Only fields in _NULLABLE_CONSTRAINED_FIELDS get the None pass —
    every other QUERY_CONSTRAINTS field (all NOT NULL in the schema)
    stays strict, exactly as before this fix."""
    cleaned, errors = _validate_generated_row(_general_prompt_row(category=None))
    assert any(field == 'category' for field, _ in errors)


def test_empty_query_text_is_rejected():
    cleaned, errors = _validate_generated_row(_general_prompt_row(query_text="   "))
    assert any(field == 'query_text' for field, _ in errors)


# ─── _deterministic_failure_reason ────────────────────────────────────────

def test_deterministic_reason_when_every_row_fails_on_the_same_field():
    row_errors = [
        [('subscription_state', "subscription_state=None not in allowed values")],
        [('subscription_state', "subscription_state=None not in allowed values")],
    ]
    reason = _deterministic_failure_reason(row_errors, total_rows=2)
    assert reason is not None
    assert 'subscription_state' in reason


def test_no_reason_when_only_some_rows_fail():
    row_errors = [
        [('subscription_state', "subscription_state=None not in allowed values")],
    ]
    reason = _deterministic_failure_reason(row_errors, total_rows=2)  # only 1 of 2 failed
    assert reason is None


def test_no_reason_when_failing_rows_dont_share_a_common_field():
    row_errors = [
        [('category', "category=None not in allowed values")],
        [('stage', "stage='bogus' not in allowed values")],
    ]
    reason = _deterministic_failure_reason(row_errors, total_rows=2)
    assert reason is None


def test_no_reason_when_nothing_failed():
    assert _deterministic_failure_reason([], total_rows=0) is None
