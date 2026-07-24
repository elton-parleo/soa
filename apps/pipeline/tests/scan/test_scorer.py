"""
Scorer fixture tests, run through the full engine.run_scan() pipeline
with httpx mocked (no real network):

  (a) rich DTC store with full JSON-LD + member pricing scores high on
      the V-family dimensions
  (b) same store minus member price drops V3 specifically
  (c) bot-blocked responses -> status='blocked'
  (d) fake was-price fixture triggers the 59-point integrity cap with
      integrity_capped=True
"""
import socket

import httpx
import pytest

from scan import engine, fetcher

ROBOTS_TXT = "User-agent: *\nSitemap: https://rich.example.com/sitemap.xml\n"

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://rich.example.com/products/blue-widget</loc></url>
  <url><loc>https://rich.example.com/products/red-widget</loc></url>
</urlset>"""

HOMEPAGE_HTML = """
<html><body>
  <nav>
    <a href="/rewards">Rewards</a>
    <a href="/shipping-returns">Shipping &amp; Returns</a>
  </nav>
</body></html>
"""

LOYALTY_HTML = """
<html><body>
  <h1>Insider Rewards</h1>
  <p>Earn points on every purchase and unlock member tiers with exclusive perks.</p>
</body></html>
"""

SHIPPING_HTML = """
<html><body><p>Free shipping on orders over $50. See our return policy for details.</p></body></html>
"""


def _product_page_html(name: str, price: str, *, member_price=True, was_price=False, valid_through=True) -> str:
    offer = {
        "@type": "Offer",
        "price": price,
        "priceCurrency": "USD",
        "availability": "https://schema.org/InStock",
    }
    if valid_through:
        offer["priceValidUntil"] = "2026-12-31"

    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "offers": offer,
    }
    if member_price:
        product["memberPrice"] = {"@type": "PriceSpecification", "price": str(float(price) - 5)}

    was_price_html = ""
    if was_price:
        was_price_html = f'<span class="was-price"><del>${float(price) + 10:.2f}</del></span>'

    import json as _json
    return f"""
    <html><body>
      <script type="application/ld+json">{_json.dumps(product)}</script>
      <h1>{name}</h1>
      {was_price_html}
      <p>Now ${price}</p>
    </body></html>
    """


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    fetcher._last_fetch_at.clear()
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    yield
    fetcher._last_fetch_at.clear()


def _serve(pages: dict, default_status=404):
    """pages: {url_suffix: html}. Matched by the URL ending with the suffix, longest suffix first."""
    ordered = sorted(pages.items(), key=lambda kv: -len(kv[0]))

    def fake_get(self, url, headers=None):
        for suffix, html in ordered:
            if url.endswith(suffix):
                return httpx.Response(200, text=html, request=httpx.Request("GET", url))
        return httpx.Response(default_status, text="", request=httpx.Request("GET", url))
    return fake_get


def test_rich_dtc_store_scores_high_on_value_family(monkeypatch):
    pages = {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": SITEMAP_XML,
        "/rewards": LOYALTY_HTML,
        "/shipping-returns": SHIPPING_HTML,
        "/products/blue-widget": _product_page_html("Blue Widget", "29.99", member_price=True),
        "/products/red-widget": _product_page_html("Red Widget", "34.99", member_price=True),
        "rich.example.com": HOMEPAGE_HTML,
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    assert result.integrity_capped is False
    assert result.total_score is not None and result.total_score > 70

    v_family_total = sum(result.dimensions[c]["score"] for c in ("V1", "V2", "V3", "V4"))
    v_family_max = sum(result.dimensions[c]["max"] for c in ("V1", "V2", "V3", "V4"))
    assert v_family_total / v_family_max > 0.8

    assert result.dimensions["V3"]["score"] == result.dimensions["V3"]["max"]


def test_same_store_minus_member_price_drops_v3(monkeypatch):
    pages = {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": SITEMAP_XML,
        "/rewards": LOYALTY_HTML,
        "/shipping-returns": SHIPPING_HTML,
        "/products/blue-widget": _product_page_html("Blue Widget", "29.99", member_price=False),
        "/products/red-widget": _product_page_html("Red Widget", "34.99", member_price=False),
        "rich.example.com": HOMEPAGE_HTML,
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    assert result.dimensions["V3"]["score"] == 0.0
    # V1/V2/V4 should be unaffected by the missing member price.
    assert result.dimensions["V1"]["score"] == result.dimensions["V1"]["max"]
    assert result.dimensions["V2"]["score"] == result.dimensions["V2"]["max"]
    assert result.dimensions["V4"]["score"] == result.dimensions["V4"]["max"]


def test_bot_blocked_store_returns_blocked_status(monkeypatch):
    def fake_get(self, url, headers=None):
        return httpx.Response(403, text="Access Denied", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = engine.run_scan("https://big-box.example.com")

    assert result.status == "blocked"
    assert result.total_score is None
    assert result.dimensions == {}


def test_fake_was_price_triggers_59_cap(monkeypatch):
    pages = {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": SITEMAP_XML,
        "/rewards": LOYALTY_HTML,
        "/shipping-returns": SHIPPING_HTML,
        "/products/blue-widget": _product_page_html("Blue Widget", "29.99", member_price=True, was_price=True),
        "/products/red-widget": _product_page_html("Red Widget", "34.99", member_price=True, was_price=True),
        "rich.example.com": HOMEPAGE_HTML,
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    assert result.integrity_capped is True
    assert result.total_score <= 59
    assert result.dimensions["V5"]["score"] == 0.0
