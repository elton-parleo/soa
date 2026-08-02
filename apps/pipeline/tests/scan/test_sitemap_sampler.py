"""
Tests for the sitemap-sampler rewrite (hotfix 5, S1/S2/S4): content-
based sitemap-child selection (never filename-trust), gzip sitemap
support, robots-disallow candidate exclusion before sampling, and the
run-status distinction between "the site blocked us" and "our sampler
found nothing" — the Chewy vs. Sephora incident shapes.
"""
import gzip
import re
import socket
from pathlib import Path

import httpx
import pytest

from scan import engine, fetcher
from scan.discovery import discover_pages
from scan.fetcher import FetchBudget


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


ROBOTS_TXT = "User-agent: *\nSitemap: https://chewy.example.com/sitemap.xml\n"

# Obfuscated index: two decoy children whose NAMES contain "product"
# but whose CONTENT is question/review URLs (zero product density), and
# one real catalog child ("sitemap-c.xml" — deliberately no "product"
# in the name) with genuine /dp/ product URLs. Filename-trust alone
# would pick a decoy; content-based density must pick the real one.
CHEWY_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://chewy.example.com/sitemap-product-questions.xml</loc></sitemap>
  <sitemap><loc>https://chewy.example.com/sitemap-product-reviews.xml</loc></sitemap>
  <sitemap><loc>https://chewy.example.com/sitemap-c.xml</loc></sitemap>
</sitemapindex>"""

CHEWY_INDEX_NO_CATALOG = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://chewy.example.com/sitemap-product-questions.xml</loc></sitemap>
  <sitemap><loc>https://chewy.example.com/sitemap-product-reviews.xml</loc></sitemap>
</sitemapindex>"""

CHEWY_QUESTIONS_CHILD = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://chewy.example.com/questions/123</loc></url>
  <url><loc>https://chewy.example.com/questions/456</loc></url>
</urlset>"""

CHEWY_REVIEWS_CHILD = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://chewy.example.com/reviews/789</loc></url>
</urlset>"""

CHEWY_CATALOG_CHILD = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://chewy.example.com/dp/dog-food-blue</loc></url>
  <url><loc>https://chewy.example.com/dp/cat-litter-tidy</loc></url>
</urlset>"""

CHEWY_PDP_HTML = """
<html><head><title>Dog Food - Chewy</title>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product", "name": "Dog Food",
 "offers": {"@type": "Offer", "price": "29.99", "priceCurrency": "USD", "availability": "https://schema.org/InStock"}}
</script></head>
<body><nav><a href="/">Home</a></nav><h1>Dog Food</h1></body></html>
"""

HOMEPAGE_HTML = (
    "<html><body><nav><a href='/rewards'>Rewards</a></nav>"
    "<p>Welcome to the store — plenty of real homepage copy here so this "
    "clears the short-body heuristic like any genuine homepage would.</p>"
    "</body></html>"
)


def _chewy_pages(index_xml=CHEWY_INDEX):
    return {
        "/robots.txt": (200, ROBOTS_TXT),
        "/sitemap.xml": (200, index_xml),
        "/sitemap-product-questions.xml": (200, CHEWY_QUESTIONS_CHILD),
        "/sitemap-product-reviews.xml": (200, CHEWY_REVIEWS_CHILD),
        "/sitemap-c.xml": (200, CHEWY_CATALOG_CHILD),
        "/dp/dog-food-blue": (200, CHEWY_PDP_HTML),
        "/dp/cat-litter-tidy": (200, CHEWY_PDP_HTML),
    }


def _serve_with_root_429(pages: dict, root_url="https://chewy.example.com"):
    """Every declared page fetches fine (200) EXCEPT the store root
    itself, which is rate-limited on every attempt — the exact Chewy
    incident shape."""
    def fake_get(self, url, headers=None):
        if url == root_url:
            return httpx.Response(429, text="", request=httpx.Request("GET", url))
        for path, (status, text) in pages.items():
            if url.endswith(path):
                return httpx.Response(status, text=text, request=httpx.Request("GET", url))
        return httpx.Response(404, text="not found", request=httpx.Request("GET", url))
    return fake_get


# ─── S1.a: content-based child selection ───────────────────────────────

def test_chewy_replay_picks_catalog_child_by_density_pdps_attempted_no_block(monkeypatch):
    monkeypatch.setattr(httpx.Client, "get", _serve_with_root_429(_chewy_pages()))

    result = engine.run_scan("https://chewy.example.com")

    assert result.status == "complete"
    assert result.total_score is not None
    sampling = result.dimensions["sitemap_sampling"]
    assert sampling["child_chosen"] == "https://chewy.example.com/sitemap-c.xml"
    assert sampling["candidates_found"] == 2
    # Root rate-limiting shows up as Agent Access evidence, not a run block.
    agent_access_evidence = " ".join(result.dimensions["agent_access"]["evidence"])
    assert "store root rate-limited our reader" in agent_access_evidence


def test_chewy_replay_without_catalog_child_is_no_product_pages_found_not_blocked(monkeypatch):
    """S2: when the real catalog child doesn't exist at all (only
    decoys), the sampler genuinely finds nothing — this must NEVER be
    worded as the site blocking us."""
    pages = _chewy_pages(index_xml=CHEWY_INDEX_NO_CATALOG)
    monkeypatch.setattr(httpx.Client, "get", _serve_with_root_429(pages))

    result = engine.run_scan("https://chewy.example.com")

    assert result.status == "failed"
    assert result.total_score is None
    assert result.dimensions["degraded_reason"] == "no_product_pages_found"
    assert result.dimensions["degraded_banner_facts"]["sitemaps_read"] >= 1
    # agent_access is scored for real even on a degraded run (S4) — the
    # synthetic "couldn't locate product pages" reason lives on the
    # OTHER crawl-derived dimensions, which genuinely have nothing to
    # go on without product page content.
    evidence = result.dimensions["catalog_context"]["evidence"][0]
    assert "couldn't locate product pages" in evidence
    assert "our reader's limitation" in evidence
    # Never a site-blame wording for this state.
    assert "blocked" not in evidence.lower()
    assert "refused" not in evidence.lower()


# ─── S1.b: gzip sitemap support ─────────────────────────────────────────

def test_gzip_sitemap_child_parses_and_contributes_products(monkeypatch):
    gz_body = gzip.compress(CHEWY_CATALOG_CHILD.encode("utf-8"))
    index_xml = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://chewy.example.com/sitemap-c.xml.gz</loc></sitemap>
</sitemapindex>"""

    def fake_get(self, url, headers=None):
        if url == "https://chewy.example.com":
            return httpx.Response(200, text=HOMEPAGE_HTML, request=httpx.Request("GET", url))
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=ROBOTS_TXT.replace("sitemap.xml", "sitemap.xml"), request=httpx.Request("GET", url))
        if url.endswith("/sitemap.xml"):
            return httpx.Response(200, text=index_xml, request=httpx.Request("GET", url))
        if url.endswith("/sitemap-c.xml.gz"):
            return httpx.Response(200, content=gz_body, request=httpx.Request("GET", url))
        if url.endswith("/dp/dog-food-blue") or url.endswith("/dp/cat-litter-tidy"):
            return httpx.Response(200, text=CHEWY_PDP_HTML, request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = discover_pages("https://chewy.example.com", FetchBudget())

    assert "https://chewy.example.com/dp/dog-food-blue" in result.sitemap_urls
    assert result.sitemap_sampling["child_chosen"] == "https://chewy.example.com/sitemap-c.xml.gz"
    probed = result.sitemap_sampling["children_probed"]
    gz_entry = next(e for e in probed if e["url"].endswith(".gz"))
    assert "skipped" not in gz_entry
    assert gz_entry["product_count"] == 2


def test_corrupt_gzip_child_is_skipped_with_reason_sampling_continues(monkeypatch):
    """A corrupt .gz never crashes the scan and never silently vanishes
    — it's recorded with a reason, and sampling still finds the OTHER,
    genuinely-parseable child."""
    index_xml = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://chewy.example.com/sitemap-corrupt.xml.gz</loc></sitemap>
  <sitemap><loc>https://chewy.example.com/sitemap-c.xml</loc></sitemap>
</sitemapindex>"""

    def fake_get(self, url, headers=None):
        if url == "https://chewy.example.com":
            return httpx.Response(200, text=HOMEPAGE_HTML, request=httpx.Request("GET", url))
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=ROBOTS_TXT, request=httpx.Request("GET", url))
        if url.endswith("/sitemap.xml"):
            return httpx.Response(200, text=index_xml, request=httpx.Request("GET", url))
        if url.endswith("/sitemap-corrupt.xml.gz"):
            return httpx.Response(200, content=b"this is not valid gzip data at all", request=httpx.Request("GET", url))
        if url.endswith("/sitemap-c.xml"):
            return httpx.Response(200, text=CHEWY_CATALOG_CHILD, request=httpx.Request("GET", url))
        if url.endswith("/dp/dog-food-blue") or url.endswith("/dp/cat-litter-tidy"):
            return httpx.Response(200, text=CHEWY_PDP_HTML, request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = discover_pages("https://chewy.example.com", FetchBudget())

    assert result.sitemap_sampling["child_chosen"] == "https://chewy.example.com/sitemap-c.xml"
    probed = result.sitemap_sampling["children_probed"]
    corrupt_entry = next(e for e in probed if e["url"].endswith("corrupt.xml.gz"))
    assert "skipped" in corrupt_entry
    assert "gzip" in corrupt_entry["skipped"].lower()
    assert "https://chewy.example.com/dp/dog-food-blue" in result.sitemap_urls


# ─── S1.c: robots-disallow candidate exclusion ─────────────────────────

def test_robots_disallows_all_candidates_excludes_them_before_sampling(monkeypatch):
    robots_txt = "User-agent: *\nDisallow: /dp/\nSitemap: https://chewy.example.com/sitemap.xml\n"
    flat_sitemap = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://chewy.example.com/dp/dog-food-blue</loc></url>
  <url><loc>https://chewy.example.com/dp/cat-litter-tidy</loc></url>
</urlset>"""

    def fake_get(self, url, headers=None):
        if url == "https://chewy.example.com":
            return httpx.Response(429, text="", request=httpx.Request("GET", url))
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=robots_txt, request=httpx.Request("GET", url))
        if url.endswith("/sitemap.xml"):
            return httpx.Response(200, text=flat_sitemap, request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = engine.run_scan("https://chewy.example.com")

    # Zero candidates via robots exclusion, root also failed, and
    # nothing hostile happened on robots.txt/sitemap themselves (both
    # 200) -> honest "our limitation," never a site-blame.
    assert result.status == "failed"
    assert result.dimensions["degraded_reason"] == "no_product_pages_found"
    assert result.dimensions["sitemap_sampling"]["robots_excluded"] == 2

    discovery_result = discover_pages("https://chewy.example.com", FetchBudget())
    assert discovery_result.sitemap_sampling["robots_excluded"] == 2
    assert not [c for c in discovery_result.candidates if c.kind == "product"]


def test_robots_disallow_evidence_names_the_specific_finding(monkeypatch):
    """S1.c: the exclusion is its own honest finding on Agent Access —
    never conflated with 'rate-limited' wording."""
    robots_txt = "User-agent: *\nDisallow: /dp/\nSitemap: https://chewy.example.com/sitemap.xml\n"
    flat_sitemap = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://chewy.example.com/dp/dog-food-blue</loc></url>
</urlset>"""

    def fake_get(self, url, headers=None):
        if url == "https://chewy.example.com":
            return httpx.Response(200, text=HOMEPAGE_HTML, request=httpx.Request("GET", url))
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=robots_txt, request=httpx.Request("GET", url))
        if url.endswith("/sitemap.xml"):
            return httpx.Response(200, text=flat_sitemap, request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = engine.run_scan("https://chewy.example.com")

    assert result.status == "complete"  # homepage fetched fine
    evidence = " ".join(result.dimensions["agent_access"]["evidence"])
    assert "robots.txt disallows 1 candidate product page(s) to our reader" in evidence


# ─── S4: Sephora replay (uniform 403, incl. robots.txt) ────────────────

def test_sephora_replay_uniform_403_stands_as_blocked_with_robots_evidence(monkeypatch):
    def fake_get(self, url, headers=None):
        return httpx.Response(403, text="Forbidden", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = engine.run_scan("https://sephora.example.com")

    assert result.status == "blocked"
    assert result.total_score is None
    assert result.dimensions["degraded_reason"] == "blocked"
    facts = result.dimensions["degraded_banner_facts"]
    assert facts["refusal"] == "403"
    assert facts["robots_included"] is True
    assert facts["attempts"] > 0
    evidence = " ".join(result.dimensions["agent_access"]["evidence"])
    assert "robots.txt itself refused our identified reader (HTTP 403)" in evidence


# ─── Grep tests (S1.a single-sourcing; S3 retired wording) ─────────────

def test_product_url_patterns_is_single_sourced():
    """S1.a: PRODUCT_URL_PATTERNS must be defined exactly once across the
    pipeline scan package — discovery.py is the source of truth; scorer.py
    and anything else needing product-URL matching imports it from there
    rather than keeping a second, driftable copy."""
    scan_dir = Path(__file__).resolve().parents[2] / "scan"
    definitions = []
    for py_file in scan_dir.glob("*.py"):
        text = py_file.read_text()
        for line in text.splitlines():
            if re.match(r"^PRODUCT_URL_PATTERNS\s*=", line):
                definitions.append((py_file.name, line))
    assert definitions == [("discovery.py", definitions[0][1])], (
        f"PRODUCT_URL_PATTERNS must be defined exactly once, in discovery.py; found: {definitions}"
    )


def test_will_hit_the_same_wall_phrase_is_gone_from_pipeline_source():
    """S3: the retired generalization sentence must not linger anywhere in
    the pipeline package (frontend coverage lives in
    LiteFullReport.test.jsx's COMPONENT_SRC grep test)."""
    scan_dir = Path(__file__).resolve().parents[2] / "scan"
    for py_file in scan_dir.glob("*.py"):
        assert "will hit the same wall" not in py_file.read_text(), py_file
