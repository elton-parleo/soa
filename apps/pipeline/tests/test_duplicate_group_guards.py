"""
Tests for the guards on the semantic duplicate review pass, built from the
real failure that motivated them.

The pass ran against a 52-query prestige beauty study and returned five
groups covering 46 of the 52 queries. Accepting its recommendations would
have deactivated 46 and left six. It had not stopped working — two genuine
duplicate pairs were in there and it found both — it had switched from
finding redundancy to sorting by topic, and then buried the real pairs
inside the clusters.

The clearest evidence is group one's own reason text, reproduced verbatim
below: it calls its 22 members "distinct" and then recommends deleting 21
of them. The reason field and the recommended action contradict each
other outright, and nothing downstream noticed.

Three of the four fixes are guards in code rather than prompt wording,
because a model that will write that sentence without hesitation is not a
model whose cooperation can be assumed. These test the guards.
"""
import pytest

from generation.query_generator import (
    DISCARD_MIXED_LABELS,
    DISCARD_OVERSIZED,
    DISCARD_REASON_DENIES_REDUNDANCY,
    MAX_DUPLICATE_GROUP_SIZE,
    DuplicateReviewFindings,
    _apply_duplicate_group_guards,
    _build_semantic_duplicate_prompt,
    build_provenance_record,
)

# ─── the real failure data ────────────────────────────────────────────────

# Group one's reason, verbatim from the run.
REASON_GROUP_ONE = (
    "These are all distinct prestige beauty topic questions about different "
    "products, ingredients, routines, or use cases."
)

# Another group's reason, verbatim: four subjects joined by "or".
REASON_TOPIC_CLUSTER = (
    "These all ask about Sephora vs Ulta prestige skincare selection, "
    "pricing, promotions, or loyalty value"
)

# The pair the pass got right, buried inside a nine-member group.
PRE_090 = "Does Sephora's Beauty Insider program make prestige skincare cheaper overall?"
PRE_096 = "Is prestige skincare actually cheaper at Sephora if you are in their loyalty program?"


def _row(category='Skincare', stage='Ready to Buy', text='q'):
    return {'query_text': text, 'category': category, 'stage': stage}


def _group(members, reason, keep=None):
    return {
        'members': list(members),
        'keep': members[0] if keep is None else keep,
        'reason': reason,
    }


# ─── guard one: group size ────────────────────────────────────────────────

def test_the_twenty_two_member_group_is_discarded_on_size():
    """A group of twenty-two is definitionally not duplicates."""
    rows = [_row() for _ in range(22)]
    kept, discarded = _apply_duplicate_group_guards(
        [_group(range(22), REASON_GROUP_ONE)], rows,
    )

    assert kept == []
    assert len(discarded) == 1
    assert DISCARD_OVERSIZED in discarded[0]['guards']
    assert discarded[0]['size'] == 22


def test_an_oversized_group_is_discarded_whole_never_truncated():
    """Truncating to the first three members would fabricate a finding.
    The model's ordering carries no signal about which members are the
    real pair — the observed failure had two genuine pairs inside a
    nine-member group, and truncation would have replaced them with three
    unrelated queries wearing a duplicate label."""
    rows = [_row() for _ in range(9)]
    kept, discarded = _apply_duplicate_group_guards(
        [_group(range(9), 'nine things that share a subject')], rows,
    )

    assert kept == []                       # nothing survives, not a slice
    assert discarded[0]['size'] == 9


def test_the_size_cap_is_three():
    rows = [_row() for _ in range(4)]

    kept, _ = _apply_duplicate_group_guards(
        [_group(range(MAX_DUPLICATE_GROUP_SIZE), 'same question')], rows,
    )
    assert len(kept) == 1                   # three survives

    kept, discarded = _apply_duplicate_group_guards(
        [_group(range(MAX_DUPLICATE_GROUP_SIZE + 1), 'same question')], rows,
    )
    assert kept == []                       # four does not
    assert DISCARD_OVERSIZED in discarded[0]['guards']


# ─── guard two: label span ────────────────────────────────────────────────

def test_a_group_spanning_skincare_makeup_and_fragrance_is_discarded():
    """Group one mixed three categories across two stages. This guard
    alone would have caught it."""
    rows = [
        _row('Skincare', 'Awareness'),
        _row('Makeup', 'Research'),
        _row('Fragrance', 'Awareness'),
    ]
    kept, discarded = _apply_duplicate_group_guards(
        [_group([0, 1, 2], 'all prestige beauty')], rows,
    )

    assert kept == []
    assert DISCARD_MIXED_LABELS in discarded[0]['guards']


def test_a_group_spanning_two_stages_is_discarded():
    """An Awareness question and a Research question are asked by
    different shoppers at different moments, even when the words
    overlap."""
    rows = [_row('Skincare', 'Awareness'), _row('Skincare', 'Research')]
    kept, discarded = _apply_duplicate_group_guards(
        [_group([0, 1], 'same wording')], rows,
    )

    assert kept == []
    assert DISCARD_MIXED_LABELS in discarded[0]['guards']


def test_a_group_within_one_category_and_stage_survives_this_guard():
    rows = [_row('Skincare', 'Ready to Buy'), _row('Skincare', 'Ready to Buy')]
    kept, discarded = _apply_duplicate_group_guards(
        [_group([0, 1], 'same question twice')], rows,
    )

    assert len(kept) == 1
    assert discarded == []


# ─── guard three: a reason that denies its own grouping ───────────────────

def test_a_reason_containing_distinct_is_discarded():
    """A group whose own stated justification denies redundancy should
    never reach a human."""
    rows = [_row(), _row()]
    kept, discarded = _apply_duplicate_group_guards(
        [_group([0, 1], REASON_GROUP_ONE)], rows,
    )

    assert kept == []
    assert DISCARD_REASON_DENIES_REDUNDANCY in discarded[0]['guards']


def test_a_reason_containing_different_is_discarded():
    rows = [_row(), _row()]
    kept, discarded = _apply_duplicate_group_guards(
        [_group([0, 1], 'Both cover different aspects of the same product line.')], rows,
    )

    assert kept == []
    assert DISCARD_REASON_DENIES_REDUNDANCY in discarded[0]['guards']


def test_the_check_is_case_insensitive():
    rows = [_row(), _row()]
    for reason in ('DISTINCT products', 'Different framings', 'DiStInCt'):
        kept, discarded = _apply_duplicate_group_guards(
            [_group([0, 1], reason)], rows,
        )
        assert kept == [], reason
        assert DISCARD_REASON_DENIES_REDUNDANCY in discarded[0]['guards']


def test_inflections_of_the_two_words_are_caught():
    """Substring rather than word-boundary, so 'differently' and
    'distinctly' carry the same signal and are caught."""
    rows = [_row(), _row()]
    for reason in ('Phrased differently but identical.', 'Distinctly separate asks.'):
        kept, _ = _apply_duplicate_group_guards([_group([0, 1], reason)], rows)
        assert kept == [], reason


def test_difference_is_not_caught_and_that_is_the_specified_behaviour():
    """The guard is exactly the two words asked for. 'differences' is not
    a superstring of 'different' — it carries a c where the word carries
    a t — so it does not trip, and widening the list is a scope decision
    rather than a bug fix."""
    rows = [_row(), _row()]
    kept, discarded = _apply_duplicate_group_guards(
        [_group([0, 1], 'Minor differences only.')], rows,
    )
    assert len(kept) == 1
    assert discarded == []


# ─── the real pair survives every guard ───────────────────────────────────

def test_the_pre_090_pre_096_pair_survives_all_three_guards():
    """The point is to suppress the noise without suppressing the signal.
    Both ask whether Sephora's loyalty program makes prestige skincare
    cheaper — same question, same answer, different words."""
    rows = [
        _row('Skincare', 'Ready to Buy', PRE_090),
        _row('Skincare', 'Ready to Buy', PRE_096),
    ]
    finding = _group(
        [0, 1],
        "Both ask whether Sephora's loyalty program lowers what you pay for "
        "prestige skincare.",
    )

    kept, discarded = _apply_duplicate_group_guards([finding], rows)

    assert discarded == []
    assert len(kept) == 1
    assert kept[0]['members'] == [0, 1]


def test_the_second_real_pair_survives_too():
    """PRE_087 and PRE_093 both ask Sephora's current prestige skincare
    price and active promotion."""
    rows = [
        _row('Skincare', 'Ready to Buy', "What does Sephora charge for prestige skincare right now, and is there a promo?"),
        _row('Skincare', 'Ready to Buy', "What is the current price and active promotion on prestige skincare at Sephora?"),
    ]
    kept, discarded = _apply_duplicate_group_guards(
        [_group([0, 1], 'Both ask current Sephora price and active promotion.')], rows,
    )

    assert discarded == []
    assert len(kept) == 1


def test_real_pairs_survive_alongside_clusters_being_discarded():
    """A single pass returning both shapes keeps the good one."""
    rows = (
        [_row('Skincare', 'Ready to Buy', PRE_090), _row('Skincare', 'Ready to Buy', PRE_096)]
        + [_row('Makeup', 'Awareness') for _ in range(20)]
    )
    findings = [
        _group([0, 1], "Both ask whether Sephora's loyalty program lowers the price."),
        _group(range(2, 22), REASON_GROUP_ONE),
    ]

    kept, discarded = _apply_duplicate_group_guards(findings, rows)

    assert len(kept) == 1
    assert kept[0]['members'] == [0, 1]
    assert len(discarded) == 1
    assert discarded[0]['size'] == 20


# ─── discards are recorded, not merely dropped ────────────────────────────

def test_discard_counts_reach_the_provenance_record():
    discards = [
        {'size': 22, 'guards': [DISCARD_OVERSIZED], 'reason': REASON_GROUP_ONE},
        {'size': 9, 'guards': [DISCARD_MIXED_LABELS], 'reason': REASON_TOPIC_CLUSTER},
    ]
    provenance = build_provenance_record(
        [_row()], {}, DuplicateReviewFindings([], discards), [],
    )

    assert provenance['semantic_groups_discarded'] == 2
    assert provenance['semantic_duplicate_groups'] == []
    assert provenance['semantic_group_discards'][0]['size'] == 22
    assert REASON_GROUP_ONE in provenance['semantic_group_discards'][0]['reason']


def test_a_pass_that_misbehaved_reads_differently_from_a_clean_one():
    """Both surface zero findings. Only the count tells them apart, which
    is the whole reason it is recorded."""
    misbehaved = build_provenance_record(
        [_row()], {},
        DuplicateReviewFindings([], [{'size': 22, 'guards': [DISCARD_OVERSIZED], 'reason': REASON_GROUP_ONE}]),
        [],
    )
    clean = build_provenance_record([_row()], {}, DuplicateReviewFindings([], []), [])

    assert misbehaved['semantic_duplicate_groups'] == clean['semantic_duplicate_groups'] == []
    assert misbehaved['semantic_groups_discarded'] == 1
    assert clean['semantic_groups_discarded'] == 0


def test_an_all_discarded_findings_list_still_reports_its_discards():
    """DuplicateReviewFindings that kept nothing is an empty list and so
    falsy — a `or []` normalisation would drop the discards in exactly
    the case they matter most."""
    findings = DuplicateReviewFindings([], [{'size': 22, 'guards': [], 'reason': 'x'}])
    assert not findings                       # falsy
    provenance = build_provenance_record([_row()], {}, findings, [])
    assert provenance['semantic_groups_discarded'] == 1


def test_a_plain_list_from_a_caller_that_knows_nothing_of_guards_records_zero():
    provenance = build_provenance_record([_row()], {}, [], [])
    assert provenance['semantic_groups_discarded'] == 0
    assert provenance['semantic_group_discards'] == []


def test_findings_behave_as_an_ordinary_list_for_every_existing_caller():
    findings = DuplicateReviewFindings([{'members': [0, 1]}], [{'size': 9}])
    assert findings == [{'members': [0, 1]}]
    assert len(findings) == 1
    assert findings[0]['members'] == [0, 1]
    assert DuplicateReviewFindings() == []
    assert findings.discarded_count == 1


# ─── the prompt itself ────────────────────────────────────────────────────

def test_the_prompt_defines_a_group_by_the_deletion_test():
    prompt = _build_semantic_duplicate_prompt([_row(text='a'), _row(text='b')])
    assert "DELETING ANY ONE OF THEM would lose no information" in prompt


def test_the_prompt_rules_out_topic_shared_category_retailer_and_shape():
    prompt = _build_semantic_duplicate_prompt([_row(text='a'), _row(text='b')])
    for phrase in ('A shared topic', 'A shared category',
                   'A shared retailer', 'A shared question shape'):
        assert phrase in prompt


def test_the_prompt_names_the_two_real_bad_reasons_verbatim():
    """Quoted from the actual failure so the model is shown the exact
    output it produced, not a paraphrase of it."""
    prompt = _build_semantic_duplicate_prompt([_row(text='a'), _row(text='b')])
    assert REASON_GROUP_ONE in prompt
    assert REASON_TOPIC_CLUSTER in prompt


def test_the_prompt_gives_the_loyalty_pair_as_a_correct_example():
    prompt = _build_semantic_duplicate_prompt([_row(text='a'), _row(text='b')])
    assert "loyalty program makes prestige skincare cheaper" in prompt
    assert "Delete either one and nothing is lost" in prompt


def test_the_prompt_tells_the_model_that_finding_nothing_is_a_good_answer():
    prompt = _build_semantic_duplicate_prompt([_row(text='a'), _row(text='b')])
    assert "Returning an empty array is a perfectly good answer" in prompt
    assert "Do not manufacture groups" in prompt


def test_the_prompt_still_asks_for_grouping_not_pairwise_comparison():
    """The shape is right and stays. The bar moved, not the method."""
    prompt = _build_semantic_duplicate_prompt([_row(text='a'), _row(text='b')])
    assert "Do NOT compare every possible pair" in prompt
    assert "GROUPS" in prompt
