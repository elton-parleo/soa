"""
The ten disagreements from the cycle-20260915 hand-check, one test each.

Forty stored answers were read by hand against their extractions; ten
disagreed. Four were the same mistake (a size read as a pack count), and
the rest were one each. This file is those ten, named by their row in the
validation sheet, plus the rules they produced.

Two of the ten cannot be fixed by a prompt at all — rows 30 and 36, where
the model got "did the answer name the brand" wrong in both directions.
Those are now decided by a string comparison outside the model, and the
tests for them are exact.

The other eight are prompt rules, so what can be tested here is the
rule's shape rather than the model's compliance: the field exists, the
prompt states the rule, and the deterministic code downstream treats the
corrected transcription the way the hand-check says it should. Whether
the model obeys is what the NEXT hand-check is for — see
scripts/validate_extractions.py.
"""
import pytest

from parser import expectation_prompts as prompts
from parser.expectation_prompts import (
    EMPTY_EXTRACTION, build_extraction_schema, stamp_brand_mentioned,
)
from scoring import brand_direct_classifier as c
from soa_shared import expected_answers as ea

BRAND = "Wiggle & Snug"
EXPECTATION = {"type": "brand_mention", "brand": BRAND, "domain": "trueshopstore.com"}
FACTS = {
    "domain": "trueshopstore.com",
    "tier_names": ["Member", "Member+"],
    "product_titles": ["Snug-Fit Diapers", "Cloud Wipes", "Bum Balm"],
}


def extraction(**kw):
    base = dict(EMPTY_EXTRACTION)
    base.update({"extraction_confident": True, "extraction_note": None,
                 "brand_mentioned": True})
    base.update(kw)
    return base


def classify(**kw):
    return c.classify(extraction(**kw), EXPECTATION, brand_facts=FACTS)


SCHEMA = build_extraction_schema()
PROMPT = prompts.EXPECTATION_EXTRACTION_PROMPT


# ── Rows 1, 3, 13, 34 — "4 oz" is not a pack of four ──────────────────────
#
# Four of the ten, and the only systematic one. A size read as a count is
# a wrong number attached to a real product: it puts the assistant up
# against a quantity nobody asked about, and on a catalog-accuracy row it
# moves a pack_count secondary.

def test_sizes_have_a_field_of_their_own():
    assert "sizes" in SCHEMA["properties"]
    assert "sizes" in SCHEMA["required"]
    assert EMPTY_EXTRACTION["sizes"] == []


def test_a_size_carries_its_unit_so_it_cannot_be_read_as_a_count():
    """A bare 4 is ambiguous; 4 with "oz" is not. The unit is what makes
    the field able to hold the thing the count field could not."""
    item = SCHEMA["properties"]["sizes"]["items"]
    assert sorted(item["required"]) == ["attributed_product", "unit", "value"]


@pytest.mark.parametrize("measurement", ["4 oz", "3.4 fl oz", "100 ml", "250 g"])
def test_the_prompt_names_the_measurements_that_were_misread(measurement):
    assert measurement in PROMPT


def test_the_prompt_says_which_question_a_count_answers():
    assert 'A count answers "how many"' in PROMPT
    assert '"4 oz" is not a pack of four' in PROMPT


def test_a_size_does_not_reach_the_pack_count_comparison():
    """The end of the chain: with the size in its own field, a
    pack_count expectation sees no value and scores absent rather than
    being told the answer said four."""
    from scoring import expectation_comparator as cmp
    verdict = cmp.compare(
        {"type": "pack_count", "value": 96},
        extraction(sizes=[{"value": "4", "unit": "oz",
                           "attributed_product": "Bum Balm"}]),
    )
    assert verdict.outcome == cmp.ABSENT


# ── Row 14 — recommending a shop is not citing one ────────────────────────

def test_recommended_retailers_have_a_field_of_their_own():
    assert "recommended_retailers" in SCHEMA["properties"]
    assert EMPTY_EXTRACTION["recommended_retailers"] == []


def test_the_prompt_says_a_recommendation_is_not_a_citation():
    assert "A recommendation is not a citation" in PROMPT
    assert "has cited nothing" in PROMPT


def test_row_14_an_answer_that_recommends_three_shops_has_cited_nothing():
    """It listed amazon.com, walmart.com and target.com as sources. The
    answer told the reader to check them."""
    from scoring.expectation_comparator import classify_sources
    attribution, domain_cited = classify_sources([], "trueshopstore.com")
    assert attribution == "none"
    assert domain_cited is False


def test_where_to_buy_with_nothing_behind_it_is_a_finding():
    """The other half of row 14: the recommendation is itself a claim
    about where this brand is sold, and an unsourced one."""
    assessment, reason = classify(
        recommended_retailers=["Amazon", "Walmart", "Target"],
    )
    assert assessment == c.FABRICATED
    assert "where to buy" in reason


def test_a_recommendation_from_an_answer_that_admitted_it_could_not_find_us():
    """"I could not find this brand — you could try Amazon" is a
    suggestion to go looking, not a claim that it is there. Treating the
    two alike would punish the most honest answer in the set for trying
    to be useful."""
    assessment, _ = classify(
        recommended_retailers=["Amazon"],
        brand_unknown_statement="I couldn't find any information about that brand",
    )
    assert assessment == c.ACKNOWLEDGED_UNKNOWN


def test_a_recommendation_beside_a_citation_is_not_a_finding():
    assessment, _ = classify(
        recommended_retailers=["Amazon"],
        sources_cited=["trueshopstore.com"],
    )
    assert assessment == c.GROUNDED


# ── Row 21 — "$10 to $15" is USD twice ────────────────────────────────────

def test_a_bare_dollar_sign_is_usd_by_table_not_by_instruction():
    assert ea.normalize_currency("$") == "USD"
    assert ea.normalize_currency("US$") == "USD"


def test_the_prompt_says_a_range_carries_one_currency():
    assert "The symbol at the front of a range governs the whole range" in PROMPT


def test_a_price_with_no_currency_is_still_compared():
    """Why the inconsistency mattered: the comparator SKIPS a stated
    price whose currency disagrees, and treats a null currency as
    agreement. So row 21's nulls scored, and would have scored
    differently had the model called one of them USD and not the
    other."""
    from scoring import expectation_comparator as cmp
    expectation = {"type": "price", "amount": "12.00", "currency": "USD"}
    with_null = cmp.compare(expectation, extraction(
        prices=[{"amount": "12.00", "currency": None, "attributed_product": None}]))
    with_usd = cmp.compare(expectation, extraction(
        prices=[{"amount": "12.00", "currency": "USD", "attributed_product": None}]))
    assert with_null.outcome == with_usd.outcome == cmp.EXACT


# ── Row 25 — a possibility is not a claim ─────────────────────────────────

@pytest.mark.parametrize("hedge", [
    "It's possible this is a very new, small, or regional brand.",
    "They likely emphasise a closer fit.",
    "It might be a store brand.",
])
def test_the_hedges_that_were_recorded_as_claims_are_caught_in_code(hedge):
    """Round one put these in the prompt and the model applied the rule
    inconsistently within a single run. Round two moved the decision
    here — see tests/test_extraction_postprocess.py for the full set."""
    from parser import extraction_postprocess as pp
    assert pp.is_hedged(hedge)


def test_the_prompt_no_longer_asks_the_model_to_judge_modality():
    """The instruction that did not work. If it comes back, the model is
    being asked for a judgement again and the hedge filter has a second,
    disagreeing opinion upstream of it."""
    assert "NOT a claim" not in PROMPT
    assert "Record every candidate" in PROMPT
    assert "the judgement is not yours to make" in PROMPT


def test_row_25_hedges_alone_no_longer_reach_the_classifier():
    """The correction that changes an outcome. With the three hedged
    sentences out of brand_claims, the same answer is the honest one it
    always was."""
    assessment, _ = classify(
        brand_claims=[],
        brand_unknown_statement='"Wiggle & Snug" is not a widely recognized or prominent diaper brand',
    )
    assert assessment == c.ACKNOWLEDGED_UNKNOWN


def test_row_25_an_unlabelled_claim_can_no_longer_reach_fabricated():
    """Round three closed the last route. An unlabelled claim is not an
    asserted claim, so a hedge that slips into brand_claims cannot
    produce a fabrication on its own."""
    assessment, _ = classify(
        brand_claims=[{"claim": "It's possible it's a regional brand", "kind": "other"}],
        brand_unknown_statement='not a widely recognized brand',
    )
    assert assessment == c.ACKNOWLEDGED_UNKNOWN


def test_a_claim_labelled_asserted_still_reaches_fabricated():
    """The other half — the mechanism still works when the labeller says
    the answer committed to something."""
    assessment, _ = classify(
        brand_claims=[{
            "claim": "sold at Aldi", "sentence": "It is sold at Aldi.",
            "kind": "assertion", "modality": "asserted",
        }],
    )
    assert assessment == c.FABRICATED


# ── Row 26 — a freshness disclaimer is not a can't-find ───────────────────

def test_the_freshness_disclaimer_is_ruled_out_in_code():
    from parser import extraction_postprocess as pp
    assert not pp.looks_unknown(
        "I don't have real-time access to the absolute latest ingredient list"
    )
    assert pp.is_disclaimer(
        "I don't have real-time access to the absolute latest ingredient list"
    )


def test_the_prompt_asks_for_the_candidate_sentence_and_stops():
    assert "Quote the candidate and stop there" in PROMPT


def test_row_26_an_answer_that_treats_the_brand_as_real_is_not_an_admission():
    """It said it lacked real-time access to the ingredient list and then
    described the wipes as highly likely to suit sensitive skin. That is
    an answer about a brand it found."""
    assessment, _ = classify(brand_unknown_statement=None)
    assert assessment == c.ECHOED


# ── Rows 30 and 36 — the model should never have been asked ───────────────

def test_row_30_an_answer_naming_the_brand_in_passing_still_names_it():
    """"on eligible Wiggle & Snug products" — recorded as not mentioning
    the brand, which scored the row `absent`."""
    record = stamp_brand_mentioned({}, "5% back on eligible Wiggle & Snug products", BRAND)
    assert record["brand_mentioned"] is True


def test_row_36_an_answer_about_other_brands_did_not_name_this_one():
    """It named "Wonder" and "The Wiggles" and never Wiggle & Snug —
    recorded as a mention, which put an answer about somebody else onto
    the brand axis."""
    record = stamp_brand_mentioned(
        {}, "You might mean Wonder, or The Wiggles.", BRAND,
    )
    assert record["brand_mentioned"] is False


def test_the_two_rows_disagree_with_each_other_which_is_the_point():
    """Row 35 was the same situation as 36 and was handled correctly. A
    field that is right sometimes is a field nobody can act on."""
    assert ea.names_brand("eligible Wiggle & Snug products", BRAND)
    assert not ea.names_brand("Wonder, or The Wiggles", BRAND)


def test_the_check_is_the_same_one_the_generator_uses():
    """One definition. A question that passes the generation guard and an
    answer that satisfies this check are agreeing about the same rule."""
    from generation import brand_direct_guard as bdg
    assert bdg.names_brand is ea.names_brand


# ── Row 7 — presented_as is a word from a list ────────────────────────────

def test_presented_as_is_an_enum_and_not_a_sentence_fragment():
    field = SCHEMA["properties"]["other_brands_named"]["items"]["properties"]
    assert field["presented_as"]["enum"] == [
        "closest_match", "comparison", "recommendation", "source", None,
    ]


def test_the_prompt_forbids_fragments_by_name():
    assert '"the", "like", "such as" are not values for this field' in PROMPT


def test_only_a_described_closest_match_is_a_substitution():
    """Round three: the labeller's relation decides, and only one of its
    four values means the answer both substituted and described."""
    assert c._is_substitution({"name": "X", "relation": "closest_match_described"})
    for other in ("spelling_guess", "citation_only", "comparison"):
        assert not c._is_substitution({"name": "X", "relation": other})


def test_a_recommendation_that_takes_the_numbers_with_it_is_still_misattribution():
    """The label is not the whole test. A brand presented as a
    recommendation, with the answer's figures hung on its product, is
    answering about that brand."""
    assessment, reason = classify(
        other_brands_named=[{"name": "Amallow", "presented_as": "recommendation"}],
        pack_counts=[{"value": 4, "attributed_product": "Amallow Baby Bum Balm"}],
    )
    assert assessment == c.MISATTRIBUTED
    assert "Amallow" in reason


def test_a_comparison_is_never_a_substitution():
    assessment, _ = classify(
        other_brands_named=[{"name": "Pampers", "presented_as": "comparison"}],
        sources_cited=["trueshopstore.com"],
    )
    assert assessment == c.GROUNDED


def test_an_unlabelled_entry_falls_back_to_the_old_free_text():
    """Extractions stored under the old prompt are still in the database.
    A re-score over them must not quietly stop finding substitutions it
    used to find — but an entry with no label and no phrase is never a
    substitution by default."""
    assert c._is_substitution({"name": "X", "presented_as": "closest match"})
    assert c._is_substitution({"name": "X", "presented_as": "if you meant"})
    assert not c._is_substitution({"name": "X"})
    assert not c._is_substitution({"name": "X", "presented_as": "comparison"})
