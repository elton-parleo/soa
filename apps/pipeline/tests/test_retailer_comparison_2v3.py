"""
2V-3 Q8: a retailer-pattern study saves the comparison rows its preview promised.

Petco's study (a seller, the retailer pattern, Petco and Chewy named, rotation
on, category control on) previewed "Comparison: 12 questions, each naming the
brand and a rival" and saved none. The study's brand is the store, and its
rivals were filtered with "a store is not a brand to choose against", so Chewy
never reached the writer, the writer was told "never a retailer", and every
rival brand it named is a line Petco stocks (one of the store's own terms).
keep_comparisons then dropped every row. A retailer-pattern study now compares
the store with the other stores it names. No model is called: the writer is a stub.
"""
from unittest.mock import patch

from generation import query_generator as qg
from generation import syndicated_study as ss
from soa_shared import unprompted
from tests.test_subject_size_2v3 import _petco

STAGES = {"Awareness": 2, "Comparison": 4}


def _row(text, stage, rival=None):
    row = {"query_text": text, "category": "Pet Supplies", "stage": stage, "specificity": "Broad",
           "persona": "Value-Conscious Pet Owner", "status": "Active", "study_pattern": "retailer"}
    if rival:
        row["rival"] = rival
    return row


WRITTEN = [
    _row("Best dry food for a senior dog", "Awareness"),
    _row("Which cat litter controls odor best?", "Awareness"),
    _row("Petco or Chewy for dog food?", "Comparison", "Chewy"),
    _row("Is Chewy cheaper than Petco for cat litter?", "Comparison", "Chewy"),
    _row("Should I buy dental treats at Petco or Chewy?", "Comparison", "Chewy"),
    _row("Chewy vs Petco for flea and tick chews", "Comparison", "Chewy"),
]


def _build(regenerated=(), *, pattern="retailer", retailers=("Petco", "Chewy"), rivals=()):
    with patch.object(ss, "generate_and_review_study", return_value=([dict(r) for r in WRITTEN], {})) as call, \
            patch.object(ss, "generate_general_queries", return_value=(list(regenerated), {})) as again:
        rows, _prov, config = ss.build_syndicated_study(
            snapshot=_petco(), study_name="Petco", description="Pet supplies at Petco.",
            stage_targets=dict(STAGES), allowed_categories=["Pet Supplies"], study_pattern=pattern,
            api_key="k", tier_config={"category_control": {"enabled": True}, "brand_direct": {"enabled": False}},
            personas=["Value-Conscious Pet Owner"], retailer_names=list(retailers), rivals=list(rivals))
    return rows, config, call, again


def test_a_retailer_study_saves_every_comparison_row_naming_both_stores():
    rows, config, call, again = _build()
    assert call.call_args.kwargs["comparison"] == {"brand": "Petco", "rivals": ["Chewy"], "kind": "retailer"}
    compared = [r["query_text"] for r in rows if r["tier"] == "comparison"]
    assert compared == [r["query_text"] for r in WRITTEN if r["stage"] == "Comparison"]
    # the count the preview showed (the Comparison stage target) is the count saved
    assert len(compared) == STAGES["Comparison"] == config["comparison"]["count"]
    assert config["comparison"]["dropped"] == 0 and not again.called
    assert config["comparison"]["line"] == "4 questions, each naming the brand and a rival"
    for text in compared:
        assert unprompted.names_any(text, ["Petco"]) and unprompted.names_any(text, ["Chewy"]), text
    # rotated: neither store leads every question
    firsts = {"Petco" if t.index("Petco") < t.index("Chewy") else "Chewy" for t in compared}
    assert firsts == {"Petco", "Chewy"}


def test_the_merchant_competitors_join_the_named_stores_once():
    _rows, config, call, _again = _build(rivals=["Chewy", "PetSmart"])
    assert call.call_args.kwargs["comparison"]["rivals"] == ["Chewy", "PetSmart"]


def test_a_brand_study_still_drops_a_store_as_its_rival():
    # brand_at_retail is unchanged: a store is not a brand to choose against
    _rows, config, call, _again = _build(pattern="brand_at_retail")
    assert "kind" not in call.call_args.kwargs["comparison"]
    assert config["comparison"]["count"] == 0


def test_the_writer_is_told_to_compare_stores_and_the_rivals_rotate():
    prompt = qg._build_general_prompt(
        "Petco", "Pet supplies.", {"Comparison": 4}, ["Pet Supplies"], "retailer", [],
        retailer_names=["Petco", "Chewy"],
        comparison={"brand": "Petco", "rivals": ["Chewy", "PetSmart"], "kind": "retailer"})
    assert "AND at least one rival store" in prompt
    assert "Chewy, PetSmart" in prompt and "Alternate which store is named first" in prompt
    assert "never a retailer" not in prompt

    seen = []
    real = qg._build_general_prompt

    def spy(*a, **kw):
        seen.append(list(kw["comparison"]["rivals"]))
        return real(*a, **kw)

    with patch.object(qg, "_build_general_prompt", side_effect=spy), \
            patch.object(qg, "_call_openai_and_validate", return_value=([], [])):
        try:
            qg.generate_general_queries(
                study_name="Petco", description="d", stage_targets={"Comparison": 2},
                allowed_categories=["Pet Supplies"], study_pattern="retailer", api_key="k",
                retailer_names=["Petco", "Chewy"],
                comparison={"brand": "Petco", "rivals": ["Chewy", "PetSmart"], "kind": "retailer"})
        except Exception:  # noqa: BLE001 - an empty writer is a shortfall; only the prompts matter here
            pass
    assert seen[:2] == [["Chewy", "PetSmart"], ["PetSmart", "Chewy"]]
