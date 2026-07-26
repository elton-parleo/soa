"""
Scorer fixture tests, run through the full engine.run_scan() pipeline
with httpx mocked (no real network).

Stage 1: (a) rich DTC store with full JSON-LD + member pricing scores
high on the V-family dimensions (b) same store minus member price drops
V3 specifically (c) bot-blocked responses -> status='blocked' (d) fake
was-price fixture triggers the 59-point integrity cap.

Stage 10 (scorer_version "2"): rescoped rubric semantics — F2 absorbs
identifiers + shipping, F3 becomes Protocol & Feed Presence (scored
llms.txt/MCP/UCP/agentic-hints, deferred Merchant Center/ACP/feed-sync),
V4 gains CONCRETE/ACTIVE/ACTIONABLE sub-checks, V5's cap discipline
tightens to sitewide-only evidence, and a brand-only site drops F3/V3 to
'na' with A2 rescaling over applicable dimensions only.
"""
import json as _json
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

SINGLE_PRODUCT_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://rich.example.com/products/blue-widget</loc></url>
</urlset>"""

BRAND_ONLY_HOMEPAGE_HTML = """
<html><body>
  <nav>
    <a href="/rewards">Rewards</a>
    <a href="/about">About</a>
    <a href="/blog">Blog</a>
  </nav>
  <main>We make things. No storefront here, just our story.</main>
</body></html>
"""


def _product_page_html(
    name: str, price: str, *, member_price=True, was_price=False, valid_through=True,
    gtin=None, sku=None, brand=None, actionable=False, agentic_hint=False,
) -> str:
    offer = {
        "@type": "Offer",
        "price": price,
        "priceCurrency": "USD",
        "availability": "https://schema.org/InStock",
    }
    if valid_through:
        date = valid_through if isinstance(valid_through, str) else "2026-12-31"
        offer["priceValidUntil"] = date

    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "offers": offer,
    }
    if member_price:
        product["memberPrice"] = {"@type": "PriceSpecification", "price": str(float(price) - 5)}
    if gtin:
        product["gtin13"] = gtin
    if sku:
        product["sku"] = sku
    if brand:
        product["brand"] = {"@type": "Brand", "name": brand}
    if actionable:
        product["description"] = "Eligible for a stackable promo code at checkout."
    if agentic_hint:
        product["additionalProperty"] = {"@type": "PropertyValue", "name": "agentic-commerce", "value": "true"}

    was_price_html = ""
    if was_price:
        was_value = was_price if isinstance(was_price, (int, float)) else float(price) + 10
        was_price_html = f'<span class="was-price"><del>${was_value:.2f}</del></span>'

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


def _base_pages(**product_kwargs):
    return {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": SITEMAP_XML,
        "/rewards": LOYALTY_HTML,
        "/shipping-returns": SHIPPING_HTML,
        "/products/blue-widget": _product_page_html("Blue Widget", "29.99", **product_kwargs),
        "/products/red-widget": _product_page_html("Red Widget", "34.99", **product_kwargs),
        "rich.example.com": HOMEPAGE_HTML,
    }


def test_rich_dtc_store_scores_high_on_value_family(monkeypatch):
    pages = _base_pages(member_price=True)
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    assert result.integrity_capped is False
    assert result.total_score is not None and result.total_score > 70

    v_family_total = sum(result.dimensions[c]["score"] for c in ("V1", "V2", "V3", "V4"))
    v_family_max = sum(result.dimensions[c]["max"] for c in ("V1", "V2", "V3", "V4"))
    assert v_family_total / v_family_max > 0.7

    assert result.dimensions["V3"]["score"] == result.dimensions["V3"]["max"]
    assert result.dimensions["scorer_version"] == "2"


def test_same_store_minus_member_price_drops_v3(monkeypatch):
    with_member = _base_pages(member_price=True)
    without_member = _base_pages(member_price=False)
    monkeypatch.setattr(httpx.Client, "get", _serve(with_member))
    with_result = engine.run_scan("https://rich.example.com")
    monkeypatch.setattr(httpx.Client, "get", _serve(without_member))
    without_result = engine.run_scan("https://rich.example.com")

    assert without_result.status == "complete"
    assert without_result.dimensions["V3"]["score"] == 0.0
    # V1/V2/V4 depend only on price/currency/validity/actionability, not
    # member pricing, so removing memberPrice must not move them at all.
    for code in ("V1", "V2", "V4"):
        assert without_result.dimensions[code]["score"] == with_result.dimensions[code]["score"]


def test_bot_blocked_store_returns_blocked_status(monkeypatch):
    def fake_get(self, url, headers=None):
        return httpx.Response(403, text="Access Denied", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = engine.run_scan("https://big-box.example.com")

    assert result.status == "blocked"
    assert result.total_score is None
    assert result.dimensions == {}


def test_fake_was_price_with_no_validity_anywhere_triggers_59_cap(monkeypatch):
    pages = _base_pages(member_price=True, was_price=True, valid_through=False)
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    assert result.integrity_capped is True
    assert result.total_score <= 59
    assert result.dimensions["V5"]["score"] == 0.0
    cap_basis = result.dimensions["V5"]["cap_basis"]
    assert any("sitewide" in line for line in cap_basis)
    assert any("priceValidUntil" in line for line in cap_basis)


def test_was_price_with_a_genuine_validity_window_only_deducts_no_cap(monkeypatch):
    """A was-price signal present sitewide, but WITH a genuine validity
    window and a modest (non-implausible) discount depth, deducts V5
    points without capping — this used to trigger the Stage-1 cap; Stage
    10's cap is deliberately narrower (D4)."""
    pages = _base_pages(member_price=True, was_price=True, valid_through=True)
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    assert result.integrity_capped is False
    assert 0 < result.dimensions["V5"]["score"] < result.dimensions["V5"]["max"]
    assert result.dimensions["V5"]["cap_basis"] == []


def test_one_bad_pdp_alone_deducts_but_does_not_cap(monkeypatch):
    pages = {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": SITEMAP_XML,
        "/rewards": LOYALTY_HTML,
        "/shipping-returns": SHIPPING_HTML,
        "/products/blue-widget": _product_page_html("Blue Widget", "29.99", was_price=True, valid_through=False),
        "/products/red-widget": _product_page_html("Red Widget", "34.99", was_price=False),
        "rich.example.com": HOMEPAGE_HTML,
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    assert result.integrity_capped is False
    assert result.dimensions["V5"]["cap_basis"] == []
    assert 0 < result.dimensions["V5"]["score"] < result.dimensions["V5"]["max"]


def test_implausible_discount_depth_caps_even_with_a_validity_window(monkeypatch):
    """>=70% discount depth sitewide is its own cap trigger (D4), even
    when every page also carries a priceValidUntil — a genuinely deep
    "sale" on every single sampled page reads as fabricated regardless."""
    pages = {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": SITEMAP_XML,
        "/rewards": LOYALTY_HTML,
        "/shipping-returns": SHIPPING_HTML,
        "/products/blue-widget": _product_page_html("Blue Widget", "10.00", was_price=100.00, valid_through=True),
        "/products/red-widget": _product_page_html("Red Widget", "12.00", was_price=120.00, valid_through=True),
        "rich.example.com": HOMEPAGE_HTML,
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    assert result.integrity_capped is True
    cap_basis = result.dimensions["V5"]["cap_basis"]
    assert any("discount depth" in line for line in cap_basis)


def test_v5_deferred_price_history_item_never_lowers_score(monkeypatch):
    """S2: a deferred item never subtracts — a clean store with no
    dishonest signal at all still scores V5 at full marks even though
    the price-history deferred item is always present (D4)."""
    pages = _base_pages(member_price=True, was_price=False)
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.dimensions["V5"]["score"] == result.dimensions["V5"]["max"]
    assert result.dimensions["V5"]["coverage"] == "partial"
    labels = [item["label"] for item in result.dimensions["V5"]["deferred_items"]]
    assert "Price-history integrity" in labels


# ─── F2: identifiers + cross-page brand consistency (Stage 10, D1) ──────

def test_f2_identifiers_present_and_brand_consistent_scores_high(monkeypatch):
    pages = {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": SITEMAP_XML,
        "/rewards": LOYALTY_HTML,
        "/shipping-returns": SHIPPING_HTML,
        "/products/blue-widget": _product_page_html("Blue Widget", "29.99", gtin="00012345678905", sku="BW-1", brand="Acme"),
        "/products/red-widget": _product_page_html("Red Widget", "34.99", gtin="00012345678912", sku="RW-1", brand="Acme"),
        "rich.example.com": HOMEPAGE_HTML,
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    assert result.dimensions["F2"]["score"] == result.dimensions["F2"]["max"]
    assert any("2/2 product pages expose a gtin/mpn/sku identifier" in e for e in result.dimensions["F2"]["evidence"])


def test_f2_inconsistent_brand_across_pages_is_penalized(monkeypatch):
    pages = {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": SITEMAP_XML,
        "/rewards": LOYALTY_HTML,
        "/shipping-returns": SHIPPING_HTML,
        "/products/blue-widget": _product_page_html("Blue Widget", "29.99", gtin="00012345678905", brand="Acme"),
        "/products/red-widget": _product_page_html("Red Widget", "34.99", gtin="00012345678912", brand="Different Co"),
        "rich.example.com": HOMEPAGE_HTML,
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result_inconsistent = engine.run_scan("https://rich.example.com")

    consistent_pages = {
        **pages,
        "/products/red-widget": _product_page_html("Red Widget", "34.99", gtin="00012345678912", brand="Acme"),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(consistent_pages))
    result_consistent = engine.run_scan("https://rich.example.com")

    assert result_inconsistent.dimensions["F2"]["score"] < result_consistent.dimensions["F2"]["score"]
    assert any("inconsistent" in e for e in result_inconsistent.dimensions["F2"]["evidence"])


# ─── F3: Protocol & Feed Presence (Stage 10, D2) ─────────────────────────

def test_f3_llms_txt_mcp_ucp_fixture_scores_the_scored_portion(monkeypatch):
    homepage_with_markup = """
    <html><head>
      <link rel="mcp-manifest" href="/.well-known/mcp.json">
      <meta name="ucp-capability" content="checkout">
    </head><body>
      <nav>
        <a href="/rewards">Rewards</a>
        <a href="/shipping-returns">Shipping &amp; Returns</a>
      </nav>
    </body></html>
    """
    pages = {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": SITEMAP_XML,
        "/rewards": LOYALTY_HTML,
        "/shipping-returns": SHIPPING_HTML,
        "/llms.txt": "# rich.example.com\n\nWe sell widgets. Agents may quote prices from /products/.\n",
        "/.well-known/mcp.json": '{"mcp_version": "1"}',
        "/products/blue-widget": _product_page_html("Blue Widget", "29.99", agentic_hint=True),
        "/products/red-widget": _product_page_html("Red Widget", "34.99", agentic_hint=True),
        "rich.example.com": homepage_with_markup,
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    f3 = result.dimensions["F3"]
    assert f3["coverage"] == "partial"
    assert f3["score"] == f3["max"]
    assert "/llms.txt present and non-empty" in f3["evidence"]
    assert any("MCP endpoint declaration discoverable" in e for e in f3["evidence"])
    assert "UCP/UIP capability markup present" in f3["evidence"]
    # Deferred items are always present at scorer_version "2" and never
    # reduce the scored portion (S2) — this fixture still hits max.
    labels = {item["label"] for item in f3["deferred_items"]}
    assert labels == {
        "Merchant Center / Deal Directory participation",
        "ACP Promotions participation",
        "Feed-level incentive syndication",
    }


def test_f3_with_no_protocol_markup_scores_zero_but_stays_applicable(monkeypatch):
    pages = _base_pages()
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    f3 = result.dimensions["F3"]
    assert f3["coverage"] == "partial"
    assert f3["score"] == 0.0
    assert f3["max"] == 10


# ─── V4: CONCRETE / ACTIVE / ACTIONABLE (Stage 10, D3) ──────────────────

def test_v4_concrete_but_expired_offer_fails_active_only(monkeypatch):
    pages = {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": SINGLE_PRODUCT_SITEMAP_XML,
        "/rewards": LOYALTY_HTML,
        "/shipping-returns": SHIPPING_HTML,
        "/products/blue-widget": _product_page_html(
            "Blue Widget", "29.99", valid_through="2020-01-01",
        ),
        "rich.example.com": "<html><body></body></html>",
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    v4 = result.dimensions["V4"]
    assert "1/1 product pages state a concrete amount or discount mechanic" in v4["evidence"]
    assert "0/1 product pages declare a currently-active validity window" in v4["evidence"]
    assert "0/1 product pages expose eligibility/code/stackability terms" in v4["evidence"]
    assert v4["score"] == pytest.approx(v4["max"] / 3, abs=0.1)


def test_v4_full_concrete_active_actionable_scores_max(monkeypatch):
    pages = {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": SINGLE_PRODUCT_SITEMAP_XML,
        "/rewards": LOYALTY_HTML,
        "/shipping-returns": SHIPPING_HTML,
        "/products/blue-widget": _product_page_html(
            "Blue Widget", "29.99", valid_through="2099-01-01", actionable=True,
        ),
        "rich.example.com": "<html><body></body></html>",
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.dimensions["V4"]["score"] == result.dimensions["V4"]["max"]


# ─── D5: brand-only site (F3/V3 -> na, A2 rescaling) ─────────────────────

def test_brand_only_site_marks_f3_and_v3_na_and_rescales_total(monkeypatch):
    pages = {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": "<?xml version=\"1.0\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\"></urlset>",
        "/rewards": LOYALTY_HTML,
        "rich.example.com": BRAND_ONLY_HOMEPAGE_HTML,
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    assert result.dimensions["F3"]["coverage"] == "na"
    assert result.dimensions["V3"]["coverage"] == "na"
    # V5 has nothing to check without a product page — full marks, not a
    # degenerate zero, and still 'partial' (not 'na') per D5.
    assert result.dimensions["V5"]["score"] == result.dimensions["V5"]["max"]
    assert result.dimensions["V5"]["coverage"] == "partial"

    applicable = {c: d for c, d in result.dimensions.items() if isinstance(d, dict) and d.get("coverage") != "na"}
    applicable_score = sum(d["score"] for d in applicable.values())
    applicable_max = sum(d["max"] for d in applicable.values())
    expected_total = int(round(applicable_score / applicable_max * 100))
    assert result.total_score == expected_total
    assert 0 <= result.total_score <= 100


# ─── A2 rescaling arithmetic (na-exclusion exact, total always in [0,100]) ──

@pytest.mark.parametrize("member_price,was_price,valid_through", [
    (True, False, True),
    (False, False, True),
    (True, True, True),
    (True, True, False),
])
def test_a2_total_score_matches_applicable_rescale_formula(monkeypatch, member_price, was_price, valid_through):
    pages = _base_pages(member_price=member_price, was_price=was_price, valid_through=valid_through)
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    applicable = {c: d for c, d in result.dimensions.items() if isinstance(d, dict) and d.get("coverage") != "na"}
    applicable_score = sum(d["score"] for d in applicable.values())
    applicable_max = sum(d["max"] for d in applicable.values())
    raw_pct = applicable_score / applicable_max * 100
    expected = int(round(min(raw_pct, 59))) if result.integrity_capped else int(round(raw_pct))
    assert result.total_score == expected
    assert 0 <= result.total_score <= 100
