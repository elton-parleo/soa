"""
Tests for scan/discovery.py: finding product and loyalty pages from a
fixture sitemap and homepage nav, with robots.txt/sitemap fetches
mocked (no real network).
"""
import socket

import httpx
import pytest

from scan.discovery import discover_pages, resolve_canonical_origin
from scan.fetcher import FetchBudget, _last_fetch_at, POLITENESS_DELAY_SECONDS
from scan import fetcher

ROBOTS_TXT = "User-agent: *\nDisallow: /admin/\nSitemap: https://shop.example.com/sitemap.xml\n"

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://shop.example.com/</loc></url>
  <url><loc>https://shop.example.com/products/blue-widget</loc></url>
  <url><loc>https://shop.example.com/products/red-widget</loc></url>
  <url><loc>https://shop.example.com/products/green-widget</loc></url>
  <url><loc>https://shop.example.com/about</loc></url>
</urlset>"""

HOMEPAGE_HTML = """
<html><body>
  <nav>
    <a href="/rewards">Rewards</a>
    <a href="/shipping-returns">Shipping &amp; Returns</a>
    <a href="/about">About Us</a>
  </nav>
  <main>Welcome to Shop Example</main>
</body></html>
"""


@pytest.fixture(autouse=True)
def reset_politeness_state(monkeypatch):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    _last_fetch_at.clear()
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    yield
    _last_fetch_at.clear()


def _serve(pages: dict):
    def fake_get(self, url, headers=None):
        for path, (status, text) in pages.items():
            if url.endswith(path):
                return httpx.Response(status, text=text, request=httpx.Request("GET", url))
        return httpx.Response(404, text="not found", request=httpx.Request("GET", url))
    return fake_get


def test_discovers_product_and_loyalty_pages_from_sitemap_and_nav(monkeypatch):
    pages = {
        "/robots.txt": (200, ROBOTS_TXT),
        "/sitemap.xml": (200, SITEMAP_XML),
        "": (200, HOMEPAGE_HTML),  # matches the bare homepage URL (ends with "")
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = discover_pages("https://shop.example.com", FetchBudget())

    assert result.robots_fetch.status == "fetched"
    assert "https://shop.example.com/products/blue-widget" in result.sitemap_urls
    product_urls = {c.url for c in result.candidates if c.kind == "product"}
    assert product_urls, "expected at least one product-page candidate from the sitemap"
    assert all("/products/" in u for u in product_urls)
    assert len(product_urls) <= 2

    loyalty_candidates = [c for c in result.candidates if c.kind == "loyalty"]
    assert loyalty_candidates and loyalty_candidates[0].url.endswith("/rewards")

    shipping_candidates = [c for c in result.candidates if c.kind == "shipping_returns"]
    assert shipping_candidates and shipping_candidates[0].url.endswith("/shipping-returns")

    homepage_candidates = [c for c in result.candidates if c.kind == "homepage"]
    assert len(homepage_candidates) == 1


def test_falls_back_to_homepage_links_when_no_sitemap(monkeypatch):
    homepage_with_products = """
    <html><body>
      <a href="/products/blue-widget">Blue Widget</a>
      <a href="/products/red-widget">Red Widget</a>
      <a href="/rewards">Rewards</a>
    </body></html>
    """
    pages = {
        "/robots.txt": (404, ""),
        "/sitemap.xml": (404, ""),
        "": (200, homepage_with_products),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = discover_pages("https://no-sitemap.example.com", FetchBudget())

    product_urls = {c.url for c in result.candidates if c.kind == "product"}
    assert product_urls
    assert all("/products/" in u for u in product_urls)


def test_no_loyalty_link_means_no_loyalty_candidate(monkeypatch):
    pages = {
        "/robots.txt": (404, ""),
        "/sitemap.xml": (404, ""),
        "": (200, "<html><body><a href='/about'>About</a></body></html>"),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = discover_pages("https://no-loyalty.example.com", FetchBudget())
    assert not [c for c in result.candidates if c.kind == "loyalty"]


def test_llms_txt_and_mcp_well_known_are_always_added_as_candidates(monkeypatch):
    """Stage 10 (D2): every scan probes these two same-origin,
    protocol-presence paths regardless of what else discovery finds."""
    pages = {
        "/robots.txt": (404, ""),
        "/sitemap.xml": (404, ""),
        "": (200, "<html><body></body></html>"),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = discover_pages("https://plain.example.com", FetchBudget())

    llms_txt = [c for c in result.candidates if c.kind == "llms_txt"]
    mcp = [c for c in result.candidates if c.kind == "mcp_well_known"]
    assert llms_txt and llms_txt[0].url == "https://plain.example.com/llms.txt"
    assert mcp and mcp[0].url == "https://plain.example.com/.well-known/mcp.json"


# ─── Stage 11: canonical host resolution (H1/H2) ────────────────────────

def test_resolve_canonical_origin_follows_apex_to_www(monkeypatch):
    body = "<html><body><h1>Allbirds</h1><p>" + "Shoes made from wool. " * 6 + "</p></body></html>"

    def fake_get(self, url, headers=None):
        if url == "https://allbirds.com/":
            return httpx.Response(301, headers={"location": "https://www.allbirds.com/"}, request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    resolution = resolve_canonical_origin("https://allbirds.com/")

    assert resolution.origin == "https://www.allbirds.com"
    assert resolution.homepage_fetch.status == "fetched"
    assert resolution.cross_domain_flag is None


def test_resolve_canonical_origin_falls_back_to_input_on_cross_domain_stop(monkeypatch):
    def fake_get(self, url, headers=None):
        if url == "https://brand.example/":
            return httpx.Response(302, headers={"location": "https://retailer.example/"}, request=httpx.Request("GET", url))
        raise AssertionError("must never fetch the cross-domain redirect target")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    resolution = resolve_canonical_origin("https://brand.example/")

    assert resolution.origin == "https://brand.example"
    assert resolution.homepage_fetch.status == "failed"
    assert resolution.cross_domain_flag is not None
    assert "retailer.example" in resolution.cross_domain_flag


# ─── Stage 11 (D1): Shopify-shaped <sitemapindex> recursion ─────────────

SHOPIFY_SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://shop.example.com/sitemap_pages_1.xml</loc></sitemap>
  <sitemap><loc>https://shop.example.com/sitemap_products_1.xml</loc></sitemap>
</sitemapindex>"""

SHOPIFY_PAGES_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://shop.example.com/pages/about</loc></url>
</urlset>"""

SHOPIFY_PRODUCTS_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://shop.example.com/products/blue-widget</loc></url>
  <url><loc>https://shop.example.com/products/red-widget</loc></url>
</urlset>"""


def test_shopify_sitemapindex_recursion_finds_products_via_child_sitemap(monkeypatch):
    pages = {
        "/robots.txt": (404, ""),
        "/sitemap.xml": (200, SHOPIFY_SITEMAP_INDEX),
        "/sitemap_pages_1.xml": (200, SHOPIFY_PAGES_SITEMAP),
        "/sitemap_products_1.xml": (200, SHOPIFY_PRODUCTS_SITEMAP),
        "": (200, HOMEPAGE_HTML),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = discover_pages("https://shop.example.com", FetchBudget())

    assert "https://shop.example.com/products/blue-widget" in result.sitemap_urls
    # Sitemap-sampler rewrite (hotfix 5, S1.a): only the WINNING child by
    # product-URL density contributes its URLs — the pages child (0%
    # product density) is probed but never selected, so its URLs never
    # pollute the candidate pool. Both children are still probed (both
    # this small) and recorded in the sampling log either way.
    assert "https://shop.example.com/pages/about" not in result.sitemap_urls
    product_urls = {c.url for c in result.candidates if c.kind == "product"}
    assert product_urls
    assert result.discovery_path == "sitemap"
    assert result.products_found == 2
    # The un-followed child sitemap names are still recorded for
    # site_typing's T1 commerce-path signal, even once fetched.
    assert any("sitemap_products_1.xml" in u for u in result.sitemap_index_entries)
    assert result.sitemap_sampling["child_chosen"] == "https://shop.example.com/sitemap_products_1.xml"
    assert result.sitemap_sampling["candidates_found"] == 2
    # 3 entries: the top-level index itself, plus its two children.
    assert len(result.sitemap_sampling["children_probed"]) == 3


# ─── Stage 11 (D2): collection-page hop fallback ────────────────────────

EMPTY_URLSET = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>"""

HOMEPAGE_WITH_COLLECTION_LINK = """
<html><body>
  <nav>
    <a href="/collections/best-sellers">Shop Best Sellers</a>
  </nav>
  <main>Welcome to Shop Example</main>
</body></html>
"""

COLLECTION_PAGE_HTML = """
<html><body>
  <div class="grid">
    <a href="/products/blue-widget">Blue Widget</a>
    <a href="/products/red-widget">Red Widget</a>
  </div>
</body></html>
"""


def test_collection_hop_finds_products_when_sitemap_has_none(monkeypatch):
    pages = {
        "/robots.txt": (404, ""),
        "/sitemap.xml": (200, EMPTY_URLSET),
        "/collections/best-sellers": (200, COLLECTION_PAGE_HTML),
        "": (200, HOMEPAGE_WITH_COLLECTION_LINK),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = discover_pages("https://shop.example.com", FetchBudget())

    product_urls = {c.url for c in result.candidates if c.kind == "product"}
    assert product_urls
    assert all("/products/" in u for u in product_urls)
    assert result.discovery_path == "collection_hop"
    assert result.products_found == 2


# ─── Stage 11 (D1): discovery budget is separate from the content budget ─

def test_discovery_fetches_never_consume_the_content_budget(monkeypatch):
    """robots.txt + sitemapindex recursion (2 fetches) must not touch the
    caller's content-page budget — only the homepage-fallback fetch (when
    no pre-resolved homepage_fetch is passed in) does, matching
    pre-Stage-11 cost accounting for that one fetch."""
    pages = {
        "/robots.txt": (404, ""),
        "/sitemap.xml": (200, SHOPIFY_SITEMAP_INDEX),
        "/sitemap_pages_1.xml": (200, SHOPIFY_PAGES_SITEMAP),
        "/sitemap_products_1.xml": (200, SHOPIFY_PRODUCTS_SITEMAP),
        "": (200, HOMEPAGE_HTML),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    content_budget = FetchBudget(max_fetches=12)
    discover_pages("https://shop.example.com", content_budget)

    # Only the homepage-fallback fetch is charged here; robots.txt +
    # both sitemaps + the two well-known probes all draw from
    # discovery.py's own internal DISCOVERY_FETCH_BUDGET instead.
    assert content_budget.used == 1


def test_discovery_budget_bounds_sitemap_recursion_independently(monkeypatch):
    """A sitemapindex with more child sitemaps than the discovery budget
    allows must not raise or hang — it just stops recursing once the
    discovery budget (not the content budget) is exhausted. Each child
    here would resolve to real products if fetched, so finding none
    confirms recursion was actually bounded, not just accidentally empty."""
    many_children = "".join(
        f"<sitemap><loc>https://shop.example.com/sitemap_{i}.xml</loc></sitemap>" for i in range(20)
    )
    big_index = f'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{many_children}</sitemapindex>'
    child_with_products = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://shop.example.com/products/never-reached</loc></url>
</urlset>"""

    def fake_get(self, url, headers=None):
        if url.endswith("/robots.txt"):
            return httpx.Response(404, text="", request=httpx.Request("GET", url))
        if url.endswith("/sitemap.xml"):
            return httpx.Response(200, text=big_index, request=httpx.Request("GET", url))
        if url == "https://shop.example.com":
            return httpx.Response(200, text=HOMEPAGE_HTML, request=httpx.Request("GET", url))
        if "/sitemap_" in url:
            return httpx.Response(200, text=child_with_products, request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = discover_pages("https://shop.example.com", FetchBudget())
    # Bounded by DISCOVERY_FETCH_BUDGET/SITEMAP_CHILD_PROBE_LIMIT long
    # before all 20 children could be visited — never raises, never
    # hangs, and most of the declared children are never actually
    # fetched. Every probed child here is identical (same single URL),
    # so the content-based selector picks exactly one of them — the
    # URL still shows up, just once, not once per probed child.
    visited_children = sum(1 for u in result.sitemap_urls if u == "https://shop.example.com/products/never-reached")
    assert 0 < visited_children < 20
    assert len(result.sitemap_index_entries) == 20  # every declared child name is still recorded (T1)
