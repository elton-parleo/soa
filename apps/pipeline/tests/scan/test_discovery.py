"""
Tests for scan/discovery.py: finding product and loyalty pages from a
fixture sitemap and homepage nav, with robots.txt/sitemap fetches
mocked (no real network).
"""
import socket

import httpx
import pytest

from scan.discovery import discover_pages
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
