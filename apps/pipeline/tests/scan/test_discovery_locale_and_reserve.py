"""
Nike discovery fix: tests for the sitemap-ordering (product-hint +
locale) rewrite, the discovery-budget reserve that keeps
collection_hop/platform_endpoint/llm_assisted reachable after a
fully-exhausted sitemap walk, and the content-based sitemap-child
sampling fallback for URL shapes that match no known pattern at all.

Same no-real-network idiom as test_discovery_rescue.py: httpx.Client.get
is monkeypatched; generation.discovery_probe's OpenAI call is
monkeypatched at the function boundary.
"""
import socket

import httpx
import pytest

from scan import fetcher
from scan.discovery import discover_pages
from scan.fetcher import FetchBudget, FetchResult


@pytest.fixture(autouse=True)
def reset_politeness_state(monkeypatch):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    fetcher._last_fetch_at.clear()
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    yield
    fetcher._last_fetch_at.clear()


ORIGIN = "https://www.nike.example.com"

PRODUCT_PAGE_HTML = """
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product", "name": "Air Widget",
 "offers": {"@type": "Offer", "price": "140.00", "priceCurrency": "USD", "availability": "https://schema.org/InStock"}}
</script>
</head><body><h1>Air Widget</h1></body></html>
"""

NON_PRODUCT_PAGE_HTML = "<html><body><h1>About us</h1><p>" + "just company info " * 10 + "</p></body></html>"

HOMEPAGE_HTML_EN_US = (
    '<html lang="en-US"><body>'
    "<p>Welcome — the catalog itself is rendered entirely client-side, so no "
    "product links ever appear in this raw markup, plenty of copy here to "
    "clear the short-body heuristic like a genuine homepage would.</p>"
    "</body></html>"
)

def _dispatch(handlers, default=(404, ""), requested=None):
    """handlers: {suffix_or_exact_url: (status, body)}. Exact-URL
    entries win over suffix matches. `requested`, when given, collects
    every URL actually requested — fetcher.py's own never-throw
    discipline swallows any exception raised from inside httpx.Client.get,
    so "this URL must never be fetched" has to be asserted against this
    log afterward, not by raising from the fake transport."""

    def fake_get(self, url, headers=None):
        if requested is not None:
            requested.append(url)
        if url in handlers:
            entry = handlers[url]
        else:
            entry = None
            for key, value in handlers.items():
                if not key.startswith("http") and url.endswith(key):
                    entry = value
                    break
        status, body = entry if entry is not None else default
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))

    return fake_get


# ─── Nike-shaped fixture: product-hint + locale reordering ──────────────

# The exact seven sitemaps Nike's own robots.txt declares, in Nike's own
# declared order — the PDP index is third, after two sitemaps (help,
# then a 64-child landing-page index) that have nothing to do with
# products at all.
_NIKE_DECLARED_SITEMAPS = [
    "sitemap-us-help.xml",
    "sitemap-v2-landingpage-index.xml",
    "sitemap-v2-pdp-index.xml",
    "sitemap-v2-snkrsweb-index.xml",
    "sitemap-v2-gridwall-index.xml",
    "sitemap-v2-article-index.xml",
    "sitemap-locator-index.xml",
]

# 64 locale children, declared alphabetically (matching the real Nike
# shape) so "en-us" is nowhere near the front — de-at, en-at, en-au...
_LOCALE_CODES = [
    f"{lang}-{region}"
    for region in ("at", "au", "be", "ca", "ch", "cl", "cn", "co", "cz", "de", "dk",
                    "es", "fi", "fr", "gb", "gr", "hk", "hu", "id", "ie", "il", "in",
                    "it", "jp", "kr", "mx", "my", "nl", "no", "nz", "ph", "pl", "pt",
                    "ro", "ru", "se", "sg", "th", "tr", "tw", "ua", "us", "vn", "za")
    for lang in ("en",)
][:63] + ["de-at"]  # pad/trim to a large-but-fast-to-build set; exact count doesn't matter

_NIKE_ROBOTS_TXT = "User-agent: *\n" + "".join(
    f"Sitemap: {ORIGIN}/{name}\n" for name in _NIKE_DECLARED_SITEMAPS
)

_NIKE_LANDINGPAGE_INDEX = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    + "".join(
        f"<sitemap><loc>{ORIGIN}/sitemap-v2-landingpage-{locale}.xml</loc></sitemap>"
        for locale in _LOCALE_CODES
    )
    + "</sitemapindex>"
)

_NIKE_PDP_CHILD_LOCALES = ["de-at", "en-at", "en-au", "en-us"]  # en-us declared LAST, not first

_NIKE_PDP_INDEX = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    + "".join(
        f"<sitemap><loc>{ORIGIN}/sitemap-v2-pdp-{locale}.xml</loc></sitemap>"
        for locale in _NIKE_PDP_CHILD_LOCALES
    )
    + "</sitemapindex>"
)


def _nike_pdp_child_xml(locale: str) -> str:
    if locale == "en-us":
        urls = [f"{ORIGIN}/t/air-widget-one-abc123", f"{ORIGIN}/t/air-widget-two-def456"]
    else:
        # Every non-en-us child is a real, fetchable sitemap with
        # locale-appropriate landing/collection URLs — zero PRODUCT_URL_
        # PATTERNS density either way, so picking en-us is a genuine
        # density+locale decision, not "only one child had any URLs".
        urls = [f"{ORIGIN}/w/{locale}/collection-one", f"{ORIGIN}/w/{locale}/collection-two"]
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{u}</loc></url>" for u in urls)
        + "</urlset>"
    )
    return body


def test_nike_shaped_pdp_index_probed_before_landingpage_locale_preferred_first(monkeypatch):
    handlers = {
        "/robots.txt": (200, _NIKE_ROBOTS_TXT),
        "sitemap-v2-pdp-index.xml": (200, _NIKE_PDP_INDEX),
        ORIGIN: (200, HOMEPAGE_HTML_EN_US),
        f"{ORIGIN}/t/air-widget-one-abc123": (200, PRODUCT_PAGE_HTML),
        f"{ORIGIN}/t/air-widget-two-def456": (200, PRODUCT_PAGE_HTML),
        "/llms.txt": (404, ""),
        "/.well-known/mcp.json": (404, ""),
    }
    for locale in _NIKE_PDP_CHILD_LOCALES:
        handlers[f"sitemap-v2-pdp-{locale}.xml"] = (200, _nike_pdp_child_xml(locale))

    requested: list = []
    monkeypatch.setattr(httpx.Client, "get", _dispatch(handlers, requested=requested))

    result = discover_pages(ORIGIN, FetchBudget())

    # The other six declared sitemaps (help, the 64-child landing-page
    # index, and the rest) must never actually be requested — the PDP
    # index alone, probed first, already exhausts the sitemap walk's
    # reserved share of the discovery budget (requirement 2) before the
    # top-level queue ever reaches them.
    joined = " ".join(requested)
    for forbidden_name in (
        "sitemap-us-help.xml", "sitemap-v2-landingpage-index.xml",
        "sitemap-v2-snkrsweb-index.xml", "sitemap-v2-gridwall-index.xml",
        "sitemap-v2-article-index.xml", "sitemap-locator-index.xml",
    ):
        assert forbidden_name not in joined, forbidden_name
    assert not any("landingpage-" in u and u != f"{ORIGIN}/sitemap-v2-landingpage-index.xml" for u in requested), (
        "no landing-page-index child should ever be fetched either"
    )

    sampling = result.sitemap_sampling
    declared_order = sampling["declared_order"]
    pdp_index_pos = next(i for i, u in enumerate(declared_order) if "pdp-index" in u)
    landingpage_pos = next(i for i, u in enumerate(declared_order) if "landingpage-index" in u)
    assert pdp_index_pos < landingpage_pos, "the PDP index must be walked before the landing-page index"

    assert sampling["locale_preferred"] == "en-us"

    # en-us is probed before its sibling children — it's the first
    # non-index entry recorded in children_probed after the pdp-index
    # itself.
    child_entries = [e for e in sampling["children_probed"] if e.get("is_index") is False]
    assert child_entries, "expected at least one pdp-index child to be probed"
    assert "en-us" in child_entries[0]["url"]

    product_urls = {c.url for c in result.candidates if c.kind == "product"}
    assert len(product_urls) >= 1
    assert all("/t/" in u for u in product_urls)
    assert result.discovery_path in ("sitemap", "sitemap_sampled")


# ─── Budget reserve: rescue tiers stay reachable, skips are logged ──────

_DECOY_CHILD_COUNT = 10


def _decoy_index_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(
            f"<sitemap><loc>{ORIGIN}/sitemap-decoy-{i}.xml</loc></sitemap>"
            for i in range(_DECOY_CHILD_COUNT)
        )
        + "</sitemapindex>"
    )


def _decoy_child_xml(i: int) -> str:
    # Zero PRODUCT_URL_PATTERNS density AND obviously non-product
    # content when sampled (requirement 3's content-sampling fallback
    # finds nothing here either) — a genuinely starved sitemap tree,
    # not just an unrecognized URL shape.
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{ORIGIN}/about/team-{i}</loc></url>"
        "</urlset>"
    )


ROBOTS_TXT_ONE_SITEMAP = f"User-agent: *\nSitemap: {ORIGIN}/sitemap.xml\n"


def _reserve_base_handlers(homepage_html: str) -> dict:
    handlers = {
        "/robots.txt": (200, ROBOTS_TXT_ONE_SITEMAP),
        "/sitemap.xml": (200, _decoy_index_xml()),
        ORIGIN: (200, homepage_html),
        "/llms.txt": (404, ""),
        "/.well-known/mcp.json": (404, ""),
    }
    for i in range(_DECOY_CHILD_COUNT):
        handlers[f"sitemap-decoy-{i}.xml"] = (200, _decoy_child_xml(i))
        handlers[f"/about/team-{i}"] = (200, NON_PRODUCT_PAGE_HTML)
    return handlers


MAGENTO_HOMEPAGE_HTML = (
    "<html><body><!-- powered by magento -->"
    "<p>Welcome to the store — plenty of real homepage copy here so this "
    "clears the short-body heuristic like any genuine homepage would, with "
    "no product or collection links anywhere in this raw markup.</p>"
    "</body></html>"
)


def test_exhausted_sitemap_walk_still_leaves_the_llm_tier_reachable(monkeypatch):
    """The decoy sitemapindex has 10 children — far more than the
    sitemap walk's reserved share can probe (SITEMAP_CHILD_PROBE_LIMIT
    and the reserve both cap it well under 10) — and every one it does
    probe is a genuine dead end (zero pattern density, no product markup
    on sampling). A platform IS detected (Magento) but isn't Shopify-
    shaped, so platform_endpoint spends nothing verifying that. The LLM
    tier still gets a real chance at the reserved fetches left over."""
    handlers = _reserve_base_handlers(MAGENTO_HOMEPAGE_HTML)
    handlers[f"{ORIGIN}/products/rescued-widget"] = (200, PRODUCT_PAGE_HTML)
    monkeypatch.setattr(httpx.Client, "get", _dispatch(handlers))
    monkeypatch.setattr(
        "generation.discovery_probe.probe_discover_urls",
        lambda homepage_url, api_key: {"urls": [f"{ORIGIN}/products/rescued-widget"]},
    )

    result = discover_pages(ORIGIN, FetchBudget(), api_key="fake-key")

    assert result.discovery_path == "llm_assisted"
    product_urls = {c.url for c in result.candidates if c.kind == "product"}
    assert product_urls == {f"{ORIGIN}/products/rescued-widget"}

    sampling = result.sitemap_sampling
    assert sampling["platform_detected"] == "magento"
    # Not every declared decoy child was probed — the reserve capped the
    # sitemap walk's own share well short of all 10.
    probed_children = [e for e in sampling["children_probed"] if "sitemap-decoy-" in e.get("url", "")]
    assert 0 < len(probed_children) < _DECOY_CHILD_COUNT


def test_a_rescue_tier_skipped_purely_for_budget_is_recorded_not_dropped(monkeypatch):
    """Same starved sitemap tree, but this time nothing about the
    homepage rules out Shopify's endpoints (no platform detected at
    all), so platform_endpoint spends the rest of the reserve probing
    all three of its own endpoints — leaving llm_assisted with nothing.
    That tier must still show up in tiers_attempted with an honest
    reason, never silently vanish."""
    handlers = _reserve_base_handlers(HOMEPAGE_HTML_EN_US)
    for path in (
        "/products.json?limit=24", "/collections/all/products.json?limit=24", "/sitemap_products_1.xml",
    ):
        handlers[path] = (404, "")
    monkeypatch.setattr(httpx.Client, "get", _dispatch(handlers))
    called = []
    monkeypatch.setattr(
        "generation.discovery_probe.probe_discover_urls",
        lambda homepage_url, api_key: (called.append(1), {"urls": []})[1],
    )

    result = discover_pages(ORIGIN, FetchBudget(), api_key="fake-key")

    assert result.discovery_path == "none"
    assert not called, "the LLM probe itself must never be called once its tier has no budget left"
    tiers_attempted = result.sitemap_sampling["tiers_attempted"]
    llm_entry = next(t for t in tiers_attempted if t["tier"] == "llm_assisted")
    assert llm_entry.get("skipped") == "discovery budget exhausted"


# ─── Content-based sitemap-child sampling (requirement 3) ───────────────

MYSTERY_PRODUCT_HTML = PRODUCT_PAGE_HTML
MYSTERY_NON_PRODUCT_HTML = NON_PRODUCT_PAGE_HTML


def test_child_confirmed_by_content_sampling_wins_over_a_child_with_neither(monkeypatch):
    """Two children of one sitemapindex match no PRODUCT_URL_PATTERNS
    shape at all (an unrecognized URL convention, not necessarily an
    empty catalog). Child B (probed first) samples to genuinely non-
    product pages and must NOT be selected; child A samples to real
    Product JSON-LD and must be — proving both halves of requirement 3's
    fallback in one fixture. The reserve (requirement 2) is neutralized
    here — it has its own dedicated tests above — so this fixture can
    freely spend a full CONTENT_SAMPLE_LIMIT sample on both children
    without the two requirements' budgets colliding."""
    monkeypatch.setattr("scan.discovery.RESCUE_FETCH_RESERVE", 0)
    index_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<sitemap><loc>{ORIGIN}/sitemap-mystery-b.xml</loc></sitemap>"
        f"<sitemap><loc>{ORIGIN}/sitemap-mystery-a.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    child_b_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{ORIGIN}/x/about-the-company</loc></url>"
        f"<url><loc>{ORIGIN}/x/press-room</loc></url>"
        "</urlset>"
    )
    child_a_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{ORIGIN}/x/widget-blue</loc></url>"
        f"<url><loc>{ORIGIN}/x/widget-red</loc></url>"
        "</urlset>"
    )
    handlers = {
        "/robots.txt": (200, ROBOTS_TXT_ONE_SITEMAP),
        "/sitemap.xml": (200, index_xml),
        "sitemap-mystery-b.xml": (200, child_b_xml),
        "sitemap-mystery-a.xml": (200, child_a_xml),
        f"{ORIGIN}/x/about-the-company": (200, MYSTERY_NON_PRODUCT_HTML),
        f"{ORIGIN}/x/press-room": (200, MYSTERY_NON_PRODUCT_HTML),
        f"{ORIGIN}/x/widget-blue": (200, MYSTERY_PRODUCT_HTML),
        f"{ORIGIN}/x/widget-red": (200, MYSTERY_PRODUCT_HTML),
        ORIGIN: (200, HOMEPAGE_HTML_EN_US),
        "/llms.txt": (404, ""),
        "/.well-known/mcp.json": (404, ""),
    }
    monkeypatch.setattr(httpx.Client, "get", _dispatch(handlers))

    result = discover_pages(ORIGIN, FetchBudget())

    assert result.discovery_path == "sitemap_sampled"
    product_urls = {c.url for c in result.candidates if c.kind == "product"}
    assert product_urls == {f"{ORIGIN}/x/widget-blue", f"{ORIGIN}/x/widget-red"}

    content_sampled = result.sitemap_sampling["content_sampled"]
    assert content_sampled["child_url"] == f"{ORIGIN}/sitemap-mystery-a.xml"
    assert set(content_sampled["confirmed_product_urls"]) == product_urls


def test_child_with_neither_pattern_nor_content_match_is_never_selected(monkeypatch):
    """A single, zero-density child whose sampled URLs are all
    genuinely non-product pages yields no candidates at all — the
    fallback must never fabricate a match."""
    monkeypatch.setattr("scan.discovery.RESCUE_FETCH_RESERVE", 0)
    index_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<sitemap><loc>{ORIGIN}/sitemap-mystery-b.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    child_b_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{ORIGIN}/x/about-the-company</loc></url>"
        f"<url><loc>{ORIGIN}/x/press-room</loc></url>"
        "</urlset>"
    )
    handlers = {
        "/robots.txt": (200, ROBOTS_TXT_ONE_SITEMAP),
        "/sitemap.xml": (200, index_xml),
        "sitemap-mystery-b.xml": (200, child_b_xml),
        f"{ORIGIN}/x/about-the-company": (200, MYSTERY_NON_PRODUCT_HTML),
        f"{ORIGIN}/x/press-room": (200, MYSTERY_NON_PRODUCT_HTML),
        ORIGIN: (200, HOMEPAGE_HTML_EN_US),
        "/llms.txt": (404, ""),
        "/.well-known/mcp.json": (404, ""),
    }
    monkeypatch.setattr(httpx.Client, "get", _dispatch(handlers))

    result = discover_pages(ORIGIN, FetchBudget())

    assert result.sitemap_sampling["content_sampled"] is None
    assert result.sitemap_sampling["child_chosen"] is None
    assert not [c for c in result.candidates if c.kind == "product"]
