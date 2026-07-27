"""
Tests for scan/site_typing.py — Stage 11 (Layer 4) commerce-signal-based
site typing. Pure unit tests against synthetic PageScanData/
DiscoveryResult objects — no HTTP mocking needed.
"""
from scan.discovery import DiscoveryResult, PageCandidate
from scan.engine import PageScanData
from scan.fetcher import FetchResult
from scan.structured_data import ExtractedData, OfferData, ProductData
from scan.site_typing import (
    SITE_TYPE_BRAND_ONLY,
    SITE_TYPE_COMMERCE,
    SITE_TYPE_DISCOVERY_FAILURE,
    classify_site,
)


def _page(kind, html=None, extracted=None, status="fetched"):
    fetch_result = FetchResult(url=f"https://shop.example.com/{kind}", status=status, html=html)
    return PageScanData(candidate=PageCandidate(url=fetch_result.url, kind=kind), fetch_result=fetch_result, extracted=extracted)


def _discovery(robots_html=None, sitemap_urls=None, sitemap_index_entries=None):
    return DiscoveryResult(
        robots_fetch=FetchResult(url="https://shop.example.com/robots.txt", status="fetched", html=robots_html),
        robot_parser=None,
        sitemap_urls=sitemap_urls or [],
        sitemap_index_entries=sitemap_index_entries or [],
    )


PLAIN_HOMEPAGE = "<html><body><nav><a href='/about'>About</a><a href='/blog'>Blog</a></nav></body></html>"
CART_HOMEPAGE = "<html><body><nav><a href='/cart'>Cart (2)</a><a href='/about'>About</a></nav></body></html>"
SHOPIFY_HOMEPAGE = '<html><head><link href="https://cdn.shopify.com/s/files/1/theme.css"></head><body></body></html>'
GENERATOR_HOMEPAGE = '<html><head><meta name="generator" content="Shopify"></head><body></body></html>'


def test_commerce_signals_and_product_pages_is_commerce_normal():
    homepage = _page("homepage", html=CART_HOMEPAGE)
    product = _page(
        "product",
        extracted=ExtractedData(products=[ProductData(name="Widget", offers=[OfferData(price=9.99)])]),
    )
    result = classify_site([homepage, product], _discovery())
    assert result.site_type == SITE_TYPE_COMMERCE
    assert result.signals  # non-empty


def test_cart_link_but_no_product_pages_is_discovery_failure():
    homepage = _page("homepage", html=CART_HOMEPAGE)
    result = classify_site([homepage], _discovery())
    assert result.site_type == SITE_TYPE_DISCOVERY_FAILURE
    assert result.reason == "product pages could not be discovered from sitemap or navigation"
    assert any("cart" in s for s in result.signals)


def test_platform_marker_but_no_product_pages_is_discovery_failure():
    homepage = _page("homepage", html=SHOPIFY_HOMEPAGE)
    result = classify_site([homepage], _discovery())
    assert result.site_type == SITE_TYPE_DISCOVERY_FAILURE
    assert any("platform marker" in s for s in result.signals)


def test_generator_meta_tag_counts_as_platform_marker():
    homepage = _page("homepage", html=GENERATOR_HOMEPAGE)
    result = classify_site([homepage], _discovery())
    assert result.site_type == SITE_TYPE_DISCOVERY_FAILURE


def test_commerce_path_in_robots_txt_but_no_product_pages_is_discovery_failure():
    homepage = _page("homepage", html=PLAIN_HOMEPAGE)
    discovery = _discovery(robots_html="User-agent: *\nDisallow: /products/wholesale\n")
    result = classify_site([homepage], discovery)
    assert result.site_type == SITE_TYPE_DISCOVERY_FAILURE
    assert any("robots.txt or sitemap" in s for s in result.signals)


def test_commerce_path_in_sitemap_index_entries_but_no_product_pages_is_discovery_failure():
    """A Shopify sitemapindex naming sitemap_products_1.xml is itself
    commerce evidence, even when that child sitemap was never actually
    followed (budget-starved) and no PDP was ever sampled."""
    homepage = _page("homepage", html=PLAIN_HOMEPAGE)
    discovery = _discovery(sitemap_index_entries=["https://shop.example.com/sitemap_products_1.xml"])
    result = classify_site([homepage], discovery)
    assert result.site_type == SITE_TYPE_DISCOVERY_FAILURE


def test_offer_markup_on_homepage_but_no_dedicated_product_pages_is_discovery_failure():
    homepage = _page(
        "homepage", html=PLAIN_HOMEPAGE,
        extracted=ExtractedData(products=[ProductData(name="Widget", offers=[OfferData(price=9.99)])]),
    )
    result = classify_site([homepage], _discovery())
    assert result.site_type == SITE_TYPE_DISCOVERY_FAILURE
    assert any("Offer markup" in s for s in result.signals)


def test_no_signals_anywhere_is_brand_only_with_positive_basis_reason():
    homepage = _page("homepage", html=PLAIN_HOMEPAGE)
    result = classify_site([homepage], _discovery())
    assert result.site_type == SITE_TYPE_BRAND_ONLY
    assert result.reason == "no cart, commerce paths, platform markers, or Offer markup found"
    assert result.signals == []


def test_no_homepage_at_all_never_raises():
    result = classify_site([], _discovery())
    assert result.site_type == SITE_TYPE_BRAND_ONLY


def test_malformed_extracted_data_never_raises():
    homepage = _page("homepage", html="<html>not much here</html>", extracted=ExtractedData())
    result = classify_site([homepage], _discovery())
    assert result.site_type in (SITE_TYPE_BRAND_ONLY, SITE_TYPE_DISCOVERY_FAILURE, SITE_TYPE_COMMERCE)
