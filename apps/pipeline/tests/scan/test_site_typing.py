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


# ─── Discovery follow-up (Part 5): the loreal.com false positive ────────

def test_the_word_products_in_a_url_slug_is_not_a_commerce_path_signal():
    """loreal.com (a corporate/editorial site, no catalog): its own
    sitemap page URLs are prose slugs that happen to contain the word
    "products" — ".../for-our-products/", ".../creating-breakthrough-
    products-through-collaborative-play/" — never a genuine /products/
    catalog path. Must type brand_only, not commerce_discovery_failure,
    the way a real /products/<slug> path correctly still does below."""
    homepage = _page("homepage", html=PLAIN_HOMEPAGE)
    discovery = _discovery(sitemap_urls=[
        "https://loreal.example.com/en/commitments-and-responsibilities/for-our-products/",
        "https://loreal.example.com/en/beauty-science/creating-breakthrough-products-through-collaborative-play/",
    ])
    result = classify_site([homepage], discovery)
    assert result.site_type == SITE_TYPE_BRAND_ONLY


def test_a_real_products_path_segment_in_a_sitemap_url_is_still_a_commerce_signal():
    homepage = _page("homepage", html=PLAIN_HOMEPAGE)
    discovery = _discovery(sitemap_urls=["https://shop.example.com/products/blue-widget"])
    result = classify_site([homepage], discovery)
    assert result.site_type == SITE_TYPE_DISCOVERY_FAILURE
    assert any("robots.txt or sitemap" in s for s in result.signals)


def test_a_real_collections_path_segment_in_a_sitemap_url_is_still_a_commerce_signal():
    homepage = _page("homepage", html=PLAIN_HOMEPAGE)
    discovery = _discovery(sitemap_urls=["https://shop.example.com/collections/all"])
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


# ─── the site type is recorded on the row (this session) ────────────────
#
# classify_site has always run and always gated the scorers, but its
# answer never left the pipeline — it survived only as evidence wording.
# emcube, marketlytics and wealthsimple were all correctly typed
# brand_only, scored 10-22, and were then presented as failing STORES,
# because the report had no way to know what they were.

def _record_scan(monkeypatch, homepage_html, extra_pages=None):
    import socket

    import httpx

    from scan import engine, fetcher

    origin = "https://typed.example.com"
    pages = {"/robots.txt": "User-agent: *\nAllow: /\n"}
    pages.update(extra_pages or {})

    def fake_get(self, url, headers=None, **kw):
        if url == origin:
            return httpx.Response(200, text=homepage_html, request=httpx.Request("GET", url))
        key = url[len(origin):]
        body = pages.get(key)
        if body is None:
            return httpx.Response(404, text="", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    fetcher._last_fetch_at.clear()
    fetcher._domain_seen.clear()
    return engine.run_scan(origin)


_BRAND_ONLY_HOMEPAGE = (
    "<html><body><h1>Marketlytics</h1><p>We are a consultancy that helps teams "
    "understand their analytics. Read our case studies and our blog for the "
    "latest on measurement strategy and data engineering.</p>"
    "<a href='/about'>About</a><a href='/blog'>Blog</a></body></html>"
)

_STORE_HOMEPAGE = (
    "<html><body><h1>Big Box</h1><nav><a href='/cart'>Cart</a></nav>"
    "<p>Plenty of real homepage copy here so this clears the short-body "
    "heuristic like any genuine storefront would, with navigation and "
    "footer text and everything else a store carries.</p></body></html>"
)


def test_a_brand_only_run_records_its_site_type(monkeypatch):
    result = _record_scan(monkeypatch, _BRAND_ONLY_HOMEPAGE)

    assert result.status == "complete"
    assert result.dimensions["site_type"] == SITE_TYPE_BRAND_ONLY
    assert result.dimensions["site_type_signals"] == []


def test_a_commerce_run_records_its_site_type_and_the_signals_behind_it(monkeypatch):
    result = _record_scan(monkeypatch, _STORE_HOMEPAGE)

    assert result.dimensions["site_type"] in (SITE_TYPE_COMMERCE, SITE_TYPE_DISCOVERY_FAILURE)
    signals = result.dimensions["site_type_signals"]
    assert any("cart/checkout" in s for s in signals), signals


def test_recording_the_site_type_changes_no_score(monkeypatch):
    """Additive sibling keys only — the same reason sitemap_sampling and
    agent_access_matrix are recorded the way they are."""
    result = _record_scan(monkeypatch, _BRAND_ONLY_HOMEPAGE)

    # The scorer's own numbers, untouched: brand_only still scores
    # price_truth_seen/deal_citability_seen at coverage='full', which is
    # what it did before this key existed. Re-coding those to 'na' would
    # move applicable_max, and that is a methodology change.
    assert result.dimensions["price_truth_seen"]["coverage"] == "full"
    assert result.dimensions["deal_citability_seen"]["coverage"] == "full"
    assert result.total_score is not None
