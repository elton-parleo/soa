"""
The two deterministic checks on a brand-direct question, and the
generator behaviour they produce.

Written against the failure that motivated them. The first real
brand-mode study (C80512) generated twelve brand-direct questions and not
one of them named the brand — because the tier reached the generator
through the UNBRANDED branch of the prompt, which tells the model not to
name a brand at any stage, and the model complied. Every one of those
twelve carried a brand_mention expectation, so every one of them was
unmeetable: an assistant that answered perfectly scored `absent`.

So the tests here are about a property, not a prompt. A prompt can be
edited by anyone at any time; what must survive that is "no question
without the brand reaches the tier", and the only thing that can promise
it is a check that runs on the output.
"""
import json
import os
from unittest.mock import patch

import pytest

from clients.truesync_catalog import build_snapshot
from generation import brand_direct_guard as bdg
from generation import catalog_tiers as ct
from generation.query_generator import (
    _build_general_prompt,
    generate_brand_direct,
    generate_general_queries,
)

BRAND = "Wiggle & Snug"

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "wiggle_and_snug_catalog.json",
)


@pytest.fixture
def snapshot():
    with open(FIXTURE_PATH) as fh:
        payloads = json.load(fh)
    return build_snapshot(
        payloads["catalog"],
        merchants=payloads["merchants"],
        incentives=payloads["incentives"],
    )


# ─── names_brand ──────────────────────────────────────────────────────────

def test_a_question_that_names_the_brand_passes():
    assert bdg.names_brand(
        "Where can I buy Wiggle & Snug Snug-Fit Diapers?", BRAND,
    )


def test_a_question_that_does_not_name_the_brand_fails():
    # Verbatim from the study that prompted this work: a perfectly good
    # shopper question, and a completely unscoreable brand-direct row.
    assert not bdg.names_brand(
        "Which diaper brands are best for sensitive skin?", BRAND,
    )


@pytest.mark.parametrize("text", [
    "Does wiggle and snug make overnight diapers?",
    "Does Wiggle and Snug make overnight diapers?",
    "Does WIGGLE & SNUG make overnight diapers?",
    "Does Wiggle  &  Snug make overnight diapers?",
])
def test_the_brand_is_recognised_however_a_shopper_types_it(text):
    """'&' and 'and' are the same brand typed two ways and a shopper types
    both. Rejecting the second would reject a question that names the
    brand, which is the thing being required."""
    assert bdg.names_brand(text, BRAND)


def test_half_a_brand_name_is_not_the_brand_name():
    """The tolerance above is about typography, not about identity. A
    question naming 'Wiggle' has not named Wiggle & Snug."""
    assert not bdg.names_brand("Are Wiggle diapers any good?", BRAND)


def test_a_brand_name_inside_a_longer_word_does_not_count():
    assert not bdg.names_brand("What is on the wigglesnuggery album?", BRAND)


# ─── intent ───────────────────────────────────────────────────────────────

CATALOG_QUESTION = (
    "What does the Wiggle & Snug Snug-Fit Diapers Size 3 small pack cost?"
)


@pytest.fixture
def catalog_keys():
    return bdg.catalog_intents([CATALOG_QUESTION], BRAND)


def test_a_catalog_price_question_with_the_words_moved_is_a_duplicate(catalog_keys):
    assert bdg.is_intent_duplicate(
        "How much do Wiggle & Snug Snug-Fit Diapers in Size 3 small pack cost?",
        catalog_keys, BRAND,
    )


def test_the_same_price_asked_a_third_way_is_still_a_duplicate(catalog_keys):
    assert bdg.is_intent_duplicate(
        "What is the price of the Size 3 small pack of Wiggle & Snug "
        "Snug-Fit Diapers?",
        catalog_keys, BRAND,
    )


def test_where_to_buy_the_same_variant_is_not_a_duplicate(catalog_keys):
    """The whole point of the tier. Same product, same variant, same
    words — different question, and one with no published number behind
    it."""
    assert not bdg.is_intent_duplicate(
        "Where can I buy Wiggle & Snug Snug-Fit Diapers in Size 3 small pack?",
        catalog_keys, BRAND,
    )


def test_a_suitability_question_is_not_a_duplicate(catalog_keys):
    assert not bdg.is_intent_duplicate(
        "Are Wiggle & Snug Snug-Fit Diapers Size 3 gentle enough for "
        "sensitive skin?",
        catalog_keys, BRAND,
    )


def test_a_price_question_about_a_different_product_is_not_a_duplicate(catalog_keys):
    assert not bdg.is_intent_duplicate(
        "What does Wiggle & Snug Bum Balm cost?", catalog_keys, BRAND,
    )


def test_a_catalog_question_with_no_recognisable_ask_is_not_a_template():
    """Otherwise every brand-direct question would be compared against a
    bag of product words with no ask to disagree with, and the first one
    naming the same product would be rejected."""
    assert bdg.catalog_intents(["Wiggle & Snug Snug-Fit Diapers"], BRAND) == []


# ─── the prompt ───────────────────────────────────────────────────────────

def _brand_prompt(**kwargs):
    return _build_general_prompt(
        "Wiggle & Snug — visibility", "Everyday diapers.",
        {"Research": 5, "Ready to Buy": 7}, ["Baby Care"],
        "brand_at_retail", [], brand_direct=BRAND, **kwargs,
    )


def test_the_brand_direct_prompt_requires_the_brand_by_name():
    prompt = _brand_prompt()
    assert "must name the brand Wiggle & Snug" in prompt
    assert "will be discarded" in prompt


def test_the_brand_direct_prompt_does_not_carry_the_unbranded_instruction():
    """The exact sentence that caused the defect. If it reappears here,
    the tier is back to asking for questions it cannot score."""
    prompt = _brand_prompt()
    assert "UNBRANDED study" not in prompt
    assert "Do not name specific retailers or brands" not in prompt


def test_the_brand_direct_prompt_asks_for_shopper_intents_not_prices():
    prompt = _brand_prompt()
    for intent in ("where to buy", "sensitive skin", "subscription"):
        assert intent in prompt
    assert "Do NOT ask what anything costs" in prompt


def test_an_unbranded_study_is_unchanged_by_the_new_branch():
    prompt = _build_general_prompt(
        "Beauty", "A study", {"Research": 3}, ["Skincare"], "retailer", [],
    )
    assert "UNBRANDED study" in prompt


# ─── the generator ────────────────────────────────────────────────────────

def _row(text, stage="Research"):
    return {
        "query_text": text,
        "category": "Baby Care",
        "stage": stage,
        "specificity": "Mid",
        "persona": "Value-Conscious Parent",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": None,
        "soa_focus": "Mention Rate",
        "rationale": "test",
    }


def _generate(batches, **kwargs):
    with patch("generation.query_generator._call_openai_and_validate") as call:
        # Every call after the scripted ones returns nothing, so a test
        # that expects rejection cannot accidentally be rescued by a
        # mock that keeps handing back the same good row forever.
        call.side_effect = [(b, None) for b in batches] + [([], None)] * 10
        rows, report = generate_general_queries(
            study_name="Wiggle & Snug — visibility",
            description="Everyday diapers.",
            stage_targets={"Research": 2},
            allowed_categories=["Baby Care"],
            study_pattern="brand_at_retail",
            api_key="k",
            **kwargs,
        )
    return rows, report


def test_a_generated_question_without_the_brand_is_rejected():
    rows, report = _generate(
        [[
            _row("Which diaper brands are best for sensitive skin?"),
            _row("Does Wiggle & Snug make overnight diapers?"),
        ]],
        require_brand=BRAND,
    )
    texts = [row["query_text"] for row in rows]
    assert texts == ["Does Wiggle & Snug make overnight diapers?"]
    assert len(report["brand_missing_drops"]) == 1
    assert report["brand_missing_drops"][0]["query_text"] == (
        "Which diaper brands are best for sensitive skin?"
    )


def test_the_rejected_slot_is_asked_for_again():
    rows, _report = _generate(
        [
            [_row("Which diaper brands are best for sensitive skin?"),
             _row("Does Wiggle & Snug make overnight diapers?")],
            [_row("Where can I buy Wiggle & Snug diapers?")],
        ],
        require_brand=BRAND,
    )
    assert len(rows) == 2
    assert all(bdg.names_brand(row["query_text"], BRAND) for row in rows)


def test_a_tier_that_cannot_fill_itself_reports_short_rather_than_admitting_it():
    """The load-bearing one. Given a model that will not name the brand,
    the tier must come back small — never padded with questions whose
    expectation they cannot meet."""
    rows, report = _generate(
        [[_row("Which diaper brands are best for sensitive skin?")]] * 6,
        require_brand=BRAND,
    )
    assert rows == []
    assert report["shortfall_by_stage"] == {"Research": 2}


def test_a_near_duplicate_of_a_catalog_question_is_rejected():
    rows, report = _generate(
        [[
            _row("How much do Wiggle & Snug Snug-Fit Diapers in Size 3 "
                 "small pack cost?"),
            _row("Where can I buy Wiggle & Snug Snug-Fit Diapers?"),
        ]],
        require_brand=BRAND,
        catalog_texts=[CATALOG_QUESTION],
    )
    texts = [row["query_text"] for row in rows]
    assert texts == ["Where can I buy Wiggle & Snug Snug-Fit Diapers?"]
    assert len(report["intent_duplicate_drops"]) == 1


def test_the_catalog_questions_are_put_in_front_of_the_model_too():
    """Checking afterwards is the guarantee; telling the model is what
    stops it costing a replacement round every time."""
    with patch("generation.query_generator._call_openai_and_validate") as call:
        call.side_effect = lambda *a, **kw: (
            [_row("Where can I buy Wiggle & Snug diapers?")], None,
        )
        generate_general_queries(
            study_name="S", description="d",
            stage_targets={"Research": 1}, allowed_categories=["Baby Care"],
            study_pattern="brand_at_retail", api_key="k",
            require_brand=BRAND, catalog_texts=[CATALOG_QUESTION],
        )
    prompt = call.call_args_list[0][0][0]
    assert CATALOG_QUESTION in prompt


def test_an_ordinary_study_is_untouched_by_either_check():
    rows, report = _generate([[
        _row("Which diaper brands are best for sensitive skin?"),
        _row("What is a good overnight diaper?"),
    ]])
    assert len(rows) == 2
    assert report["brand_missing_drops"] == []
    assert report["intent_duplicate_drops"] == []


# ─── the tier ─────────────────────────────────────────────────────────────

def test_the_tier_never_contains_a_question_without_the_brand(snapshot):
    """The property, asserted end-to-end on the real catalog fixture
    against a model that returns a mix of both kinds."""
    mixed = [
        _row("Which diaper brands are best for sensitive skin?"),
        _row("Does Wiggle & Snug make overnight diapers?"),
        _row("What is the gentlest diaper for newborns?"),
        _row("Where can I buy Wiggle & Snug Bum Balm?", "Ready to Buy"),
        _row("Is there a diaper subscription worth having?", "Ready to Buy"),
        _row("Does Wiggle & Snug offer a subscription?", "Ready to Buy"),
    ]
    with patch("generation.query_generator._call_openai_and_validate") as call:
        # A callable, not a finite list: the point of the test is that the
        # tier stays clean however many times it has to ask, so the mock
        # must not be the thing that ends the loop.
        call.side_effect = lambda *a, **kw: (list(mixed), None)
        rows, report = generate_brand_direct(
            snapshot,
            study_name="Wiggle & Snug — visibility",
            description="Everyday diapers.",
            stage_targets={"Research": 12, "Ready to Buy": 16},
            allowed_categories=["Baby Care"],
            study_pattern="brand_at_retail",
            api_key="k",
            count=6,
        )

    assert rows
    for row in rows:
        assert bdg.names_brand(row["query_text"], BRAND), row["query_text"]
    assert report["brand_missing_drops"]


def test_the_tier_reports_its_own_shortfall(snapshot):
    with patch("generation.query_generator._call_openai_and_validate") as call:
        call.side_effect = lambda *a, **kw: (
            [_row("Which diaper brands are best for sensitive skin?")], None,
        )
        rows, report = generate_brand_direct(
            snapshot,
            study_name="S", description="d",
            stage_targets={"Research": 12, "Ready to Buy": 16},
            allowed_categories=["Baby Care"],
            study_pattern="brand_at_retail",
            api_key="k", count=6,
        )
    assert rows == []
    assert report["shortfall"] == 6
    assert report["requested"] == 6


def test_the_real_catalog_questions_are_what_brand_direct_dedupes_against(snapshot):
    """Not a hand-written fixture: the actual text build_catalog_accuracy
    produces, so a change to the price template cannot silently stop the
    dedupe from matching anything."""
    catalog_rows, _ = ct.build_catalog_accuracy(
        snapshot, category="Baby Care", persona="Value-Conscious Parent",
        study_pattern="brand_at_retail",
    )
    texts = [row["query_text"] for row in catalog_rows]
    keys = bdg.catalog_intents(texts, BRAND)
    assert keys, "the catalog tier's own price questions must read as price asks"

    restated = texts[0].replace("What does the", "How much does the").replace(
        "cost?", "sell for?",
    )
    assert bdg.is_intent_duplicate(restated, keys, BRAND)
