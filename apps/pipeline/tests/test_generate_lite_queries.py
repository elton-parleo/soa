"""
Tests for generate_lite_queries' stage-distribution enforcement: exactly
LITE_QUERIES_PER_STAGE (3) queries per QUERY_STAGES stage, a single
targeted retry for shortfall stages, and LiteGenerationError if the
shortfall persists after that retry (a partial lite study would produce a
misleading report). Mocks _call_openai_and_validate so no real OpenAI call
is made; _validate_generated_row's own behavior is covered elsewhere.
"""
from unittest.mock import patch

import pytest

from generation.query_generator import (
    LITE_QUERIES_PER_STAGE,
    LiteGenerationError,
    generate_lite_queries,
)
from soa_shared.constants import QUERY_STAGES


def _row(stage, suffix=""):
    return {
        'query_text': f"Question about {stage}{suffix}",
        'category': 'General',
        'stage': stage,
        'specificity': 'Broad',
        'persona': 'Casual / Gift Buyer',
        'study_pattern': 'brand_vs_brand',
        'status': 'Active',
        'subscription_state': 'not_subscribed',
        'soa_focus': 'Mention Rate',
        'rationale': 'test',
    }


def _perfect_batch():
    return [
        _row(stage, f"-{i}")
        for stage in QUERY_STAGES
        for i in range(LITE_QUERIES_PER_STAGE)
    ]


def _stage_counts(rows):
    counts = {}
    for row in rows:
        counts[row['stage']] = counts.get(row['stage'], 0) + 1
    return counts


def test_perfect_distribution_needs_no_retry():
    with patch("generation.query_generator._call_openai_and_validate") as mock_call:
        mock_call.return_value = _perfect_batch()
        rows = generate_lite_queries("Acme", ["Rival"], api_key="k")

    assert mock_call.call_count == 1
    assert len(rows) == 12
    assert _stage_counts(rows) == {s: 3 for s in QUERY_STAGES}


def test_excess_rows_for_a_stage_are_capped_not_overcounted():
    batch = [_row(stage, f"-{i}") for stage in QUERY_STAGES for i in range(5 if stage == "Awareness" else 3)]

    with patch("generation.query_generator._call_openai_and_validate") as mock_call:
        mock_call.return_value = batch
        rows = generate_lite_queries("Acme", [], api_key="k")

    assert mock_call.call_count == 1
    assert _stage_counts(rows) == {s: 3 for s in QUERY_STAGES}


def test_shortfall_then_successful_retry():
    first_batch = [
        _row(stage, f"-first-{i}")
        for stage in QUERY_STAGES
        for i in range(2 if stage == "Awareness" else 3)
    ]
    retry_batch = [_row("Awareness", "-retry")]

    with patch("generation.query_generator._call_openai_and_validate") as mock_call:
        mock_call.side_effect = [first_batch, retry_batch]
        rows = generate_lite_queries("Acme", ["Rival"], api_key="k")

    assert mock_call.call_count == 2
    assert _stage_counts(rows) == {s: 3 for s in QUERY_STAGES}

    retry_prompt = mock_call.call_args_list[1][0][0]
    assert "Awareness" in retry_prompt
    assert "Research" not in retry_prompt.split("Distribute")[1].split("Critical rule")[0]


def test_shortfall_persists_after_retry_raises():
    first_batch = [
        _row(stage, f"-first-{i}")
        for stage in QUERY_STAGES
        for i in range(1 if stage == "Comparison" else 3)
    ]
    retry_batch = []  # still short

    with patch("generation.query_generator._call_openai_and_validate") as mock_call:
        mock_call.side_effect = [first_batch, retry_batch]
        with pytest.raises(LiteGenerationError):
            generate_lite_queries("Acme", ["Rival"], api_key="k")

    assert mock_call.call_count == 2


def test_partial_retry_success_still_raises_if_short():
    first_batch = [
        _row(stage, f"-first-{i}")
        for stage in QUERY_STAGES
        for i in range(1 if stage == "Comparison" else 3)
    ]
    # Retry returns only 1 of the 2 needed Comparison rows.
    retry_batch = [_row("Comparison", "-retry")]

    with patch("generation.query_generator._call_openai_and_validate") as mock_call:
        mock_call.side_effect = [first_batch, retry_batch]
        with pytest.raises(LiteGenerationError, match="Comparison"):
            generate_lite_queries("Acme", ["Rival"], api_key="k")
