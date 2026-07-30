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
from pathlib import Path

import httpx
import pytest

from scan import engine, fetcher
from scan.site_typing import BRAND_ONLY_REASON, DISCOVERY_FAILURE_REASON

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
    # Stage 25: value_protocols_seen is now in the crawl-only total too
    # (0/7 here — this fixture never declares an MCP capabilities
    # manifest), which dilutes the pre-Stage-25 ">70" bound; the fixture
    # is about F1-F3/price_truth/member_value/deal_citability scoring
    # high, not about protocol declarations, so the threshold moves
    # rather than adding an unrelated manifest fixture here.
    assert result.total_score is not None and result.total_score > 55

    true_value_total = sum(
        result.dimensions[c]["score"] for c in ("price_truth_seen", "member_value_seen", "deal_citability_seen")
    )
    true_value_max = sum(
        result.dimensions[c]["max"] for c in ("price_truth_seen", "member_value_seen", "deal_citability_seen")
    )
    assert true_value_total / true_value_max > 0.7

    # member_value_seen combines v2 loyalty_surface (program surface,
    # present in every _base_pages fixture) + member_value (member
    # pricing, present here) — both signals are present, so full marks.
    assert result.dimensions["member_value_seen"]["score"] == result.dimensions["member_value_seen"]["max"]
    assert result.dimensions["scorer_version"] == "4"


# ─── Part 5 (H1): fix_human — plain-language fix text ────────────────────

CRAWL_DIM_CODES = (
    "agent_access", "catalog_context", "protocol_feed",
    "price_truth_seen", "member_value_seen", "deal_citability_seen",
)


def test_fix_human_present_whenever_fix_is_and_absent_whenever_it_isnt(monkeypatch):
    """Every crawl-derived dimension either has both fix and fix_human, or
    neither — fix_human is never a second, independent signal that could
    drift out of sync with whether a fix actually exists."""
    pages = _base_pages()  # no llms.txt/mcp markup -> protocol_feed definitely has a fix
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    for code in CRAWL_DIM_CODES:
        dim = result.dimensions[code]
        assert ("fix" in dim) and ("fix_human" in dim)
        assert (dim["fix"] is None) == (dim["fix_human"] is None), code


def test_protocol_feed_fix_human_is_plain_language_no_markup(monkeypatch):
    pages = _base_pages()  # no llms.txt/mcp -> protocol_feed scores low, carries a fix
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")
    dim = result.dimensions["protocol_feed"]

    assert dim["fix"] is not None  # sanity: this fixture really does have a gap here
    fix_human = dim["fix_human"]
    assert fix_human is not None
    for marker in ("{", "<", "@type", "schema.org", "json-ld", "well-known"):
        assert marker.lower() not in fix_human.lower(), marker
    # H3: a single, plain sentence — not a semicolon/bullet-joined list.
    assert fix_human.count(".") <= 1


def test_no_markup_in_any_populated_fix_human_across_every_crawl_dimension(monkeypatch):
    """H2: whatever fix_human strings this run actually populates, none
    of them ever leak markup vocabulary — the technical version stays in
    `fix` only."""
    pages = _base_pages()
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))
    result = engine.run_scan("https://rich.example.com")

    for code in CRAWL_DIM_CODES:
        fix_human = result.dimensions[code]["fix_human"]
        if fix_human is None:
            continue
        for marker in ("{", "}", "<", ">", "@type", "json-ld", "schema.org"):
            assert marker.lower() not in fix_human.lower(), (code, marker)


def test_same_store_minus_member_price_drops_member_value_seen(monkeypatch):
    with_member = _base_pages(member_price=True)
    without_member = _base_pages(member_price=False)
    monkeypatch.setattr(httpx.Client, "get", _serve(with_member))
    with_result = engine.run_scan("https://rich.example.com")
    monkeypatch.setattr(httpx.Client, "get", _serve(without_member))
    without_result = engine.run_scan("https://rich.example.com")

    assert without_result.status == "complete"
    # member_value_seen = loyalty_surface (unchanged, still present) +
    # member_value (drops to 0 without memberPrice) — the combined
    # sub-lens drops, but not to zero, since the loyalty half is intact.
    assert (
        without_result.dimensions["member_value_seen"]["score"]
        < with_result.dimensions["member_value_seen"]["score"]
    )
    # price_truth_seen/deal_citability_seen depend only on price/
    # currency/validity/actionability, not member pricing, so removing
    # memberPrice must not move them at all.
    for code in ("price_truth_seen", "deal_citability_seen"):
        assert without_result.dimensions[code]["score"] == with_result.dimensions[code]["score"]


def test_bot_blocked_store_returns_blocked_status(monkeypatch):
    def fake_get(self, url, headers=None):
        return httpx.Response(403, text="Access Denied", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = engine.run_scan("https://big-box.example.com")

    assert result.status == "blocked"
    assert result.total_score is None
    assert result.dimensions == {}


def test_fake_was_price_with_no_validity_anywhere_is_advisory_only_never_caps(monkeypatch):
    """Stage 16 (Part 6): the same egregious was-price pattern that used
    to trigger the 59-point cap under v2 now has ZERO score effect under
    v3 — integrity_capped is always False, total_score is never capped,
    and the finding surfaces only as an unscored advisory."""
    pages = _base_pages(member_price=True, was_price=True, valid_through=False)
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    assert result.integrity_capped is False
    advisory = result.dimensions["price_honesty_advisory"]
    assert advisory["scored"] is False
    assert advisory["would_have_capped"] is True
    assert any("sitewide" in line for line in advisory["cap_basis"])
    assert any("priceValidUntil" in line for line in advisory["cap_basis"])
    # No dimension named after price honesty in the scored set at all.
    assert "price_truth" not in result.dimensions
    assert "offer_integrity" not in result.dimensions


def test_implausible_discount_depth_is_advisory_only_never_caps(monkeypatch):
    """>=70% discount depth sitewide would have triggered the v2 cap
    (D4) even with a validity window present — under v3 this is still
    flagged (would_have_capped=True) but has no score effect."""
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
    assert result.integrity_capped is False
    advisory = result.dimensions["price_honesty_advisory"]
    assert advisory["would_have_capped"] is True
    assert any("discount depth" in line for line in advisory["cap_basis"])


def test_clean_store_advisory_finds_nothing_and_never_scores(monkeypatch):
    """A clean store (no was-price signal at all) still gets an
    advisory entry, unscored, with no cap flag and no cap_basis —
    matches the old V5-at-full-marks case, just relabeled as advisory."""
    pages = _base_pages(member_price=True, was_price=False)
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    advisory = result.dimensions["price_honesty_advisory"]
    assert advisory["scored"] is False
    assert advisory["would_have_capped"] is False
    assert advisory["cap_basis"] == []


_FORBIDDEN_CAP_PHRASES = ("score cap", "59-point", "59 point", "capped the score", "score is capped")


@pytest.mark.parametrize("was_price,valid_through", [(True, False), (True, True), (False, True)])
def test_no_score_cap_language_in_v3_evidence_or_fix_text(monkeypatch, was_price, valid_through):
    """Stage 16 (Part 6) grep-test: sweep every dimension's evidence/fix
    strings (including the price_honesty_advisory) across the would-
    have-capped, discount-flagged, and clean cases — none may ever use
    'cap'-the-score language, since v3 has no cap to describe."""
    pages = _base_pages(member_price=True, was_price=was_price, valid_through=valid_through)
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    blob_parts = []
    for value in result.dimensions.values():
        if not isinstance(value, dict):
            continue
        blob_parts.extend(str(e) for e in (value.get("evidence") or []))
        if value.get("fix"):
            blob_parts.append(str(value["fix"]))
    blob = " ".join(blob_parts).lower()
    for phrase in _FORBIDDEN_CAP_PHRASES:
        assert phrase not in blob


def test_no_score_cap_language_anywhere_in_scan_module_source():
    """Static grep over apps/pipeline/scan/*.py — a regression guard
    against reintroducing cap-the-score copy anywhere in the module,
    not just the fixtures exercised above."""
    scan_dir = Path(__file__).resolve().parents[2] / "scan"
    offenders = []
    for path in scan_dir.glob("*.py"):
        text = path.read_text().lower()
        for phrase in _FORBIDDEN_CAP_PHRASES:
            if phrase in text:
                offenders.append((path.name, phrase))
    assert offenders == []


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
    assert result.dimensions["catalog_context"]["score"] == result.dimensions["catalog_context"]["max"]
    assert any("2/2 product pages expose a gtin/mpn/sku identifier" in e for e in result.dimensions["catalog_context"]["evidence"])


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

    assert result_inconsistent.dimensions["catalog_context"]["score"] < result_consistent.dimensions["catalog_context"]["score"]
    assert any("inconsistent" in e for e in result_inconsistent.dimensions["catalog_context"]["evidence"])


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
    f3 = result.dimensions["protocol_feed"]
    assert f3["coverage"] == "partial"
    assert f3["score"] == f3["max"]
    assert "/llms.txt present and non-empty" in f3["evidence"]
    assert any("MCP endpoint declaration discoverable" in e for e in f3["evidence"])
    assert "UCP/UIP capability markup present" in f3["evidence"]
    # Deferred items are always present and never reduce the scored
    # portion (S2) — this fixture still hits max.
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

    f3 = result.dimensions["protocol_feed"]
    assert f3["coverage"] == "partial"
    assert f3["score"] == 0.0
    assert f3["max"] == 6


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
    v4 = result.dimensions["deal_citability_seen"]
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

    assert result.dimensions["deal_citability_seen"]["score"] == result.dimensions["deal_citability_seen"]["max"]


# ─── D5: brand-only site (F3/V3 -> na, A2 rescaling) ─────────────────────

def test_brand_only_site_marks_protocol_feed_na_and_rescales_total(monkeypatch):
    pages = {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": "<?xml version=\"1.0\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\"></urlset>",
        "/rewards": LOYALTY_HTML,
        "rich.example.com": BRAND_ONLY_HOMEPAGE_HTML,
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    assert result.dimensions["protocol_feed"]["coverage"] == "na"
    # Stage 16: member_value_seen combines loyalty-surface (never
    # product-page-dependent — always checkable) with member-price
    # encoding (na on a brand-only site). Because loyalty is always
    # applicable, the COMBINED sub-lens is no longer 'na' the way v2's
    # standalone V3 was — it degrades to loyalty-surface-only, rescaled
    # onto the full seen_max, and stays 'full' coverage. This is an
    # intentional consequence of the merge (T1), not a regression.
    member_value_seen = result.dimensions["member_value_seen"]
    assert member_value_seen["coverage"] == "full"
    assert member_value_seen["max"] == 9

    advisory = result.dimensions["price_honesty_advisory"]
    assert advisory["scored"] is False
    assert advisory["would_have_capped"] is False

    applicable = {c: d for c, d in result.dimensions.items() if isinstance(d, dict) and d.get("coverage") not in ("na",) and "score" in d}
    applicable_score = sum(d["score"] for d in applicable.values())
    applicable_max = sum(d["max"] for d in applicable.values())
    expected_total = int(round(applicable_score / applicable_max * 100))
    assert result.total_score == expected_total
    assert 0 <= result.total_score <= 100
    assert result.dimensions["protocol_feed"]["evidence"][0] == f"protocol & feed presence is not applicable — {BRAND_ONLY_REASON}"


# ─── Stage 11 (T2): discovery failure — commerce signals, no PDPs ───────

def test_commerce_signals_without_pdps_is_a_discovery_failure_never_brand_only(monkeypatch):
    """Commerce signals present (a cart link) but no product pages
    discoverable from sitemap or navigation — must degrade to
    coverage='partial' with the honest reason, never a brand-only or
    'not applicable' claim anywhere in the full serialized report."""
    cart_homepage = """
    <html><body>
      <nav>
        <a href="/cart">Cart (0)</a>
        <a href="/rewards">Rewards</a>
        <a href="/shipping-returns">Shipping &amp; Returns</a>
      </nav>
      <main>We sell things, but the crawl can't find the catalog this run.</main>
    </body></html>
    """
    pages = {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": "<?xml version=\"1.0\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\"></urlset>",
        "/rewards": LOYALTY_HTML,
        "/shipping-returns": SHIPPING_HTML,
        "rich.example.com": cart_homepage,
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://rich.example.com")

    assert result.status == "complete"
    for code in ("catalog_context", "price_truth_seen", "deal_citability_seen"):
        assert result.dimensions[code]["coverage"] == "partial"
        assert result.dimensions[code]["evidence"] == [DISCOVERY_FAILURE_REASON]
    # member_value_seen combines loyalty (always applicable, found here)
    # with member-price encoding (partial — discovery failure, same
    # reason as the single-check dimensions above). 'partial' wins per
    # _combine_coverage, and the discovery-failure reason is still
    # surfaced honestly alongside the loyalty evidence.
    member_value_seen = result.dimensions["member_value_seen"]
    assert member_value_seen["coverage"] == "partial"
    assert DISCOVERY_FAILURE_REASON in member_value_seen["evidence"]
    # protocol_feed is decoupled from PDP discovery (T3) — still scored
    # normally, never na, regardless of the failed product-page sample.
    assert result.dimensions["protocol_feed"]["coverage"] == "partial"
    assert result.dimensions["protocol_feed"]["score"] >= 0

    serialized = _json.dumps(result.dimensions).lower()
    assert "brand-only" not in serialized
    assert "brand_only" not in serialized
    assert "not applicable" not in serialized


# ─── Stage 11 (T4): not_found vs failed on /.well-known/mcp.json ────────

def test_mcp_not_found_scores_absent_but_network_failure_excludes_the_subcheck(monkeypatch):
    pages_404 = _base_pages()  # mcp.json not declared -> default_status 404 -> not_found

    monkeypatch.setattr(httpx.Client, "get", _serve(pages_404))
    result_404 = engine.run_scan("https://rich.example.com")
    f3_404 = result_404.dimensions["protocol_feed"]
    assert any("no MCP endpoint declaration found" in e for e in f3_404["evidence"])
    assert not any("excluded from scoring" in e for e in f3_404["evidence"])

    def fake_get_network_failure(self, url, headers=None):
        if url.endswith("/.well-known/mcp.json"):
            raise httpx.TimeoutException("timed out")
        return _serve(_base_pages())(self, url, headers)

    monkeypatch.setattr(httpx.Client, "get", fake_get_network_failure)
    result_failed = engine.run_scan("https://rich.example.com")
    f3_failed = result_failed.dimensions["protocol_feed"]
    assert any("could not verify MCP endpoint" in e for e in f3_failed["evidence"])
    assert any("excluded from scoring" in e for e in f3_failed["evidence"])

    # The excluded (unverifiable) check must not have been scored as
    # absent — the remaining verifiable checks' weight rescales to fill
    # the gap rather than losing points to an unknown.
    other_checks_present = sum(
        1 for e in f3_failed["evidence"]
        if e in ("/llms.txt present and non-empty", "UCP/UIP capability markup present", "agentic-commerce hints present in structured data")
    )
    if other_checks_present:
        assert f3_failed["score"] > 0


# ─── A2 rescaling arithmetic (na-exclusion exact, total always in [0,100]) ──
# Stage 16 (Part 6): the integrity cap no longer exists under v3 — every
# case asserts result.integrity_capped is False and total_score is the
# plain na-exclusion rescale, with no cap branch to prove.

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
    assert result.integrity_capped is False
    applicable = {
        c: d for c, d in result.dimensions.items()
        if isinstance(d, dict) and "score" in d and d.get("coverage") != "na"
    }
    applicable_score = sum(d["score"] for d in applicable.values())
    applicable_max = sum(d["max"] for d in applicable.values())
    expected = int(round(applicable_score / applicable_max * 100))
    assert result.total_score == expected
    assert 0 <= result.total_score <= 100


# ─── Stage 11 acceptance: allbirds-like end-to-end fixture ──────────────
# A real network call to a third-party production domain isn't something
# to make from an automated test — this fixture models allbirds.com's
# actual observed shape instead (apex->www redirect, Shopify sitemapindex,
# Shopify platform markers), exercising every Stage 11 layer together.

def test_allbirds_like_fixture_resolves_www_and_scores_normally(monkeypatch):
    product_html = _product_page_html("Wool Runner", "98.00", gtin="00012345678905", brand="Allbirds")

    def fake_get(self, url, headers=None):
        if url == "https://allbirds.com":
            return httpx.Response(301, headers={"location": "https://www.allbirds.com/"}, request=httpx.Request("GET", url))
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nSitemap: https://www.allbirds.com/sitemap.xml\n", request=httpx.Request("GET", url))
        if url.endswith("/sitemap.xml"):
            return httpx.Response(200, text=(
                '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<sitemap><loc>https://www.allbirds.com/sitemap_products_1.xml</loc></sitemap>'
                '</sitemapindex>'
            ), request=httpx.Request("GET", url))
        if url.endswith("/sitemap_products_1.xml"):
            return httpx.Response(200, text=(
                '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<url><loc>https://www.allbirds.com/products/wool-runner</loc></url>'
                '</urlset>'
            ), request=httpx.Request("GET", url))
        if url == "https://www.allbirds.com/" or url == "https://www.allbirds.com":
            return httpx.Response(200, text=(
                '<html><head><link href="https://cdn.shopify.com/s/files/1/theme.css"></head>'
                '<body><nav><a href="/cart">Cart</a><a href="/rewards">Rewards</a>'
                '<a href="/shipping-returns">Shipping</a></nav></body></html>'
            ), request=httpx.Request("GET", url))
        if url.endswith("/products/wool-runner"):
            return httpx.Response(200, text=product_html, request=httpx.Request("GET", url))
        if url.endswith("/rewards"):
            return httpx.Response(200, text=LOYALTY_HTML, request=httpx.Request("GET", url))
        if url.endswith("/shipping-returns"):
            return httpx.Response(200, text=SHIPPING_HTML, request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = engine.run_scan("allbirds.com")

    assert result.status == "complete"
    # Canonical host resolved to www — every fetch after the initial
    # apex redirect targets www, never a mix of the two.
    non_initial_fetches = [f for f in result.pages_fetched if f["url"] != "https://allbirds.com"]
    assert non_initial_fetches
    assert all("www.allbirds.com" in f["url"] for f in non_initial_fetches)

    initial_fetch = next(f for f in result.pages_fetched if f["url"] == "https://allbirds.com")
    assert initial_fetch["final_url"] == "https://www.allbirds.com/"
    assert initial_fetch["status"] != "blocked"
    assert all(f["status"] != "blocked" for f in result.pages_fetched)

    # Product pages were discovered via the sitemap and scored normally
    # — protocol_feed/member_value_seen never claim brand-only/not-
    # applicable despite this being a real commerce catalog reached
    # through index recursion.
    assert result.dimensions["protocol_feed"]["coverage"] != "na"
    assert result.dimensions["member_value_seen"]["coverage"] != "na"
    assert "1/1 product pages expose a machine-readable price consistent with the page's own text" in result.dimensions["price_truth_seen"]["evidence"]
