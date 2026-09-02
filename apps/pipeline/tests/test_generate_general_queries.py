"""
Tests for the general path's stage-distribution enforcement
(generate_general_queries) and for the helper it shares with lite
(_fill_stage_buckets).

The lite path already enforced its distribution; the general path had no
enforcement at all, which is how a fifty-question study came back with a
lopsided funnel. The difference that survives the sharing is what happens
on a residual shortfall: lite raises, general reports. Both behaviours are
locked down here, and test_generate_lite_queries.py — unchanged — is what
proves lite's own output did not move.

Mocks _call_openai_and_validate, so no real OpenAI call is made.
"""
from unittest.mock import patch

import pytest

from generation.query_generator import (
    REPLACEMENT_ROUNDS,
    RETRY_BUDGET_GENERAL,
    SHORTFALL_RAISE,
    SHORTFALL_REPORT,
    LiteGenerationError,
    _build_general_prompt,
    _fill_stage_buckets,
    generate_general_queries,
)

ALLOWED = ['Skincare', 'Makeup', 'Fragrance']


def _row(stage, suffix="", category="Skincare"):
    return {
        'query_text': f"Question about {stage}{suffix}",
        'category': category,
        'stage': stage,
        'specificity': 'Mid',
        'persona': 'Beauty Enthusiast',
        'study_pattern': 'retailer',
        'status': 'Active',
        'subscription_state': None,
        'soa_focus': 'Mention Rate',
        'rationale': 'test',
    }


def _counts(rows):
    counts = {}
    for row in rows:
        counts[row['stage']] = counts.get(row['stage'], 0) + 1
    return counts


def _generate(targets, batches, allowed=ALLOWED, pattern='retailer'):
    with patch("generation.query_generator._call_openai_and_validate") as mock_call:
        mock_call.side_effect = [(b, None) for b in batches]
        rows, report = generate_general_queries(
            study_name="Prestige Beauty",
            description="A study",
            stage_targets=targets,
            allowed_categories=allowed,
            study_pattern=pattern,
            api_key="k",
        )
    return rows, report, mock_call


# ─── _fill_stage_buckets ──────────────────────────────────────────────────

def test_helper_caps_a_stage_at_its_target():
    targets = {'Awareness': 2, 'Research': 2}
    batch = [_row('Awareness', f"-{i}") for i in range(5)] + [
        _row('Research', f"-{i}") for i in range(2)
    ]
    with patch("generation.query_generator._call_openai_and_validate") as mock_call:
        mock_call.return_value = (batch, None)
        result = _fill_stage_buckets(
            targets=targets, build_prompt=lambda s, a: "p", api_key="k",
            retry_budget=1, on_shortfall=SHORTFALL_REPORT,
        )

    assert len(result['buckets']['Awareness']) == 2
    assert result['shortfall'] == {}


def test_helper_retries_only_the_short_stages():
    targets = {'Awareness': 2, 'Research': 2}
    first = [_row('Awareness', "-0"), _row('Research', "-0"), _row('Research', "-1")]
    seen_shortfalls = []

    def _build(shortfall, accepted):
        seen_shortfalls.append(dict(shortfall))
        return "prompt"

    with patch("generation.query_generator._call_openai_and_validate") as mock_call:
        mock_call.side_effect = [(first, None), ([_row('Awareness', "-1")], None)]
        result = _fill_stage_buckets(
            targets=targets, build_prompt=_build, api_key="k",
            retry_budget=1, on_shortfall=SHORTFALL_REPORT,
        )

    assert seen_shortfalls[0] == {'Awareness': 2, 'Research': 2}
    assert seen_shortfalls[1] == {'Awareness': 1}     # Research is full
    assert result['shortfall'] == {}


def test_helper_passes_accepted_rows_to_the_retry_prompt():
    """A retry that cannot see what the first call produced will just
    reproduce it."""
    targets = {'Awareness': 2}
    seen_accepted = []

    def _build(shortfall, accepted):
        seen_accepted.append([r['query_text'] for r in accepted])
        return "prompt"

    with patch("generation.query_generator._call_openai_and_validate") as mock_call:
        mock_call.side_effect = [([_row('Awareness', "-0")], None),
                                 ([_row('Awareness', "-1")], None)]
        _fill_stage_buckets(
            targets=targets, build_prompt=_build, api_key="k",
            retry_budget=1, on_shortfall=SHORTFALL_REPORT,
        )

    assert seen_accepted[0] == []
    assert seen_accepted[1] == ["Question about Awareness-0"]


def test_helper_raise_behaviour_uses_the_callers_message():
    targets = {'Comparison': 3}
    with patch("generation.query_generator._call_openai_and_validate") as mock_call:
        mock_call.side_effect = [([], None), ([], None)]
        with pytest.raises(LiteGenerationError, match="my own wording"):
            _fill_stage_buckets(
                targets=targets, build_prompt=lambda s, a: "p", api_key="k",
                retry_budget=1, on_shortfall=SHORTFALL_RAISE,
                shortfall_message=lambda s: f"my own wording {s}",
            )


def test_helper_report_behaviour_returns_the_shortfall_instead_of_raising():
    targets = {'Comparison': 3}
    with patch("generation.query_generator._call_openai_and_validate") as mock_call:
        mock_call.side_effect = [([], None), ([], None)]
        result = _fill_stage_buckets(
            targets=targets, build_prompt=lambda s, a: "p", api_key="k",
            retry_budget=1, on_shortfall=SHORTFALL_REPORT,
        )

    assert result['shortfall'] == {'Comparison': 3}


def test_helper_stops_calling_once_every_stage_is_full():
    targets = {'Awareness': 1}
    with patch("generation.query_generator._call_openai_and_validate") as mock_call:
        mock_call.return_value = ([_row('Awareness')], None)
        result = _fill_stage_buckets(
            targets=targets, build_prompt=lambda s, a: "p", api_key="k",
            retry_budget=2, on_shortfall=SHORTFALL_REPORT,
        )

    assert result['calls'] == 1


# ─── generate_general_queries: reports, never raises ──────────────────────

def test_a_persistent_shortfall_reports_rather_than_raising():
    """Hard-failing a fifty-question study after five batches, and
    discarding forty-seven good queries because three are missing, is
    worse than saying so."""
    targets = {'Awareness': 2, 'Comparison': 3}
    delivered = [_row('Awareness', "-0"), _row('Awareness', "-1")]
    batches = [delivered] + [[]] * 10

    rows, report, _ = _generate(targets, batches)

    assert len(rows) == 2                      # the good rows are kept
    assert report['shortfall_by_stage'] == {'Comparison': 3}


def test_report_names_requested_and_delivered_per_stage():
    targets = {'Awareness': 2, 'Research': 3, 'Comparison': 1}
    batch = (
        [_row('Awareness', f"-{i}") for i in range(2)]
        + [_row('Research', f"-{i}") for i in range(3)]
        + [_row('Comparison', "-0")]
    )
    rows, report, _ = _generate(targets, [batch])

    assert report['requested_by_stage'] == {'Awareness': 2, 'Research': 3, 'Comparison': 1}
    assert report['delivered_by_stage'] == {'Awareness': 2, 'Research': 3, 'Comparison': 1}
    assert report['shortfall_by_stage'] == {}
    assert _counts(rows) == {'Awareness': 2, 'Research': 3, 'Comparison': 1}


def test_delivered_counts_are_accurate_when_a_stage_is_partially_filled():
    targets = {'Awareness': 3, 'Research': 2}
    batches = [[_row('Awareness', "-0"), _row('Research', "-0"), _row('Research', "-1")]] + [[]] * 10

    rows, report, _ = _generate(targets, batches)

    assert report['delivered_by_stage'] == {'Awareness': 1, 'Research': 2}
    assert report['shortfall_by_stage'] == {'Awareness': 2}


def test_the_study_pattern_is_stamped_not_left_to_the_model():
    """study_pattern is a property of the study. Letting the model emit
    it per row lets one study end up 'mixed', which changes the coding
    rubric from query to query."""
    targets = {'Awareness': 1}
    with patch("generation.query_generator._call_openai_and_validate") as mock_call:
        mock_call.return_value = ([_row('Awareness')], None)
        generate_general_queries(
            study_name="S", description="d", stage_targets=targets,
            allowed_categories=ALLOWED, study_pattern="brand_at_retail",
            api_key="k",
        )

    assert mock_call.call_args.kwargs['stamp'] == {'study_pattern': 'brand_at_retail'}


def test_the_prompt_never_asks_the_model_for_study_pattern():
    prompt = _build_general_prompt(
        "S", "d", {'Awareness': 2}, ALLOWED, 'retailer', [],
    )
    assert "study_pattern" not in prompt


# ─── category allow-list ──────────────────────────────────────────────────

def test_only_allowed_categories_are_rendered_into_the_prompt():
    prompt = _build_general_prompt(
        "S", "d", {'Awareness': 2}, ['Skincare', 'Makeup'], 'retailer', [],
    )
    assert "'Skincare'" in prompt
    assert "'Makeup'" in prompt
    assert "'Baby Care'" not in prompt
    assert "'Haircare'" not in prompt


def test_an_out_of_list_category_row_is_dropped_not_rewritten():
    """The real case: a Dyson Airwrap price query labelled 'Skincare'.
    Relabelling it 'Haircare' is the cheap edit and the wrong one — it
    turns a visible scope violation into a clean-looking row and the
    drift vanishes from the record."""
    targets = {'Awareness': 2}
    batch = [
        _row('Awareness', "-ok", category='Skincare'),
        _row('Awareness', "-bad", category='Haircare'),
        _row('Awareness', "-ok2", category='Makeup'),
    ]
    rows, report, _ = _generate(targets, [batch], allowed=['Skincare', 'Makeup'])

    categories = [r['category'] for r in rows]
    assert 'Haircare' not in categories
    assert set(categories) == {'Skincare', 'Makeup'}

    assert len(report['category_drops']) == 1
    drop = report['category_drops'][0]
    assert drop['category'] == 'Haircare'          # recorded as it WAS
    assert drop['query_text'] == "Question about Awareness-bad"
    assert 'Haircare' in drop['reason']


def test_a_dropped_category_row_never_reappears_relabelled():
    targets = {'Awareness': 1}
    batches = [[_row('Awareness', "-bad", category='Baby Care')]] + [[]] * 10
    rows, report, _ = _generate(targets, batches, allowed=['Skincare'])

    assert rows == []
    assert report['shortfall_by_stage'] == {'Awareness': 1}
    assert len(report['category_drops']) == 1


# ─── exact dedupe and replacement rounds ──────────────────────────────────

def test_exact_duplicates_are_removed_and_reported():
    targets = {'Awareness': 3}
    batches = [
        [_row('Awareness', "-a"), _row('Awareness', "-a"), _row('Awareness', "-b")],
    ] + [[_row('Awareness', "-c")]] + [[]] * 10

    rows, report, _ = _generate(targets, batches)

    texts = [r['query_text'] for r in rows]
    assert len(texts) == len(set(texts))
    assert len(report['duplicates_dropped']) == 1


def test_a_replacement_round_targets_the_stage_that_lost_rows():
    """Dedupe removed a Research row, so the replacement prompt must ask
    for Research — not for a fresh slice of the whole distribution."""
    targets = {'Awareness': 2, 'Research': 2}
    seen_shortfalls = []

    first = [
        _row('Awareness', "-0"), _row('Awareness', "-1"),
        _row('Research', "-dup"), _row('Research', "-dup"),   # collide
    ]
    replacement = [_row('Research', "-new")]

    def _capture(prompt, api_key, temperature=0.8, stamp=None):
        return (batches.pop(0), None)

    batches = [first, replacement]

    with patch("generation.query_generator._build_general_prompt") as mock_build, \
         patch("generation.query_generator._call_openai_and_validate", side_effect=_capture):
        mock_build.side_effect = lambda name, desc, shortfall, cats, pattern, avoid: (
            seen_shortfalls.append(dict(shortfall)) or "prompt"
        )
        rows, report = generate_general_queries(
            study_name="S", description="d", stage_targets=targets,
            allowed_categories=ALLOWED, study_pattern='retailer', api_key="k",
        )

    # First call asks for the full distribution; the replacement round
    # asks for Research only.
    assert seen_shortfalls[0] == {'Awareness': 2, 'Research': 2}
    assert seen_shortfalls[-1] == {'Research': 1}
    assert report['replacement_rounds'] == 1
    assert _counts(rows) == {'Awareness': 2, 'Research': 2}


def test_a_replacement_that_collides_is_itself_deduped():
    """A replacement can perfectly well repeat something already kept, so
    it re-enters dedupe rather than being trusted."""
    targets = {'Awareness': 2}
    batches = [
        [_row('Awareness', "-a"), _row('Awareness', "-a")],   # one survives
        [_row('Awareness', "-a")],                            # replacement collides
        [_row('Awareness', "-a")],
        [_row('Awareness', "-a")],
    ]
    rows, report, _ = _generate(targets, batches)

    assert len(rows) == 1
    assert report['shortfall_by_stage'] == {'Awareness': 1}
    assert len(report['duplicates_dropped']) >= 2


def test_replacement_rounds_are_bounded():
    """A study whose subject only supports a handful of distinct
    questions must not turn into an unbounded OpenAI bill."""
    targets = {'Awareness': 5}
    batches = [[_row('Awareness', "-same")] for _ in range(20)]

    rows, report, mock_call = _generate(targets, batches)

    assert report['replacement_rounds'] == REPLACEMENT_ROUNDS
    # (1 initial + RETRY_BUDGET_GENERAL retries) per round, over
    # 1 + REPLACEMENT_ROUNDS rounds.
    assert mock_call.call_count == (1 + RETRY_BUDGET_GENERAL) * (1 + REPLACEMENT_ROUNDS)
    assert report['generation_calls'] == mock_call.call_count


def test_a_replacement_uses_the_full_keep_list_as_the_avoid_list():
    targets = {'Awareness': 2}
    seen_avoid = []

    batches = [
        [_row('Awareness', "-a"), _row('Awareness', "-a")],
        [_row('Awareness', "-b")],
    ]

    def _capture(prompt, api_key, temperature=0.8, stamp=None):
        return (batches.pop(0), None) if batches else ([], None)

    with patch("generation.query_generator._build_general_prompt") as mock_build, \
         patch("generation.query_generator._call_openai_and_validate", side_effect=_capture):
        mock_build.side_effect = lambda name, desc, shortfall, cats, pattern, avoid: (
            seen_avoid.append(list(avoid)) or "prompt"
        )
        generate_general_queries(
            study_name="S", description="d", stage_targets=targets,
            allowed_categories=ALLOWED, study_pattern='retailer', api_key="k",
        )

    # The replacement round's first prompt knows about the kept row.
    assert seen_avoid[0] == []
    assert any("Question about Awareness-a" in avoid for avoid in seen_avoid[1:])


def test_zero_target_stages_are_ignored_entirely():
    targets = {'Awareness': 2, 'Research': 0}
    batch = [_row('Awareness', f"-{i}") for i in range(2)]
    rows, report, _ = _generate(targets, [batch])

    assert 'Research' not in report['requested_by_stage']
    assert report['shortfall_by_stage'] == {}
