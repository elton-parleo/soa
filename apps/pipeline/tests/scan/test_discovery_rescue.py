"""
Tests for the rescue-session discovery tiers: widened URL-shape
patterns (Part 1), deterministic platform-endpoint probes (Part 2),
last-resort LLM-assisted discovery (Part 3), and the provenance trail
they leave on the sampling record / Agent Access evidence / OfferFeed
eligibility / Price Truth coverage wording (Part 4).

Same no-real-network idiom as test_discovery.py/test_sitemap_sampler.py:
httpx.Client.get is monkeypatched; generation.discovery_probe's OpenAI
call is monkeypatched at the function boundary (probe_discover_urls),
same as test_fetch_probe.py's _call_once mocking.
"""
import json
import socket

import httpx
import pytest

from scan import engine, fetcher, scorer
from scan.discovery import (
    DiscoveryResult,
    _looks_like_collection_url,
    _looks_like_product_url,
    _probe_platform_endpoints,
    discover_pages,
)
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


ORIGIN = "https://shop.example.com"
CHEWY_ORIGIN = "https://chewy.example.com"


def _serve(pages: dict, origin: str = ORIGIN):
    """Same idiom as test_discovery.py's _serve, except the homepage is
    matched by exact URL equality against `origin` (a dict key, not a
    catch-all "" suffix) — every OTHER path in `pages` matches by
    suffix. This matters here specifically because several tests build
    `pages` via a base-dict helper and then add MORE keys afterward;
    dict insertion order would otherwise put a "" catch-all before
    those later keys and swallow requests meant for them."""
    def fake_get(self, url, headers=None):
        if url == origin and origin in pages:
            status, text = pages[origin]
            return httpx.Response(status, text=text, request=httpx.Request("GET", url))
        for path, (status, text) in pages.items():
            if path != origin and url.endswith(path):
                return httpx.Response(status, text=text, request=httpx.Request("GET", url))
        return httpx.Response(404, text="not found", request=httpx.Request("GET", url))
    return fake_get


# ─── Part 1: widened URL-shape patterns ──────────────────────────────────

@pytest.mark.parametrize("path", [
    "/pd/12345", "/prod/blue-widget", "/sku/BW-123",
    "/buy/blue-widget", "/detail/blue-widget",
    "/store/blue-widget-p12345", "/store/blue-widget-p12345.html",
    "/p/blue-widget/p98765",
])
def test_part1_widened_product_patterns_match(path):
    assert _looks_like_product_url(f"https://shop.example.com{path}") is True


@pytest.mark.parametrize("path", [
    "/browse/dresses", "/departments/electronics", "/department/electronics",
    "/catalog/mens", "/shop/womens",
])
def test_part1_widened_collection_patterns_match(path):
    assert _looks_like_collection_url(f"https://shop.example.com{path}") is True


@pytest.mark.parametrize("path", [
    "/pages/about", "/blogs/news/first-post", "/policies/privacy",
    "/account/orders", "/cart",
])
def test_part1_non_product_non_collection_paths_never_match(path):
    assert _looks_like_product_url(f"https://shop.example.com{path}") is False
    assert _looks_like_collection_url(f"https://shop.example.com{path}") is False


def test_part1_shop_segment_collection_beats_product_on_overlap():
    """/shop/ is deliberately in BOTH pattern sets — collection always
    wins, the conservative reading (never sample a category page)."""
    url = "https://shop.example.com/shop/dresses"
    assert _looks_like_collection_url(url) is True
    assert _looks_like_product_url(url) is False


# ─── Part 2: deterministic platform-endpoint probes ──────────────────────

SHOPIFY_HOMEPAGE_HTML = (
    "<html><head><script src='https://cdn.shopify.com/s/files/1/theme.js'></script></head>"
    "<body><p>Welcome to the store — enough real homepage copy here to clear "
    "the short-body heuristic like any genuine homepage would.</p></body></html>"
)

# The realistic Part 3 shape: a client-rendered (Next.js-style) shell —
# a real 200 response, but under fetcher.py's MIN_BODY_LENGTH, so
# fetcher.py's check_short_body heuristic (F2) marks it 'blocked', not
# 'fetched'. That's a DIFFERENT thing from the site actively blocking
# us (403/429/challenge) — _homepage_reached() in discovery.py treats
# "reached the homepage" as "got a real sub-400 HTTP response," not
# "our own body-length heuristic happened to like what came back," so
# the LLM tier can still fire here. This is also what makes
# _derive_status (engine.py) NOT take its early "homepage fetched fine
# -> complete" shortcut — the exact reason a real starved run reaches
# the no_product_pages_found banner at all, rather than a low-but-
# complete score.
PLAIN_HOMEPAGE_HTML = '<div id="__next"></div>'

PRODUCTS_JSON = json.dumps({"products": [{"handle": "blue-widget"}, {"handle": "red-widget"}]})

ROBOTS_DISALLOW_ALL_ENDPOINTS = (
    "User-agent: *\n"
    "Disallow: /products.json\n"
    "Disallow: /collections/\n"
    "Disallow: /sitemap_products_1.xml\n"
)


def test_part2_shopify_products_json_yields_verified_platform_endpoint_candidates(monkeypatch):
    pages = {
        "/robots.txt": (404, ""),
        "/sitemap.xml": (404, ""),
        "/products.json?limit=24": (200, PRODUCTS_JSON),
        ORIGIN: (200, SHOPIFY_HOMEPAGE_HTML),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = discover_pages("https://shop.example.com", FetchBudget())

    assert result.discovery_path == "platform_endpoint"
    product_urls = {c.url for c in result.candidates if c.kind == "product"}
    assert product_urls == {
        "https://shop.example.com/products/blue-widget",
        "https://shop.example.com/products/red-widget",
    }
    assert result.sitemap_sampling["platform_detected"] == "shopify"
    assert result.sitemap_sampling["platform_endpoint_used"] == "shopify_products_json"


def test_part2_all_endpoints_404_falls_through_cleanly(monkeypatch):
    pages = {
        "/robots.txt": (404, ""),
        "/sitemap.xml": (404, ""),
        ORIGIN: (200, SHOPIFY_HOMEPAGE_HTML),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = discover_pages("https://shop.example.com", FetchBudget())

    assert result.discovery_path == "none"
    assert result.sitemap_sampling["platform_detected"] == "shopify"
    assert result.sitemap_sampling["platform_endpoint_used"] is None
    probed = result.sitemap_sampling["platform_endpoints_probed"]
    assert len(probed) == 3
    assert all(e.get("outcome", "").startswith("fetch failed") for e in probed)


def test_part2_robots_disallowed_endpoint_is_skipped_without_a_fetch(monkeypatch):
    def fake_get(self, url, headers=None):
        if "/products.json" in url or "/collections/" in url or "/sitemap_products_1.xml" in url:
            raise AssertionError(f"must never fetch a robots-disallowed platform endpoint: {url}")
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=ROBOTS_DISALLOW_ALL_ENDPOINTS, request=httpx.Request("GET", url))
        if url.endswith("/sitemap.xml"):
            return httpx.Response(404, text="", request=httpx.Request("GET", url))
        if url == "https://shop.example.com":
            return httpx.Response(200, text=SHOPIFY_HOMEPAGE_HTML, request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = discover_pages("https://shop.example.com", FetchBudget())

    assert result.discovery_path == "none"
    probed = result.sitemap_sampling["platform_endpoints_probed"]
    assert len(probed) == 3
    assert all(e.get("skipped") == "robots disallowed" for e in probed)


def test_part2_budget_exhaustion_mid_tier_degrades_not_raises():
    exhausted_budget = FetchBudget(max_fetches=0)
    sampling_log = {"platform_detected": None, "platform_endpoints_probed": []}

    urls, endpoint = _probe_platform_endpoints(
        "https://shop.example.com", SHOPIFY_HOMEPAGE_HTML, None, exhausted_budget, [], sampling_log,
    )

    assert urls == []
    assert endpoint == "none"
    assert len(sampling_log["platform_endpoints_probed"]) == 3
    assert all(e.get("skipped") == "discovery budget exhausted" for e in sampling_log["platform_endpoints_probed"])


# ─── Part 3: LLM-assisted discovery (last resort, pointer only) ─────────

PRODUCT_PAGE_HTML = """
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product", "name": "Widget",
 "offers": {"@type": "Offer", "price": "19.99", "priceCurrency": "USD", "availability": "https://schema.org/InStock"}}
</script>
</head><body><h1>Widget</h1></body></html>
"""


def _llm_base_pages():
    return {
        "/robots.txt": (404, ""),
        "/sitemap.xml": (404, ""),
        "/products.json?limit=24": (404, ""),
        "/collections/all/products.json?limit=24": (404, ""),
        "/sitemap_products_1.xml": (404, ""),
        ORIGIN: (200, PLAIN_HOMEPAGE_HTML),
    }


def test_part3_llm_discovery_verifies_urls_in_isolation(monkeypatch):
    """_probe_llm_discovery on its own, given an unconstrained
    discovery_budget: both model-returned URLs verify. (The full-ladder
    integration test below shows the realistic, budget-constrained
    outcome — by the time the LLM tier runs, the sitemap + full
    platform-endpoint tier have already spent 5 of DISCOVERY_FETCH_
    BUDGET's 6 fetches, so at most one verification survives there.)"""
    from scan.discovery import _probe_llm_discovery

    pages = {
        "/products/blue-widget": (200, PRODUCT_PAGE_HTML),
        "/products/red-widget": (200, PRODUCT_PAGE_HTML),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))
    monkeypatch.setattr(
        "generation.discovery_probe.probe_discover_urls",
        lambda homepage_url, api_key: {"urls": [
            "https://shop.example.com/products/blue-widget",
            "https://shop.example.com/products/red-widget",
        ]},
    )

    verified, reused_fetches, trace = _probe_llm_discovery(
        "https://shop.example.com", None, FetchBudget(max_fetches=6), [], "fake-key",
    )

    assert verified == [
        "https://shop.example.com/products/blue-widget",
        "https://shop.example.com/products/red-widget",
    ]
    assert trace == {"urls_returned": 2, "urls_verified": 2, "rejections": []}
    assert set(reused_fetches) == set(verified)


def test_part3_llm_discovery_verified_happy_path_through_the_full_ladder(monkeypatch):
    """Integration-level: by the time the LLM tier runs, the sitemap
    tier + full platform-endpoint tier have already spent 5 of
    DISCOVERY_FETCH_BUDGET's 6 fetches, leaving exactly one
    verification fetch — the second, equally-valid URL is correctly
    rejected for budget, not fabricated or silently dropped."""
    pages = _llm_base_pages()
    pages["/products/blue-widget"] = (200, PRODUCT_PAGE_HTML)
    pages["/products/red-widget"] = (200, PRODUCT_PAGE_HTML)
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))
    monkeypatch.setattr(
        "generation.discovery_probe.probe_discover_urls",
        lambda homepage_url, api_key: {"urls": [
            "https://shop.example.com/products/blue-widget",
            "https://shop.example.com/products/red-widget",
        ]},
    )

    result = discover_pages("https://shop.example.com", FetchBudget(), api_key="fake-key")

    assert result.discovery_path == "llm_assisted"
    product_urls = {c.url for c in result.candidates if c.kind == "product"}
    assert product_urls == {"https://shop.example.com/products/blue-widget"}
    trace = result.sitemap_sampling["llm_discovery"]
    assert trace["urls_returned"] == 2
    assert trace["urls_verified"] == 1
    assert trace["rejections"] == [
        {"url": "https://shop.example.com/products/red-widget", "reason": "discovery budget exhausted"},
    ]
    # The one verified fetch is reused by engine.py's _gather_pages,
    # not fetched a second time against the content budget.
    assert set(result.reused_product_fetches) == product_urls


def test_part3_llm_discovery_rejects_off_domain_hallucination(monkeypatch):
    pages = _llm_base_pages()
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))
    monkeypatch.setattr(
        "generation.discovery_probe.probe_discover_urls",
        lambda homepage_url, api_key: {"urls": ["https://totally-different-store.example.com/products/x"]},
    )

    result = discover_pages("https://shop.example.com", FetchBudget(), api_key="fake-key")

    assert result.discovery_path == "none"
    trace = result.sitemap_sampling["llm_discovery"]
    assert trace["urls_verified"] == 0
    assert trace["rejections"] == [
        {"url": "https://totally-different-store.example.com/products/x", "reason": "off-domain"},
    ]


def test_part3_llm_discovery_rejects_a_url_with_no_product_markup(monkeypatch):
    pages = _llm_base_pages()
    pages["/about-us"] = (200, "<html><body><h1>About Us</h1><p>" + "just company info " * 10 + "</p></body></html>")
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))
    monkeypatch.setattr(
        "generation.discovery_probe.probe_discover_urls",
        lambda homepage_url, api_key: {"urls": ["https://shop.example.com/about-us"]},
    )

    result = discover_pages("https://shop.example.com", FetchBudget(), api_key="fake-key")

    assert result.discovery_path == "none"
    trace = result.sitemap_sampling["llm_discovery"]
    assert trace["rejections"] == [{"url": "https://shop.example.com/about-us", "reason": "no product markup found"}]


def test_part3_llm_discovery_empty_response_falls_through_cleanly(monkeypatch):
    """Covers malformed-JSON-at-the-source too: probe_discover_urls
    itself already guarantees {"urls": []} on any failure (see
    test_discovery_probe.py) — this confirms the tier consumes that
    contract without raising or fabricating anything."""
    pages = _llm_base_pages()
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))
    monkeypatch.setattr("generation.discovery_probe.probe_discover_urls", lambda homepage_url, api_key: {"urls": []})

    result = discover_pages("https://shop.example.com", FetchBudget(), api_key="fake-key")

    assert result.discovery_path == "none"
    assert result.sitemap_sampling["llm_discovery"] == {"urls_returned": 0, "urls_verified": 0, "rejections": []}


def test_part3_all_four_llm_urls_invalid_still_ends_no_product_pages_found_unchanged_banner(monkeypatch):
    pages = _llm_base_pages()
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))
    monkeypatch.setattr(
        "generation.discovery_probe.probe_discover_urls",
        lambda homepage_url, api_key: {"urls": [
            "https://off-domain.example.com/products/a",
            "https://off-domain.example.com/products/b",
            "https://off-domain.example.com/products/c",
            "https://off-domain.example.com/products/d",
        ]},
    )

    result = engine.run_scan("https://shop.example.com", api_key="fake-key")

    assert result.status == "failed"
    assert result.error == "no product pages found to sample"
    assert result.dimensions["degraded_reason"] == "no_product_pages_found"
    assert result.dimensions["discovery_path"] == "none"
    assert result.dimensions["sitemap_sampling"]["llm_discovery"]["urls_verified"] == 0
    # S3's banner-facts wording stays exactly as it was — this session
    # makes the state rarer, never softer.
    assert result.dimensions["degraded_banner_facts"]["sitemaps_read"] >= 0


def test_part3_llm_discovery_never_runs_when_flag_is_explicitly_off(monkeypatch):
    pages = _llm_base_pages()
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))
    monkeypatch.setenv("LLM_DISCOVERY_FALLBACK", "off")
    called = []
    monkeypatch.setattr(
        "generation.discovery_probe.probe_discover_urls",
        lambda homepage_url, api_key: (called.append(1), {"urls": []})[1],
    )

    result = discover_pages("https://shop.example.com", FetchBudget(), api_key="fake-key")

    assert not called
    assert result.sitemap_sampling["llm_discovery"] is None
    assert result.discovery_path == "none"


def test_part3_llm_discovery_never_runs_without_an_api_key_and_default_flag(monkeypatch):
    pages = _llm_base_pages()
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))
    monkeypatch.delenv("LLM_DISCOVERY_FALLBACK", raising=False)
    called = []
    monkeypatch.setattr(
        "generation.discovery_probe.probe_discover_urls",
        lambda homepage_url, api_key: (called.append(1), {"urls": []})[1],
    )

    result = discover_pages("https://shop.example.com", FetchBudget(), api_key=None)

    assert not called
    assert result.discovery_path == "none"


# ─── Part 4: provenance and honest reporting ─────────────────────────────

def _minimal_discovery(discovery_path: str) -> DiscoveryResult:
    return DiscoveryResult(
        robots_fetch=FetchResult(url="https://shop.example.com/robots.txt", status="fetched", html="User-agent: *\n"),
        robot_parser=None,
        sitemap_urls=[],
        discovery_path=discovery_path,
    )


@pytest.mark.parametrize("discovery_path", ["sitemap", "none"])
def test_part4_agent_access_evidence_omits_the_route_line_for_sitemap_and_none(discovery_path):
    result = scorer.score_agent_access(_minimal_discovery(discovery_path), [])
    evidence = " ".join(result.evidence)
    assert "couldn't find product pages through your declared sitemaps" not in evidence


@pytest.mark.parametrize("discovery_path,expected_note", [
    ("homepage", "found via your site's links, not your sitemap"),
    ("collection_hop", "found via your site's category pages, not your sitemap"),
    ("platform_endpoint", "found via your store platform's catalog endpoint"),
    ("llm_assisted", "found via AI-assisted discovery, not your sitemap"),
])
def test_part4_agent_access_evidence_names_the_route_for_non_sitemap_paths(discovery_path, expected_note):
    result = scorer.score_agent_access(_minimal_discovery(discovery_path), [])
    evidence = " ".join(result.evidence)
    assert "couldn't find product pages through your declared sitemaps" in evidence
    assert expected_note in evidence


def test_part4_agent_access_route_evidence_never_changes_the_score():
    plain = scorer.score_agent_access(_minimal_discovery("sitemap"), [])
    rescued = scorer.score_agent_access(_minimal_discovery("platform_endpoint"), [])
    assert plain.score == rescued.score
    assert plain.max == rescued.max


def test_part4_sampling_record_carries_platform_and_llm_trace_keys_on_every_run(monkeypatch):
    """The full ladder trace is present regardless of which tier (if
    any) actually won — same "recorded on every run" discipline as the
    pre-existing sitemap children_probed trace."""
    pages = {
        "/robots.txt": (200, "User-agent: *\nSitemap: https://shop.example.com/sitemap.xml\n"),
        "/sitemap.xml": (200, (
            '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://shop.example.com/products/blue-widget</loc></url></urlset>"
        )),
        ORIGIN: (200, SHOPIFY_HOMEPAGE_HTML),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = discover_pages("https://shop.example.com", FetchBudget())

    assert result.discovery_path == "sitemap"
    sampling = result.sitemap_sampling
    for key in ("tiers_attempted", "platform_detected", "platform_endpoints_probed", "platform_endpoint_used", "llm_discovery"):
        assert key in sampling
    # Sitemap succeeded, so neither downstream tier ever ran.
    assert sampling["platform_endpoints_probed"] == []
    assert sampling["llm_discovery"] is None


def test_part4_payload_contract_is_additive_discovery_path_present_and_agent_access_unaffected_when_sitemap(monkeypatch):
    pages = {
        "/robots.txt": (200, "User-agent: *\nSitemap: https://shop.example.com/sitemap.xml\n"),
        "/sitemap.xml": (200, (
            '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://shop.example.com/products/blue-widget</loc></url>"
            "<url><loc>https://shop.example.com/products/red-widget</loc></url></urlset>"
        )),
        "/products/blue-widget": (200, PRODUCT_PAGE_HTML),
        "/products/red-widget": (200, PRODUCT_PAGE_HTML),
        ORIGIN: (200, SHOPIFY_HOMEPAGE_HTML),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan("https://shop.example.com")

    assert result.status == "complete"
    assert result.dimensions["discovery_path"] == "sitemap"
    evidence = " ".join(result.dimensions["agent_access"]["evidence"])
    assert "couldn't find product pages through your declared sitemaps" not in evidence
    offers = result.dimensions["offers"]
    list_price_row = next(r for r in offers if r["name"] == "List price")
    assert "found via" not in list_price_row["eligibility"]


# ─── Starved-run replay: now scores ──────────────────────────────────────

CHEWY_INDEX_NO_CATALOG = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://chewy.example.com/sitemap-product-questions.xml</loc></sitemap>
  <sitemap><loc>https://chewy.example.com/sitemap-product-reviews.xml</loc></sitemap>
</sitemapindex>"""

CHEWY_QUESTIONS_CHILD = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://chewy.example.com/questions/123</loc></url>
</urlset>"""

CHEWY_REVIEWS_CHILD = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://chewy.example.com/reviews/789</loc></url>
</urlset>"""

CHEWY_SHOPIFY_HOMEPAGE_HTML = (
    "<html><head><script src='https://cdn.shopify.com/s/files/1/theme.js'></script></head>"
    "<body><p>Welcome to the store — enough real homepage copy here to clear "
    "the short-body heuristic, with the catalog rendered entirely client-side "
    "so no product links appear in this raw markup at all.</p></body></html>"
)


def test_starved_chewy_shaped_run_now_scores_via_platform_endpoint(monkeypatch):
    """Previously test_sitemap_sampler.py's
    test_chewy_replay_without_catalog_child_is_no_product_pages_found_not_blocked
    ended no_product_pages_found — same sitemapindex (decoys only, no
    real catalog child), same client-rendered homepage. Adding a
    Shopify fingerprint + a working /products.json (the actual rescue
    this session ships) now scores the run instead."""
    pages = {
        "/robots.txt": (200, "User-agent: *\nSitemap: https://chewy.example.com/sitemap.xml\n"),
        "/sitemap.xml": (200, CHEWY_INDEX_NO_CATALOG),
        "/sitemap-product-questions.xml": (200, CHEWY_QUESTIONS_CHILD),
        "/sitemap-product-reviews.xml": (200, CHEWY_REVIEWS_CHILD),
        "/products.json?limit=24": (200, PRODUCTS_JSON),
        "/products/blue-widget": (200, PRODUCT_PAGE_HTML),
        "/products/red-widget": (200, PRODUCT_PAGE_HTML),
        CHEWY_ORIGIN: (200, CHEWY_SHOPIFY_HOMEPAGE_HTML),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages, CHEWY_ORIGIN))

    result = engine.run_scan("https://chewy.example.com")

    assert result.status == "complete"
    assert result.total_score is not None
    assert result.dimensions["discovery_path"] == "platform_endpoint"
    assert result.dimensions["sitemap_sampling"]["platform_endpoint_used"] == "shopify_products_json"
    evidence = " ".join(result.dimensions["agent_access"]["evidence"])
    assert "found via your store platform's catalog endpoint" in evidence
    offers = result.dimensions["offers"]
    list_price_row = next(r for r in offers if r["name"] == "List price")
    assert "found via your store platform's catalog endpoint" in list_price_row["eligibility"]
