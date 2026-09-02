"""
Tests for the exact-duplicate machinery in generation/query_generator.py
(normalize_query_text, dedupe_exact) and for the two _build_prompt fixes
that motivated it: the FULL already-generated list reaching the avoid
text, and subscription_state being requested rather than silently
omitted.

Context: a 50-question study came back with eleven duplicate or
near-duplicate rows, clustered roughly nine rows apart. BATCH_SIZE is
10, and _build_prompt used to send only already_generated[-20:], so by
batch 5 the model could not see batches 1-2 at all. Both halves of the
fix are covered here — the prompt no longer hides earlier questions, and
whatever still slips through is removed at the accumulation point.
"""
from generation.query_generator import (
    _build_prompt,
    dedupe_exact,
    normalize_query_text,
)


# ─── normalize_query_text ─────────────────────────────────────────────────

def test_normalizer_lowercases():
    assert normalize_query_text("Best Vitamin C Serum") == "best vitamin c serum"


def test_normalizer_strips_surrounding_whitespace():
    assert normalize_query_text("   best serum   ") == "best serum"


def test_normalizer_collapses_internal_whitespace():
    assert normalize_query_text("best    vitamin\tc\nserum") == "best vitamin c serum"


def test_normalizer_strips_trailing_punctuation():
    assert normalize_query_text("What is the best serum?") == "what is the best serum"
    assert normalize_query_text("What is the best serum.") == "what is the best serum"
    assert normalize_query_text("What is the best serum?!") == "what is the best serum"


def test_normalizer_keeps_internal_punctuation():
    """Only TRAILING punctuation goes — an internal dash or comma is part
    of the question, and stripping it would collide genuinely different
    questions."""
    assert normalize_query_text("A vs B — which wins?") == "a vs b — which wins"


def test_normalizer_handles_none_and_empty():
    assert normalize_query_text(None) == ""
    assert normalize_query_text("") == ""
    assert normalize_query_text("   ") == ""


def test_normalizer_makes_cosmetic_variants_equal():
    a = normalize_query_text("Which retailer has the best price?")
    b = normalize_query_text("which retailer  has the best price")
    assert a == b


# ─── dedupe_exact ─────────────────────────────────────────────────────────

def _row(text, **overrides):
    row = dict(
        query_text=text,
        category='Skincare',
        stage='Research',
        specificity='Mid',
        persona='Beauty Enthusiast',
        study_pattern='retailer',
        status='Active',
        subscription_state=None,
        soa_focus='Mention Rate',
        rationale='test',
    )
    row.update(overrides)
    return row


def test_dedupe_keeps_first_occurrence():
    rows = [_row("Question A"), _row("Question B"), _row("Question A")]
    survivors, dropped = dedupe_exact(rows)

    assert [r['query_text'] for r in survivors] == ["Question A", "Question B"]
    assert len(dropped) == 1
    assert dropped[0]['query_text'] == "Question A"


def test_dedupe_returns_the_dropped_rows_not_just_their_text():
    """The provenance record has to name what was discarded, so dropped
    carries whole rows."""
    rows = [_row("Question A"), _row("Question A", stage='Awareness')]
    _, dropped = dedupe_exact(rows)

    assert dropped[0]['stage'] == 'Awareness'
    assert dropped[0]['category'] == 'Skincare'


def test_identical_text_under_two_different_stages_is_still_a_duplicate():
    """THE case that decides the key. The observed failures included the
    same question text carrying different stage labels. Keying on
    (query_text, stage) — or on any composite — would let exactly these
    through while catching only the harmless verbatim-in-every-field
    case. A question asked twice is asked twice however it was labelled
    the second time."""
    rows = [
        _row("Where can I get the best price on a vitamin C serum?", stage='Comparison'),
        _row("Where can I get the best price on a vitamin C serum?", stage='Ready to Buy'),
    ]
    survivors, dropped = dedupe_exact(rows)

    assert len(survivors) == 1
    assert len(dropped) == 1
    assert survivors[0]['stage'] == 'Comparison'   # first occurrence wins
    assert dropped[0]['stage'] == 'Ready to Buy'


def test_identical_text_differing_in_every_other_field_is_still_a_duplicate():
    rows = [
        _row("Same question", category='Skincare', persona='Beauty Enthusiast',
             specificity='Broad'),
        _row("Same question", category='Makeup', persona='Value-Conscious',
             specificity='Narrow'),
    ]
    survivors, dropped = dedupe_exact(rows)
    assert len(survivors) == 1
    assert len(dropped) == 1


def test_dedupe_uses_the_normalizer_so_cosmetic_drift_collides():
    rows = [
        _row("What is the best serum?"),
        _row("  what is   the best serum  "),
    ]
    survivors, dropped = dedupe_exact(rows)
    assert len(survivors) == 1
    assert len(dropped) == 1


def test_genuinely_different_questions_all_survive():
    rows = [_row(f"Question number {i}?") for i in range(10)]
    survivors, dropped = dedupe_exact(rows)
    assert len(survivors) == 10
    assert dropped == []


def test_dedupe_of_empty_list():
    assert dedupe_exact([]) == ([], [])


def test_dedupe_does_not_mutate_the_input_rows():
    rows = [_row("A"), _row("A")]
    before = [dict(r) for r in rows]
    dedupe_exact(rows)
    assert rows == before


# ─── _build_prompt ────────────────────────────────────────────────────────

def test_prompt_includes_every_already_generated_question_not_just_the_last_twenty():
    """The duplicate bug itself. With BATCH_SIZE=10 and a 50-question
    study, the final batch has 40 prior questions to avoid; a 20-entry
    window hid half of them."""
    prior = [f"Prior question {i}?" for i in range(40)]
    prompt = _build_prompt("Prestige Beauty", "A study", 10, prior)

    for question in prior:
        assert question in prompt


def test_avoid_text_wording_is_unchanged():
    prompt = _build_prompt("S", "d", 10, ["Only question?"])
    assert (
        "Do NOT repeat or closely paraphrase these already-generated questions:"
        in prompt
    )


def test_no_avoid_section_when_nothing_generated_yet():
    prompt = _build_prompt("S", "d", 10, [])
    assert "Do NOT repeat" not in prompt


def test_prompt_requests_subscription_state():
    """_build_lite_prompt already asks for it; the general prompt used to
    omit it, so generally-generated rows never carried a value even when
    one applied. _NULLABLE_CONSTRAINED_FIELDS still makes an absent value
    valid — see test_query_generator_validation.py — so asking for it
    cannot reintroduce the 100%-rejection regression."""
    prompt = _build_prompt("S", "d", 10, [])
    assert "subscription_state" in prompt
