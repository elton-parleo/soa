"""
The deterministic pass, on the rows from both hand-checks.

Round one: 10 of 40 disagreed. Round two, after the prompt was corrected:
8 of 40. The second set is the argument for this module — four of the
eight were the model applying a rule the prompt had spelled out, and
applying it differently to two answers of the same shape in the same run.

So the rules moved into code, and these are the rows that moved them.
Each test is named by its row in the validation sheet and the sample it
came from.
"""
import pytest

from parser import extraction_postprocess as pp
from soa_shared import expected_answers as ea

BRAND = "Wiggle & Snug"
DOMAIN = "trueshopstore.com"


def record(**kw):
    base = {
        "prices": [], "codes": [], "pack_counts": [], "sizes": [], "gtins": [],
        "member_prices": [], "points": [], "brand_unknown_statement": None,
        "other_brands_named": [], "loyalty_tiers_named": [], "brand_claims": [],
        "sources_cited": [], "recommended_retailers": [],
        "extraction_confident": True, "extraction_note": None,
    }
    base.update(kw)
    return base


def run(answer="...", **kw):
    return pp.normalize(
        record(**kw), answer_text=answer, brand=BRAND, brand_domain=DOMAIN,
    )


# ── (1) Modality — rows 7, 17, 25, 34 ─────────────────────────────────────

@pytest.mark.parametrize("sentence", [
    # Row 7 (WIG_148 gemini 3) and row 25 (WIG_141 gemini 1), verbatim.
    "It's possible that this is a very new, small, or regional brand.",
    "It's possible it's a fictional brand.",
    # Row 17 (WIG_140 gemini 2).
    "It might be a very new, regional, store-specific brand.",
    "If it's a store brand, availability would be limited.",
    # Row 34 (WIG_148 gemini 2) — left out by the model on this run, put
    # in on another. Same shape either way.
    "It might be a fictional product or a local item.",
    # The rest of the marker list.
    "They likely emphasise a closer fit.",
    "This may be a private label.",
    "It could be sold only in some regions.",
    "Perhaps it was discontinued.",
    "It appears to be a store brand.",
    "It seems to be sold online only.",
    "The name suggests a snug fit.",
])
def test_a_hedged_sentence_is_hedged(sentence):
    assert pp.is_hedged(sentence)


@pytest.mark.parametrize("sentence", [
    "Wiggle & Snug is a private label brand sold exclusively at Kohl's.",
    "The tiers are called Snuggle Friend, Snuggle Pal and Snuggle Bestie.",
    "Wiggle & Snug does not currently offer a member rewards program.",
    "It is sold at Aldi.",
    "The product launched in May 2024.",
])
def test_an_asserted_sentence_is_not_hedged(sentence):
    assert not pp.is_hedged(sentence)


def test_may_the_month_is_not_may_the_hedge():
    """The reason 'may' and 'may be' are separate markers. A claim about
    a launch date is a claim."""
    assert not pp.is_hedged("The line launched in May 2024.")
    assert pp.is_hedged("It may be a store brand.")


def test_the_hedge_is_decided_from_the_sentence_not_the_claim():
    """The model extracts a claim and the sentence it came from. A claim
    phrased flatly inside a hedged sentence is still hedged — which is
    exactly what rows 7, 17 and 25 looked like."""
    out = run(brand_claims=[{
        "claim": "it is a regional brand",
        "sentence": "It's possible that this is a very new, small, or regional brand.",
        "kind": "other",
    }])
    assert out["brand_claims"][0]["hedged"] is True
    assert pp.asserted_claims(out) == []


def test_an_asserted_claim_survives_the_filter():
    out = run(brand_claims=[{
        "claim": "sold exclusively at Kohl's",
        "sentence": "Wiggle & Snug is a private label brand sold exclusively at Kohl's.",
        "kind": "retail",
    }])
    assert out["brand_claims"][0]["hedged"] is False
    assert len(pp.asserted_claims(out)) == 1


def test_the_pass_says_how_many_it_hedged():
    out = run(brand_claims=[
        {"claim": "a", "sentence": "It's possible it is a regional brand.", "kind": "other"},
        {"claim": "b", "sentence": "It might be fictional.", "kind": "other"},
        {"claim": "c", "sentence": "It is sold at Aldi.", "kind": "retail"},
    ])
    assert any("2 claim(s) hedged" in note for note in out["postprocess"])


def test_a_claim_with_no_sentence_falls_back_to_its_own_text():
    """Older stored records have no sentence field. Judging the claim
    text is worse than judging the sentence and better than judging
    nothing."""
    out = run(brand_claims=[{"claim": "It might be a store brand", "kind": "other"}])
    assert out["brand_claims"][0]["hedged"] is True


# ── (2) Unknown statements — rows 26 and 40 ───────────────────────────────

@pytest.mark.parametrize("sentence", [
    "I couldn't find any information about that brand.",
    "I could not find an official product page.",
    "I can't verify a current listing for Wiggle & Snug.",
    "I'm not familiar with that brand.",
    "I have no information about this company.",
    '"Wiggle & Snug" is not a real or widely recognized brand of diapers.',
    "It does not appear to exist.",
    "I haven't been able to find any information on that brand.",
    "I've never heard of it.",
])
def test_a_cannot_find_sentence_qualifies(sentence):
    assert pp.looks_unknown(sentence)


@pytest.mark.parametrize("sentence", [
    # Row 26 of round one and row 40 of round two, verbatim.
    "I don't have real-time access to the absolute latest ingredient list.",
    "Without having the specific product in front of me, I cannot give a "
    "definitive yes or no.",
    "My knowledge cutoff means I may not have the most recent information.",
    "I can't browse the web to check the current page.",
])
def test_a_disclaimer_about_our_own_reach_never_qualifies(sentence):
    assert not pp.looks_unknown(sentence)
    assert pp.is_disclaimer(sentence)


def test_row_40_a_disclaimer_is_dropped_and_leaves_no_claim_behind():
    """The answer treats the brand as real and merely lacks the
    packaging. There is no finding here, so nothing is recorded."""
    out = run(brand_unknown_statement=(
        "Without having the specific product in front of me, I cannot give a "
        "definitive yes or no."
    ))
    assert out["brand_unknown_statement"] is None
    assert out["brand_claims"] == []
    assert any("disclaimer" in note for note in out["postprocess"])


def test_row_26_an_assertion_filed_as_an_unknown_becomes_a_claim():
    """The correction that flipped an outcome. "Wiggle & Snug does not
    currently offer a member rewards program" is a statement ABOUT the
    brand, and a false one — the record publishes Member and Member+."""
    out = run(brand_unknown_statement=(
        "Wiggle & Snug does not currently offer a member rewards program "
        "called 'Wiggle & Snug Member Rewards' with specific tiers."
    ))
    assert out["brand_unknown_statement"] is None
    (claim,) = out["brand_claims"]
    assert claim["kind"] == "loyalty"
    assert claim["hedged"] is False
    assert any("moved to claims" in note for note in out["postprocess"])


def test_a_real_cannot_find_is_left_exactly_where_it_was():
    statement = '"Wiggle & Snug" is not a real or widely recognized brand of diapers.'
    out = run(brand_unknown_statement=statement)
    assert out["brand_unknown_statement"] == statement
    assert out["brand_claims"] == []


def test_a_promoted_assertion_that_was_hedged_is_still_hedged():
    out = run(brand_unknown_statement=(
        "It's possible they no longer run a rewards programme."
    ))
    (claim,) = out["brand_claims"]
    assert claim["hedged"] is True
    assert pp.asserted_claims(out) == []


@pytest.mark.parametrize("sentence,kind", [
    ("It does not offer a member rewards program.", "loyalty"),
    ("It is sold exclusively at Kohl's.", "retail"),
    ("It is owned by a supermarket group.", "ownership"),
    ("The line launched in 2024.", "other"),
])
def test_a_promoted_assertion_gets_a_kind_from_its_words(sentence, kind):
    assert pp.claim_kind(sentence) == kind


# ── (3) brand_mentioned — row 36 ──────────────────────────────────────────

@pytest.mark.parametrize("answer", [
    "Wiggle & Snug sells diapers.",
    "wiggle and snug sells diapers.",
    "Wiggle&Snug sells diapers.",
    "WIGGLE & SNUG sells diapers.",
    "5% back on eligible Wiggle & Snug products.",
])
def test_every_way_the_brand_is_written_counts_as_naming_it(answer):
    assert run(answer=answer)["brand_mentioned"] is True


@pytest.mark.parametrize("answer", [
    # Row 36, both samples. Named Wonder and The Wiggles and never this
    # brand; recorded as a mention, which put an answer about somebody
    # else onto the brand axis.
    "You might mean Wonder, or The Wiggles.",
    "There is a retailer called Wiggle, but that is not the same thing.",
    "Snug-Fit diapers are a common product type.",
])
def test_a_partial_token_is_never_the_brand(answer):
    assert run(answer=answer)["brand_mentioned"] is False


def test_no_answer_at_all_names_nobody():
    assert run(answer="")["brand_mentioned"] is False
    assert run(answer=None)["brand_mentioned"] is False


# ── (4) Currency — row 27 ─────────────────────────────────────────────────

@pytest.mark.parametrize("written,code", [
    ("$", "USD"), ("US$", "USD"), ("USD", "USD"),
    ("£", "GBP"), ("GBP", "GBP"),
    ("€", "EUR"), ("EUR", "EUR"),
    ("Rs.", "INR"), ("Rs", "INR"), ("₹", "INR"), ("INR", "INR"),
])
def test_the_table_maps_what_answers_actually_write(written, code):
    assert ea.normalize_currency(written) == code


def test_row_27_rs_becomes_inr_rather_than_staying_a_raw_string():
    """The regression: one sample read this same answer as INR and the
    next as "Rs.", which no expectation will ever match."""
    out = run(prices=[{"amount": "255.00", "currency": "Rs.",
                       "attributed_product": "Trial Pack"}])
    assert out["prices"][0]["currency"] == "INR"
    assert out["extraction_confident"] is True


def test_a_currency_nothing_can_read_makes_the_run_unscoreable():
    """Never a raw string. Calling it a match and calling it a mismatch
    are both claims about the assistant made out of our own confusion."""
    out = run(prices=[{"amount": "10.00", "currency": "CA$",
                       "attributed_product": "x"}])
    assert out["extraction_confident"] is False
    assert "CA$" in out["extraction_note"]
    assert any("unreadable currency" in note for note in out["postprocess"])


def test_a_price_with_no_currency_stays_scoreable():
    """A bare number is not a confusing currency, it is no currency —
    and the comparator already treats that as agreement rather than as a
    mismatch."""
    out = run(prices=[{"amount": "10.00", "currency": None,
                       "attributed_product": "x"}])
    assert out["extraction_confident"] is True
    assert out["prices"][0]["currency"] is None


def test_member_prices_go_through_the_same_table():
    out = run(member_prices=[{"amount": "8.00", "currency": "£",
                              "tier": "Member", "attributed_product": "x"}])
    assert out["member_prices"][0]["currency"] == "GBP"


# ── (5) closest_match needs something attributed — row 34 ─────────────────

def test_row_34_alternate_spelling_guesses_are_dropped():
    """The answer offered "Wiggles & Giggles" and "Snuggle & Snug" as
    guesses at what the asker might have meant and described neither. It
    was scored misattributed for describing a brand it never
    described."""
    out = run(
        answer="Could it be Wiggles & Giggles, or Snuggle & Snug?",
        other_brands_named=[
            {"name": "Wiggles & Giggles", "presented_as": "closest_match"},
            {"name": "Snuggle & Snug", "presented_as": "closest_match"},
        ],
    )
    assert out["other_brands_named"] == []
    assert any("describes nothing" in note for note in out["postprocess"])


def test_a_closest_match_that_carries_a_price_survives():
    out = run(
        other_brands_named=[{"name": "Beezpro", "presented_as": "closest_match"}],
        prices=[{"amount": "255.00", "currency": "Rs.",
                 "attributed_product": "Beezpro Snug Fit Trial Pack"}],
    )
    assert [e["name"] for e in out["other_brands_named"]] == ["Beezpro"]


def test_a_closest_match_that_carries_a_claim_survives():
    out = run(
        other_brands_named=[{"name": "Huggies", "presented_as": "closest_match"}],
        brand_claims=[{
            "claim": "Huggies Little Snugglers is suitable for newborns",
            "sentence": "Huggies Little Snugglers is suitable for newborns.",
            "kind": "other",
        }],
    )
    assert [e["name"] for e in out["other_brands_named"]] == ["Huggies"]


def test_a_closest_match_that_carries_a_citation_survives():
    out = run(
        other_brands_named=[{"name": "Amallow", "presented_as": "closest_match"}],
        sources_cited=["amallow.com"],
    )
    assert [e["name"] for e in out["other_brands_named"]] == ["Amallow"]


def test_the_requirement_is_only_on_closest_match():
    """A comparison or a recommendation is not claiming to BE the brand,
    so it does not have to describe anything to be worth recording."""
    out = run(other_brands_named=[
        {"name": "Pampers", "presented_as": "comparison"},
        {"name": "Desitin", "presented_as": "recommendation"},
    ])
    assert [e["name"] for e in out["other_brands_named"]] == ["Pampers", "Desitin"]


# ── (6) Hygiene ───────────────────────────────────────────────────────────

def test_the_brand_is_never_one_of_the_other_brands():
    out = run(other_brands_named=[
        {"name": "Wiggle & Snug", "presented_as": "comparison"},
        {"name": "wiggle and snug", "presented_as": "closest_match"},
        {"name": "Pampers", "presented_as": "comparison"},
    ])
    assert [e["name"] for e in out["other_brands_named"]] == ["Pampers"]


def test_the_brands_own_site_is_never_another_brand():
    out = run(other_brands_named=[
        {"name": "trueshopstore.com", "presented_as": "source"},
        {"name": "Pampers", "presented_as": "comparison"},
    ])
    assert [e["name"] for e in out["other_brands_named"]] == ["Pampers"]


def test_a_retailer_a_price_came_from_is_a_source_not_a_suggestion():
    """Counting it twice would turn a cited answer into an unsourced
    availability claim, which is the thing fabricated is for."""
    out = run(
        sources_cited=["beezpro.in"],
        recommended_retailers=["Beezpro", "Amazon"],
    )
    assert out["recommended_retailers"] == ["Amazon"]
    assert any("were sources" in note for note in out["postprocess"])


@pytest.mark.parametrize("field,items,kept", [
    ("sources_cited", ["target.com", "Target.com", "target.com"], 1),
    ("recommended_retailers", ["Amazon", "amazon", "Amazon"], 1),
    ("loyalty_tiers_named", ["Member", "member", "Member+"], 2),
])
def test_duplicates_are_collapsed(field, items, kept):
    assert len(run(**{field: items})[field]) == kept


def test_duplicate_claims_are_collapsed():
    out = run(brand_claims=[
        {"claim": "sold at Aldi", "sentence": "It is sold at Aldi.", "kind": "retail"},
        {"claim": "Sold at Aldi", "sentence": "It is sold at Aldi.", "kind": "retail"},
    ])
    assert len(out["brand_claims"]) == 1


def test_an_empty_list_survives_every_step():
    out = run()
    for field in ("prices", "brand_claims", "other_brands_named",
                  "recommended_retailers", "sources_cited", "loyalty_tiers_named"):
        assert out[field] == []
    assert out["postprocess"] == []


def test_the_pass_never_raises_on_a_malformed_record():
    """A model that returns the wrong shape is our problem to survive,
    not the study's."""
    out = pp.normalize(
        {"prices": [None, "nonsense"], "brand_claims": [None, {}],
         "other_brands_named": [None, {"presented_as": "closest_match"}],
         "recommended_retailers": [None, ""], "sources_cited": None},
        answer_text="x", brand=BRAND, brand_domain=DOMAIN,
    )
    assert out["brand_claims"] == []
    assert out["other_brands_named"] == []
