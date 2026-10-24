"""
2O-1 (H29): category-control questions ask for a product.

On FL14, 7 of the 20 AI-written category questions drew no brand from any
agent on any surface ("How do parents decide between disposable diapers and
other baby care options?"). The demo's ask for a product ("what's the safest
diaper for a newborn", "best diapers for sensitive skin"). The writer is now
told so (both the first call and the regeneration read the same prompt), and
every question it returns is checked with syndicated_study.asks_for_product;
one that asks for none is regenerated (bounded), then dropped and counted.
No model is called: the writer is a stub. Existing studies are untouched.
"""
import json
import os
from unittest.mock import patch

import pytest

from clients.truesync_catalog import build_snapshot
from generation import query_generator as qg
from generation import syndicated_study as ss

HERE = os.path.dirname(os.path.abspath(__file__))
FL14 = json.load(open(os.path.join(HERE, 'fixtures', 'category_control', 'fl14_category_questions.json')))
STAGES = {"Awareness": 2, "Research": 3}


@pytest.fixture
def snapshot():
    with open(os.path.join(HERE, "fixtures", "wiggle_and_snug_catalog.json")) as fh:
        payloads = json.load(fh)
    return build_snapshot(payloads["catalog"], merchants=payloads["merchants"], incentives=payloads["incentives"])


def _row(text, stage):
    return {"query_text": text, "category": "Baby Care", "stage": stage, "specificity": "Broad",
            "persona": "Value-Conscious Parent", "status": "Active", "study_pattern": "brand_at_retail"}


# ── the check ─────────────────────────────────────────────────────────────

def test_fl14s_seven_fail_the_check():
    assert [q for q in FL14['drew_no_brand'] if ss.asks_for_product(q)] == []
    assert len(FL14['drew_no_brand']) == 7


def test_the_demos_questions_pass():
    assert all(ss.asks_for_product(q) for q in FL14['demo'])


@pytest.mark.parametrize('q', [
    "Which diapers hold up overnight for a heavy wetter?",
    "Best diapers for a crawling baby?",
    "Can you recommend a diaper for a newborn with eczema?",
    "What diapers should I buy for a 9 lb baby?",
    "Should I get a hypoallergenic diaper for sensitive skin?",
    "What diaper is good for a long car ride?",
    "What's the cheapest overnight diaper that doesn't leak?",
])
def test_a_question_that_asks_for_a_product_passes(q):
    assert ss.asks_for_product(q)


@pytest.mark.parametrize('q', [
    # "what diaper(s)" before a noun is not a product ask: FL14's fifth
    "What diaper features matter most for comfort, dryness, and rash prevention?",
    # "buy" without "should I": FL14's third
    "What baby care products do new parents usually buy first for diapering?",
    # "most" is not "-est": FL14's sixth
    "What are the most important factors when choosing baby diapers for sensitive skin?",
    "What should I compare when choosing diapers?",
])
def test_the_near_misses_fail(q):
    assert not ss.asks_for_product(q)


# ── the prompt, both calls ────────────────────────────────────────────────

def _prompt(**kw):
    return qg._build_general_prompt("Pampers", "Pampers newborn diapers.", {"Awareness": 2, "Comparison": 1},
                                    ["Baby Care"], "brand_at_retail", [], **kw)


def test_the_prompt_states_the_rule_only_for_the_category_tier():
    before = _prompt()
    after = _prompt(category_control={"brand": "Pampers", "product_names": ["Swaddlers"]})
    rule = "Every one of these questions asks which product or brand to buy for a need the shopper states"
    assert rule not in before and rule in after
    assert '"what\'s the safest diaper for a newborn", "best diapers for sensitive skin"' in after
    assert "Never ask how parents decide, what factors matter, what to compare" in after
    # the comparison tier is its own: it names the brand and a rival, and asks which to choose
    compared = _prompt(category_control={"brand": "Pampers", "product_names": []},
                       comparison={"brand": "Pampers", "rivals": ["Huggies"]})
    assert "neither the no-brand rule nor the product-ask rule above applies to them" in compared


def test_the_regeneration_reads_the_same_prompt(snapshot):
    """The second stage: regenerate() calls generate_general_queries with the
    rule (category_control), so its prompt states it too."""
    first = [_row("Best diapers for a newborn", "Awareness"),
             _row("How do parents decide between disposable diapers and other baby care options?", "Awareness"),
             _row("Which diapers stop leaks overnight?", "Research")]
    with patch.object(ss, "generate_and_review_study", return_value=(first, {})), \
            patch.object(ss, "generate_general_queries", return_value=([], {})) as again:
        ss.build_syndicated_study(
            snapshot=snapshot, study_name="W&S", description="", stage_targets=dict(STAGES),
            allowed_categories=["Baby Care"], study_pattern="brand_at_retail", api_key="k",
            tier_config={"category_control": {"enabled": True}})
    assert again.call_args.kwargs["category_control"]["brand"] == "Wiggle & Snug"
    assert again.call_args.kwargs["stage_targets"] == {"Awareness": 1}


# ── keep_product_asks: regenerate, bounded, then drop ─────────────────────

FIRST = [_row("Best diapers for a newborn", "Awareness"),
         _row(FL14['drew_no_brand'][0], "Awareness"),
         _row("Which diapers stop leaks overnight?", "Research"),
         _row(FL14['drew_no_brand'][1], "Research"),
         _row(FL14['drew_no_brand'][4], "Research")]


def _build(snapshot, *rounds):
    calls = list(rounds)
    with patch.object(ss, "generate_and_review_study", return_value=([dict(r) for r in FIRST], {})), \
            patch.object(ss, "generate_general_queries",
                         side_effect=lambda **kw: (calls.pop(0) if calls else [], {})) as again:
        rows, provenance, config = ss.build_syndicated_study(
            snapshot=snapshot, study_name="W&S", description="", stage_targets=dict(STAGES),
            allowed_categories=["Baby Care"], study_pattern="brand_at_retail", api_key="k",
            tier_config={"category_control": {"enabled": True}})
    return rows, provenance, config, again


def test_a_question_that_asks_for_no_product_is_regenerated_and_replaced(snapshot):
    fresh = [_row("Which diapers suit a newborn with eczema?", "Awareness"),
             _row("Best diapers for a heavy wetter", "Research"),
             _row("Recommend a diaper for a long nap", "Research")]
    rows, provenance, config, again = _build(snapshot, fresh)
    assert again.call_count == 1
    assert again.call_args.kwargs["stage_targets"] == {"Awareness": 1, "Research": 2}
    assert [r["query_text"] for r in rows] == ["Best diapers for a newborn", "Which diapers suit a newborn with eczema?",
                                               "Which diapers stop leaks overnight?", "Best diapers for a heavy wetter",
                                               "Recommend a diaper for a long nap"]
    control = config["category_control"]
    assert len(control["not_a_product_ask_found"]) == 3
    assert (control["product_ask_rounds"], control["product_ask_replaced"], control["count"]) == (1, 3, 5)
    assert control["not_a_product_ask_dropped"] == []
    assert control["line"] == "5 questions, none naming the brand"
    assert provenance["category_control_check"]["product_ask_replaced"] == 3


def test_regeneration_is_bounded_and_what_still_fails_is_dropped_and_counted(snapshot):
    still = [_row("How often do parents change diapers at night?", "Awareness"),
             _row("Is Wiggle & Snug good for a newborn?", "Research"),      # names the brand: no replacement
             _row(FL14['drew_no_brand'][5], "Research")]
    rows, _p, config, again = _build(snapshot, still, still, still)
    assert again.call_count == ss.PRODUCT_ASK_ROUNDS == 2
    assert [r["query_text"] for r in rows] == ["Best diapers for a newborn", "Which diapers stop leaks overnight?"]
    control = config["category_control"]
    assert [d["query_text"] for d in control["not_a_product_ask_dropped"]] == [
        FL14['drew_no_brand'][0], FL14['drew_no_brand'][1], FL14['drew_no_brand'][4]]
    assert control["count"] == 2
    assert control["line"] == "2 questions, none naming the brand, 3 dropped for asking for no product"


def test_a_study_that_already_asks_for_products_makes_no_second_call(snapshot):
    clean = [_row("Best diapers for a newborn", "Awareness"), _row("Which diapers stop leaks overnight?", "Research")]
    with patch.object(ss, "generate_and_review_study", return_value=(clean, {})), \
            patch.object(ss, "generate_general_queries") as again:
        _rows, _p, config = ss.build_syndicated_study(
            snapshot=snapshot, study_name="W&S", description="", stage_targets=dict(STAGES),
            allowed_categories=["Baby Care"], study_pattern="brand_at_retail", api_key="k",
            tier_config={"category_control": {"enabled": True}})
    again.assert_not_called()
    assert config["category_control"]["product_ask_rounds"] == 0
