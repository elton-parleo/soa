"""
Composing a study from the four tiers.

The two properties that matter most here are both about what does NOT
happen: with no brand chosen, the generation call is the one this code
made before the tiers existed, with the same arguments; and with the
control tier on, no new question is generated at all — it is a tag.
"""
import json
import os
from unittest.mock import patch

import pytest

from clients.truesync_catalog import build_snapshot, CatalogSnapshot
from generation import syndicated_study as ss

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "wiggle_and_snug_catalog.json",
)

STAGE_TARGETS = {
    "Awareness": 10, "Research": 12, "Comparison": 12, "Ready to Buy": 16,
}


@pytest.fixture
def payloads():
    with open(FIXTURE_PATH) as fh:
        return json.load(fh)


@pytest.fixture
def snapshot(payloads):
    return build_snapshot(
        payloads["catalog"],
        merchants=payloads["merchants"],
        incentives=payloads["incentives"],
    )


def _stage_rows(n=50):
    """What generate_and_review_study returns, in the shape it returns it."""
    return [
        {
            "query_text": f"stage question {i}",
            "category": "Baby Care",
            "stage": "Awareness",
            "specificity": "Broad",
            "persona": "Value-Conscious Parent",
            "status": "Active",
            "study_pattern": "brand_at_retail",
            "soa_focus": "Mention Rate",
            "rationale": "because",
        }
        for i in range(n)
    ]


def _brand_rows(n=12):
    return [
        {
            "query_text": f"brand question {i}",
            "category": "Baby Care",
            "stage": "Research",
            "specificity": "Mid",
            "persona": "Value-Conscious Parent",
            "status": "Active",
            "study_pattern": "brand_at_retail",
        }
        for i in range(n)
    ]


_UNSET = object()


def _build(
    snapshot, tier_config, *,
    stage_rows=None, brand_rows=None, personas=_UNSET, **kwargs,
):
    stage_rows = _stage_rows() if stage_rows is None else stage_rows
    brand_rows = _brand_rows() if brand_rows is None else brand_rows
    # _UNSET rather than a default of ["Value-Conscious Parent"], so a
    # test can ask for personas=None — the case the whole persona
    # fallback exists for — without it reading as "not specified".
    personas = ["Value-Conscious Parent"] if personas is _UNSET else personas

    with patch.object(
        ss, "generate_and_review_study",
        return_value=(stage_rows, {"requested_by_stage": dict(STAGE_TARGETS)}),
    ) as stage_call, patch.object(
        ss, "generate_brand_direct",
        return_value=(brand_rows, {"requested": len(brand_rows)}),
    ) as brand_call:
        result = ss.build_syndicated_study(
            snapshot=snapshot,
            study_name="Wiggle & Snug — visibility after syndication",
            description="Everyday diapers.",
            stage_targets=dict(STAGE_TARGETS),
            allowed_categories=["Baby Care"],
            study_pattern="brand_at_retail",
            api_key="k",
            tier_config=tier_config,
            personas=personas,
            **kwargs,
        )
    return result + (stage_call, brand_call)


ALL_ON = {
    "brand_direct": {"enabled": True, "count": 12},
    "catalog_accuracy": {"enabled": True},
    "value_incentives": {"enabled": True},
    "category_control": {"enabled": False},
}


# ── the untoggled study is today's study ──────────────────────────────────

def test_no_brand_reaches_the_existing_generator_with_the_existing_arguments():
    """
    The guarantee for every existing user. Not "close to today's
    behaviour" — the same call, with the same arguments, and no tier
    machinery in the path at all.
    """
    rows, provenance, config, stage_call, brand_call = _build(None, None)

    stage_call.assert_called_once()
    kwargs = stage_call.call_args.kwargs
    assert kwargs["stage_targets"] == STAGE_TARGETS
    assert kwargs["study_pattern"] == "brand_at_retail"
    assert kwargs["allowed_categories"] == ["Baby Care"]
    assert "catalog_context" not in kwargs
    assert "snapshot" not in kwargs

    brand_call.assert_not_called()
    assert len(rows) == 50


def test_no_brand_leaves_every_row_ungrounded():
    """NULL on all four columns is the untouched state — the same state
    every query written before the tiers existed is in."""
    rows, _prov, _config, _s, _b = _build(None, None)
    for row in rows:
        assert row.get("tier") is None
        assert row.get("expected_answer") is None
        assert row.get("provenance") is None
        assert row.get("source_ref") is None


def test_no_brand_records_no_tiers_as_enabled():
    _rows, _prov, config, _s, _b = _build(None, None)
    assert all(not config[tier]["enabled"] for tier in ss.TIERS)


def test_an_absent_tier_is_disabled_rather_than_defaulted_on():
    """A study that quietly acquired a tier nobody asked for would put
    questions in a report nobody can account for."""
    config = ss.normalize_tier_config({"catalog_accuracy": {"enabled": True}})
    assert config["catalog_accuracy"]["enabled"] is True
    assert config["brand_direct"]["enabled"] is False
    assert config["value_incentives"]["enabled"] is False
    assert config["category_control"]["enabled"] is False


# ── category control tags, it does not generate ───────────────────────────

def test_category_control_tags_the_stage_questions_and_adds_none(snapshot):
    rows, _prov, config, stage_call, _b = _build(
        snapshot,
        {"category_control": {"enabled": True}},
    )
    assert stage_call.call_count == 1
    assert len(rows) == 50
    assert {r["tier"] for r in rows} == {"category_control"}
    assert config["category_control"]["count"] == 50


def test_a_control_question_carries_no_expectation(snapshot):
    """Deliberately unscoreable by Layer 2. There is no published number a
    right answer to 'best diapers for a newborn' must contain, and this
    brand is not expected to win them — that is what makes them a floor."""
    rows, _prov, _config, _s, _b = _build(
        snapshot, {"category_control": {"enabled": True}},
    )
    assert all(r.get("expected_answer") is None for r in rows)
    assert {r["provenance"] for r in rows} == {"ai"}


# ── the additive tiers ────────────────────────────────────────────────────

def test_brand_direct_is_additive_and_stamped(snapshot):
    rows, _prov, config, _s, brand_call = _build(
        snapshot, {"brand_direct": {"enabled": True, "count": 12}},
    )
    assert len(rows) == 62
    brand_call.assert_called_once()
    assert config["brand_direct"]["count"] == 12


def test_the_catalog_tiers_are_additive(snapshot):
    rows, _prov, config, _s, _b = _build(snapshot, ALL_ON)

    # 50 stage + 12 brand-direct + 19 accuracy (one price question per
    # variant, pack count riding as a secondary) + 6 value.
    assert config["catalog_accuracy"]["count"] == 19
    assert config["value_incentives"]["count"] == 6
    assert len(rows) == 50 + 12 + 19 + 6


def test_the_default_study_lands_inside_the_hundred_question_cap(snapshot):
    """The reason pack count stopped being its own question. A feature
    whose defaults open on a red tally has the wrong defaults."""
    from generation.syndicated_study import tally

    _rows, _prov, config, _s, _b = _build(snapshot, ALL_ON)
    config["category_control"]["stage_total"] = 50

    assert tally(config)["total"] == 87
    assert tally(config)["total"] < 100


def test_the_resolved_config_records_which_variants_were_sampled(snapshot):
    _rows, _prov, config, _s, _b = _build(snapshot, ALL_ON)
    sampled = config["catalog_accuracy"]["sampled_variants"]
    assert len(sampled) == 19
    assert "snug-fit-diapers-s3-small" in sampled


def test_the_resolved_config_records_the_catalog_it_read(snapshot):
    """The modal's read-back line, frozen at generation time: what the
    catalog said when these expectations were written."""
    _rows, _prov, config, _s, _b = _build(snapshot, ALL_ON)
    merchant = config["merchant"]
    assert merchant["brand"] == "Wiggle & Snug"
    assert merchant["domain"] == "trueshopstore.com"
    assert (merchant["products"], merchant["variants"]) == (5, 19)
    assert (merchant["gtins"], merchant["codes"]) == (6, 2)
    assert merchant["tiers"] == ["Member", "Member+"]


def test_provenance_keeps_its_existing_shape_and_gains_a_tiers_section(snapshot):
    """Nothing that read the provenance record before reads differently."""
    _rows, provenance, _config, _s, _b = _build(snapshot, ALL_ON)
    assert provenance["requested_by_stage"] == STAGE_TARGETS
    assert set(provenance["tiers"]) >= set(ss.TIERS)


# ── expected nulls, written before the run ────────────────────────────────

def test_every_enabled_tier_carries_an_expected_nulls_note(snapshot):
    _rows, _prov, config, _s, _b = _build(
        snapshot, {**ALL_ON, "category_control": {"enabled": True}},
    )
    for tier in ss.TIERS:
        assert config[tier]["expected_nulls"], tier
    assert "Near zero" in config["category_control"]["expected_nulls"]


# ── the catalog being unreachable ─────────────────────────────────────────

def test_an_unreachable_catalog_still_produces_the_ungrounded_study():
    """Failing a job holding fifty good questions because a third-party
    endpoint was down for thirty seconds is the worse outcome."""
    down = CatalogSnapshot(available=False, error="504 from TrueSync")
    rows, _prov, config, stage_call, brand_call = _build(down, ALL_ON)

    stage_call.assert_called_once()
    brand_call.assert_not_called()
    assert len(rows) == 50
    assert all(r.get("tier") is None for r in rows)


def test_an_unreachable_catalog_is_recorded_not_silent():
    """A tier asked for and not built is a fact the report has to state,
    or a missing rate reads as a zero rate."""
    down = CatalogSnapshot(available=False, error="504 from TrueSync")
    _rows, _prov, config, _s, _b = _build(down, ALL_ON)

    for tier in ("brand_direct", "catalog_accuracy", "value_incentives"):
        assert config[tier]["unavailable"] == "504 from TrueSync"
        assert config[tier]["count"] == 0


# ── the tally ─────────────────────────────────────────────────────────────

def test_the_tally_splits_by_who_wrote_the_question(snapshot):
    """'{stage total} AI-written + {catalog count} from the catalog'.
    Brand-direct is a model writing with a catalog open, so it is
    AI-written; the two template tiers are from the catalog."""
    _rows, _prov, config, _s, _b = _build(snapshot, ALL_ON)
    config["category_control"]["stage_total"] = 50

    assert ss.tally(config) == {
        "ai_written": 62,       # 50 stage + 12 brand-direct
        "from_catalog": 25,     # 19 accuracy + 6 value
        "total": 87,
    }


def test_the_control_tier_adds_nothing_to_the_tally(snapshot):
    """It is a tag on questions already counted in the stage total."""
    _rows, _prov, config, _s, _b = _build(
        snapshot, {"category_control": {"enabled": True}},
    )
    config["category_control"]["stage_total"] = 50

    assert ss.tally(config) == {
        "ai_written": 50, "from_catalog": 0, "total": 50,
    }


def test_a_disabled_tier_contributes_nothing_even_with_a_count_on_it():
    config = ss.normalize_tier_config({
        "brand_direct": {"enabled": False, "count": 12},
        "catalog_accuracy": {"enabled": False, "count": 35},
        "category_control": {"enabled": False, "stage_total": 50},
    })
    config["category_control"]["stage_total"] = 50
    assert ss.tally(config) == {
        "ai_written": 50, "from_catalog": 0, "total": 50,
    }


# ── the persona stamped on catalog-built rows ─────────────────────────────
#
# soa_queries.persona is NOT NULL and CHECKed against QUERY_PERSONAS, so
# a builder always has to write something. What it used to write, with no
# personas in the brief, was the literal 'Value-Conscious' — a real enum
# value from the beauty verticals, and the wrong one for a Baby Care
# study. The first real brand-mode study came out with model-written
# questions labelled 'Value-Conscious Parent' and catalog-built questions
# labelled 'Value-Conscious': one study, two populations, and every report
# that segments by persona showing half of each.

def test_the_brief_is_what_decides_the_persona_when_it_names_one():
    assert ss._primary_persona(["Sensitive-Skin Baby Parent"]) == (
        "Sensitive-Skin Baby Parent"
    )


def test_a_persona_outside_the_enum_is_ignored_rather_than_written():
    """It would fail the CHECK constraint on insert, taking the whole
    study with it — and a study is worth more than a label."""
    assert ss._primary_persona(
        ["Diaper Enthusiast"], [{"persona": "Value-Conscious Parent"}],
    ) == "Value-Conscious Parent"


def test_with_no_brief_the_study_s_own_questions_decide():
    rows = (
        [{"persona": "Value-Conscious Parent"}] * 30
        + [{"persona": "New / First-Time Parent"}] * 20
    )
    assert ss._primary_persona(None, rows) == "Value-Conscious Parent"


def test_the_persona_is_never_a_value_the_enum_does_not_contain():
    from soa_shared.constants import QUERY_PERSONAS
    for personas, rows in (
        (None, None),
        ([], []),
        (["nonsense"], [{"persona": "nonsense"}]),
    ):
        assert ss._primary_persona(personas, rows) in QUERY_PERSONAS


def test_catalog_rows_carry_the_same_persona_as_the_study_s_own_questions(snapshot):
    """The end-to-end form of the defect: with no personas in the brief,
    every row in the study — model-written and template-built — has to
    land on one persona."""
    rows, _prov, _config, _stage, _brand = _build(
        snapshot, ALL_ON, personas=None,
    )
    assert {row["persona"] for row in rows} == {"Value-Conscious Parent"}


def test_a_named_persona_still_wins_over_the_study_s_questions(snapshot):
    rows, _prov, _config, _stage, _brand = _build(
        snapshot, ALL_ON, personas=["Eco-Conscious Parent"],
    )
    catalog = [r for r in rows if r.get("tier") in
               ("catalog_accuracy", "value_incentives")]
    assert catalog
    assert {r["persona"] for r in catalog} == {"Eco-Conscious Parent"}


# ── brand-direct sees the catalog tiers ───────────────────────────────────

def test_brand_direct_is_handed_the_catalog_questions_to_avoid(snapshot):
    rows, _prov, _config, _stage, brand_call = _build(snapshot, ALL_ON)
    texts = brand_call.call_args.kwargs["catalog_texts"]
    assert texts, "brand-direct must know what the catalog tiers are asking"

    catalog = [r["query_text"] for r in rows if r.get("tier") in
               ("catalog_accuracy", "value_incentives")]
    assert sorted(texts) == sorted(catalog)


def test_the_question_order_is_unchanged_by_building_the_catalog_first(snapshot):
    """Catalog tiers are built before brand-direct now, so brand-direct
    can see them — but the study still reads stage, then brand-direct,
    then catalog."""
    rows, _prov, _config, _stage, _brand = _build(snapshot, ALL_ON)
    # generate_brand_direct is mocked here, so its rows never reach
    # stamp_brand_direct and carry no tier — their text is what
    # identifies them.
    kinds = [
        row.get("tier") or (
            "brand_direct" if row["query_text"].startswith("brand question")
            else "stage"
        )
        for row in rows
    ]
    first_brand = kinds.index("brand_direct")
    first_catalog = min(
        kinds.index(t) for t in ("catalog_accuracy", "value_incentives")
        if t in kinds
    )
    assert first_brand < first_catalog
    assert all(k == "stage" for k in kinds[:first_brand])
