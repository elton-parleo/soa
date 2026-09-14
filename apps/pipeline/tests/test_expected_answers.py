"""
The typed expected-answer vocabulary — soa_shared/expected_answers.py.

The executable half of docs/expected-answer-vocabulary.md. Where this
suite and that document disagree, one of them is a bug; there is no third
source of truth.
"""
import pytest

from soa_shared import expected_answers as ea


# ── money is a string, never a float ──────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("22.99", "22.99"),
    ("$22.99", "22.99"),
    ("22.99 USD", "22.99"),
    ("  22.99  ", "22.99"),
    ("1,234.50", "1234.50"),
    ("18.9", "18.90"),          # two places always
    ("18.90", "18.90"),
    (22.99, "22.99"),
    (0, "0.00"),
])
def test_normalize_money_accepts_what_records_and_models_emit(raw, expected):
    assert ea.normalize_money(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "  ", "free", "$", True, "n/a"])
def test_normalize_money_returns_none_rather_than_raising(raw):
    """An unparseable amount from a model is an `unscoreable` outcome,
    not a crash."""
    assert ea.normalize_money(raw) is None


def test_two_spellings_of_one_price_are_one_price():
    assert ea.normalize_money("18.9") == ea.normalize_money("$18.90")


def test_money_never_round_trips_through_a_float():
    """0.1 + 0.2 is the canonical demonstration. If normalisation went
    via float, a published '0.30' and a stated '0.30' could differ."""
    assert ea.normalize_money("0.30") == "0.30"
    assert ea.price("0.30")["amount"] == "0.30"


# ── the constructors reject what cannot be scored ─────────────────────────

def test_price_carries_amount_and_currency():
    assert ea.price("22.99", "usd") == {
        "type": "price", "amount": "22.99", "currency": "USD",
    }


def test_price_rejects_a_non_number():
    with pytest.raises(ea.ExpectedAnswerError):
        ea.price("about twenty-three dollars")


def test_gtin_strips_separators_but_keeps_leading_zeros():
    assert ea.gtin("0884-400 137609")["value"] == "0884400137609"


def test_gtin_rejects_something_with_no_digits():
    with pytest.raises(ea.ExpectedAnswerError):
        ea.gtin("no barcode")


def test_pack_count_is_an_integer():
    assert ea.pack_count("84 ct")["value"] == 84
    assert ea.pack_count(84)["value"] == 84


def test_code_normalises_case_and_keeps_its_value():
    assert ea.code("snug3", "amount_off", "3") == {
        "type": "code", "code": "SNUG3", "value_kind": "amount_off", "value": "3.00",
    }


def test_code_rejects_an_unknown_value_kind():
    with pytest.raises(ea.ExpectedAnswerError):
        ea.code("SNUG3", "some_off", "3.00")


def test_code_rejects_a_value_it_cannot_compare():
    """A right code with an unknown discount cannot be scored — and an
    answer that sends a shopper to checkout expecting the wrong saving is
    exactly the failure this tier exists to catch."""
    with pytest.raises(ea.ExpectedAnswerError):
        ea.code("SNUG3", "amount_off", "a few dollars")


def test_member_price_requires_a_tier():
    """A member price with no tier names no entitlement, and is not a
    claim about anything."""
    with pytest.raises(ea.ExpectedAnswerError):
        ea.member_price("16.84", None)


def test_member_price_keeps_the_tier_verbatim_for_display():
    built = ea.member_price("16.84", "Member+")
    assert built["tier_name"] == "Member+"
    assert built["amount"] == "16.84"


def test_points_per_dollar_carries_a_rate():
    built = ea.points("per_dollar", rate="1.0", program_name="Member Rewards")
    assert built["rule"] == {
        "kind": "per_dollar", "rate": "1.00", "program_name": "Member Rewards",
    }


def test_points_fixed_carries_a_total():
    assert ea.points("fixed", total=16)["rule"]["points"] == 16


def test_points_rejects_an_unknown_kind():
    with pytest.raises(ea.ExpectedAnswerError):
        ea.points("vibes", rate="1.0")


def test_brand_mention_lowercases_the_domain():
    assert ea.brand_mention("Wiggle & Snug", "TrueShopStore.com") == {
        "type": "brand_mention",
        "brand": "Wiggle & Snug",
        "domain": "trueshopstore.com",
    }


# ── validation ────────────────────────────────────────────────────────────

def test_validate_rejects_free_text():
    """The whole reason the vocabulary exists: a free-text expectation can
    only be scored by a second opinion, and a generous judge scores a
    wrong answer as right."""
    with pytest.raises(ea.ExpectedAnswerError):
        ea.validate("about twenty-three dollars")


def test_validate_rejects_an_unknown_type():
    with pytest.raises(ea.ExpectedAnswerError) as exc:
        ea.validate({"type": "shipping_speed", "value": "2 days"})
    assert "shipping_speed" in str(exc.value)


@pytest.mark.parametrize("incomplete", [
    {"type": "price", "amount": "22.99"},                       # no currency
    {"type": "member_price", "amount": "16.84", "currency": "USD"},   # no tier
    {"type": "code", "code": "SNUG3", "value_kind": "amount_off"},    # no value
    {"type": "brand_mention"},                                  # no brand
    {"type": "points", "rule": {"kind": "per_dollar"}},         # no rate
    {"type": "points", "rule": {"kind": "fixed"}},              # no total
])
def test_validate_rejects_a_partial_expectation(incomplete):
    with pytest.raises(ea.ExpectedAnswerError):
        ea.validate(incomplete)


def test_validate_accepts_every_constructed_shape():
    for built in (
        ea.price("22.99"),
        ea.gtin("884400137609"),
        ea.pack_count(84),
        ea.code("SNUG3", "amount_off", "3.00"),
        ea.member_price("16.84", "Member+"),
        ea.points("per_dollar", rate="1.0"),
        ea.points("fixed", total=16),
        ea.brand_mention("Wiggle & Snug", "trueshopstore.com"),
    ):
        assert ea.validate(built) is built


def test_is_scoreable_is_false_for_no_expectation():
    """category_control questions carry none, deliberately. Layer 1 still
    runs on them; Layer 2 does not."""
    assert ea.is_scoreable(None) is False
    assert ea.is_scoreable({}) is False


# ── secondary expectations ────────────────────────────────────────────────

def test_secondary_rides_along_on_the_primary():
    built = ea.with_secondary(
        ea.price("22.99"), [ea.gtin("884400137609")],
    )
    assert built["type"] == "price"
    assert built["secondary"] == [{"type": "gtin", "value": "884400137609"}]
    ea.validate(built)


def test_secondary_is_validated_too():
    with pytest.raises(ea.ExpectedAnswerError):
        ea.with_secondary(ea.price("22.99"), [{"type": "vibes"}])


def test_no_secondary_leaves_the_expectation_untouched():
    primary = ea.price("22.99")
    assert ea.with_secondary(primary, []) == primary


# ── display ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("built, rendered", [
    (ea.price("22.99"), "22.99 USD"),
    (ea.gtin("884400137609"), "GTIN 884400137609"),
    (ea.pack_count(84), "84 count"),
    (ea.code("SNUG3", "amount_off", "3.00"), "SNUG3, 3.00 off"),
    (ea.code("WELCOME10", "percent_off", "10.0"), "WELCOME10, 10.00% off"),
    (ea.member_price("16.84", "Member+"), "16.84 USD (Member+)"),
    (ea.points("per_dollar", rate="1.0"), "1.00 points per dollar"),
    (ea.points("fixed", total=16), "16 points"),
    (ea.brand_mention("Wiggle & Snug", "trueshopstore.com"),
     "brand named, trueshopstore.com cited"),
    (ea.brand_mention("Wiggle & Snug"), "brand named"),
])
def test_describe_renders_each_type(built, rendered):
    assert ea.describe(built) == rendered


# ── the vocabulary lists themselves ───────────────────────────────────────

def test_the_seven_types_are_the_seven_the_document_names():
    assert ea.EXPECTED_ANSWER_TYPES == [
        "price", "gtin", "pack_count", "code",
        "member_price", "points", "brand_mention",
    ]


def test_the_five_outcomes_include_unscoreable_as_its_own_bucket():
    assert ea.EXPECTATION_OUTCOMES == [
        "exact", "stale", "wrong", "absent", "unscoreable",
    ]
    assert "unscoreable" in ea.EXPECTATION_OUTCOMES


def test_the_four_tiers():
    assert ea.QUERY_TIERS == [
        "brand_direct", "catalog_accuracy", "value_incentives", "category_control",
    ]
