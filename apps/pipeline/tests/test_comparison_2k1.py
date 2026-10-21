"""
2K-1 §1 (E29): the comparison tier, generator side.

With category control on, the study's Comparison-stage questions are the
comparison tier: the brand and a rival, asking which to choose. 2I-7 made
category control mean "names no brand", so FL12's "Pampers vs Huggies for
newborns" was tagged category control and is now regenerated away. The
writer is told the comparison rule for that stage; every question it returns
for the stage is checked with soa_shared/unprompted.is_comparison; one naming
no rival is regenerated once, then dropped and counted. No model is called:
the writer is a stub.
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
STAGES = {"Awareness": 2, "Comparison": 4}
RIVALS = ["Pampers", "Huggies"]


@pytest.fixture
def snapshot():
    with open(os.path.join(HERE, "fixtures", "wiggle_and_snug_catalog.json")) as fh:
        payloads = json.load(fh)
    return build_snapshot(payloads["catalog"], merchants=payloads["merchants"], incentives=payloads["incentives"])


def _row(text, stage, rival=None):
    row = {"query_text": text, "category": "Baby Care", "stage": stage, "specificity": "Broad",
           "persona": "Value-Conscious Parent", "status": "Active", "study_pattern": "brand_at_retail"}
    if rival:
        row["rival"] = rival
    return row


#: the writer's first answer: two category-control questions, four comparison-stage ones
FIRST = [
    _row("Best diapers for a newborn", "Awareness"),
    _row("What diapers stop leaks overnight?", "Awareness"),
    _row("Wiggle & Snug vs Pampers for a newborn", "Comparison", "Pampers"),
    _row("Wiggle & Snug or Huggies for overnight leaks?", "Comparison", "Huggies"),
    _row("Wiggle & Snug vs Coterie for sensitive skin", "Comparison", "Coterie"),    # a rival the writer named
    _row("Is Wiggle & Snug cheaper at Target or Walmart?", "Comparison", "Target"),  # a store is not a rival
]


def _build(snapshot, regenerated, *, tiers=None, stages=None, rivals=RIVALS):
    tiers = tiers or {"category_control": {"enabled": True}}
    with patch.object(ss, "generate_and_review_study", return_value=([dict(r) for r in FIRST], {})) as stage_call, \
            patch.object(ss, "generate_general_queries", return_value=(regenerated, {})) as again:
        rows, provenance, config = ss.build_syndicated_study(
            snapshot=snapshot, study_name="W&S", description="Everyday diapers for Wiggle & Snug shoppers.",
            stage_targets=dict(stages or STAGES), allowed_categories=["Baby Care"], study_pattern="brand_at_retail",
            api_key="k", tier_config=tiers, personas=["Value-Conscious Parent"], rivals=rivals)
    return rows, provenance, config, stage_call, again


def test_comparison_questions_are_stored_with_the_tier_and_one_naming_no_rival_is_dropped(snapshot):
    still = [_row("Is Wiggle & Snug cheaper at Costco?", "Comparison", "Costco")]
    rows, provenance, config, stage_call, again = _build(snapshot, still)
    # the stage writer was told the comparison rule, with the listed rivals
    assert stage_call.call_args.kwargs["comparison"] == {"brand": "Wiggle & Snug", "rivals": RIVALS}
    by_tier = {}
    for r in rows:
        by_tier.setdefault(r["tier"], []).append(r["query_text"])
    assert by_tier == {
        "category_control": ["Best diapers for a newborn", "What diapers stop leaks overnight?"],
        "comparison": ["Wiggle & Snug vs Pampers for a newborn", "Wiggle & Snug or Huggies for overnight leaks?",
                       "Wiggle & Snug vs Coterie for sensitive skin"]}
    assert all("rival" not in r for r in rows)          # the declared rival is not a column
    # each stored comparison names the brand and a rival
    for text_ in by_tier["comparison"]:
        assert unprompted.names_any(text_, ["Wiggle & Snug"])
        assert unprompted.names_any(text_, ["Pampers", "Huggies", "Coterie"])
    # regenerated once, for the one failure, with the rule; the replacement named a store: dropped
    again.assert_called_once()
    kw = again.call_args.kwargs
    assert kw["stage_targets"] == {"Comparison": 1} and kw["comparison"]["brand"] == "Wiggle & Snug"
    comparison = config["comparison"]
    assert (comparison["generated"], comparison["regenerated"], comparison["replaced"], comparison["dropped"],
            comparison["count"]) == (4, 1, 0, 1, 3)
    assert comparison["dropped"] == 1 and comparison["line"] == \
        "3 questions, each naming the brand and a rival (1 dropped for naming no rival)"
    assert [d["query_text"] for d in config["comparison"]["found"]] == ["Is Wiggle & Snug cheaper at Target or Walmart?"]
    assert [tuple(x) for x in config["comparison"]["rivals_named"]] == [("Coterie", 1), ("Huggies", 1), ("Pampers", 1)]
    # category control counts its own questions, not the comparison tier's
    assert (config["category_control"]["count"], config["category_control"]["line"]) == \
        (2, "2 questions, none naming the brand")


def test_a_replacement_that_names_a_rival_takes_the_failed_question_s_place(snapshot):
    fixed = [_row("Wiggle & Snug vs Huggies at Target: which to buy?", "Comparison", "Huggies")]
    rows, _p, config, _s, _a = _build(snapshot, fixed)
    assert [r["query_text"] for r in rows if r["tier"] == "comparison"][-1] == fixed[0]["query_text"]
    assert (config["comparison"]["replaced"], config["comparison"]["dropped"], config["comparison"]["count"]) == (1, 0, 4)


def test_no_listed_rival_the_writer_s_declared_one_is_accepted_when_it_is_a_brand(snapshot):
    rows, _p, config, stage_call, _a = _build(snapshot, [], rivals=[])
    assert stage_call.call_args.kwargs["comparison"]["rivals"] == []
    assert [r["query_text"] for r in rows if r["tier"] == "comparison"] == [
        "Wiggle & Snug vs Pampers for a newborn", "Wiggle & Snug or Huggies for overnight leaks?",
        "Wiggle & Snug vs Coterie for sensitive skin"]


def test_without_a_comparison_stage_or_the_control_tier_the_call_is_2i7_s(snapshot):
    _rows, _p, config, stage_call, _a = _build(snapshot, [], stages={"Awareness": 2})
    assert "comparison" not in stage_call.call_args.kwargs and "comparison" not in config
    _rows, _p, config, stage_call, _a = _build(snapshot, [], tiers={"brand_direct": {"enabled": False}})
    assert "comparison" not in stage_call.call_args.kwargs and "category_control" not in stage_call.call_args.kwargs
    assert "comparison" not in config


def test_the_prompt_states_the_rule_for_the_comparison_stage_only_when_asked():
    base = dict(study_name="S", description="d", allowed_categories=["Baby Care"], study_pattern="brand_at_retail",
                already_generated=[], category_control={"brand": "Pampers", "product_names": []})
    plain = qg._build_general_prompt(stage_counts={"Awareness": 2, "Comparison": 2}, **base)
    assert "COMPARISON questions" not in plain and "rival" not in plain
    asked = qg._build_general_prompt(stage_counts={"Awareness": 2, "Comparison": 2},
                                     comparison={"brand": "Pampers", "rivals": ["Huggies", "Luvs"]}, **base)
    assert "COMPARISON questions" in asked and "Huggies, Luvs" in asked and "rival (Comparison stage only)" in asked
    # no Comparison stage in this call: nothing to say
    assert qg._build_general_prompt(stage_counts={"Awareness": 2}, comparison={"brand": "Pampers", "rivals": []},
                                    **base) == qg._build_general_prompt(stage_counts={"Awareness": 2}, **base)


def test_a_declared_rival_survives_validation_and_a_row_without_one_is_unchanged():
    row = _row("Pampers vs Huggies", "Comparison", "Huggies")
    cleaned, errors = qg._validate_generated_row({**row, "subscription_state": None})
    assert cleaned["rival"] == "Huggies"
    cleaned, _ = qg._validate_generated_row({**_row("Best diapers", "Awareness"), "subscription_state": None})
    assert "rival" not in cleaned


# ═══ the predicates on FL12's shape ═══════════════════════════════════════

with open(os.path.join(HERE, "fixtures", "comparison", "fl12_shaped_comparison_questions.json")) as _fh:
    FL12_COMPARISON = json.load(_fh)
with open(os.path.join(HERE, "fixtures", "category_control", "fl12_shaped_questions.json")) as _fh:
    FL12_CONTROL = json.load(_fh)


def test_the_12_pampers_vs_questions_are_comparisons_and_brand_choice_and_not_unprompted():
    brand, rivals = [FL12_COMPARISON["brand"]], FL12_COMPARISON["rivals"]
    qs = FL12_COMPARISON["questions"]
    assert len(qs) == 12
    assert all(unprompted.is_comparison(q, brand, rivals) for q in qs)
    tagged = [{**q, "tier": "comparison"} for q in qs]
    assert not any(unprompted.is_unprompted(q, brand) for q in tagged)
    assert all(unprompted.is_brand_choice(q, brand) for q in tagged)


def test_none_of_fl12_s_50_category_control_questions_is_a_comparison():
    """'Pampers or store brand diapers for daycare?' names the brand and no
    rival brand; 'Should I switch from Pampers to a cloth diaper?' neither."""
    brand, rivals = [FL12_CONTROL["brand"]], FL12_COMPARISON["rivals"]
    qs = FL12_CONTROL["questions"]
    assert not any(unprompted.is_comparison(q, brand, rivals) for q in qs)
    # brand choice: the 37 unbranded, as unprompted; the 13 branded control questions are neither
    assert sum(unprompted.is_brand_choice(q, brand) for q in qs) == 37


@pytest.mark.parametrize("text, expected", [
    ("Pampers Swaddlers vs Pampers Baby-Dry", False),     # two lines of the brand: no rival
    ("Huggies vs Luvs for a newborn", False),             # no brand
    ("pampers VS huggies", True),                         # case-insensitive
    ("Pampers vs Huggiesish", False),                     # whole words
])
def test_is_comparison_edges(text, expected):
    assert unprompted.is_comparison(text, ["Pampers", "Pampers Baby-Dry"], ["Huggies", "Luvs", "Pampers Baby-Dry"]) is expected


# ═══ the worker: the merchant's competitors by name ═══════════════════════

def test_merchant_rivals_reads_supply_s_list_and_names_each_by_its_entity():
    import worker
    from soa_pg_harness import sqlite_engine
    from soa_shared.models.soa_models import SoaEntity
    from sqlalchemy import text

    engine = sqlite_engine()
    SoaEntity.__table__.create(engine)
    with engine.begin() as c:
        for i, (name, url, aliases) in enumerate([("Huggies", "https://www.huggies.com/", '["huggies.com"]'),
                                                  ("luvs.com", "https://luvs.com/", '["luvs.com"]')], start=1):
            c.execute(text("INSERT INTO soa_entities (id, name, slug, entity_type, website_url, aliases) "
                           "VALUES (:i, :n, :s, 'brand', :u, :a)"), {"i": i, "n": name, "s": f"e{i}", "u": url, "a": aliases})

    class Supply:
        def __init__(self, payload, error=None):
            self.payload, self.error = payload, error

        def retailers(self, slug):
            return self.payload, self.error

    with patch.object(worker, "engine", engine):
        # a named entity is named; a domain-named one (no name entered yet) and an unknown domain are left out
        assert worker.merchant_rivals(Supply({"comparison_domains": ["huggies.com", "luvs.com", "coterie.com"]}),
                                      "pampers") == ["Huggies"]
        assert worker.merchant_rivals(Supply(None, "502"), "pampers") == []
