"""
Stage 25 (Part 2, P2): member-value strict-parse fixture corpus —
_detect_member_price_structure replaces the old whole-blob substring scan
(MEMBER_PRICE_JSON_HINTS) with structural validation, reusing the same
schema.org vocabulary the landing page's own JSON-LD excerpt documents as
valid (JSONLD_KEY_ALLOWLIST: membershipPointsEarned, eligibleCustomerType)
plus the memberPrice/loyaltyPrice convention scorer.py's fix text already
recommends.
"""
from scan.structured_data import _detect_member_price_structure


def _offers(node):
    offers = node.get("offers")
    return offers if isinstance(offers, list) else ([offers] if offers else [])


# ─── Valid structures (each is sufficient on its own) ────────────────────

def test_member_price_field_with_numeric_price_is_valid():
    node = {"memberPrice": {"@type": "PriceSpecification", "price": "24.99"}}
    assert _detect_member_price_structure(node, _offers(node)) is True


def test_loyalty_price_field_as_a_bare_number_is_valid():
    node = {"loyaltyPrice": 24.99}
    assert _detect_member_price_structure(node, _offers(node)) is True


def test_offer_with_eligible_customer_type_string_is_valid():
    node = {"offers": {"@type": "Offer", "price": "29.99", "eligibleCustomerType": "LoyaltyProgramMember"}}
    assert _detect_member_price_structure(node, _offers(node)) is True


def test_offer_with_eligible_customer_type_list_is_valid():
    node = {"offers": {"@type": "Offer", "eligibleCustomerType": ["LoyaltyProgramMember"]}}
    assert _detect_member_price_structure(node, _offers(node)) is True


def test_offer_with_membership_points_earned_is_valid():
    node = {
        "offers": {
            "@type": "Offer", "price": "29.99",
            "priceSpecification": {"@type": "UnitPriceSpecification", "membershipPointsEarned": 10},
        },
    }
    assert _detect_member_price_structure(node, _offers(node)) is True


def test_second_offer_in_a_list_with_eligible_customer_type_is_valid():
    """A product with two Offers — a regular one and a member-priced one
    — where only the SECOND carries eligibleCustomerType."""
    node = {
        "offers": [
            {"@type": "Offer", "price": "29.99"},
            {"@type": "Offer", "price": "24.99", "eligibleCustomerType": "LoyaltyProgramMember"},
        ],
    }
    assert _detect_member_price_structure(node, _offers(node)) is True


# ─── The false-positive this replaces: a bare text mention ───────────────

def test_a_prose_mention_of_member_price_in_description_is_not_valid():
    """The exact false-positive P2 fixes: the old MEMBER_PRICE_JSON_HINTS
    scan matched this substring anywhere in the JSON blob (json.dumps(node)
    .lower()), including here — a marketing sentence, not a structured
    price. Strict-parse requires the real schema.org shape instead."""
    node = {
        "@type": "Product", "name": "Widget",
        "description": "Ask about our member price and loyalty program discounts in store.",
        "offers": {"@type": "Offer", "price": "29.99"},
    }
    assert _detect_member_price_structure(node, _offers(node)) is False


def test_eligible_customer_type_as_empty_string_is_not_valid():
    node = {"offers": {"@type": "Offer", "eligibleCustomerType": "  "}}
    assert _detect_member_price_structure(node, _offers(node)) is False


def test_membership_points_earned_as_a_non_numeric_string_is_not_valid():
    """Guards against a stray "membershipPointsEarned": "yes" or similar
    malformed value counting as real structure."""
    node = {"offers": {"@type": "Offer", "priceSpecification": {"membershipPointsEarned": "lots"}}}
    assert _detect_member_price_structure(node, _offers(node)) is False


def test_membership_points_earned_boolean_is_not_valid():
    """bool is a subclass of int in Python — explicitly excluded so a
    stray true/false value can't accidentally pass as a point count."""
    node = {"offers": {"@type": "Offer", "priceSpecification": {"membershipPointsEarned": True}}}
    assert _detect_member_price_structure(node, _offers(node)) is False


def test_member_price_field_with_unparseable_price_is_not_valid():
    node = {"memberPrice": {"@type": "PriceSpecification", "price": "call for pricing"}}
    assert _detect_member_price_structure(node, _offers(node)) is False


def test_no_member_signal_anywhere_is_not_valid():
    node = {"@type": "Product", "name": "Widget", "offers": {"@type": "Offer", "price": "29.99"}}
    assert _detect_member_price_structure(node, _offers(node)) is False


def test_never_raises_on_malformed_offers_list():
    node = {"offers": ["not-a-dict", None, 42]}
    assert _detect_member_price_structure(node, _offers(node)) is False
