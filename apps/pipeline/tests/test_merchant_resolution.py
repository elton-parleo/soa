"""
Tests for parser/merchant_resolution.py — resolving a coder-extracted
merchant_name against the known merchants table, and classifying each
observation's attribution status.
"""
from parser.merchant_resolution import KnownMerchant, classify_attribution, resolve_merchant_slug

MERCHANTS = [
    KnownMerchant(id=6, name="Target", slug="target", domain="target.com"),
    KnownMerchant(id=34, name="Walmart", slug="walmart", domain="walmart.com"),
    KnownMerchant(id=33, name="Amazon", slug="amazon", domain="amazon.com"),
    KnownMerchant(id=80, name="Pampers", slug="pampers", domain="pampers.com"),
    KnownMerchant(id=36, name="Costco Wholesale", slug="costco", domain="costco.com"),
    KnownMerchant(id=89, name="CVS", slug="cvs", domain="cvs.com"),
    KnownMerchant(id=4, name="Walgreens", slug="walgreens", domain="walgreens.com"),
    KnownMerchant(id=96, name="Sam's Club", slug="sams-club", domain="samsclub.com"),
    KnownMerchant(id=97, name="Kroger", slug="kroger", domain="kroger.com"),
    KnownMerchant(id=98, name="eBay", slug="ebay", domain="ebay.com"),
]


def test_exact_name_match():
    assert resolve_merchant_slug("Amazon", MERCHANTS) == "amazon"


def test_exact_slug_match_case_insensitive():
    assert resolve_merchant_slug("WALMART", MERCHANTS) == "walmart"


def test_substring_match_verbatim_evidence_phrasing():
    # Real example from cycle 55: evidence says "Walmart's Pampers Size 3 listing"
    assert resolve_merchant_slug("Walmart's Pampers Size 3 listing", MERCHANTS) == "walmart"


def test_substring_match_against_longer_merchant_name():
    # "Costco Wholesale" (name) should match "Costco" (a substring of the name).
    assert resolve_merchant_slug("Costco", MERCHANTS) == "costco"


def test_unmapped_merchant_returns_none():
    # Real example from cycle 55: rite-aid was never onboarded engine-side
    # (confirmed 404 on the Deal Engine) — a name outside the known set
    # must not silently match.
    assert resolve_merchant_slug("Rite Aid", MERCHANTS) is None


def test_none_input_returns_none():
    assert resolve_merchant_slug(None, MERCHANTS) is None


def test_empty_string_returns_none():
    assert resolve_merchant_slug("", MERCHANTS) is None
    assert resolve_merchant_slug("   ", MERCHANTS) is None


def test_pampers_brand_site_resolves_distinctly_from_retailers():
    assert resolve_merchant_slug("Pampers.com", MERCHANTS) == "pampers"
    assert resolve_merchant_slug("Pampers.com", MERCHANTS) != "walmart"


# --- classify_attribution -----------------------------------------------

def test_classify_unattributed_when_no_merchant_name():
    slug, status = classify_attribution("Pampers", None, MERCHANTS)
    assert slug is None
    assert status == "unattributed"


def test_classify_unmapped_when_merchant_not_known():
    slug, status = classify_attribution("Luvs", "Rite Aid", MERCHANTS)
    assert slug is None
    assert status == "unmapped"


def test_classify_mapped_when_retailer_differs_from_entity_brand():
    # Run 5798 (corrected): the Target price for the Pampers entity must
    # attribute to target, not to Pampers itself.
    slug, status = classify_attribution("Pampers", "Target", MERCHANTS)
    assert slug == "target"
    assert status == "mapped"


def test_classify_brand_self_reference_without_d2c_signal():
    # The failure mode found in validation: merchant_name resolves to the
    # SAME brand as the entity, with no explicit D2C signal and no
    # same-run citation to the brand's own domain.
    slug, status = classify_attribution("Pampers", "Pampers", MERCHANTS)
    assert slug is None
    assert status == "brand_self_reference"


def test_classify_mapped_when_self_reference_has_explicit_d2c_wording():
    slug, status = classify_attribution("Pampers", "Pampers.com", MERCHANTS)
    assert slug == "pampers"
    assert status == "mapped"

    slug, status = classify_attribution("Pampers", "Pampers' official website", MERCHANTS)
    assert slug == "pampers"
    assert status == "mapped"


def test_classify_mapped_when_self_reference_has_same_run_citation_to_own_domain():
    slug, status = classify_attribution(
        "Pampers", "Pampers", MERCHANTS, run_citation_domains={"pampers.com"},
    )
    assert slug == "pampers"
    assert status == "mapped"


def test_classify_self_reference_guard_is_specific_to_the_matching_brand():
    # A Huggies-entity observation naming "Pampers" is a genuine competing
    # retailer/brand mention, not a self-reference — must resolve normally.
    slug, status = classify_attribution("Huggies", "Pampers", MERCHANTS)
    assert slug == "pampers"
    assert status == "mapped"


# --- apostrophe / trailing-punctuation normalization (Task 1) -----------
# Real cycle-55 data: "Sam's Club" (straight apostrophe, 24 occurrences)
# and "Sam's Club" (curly ’, 22 occurrences) were both landing in
# 'unmapped' before this normalization, despite sams-club now existing
# as a known merchant.

def test_resolves_straight_apostrophe_variant():
    assert resolve_merchant_slug("Sam's Club", MERCHANTS) == "sams-club"


def test_resolves_curly_apostrophe_variant():
    assert resolve_merchant_slug("Sam’s Club", MERCHANTS) == "sams-club"


def test_resolves_no_apostrophe_variant():
    assert resolve_merchant_slug("Sams Club", MERCHANTS) == "sams-club"


def test_resolves_with_trailing_punctuation_and_whitespace():
    assert resolve_merchant_slug("  Kroger.  ", MERCHANTS) == "kroger"
    assert resolve_merchant_slug("eBay,", MERCHANTS) == "ebay"


def test_hyphenated_slug_matches_space_separated_name_variant():
    # merchant_name text is unlikely to contain the literal hyphenated
    # slug "sams-club" verbatim — the space-separated form must match too.
    assert resolve_merchant_slug("shop at Sam's Club for bulk diapers", MERCHANTS) == "sams-club"
