"""
Every scan row records WHICH key signed its fetches.

signing_enabled already said THAT a run was signed. After a key
rotation, "was this run signed with the old key or the new one?" was
only answerable by reconstructing what the worker's environment held at
the time. signing_kid makes it a database question.

The kid is public material — it is a thumbprint over the public key,
published in the key directory and sent in every Signature-Input — but
it stays out of the report payload, which has no use for it
(cycle_scoring.build_scan_payload reads named keys off dimensions and
never spreads it, so this needs no filtering to stay internal).

Both run paths are covered: a complete run and a degraded/blocked one.
"""
import socket

import httpx
import pytest

from scan import engine, fetcher, signing

ORIGIN = "https://acme.example.com"
ROBOTS = "User-agent: *\nAllow: /\n"
SITEMAP = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    f"<url><loc>{ORIGIN}/products/widget</loc></url>"
    "</urlset>"
)
PRODUCT_HTML = """
<html><head><title>Widget</title>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product", "name": "Widget",
 "offers": {"@type": "Offer", "price": "29.99", "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"}}
</script></head>
<body><nav><a href="/rewards">Rewards</a></nav><h1>Widget</h1><p>Now $29.99</p></body></html>
"""
HOMEPAGE_HTML = (
    "<html><body><nav><a href='/rewards'>Rewards</a></nav>"
    "<p>Welcome to the store — plenty of real homepage copy here so this "
    "clears the short-body heuristic like any genuine homepage would.</p></body></html>"
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


def _complete_run_server(monkeypatch):
    def fake_get(self, url, headers=None, **kw):
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=ROBOTS, request=httpx.Request("GET", url))
        if url.endswith("/sitemap.xml"):
            return httpx.Response(200, text=SITEMAP, request=httpx.Request("GET", url))
        if url.endswith("/products/widget"):
            return httpx.Response(200, text=PRODUCT_HTML, request=httpx.Request("GET", url))
        if url in (ORIGIN, ORIGIN + "/"):
            return httpx.Response(200, text=HOMEPAGE_HTML, request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)


def _blocked_run_server(monkeypatch):
    def fake_get(self, url, headers=None, **kw):
        return httpx.Response(403, text="Access Denied", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)


@pytest.mark.parametrize("server,expected_status", [
    (_complete_run_server, "complete"),
    (_blocked_run_server, "blocked"),
])
def test_both_run_paths_record_the_signing_kid(monkeypatch, server, expected_status):
    server(monkeypatch)
    monkeypatch.setattr(signing, "key_id", lambda: "abc")

    result = engine.run_scan(ORIGIN)

    assert result.status == expected_status
    assert result.dimensions["signing_kid"] == "abc"


@pytest.mark.parametrize("server,expected_status", [
    (_complete_run_server, "complete"),
    (_blocked_run_server, "blocked"),
])
def test_the_key_is_present_and_none_when_signing_is_off(monkeypatch, server, expected_status):
    """Present-and-None, never absent — so a reader never has to tell
    'unsigned run' apart from 'row written before this key existed'."""
    server(monkeypatch)
    monkeypatch.setattr(signing, "key_id", lambda: None)

    result = engine.run_scan(ORIGIN)

    assert result.status == expected_status
    assert "signing_kid" in result.dimensions
    assert result.dimensions["signing_kid"] is None


def test_the_kid_sits_next_to_signing_enabled_not_instead_of_it(monkeypatch):
    _complete_run_server(monkeypatch)
    monkeypatch.setattr(signing, "key_id", lambda: "abc")
    monkeypatch.setattr(signing, "is_signing_enabled", lambda: True)

    result = engine.run_scan(ORIGIN)

    assert result.dimensions["signing_enabled"] is True
    assert result.dimensions["signing_kid"] == "abc"
