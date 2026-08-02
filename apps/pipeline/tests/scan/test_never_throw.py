"""
Never-throw contract for the Agent Scan engine (rule 4 in the leadgen
Agent Scan spec): run_scan()'s public entry point must never raise,
regardless of DNS failure, full robots disallow, empty HTML, or garbage
markup. Every case must come back as a ScanResult with a terminal
status.
"""
import socket

import httpx
import pytest

from scan import engine, fetcher

TERMINAL_STATUSES = {"complete", "blocked", "failed", "skipped"}


@pytest.fixture(autouse=True)
def reset_politeness_state(monkeypatch):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    fetcher._last_fetch_at.clear()
    yield
    fetcher._last_fetch_at.clear()


def _mock_public_dns(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )


def test_empty_input_returns_skipped_never_raises():
    result = engine.run_scan("")
    assert result.status == "skipped"
    assert result.total_score is None


def test_none_input_returns_skipped_never_raises():
    result = engine.run_scan(None)
    assert result.status == "skipped"


def test_unparseable_input_returns_failed_never_raises():
    result = engine.run_scan("://not a url at all")
    assert result.status in TERMINAL_STATUSES


def test_dns_failure_returns_failed_never_raises(monkeypatch):
    def raise_gaierror(*a, **k):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", raise_gaierror)
    result = engine.run_scan("this-domain-does-not-exist.invalid")
    assert result.status == "failed"
    assert result.total_score is None


def test_robots_full_disallow_still_produces_a_result(monkeypatch):
    """
    robots.txt disallowing everything means product-page fetches come
    back robots_disallowed, not that the scan explodes — an unknown
    DTC store must always produce a score (possibly a low F1 score).
    """
    _mock_public_dns(monkeypatch)

    def fake_get(self, url, headers=None):
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n", request=httpx.Request("GET", url))
        # Homepage itself is also disallowed by "Disallow: /" — but the
        # engine already checked robots before this call for gated URLs;
        # homepage fetch bypasses the robot_parser check here in the fake
        # only because robots.txt fetch has no robot_parser gate, mirroring
        # production discovery.py behavior for the initial robots.txt GET.
        return httpx.Response(200, text="<html><body>Home</body></html>", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = engine.run_scan("https://fully-disallowed.example.com")
    assert result.status in TERMINAL_STATUSES
    assert result.status != "skipped"


def test_empty_html_response_never_raises(monkeypatch):
    _mock_public_dns(monkeypatch)

    def fake_get(self, url, headers=None):
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = engine.run_scan("https://empty-html.example.com")
    assert result.status in TERMINAL_STATUSES


def test_garbage_html_never_raises(monkeypatch):
    _mock_public_dns(monkeypatch)

    garbage = "<html><script type='application/ld+json'>{not valid json!!!</script><div class=<broken"

    def fake_get(self, url, headers=None):
        return httpx.Response(200, text=garbage, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = engine.run_scan("https://garbage-html.example.com")
    assert result.status in TERMINAL_STATUSES
    if result.status == "complete":
        assert result.total_score is not None


def test_bot_blocked_site_returns_blocked_status(monkeypatch):
    _mock_public_dns(monkeypatch)

    def fake_get(self, url, headers=None):
        return httpx.Response(403, text="Access Denied", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = engine.run_scan("https://big-box-blocked.example.com")
    assert result.status == "blocked"


def test_timeout_never_raises(monkeypatch):
    _mock_public_dns(monkeypatch)

    def fake_get(self, url, headers=None):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = engine.run_scan("https://times-out.example.com")
    assert result.status in TERMINAL_STATUSES


def test_cross_domain_redirect_never_raises_and_flags(monkeypatch):
    """Stage 11 (H3): a brand redirecting entirely to an unrelated
    domain must still produce a terminal ScanResult, with the stop
    recorded on cross_domain_redirect — never an exception, never a
    silent scan of the other domain."""
    _mock_public_dns(monkeypatch)

    def fake_get(self, url, headers=None):
        # _normalize_input strips the trailing slash before this is ever
        # requested — the canonical-resolution fetch hits the bare origin.
        if url == "https://acquired-brand.example":
            return httpx.Response(302, headers={"location": "https://parent-retailer.example/"}, request=httpx.Request("GET", url))
        if url.startswith("https://parent-retailer.example"):
            raise AssertionError("must never fetch the cross-domain redirect target")
        # Discovery still attempts robots.txt/sitemap/well-known probes
        # against the (fallback) original origin after the stop.
        return httpx.Response(404, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = engine.run_scan("https://acquired-brand.example/")
    assert result.status in TERMINAL_STATUSES
    assert result.cross_domain_redirect is not None
    assert "parent-retailer.example" in result.cross_domain_redirect


def test_malformed_sitemapindex_never_raises(monkeypatch):
    """A sitemap.xml claiming to be a <sitemapindex> but with garbage
    child entries must degrade gracefully, not crash discovery."""
    _mock_public_dns(monkeypatch)

    def fake_get(self, url, headers=None):
        if url.endswith("/sitemap.xml"):
            return httpx.Response(
                200,
                text="<sitemapindex><sitemap><loc>not a url!!! <<<</loc></sitemap></sitemapindex>",
                request=httpx.Request("GET", url),
            )
        return httpx.Response(200, text="<html><body>Home page content here, plenty of it.</body></html>", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = engine.run_scan("https://malformed-sitemap.example.com")
    assert result.status in TERMINAL_STATUSES


def test_unexpected_exception_inside_pipeline_never_raises(monkeypatch):
    """
    Belt-and-suspenders: even a bug deep inside scoring must not escape
    run_scan()'s outer try/except. The homepage body needs to clear
    fetcher.py's MIN_BODY_LENGTH short-body-blocked heuristic (R1,
    hotfix 3: _derive_status no longer treats an infrastructure probe
    like llms.txt fetching fine as "the run is complete" — only a real
    product page or a genuinely-fetched homepage count) so this run
    actually reaches the scoring stage the monkeypatched scorer blows up
    in, rather than degrading to 'blocked' before scoring is ever tried.
    """
    _mock_public_dns(monkeypatch)

    def fake_get(self, url, headers=None):
        body = "<html><body>" + ("Home page content, plenty of it here. " * 5) + "</body></html>"
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    def boom(*a, **k):
        raise RuntimeError("scorer exploded")

    monkeypatch.setattr(engine.scorer, "score_f1_agent_access", boom)

    result = engine.run_scan("https://triggers-scorer-bug.example.com")
    assert result.status == "failed"
    assert "unexpected error" in result.error
