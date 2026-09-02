"""
Tests for the two advisory review passes (review_semantic_duplicates,
review_coherence) and the provenance record built on top of them.

Three properties matter more than any individual finding:

  - They run at temperature 0. These are classification tasks. At the
    generation default of 0.8 the same fifty rows group differently on
    consecutive runs, and a finding a reviewer cannot reproduce is worse
    than no finding.
  - They never mutate or drop anything. Exact-match dedupe is the only
    automatic removal in the module; a semantic or scope judgement
    applied silently is indistinguishable afterwards from the generator
    having written fewer questions.
  - They degrade to empty findings on unreadable output. A second
    opinion must never fail a study that already generated successfully.
"""
import copy
import json
from unittest.mock import MagicMock, patch

from generation.query_generator import (
    COHERENCE_LABEL_MISMATCH,
    COHERENCE_OUT_OF_SCOPE,
    REVIEW_TEMPERATURE,
    _build_coherence_prompt,
    _build_semantic_duplicate_prompt,
    build_provenance_record,
    review_coherence,
    review_semantic_duplicates,
)

ALLOWED = ['Skincare', 'Makeup', 'Fragrance', 'Cross-Category']


def _row(text, category='Skincare', stage='Research'):
    return {
        'query_text': text,
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


# The real case exact matching cannot see and string similarity calls
# ambiguous: same product type, same job to be done, different wording.
SAME_QUESTION_TWICE = [
    _row("What's the best prestige vitamin C serum for brightening dull skin?"),
    _row("Which retailer stocks the widest range of niche fragrance?"),
    _row("Which prestige vitamin C serum works best for brightening and uneven tone?"),
]

# The real out-of-scope case: a hair-styling appliance in a prestige
# beauty study. Some allowed label would technically fit, which is
# exactly the trap.
OFF_BRIEF_ROWS = [
    _row("What's the best prestige vitamin C serum?", category='Skincare'),
    _row("Where can I get the best price on a Dyson Airwrap?", category='Skincare'),
]


def _openai_returning(payload):
    client = MagicMock()
    message = MagicMock()
    message.content = payload if isinstance(payload, str) else json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    client.chat.completions.create.return_value = MagicMock(choices=[choice])
    return client


# ─── temperature ──────────────────────────────────────────────────────────

def test_semantic_review_calls_the_model_at_temperature_zero():
    client = _openai_returning([])
    with patch("generation.query_generator.OpenAI", return_value=client):
        review_semantic_duplicates(SAME_QUESTION_TWICE, "k")

    assert client.chat.completions.create.call_args.kwargs["temperature"] == 0
    assert REVIEW_TEMPERATURE == 0


def test_coherence_review_calls_the_model_at_temperature_zero():
    client = _openai_returning([])
    with patch("generation.query_generator.OpenAI", return_value=client):
        review_coherence(OFF_BRIEF_ROWS, "Prestige Beauty", "d", ALLOWED, "k")

    assert client.chat.completions.create.call_args.kwargs["temperature"] == 0


# ─── neither mutates its input ────────────────────────────────────────────

def test_semantic_review_does_not_mutate_or_drop_rows():
    rows = copy.deepcopy(SAME_QUESTION_TWICE)
    before = copy.deepcopy(rows)
    client = _openai_returning([{"members": [1, 3], "keep": 1, "reason": "same question"}])
    with patch("generation.query_generator.OpenAI", return_value=client):
        findings = review_semantic_duplicates(rows, "k")

    assert rows == before
    assert len(rows) == 3
    assert isinstance(findings, list)


def test_coherence_review_does_not_mutate_or_drop_rows():
    rows = copy.deepcopy(OFF_BRIEF_ROWS)
    before = copy.deepcopy(rows)
    client = _openai_returning([
        {"index": 1, "verdict": "ok"},
        {"index": 2, "verdict": "out_of_scope", "reason": "not a beauty product"},
    ])
    with patch("generation.query_generator.OpenAI", return_value=client):
        review_coherence(rows, "Prestige Beauty", "d", ALLOWED, "k")

    assert rows == before
    assert rows[1]['category'] == 'Skincare'   # no proposed value applied


def test_a_label_mismatch_proposal_is_never_applied():
    rows = copy.deepcopy(OFF_BRIEF_ROWS)
    client = _openai_returning([
        {"index": 2, "verdict": "label_mismatch",
         "field": "category", "proposed_value": "Makeup"},
    ])
    with patch("generation.query_generator.OpenAI", return_value=client):
        findings = review_coherence(rows, "Prestige Beauty", "d", ALLOWED, "k")

    assert rows[1]['category'] == 'Skincare'
    assert findings[0]['proposed_value'] == 'Makeup'


# ─── semantic duplicate grouping ──────────────────────────────────────────

def test_same_question_different_wording_lands_in_one_group():
    client = _openai_returning([
        {"members": [1, 3], "keep": 1,
         "reason": "both ask for the best prestige vitamin C serum for brightening"},
    ])
    with patch("generation.query_generator.OpenAI", return_value=client):
        findings = review_semantic_duplicates(SAME_QUESTION_TWICE, "k")

    assert len(findings) == 1
    group = findings[0]
    assert group['members'] == [0, 2]           # 1-based in, 0-based out
    assert group['keep'] == 0
    assert "vitamin C serum" in group['keep_text']
    assert group['member_texts'][1].startswith("Which prestige vitamin C serum")
    assert group['reason']


def test_the_prompt_asks_for_groups_not_pairwise_comparison():
    """Across fifty items exhaustive pairwise comparison is 1,225
    judgements and models are unreliable at it; grouping is one pass."""
    prompt = _build_semantic_duplicate_prompt(SAME_QUESTION_TWICE)
    assert "GROUPS" in prompt
    assert "Do NOT compare every possible pair" in prompt


def test_the_prompt_sends_question_text_only_numbered():
    prompt = _build_semantic_duplicate_prompt(SAME_QUESTION_TWICE)
    assert "1. What's the best prestige vitamin C serum for brightening dull skin?" in prompt
    assert "Beauty Enthusiast" not in prompt      # no labels, just the questions
    assert "Mention Rate" not in prompt


def test_a_group_with_fewer_than_two_members_is_discarded():
    client = _openai_returning([{"members": [1], "keep": 1, "reason": "?"}])
    with patch("generation.query_generator.OpenAI", return_value=client):
        assert review_semantic_duplicates(SAME_QUESTION_TWICE, "k") == []


def test_out_of_range_indexes_are_discarded():
    client = _openai_returning([{"members": [1, 99], "keep": 99, "reason": "?"}])
    with patch("generation.query_generator.OpenAI", return_value=client):
        assert review_semantic_duplicates(SAME_QUESTION_TWICE, "k") == []


def test_a_keep_outside_its_own_group_falls_back_to_the_first_member():
    client = _openai_returning([{"members": [1, 3], "keep": 2, "reason": "?"}])
    with patch("generation.query_generator.OpenAI", return_value=client):
        findings = review_semantic_duplicates(SAME_QUESTION_TWICE, "k")

    assert findings[0]['keep'] == 0


def test_fewer_than_two_rows_needs_no_model_call():
    client = _openai_returning([])
    with patch("generation.query_generator.OpenAI", return_value=client):
        assert review_semantic_duplicates([_row("only one")], "k") == []
        assert review_semantic_duplicates([], "k") == []

    client.chat.completions.create.assert_not_called()


# ─── coherence: out_of_scope vs label_mismatch ────────────────────────────

def test_an_off_brief_row_is_classified_out_of_scope_not_label_mismatch():
    """The Dyson Airwrap case. Relabelling it 'Haircare' makes it pass
    every check, which is precisely why that answer is wrong — the defect
    is that a hair-styling appliance is not a prestige beauty product."""
    client = _openai_returning([
        {"index": 1, "verdict": "ok"},
        {"index": 2, "verdict": "out_of_scope",
         "reason": "a hair-styling appliance is not a prestige beauty product"},
    ])
    with patch("generation.query_generator.OpenAI", return_value=client):
        findings = review_coherence(
            OFF_BRIEF_ROWS, "Prestige Beauty", "Prestige beauty products", ALLOWED, "k",
        )

    assert len(findings) == 1
    assert findings[0]['verdict'] == COHERENCE_OUT_OF_SCOPE
    assert findings[0]['index'] == 1
    assert "Dyson Airwrap" in findings[0]['query_text']
    assert findings[0]['reason']
    assert 'proposed_value' not in findings[0]


def test_the_prompt_makes_the_distinction_explicit_with_the_worked_example():
    prompt = _build_coherence_prompt(
        OFF_BRIEF_ROWS, "Prestige Beauty", "Prestige beauty", ALLOWED,
    )
    assert "Dyson Airwrap" in prompt
    assert "out_of_scope even if some allowed category label would technically fit" in prompt
    assert "Ask first whether the question's subject belongs in this study" in prompt


def test_the_coherence_prompt_carries_name_description_and_allowed_categories():
    prompt = _build_coherence_prompt(
        OFF_BRIEF_ROWS, "Prestige Beauty", "Only prestige beauty", ['Skincare', 'Makeup'],
    )
    assert "Prestige Beauty" in prompt
    assert "Only prestige beauty" in prompt
    assert "'Skincare'" in prompt
    assert "'Baby Care'" not in prompt


def test_a_label_mismatch_finding_names_the_field_and_the_proposed_value():
    client = _openai_returning([
        {"index": 1, "verdict": "label_mismatch",
         "field": "stage", "proposed_value": "Comparison"},
    ])
    with patch("generation.query_generator.OpenAI", return_value=client):
        findings = review_coherence(OFF_BRIEF_ROWS, "S", "d", ALLOWED, "k")

    assert findings[0]['verdict'] == COHERENCE_LABEL_MISMATCH
    assert findings[0]['field'] == 'stage'
    assert findings[0]['proposed_value'] == 'Comparison'


def test_ok_verdicts_produce_no_finding():
    client = _openai_returning([
        {"index": 1, "verdict": "ok"}, {"index": 2, "verdict": "ok"},
    ])
    with patch("generation.query_generator.OpenAI", return_value=client):
        assert review_coherence(OFF_BRIEF_ROWS, "S", "d", ALLOWED, "k") == []


def test_an_unrecognised_verdict_is_discarded():
    client = _openai_returning([{"index": 1, "verdict": "probably fine"}])
    with patch("generation.query_generator.OpenAI", return_value=client):
        assert review_coherence(OFF_BRIEF_ROWS, "S", "d", ALLOWED, "k") == []


# ─── graceful degradation ─────────────────────────────────────────────────

def test_unparseable_output_degrades_to_no_findings():
    client = _openai_returning("this is not JSON at all")
    with patch("generation.query_generator.OpenAI", return_value=client):
        assert review_semantic_duplicates(SAME_QUESTION_TWICE, "k") == []
        assert review_coherence(OFF_BRIEF_ROWS, "S", "d", ALLOWED, "k") == []


def test_a_json_object_instead_of_an_array_degrades_to_no_findings():
    client = _openai_returning({"verdict": "no idea"})
    with patch("generation.query_generator.OpenAI", return_value=client):
        assert review_semantic_duplicates(SAME_QUESTION_TWICE, "k") == []
        assert review_coherence(OFF_BRIEF_ROWS, "S", "d", ALLOWED, "k") == []


def test_non_dict_elements_are_skipped_not_fatal():
    client = _openai_returning(["nonsense", 42, {"members": [1, 3], "keep": 1, "reason": "r"}])
    with patch("generation.query_generator.OpenAI", return_value=client):
        findings = review_semantic_duplicates(SAME_QUESTION_TWICE, "k")

    assert len(findings) == 1


def test_an_exception_from_the_model_call_degrades_to_no_findings():
    """A flaky OpenAI call must not fail a study creation that has
    already completely succeeded."""
    with patch("generation.query_generator.OpenAI", side_effect=RuntimeError("boom")):
        assert review_semantic_duplicates(SAME_QUESTION_TWICE, "k") == []
        assert review_coherence(OFF_BRIEF_ROWS, "S", "d", ALLOWED, "k") == []


# ─── provenance record ────────────────────────────────────────────────────

def _report():
    return {
        'requested_by_stage': {'Awareness': 2, 'Research': 2},
        'delivered_by_stage': {'Awareness': 2, 'Research': 1},
        'shortfall_by_stage': {'Research': 1},
        'duplicates_dropped': [_row("A repeated question?", stage='Research')],
        'category_drops': [
            {'query_text': "Best baby wipes?", 'category': 'Baby Care',
             'reason': "category 'Baby Care' is outside the study's allowed categories"},
        ],
        'replacement_rounds': 1,
        'generation_calls': 4,
    }


def test_provenance_captures_every_required_element():
    rows = [_row("Q1?"), _row("Q2?"), _row("Q3?")]
    groups = [{'members': [0, 1], 'keep': 0, 'reason': 'same question',
               'member_texts': ["Q1?", "Q2?"], 'keep_text': "Q1?"}]
    coherence = [
        {'index': 2, 'verdict': COHERENCE_OUT_OF_SCOPE, 'query_text': "Q3?",
         'category': 'Skincare', 'reason': 'off brief'},
    ]

    record = build_provenance_record(rows, _report(), groups, coherence)

    assert record['rows_generated'] == 3
    assert record['requested_by_stage'] == {'Awareness': 2, 'Research': 2}
    assert record['delivered_by_stage'] == {'Awareness': 2, 'Research': 1}
    assert record['shortfall_by_stage'] == {'Research': 1}
    assert record['replacement_rounds'] == 1

    assert record['exact_duplicates_dropped'] == [
        {'query_text': "A repeated question?", 'stage': 'Research'},
    ]
    assert record['category_drops'][0]['category'] == 'Baby Care'
    assert record['semantic_duplicate_groups'] == groups


def test_provenance_groups_coherence_findings_by_outcome():
    rows = [_row("Q1?"), _row("Q2?"), _row("Q3?")]
    coherence = [
        {'index': 0, 'verdict': COHERENCE_LABEL_MISMATCH, 'field': 'category',
         'proposed_value': 'Makeup', 'query_text': "Q1?", 'category': 'Skincare',
         'reason': ''},
        {'index': 1, 'verdict': COHERENCE_OUT_OF_SCOPE, 'query_text': "Q2?",
         'category': 'Skincare', 'reason': 'off brief'},
    ]

    record = build_provenance_record(rows, _report(), [], coherence)
    by_outcome = record['coherence_findings_by_outcome']

    assert len(by_outcome[COHERENCE_LABEL_MISMATCH]) == 1
    assert len(by_outcome[COHERENCE_OUT_OF_SCOPE]) == 1
    assert record['coherence_ok_count'] == 1


def test_provenance_works_with_no_review_findings_at_all():
    """Reviews degrade to empty, so the record has to be well-formed
    without them."""
    record = build_provenance_record([_row("Q1?")], _report())

    assert record['semantic_duplicate_groups'] == []
    assert record['coherence_findings_by_outcome'][COHERENCE_OUT_OF_SCOPE] == []
    assert record['coherence_ok_count'] == 1


def test_provenance_keeps_the_automatic_and_advisory_halves_distinct():
    """A reviewer has to be able to tell at a glance what is already gone
    from what is merely flagged."""
    record = build_provenance_record([_row("Q1?")], _report(), [], [])

    # Automatic: these rows are not in the study.
    assert record['exact_duplicates_dropped']
    assert record['category_drops']
    # Advisory: nothing was applied.
    assert record['semantic_duplicate_groups'] == []
    assert record['coherence_findings_by_outcome'][COHERENCE_LABEL_MISMATCH] == []


# ─── generate_and_review_study ────────────────────────────────────────────

def test_reviews_run_on_the_rows_that_survived_exact_dedupe():
    """Reviewing the pre-dedupe set would report every removed duplicate
    a second time as a semantic one, burying the findings that actually
    need a human."""
    from generation.query_generator import generate_and_review_study

    generated = [_row("Q1?", stage='Awareness'), _row("Q1?", stage='Awareness'),
                 _row("Q2?", stage='Awareness')]
    seen = {}

    def _fake_semantic(rows, api_key):
        seen['semantic'] = [r['query_text'] for r in rows]
        return []

    def _fake_coherence(rows, name, desc, cats, api_key):
        seen['coherence'] = [r['query_text'] for r in rows]
        return []

    with patch("generation.query_generator._call_openai_and_validate",
               side_effect=[(generated, None)] + [([], None)] * 10), \
         patch("generation.query_generator.review_semantic_duplicates", _fake_semantic), \
         patch("generation.query_generator.review_coherence", _fake_coherence):
        rows, provenance = generate_and_review_study(
            study_name="S", description="d",
            stage_targets={'Awareness': 2}, allowed_categories=ALLOWED,
            study_pattern='retailer', api_key="k",
        )

    assert seen['semantic'] == ["Q1?", "Q2?"]       # the duplicate is gone
    assert seen['coherence'] == ["Q1?", "Q2?"]
    assert len(rows) == 2
    assert len(provenance['exact_duplicates_dropped']) == 1


def test_the_composition_returns_rows_untouched_by_the_reviews():
    from generation.query_generator import generate_and_review_study

    generated = [_row("Q1?", stage='Awareness'), _row("Q2?", stage='Awareness')]

    with patch("generation.query_generator._call_openai_and_validate",
               side_effect=[(generated, None)] + [([], None)] * 10), \
         patch("generation.query_generator.review_semantic_duplicates",
               return_value=[{'members': [0, 1], 'keep': 0, 'reason': 'r',
                              'member_texts': ["Q1?", "Q2?"], 'keep_text': "Q1?"}]), \
         patch("generation.query_generator.review_coherence",
               return_value=[{'index': 1, 'verdict': COHERENCE_OUT_OF_SCOPE,
                              'query_text': "Q2?", 'category': 'Skincare',
                              'reason': 'off brief'}]):
        rows, provenance = generate_and_review_study(
            study_name="S", description="d",
            stage_targets={'Awareness': 2}, allowed_categories=ALLOWED,
            study_pattern='retailer', api_key="k",
        )

    # Findings recorded, nothing removed.
    assert [r['query_text'] for r in rows] == ["Q1?", "Q2?"]
    assert len(provenance['semantic_duplicate_groups']) == 1
    assert len(provenance['coherence_findings_by_outcome'][COHERENCE_OUT_OF_SCOPE]) == 1
