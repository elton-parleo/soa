"""
Fetcher hardening: discovery stops before it starts when robots.txt AND
the store root both refuse us.

On 5 of the 13 blocked runs in the export, robots.txt and the homepage
both returned 403 — and so did every one of the 6-7 follow-up probes
(sitemap.xml, sitemap_products_1.xml, products.json twice, llms.txt,
.well-known/mcp.json), with the same body each time. Nothing was learned
from any of them.

BOTH signals are required, and these tests hold that line: robots 200
with a refused homepage is the Warby Parker shape, where robots.txt,
llms.txt and the MCP manifest were all served while HTML was refused,
and those probes are exactly the ones worth keeping.

httpx.Client.get is mocked and every requested URL is counted, so "no
further HTTP requests" is asserted directly rather than inferred.
"""
import socket

import httpx
import pytest

from scan import discovery, engine, fetcher
from scan.fetcher import FetchBudget, FetchResult

ORIGIN = "https://big-box.example.com"

ROBOTS_TXT_PLAIN = "User-agent: *\nAllow: /\nSitemap: https://big-box.example.com/sitemap.xml\n"
HOMEPAGE_HTML = (
    "<html><body><nav><a href='/rewards'>Rewards</a></nav>"
    "<p>Welcome to the store — plenty of real homepage copy here so this "
    "clears the short-body heuristic like any genuine homepage would.</p>"
    "</body></html>"
)
# The shape the export actually showed: a small, identical Access Denied
# body returned for every URL on the origin.
ACCESS_DENIED_BODY = (
    "<html><head><title>Access Denied</title></head><body>"
    "You don't have permission to access this resource on this server. "
    "Reference #18.abcd1234.0000000000.0000000a " * 3
    + "</body></html>"
)


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


def _counting_server(monkeypatch, robots, *, other=(403, ACCESS_DENIED_BODY)):
    """Serves `robots` for /robots.txt and `other` for everything else,
    recording every URL requested."""
    requested = []

    def fake_get(self, url, headers=None, **kw):
        requested.append(url)
        status, body = robots if url.endswith("/robots.txt") else other
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    return requested


def _homepage_fetch(http_status, *, status="blocked"):
    return FetchResult(
        url=ORIGIN, status=status, http_status=http_status,
        error=f"HTTP {http_status}", bytes=370,
    )


# ─── the short-circuit fires ─────────────────────────────────────────────

@pytest.mark.parametrize("refusal", [403, 429])
def test_robots_and_homepage_both_refused_stops_after_robots(monkeypatch, refusal):
    requested = _counting_server(
        monkeypatch, (refusal, ACCESS_DENIED_BODY), other=(refusal, ACCESS_DENIED_BODY),
    )

    result = discovery.discover_pages(
        ORIGIN, FetchBudget(), homepage_fetch=_homepage_fetch(refusal),
    )

    # One URL — robots.txt itself, whose own retry ladder may knock more
    # than once. No SECOND URL is ever requested, which is the claim.
    assert set(requested) == {f"{ORIGIN}/robots.txt"}
    short_circuit = result.sitemap_sampling["short_circuit"]
    assert short_circuit["reason"] == "robots_and_homepage_refused"
    assert short_circuit["robots_http_status"] == refusal
    assert short_circuit["homepage_http_status"] == refusal
    assert short_circuit["skipped"] == [
        "sitemap", "platform_endpoint", "llm_assisted",
        "llms_txt", "mcp_well_known", "product_pages",
    ]


def test_no_sitemap_products_json_llms_txt_or_mcp_url_is_ever_requested(monkeypatch):
    requested = _counting_server(monkeypatch, (403, ACCESS_DENIED_BODY))

    discovery.discover_pages(ORIGIN, FetchBudget(), homepage_fetch=_homepage_fetch(403))

    joined = " ".join(requested)
    for path in ("sitemap", "products.json", "llms.txt", "mcp.json", ".well-known"):
        assert path not in joined, path


def test_the_short_circuit_tier_is_recorded_in_the_trace(monkeypatch):
    _counting_server(monkeypatch, (403, ACCESS_DENIED_BODY))

    result = discovery.discover_pages(ORIGIN, FetchBudget(), homepage_fetch=_homepage_fetch(403))

    assert {"tier": "short_circuit", "candidates_found": 0} in result.sitemap_sampling["tiers_attempted"]


def test_the_short_circuited_result_is_fully_shaped(monkeypatch):
    _counting_server(monkeypatch, (403, ACCESS_DENIED_BODY))
    homepage_fetch = _homepage_fetch(403)

    result = discovery.discover_pages(ORIGIN, FetchBudget(), homepage_fetch=homepage_fetch)

    assert [c.kind for c in result.candidates] == ["homepage"]
    assert result.candidates[0].url == ORIGIN
    assert result.homepage_fetch is homepage_fetch
    assert result.llms_txt_fetch is None
    assert result.mcp_well_known_fetch is None
    assert result.discovery_path == "none"
    assert result.sitemap_urls == []
    assert result.products_found == 0
    assert result.sitemap_index_entries == []
    assert result.reused_product_fetches == {}
    assert [fr.http_status for fr in result.all_fetches] == [403]


def test_the_content_budget_is_left_untouched(monkeypatch):
    """The whole point is not spending it — discovery draws robots.txt
    from its own budget and never reaches a content fetch."""
    _counting_server(monkeypatch, (403, ACCESS_DENIED_BODY))
    budget = FetchBudget()

    discovery.discover_pages(ORIGIN, budget, homepage_fetch=_homepage_fetch(403))

    assert budget.used == 0


def test_an_ordinary_run_records_short_circuit_as_none(monkeypatch):
    """The key is always present, so a reader never has to tell
    'not short-circuited' apart from 'written before this key existed'."""
    def fake_get(self, url, headers=None, **kw):
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=ROBOTS_TXT_PLAIN, request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = discovery.discover_pages(
        ORIGIN, FetchBudget(),
        homepage_fetch=FetchResult(url=ORIGIN, status="fetched", html=HOMEPAGE_HTML, http_status=200),
    )
    assert result.sitemap_sampling["short_circuit"] is None
    assert discovery.DiscoveryResult(robots_fetch=None, robot_parser=None).sitemap_sampling["short_circuit"] is None


# ─── both signals are required ───────────────────────────────────────────

def test_robots_200_with_a_refused_homepage_is_not_short_circuited(monkeypatch):
    """The Warby Parker shape: robots.txt, llms.txt and the MCP manifest
    were all served while HTML was refused. Those probes are worth
    keeping — this is the case the two-signal rule exists to protect."""
    requested = _counting_server(monkeypatch, (200, ROBOTS_TXT_PLAIN))

    result = discovery.discover_pages(ORIGIN, FetchBudget(), homepage_fetch=_homepage_fetch(403))

    assert result.sitemap_sampling["short_circuit"] is None
    joined = " ".join(requested)
    assert "/sitemap.xml" in joined
    assert "/llms.txt" in joined


def test_robots_403_with_a_fetched_homepage_is_not_short_circuited(monkeypatch):
    requested = _counting_server(monkeypatch, (403, ACCESS_DENIED_BODY), other=(404, ""))

    result = discovery.discover_pages(
        ORIGIN, FetchBudget(),
        homepage_fetch=FetchResult(url=ORIGIN, status="fetched", html=HOMEPAGE_HTML, http_status=200),
    )

    assert result.sitemap_sampling["short_circuit"] is None
    assert len(requested) > 1


def test_a_standalone_caller_passing_no_homepage_fetch_is_not_short_circuited(monkeypatch):
    """One signal is not two. A caller using discover_pages standalone
    has told us nothing about the store root."""
    requested = _counting_server(monkeypatch, (403, ACCESS_DENIED_BODY))

    result = discovery.discover_pages(ORIGIN, FetchBudget(), homepage_fetch=None)

    assert result.sitemap_sampling["short_circuit"] is None
    assert len(requested) > 1


def test_a_503_homepage_is_not_the_hard_refused_shape(monkeypatch):
    """Only 403/429 count — a 5xx store root is an outage, not a wall."""
    requested = _counting_server(monkeypatch, (403, ACCESS_DENIED_BODY), other=(404, ""))

    result = discovery.discover_pages(
        ORIGIN, FetchBudget(), homepage_fetch=_homepage_fetch(503, status="failed"),
    )

    assert result.sitemap_sampling["short_circuit"] is None
    assert len(requested) > 1


# ─── engine level: where a short-circuited run lands ─────────────────────

def _uniform_403(monkeypatch):
    requested = []

    def fake_get(self, url, headers=None, **kw):
        requested.append(url)
        return httpx.Response(403, text=ACCESS_DENIED_BODY, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    return requested


def test_a_uniformly_403_origin_still_lands_exactly_where_it_used_to(monkeypatch):
    requested = _uniform_403(monkeypatch)

    result = engine.run_scan(ORIGIN)

    assert result.status == "blocked"
    assert result.dimensions["degraded_reason"] == "blocked"
    # The fetch probe still has a URL worth asking ChatGPT to open.
    assert result.fetch_probe_kind == "store_root"
    assert result.fetch_probe_url == ORIGIN
    # Homepage + robots.txt, and nothing else.
    assert len(result.pages_fetched) == 2
    assert result.dimensions["discovery_trace"]["short_circuited"] is True
    # Two URLs, each capped at the 403 ladder's 2 attempts.
    assert len(requested) == 4


def test_the_short_circuited_run_never_claims_it_read_product_pages(monkeypatch):
    """Every blocked row in the export carried 'product pages read
    successfully' with zero product pages sampled."""
    _uniform_403(monkeypatch)

    result = engine.run_scan(ORIGIN)

    evidence = " ".join(result.dimensions["agent_access"]["evidence"])
    assert "robots.txt itself refused" in evidence
    assert "product pages read successfully" not in evidence
    assert "no product pages were read this run" in evidence


def test_the_short_circuited_run_explains_the_unprobed_protocol_surface(monkeypatch):
    _uniform_403(monkeypatch)

    result = engine.run_scan(ORIGIN)

    vp_evidence = " ".join(result.dimensions["value_protocols_seen"]["evidence"])
    assert "both refused our reader" in vp_evidence


def test_the_run_level_block_evidence_names_the_wall(monkeypatch):
    """Fix 1 and Fix 5 together: the two fetches we did make are enough
    to say what refused us and that it said the same thing twice."""
    _uniform_403(monkeypatch)

    result = engine.run_scan(ORIGIN)

    block_evidence = result.dimensions["block_evidence"]
    assert block_evidence["blocked_titles"] == ["Access Denied"]
    assert len(block_evidence["blocked_body_sizes"]) == 1  # identical bodies, deduped
