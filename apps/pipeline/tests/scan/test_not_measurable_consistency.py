"""
Tests for N1 (not-measurable plumbing consistency stage): per-dimension
measurability derives from ITS OWN required inputs, not a per-run
blanket. Value Protocols depends only on discovery-surface fetches
(the MCP well-known page) — never sampled PDPs — so it is ALWAYS
real-scored, even on a degraded run, while the genuinely PDP-dependent
dimensions (catalog_context, price_truth_seen, member_value_seen,
deal_citability_seen) still fall back to the honest NOT MEASURABLE
entry when a run never got any product pages.
"""
import socket

import httpx
import pytest

from scan import engine, fetcher

ORIGIN = "https://acme.example.com"

ROBOTS_TXT_PLAIN = "User-agent: *\nAllow: /\n"

EMPTY_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
</urlset>"""

HOMEPAGE_HTML = (
    "<html><body><nav><a href='/rewards'>Rewards</a></nav>"
    "<p>Welcome to the store — plenty of real homepage copy here so this "
    "clears the short-body heuristic like any genuine homepage would.</p>"
    "</body></html>"
)

PROTOCOL_MANIFEST = """{"capabilities": ["dev.ucp.shopping.discount"], "specVersion": "2025-01"}"""

_PDP_DEPENDENT_CODES = ("catalog_context", "price_truth_seen", "member_value_seen", "deal_citability_seen")


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


def _serve(pages: dict, root_status=200, root_body=HOMEPAGE_HTML):
    def fake_get(self, url, headers=None):
        if url == ORIGIN or url == ORIGIN + "/":
            return httpx.Response(root_status, text=root_body, request=httpx.Request("GET", url))
        for path, (status, body) in pages.items():
            if url.endswith(path):
                return httpx.Response(status, text=body, request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))
    return fake_get


def _assert_no_row_mixes_score_and_couldnt_evaluate(dimensions: dict):
    """Invariant (N1 tests): no dimension row may combine a numeric
    score with couldn't-evaluate evidence, and no coverage='blocked'
    row may carry a nonzero score."""
    for code, d in dimensions.items():
        if not isinstance(d, dict) or "coverage" not in d:
            continue  # skip sibling keys like scorer_version/sitemap_sampling
        evidence_text = " ".join(d.get("evidence") or [])
        couldnt_evaluate = "couldn't be evaluated" in evidence_text or "could not be evaluated" in evidence_text
        if d["coverage"] == "blocked":
            assert d["score"] == 0.0, f"{code}: blocked row has a nonzero score"
        if couldnt_evaluate:
            assert d["score"] == 0.0, f"{code}: couldn't-evaluate evidence paired with a nonzero score"
            assert d["coverage"] in ("blocked", "partial"), f"{code}: couldn't-evaluate evidence but coverage={d['coverage']!r}"


# ─── N1: VP real-scored when PDP sampling is starved ─────────────────────

def test_vp_scored_real_with_protocol_evidence_when_pdp_sampling_starved(monkeypatch):
    """VP-inputs-ok/pages-starved fixture (N1 test spec): robots.txt,
    sitemap, and the MCP well-known page all fetch fine, but the
    sitemap is genuinely empty — no product pages exist to sample. VP
    must score for real (0/7, honest protocol evidence); the four
    PDP-dependent dimensions fall back to NOT MEASURABLE with sampling
    evidence."""
    pages = {
        "/robots.txt": (200, ROBOTS_TXT_PLAIN),
        "/sitemap.xml": (200, EMPTY_SITEMAP),
        "/.well-known/mcp.json": (404, ""),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages, root_status=429))

    result = engine.run_scan(ORIGIN)

    assert result.status in ("blocked", "failed")
    assert result.total_score is None

    vp = result.dimensions["value_protocols_seen"]
    assert vp["coverage"] == "full"
    assert vp["score"] == 0.0
    assert vp["evidence"] == ["no protocol profile found"]

    for code in _PDP_DEPENDENT_CODES:
        d = result.dimensions[code]
        assert d["coverage"] == "blocked", code
        assert d["score"] == 0.0, code
        assert "could" in " ".join(d["evidence"]).lower()  # sampling-honest wording, not protocol wording

    _assert_no_row_mixes_score_and_couldnt_evaluate(result.dimensions)


def test_vp_declares_a_real_protocol_when_manifest_present_even_when_pdp_sampling_starved(monkeypatch):
    """Same starved-PDP shape, but the MCP well-known page actually
    declares a capability — VP must score the real, non-zero finding,
    proving this isn't just a hardcoded 0/7."""
    pages = {
        "/robots.txt": (200, ROBOTS_TXT_PLAIN),
        "/sitemap.xml": (200, EMPTY_SITEMAP),
        "/.well-known/mcp.json": (200, PROTOCOL_MANIFEST),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages, root_status=429))

    result = engine.run_scan(ORIGIN)

    assert result.status in ("blocked", "failed")
    vp = result.dimensions["value_protocols_seen"]
    assert vp["coverage"] == "full"
    assert vp["score"] > 0.0
    assert any("dev.ucp.shopping.discount" in e for e in vp["evidence"])


def test_vp_still_scores_real_even_when_its_own_mcp_fetch_also_fails(monkeypatch):
    """VP-inputs-failed fixture (N1 test spec): a uniform-403 run where
    EVERYTHING, including the MCP well-known page itself, fails. VP's
    own scorer (apps/pipeline/scan/scorer.py::score_value_protocols)
    treats "fetch attempted but failed" identically to "fetch attempted,
    manifest absent" — an agent-checkout protocol declaration either
    exists or it doesn't, on every site type (V1's own design, Stage
    25) — so there is no reachable state where VP is genuinely
    NOT MEASURABLE; it always produces the same honest 0/7 "no protocol
    profile found" finding. This locks in that this is the real,
    correct behavior of the current scorer (not something this stage
    changes) — never blocked, never a bare zero mistaken for an
    unevaluated dimension."""
    def fake_get(self, url, headers=None):
        return httpx.Response(403, text="Forbidden", request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = engine.run_scan(ORIGIN)

    assert result.status == "blocked"
    vp = result.dimensions["value_protocols_seen"]
    assert vp["coverage"] == "full"
    assert vp["score"] == 0.0
    assert vp["evidence"] == ["no protocol profile found"]

    for code in _PDP_DEPENDENT_CODES:
        assert result.dimensions[code]["coverage"] == "blocked", code

    _assert_no_row_mixes_score_and_couldnt_evaluate(result.dimensions)


# ─── Invariant sweep across representative fixtures ──────────────────────

def test_invariant_holds_on_a_normal_complete_run_too(monkeypatch):
    """Sanity check: the invariant helper itself doesn't false-positive
    on an ordinary, fully-scored run."""
    pdp_html = """
    <html><head><title>Classic Tee</title>
    <script type="application/ld+json">
    {"@context": "https://schema.org", "@type": "Product", "name": "Classic Tee",
     "offers": {"@type": "Offer", "price": "29.99", "priceCurrency": "USD", "availability": "https://schema.org/InStock"}}
    </script></head><body><nav><a href="/">Home</a></nav></body></html>
    """
    flat_sitemap = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://acme.example.com/products/classic-tee</loc></url>
    </urlset>"""
    pages = {
        "/robots.txt": (200, ROBOTS_TXT_PLAIN),
        "/sitemap.xml": (200, flat_sitemap),
        "/products/classic-tee": (200, pdp_html),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan(ORIGIN)

    assert result.status == "complete"
    _assert_no_row_mixes_score_and_couldnt_evaluate(result.dimensions)
