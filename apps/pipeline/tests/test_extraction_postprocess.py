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
from scoring import brand_direct_classifier as c
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


def labelled(answer="...", labels=None, brand=BRAND, **kw):
    """Transcription, then the labelling pass — the whole chain, with the
    labeller's answer supplied rather than called for."""
    return pp.apply_labels(
        run(answer=answer, **kw), labels or {},
        answer_text=answer, brand=brand,
    )


def spans_of(answer):
    from parser.span_segmenter import segment
    return segment(answer)


def label_all(answer, **kinds):
    """Label every span of `answer`. `kinds` maps a substring to
    (kind, modality); anything unmatched is labelled `none`, so the
    coverage check has nothing to complain about."""
    out = []
    for span in spans_of(answer):
        kind, modality = 'none', 'asserted'
        for needle, value in kinds.items():
            if needle.replace('_', ' ') in span['text'].lower():
                kind, modality = value if isinstance(value, tuple) else (value, 'asserted')
                break
        out.append({'span_id': span['id'], 'kind': kind, 'modality': modality})
    return {'spans': out}


def sentence(text, kind, modality="asserted"):
    return {"sentence": text, "kind": kind, "modality": modality}


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
    """The lexicon reads the sentence a claim came from, not the claim.
    It is a cross-check now — the label decides — but it must still read
    the right string."""
    out = run(brand_claims=[{
        "claim": "it is a regional brand",
        "sentence": "It's possible that this is a very new, small, or regional brand.",
        "kind": "other",
    }])
    assert out["brand_claims"][0]["lexicon_hedged"] is True


def test_an_unlabelled_claim_is_not_an_asserted_claim():
    """The rule that keeps a failed labelling call from becoming a
    fabrication. No label means no claim, never "treat it as
    asserted"."""
    out = run(brand_claims=[{
        "claim": "sold at Aldi", "sentence": "It is sold at Aldi.", "kind": "retail",
    }])
    assert pp.asserted_claims(out) == []


def test_a_claim_the_labeller_calls_asserted_survives():
    text = "Wiggle & Snug is a private label brand sold exclusively at Kohl's."
    out = labelled(answer=text, labels=label_all(text, kohl=("assertion", "asserted")))
    assert len(pp.asserted_claims(out)) == 1


def test_a_claim_the_labeller_calls_hedged_does_not():
    text = "It's possible that this is a very new, small, or regional brand."
    out = labelled(answer=text, labels=label_all(text, possible=("assertion", "hedged")))
    assert pp.asserted_claims(out) == []


def test_a_conditional_fragment_is_not_an_assertion():
    text = "If it's a store brand, availability would be limited."
    out = labelled(answer=text,
                   labels=label_all(text, store=("assertion", "conditional")))
    assert pp.asserted_claims(out) == []


def test_an_instruction_to_the_reader_is_never_a_claim():
    """One row's whole fabricated verdict rested on "it's always best to
    double-check the weight ranges on the packaging or their official
    website" being read as a claim about the brand."""
    text = ("It's always best to double-check the weight ranges on the "
            "Wiggle & Snug packaging or their official website.")
    out = labelled(answer=text, labels=label_all(text, **{"double-check": "instruction"}))
    assert out["brand_claims"] == []
    assert pp.asserted_claims(out) == []


def test_the_lexicon_and_the_label_disagreeing_is_surfaced_not_resolved():
    """One row said "Wiggle & Snug is a Wiggle own-brand" and the lexicon
    called it hedged. Neither side gets to win quietly."""
    text = "Wiggle & Snug is typically a Wiggle own-brand."
    out = labelled(answer=text, labels=label_all(text, own=("assertion", "asserted")))
    (flag,) = out["needs_review"]
    assert flag["lexicon"] == "hedged"
    assert flag["label"] == "asserted"


def test_agreement_raises_no_flag():
    text = "Wiggle & Snug is possibly a regional brand."
    out = labelled(answer=text, labels=label_all(text, possibly=("assertion", "hedged")))
    assert out["needs_review"] == []


def test_a_claim_with_no_sentence_falls_back_to_its_own_text():
    """Older stored records have no sentence field."""
    out = run(brand_claims=[{"claim": "It might be a store brand", "kind": "other"}])
    assert out["brand_claims"][0]["lexicon_hedged"] is True


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


def test_row_40_a_disclaimer_leaves_no_unknown_and_no_claim():
    """The answer treats the brand as real and merely lacks the
    packaging. There is no finding here, so nothing is recorded — but it
    is the LABEL that says so, not the lexicon."""
    text = ("Without having the specific Wiggle & Snug product in front of me, "
            "I cannot give a definitive yes or no.")
    out = labelled(answer=text, labels=label_all(text, without="disclaimer"))
    assert out["brand_unknown_statement"] is None
    assert out["brand_claims"] == []


def test_an_unlabelled_brand_span_is_a_finding_not_a_silence():
    """The failure this whole round is for. One answer's headline —
    "It appears that Wiggle & Snug Bum Balm 4 oz has been discontinued" —
    reached neither the claims nor the unknown statement, and nothing
    recorded that it had gone missing."""
    text = "It appears that Wiggle & Snug Bum Balm 4 oz has been discontinued."
    out = labelled(answer=text, labels={"spans": []})
    (gap,) = out["needs_review"]
    assert gap["reason"] == "a span naming the brand came back unlabelled"
    assert gap["text"] == text


def test_a_span_the_labeller_declined_is_not_a_gap():
    """"none" is a real answer. Never coming back is not."""
    text = "It appears that Wiggle & Snug Bum Balm 4 oz has been discontinued."
    out = labelled(answer=text, labels=label_all(text))
    assert out["needs_review"] == []


def test_a_span_that_does_not_name_the_brand_need_not_be_labelled():
    text = "Most overnight diapers hold more liquid than daytime ones."
    out = labelled(answer=text, labels={"spans": []})
    assert out["needs_review"] == []


def test_row_26_an_assertion_filed_as_an_unknown_becomes_a_claim():
    """"Wiggle & Snug does not currently offer a member rewards program"
    is a statement ABOUT the brand, and a false one — the record
    publishes Member and Member+."""
    text = ("Wiggle & Snug does not currently offer a member rewards program "
            "with specific tiers.")
    out = labelled(answer=text,
                   brand_unknown_statement=text,
                   labels=label_all(text, rewards=("assertion", "asserted")))
    assert out["brand_unknown_statement"] is None
    (claim,) = out["brand_claims"]
    assert claim["claim_kind"] == "loyalty"
    assert pp.asserted_claims(out) == [claim]


def test_a_cannot_find_sentence_filed_as_a_claim_becomes_the_unknown():
    """Two samples had it the other way round."""
    text = ("I did not find a reliable current product page specifically for "
            "Wiggle & Snug Bum Balm.")
    out = labelled(answer=text, labels=label_all(text, **{"did not find": "unknown_statement"}))
    assert out["brand_unknown_statement"] == text
    assert out["brand_claims"] == []


def test_a_real_cannot_find_is_left_exactly_where_it_was():
    statement = '"Wiggle & Snug" is not a real or widely recognized brand of diapers.'
    out = run(brand_unknown_statement=statement)
    assert out["brand_unknown_statement"] == statement
    assert out["brand_claims"] == []


def test_a_promoted_assertion_that_was_hedged_is_not_an_asserted_claim():
    text = "It's possible Wiggle & Snug no longer run a rewards programme."
    out = labelled(answer=text, labels=label_all(text, possible=("assertion", "hedged")))
    (claim,) = out["brand_claims"]
    assert claim["modality"] == "hedged"
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

def test_row_34_alternate_spelling_guesses_are_kept_and_labelled():
    """The revert. Dropping them lost the record of what the answer did;
    the label is what stops them driving misattributed. The same rule
    deleted two brands the answer DID describe, in the same sample."""
    out = labelled(
        answer="Could it be Wiggles & Giggles, or Snuggle & Snug?",
        other_brands_named=[
            {"name": "Wiggles & Giggles"}, {"name": "Snuggle & Snug"},
        ],
        labels={"other_brands": [
            {"name": "Wiggles & Giggles", "relation": "spelling_guess"},
            {"name": "Snuggle & Snug", "relation": "spelling_guess"},
        ]},
    )
    assert [e["name"] for e in out["other_brands_named"]] == [
        "Wiggles & Giggles", "Snuggle & Snug",
    ]
    assert all(e["relation"] == "spelling_guess" for e in out["other_brands_named"])
    assert c.misattributed_to(out) is None


def test_a_described_closest_match_still_drives_misattributed():
    out = labelled(
        other_brands_named=[{"name": "Huggies Snug & Dry"}],
        labels={"other_brands": [
            {"name": "Huggies Snug & Dry", "relation": "closest_match_described"},
        ]},
    )
    assert c.misattributed_to(out) == "Huggies Snug & Dry"


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
        {"name": "Wiggle & Snug"}, {"name": "wiggle and snug"},
        {"name": "Pampers"},
    ])
    assert [e["name"] for e in out["other_brands_named"]] == ["Pampers"]


def test_a_brand_sharing_a_word_with_ours_is_not_ours():
    """"Wiggle" is a UK sports retailer that one answer explicitly
    distinguishes from Wiggle & Snug. Dropping it as "is the brand"
    deleted the one thing that answer was doing."""
    out = run(other_brands_named=[{"name": "Wiggle"}])
    assert [e["name"] for e in out["other_brands_named"]] == ["Wiggle"]


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
