"""
Engine-level tests for Part 1 (M1-M5) and Part 2 (P1) — the Agent
Access Matrix serialized onto a real run_scan() result (complete and
degraded), M5 divergence evidence reaching dimensions["agent_access"],
and the fetch-probe URL ladder (fetched PDP -> attempted PDP -> store
root).
"""
import socket

import httpx
import pytest

from scan import engine, fetcher

ORIGIN = "https://acme.example.com"

# GPTBot fully disallowed while '*' allows everything — the M5
# divergence case, exercised end to end through run_scan().
ROBOTS_TXT_DIVERGENT = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
ROBOTS_TXT_PLAIN = "User-agent: *\nAllow: /\n"

FLAT_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://acme.example.com/products/classic-tee</loc></url>
  <url><loc>https://acme.example.com/products/wool-hat</loc></url>
</urlset>"""

EMPTY_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
</urlset>"""

PDP_HTML = """
<html><head><title>Classic Tee - Acme</title>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product", "name": "Classic Tee",
 "offers": {"@type": "Offer", "price": "29.99", "priceCurrency": "USD", "availability": "https://schema.org/InStock"}}
</script></head>
<body><nav><a href="/">Home</a></nav><h1>Classic Tee</h1></body></html>
"""

HOMEPAGE_HTML = (
    "<html><body><nav><a href='/rewards'>Rewards</a></nav>"
    "<p>Welcome to the store — plenty of real homepage copy here so this "
    "clears the short-body heuristic like any genuine homepage would.</p>"
    "</body></html>"
)


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


# ─── M4: matrix serialization ────────────────────────────────────────────

def test_matrix_serialized_on_complete_run_with_m5_divergence(monkeypatch):
    pages = {
        "/robots.txt": (200, ROBOTS_TXT_DIVERGENT),
        "/sitemap.xml": (200, FLAT_SITEMAP),
        "/products/classic-tee": (200, PDP_HTML),
        "/products/wool-hat": (200, PDP_HTML),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan(ORIGIN)

    assert result.status == "complete"
    matrix = result.dimensions["agent_access_matrix"]
    assert len(matrix) == 6
    gptbot = next(r for r in matrix if r["agent"] == "GPTBot")
    assert gptbot["root"] == "blocked"
    assert gptbot["product_pages"] == "blocked"

    evidence = " ".join(result.dimensions["agent_access"]["evidence"])
    assert "robots.txt blocks GPTBot specifically" in evidence


def test_matrix_serialized_on_degraded_run_robots_unreadable(monkeypatch):
    """Sephora shape: uniform 403 including robots.txt itself — matrix
    must render 'unknown' per agent, never a guess, and still be
    present on a non-complete run (S4's real-scored agent_access)."""
    def fake_get(self, url, headers=None):
        return httpx.Response(403, text="Forbidden", request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = engine.run_scan(ORIGIN)

    assert result.status == "blocked"
    matrix = result.dimensions["agent_access_matrix"]
    assert len(matrix) == 6
    assert all(r["root"] == "unknown" and r["product_pages"] == "unknown" for r in matrix)
    evidence = " ".join(result.dimensions["agent_access"]["evidence"])
    assert "robots.txt itself refused our identified reader" in evidence


def test_no_divergence_evidence_when_robots_uniform(monkeypatch):
    pages = {
        "/robots.txt": (200, ROBOTS_TXT_PLAIN),
        "/sitemap.xml": (200, FLAT_SITEMAP),
        "/products/classic-tee": (200, PDP_HTML),
        "/products/wool-hat": (200, PDP_HTML),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan(ORIGIN)

    evidence = " ".join(result.dimensions["agent_access"]["evidence"])
    assert "specifically" not in evidence


# ─── P1: fetch_probe_url ladder ──────────────────────────────────────────

def test_fetch_probe_url_is_the_fetched_pdp(monkeypatch):
    pages = {
        "/robots.txt": (200, ROBOTS_TXT_PLAIN),
        "/sitemap.xml": (200, FLAT_SITEMAP),
        "/products/classic-tee": (200, PDP_HTML),
        "/products/wool-hat": (200, PDP_HTML),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan(ORIGIN)

    assert result.status == "complete"
    assert result.fetch_probe_url == "https://acme.example.com/products/classic-tee"
    assert result.fetch_probe_kind == "product_page"


def test_fetch_probe_url_falls_back_to_attempted_pdp_when_pdps_fail(monkeypatch):
    """Homepage fetches fine (run stays 'complete' per _derive_status),
    but every sampled PDP terminally fails — the ladder's second rung
    (first ATTEMPTED PDP) must still pick a real URL, not skip to the
    store root."""
    pages = {
        "/robots.txt": (200, ROBOTS_TXT_PLAIN),
        "/sitemap.xml": (200, FLAT_SITEMAP),
        "/products/classic-tee": (500, "server error"),
        "/products/wool-hat": (500, "server error"),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan(ORIGIN)

    assert result.status == "complete"  # homepage fetched fine
    assert result.fetch_probe_url == "https://acme.example.com/products/classic-tee"
    assert result.fetch_probe_kind == "product_page"  # attempted, not fetched — still a real PDP


def test_fetch_probe_url_falls_back_to_store_root_when_no_pdp_attempted(monkeypatch):
    pages = {
        "/robots.txt": (200, ROBOTS_TXT_PLAIN),
        "/sitemap.xml": (200, EMPTY_SITEMAP),
    }
    monkeypatch.setattr(httpx.Client, "get", _serve(pages))

    result = engine.run_scan(ORIGIN)

    assert result.status == "complete"  # homepage fetched fine
    assert result.fetch_probe_url == ORIGIN
    assert result.fetch_probe_kind == "store_root"


# ─── Scoring parity: the matrix is evidence-only, never a score input ───

def test_scoring_parity_divergence_evidence_never_changes_score():
    """M5's divergence lines are appended to F1's evidence list only —
    score_f1_agent_access/score_agent_access must return byte-identical
    score/max whether or not any divergence_evidence is passed in."""
    from scan import scorer
    from scan.discovery import DiscoveryResult
    from scan.fetcher import FetchResult

    discovery = DiscoveryResult(
        robots_fetch=FetchResult(url="https://acme.example.com/robots.txt", status="fetched", html="User-agent: *\nAllow: /\n"),
        robot_parser=None,
        sitemap_urls=["https://acme.example.com/products/a"],
    )
    pages = []

    plain = scorer.score_f1_agent_access(discovery, pages)
    with_divergence = scorer.score_f1_agent_access(
        discovery, pages, divergence_evidence=["robots.txt blocks GPTBot specifically — the general '*' rule allows it"],
    )

    assert plain.score == with_divergence.score
    assert plain.max == with_divergence.max
    divergence_line = "robots.txt blocks GPTBot specifically — the general '*' rule allows it"
    assert divergence_line in with_divergence.evidence
    assert divergence_line not in plain.evidence
    # Removing the one appended line leaves the evidence otherwise identical.
    assert [e for e in with_divergence.evidence if e != divergence_line] == plain.evidence

    plain_v3 = scorer.score_agent_access(discovery, pages)
    with_divergence_v3 = scorer.score_agent_access(discovery, pages, divergence_evidence=["x"])
    assert plain_v3.score == with_divergence_v3.score
    assert plain_v3.max == with_divergence_v3.max


def test_scoring_parity_total_score_identical_regardless_of_matrix_divergence(monkeypatch):
    """Two otherwise-identical runs, one where a named agent's group
    diverges from '*' (GPTBot fully disallowed) and one where robots.txt
    is uniform — total_score and every non-agent_access dimension score
    must be byte-identical; only agent_access's evidence list differs."""
    base_pages = {
        "/sitemap.xml": (200, FLAT_SITEMAP),
        "/products/classic-tee": (200, PDP_HTML),
        "/products/wool-hat": (200, PDP_HTML),
    }

    uniform_pages = dict(base_pages, **{"/robots.txt": (200, ROBOTS_TXT_PLAIN)})
    monkeypatch.setattr(httpx.Client, "get", _serve(uniform_pages))
    uniform_result = engine.run_scan(ORIGIN)

    divergent_pages = dict(base_pages, **{"/robots.txt": (200, ROBOTS_TXT_DIVERGENT)})
    monkeypatch.setattr(httpx.Client, "get", _serve(divergent_pages))
    divergent_result = engine.run_scan(ORIGIN)

    assert uniform_result.total_score == divergent_result.total_score
    for code in ("catalog_context", "protocol_feed", "price_truth_seen", "member_value_seen", "deal_citability_seen", "value_protocols_seen"):
        assert uniform_result.dimensions[code]["score"] == divergent_result.dimensions[code]["score"]
    # agent_access itself: score/max still byte-identical (evidence-only diff)
    assert uniform_result.dimensions["agent_access"]["score"] == divergent_result.dimensions["agent_access"]["score"]
    assert uniform_result.dimensions["agent_access"]["max"] == divergent_result.dimensions["agent_access"]["max"]
    assert divergent_result.dimensions["agent_access"]["evidence"] != uniform_result.dimensions["agent_access"]["evidence"]


def test_scoring_parity_fetch_probe_never_reaches_run_scan_at_all():
    """The fetch probe runs entirely outside run_scan() (worker.py, after
    the scan row's dimensions/total_score are already written) — a
    ScanResult has no field a probe outcome could even influence besides
    fetch_probe_url itself."""
    from dataclasses import fields
    from scan.engine import ScanResult
    field_names = {f.name for f in fields(ScanResult)}
    assert "fetch_probe_url" in field_names
    assert "fetch_probe_kind" in field_names
    other_probe_fields = field_names - {"fetch_probe_url", "fetch_probe_kind"}
    assert not any("probe" in name for name in other_probe_fields)
