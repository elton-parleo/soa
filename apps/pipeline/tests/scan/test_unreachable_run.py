"""
Unreachable-host follow-up (Lululemon, request 138): every fetch —
robots.txt, /sitemap.xml, the store root, llms.txt, the MCP manifest —
ended `failed` with no HTTP status, because the Akamai edge held an
identified reader's connection open until our timeout. The stored row
said degraded_reason=no_product_pages_found and discovery_outcome=
no_sitemap, and the report told Lululemon it doesn't declare a sitemap.

These run the real engine against a transport where every request
times out, then check the run status, the outcome classification, the
DNS vendor fallback and the timeout shortening, plus the two supporting
changes: no_sitemap now needs robots.txt to have actually answered, and
a retried URL records the status that caused the retry.
"""
import socket
import time

import httpx
import pytest

from scan import engine, fetcher

ORIGIN = "https://lulu.example.com"

HOMEPAGE_HTML = (
    "<html><body><p>Welcome to the store — plenty of real homepage copy here "
    "so this clears the short-body heuristic like any genuine homepage would.</p></body></html>"
)


@pytest.fixture(autouse=True)
def reset_fetch_state(monkeypatch):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    fetcher._last_fetch_at.clear()
    fetcher._domain_seen.clear()
    fetcher._host_timeouts.clear()
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    yield
    fetcher._last_fetch_at.clear()
    fetcher._domain_seen.clear()
    fetcher._host_timeouts.clear()


def _every_request_times_out(seen_timeouts=None):
    """Replaces httpx.Client.get. Records the timeout each client was
    built with, so the shortening can be checked."""
    def fake_get(self, url, headers=None):
        if seen_timeouts is not None:
            seen_timeouts.append(self.timeout.read)
        raise httpx.ReadTimeout("timed out", request=httpx.Request("GET", url))
    return fake_get


def _dispatch(handlers, default=(404, "")):
    def fake_get(self, url, headers=None):
        entry = handlers.get(url)
        if entry is None:
            entry = next((v for k, v in handlers.items() if not k.startswith("http") and url.endswith(k)), default)
        status, body = entry
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))
    return fake_get


# ─── the run status and the outcome ─────────────────────────────────────

def test_all_fetches_timing_out_is_failed_unreachable(monkeypatch):
    monkeypatch.setattr(httpx.Client, "get", _every_request_times_out())

    result = engine.run_scan(ORIGIN)

    assert result.status == engine.STATUS_FAILED
    assert result.dimensions["degraded_reason"] == "unreachable"
    assert result.error == "the site did not respond to any request"
    # Every fetch really did end without an HTTP status — the premise.
    assert result.pages_fetched
    assert all(row["http_status"] is None for row in result.pages_fetched)


def test_all_fetches_timing_out_classifies_unreachable_not_no_sitemap(monkeypatch):
    monkeypatch.setattr(httpx.Client, "get", _every_request_times_out())

    result = engine.run_scan(ORIGIN)

    outcome = result.dimensions["discovery_outcome"]
    assert outcome["code"] == "unreachable"
    assert outcome["summary"] == (
        "your site did not respond to our reader at all — every request "
        "timed out before any answer came back"
    )
    assert "sitemap" not in outcome["summary"]


def test_a_single_real_response_is_not_unreachable(monkeypatch):
    """robots.txt answered 404, everything else timed out: something
    responded, so this is not 'nothing answered'."""
    def fake_get(self, url, headers=None):
        if url.endswith("/robots.txt"):
            return httpx.Response(404, text="", request=httpx.Request("GET", url))
        raise httpx.ReadTimeout("timed out", request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = engine.run_scan(ORIGIN)

    assert result.dimensions["degraded_reason"] != "unreachable"
    assert result.dimensions["discovery_outcome"]["code"] != "unreachable"


# ─── no_sitemap needs robots.txt to have actually answered ──────────────

def test_no_sitemap_still_fires_when_robots_is_served(monkeypatch):
    monkeypatch.setattr(httpx.Client, "get", _dispatch({
        "/robots.txt": (200, "User-agent: *\nDisallow: /admin/\n"),
        ORIGIN: (200, HOMEPAGE_HTML),
        "/sitemap.xml": (404, ""),
    }))
    result = engine.run_scan(ORIGIN)
    assert result.dimensions["discovery_outcome"]["code"] == "no_sitemap"


def test_no_sitemap_still_fires_when_robots_is_a_real_404(monkeypatch):
    monkeypatch.setattr(httpx.Client, "get", _dispatch({
        "/robots.txt": (404, ""),
        ORIGIN: (200, HOMEPAGE_HTML),
        "/sitemap.xml": (404, ""),
    }))
    result = engine.run_scan(ORIGIN)
    assert result.dimensions["discovery_outcome"]["code"] == "no_sitemap"


def test_no_sitemap_never_fires_when_robots_itself_never_answered(monkeypatch):
    """robots.txt timed out while the homepage answered: we never
    learned whether a sitemap is declared, so "you don't declare one"
    would be a claim nobody checked."""
    def fake_get(self, url, headers=None):
        if url.endswith("/robots.txt"):
            raise httpx.ReadTimeout("timed out", request=httpx.Request("GET", url))
        if url == ORIGIN:
            return httpx.Response(200, text=HOMEPAGE_HTML, request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = engine.run_scan(ORIGIN)

    assert result.dimensions["discovery_outcome"]["code"] != "no_sitemap"


# ─── DNS vendor fallback ────────────────────────────────────────────────

def test_unreachable_run_records_the_dns_vendor_hint(monkeypatch):
    monkeypatch.setattr(httpx.Client, "get", _every_request_times_out())
    monkeypatch.setattr(
        fetcher, "_dns_names_for",
        lambda hostname: ["a23-67-33-24.deploy.static.akamaitechnologies.com"],
    )

    result = engine.run_scan(ORIGIN)

    evidence = result.dimensions["block_evidence"]
    assert evidence["dominant_vendor"] is None  # nothing answered, so nothing to fingerprint
    assert evidence["dns_vendor_hint"] == "akamai"
    assert evidence["dns_vendor_record"] == "a23-67-33-24.deploy.static.akamaitechnologies.com"


def test_dns_is_not_asked_when_a_response_already_named_the_vendor(monkeypatch):
    asked = []
    monkeypatch.setattr(fetcher, "_dns_names_for", lambda hostname: asked.append(hostname) or [])
    summary = engine._block_evidence_summary(
        [{"status": "blocked", "edge_vendor_hint": "cloudflare"}], dns_hostname="lulu.example.com",
    )
    assert summary["dominant_vendor"] == "cloudflare"
    assert summary["dns_vendor_hint"] is None
    assert asked == []


def test_dns_is_not_asked_on_a_complete_run(monkeypatch):
    asked = []
    monkeypatch.setattr(fetcher, "_dns_names_for", lambda hostname: asked.append(hostname) or [])
    monkeypatch.setattr(httpx.Client, "get", _dispatch({
        "/robots.txt": (200, "User-agent: *\n"),
        ORIGIN: (200, HOMEPAGE_HTML),
    }))
    result = engine.run_scan(ORIGIN)
    assert result.status == engine.STATUS_COMPLETE
    assert asked == []
    assert result.dimensions["block_evidence"]["dns_vendor_hint"] is None


@pytest.mark.parametrize("names, vendor", [
    (["e106594.a.akamaiedge.net"], "akamai"),
    (["lululemon.com.edgekey.net"], "akamai"),
    (["a69-192-139-102.deploy.static.akamaitechnologies.com"], "akamai"),
    (["zdu2x7w.x.incapdns.net"], "imperva"),
    (["shop.example.com.cdn.cloudflare.net"], "cloudflare"),
    (["client.px-cloud.net"], "human_px"),
    (["server-13-33-33-1.sin2.r.cloudfront.net."], "cloudfront"),
    (["288db7e80eda92e3.vercel-dns-013.com"], None),
    ([], None),
])
def test_dns_vendor_markers(monkeypatch, names, vendor):
    monkeypatch.setattr(fetcher, "_dns_names_for", lambda hostname: names)
    assert fetcher.dns_vendor_hint("example.com")[0] == vendor


def test_dns_vendor_hint_never_raises(monkeypatch):
    def boom(hostname):
        raise OSError("resolver exploded")
    monkeypatch.setattr(fetcher, "_dns_names_for", boom)
    assert fetcher.dns_vendor_hint("example.com") == (None, None)
    assert fetcher.dns_vendor_hint(None) == (None, None)


def test_dns_vendor_hint_is_bounded_by_its_timeout(monkeypatch):
    monkeypatch.setattr(fetcher, "_dns_names_for", lambda hostname: time.sleep(5) or ["x.akamaiedge.net"])
    started = time.monotonic()
    assert fetcher.dns_vendor_hint("example.com", timeout=0.2) == (None, None)
    assert time.monotonic() - started < 2


def test_dns_names_order_cname_then_ptr_then_www_sibling(monkeypatch):
    """The resolver itself: an apex with no CNAME of its own (Lululemon)
    still yields its address's PTR name and its www sibling's CNAME
    target — the two places its Akamai edge is actually published."""
    def fake_getaddrinfo(host, port, *a, **k):
        if host == "lululemon.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "lululemon.com", ("69.192.139.102", 443))]
        if host == "www.lululemon.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "e106594.a.akamaiedge.net", ("23.211.139.207", 443))]
        raise socket.gaierror("unknown")
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "gethostbyaddr", lambda ip: (f"a{ip.replace('.', '-')}.deploy.static.akamaitechnologies.com", [], [ip]))
    # conftest stubs _dns_names_for; this test is about the real one.
    names = _REAL_DNS_NAMES_FOR("lululemon.com")
    assert names == [
        "a69-192-139-102.deploy.static.akamaitechnologies.com",
        "e106594.a.akamaiedge.net",
    ]


# The real resolver, captured at import time — before conftest's
# autouse fixture replaces fetcher._dns_names_for for every test.
_REAL_DNS_NAMES_FOR = fetcher._dns_names_for


# ─── timeout shortening ─────────────────────────────────────────────────

def test_timeout_shortens_after_two_timeouts_to_the_same_host(monkeypatch):
    seen = []
    monkeypatch.setattr(httpx.Client, "get", _every_request_times_out(seen))

    engine.run_scan(ORIGIN)

    assert seen[:2] == [fetcher.TIMEOUT_SECONDS, fetcher.TIMEOUT_SECONDS]
    assert len(seen) > 2
    assert all(t == fetcher.REPEAT_TIMEOUT_SECONDS for t in seen[2:])


def test_a_cooperative_host_always_gets_the_full_timeout(monkeypatch):
    seen = []

    def fake_get(self, url, headers=None):
        seen.append(self.timeout.read)
        return httpx.Response(404, text="", request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx.Client, "get", fake_get)

    engine.run_scan(ORIGIN)

    assert seen and all(t == fetcher.TIMEOUT_SECONDS for t in seen)


def test_a_new_scan_of_the_same_host_starts_on_the_full_timeout(monkeypatch):
    monkeypatch.setattr(httpx.Client, "get", _every_request_times_out())
    engine.run_scan(ORIGIN)

    seen = []
    monkeypatch.setattr(httpx.Client, "get", _every_request_times_out(seen))
    engine.run_scan(ORIGIN)

    assert seen[0] == fetcher.TIMEOUT_SECONDS


# ─── retry_http_status ──────────────────────────────────────────────────

def test_a_recovered_retry_records_the_status_that_caused_it(monkeypatch):
    calls = []

    def fake_get(self, url, headers=None):
        calls.append(url)
        status = 403 if len(calls) == 1 else 200
        return httpx.Response(status, text=HOMEPAGE_HTML, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = fetcher.fetch(f"{ORIGIN}/p/thing")

    assert result.status == "fetched"
    assert result.http_status == 200
    assert result.attempts == 2
    assert result.retry_http_status == 403
    assert engine._fetch_entry(result)["retry_http_status"] == 403


def test_an_unretried_fetch_has_no_retry_status(monkeypatch):
    monkeypatch.setattr(httpx.Client, "get", _dispatch({"/p/thing": (200, HOMEPAGE_HTML)}))
    result = fetcher.fetch(f"{ORIGIN}/p/thing")
    assert result.attempts == 1
    assert result.retry_http_status is None
