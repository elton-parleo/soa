"""
A sampled "product page" must actually be a product page.

Walmart's stored audit (#127) scored catalog 0 with exactly one product
page fetched: https://www.walmart.com/cp/pd/9881824 — a CATEGORY page
that matched discovery's /pd/ URL pattern. Every PDP-dependent scorer
read it, found no Product markup, and reported "checked, nothing found"
about a page that was never a product page. There were 50,000 real /ip/
URLs behind that same sitemap.

These tests hold both halves: the false positive is re-kinded and
recorded (never silently counted as a read product page), and the run
falls forward to the next ranked candidate rather than stopping at it.
No real network — httpx.Client.get is mocked per URL.
"""
import socket

import httpx
import pytest

from scan import discovery, engine, fetcher

ORIGIN = "https://big-box.example.com"

ROBOTS_TXT = f"User-agent: *\nAllow: /\nSitemap: {ORIGIN}/sitemap.xml\n"

# Carries a cart link so site_typing sees positive commerce evidence —
# this is a store whose PDP sampling went wrong, not a brand site.
HOMEPAGE_HTML = (
    "<html><body><h1>Big Box</h1><nav><a href='/cart'>Cart</a></nav>"
    "<p>Plenty of real homepage copy here so this "
    "clears the short-body heuristic like any genuine homepage would, with "
    "navigation and footer text and everything else a storefront carries.</p>"
    "</body></html>"
)

# A real PDP: Product JSON-LD with an offer, exactly what
# discovery._looks_like_product_page verifies.
PDP_HTML = """<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product", "name": "Blue Widget",
 "offers": {"@type": "Offer", "price": "19.99", "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"}}
</script>
</head><body><h1>Blue Widget</h1></body></html>
"""

# The Walmart shape: a category page whose URL matched a product
# pattern. Real page, real length, no Product markup and no price.
CATEGORY_HTML = (
    "<html><head><title>Widgets</title></head><body>"
    "<h1>Shop all widgets</h1>"
    "<p>Browse our full range of widgets by size, color and material. "
    "Filter by brand, sort by popularity, and find the widget that fits "
    "your project. Free shipping on qualifying orders.</p>"
    "</body></html>"
)


def _sitemap(*paths):
    locs = "".join(f"<url><loc>{ORIGIN}{p}</loc></url>" for p in paths)
    return f"<?xml version='1.0' encoding='UTF-8'?><urlset>{locs}</urlset>"


@pytest.fixture(autouse=True)
def reset_politeness_state(monkeypatch):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    fetcher._last_fetch_at.clear()
    fetcher._domain_seen.clear()
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    yield
    fetcher._last_fetch_at.clear()
    fetcher._domain_seen.clear()


def _serve(monkeypatch, pages: dict):
    """pages maps a path (or the bare origin) to its HTML; anything not
    listed is a 404. Every requested URL is recorded."""
    requested = []

    def fake_get(self, url, headers=None, **kw):
        requested.append(url)
        key = url[len(ORIGIN):] or "/"
        if url == ORIGIN:
            key = "/"
        body = pages.get(key)
        if body is None:
            return httpx.Response(404, text="", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    return requested


def _rejected_rows(result):
    return [e for e in result.pages_fetched if e.get("product_candidate_rejected")]


# ─── the false positive is caught ────────────────────────────────────────

def test_a_category_page_matching_a_product_pattern_is_rejected_not_scored(monkeypatch):
    """The exact Walmart shape: candidate 1 is a category page, candidate
    2 is a real PDP. One product page is scored; the false positive is
    recorded as a rejection, not as a product page we read and found
    nothing in."""
    _serve(monkeypatch, {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": _sitemap("/pd/9881824", "/ip/blue-widget/12345"),
        "/": HOMEPAGE_HTML,
        "/pd/9881824": CATEGORY_HTML,
        "/ip/blue-widget/12345": PDP_HTML,
    })

    result = engine.run_scan(ORIGIN)

    assert result.status == "complete"
    rejected = _rejected_rows(result)
    assert [e["url"] for e in rejected] == [f"{ORIGIN}/pd/9881824"]
    assert "not a product page" in rejected[0]["product_candidate_rejected"]
    # The real PDP still scored: catalog_context read a product page.
    assert result.dimensions["catalog_context"]["coverage"] != "blocked"
    assert result.dimensions["discovery_trace"]["product_pages_fetched"] == 1


def test_the_rejected_page_is_still_recorded_as_fetched(monkeypatch):
    """It is a rejection, not a disappearance — the fetch happened, cost
    budget, and stays in the record with its own reason."""
    _serve(monkeypatch, {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": _sitemap("/pd/9881824", "/ip/blue-widget/12345"),
        "/": HOMEPAGE_HTML,
        "/pd/9881824": CATEGORY_HTML,
        "/ip/blue-widget/12345": PDP_HTML,
    })

    result = engine.run_scan(ORIGIN)

    row = next(e for e in result.pages_fetched if e["url"] == f"{ORIGIN}/pd/9881824")
    assert row["status"] == "fetched"
    assert row["http_status"] == 200


def test_a_real_pdp_is_never_rejected(monkeypatch):
    _serve(monkeypatch, {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": _sitemap("/ip/blue-widget/12345", "/ip/red-widget/67890"),
        "/": HOMEPAGE_HTML,
        "/ip/blue-widget/12345": PDP_HTML,
        "/ip/red-widget/67890": PDP_HTML,
    })

    result = engine.run_scan(ORIGIN)

    assert _rejected_rows(result) == []
    assert result.dimensions["discovery_trace"]["product_pages_fetched"] == 2


def test_a_refused_product_page_is_not_a_rejection(monkeypatch):
    """Only a page that FETCHED and turned out not to be a product page
    is a rejection. A refusal is still, as far as anyone knows, a real
    product page — and the refused/unreadable classifications
    downstream depend on it staying one."""
    def fake_get(self, url, headers=None, **kw):
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=ROBOTS_TXT, request=httpx.Request("GET", url))
        if url.endswith("/sitemap.xml"):
            return httpx.Response(200, text=_sitemap("/ip/blue-widget/12345"), request=httpx.Request("GET", url))
        if url == ORIGIN:
            return httpx.Response(200, text=HOMEPAGE_HTML, request=httpx.Request("GET", url))
        if "/ip/" in url:
            return httpx.Response(403, text="Access Denied " * 20, request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = engine.run_scan(ORIGIN)

    assert _rejected_rows(result) == []
    assert result.dimensions["discovery_outcome"]["code"] == "product_pages_refused"


# ─── falling forward to the next candidate ───────────────────────────────

def test_a_rejection_falls_forward_to_the_next_ranked_candidate(monkeypatch):
    """Walmart had 50,000 real /ip/ URLs behind the same sitemap —
    stopping at the first false positive was never the honest answer."""
    requested = _serve(monkeypatch, {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": _sitemap("/pd/9881824", "/pd/9881825", "/ip/blue-widget/12345"),
        "/": HOMEPAGE_HTML,
        "/pd/9881824": CATEGORY_HTML,
        "/pd/9881825": CATEGORY_HTML,
        "/ip/blue-widget/12345": PDP_HTML,
    })

    result = engine.run_scan(ORIGIN)

    assert f"{ORIGIN}/ip/blue-widget/12345" in requested
    assert len(_rejected_rows(result)) == 2
    assert result.dimensions["discovery_trace"]["product_pages_fetched"] == 1


def test_no_replacement_is_fetched_when_nothing_was_rejected(monkeypatch):
    """The replacement path is engaged by a rejection and nothing else —
    a run that simply found one product page spends nothing here."""
    requested = _serve(monkeypatch, {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": _sitemap("/ip/blue-widget/12345", "/ip/red-widget/67890", "/ip/green-widget/99999"),
        "/": HOMEPAGE_HTML,
        "/ip/blue-widget/12345": PDP_HTML,
        "/ip/red-widget/67890": PDP_HTML,
        "/ip/green-widget/99999": PDP_HTML,
    })

    engine.run_scan(ORIGIN)

    assert f"{ORIGIN}/ip/green-widget/99999" not in requested


def test_replacement_fetches_are_bounded(monkeypatch):
    """A run that keeps knocking is a run spending budget to learn
    nothing — same discipline as the walled short-circuit."""
    paths = [f"/pd/{i}" for i in range(8)]
    pages = {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": _sitemap(*paths),
        "/": HOMEPAGE_HTML,
    }
    pages.update({p: CATEGORY_HTML for p in paths})
    requested = _serve(monkeypatch, pages)

    engine.run_scan(ORIGIN)

    product_requests = [u for u in requested if "/pd/" in u]
    assert len(product_requests) == discovery.MAX_PRODUCT_PAGES + engine.MAX_PRODUCT_REPLACEMENT_FETCHES


# ─── all rejected: the existing no-product-pages path, unchanged ─────────

def test_every_candidate_rejected_is_classified_honestly(monkeypatch):
    """"couldn't read any of them (network error or timeout)" would be
    a false sentence about pages that returned 200 and parsed fine —
    they just weren't product pages. This is the Walmart live run's own
    shape: four /ip/ candidates opened, none carrying product markup."""
    _serve(monkeypatch, {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": _sitemap("/pd/9881824", "/pd/9881825"),
        "/": HOMEPAGE_HTML,
        "/pd/9881824": CATEGORY_HTML,
        "/pd/9881825": CATEGORY_HTML,
    })

    result = engine.run_scan(ORIGIN)

    outcome = result.dimensions["discovery_outcome"]
    assert outcome["code"] == "product_candidates_not_products"
    assert outcome["product_candidates_rejected"] == 2
    assert "without product markup" in outcome["summary"]
    # Never a refusal and never a network failure — both would be wrong.
    assert "refused" not in outcome["summary"]
    assert "timeout" not in outcome["summary"]


def test_a_run_that_read_a_real_pdp_is_never_described_by_its_rejections(monkeypatch):
    _serve(monkeypatch, {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": _sitemap("/pd/9881824", "/ip/blue-widget/12345"),
        "/": HOMEPAGE_HTML,
        "/pd/9881824": CATEGORY_HTML,
        "/ip/blue-widget/12345": PDP_HTML,
    })

    result = engine.run_scan(ORIGIN)

    outcome = result.dimensions["discovery_outcome"]
    assert outcome["code"] == "product_pages_read"
    assert outcome["product_candidates_rejected"] == 1


def test_the_rejection_count_is_zero_on_an_ordinary_run(monkeypatch):
    """Always present, never absent — same discipline as every other
    key on this record."""
    _serve(monkeypatch, {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": _sitemap("/ip/blue-widget/12345"),
        "/": HOMEPAGE_HTML,
        "/ip/blue-widget/12345": PDP_HTML,
    })

    result = engine.run_scan(ORIGIN)
    assert result.dimensions["discovery_outcome"]["product_candidates_rejected"] == 0


def test_every_candidate_rejected_lands_on_the_no_product_pages_path(monkeypatch):
    _serve(monkeypatch, {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": _sitemap("/pd/9881824", "/pd/9881825"),
        "/": HOMEPAGE_HTML,
        "/pd/9881824": CATEGORY_HTML,
        "/pd/9881825": CATEGORY_HTML,
    })

    result = engine.run_scan(ORIGIN)

    # Homepage read fine, so the run is still 'complete' — what changed
    # is that the PDP-dependent dimensions say "not measured" instead of
    # a scored zero derived from a category page.
    assert result.status == "complete"
    assert result.dimensions["discovery_trace"]["product_pages_fetched"] == 0
    assert result.dimensions["catalog_context"]["coverage"] == "blocked"
    assert len(_rejected_rows(result)) == 2


# ─── the fetch probe still gets a product URL to ask about ───────────────

def test_a_rejected_candidate_is_still_what_the_probe_asks_chatgpt_to_open(monkeypatch):
    """A rejected page is a real product URL off the store's own
    catalog that our reader was served without product details. Asking
    ChatGPT to open that exact URL is the whole point of the probe on
    such a run — dropping to the homepage would throw the comparison
    away."""
    _serve(monkeypatch, {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": _sitemap("/pd/9881824"),
        "/": HOMEPAGE_HTML,
        "/pd/9881824": CATEGORY_HTML,
    })

    result = engine.run_scan(ORIGIN)

    assert result.fetch_probe_url == f"{ORIGIN}/pd/9881824"
    assert result.fetch_probe_kind == "product_page"


def test_a_real_pdp_still_outranks_a_rejected_one(monkeypatch):
    _serve(monkeypatch, {
        "/robots.txt": ROBOTS_TXT,
        "/sitemap.xml": _sitemap("/pd/9881824", "/ip/blue-widget/12345"),
        "/": HOMEPAGE_HTML,
        "/pd/9881824": CATEGORY_HTML,
        "/ip/blue-widget/12345": PDP_HTML,
    })

    result = engine.run_scan(ORIGIN)

    assert result.fetch_probe_url == f"{ORIGIN}/ip/blue-widget/12345"
