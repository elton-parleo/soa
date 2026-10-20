"""
2I-7 §2: the generator keeps the brand out of category-control questions.

FL12 (Pampers, Oct 19) asked 13 category-control questions in its first 25
that named the brand ("What Pampers diaper line should I start with for a
newborn?"): nothing told the stage writer the tier's rule, and nothing
checked it. Now the writer is told, and every question it returns is
checked with soa_shared/unprompted.py, the rule the console's score counts
by: one that names the brand is regenerated once, then dropped and counted.
No model is called: the writer is a stub.
"""
import json
import os
from unittest.mock import patch

import pytest

from clients.truesync_catalog import build_snapshot
from generation import query_generator as qg
from generation import syndicated_study as ss
from soa_shared import unprompted

HERE = os.path.dirname(os.path.abspath(__file__))
STAGES = {"Awareness": 2, "Research": 3}


@pytest.fixture
def snapshot():
    with open(os.path.join(HERE, "fixtures", "wiggle_and_snug_catalog.json")) as fh:
        payloads = json.load(fh)
    return build_snapshot(payloads["catalog"], merchants=payloads["merchants"], incentives=payloads["incentives"])


def _row(text, stage):
    return {"query_text": text, "category": "Baby Care", "stage": stage, "specificity": "Broad",
            "persona": "Value-Conscious Parent", "status": "Active", "study_pattern": "brand_at_retail"}


#: the writer's first answer: three that name the brand, two that do not
FIRST = [
    _row("Best diapers for a newborn", "Awareness"),
    _row("Is Wiggle & Snug good for a newborn?", "Awareness"),
    _row("What diapers stop leaks overnight?", "Research"),
    _row("Are wiggle and snug diapers worth it?", "Research"),
    _row("How do Snug-Fit Diapers run on sizing?", "Research"),     # a product name alone
]


def _build(snapshot, regenerated, *, tiers=None):
    tiers = tiers or {"category_control": {"enabled": True}}
    with patch.object(ss, "generate_and_review_study", return_value=([dict(r) for r in FIRST], {})) as stage_call, \
            patch.object(ss, "generate_general_queries", return_value=(regenerated, {})) as again:
        rows, provenance, config = ss.build_syndicated_study(
            snapshot=snapshot, study_name="W&S", description="Everyday diapers for Wiggle & Snug shoppers.",
            stage_targets=dict(STAGES), allowed_categories=["Baby Care"], study_pattern="brand_at_retail",
            api_key="k", tier_config=tiers, personas=["Value-Conscious Parent"])
    return rows, provenance, config, stage_call, again


def test_three_branded_are_regenerated_once_and_dropped_when_still_branded(snapshot):
    still = [_row("Wiggle & Snug or store brand?", "Awareness"),
             _row("Is Wiggle & Snug sold at Target?", "Research"),
             _row("Is the Snug-Fit Trial Pack worth it?", "Research")]
    rows, provenance, config, stage_call, again = _build(snapshot, still)
    assert [r["query_text"] for r in rows] == ["Best diapers for a newborn", "What diapers stop leaks overnight?"]
    assert {r["tier"] for r in rows} == {"category_control"}
    # regenerated once, for the failed stages, with the rule and the avoid list
    again.assert_called_once()
    kw = again.call_args.kwargs
    assert kw["stage_targets"] == {"Awareness": 1, "Research": 2}
    assert kw["category_control"]["brand"] == "Wiggle & Snug"
    assert set(kw["avoid_texts"]) == {r["query_text"] for r in FIRST}
    control = config["category_control"]
    assert (control["generated"], control["branded_regenerated"], control["replaced"], control["dropped"],
            control["count"]) == (5, 3, 0, 3, 2)
    assert [d["query_text"] for d in control["branded_dropped"]] == [r["query_text"] for r in FIRST
                                                                     if not unprompted.is_unprompted(r, control["checked_against"])]
    assert control["branded_dropped"][2]["names"] == ["Snug-Fit Diapers"]
    assert len(control["replacements_naming_the_brand"]) == 3
    assert control["line"] == "2 questions, none naming the brand (3 dropped for naming it)"
    assert provenance["category_control_check"]["branded_regenerated"] == 3
    assert not any(not unprompted.is_unprompted(r, control["checked_against"]) for r in rows)


def test_an_unbranded_replacement_takes_the_branded_ones_place(snapshot):
    fresh = [_row("Which diapers suit a newborn with eczema?", "Awareness"),
             _row("Best diapers for a heavy wetter", "Research"),
             _row("Is Wiggle & Snug cheaper in bulk?", "Research")]          # still branded: dropped
    rows, _p, config, _s, again = _build(snapshot, fresh)
    assert again.call_count == 1
    assert [r["query_text"] for r in rows] == ["Best diapers for a newborn", "Which diapers suit a newborn with eczema?",
                                               "What diapers stop leaks overnight?", "Best diapers for a heavy wetter"]
    control = config["category_control"]
    assert (control["replaced"], control["dropped"], control["count"]) == (2, 1, 4)
    # the slot dropped is the last branded question of its stage
    assert [d["query_text"] for d in control["branded_dropped"]] == ["How do Snug-Fit Diapers run on sizing?"]
    assert control["line"] == "4 questions, none naming the brand (1 dropped for naming it)"


def test_an_all_unbranded_study_makes_no_second_call(snapshot):
    clean = [dict(r) for r in FIRST if unprompted.is_unprompted(r, unprompted.brand_terms("Wiggle & Snug", (), ["Snug-Fit Diapers"]))]
    with patch.object(ss, "generate_and_review_study", return_value=(clean, {})), \
            patch.object(ss, "generate_general_queries") as again:
        rows, _p, config = ss.build_syndicated_study(
            snapshot=snapshot, study_name="W&S", description="", stage_targets=dict(STAGES),
            allowed_categories=["Baby Care"], study_pattern="brand_at_retail", api_key="k",
            tier_config={"category_control": {"enabled": True}})
    again.assert_not_called()
    assert config["category_control"]["dropped"] == 0 and len(rows) == 2
    assert config["category_control"]["line"] == "2 questions, none naming the brand"


def test_the_stage_writer_is_told_the_rule_only_when_the_tier_is_on(snapshot):
    _r, _p, _c, stage_call, _a = _build(snapshot, [])
    control = stage_call.call_args.kwargs["category_control"]
    assert control["brand"] == "Wiggle & Snug"
    assert "Snug-Fit Diapers" in control["product_names"]
    _r, _p, config, stage_call, again = _build(snapshot, [], tiers={"brand_direct": {"enabled": False}})
    assert "category_control" not in stage_call.call_args.kwargs
    again.assert_not_called()


def test_the_product_names_are_stored_for_the_console(snapshot):
    """tier_config.merchant.product_names is what console_read_models.study_brand_terms reads back."""
    _r, _p, config, _s, _a = _build(snapshot, [], tiers={"category_control": {"enabled": True},
                                                          "catalog_accuracy": {"enabled": True}})
    assert config["merchant"]["product_names"] == [p.title for p in snapshot.products]
    assert config["category_control"]["checked_against"][0] == "Wiggle & Snug"


# ═══ the writer's prompt, before and after ═════════════════════════════════

def _prompt(**kw):
    return qg._build_general_prompt("W&S", "Pampers newborn diapers: lines, sizes, leaks.", {"Awareness": 2},
                                    ["Baby Care"], "brand_at_retail", [], **kw)


def test_the_prompt_states_the_rule_and_reads_the_guidance_as_the_category():
    before, after = _prompt(), _prompt(category_control={"brand": "Pampers", "product_names": ["Swaddlers", "Cruisers 360"]})
    assert "CATEGORY-CONTROL" not in before and "CATEGORY-CONTROL" in after
    assert "No question may name Pampers, in any spelling, or any of its product lines (Swaddlers, Cruisers 360)" in after
    assert "no question may name any other brand" in after
    assert "A retailer may be named only where the naming rule above allows it" in after
    assert ("Study description: Pampers newborn diapers: lines, sizes, leaks.\n\nThe description above is guidance "
            "for the whole study, which is about Pampers. For THESE questions read it as describing the category") in after
    # without the tier the prompt is the one it was
    assert before == _prompt(category_control=None)
    assert "Study description: Pampers newborn diapers: lines, sizes, leaks.\n\nDistribute" in before


# ═══ the predicate against FL12's shape ═══════════════════════════════════

def test_the_predicate_flags_fl12s_13_and_passes_its_37():
    """fixtures/category_control/fl12_shaped_questions.json is FL12-SHAPED, not
    recorded (its _note): the two questions the brief quotes, and 48 written in
    its shape. Replace it with FL12's export to make this a recording."""
    with open(os.path.join(HERE, "fixtures", "category_control", "fl12_shaped_questions.json")) as fh:
        fl12 = json.load(fh)
    terms = unprompted.brand_terms(fl12["brand"], fl12["aliases"], fl12["product_names"])
    flagged = [q for q in fl12["questions"] if not unprompted.is_unprompted(q, terms)]
    passed = [q for q in fl12["questions"] if unprompted.is_unprompted(q, terms)]
    assert (len(flagged), len(passed)) == (13, 37)
    assert all(q["names_the_brand"] for q in flagged) and not any(q["names_the_brand"] for q in passed)
    assert sum(1 for q in fl12["questions"][:25] if q in flagged) == 13
    assert fl12["questions"][0]["query_text"] == "What Pampers diaper line should I start with for a newborn?"
