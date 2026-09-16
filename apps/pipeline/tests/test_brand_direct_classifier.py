"""
Classifying a brand-direct answer, on fixtures taken from cycle
20260915-113207-wiggle-snug-full.

Every case below is a real run from that cycle, named by its run_id. The
extraction fields the classifier reads (brand_unknown_statement,
other_brands_named, brand_claims) did not exist when that cycle was
scored, so they are written here as the transcription prompt now asks for
them — quoted from the answer, never summarised. The rest of each
extraction is exactly what was stored.

All 66 of those runs scored `exact` or `absent`. 63 were `exact`.
"""
import json
import os

import pytest

from scoring import brand_direct_classifier as c

BRAND = "Wiggle & Snug"
EXPECTATION = {"type": "brand_mention", "brand": BRAND, "domain": "trueshopstore.com"}

# What the record actually publishes, from the study's own merchant block.
FACTS = {
    "domain": "trueshopstore.com",
    "tier_names": ["Member", "Member+"],
    "product_titles": [
        "Snug-Fit Diapers", "Snug-Fit Overnight Diapers", "Cloud Wipes",
        "Bum Balm", "Snug-Fit Trial Pack",
    ],
}

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "wiggle_and_snug_brand_direct_outcomes.json",
)


@pytest.fixture(scope="module")
def body():
    with open(FIXTURE) as fh:
        return json.load(fh)


def extraction(**kw):
    base = {
        "prices": [], "codes": [], "pack_counts": [], "gtins": [],
        "member_prices": [], "points": [], "brand_mentioned": True,
        "brand_unknown_statement": None, "other_brands_named": [],
        "loyalty_tiers_named": [], "brand_claims": [], "sources_cited": [],
        "extraction_confident": True, "extraction_note": None,
    }
    base.update(kw)
    return base


def classify(**kw):
    return c.classify(extraction(**kw), EXPECTATION, brand_facts=FACTS)


# ── the fixture is the cycle ──────────────────────────────────────────────

def test_the_fixture_is_the_body_the_endpoint_returned(body):
    assert body["cycle_code"] == "20260915-113207-wiggle-snug-full"
    assert body["tier"] == "brand_direct"
    assert len(body["outcomes"]) == 66


def test_the_old_scoring_called_sixty_three_of_them_exact(body):
    outcomes = [o["outcome"] for o in body["outcomes"]]
    assert outcomes.count("exact") == 63
    assert outcomes.count("absent") == 3


# ── acknowledged_unknown ──────────────────────────────────────────────────

def test_run_10636_not_a_real_brand_is_not_a_success():
    """Gemini: 'Wiggle & Snug Snug-Fit Diapers is not a real or widely
    recognized brand of diapers.' The single worst result in the study,
    and the old scoring's cleanest `exact`."""
    assessment, reason = classify(
        brand_unknown_statement=(
            '"Wiggle & Snug Snug-Fit Diapers" is not a real or widely '
            'recognized brand of diapers'
        ),
    )
    assert assessment == c.ACKNOWLEDGED_UNKNOWN
    assert "not a real" in reason


def test_run_10660_cannot_find_any_information():
    assessment, _ = classify(
        brand_unknown_statement=(
            'I cannot find any information about a company named '
            '"Wiggle & Snug"'
        ),
    )
    assert assessment == c.ACKNOWLEDGED_UNKNOWN


def test_run_10814_could_not_verify_a_listing():
    assessment, _ = classify(
        brand_unknown_statement=(
            'I couldn’t reliably verify a current store/brand listing for '
            '“Wiggle & Snug” from public search results'
        ),
    )
    assert assessment == c.ACKNOWLEDGED_UNKNOWN


def test_hedging_about_one_detail_is_not_acknowledging_the_brand_is_unknown():
    """The extractor is told to leave the statement null unless the answer
    says it cannot find the BRAND. Nothing here should invent one."""
    assessment, _ = classify(sources_cited=["trueshopstore.com"])
    assert assessment == c.GROUNDED


# ── misattributed ─────────────────────────────────────────────────────────

def test_run_10819_the_specifics_belong_to_bc_babycare():
    """'assuming you mean the Bc Babycare "Cloud Moist Baby Wipes" 3-pack
    / 240 count listing' — the counts are attached to their product."""
    assessment, reason = classify(
        pack_counts=[
            {"value": 3, "attributed_product": 'Bc Babycare “Cloud Moist Baby Wipes”'},
            {"value": 240, "attributed_product": 'Bc Babycare “Cloud Moist Baby Wipes”'},
        ],
        other_brands_named=[{"name": "Bc Babycare", "presented_as": "assuming you mean"}],
        brand_unknown_statement='I couldn’t verify a product specifically branded “Wiggle & Snug Cloud Wipes”',
        sources_cited=["target.com", "publications.aap.org"],
    )
    assert assessment == c.MISATTRIBUTED
    assert "Bc Babycare" in reason


def test_run_10834_the_closest_match_was_beezpro():
    assessment, reason = classify(
        prices=[{
            "amount": "255.00", "currency": "Rs.",
            "attributed_product": 'Beezpro’s “Snug Fit Padded underwear Single Piece Trial Pack”',
        }],
        other_brands_named=[{"name": "Beezpro", "presented_as": "closest match"}],
        sources_cited=["beezpro.in"],
    )
    assert assessment == c.MISATTRIBUTED
    assert "Beezpro" in reason


def test_run_10815_huggies_offered_with_no_number_at_all():
    """'If you meant Huggies Little Snugglers or Huggies Snug & Dry, then
    yes...' — no quantity is attributed, so the substitution phrase is
    the only thing that can catch it."""
    assessment, reason = classify(
        other_brands_named=[
            {"name": "Huggies Little Snugglers", "presented_as": "if you meant"},
            {"name": "Huggies Snug & Dry", "presented_as": "if you meant"},
        ],
        brand_unknown_statement='I couldn’t verify a diaper brand/product specifically called “Wiggle & Snug Snug-Fit Diapers”',
        sources_cited=["target.com", "healthychildren.org"],
    )
    assert assessment == c.MISATTRIBUTED
    assert "Huggies" in reason


def test_run_10672_wiggle_and_giggle():
    assessment, reason = classify(
        pack_counts=[{"value": 4, "attributed_product": "Wiggle & Giggle Organic Baby Bum Balm 4 oz"}],
        other_brands_named=[{"name": "Wiggle & Giggle", "presented_as": "you might be looking for"}],
        sources_cited=["amazon.com"],
    )
    assert assessment == c.MISATTRIBUTED


def test_misattribution_outranks_the_admission_that_came_with_it():
    """Most of these answers say both. The reader still walks away with
    the other brand, so that is what gets recorded."""
    assessment, _ = classify(
        other_brands_named=[{"name": "Amallow", "presented_as": "closest match"}],
        brand_unknown_statement='I couldn’t verify a current product under the exact name “Wiggle & Snug Bum Balm 4 oz”',
        pack_counts=[{"value": 4, "attributed_product": "Amallow Baby Bum Balm, 4 oz"}],
        sources_cited=["amallow.com"],
    )
    assert assessment == c.MISATTRIBUTED


def test_a_brand_named_without_being_offered_in_place_of_ours_is_not_misattribution():
    """A comparison is not a substitution. 'Unlike Pampers, this one...'
    names another brand and answers about ours."""
    assessment, _ = classify(
        other_brands_named=[{"name": "Pampers", "presented_as": "comparison"}],
        sources_cited=["trueshopstore.com"],
    )
    assert assessment == c.GROUNDED


# ── fabricated ────────────────────────────────────────────────────────────

def test_run_10628_a_private_label_at_aldi():
    """Labelled now, because round three made a claim count only when the
    labelling pass says the answer asserted it."""
    assessment, reason = classify(
        brand_claims=[{
            "claim": "They are a private label brand sold at Aldi",
            "sentence": "They are a private label brand sold at Aldi.",
            "kind": "assertion", "modality": "asserted", "claim_kind": "retail",
        }],
    )
    assert assessment == c.FABRICATED
    assert "no source" in reason


def test_the_same_sentence_hedged_is_not_a_fabrication():
    """The verbatim hedge from the answer this row came from."""
    assessment, _ = classify(
        brand_claims=[{
            "claim": "a private label brand",
            "sentence": "They are possibly a private label brand, often associated "
                        "with supermarkets like Aldi.",
            "kind": "assertion", "modality": "hedged", "claim_kind": "retail",
        }],
    )
    assert assessment == c.ECHOED


def test_run_10651_exclusive_to_kohls():
    assessment, _ = classify(
        brand_claims=[{
            "claim": "Wiggle & Snug is a private label brand sold exclusively at Kohl's",
            "kind": "retail",
        }],
        loyalty_tiers_named=["Kohl's Rewards Member", "Kohl's Rewards Credit Cardholder"],
    )
    assert assessment == c.FABRICATED


def test_run_10650_snuggle_friend_pal_and_bestie():
    """The record publishes Member and Member+. These are three tier names
    from nowhere."""
    assessment, reason = classify(
        loyalty_tiers_named=["Snuggle Friend", "Snuggle Pal", "Snuggle Bestie"],
        points=[{"value": "Snuggle Points", "per_dollar": None, "program": "Wiggle & Snug Member Rewards"}],
    )
    assert assessment == c.FABRICATED
    assert "tiers the record does not publish" in reason


def test_run_10833_wiggle_snug_and_cuddle_even_with_a_citation():
    """Cited deals.parleo.io and still invented the tiers. A source
    attached to an invention does not make it grounded — which is why
    fabricated is checked before grounded."""
    assessment, reason = classify(
        loyalty_tiers_named=["Wiggle", "Snug", "Cuddle"],
        sources_cited=["deals.parleo.io"],
    )
    assert assessment == c.FABRICATED
    assert "does not publish" in reason


def test_a_loyalty_claim_that_names_the_real_tiers_is_not_fabricated():
    assessment, _ = classify(
        loyalty_tiers_named=["Member", "Member+"],
        sources_cited=["trueshopstore.com"],
    )
    assert assessment == c.GROUNDED


def test_the_record_is_the_limit_of_what_can_be_called_invented():
    """A retail claim the record cannot speak to, WITH a source, is not
    reported as fabricated. We did not disprove it; saying we did would
    be the same failure the tier exists to catch."""
    assessment, _ = classify(
        brand_claims=[{
            "claim": "sold by independent sellers on Etsy",
            "kind": "retail",
        }],
        sources_cited=["etsy.com"],
    )
    assert assessment == c.ECHOED


# ── grounded ──────────────────────────────────────────────────────────────

def test_run_10830_read_the_record_and_said_so():
    """One of the two runs in 66 that cited trueshopstore.com/loyalty and
    got Member and Member+ right."""
    assessment, reason = classify(
        points=[{"value": "1", "per_dollar": True, "program": "Member Rewards"}],
        member_prices=[{"amount": None, "tier": "member pricing", "attributed_product": "selected products"}],
        loyalty_tiers_named=["Member", "Member+"],
        sources_cited=["trueshopstore.com"],
    )
    assert assessment == c.GROUNDED
    assert "trueshopstore.com" in reason


def test_a_lookalike_domain_is_not_the_brands_domain():
    """Run 10663 cited wiggleandsnug.com and called it 'their official
    website'. The record's domain is trueshopstore.com."""
    assessment, reason = classify(
        brand_claims=[{
            "claim": "their official website (wiggleandsnug.com)",
            "sentence": "Their official website is wiggleandsnug.com.",
            "kind": "assertion", "modality": "asserted", "claim_kind": "ownership",
        }],
        sources_cited=["wiggleandsnug.com"],
    )
    assert assessment == c.FABRICATED
    assert "trueshopstore.com" in reason


# ── echoed, absent, unscoreable ───────────────────────────────────────────

def test_run_10649_named_the_brand_and_answered_generically():
    """'For a 15 lb baby, you should generally buy Size 2 Wiggle & Snug
    Snug-Fit Diapers.' Nothing to check it against — which is precisely
    what the old `exact` was counting."""
    assessment, reason = classify()
    assert assessment == c.ECHOED
    assert "nothing checkable" in reason


def test_run_10820_never_named_the_brand():
    assessment, reason = classify(brand_mentioned=False)
    assert assessment == c.ABSENT
    assert BRAND in reason


def test_an_unreadable_answer_is_ours_not_theirs():
    assessment, _ = classify(
        extraction_confident=False, extraction_note="run status 'error', no answer text",
    )
    assert assessment == c.UNSCOREABLE


def test_absent_is_decided_before_anything_else_about_the_answer():
    """An answer that never named the brand cannot be misattributing it or
    inventing facts about it."""
    assessment, _ = classify(
        brand_mentioned=False,
        other_brands_named=[{"name": "Huggies", "presented_as": "closest match"}],
        brand_claims=[{"claim": "sold at Aldi", "kind": "retail"}],
    )
    assert assessment == c.ABSENT


# ── the whole cycle, reclassified ─────────────────────────────────────────

def test_the_classifier_only_runs_for_the_brand_direct_tier():
    assert c.is_brand_direct("brand_direct", EXPECTATION)
    assert not c.is_brand_direct("catalog_accuracy", {"type": "price"})
    assert not c.is_brand_direct("value_incentives", {"type": "code"})
    # A brand_mention expectation on another tier is not on this axis.
    assert not c.is_brand_direct("category_control", EXPECTATION)


def test_every_classification_is_in_the_shared_vocabulary():
    from soa_shared import expected_answers as ea
    cases = [
        {},
        {"brand_mentioned": False},
        {"extraction_confident": False},
        {"brand_unknown_statement": "cannot find it"},
        {"other_brands_named": [{"name": "Huggies", "presented_as": "closest match"}]},
        {"brand_claims": [{"claim": "sold at Aldi", "kind": "retail"}]},
        {"sources_cited": ["trueshopstore.com"]},
    ]
    for case in cases:
        assessment, _ = classify(**case)
        assert assessment in ea.BRAND_OUTCOMES, (case, assessment)
