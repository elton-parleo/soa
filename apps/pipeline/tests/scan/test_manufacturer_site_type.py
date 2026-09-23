"""
Manufacturer sites (Clorox, request 146): real product pages with
Product JSON-LD and GTINs, no Offer anywhere, and a retailer link
("please enable cookies to find retailers"). site_typing records them as
"manufacturer" so the report can stop asking the brand to publish prices
it has no way to publish.

Two properties matter as much as the positive case: it never fires on
a store (any Offer, an add-to-cart control or a store-platform marker
rules it out), and it never changes a score — no scorer branches on it.
"""
import pytest

from scan import scorer
from scan.discovery import DiscoveryResult, PageCandidate
from scan.engine import PageScanData
from scan.fetcher import FetchResult
from scan.site_typing import (
    SITE_TYPE_COMMERCE,
    SITE_TYPE_MANUFACTURER,
    SiteTypeResult,
    classify_site,
)
from scan.structured_data import ExtractedData, OfferData, ProductData

CLOROX_HOMEPAGE = (
    "<html><body><nav><a href='/products/'>Products</a><a href='/tips/'>Tips</a></nav>"
    "<p>Bleach, wipes and cleaners for every room.</p></body></html>"
)
# Clorox's own retailer control, verbatim.
CLOROX_PDP = (
    "<html><body><h1>Clorox 2 for Colors Free &amp; Clear</h1>"
    "<button id='ot-sdk-btn'>Please enable cookies to find retailers.</button></body></html>"
)
PDP_NO_RETAILER_LINK = "<html><body><h1>Clorox 2 for Colors Free &amp; Clear</h1></body></html>"


def _product(offers=()):
    return ProductData(name="Clorox 2 for Colors", gtin="044600300481", offers=list(offers))


def _page(kind, html=None, extracted=None, status="fetched"):
    fr = FetchResult(url=f"https://www.clorox.example.com/{kind}", status=status, html=html)
    return PageScanData(candidate=PageCandidate(url=fr.url, kind=kind), fetch_result=fr, extracted=extracted)


def _discovery():
    return DiscoveryResult(
        robots_fetch=FetchResult(url="https://www.clorox.example.com/robots.txt", status="fetched", html="User-agent: *\n"),
        robot_parser=None,
        sitemap_urls=["https://www.clorox.example.com/products/clorox-2/"],
    )


def _clorox_pages(pdp_html=CLOROX_PDP, offers=(), homepage=CLOROX_HOMEPAGE):
    return [
        _page("homepage", html=homepage),
        _page("product", html=pdp_html, extracted=ExtractedData(products=[_product(offers)])),
        _page("product", html=pdp_html, extracted=ExtractedData(products=[_product(offers)])),
    ]


def test_clorox_shape_is_manufacturer():
    result = classify_site(_clorox_pages(), _discovery())
    assert result.site_type == SITE_TYPE_MANUFACTURER
    assert any("no Offer markup" in s for s in result.signals)
    assert any("find-a-retailer" in s for s in result.signals)


def test_retailer_link_on_the_homepage_counts_too():
    homepage = CLOROX_HOMEPAGE.replace("</nav>", "<a href='/where-to-buy/'>Where to Buy</a></nav>")
    result = classify_site(_clorox_pages(pdp_html=PDP_NO_RETAILER_LINK, homepage=homepage), _discovery())
    assert result.site_type == SITE_TYPE_MANUFACTURER


def test_a_pricespider_widget_counts_as_a_retailer_link():
    pdp = PDP_NO_RETAILER_LINK.replace("</body>", "<div class='ps-widget' ps-sku='044600300481'></div></body>")
    assert classify_site(_clorox_pages(pdp_html=pdp), _discovery()).site_type == SITE_TYPE_MANUFACTURER


def test_one_offer_anywhere_rules_it_out():
    pages = _clorox_pages()
    pages[2] = _page("product", html=CLOROX_PDP, extracted=ExtractedData(products=[_product([OfferData(price=6.49)])]))
    assert classify_site(pages, _discovery()).site_type != SITE_TYPE_MANUFACTURER


def test_no_retailer_signal_is_not_manufacturer():
    assert classify_site(_clorox_pages(pdp_html=PDP_NO_RETAILER_LINK), _discovery()).site_type != SITE_TYPE_MANUFACTURER


def test_an_add_to_cart_control_means_a_store_whatever_its_markup_lacks():
    """The case this must never mislabel: a DTC store with no Offer
    markup and a "Buy now" button. It is a store with a markup gap, and
    that gap is exactly what its report should tell it."""
    pdp = PDP_NO_RETAILER_LINK.replace(
        "</body>", "<a href='/checkout'>Buy now</a><button>Add to cart</button></body>",
    )
    assert classify_site(_clorox_pages(pdp_html=pdp), _discovery()).site_type != SITE_TYPE_MANUFACTURER


def test_a_store_platform_marker_rules_it_out():
    homepage = CLOROX_HOMEPAGE.replace("<body>", "<body><link href='https://cdn.shopify.com/s/files/1/x.css'>")
    assert classify_site(_clorox_pages(homepage=homepage), _discovery()).site_type != SITE_TYPE_MANUFACTURER


def test_no_product_page_read_is_never_manufacturer():
    pages = [_page("homepage", html=CLOROX_HOMEPAGE.replace("</nav>", "<a href='/where-to-buy/'>Where to Buy</a></nav>"))]
    assert classify_site(pages, _discovery()).site_type != SITE_TYPE_MANUFACTURER


def test_product_pages_that_failed_to_fetch_are_never_manufacturer():
    pages = [
        _page("homepage", html=CLOROX_HOMEPAGE),
        _page("product", html=None, extracted=None, status="blocked"),
    ]
    assert classify_site(pages, _discovery()).site_type != SITE_TYPE_MANUFACTURER


# ─── presentation only: no score moves ──────────────────────────────────

@pytest.mark.parametrize("score_fn", [
    scorer.score_catalog_context,
    scorer.score_protocol_feed,
    scorer.score_price_truth_seen,
    scorer.score_member_value_seen,
    scorer.score_deal_citability_seen,
])
def test_every_scorer_scores_a_manufacturer_exactly_like_commerce_normal(score_fn):
    pages = _clorox_pages()
    manufacturer = SiteTypeResult(site_type=SITE_TYPE_MANUFACTURER, reason="x")
    commerce = SiteTypeResult(site_type=SITE_TYPE_COMMERCE, reason="x")
    assert score_fn(pages, manufacturer) == score_fn(pages, commerce)
