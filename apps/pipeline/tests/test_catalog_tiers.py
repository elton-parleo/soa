"""
The catalog-built tiers, against the real Wiggle & Snug catalog.

tests/fixtures/wiggle_and_snug_catalog.json is generated from the live
canonical records (listings 90-94 on api.parleo.io) projected through the
same transformation the supply app's Part B endpoints apply — real data
in the real response shape, not a hand-typed approximation. Its shape:
5 products, 19 variants, 6 GTINs, two codes (WELCOME10 and SNUG3), and a
Member Rewards programme with two tiers.

The literal question strings asserted here are the frozen wording. Their
twin lives in apps/api/web/src/components/__tests__/catalogTiers.test.js,
asserting the same strings from the same fixture, so the modal's examples
and the generator's output cannot drift apart silently.
"""
import copy
import json
import os

import pytest

from clients.truesync_catalog import build_snapshot
from generation import catalog_tiers as ct
from soa_shared import expected_answers as ea

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "wiggle_and_snug_catalog.json",
)

CATEGORY = "Baby Care"
PERSONA = "Value-Conscious Parent"
# study_pattern is a property of the study, never of a question, and is
# NOT NULL on soa_queries — so the builders take it as a required keyword
# rather than letting a caller omit it and fail at the INSERT.
STUDY_PATTERN = "brand_at_retail"


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
        price_history=payloads["price_history"],
    )


def _accuracy(snapshot, **kwargs):
    return ct.build_catalog_accuracy(
        snapshot, category=CATEGORY, persona=PERSONA,
        study_pattern=STUDY_PATTERN, **kwargs,
    )


def _value(snapshot):
    return ct.build_value_incentives(
        snapshot, category=CATEGORY, persona=PERSONA, study_pattern=STUDY_PATTERN,
    )


# ── the fixture is the catalog the mock describes ─────────────────────────

def test_the_catalog_read_back_matches_what_the_modal_claims(snapshot):
    """5 products, 19 variants, 6 GTINs, 2 live codes, Member Rewards
    (2 tiers) — the line the modal renders, computed from the record."""
    assert snapshot.product_count == 5
    assert snapshot.variant_count == 19
    assert snapshot.gtin_count == 6
    assert snapshot.code_count == 2
    assert snapshot.program_name == "Member Rewards"
    assert [t["name"] for t in snapshot.tiers] == ["Member", "Member+"]
    assert snapshot.brand == "Wiggle & Snug"
    assert snapshot.domain == "trueshopstore.com"


# ── catalog accuracy: counts and templates ────────────────────────────────

def test_one_price_question_per_variant(snapshot):
    rows, report = _accuracy(snapshot)
    prices = [r for r in rows if r["expected_answer"]["type"] == "price"]
    assert len(prices) == 19
    assert len(report["sampled_variants"]) == 19
    assert report["sampled"] is False


def test_the_price_template_is_frozen(snapshot):
    rows, _ = _accuracy(snapshot)
    texts = {r["query_text"] for r in rows}
    assert (
        "What does the Wiggle & Snug Snug-Fit Diapers Size 3 small pack (84 ct) cost?"
        in texts
    )


def test_a_single_variant_product_is_asked_about_by_name_alone(snapshot):
    """A variant display exists to distinguish variants; with one variant
    there is nothing to distinguish, and appending its size reads like a
    machine talking."""
    rows, _ = _accuracy(snapshot)
    texts = {r["query_text"] for r in rows}
    assert "What does the Wiggle & Snug Cloud Wipes 3-Pack cost?" in texts
    assert "What does the Wiggle & Snug Bum Balm 4 oz cost?" in texts


def test_the_price_expectation_is_the_published_price_to_the_cent(snapshot):
    rows, _ = _accuracy(snapshot)
    row = next(
        r for r in rows
        if r["query_text"].endswith("Size 3 small pack (84 ct) cost?")
    )
    assert row["expected_answer"]["type"] == "price"
    assert row["expected_answer"]["amount"] == "22.99"
    assert row["expected_answer"]["currency"] == "USD"


def test_gtin_rides_along_as_a_secondary_and_is_never_asked(snapshot):
    rows, _ = _accuracy(snapshot)

    with_gtin = [
        r for r in rows
        if any(s["type"] == "gtin" for s in r["expected_answer"].get("secondary") or [])
    ]
    # Six variants carry a GTIN; six price questions carry it as secondary.
    assert len(with_gtin) == 6
    assert all(r["expected_answer"]["type"] == "price" for r in with_gtin)

    # And not one question asks for it.
    assert not any("GTIN" in r["query_text"].upper() for r in rows)
    assert not any(r["expected_answer"]["type"] == "gtin" for r in rows)


def test_the_gtin_secondary_is_the_published_gtin(snapshot):
    rows, _ = _accuracy(snapshot)
    row = next(
        r for r in rows
        if r["query_text"].endswith("Size 3 small pack (84 ct) cost?")
    )
    assert {"type": "gtin", "value": "884400137609"} in (
        row["expected_answer"]["secondary"]
    )


# ── catalog accuracy: pack count is a secondary, not a question ───────────

def test_one_question_per_variant_and_no_pack_count_question(snapshot):
    """Two questions per variant put the default Wiggle & Snug study at
    103 against the study's own 100 cap, and a feature whose defaults
    open on a red tally has the wrong defaults."""
    rows, report = _accuracy(snapshot)

    assert len(rows) == 19
    assert report["count"] == 19
    assert {r["expected_answer"]["type"] for r in rows} == {"price"}
    assert not any(r["query_text"].startswith("How many come in") for r in rows)


def test_the_pack_count_rides_on_the_price_question(snapshot):
    rows, _ = _accuracy(snapshot)
    row = next(
        r for r in rows
        if r["query_text"].endswith("Size 3 small pack (84 ct) cost?")
    )
    assert {"type": "pack_count", "value": 84} in row["expected_answer"]["secondary"]


def test_both_secondaries_ride_on_one_question_where_the_record_has_both(snapshot):
    rows, _ = _accuracy(snapshot)
    row = next(r for r in rows if "Cloud Wipes" in r["query_text"])
    assert row["expected_answer"]["secondary"] == [
        {"type": "gtin", "value": "884400676641"},
        {"type": "pack_count", "value": 216},
    ]


def test_a_single_unit_variant_carries_no_pack_count_secondary(snapshot):
    """Bum Balm is one 4 oz jar. "How many come in it" is not a question
    about anything."""
    rows, _ = _accuracy(snapshot)
    row = next(r for r in rows if "Bum Balm" in r["query_text"])
    assert not any(
        item["type"] == "pack_count"
        for item in row["expected_answer"].get("secondary") or []
    )


def test_the_report_separates_a_restated_count_from_a_volunteered_one(snapshot):
    """
    The price question names a multi-variant variant BY its count, so an
    assistant restating 84 is echoing the question rather than knowing
    it. Recorded as two populations so the report can say which is which
    — a rate that mixes them is not measuring knowledge.
    """
    _rows, report = _accuracy(snapshot)
    secondary = report["secondary"]

    assert secondary["gtin"] == 6
    assert secondary["pack_count"] == 18
    # Only the two single-variant products with a real count state no
    # count in their subject.
    assert sorted(secondary["pack_count_volunteered"]) == [
        "cloud-wipes-3pack", "snug-fit-trial-pack",
    ]
    assert len(secondary["pack_count_restated"]) == 16


# ── catalog accuracy: provenance and source_ref ───────────────────────────

def test_every_catalog_row_is_provenance_catalog_and_asked_at_ready_to_buy(snapshot):
    rows, _ = _accuracy(snapshot)
    assert {r["provenance"] for r in rows} == {"catalog"}
    assert {r["tier"] for r in rows} == {"catalog_accuracy"}
    assert {r["stage"] for r in rows} == {"Ready to Buy"}


def test_source_ref_carries_the_record_published_at_not_now(snapshot):
    rows, _ = _accuracy(snapshot)
    row = next(
        r for r in rows
        if r["query_text"].endswith("Size 3 small pack (84 ct) cost?")
    )
    ref = row["source_ref"]
    assert ref["merchant_slug"] == "wiggle-and-snug"
    assert ref["listing_id"] == 90
    assert ref["variant_id"] == "snug-fit-diapers-s3-small"
    # The record's publication timestamp — what a later comparison says
    # the claim was made against.
    assert ref["published_at"] == "2026-09-04T20:49:40.991623+00:00"


# ── catalog accuracy: the sampling rule at 40 variants ────────────────────

def _forty_variant_payload(payloads):
    """
    A catalog with 40 variants across 4 products, priced 1.00 .. 40.00 so
    a sample's spread is checkable by inspection.
    """
    listings = []
    for product_index in range(4):
        listings.append({
            "listing_id": 500 + product_index,
            "product_id": f"catalog_product:{500 + product_index}",
            "title": f"Product {product_index}",
            "brand": "Wiggle & Snug",
            "published_at": "2026-09-01T00:00:00+00:00",
            "variants": [
                {
                    "variant_id": f"p{product_index}-v{variant_index}",
                    "title": f"Product {product_index} variant {variant_index}",
                    "size": f"Size {variant_index}",
                    "count": 10 + variant_index,
                    "attributes": {},
                    "list_price": f"{product_index * 10 + variant_index + 1}.00",
                    "currency": "USD",
                    "gtin": None,
                }
                for variant_index in range(10)
            ],
        })
    return {"merchant": "wiggle-and-snug", "listings": listings}


@pytest.fixture
def forty(payloads):
    return build_snapshot(
        _forty_variant_payload(payloads), merchants=payloads["merchants"],
    )


def test_forty_variants_are_capped_at_twenty(forty):
    assert forty.variant_count == 40
    _rows, report = _accuracy(forty)
    assert len(report["sampled_variants"]) == 20
    assert report["sampled"] is True
    assert report["variants_available"] == 40
    assert report["variant_cap"] == 20


def test_the_sample_covers_every_product_at_least_once(forty):
    _rows, report = _accuracy(forty)
    products = {vid.split("-")[0] for vid in report["sampled_variants"]}
    assert products == {"p0", "p1", "p2", "p3"}


def test_the_sample_spreads_across_price_points_not_just_the_cheapest(forty):
    """Taking the first N of a price sort would only ever ask about the
    bottom of the range, which cannot tell you whether the assistant knows
    the dear one."""
    _rows, report = _accuracy(forty)
    sampled = set(report["sampled_variants"])

    for product_index in range(4):
        prices = sorted(
            product_index * 10 + variant_index + 1
            for variant_index in range(10)
            if f"p{product_index}-v{variant_index}" in sampled
        )
        assert prices, f"product {product_index} unsampled"
        # Both ends of this product's range are in the sample.
        assert min(prices) == product_index * 10 + 1
        assert max(prices) == product_index * 10 + 10


def test_the_sample_is_recorded_so_a_rerun_can_be_compared_to_it(forty):
    _rows, report = _accuracy(forty)
    assert set(report["sampled_variants"]) <= {
        f"p{p}-v{v}" for p in range(4) for v in range(10)
    }
    assert len(report["sampled_variants"]) == len(set(report["sampled_variants"]))


def test_a_smaller_cap_is_honoured(forty):
    _rows, report = _accuracy(forty, cap=6)
    assert len(report["sampled_variants"]) == 6
    # Still one from each product first — coverage before depth.
    assert {vid.split("-")[0] for vid in report["sampled_variants"]} == {
        "p0", "p1", "p2", "p3",
    }


# ── value & incentives ────────────────────────────────────────────────────

def test_one_question_per_mechanic_the_record_has(snapshot):
    _rows, report = _value(snapshot)
    assert report["mechanics"] == {"code": 2, "member_price": 3, "points": 1}
    assert report["mechanics_absent"] == []


def test_the_two_codes_get_two_questions_a_shopper_would_type_differently(snapshot):
    rows, _ = _value(snapshot)
    codes = [r for r in rows if r["expected_answer"]["type"] == "code"]
    texts = {r["query_text"] for r in codes}

    assert texts == {
        "Is there a first-order promo code for Wiggle & Snug, and what does it take off?",
        "Are there any promo codes for Wiggle & Snug Snug-Fit Diapers right now, "
        "and what do they take off?",
    }
    assert {r["expected_answer"]["code"] for r in codes} == {"WELCOME10", "SNUG3"}


def test_the_code_expectation_carries_the_value_not_just_the_code(snapshot):
    """A right code with a wrong discount is wrong, not partly right: an
    answer that sends a shopper to checkout expecting the wrong saving has
    failed in the way that costs the merchant."""
    rows, _ = _value(snapshot)
    snug3 = next(
        r for r in rows
        if r["expected_answer"].get("code") == "SNUG3"
    )
    assert snug3["expected_answer"] == {
        "type": "code", "code": "SNUG3",
        "value_kind": "amount_off", "value": "3.00",
    }


def test_the_member_price_template_is_frozen_and_names_the_tier(snapshot):
    rows, _ = _value(snapshot)
    member = [r for r in rows if r["expected_answer"]["type"] == "member_price"]
    assert (
        "What do Member+ members pay for the Wiggle & Snug Cloud Wipes 3-Pack?"
        in {r["query_text"] for r in member}
    )
    assert all(r["expected_answer"]["tier_name"] == "Member+" for r in member)


def test_a_member_price_naming_no_tier_is_not_asked_about(snapshot):
    """Bum Balm's record states an outright member_price with no
    tier_name. A member price that names no tier names no entitlement, so
    there is no claim to score — and inventing a tier to make one
    scoreable would be inventing the answer."""
    rows, _ = _value(snapshot)
    assert not any("Bum Balm" in r["query_text"] for r in rows)


def test_the_points_question_is_asked_once_not_once_per_variant(snapshot):
    """A brand that earns one point per dollar earns it on everything;
    asked nineteen times it is one fact measured nineteen ways."""
    rows, _ = _value(snapshot)
    points = [r for r in rows if r["expected_answer"]["type"] == "points"]
    assert len(points) == 1
    assert points[0]["query_text"] == (
        "How many Member Rewards points do you earn per dollar on "
        "Wiggle & Snug products?"
    )
    assert points[0]["expected_answer"]["rule"]["kind"] == "per_dollar"
    assert points[0]["expected_answer"]["rule"]["rate"] == "1.00"


def test_every_value_row_is_provenance_catalog(snapshot):
    rows, _ = _value(snapshot)
    assert {r["provenance"] for r in rows} == {"catalog"}
    assert {r["tier"] for r in rows} == {"value_incentives"}
    assert {r["stage"] for r in rows} == {"Ready to Buy"}


# ── value & incentives: a brand that lacks a mechanic ─────────────────────

def _without(payloads, *, codes=False, member_prices=False, points=False):
    incentives = copy.deepcopy(payloads["incentives"])
    for listing in incentives["listings"]:
        if codes:
            for incentive in listing["incentives"]:
                incentive["promo_code"] = None
        for variant in listing["variants"]:
            if member_prices:
                variant["entitled_member_price"] = None
                variant["entitled_tier_name"] = None
            if points:
                variant["points"] = []
    return incentives


def test_a_brand_with_no_promo_code_is_asked_no_code_question(payloads):
    snapshot = build_snapshot(
        payloads["catalog"],
        merchants=payloads["merchants"],
        incentives=_without(payloads, codes=True),
    )
    rows, report = _value(snapshot)
    assert report["mechanics"]["code"] == 0
    assert "code" in report["mechanics_absent"]
    assert not any(r["expected_answer"]["type"] == "code" for r in rows)


def test_a_brand_with_no_member_price_is_asked_no_member_price_question(payloads):
    snapshot = build_snapshot(
        payloads["catalog"],
        merchants=payloads["merchants"],
        incentives=_without(payloads, member_prices=True),
    )
    rows, report = _value(snapshot)
    assert report["mechanics"]["member_price"] == 0
    assert not any(r["expected_answer"]["type"] == "member_price" for r in rows)


def test_a_brand_with_no_points_programme_is_asked_no_points_question(payloads):
    snapshot = build_snapshot(
        payloads["catalog"],
        merchants=payloads["merchants"],
        incentives=_without(payloads, points=True),
    )
    rows, report = _value(snapshot)
    assert report["mechanics"]["points"] == 0
    assert not any(r["expected_answer"]["type"] == "points" for r in rows)


def test_no_subscribe_and_save_question_for_a_brand_without_one(snapshot):
    """
    The tier asks about exactly three mechanics — code, member price and
    points — and never manufactures a question for one the record does not
    carry. Wiggle & Snug's records carry a single subscribe_and_save offer
    with no stated value, and no subscribe-and-save question is produced.

    A tier that asked a brand about a mechanic it does not run would not
    measure the assistant; it would measure the brand's product mix, and
    it would render as an assistant failure on the report.
    """
    rows, report = _value(snapshot)
    assert set(report["mechanics"]) == {"code", "member_price", "points"}
    lowered = " ".join(r["query_text"].lower() for r in rows)
    assert "subscribe" not in lowered
    assert "subscription" not in lowered


def test_an_empty_incentives_payload_builds_nothing_rather_than_guessing(payloads):
    snapshot = build_snapshot(payloads["catalog"], merchants=payloads["merchants"])
    rows, report = _value(snapshot)
    assert rows == []
    assert report["mechanics_absent"] == ["code", "member_price", "points"]


# ── every row a builder emits is scoreable ────────────────────────────────

def test_every_emitted_expectation_validates(snapshot):
    """A question carrying an unscoreable expectation is worse than one
    carrying none: it is counted in a denominator it can never contribute
    to. The builders call validate() on the way out; this is the check
    that they cannot stop."""
    rows = _accuracy(snapshot)[0] + _value(snapshot)[0]
    assert rows
    for row in rows:
        assert ea.validate(row["expected_answer"]) is row["expected_answer"]


def test_a_variant_with_an_unparseable_price_is_recorded_not_silently_dropped(payloads):
    catalog = copy.deepcopy(payloads["catalog"])
    catalog["listings"][2]["variants"][0]["list_price"] = "call for pricing"
    snapshot = build_snapshot(catalog, merchants=payloads["merchants"])

    rows, report = _accuracy(snapshot)
    assert report["skipped_no_price"] == ["cloud-wipes-3pack"]
    assert not any("Cloud Wipes" in r["query_text"] for r in rows)


# ── expected nulls ────────────────────────────────────────────────────────

def test_expected_nulls_are_written_before_the_run_not_explained_after(snapshot):
    control = ct.expected_nulls(snapshot, "category_control")
    assert "Near zero" in control
    assert "Wiggle & Snug" in control

    accuracy = ct.expected_nulls(snapshot, "catalog_accuracy")
    assert "feed enrollment" in accuracy


def test_expected_nulls_name_the_mechanics_a_brand_actually_lacks(payloads):
    snapshot = build_snapshot(
        payloads["catalog"],
        merchants=payloads["merchants"],
        incentives=_without(payloads, codes=True, member_prices=True),
    )
    note = ct.expected_nulls(snapshot, "value_incentives")
    assert "no promo code" in note
    assert "no member price" in note


def test_every_row_carries_the_studys_pattern(snapshot):
    """NOT NULL on soa_queries, and a property of the study rather than
    of a question — so the builders require it rather than letting a
    caller omit it and discover the omission at the INSERT."""
    rows = _accuracy(snapshot)[0] + _value(snapshot)[0]
    assert {r["study_pattern"] for r in rows} == {STUDY_PATTERN}
