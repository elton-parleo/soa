"""
F1/F2 (V4 report redesign): direct unit tests for offer_feed.py's pure
functions. Fixtures build lightweight PageScanData/FetchResult/
DimensionScore-shaped objects directly rather than running a full
engine.run_scan() — no test_engine.py exists for that top-level
orchestration today, and these two functions don't need it.
"""
from dataclasses import dataclass, field
from typing import Optional

import pytest

from scan.offer_feed import build_offer_feed, extract_product_image, extract_product_name
from scan.scorer import DimensionScore
from scan.structured_data import ExtractedData, OfferData, ProductData


@dataclass
class _FetchResult:
    url: str
    final_url: Optional[str] = None


@dataclass
class _Page:
    fetch_result: _FetchResult
    extracted: Optional[ExtractedData]


def _page(url, extracted=None):
    return _Page(fetch_result=_FetchResult(url=url), extracted=extracted or ExtractedData())


def _dim(score, max_, coverage="full"):
    return DimensionScore(score=score, max=max_, coverage=coverage)


DIM_SCORES_ALL_ZERO = {
    "price_truth_seen": _dim(0, 5),
    "member_value_seen": _dim(0, 9),
    "deal_citability_seen": _dim(0, 4),
    "value_protocols_seen": _dim(0, 7),
}


# ─── extract_product_image (F2) ──────────────────────────────────────────

def test_extract_product_image_absolutizes_a_relative_url():
    extracted = ExtractedData(products=[ProductData(name="Widget", image="/img/widget.jpg")])
    pages = [_page("https://example.com/products/widget", extracted)]
    assert extract_product_image(pages) == "https://example.com/img/widget.jpg"


def test_extract_product_image_keeps_an_already_absolute_url():
    extracted = ExtractedData(products=[ProductData(name="Widget", image="https://cdn.example.com/widget.jpg")])
    pages = [_page("https://example.com/products/widget", extracted)]
    assert extract_product_image(pages) == "https://cdn.example.com/widget.jpg"


def test_extract_product_image_prefers_final_url_over_the_original_request_url():
    extracted = ExtractedData(products=[ProductData(name="Widget", image="/img/widget.jpg")])
    page = _page("https://example.com/products/widget", extracted)
    page.fetch_result.final_url = "https://www.example.com/products/widget"
    assert extract_product_image([page]) == "https://www.example.com/img/widget.jpg"


def test_extract_product_image_none_when_no_product_declares_one():
    extracted = ExtractedData(products=[ProductData(name="Widget")])
    pages = [_page("https://example.com/products/widget", extracted)]
    assert extract_product_image(pages) is None


def test_extract_product_image_none_when_page_extraction_failed():
    pages = [_Page(fetch_result=_FetchResult(url="https://example.com"), extracted=None)]
    assert extract_product_image(pages) is None


def test_extract_product_image_takes_the_first_across_multiple_pages():
    p1 = _page("https://example.com/a", ExtractedData(products=[ProductData(image="https://cdn.example.com/a.jpg")]))
    p2 = _page("https://example.com/b", ExtractedData(products=[ProductData(image="https://cdn.example.com/b.jpg")]))
    assert extract_product_image([p1, p2]) == "https://cdn.example.com/a.jpg"


# ─── extract_product_name (1c) ───────────────────────────────────────────

def test_extract_product_name_returns_the_first_declared_name():
    extracted = ExtractedData(products=[ProductData(name="Widget")])
    pages = [_page("https://example.com/products/widget", extracted)]
    assert extract_product_name(pages) == "Widget"


def test_extract_product_name_none_when_no_product_declares_one():
    extracted = ExtractedData(products=[ProductData(image="https://cdn.example.com/widget.jpg")])
    pages = [_page("https://example.com/products/widget", extracted)]
    assert extract_product_name(pages) is None


def test_extract_product_name_none_when_page_extraction_failed():
    pages = [_Page(fetch_result=_FetchResult(url="https://example.com"), extracted=None)]
    assert extract_product_name(pages) is None


def test_extract_product_name_takes_the_first_across_multiple_pages():
    p1 = _page("https://example.com/a", ExtractedData(products=[ProductData(name="Widget A")]))
    p2 = _page("https://example.com/b", ExtractedData(products=[ProductData(name="Widget B")]))
    assert extract_product_name([p1, p2]) == "Widget A"


def test_extract_product_name_is_independent_of_extract_product_image():
    # A product with a name but no image, and a separate product (or the
    # same one) with an image but no name, must each surface their own
    # field rather than one field's absence blanking the other.
    extracted = ExtractedData(products=[ProductData(name="Widget", image=None)])
    pages = [_page("https://example.com/widget", extracted)]
    assert extract_product_name(pages) == "Widget"
    assert extract_product_image(pages) is None

    extracted2 = ExtractedData(products=[ProductData(name=None, image="https://cdn.example.com/widget.jpg")])
    pages2 = [_page("https://example.com/widget", extracted2)]
    assert extract_product_name(pages2) is None
    assert extract_product_image(pages2) == "https://cdn.example.com/widget.jpg"


# ─── build_offer_feed (F1) ────────────────────────────────────────────────

def test_offer_feed_has_exactly_six_named_rows_in_order():
    rows = build_offer_feed([], DIM_SCORES_ALL_ZERO)
    assert [r["name"] for r in rows] == [
        "List price", "Availability", "Shipping", "Member price", "Deals and promos", "Checkout value",
    ]
    for r in rows:
        assert set(r.keys()) == {"name", "value", "channel", "eligibility", "freshness", "readable"}


def test_offer_feed_all_signals_absent_reads_invisible_or_unmeasured_never_fabricated():
    rows = build_offer_feed([], DIM_SCORES_ALL_ZERO)
    by_name = {r["name"]: r for r in rows}
    # DIM_SCORES_ALL_ZERO's dimensions are coverage="full", score=0 -> a
    # real, measured absence (invisible), not an unmeasured run.
    assert by_name["List price"]["readable"] == "invisible"
    assert by_name["List price"]["value"] == "Not encoded"
    assert by_name["Checkout value"]["readable"] == "invisible"
    assert by_name["Checkout value"]["value"] == "Nothing declared"


def test_offer_feed_list_price_row_from_a_priced_offer():
    products = [ProductData(name="Widget", offers=[OfferData(price=29.99, price_currency="USD")])]
    pages = [_page("https://example.com/widget", ExtractedData(products=products))]
    dim_scores = {**DIM_SCORES_ALL_ZERO, "price_truth_seen": _dim(5, 5)}
    rows = build_offer_feed(pages, dim_scores)
    row = next(r for r in rows if r["name"] == "List price")
    assert row["value"] == "$29.99"
    assert row["channel"] == "schema.org"
    assert row["eligibility"] == "1 of 1 offers"
    assert row["readable"] == "seen"


def test_offer_feed_availability_row_reads_the_raw_offer_availability_string():
    products = [ProductData(name="Widget", offers=[OfferData(availability="InStock")])]
    pages = [_page("https://example.com/widget", ExtractedData(products=products))]
    rows = build_offer_feed(pages, DIM_SCORES_ALL_ZERO)
    row = next(r for r in rows if r["name"] == "Availability")
    assert row["value"] == "InStock"
    assert row["readable"] == "seen"


def test_offer_feed_shipping_row_from_a_text_hit():
    extracted = ExtractedData(shipping_returns_text_hits=["free shipping over $50"])
    pages = [_page("https://example.com/widget", extracted)]
    rows = build_offer_feed(pages, DIM_SCORES_ALL_ZERO)
    row = next(r for r in rows if r["name"] == "Shipping")
    assert row["value"] == "free shipping over $50"
    assert row["channel"] == "page copy"
    assert row["readable"] == "partial"  # unstructured text, never a full "seen"


def test_offer_feed_member_price_row_never_fabricates_a_dollar_value():
    products = [ProductData(name="Widget", has_member_price_hint=True)]
    pages = [_page("https://example.com/widget", ExtractedData(products=products))]
    dim_scores = {**DIM_SCORES_ALL_ZERO, "member_value_seen": _dim(9, 9)}
    rows = build_offer_feed(pages, dim_scores)
    row = next(r for r in rows if r["name"] == "Member price")
    # No numeric member price is ever extracted by structured_data.py —
    # the row must say qualitatively that it's encoded, not invent a number.
    assert row["value"] == "Encoded on product data"
    assert "$" not in row["value"]
    assert row["readable"] == "seen"


def test_offer_feed_deals_and_promos_row_from_a_concrete_discount_hint():
    products = [ProductData(name="Widget", has_concrete_discount_hint=True)]
    pages = [_page("https://example.com/widget", ExtractedData(products=products))]
    dim_scores = {**DIM_SCORES_ALL_ZERO, "deal_citability_seen": _dim(4, 4)}
    rows = build_offer_feed(pages, dim_scores)
    row = next(r for r in rows if r["name"] == "Deals and promos")
    assert row["value"] == "Encoded on product data"
    assert row["readable"] == "seen"


def test_offer_feed_checkout_value_row_from_value_protocols():
    dim_scores = {**DIM_SCORES_ALL_ZERO, "value_protocols_seen": _dim(7, 7)}
    rows = build_offer_feed([], dim_scores)
    row = next(r for r in rows if r["name"] == "Checkout value")
    assert row["value"] == "Declared"
    assert row["channel"] == "UCP / ACP"
    assert row["readable"] == "seen"


# ─── H1: honest states — unmeasured, never a fabricated invisible ────────

def test_offer_feed_blocked_dimension_reads_unmeasured_not_invisible():
    dim_scores = {
        **DIM_SCORES_ALL_ZERO,
        "price_truth_seen": _dim(0, 5, coverage="blocked"),
        "member_value_seen": _dim(0, 9, coverage="blocked"),
        "deal_citability_seen": _dim(0, 4, coverage="blocked"),
    }
    rows = build_offer_feed([], dim_scores)
    by_name = {r["name"]: r for r in rows}
    assert by_name["List price"]["readable"] == "unmeasured"
    assert by_name["Availability"]["readable"] == "unmeasured"
    assert by_name["Shipping"]["readable"] == "unmeasured"
    assert by_name["Member price"]["readable"] == "unmeasured"
    assert by_name["Deals and promos"]["readable"] == "unmeasured"


def test_offer_feed_na_dimension_reads_unmeasured():
    dim_scores = {**DIM_SCORES_ALL_ZERO, "value_protocols_seen": _dim(0, 7, coverage="na")}
    rows = build_offer_feed([], dim_scores)
    row = next(r for r in rows if r["name"] == "Checkout value")
    assert row["readable"] == "unmeasured"


def test_offer_feed_missing_dimension_key_reads_unmeasured_not_a_crash():
    rows = build_offer_feed([], {})
    for row in rows:
        assert row["readable"] == "unmeasured"
