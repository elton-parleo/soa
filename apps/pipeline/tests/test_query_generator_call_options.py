"""
Tests for the two options added to _call_openai_and_validate: the
temperature parameter (0.8 by default, so every pre-existing caller is
byte-for-byte unchanged) and the stamp parameter (fields the CALLER
decides, merged in before validation rather than left to the model).

stamp exists because study_pattern is a property of the study, not of
each question. Letting the model emit it per row lets a single study end
up with a mix of 'retailer' and 'brand_vs_brand' rows, which silently
changes the coding rubric from query to query. Stamping happens BEFORE
_validate_generated_row so the value is still checked against
QUERY_CONSTRAINTS — a caller cannot use it to smuggle in a value the DB
would reject.
"""
import json
from unittest.mock import MagicMock, patch

from generation.query_generator import _call_openai_and_validate


def _row(**overrides):
    row = dict(
        query_text="What is the best serum?",
        category="Skincare",
        stage="Research",
        specificity="Mid",
        persona="Beauty Enthusiast",
        study_pattern="brand_vs_brand",
        status="Active",
        soa_focus="Mention Rate",
        rationale="test",
    )
    row.update(overrides)
    return row


def _openai_returning(payload):
    """Patches the OpenAI client so no network call happens; returns the
    mock so the test can inspect the kwargs the helper actually sent."""
    client = MagicMock()
    message = MagicMock()
    message.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    client.chat.completions.create.return_value = MagicMock(choices=[choice])
    return client


def test_temperature_defaults_to_0_8():
    client = _openai_returning([_row()])
    with patch("generation.query_generator.OpenAI", return_value=client):
        _call_openai_and_validate("prompt", "key")

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["temperature"] == 0.8


def test_temperature_is_forwarded_when_given():
    client = _openai_returning([_row()])
    with patch("generation.query_generator.OpenAI", return_value=client):
        _call_openai_and_validate("prompt", "key", temperature=0)

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["temperature"] == 0


def test_stamp_overrides_whatever_the_model_emitted():
    client = _openai_returning([_row(study_pattern="retailer")])
    with patch("generation.query_generator.OpenAI", return_value=client):
        rows, reason = _call_openai_and_validate(
            "prompt", "key", stamp={"study_pattern": "brand_vs_brand"},
        )

    assert reason is None
    assert rows[0]["study_pattern"] == "brand_vs_brand"


def test_stamp_fills_in_a_field_the_model_omitted_entirely():
    """The real use: the prompt stops asking for study_pattern at all, so
    the model never emits it, and validation would otherwise reject every
    row."""
    row = _row()
    del row["study_pattern"]
    client = _openai_returning([row])
    with patch("generation.query_generator.OpenAI", return_value=client):
        rows, reason = _call_openai_and_validate(
            "prompt", "key", stamp={"study_pattern": "retailer"},
        )

    assert reason is None
    assert len(rows) == 1
    assert rows[0]["study_pattern"] == "retailer"


def test_a_stamped_value_is_still_validated():
    """Stamping is not a bypass — it decides who chooses the value, not
    whether it is checked. An out-of-range stamp fails validation exactly
    as an out-of-range model output would."""
    client = _openai_returning([_row()])
    with patch("generation.query_generator.OpenAI", return_value=client):
        rows, reason = _call_openai_and_validate(
            "prompt", "key", stamp={"study_pattern": "not_a_real_pattern"},
        )

    assert rows == []
    assert reason is not None
    assert "study_pattern" in reason


def test_no_stamp_leaves_rows_exactly_as_parsed():
    client = _openai_returning([_row(study_pattern="retailer")])
    with patch("generation.query_generator.OpenAI", return_value=client):
        rows, _ = _call_openai_and_validate("prompt", "key")

    assert rows[0]["study_pattern"] == "retailer"
