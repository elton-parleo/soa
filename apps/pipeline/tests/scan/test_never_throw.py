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


def test_unexpected_exception_inside_pipeline_never_raises(monkeypatch):
    """
    Belt-and-suspenders: even a bug deep inside scoring must not escape
    run_scan()'s outer try/except.
    """
    _mock_public_dns(monkeypatch)

    def fake_get(self, url, headers=None):
        return httpx.Response(200, text="<html>ok</html>", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    def boom(*a, **k):
        raise RuntimeError("scorer exploded")

    monkeypatch.setattr(engine.scorer, "score_f1_agent_access", boom)

    result = engine.run_scan("https://triggers-scorer-bug.example.com")
    assert result.status == "failed"
    assert "unexpected error" in result.error
