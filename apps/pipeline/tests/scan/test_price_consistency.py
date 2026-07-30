"""
Stage 25 (Part 2, P1): the price-consistency fixture corpus — 5 named
scenarios proving _price_consistency_mismatch is conservative by
construction (a confident mismatch only ever fires when none of its 4
guards apply), plus score_price_truth_seen tests proving a confident
mismatch demotes a page to "no legible price" rather than a harsher,
separate penalty (Part 0 clarification: same effect as no structured
price at all).

Built directly against PageScanData/ExtractedData/ProductData/OfferData
rather than through engine.run_scan's HTTP-mocked fixtures (test_scorer.py's
convention) — precise control over the structured-vs-visible price
combination is the whole point of this corpus, and going through a full
HTML page would obscure exactly which guard each case exercises.
"""
from scan import scorer, site_typing
from scan.discovery import PageCandidate
from scan.engine import PageScanData
from scan.fetcher import FetchResult
from scan.structured_data import ExtractedData, OfferData, ProductData

COMMERCE_SITE = site_typing.SiteTypeResult(
    site_type=site_typing.SITE_TYPE_COMMERCE,
    reason="commerce signals present and product pages sampled",
    signals=["test"],
)


def _product_page(price, visible_prices, *, was_price_signals=None, currency="USD"):
    extracted = ExtractedData(
        products=[ProductData(name="Widget", offers=[OfferData(price=price, price_currency=currency)])],
        has_jsonld=True,
        visible_prices=visible_prices,
        was_price_signals=was_price_signals or [],
    )
    return PageScanData(
        candidate=PageCandidate(url="https://example.com/products/widget", kind="product"),
        fetch_result=FetchResult(url="https://example.com/products/widget", status="fetched"),
        extracted=extracted,
    )


# ─── _price_consistency_mismatch: the 5-scenario fixture corpus ──────────

def test_clean_match_is_never_a_mismatch():
    """The ordinary case: one visible price, and it agrees with the
    structured price."""
    page = _product_page(price=29.99, visible_prices=[29.99])
    assert scorer._price_consistency_mismatch(page) is False


def test_confident_mismatch_when_the_single_visible_price_clearly_disagrees():
    """No ambiguity to hide behind: one visible price, no was-price
    signal, and it's nowhere near the structured price."""
    page = _product_page(price=29.99, visible_prices=[49.99])
    assert scorer._price_consistency_mismatch(page) is True


def test_variant_priced_page_is_never_flagged_even_if_none_of_the_visible_prices_match():
    """Guard 2: more than one distinct visible price (different
    sizes/colors legitimately pricing differently) is too ambiguous to
    call a mismatch, even though neither visible number happens to equal
    the structured price."""
    page = _product_page(price=29.99, visible_prices=[34.99, 39.99])
    assert scorer._price_consistency_mismatch(page) is False


def test_sale_pair_page_is_never_flagged_despite_a_disagreeing_visible_price():
    """Guard 3: a was-price/strikethrough signal means the page shows two
    prices by design (original vs. discounted) — even if the one distinct
    parsed visible price disagrees with the structured price, we don't
    know which side of the sale it's supposed to match, so this is never
    called a confident mismatch."""
    page = _product_page(price=29.99, visible_prices=[49.99], was_price_signals=["strikethrough element: '$49.99'"])
    assert scorer._price_consistency_mismatch(page) is False


def test_no_text_price_page_is_never_flagged():
    """Guard 2 (the zero-price side): nothing to compare against at all —
    a JS-rendered price, an image price, or a page where the crawler's
    text extraction simply didn't find a dollar figure."""
    page = _product_page(price=29.99, visible_prices=[])
    assert scorer._price_consistency_mismatch(page) is False


# ─── Guard 4: rounding/formatting tolerance ───────────────────────────────

def test_a_one_cent_difference_is_tolerance_not_a_mismatch():
    page = _product_page(price=29.99, visible_prices=[30.00])
    assert scorer._price_consistency_mismatch(page) is False


def test_a_several_dollar_difference_clears_the_tolerance_and_is_a_mismatch():
    page = _product_page(price=29.99, visible_prices=[39.99])
    assert scorer._price_consistency_mismatch(page) is True


# ─── Guard 1: nothing structured to compare ──────────────────────────────

def test_no_structured_price_at_all_is_never_a_mismatch():
    extracted = ExtractedData(
        products=[ProductData(name="Widget", offers=[OfferData(price=None)])],
        visible_prices=[29.99],
    )
    page = PageScanData(
        candidate=PageCandidate(url="https://example.com/products/widget", kind="product"),
        fetch_result=FetchResult(url="https://example.com/products/widget", status="fetched"),
        extracted=extracted,
    )
    assert scorer._price_consistency_mismatch(page) is False


def test_any_matching_variant_offer_price_prevents_a_mismatch_call():
    """A page with multiple structured Offers (size/color variants) is
    only a confident mismatch if ALL of them disagree with the single
    visible price — one legitimate variant match is enough to explain
    what's shown."""
    extracted = ExtractedData(
        products=[ProductData(name="Widget", offers=[
            OfferData(price=34.99), OfferData(price=29.99),
        ])],
        visible_prices=[29.99],
    )
    page = PageScanData(
        candidate=PageCandidate(url="https://example.com/products/widget", kind="product"),
        fetch_result=FetchResult(url="https://example.com/products/widget", status="fetched"),
        extracted=extracted,
    )
    assert scorer._price_consistency_mismatch(page) is False


# ─── score_price_truth_seen: a mismatch degrades to "no legible price" ───

def test_score_price_truth_seen_excludes_a_mismatched_page_from_the_price_ratio():
    """A confident mismatch has the SAME effect on the price ratio as no
    structured price at all — not a separate, harsher penalty (Part 0
    clarification)."""
    clean_page = _product_page(price=29.99, visible_prices=[29.99])
    mismatched_page = _product_page(price=29.99, visible_prices=[49.99])

    clean_result = scorer.score_price_truth_seen([clean_page], COMMERCE_SITE)
    mismatch_result = scorer.score_price_truth_seen([mismatched_page], COMMERCE_SITE)

    # Same currency ratio either way (both declare priceCurrency) — only
    # the price component of the score differs.
    assert mismatch_result.score < clean_result.score
    no_price_page = _product_page(price=None, visible_prices=[])
    no_price_result = scorer.score_price_truth_seen([no_price_page], COMMERCE_SITE)
    assert mismatch_result.score == no_price_result.score


def test_score_price_truth_seen_surfaces_mismatch_evidence():
    mismatched_page = _product_page(price=29.99, visible_prices=[49.99])
    result = scorer.score_price_truth_seen([mismatched_page], COMMERCE_SITE)
    assert any("disagrees with the page's own visible price text" in e for e in result.evidence)


def test_score_price_truth_seen_clean_match_has_no_mismatch_evidence():
    clean_page = _product_page(price=29.99, visible_prices=[29.99])
    result = scorer.score_price_truth_seen([clean_page], COMMERCE_SITE)
    assert not any("disagrees with" in e for e in result.evidence)
