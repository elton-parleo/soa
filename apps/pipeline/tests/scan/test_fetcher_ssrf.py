"""
Tests for scan/fetcher.py's SSRF guard: every private/loopback/
link-local/metadata/reserved range must be rejected before any HTTP
request is attempted, scheme and port are restricted, and a redirect
into a disallowed range is caught on re-validation rather than
followed. No real network access — socket.getaddrinfo and
httpx.Client.get are monkeypatched.
"""
import socket

import httpx
import pytest

from scan import fetcher


def _fake_addrinfo(ip: str, family=socket.AF_INET):
    return [(family, socket.SOCK_STREAM, 6, "", (ip, 443) if family == socket.AF_INET else (ip, 443, 0, 0))]


@pytest.fixture(autouse=True)
def reset_politeness_state(monkeypatch):
    # Avoid real sleeps in the politeness delay while testing multi-hop redirects.
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    fetcher._last_fetch_at.clear()
    yield
    fetcher._last_fetch_at.clear()


@pytest.mark.parametrize("ip", [
    "10.0.0.5",        # RFC1918
    "172.16.5.5",       # RFC1918
    "172.31.255.255",   # RFC1918 upper bound
    "192.168.1.1",      # RFC1918
    "127.0.0.1",        # loopback
    "169.254.169.254",  # link-local / cloud metadata
    "0.0.0.0",
])
def test_ipv4_disallowed_ranges_rejected(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo(ip))
    called = {"hit": False}

    def fail_if_called(*a, **k):
        called["hit"] = True
        raise AssertionError("HTTP request must not be attempted for a disallowed address")

    monkeypatch.setattr(httpx.Client, "get", fail_if_called)

    result = fetcher.fetch("https://evil.example.com/")
    assert result.status == fetcher.FAILED
    assert not called["hit"]


@pytest.mark.parametrize("ip", [
    "::1",        # loopback
    "fc00::1",    # unique local (fc00::/7)
    "fe80::1",    # link-local
])
def test_ipv6_disallowed_ranges_rejected(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo(ip, family=socket.AF_INET6))
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )
    result = fetcher.fetch("https://evil.example.com/")
    assert result.status == fetcher.FAILED


def test_disallowed_scheme_rejected(monkeypatch):
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )
    result = fetcher.fetch("ftp://example.com/file")
    assert result.status == fetcher.FAILED
    assert "scheme" in result.error


def test_disallowed_port_rejected(monkeypatch):
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )
    result = fetcher.fetch("https://example.com:8080/")
    assert result.status == fetcher.FAILED
    assert "port" in result.error


def test_dns_resolution_failure_never_raises(monkeypatch):
    def raise_gaierror(*a, **k):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", raise_gaierror)
    result = fetcher.fetch("https://does-not-resolve.invalid/")
    assert result.status == fetcher.FAILED
    assert "DNS resolution failed" in result.error


def test_public_ip_allowed_through_to_http(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo("93.184.216.34"))
    # A real page body, well over the Stage 11 <100-char "blocked" heuristic.
    body = "<html><body><h1>Example</h1><p>" + "This is a genuine page. " * 5 + "</p></body></html>"

    def fake_get(self, url, headers=None):
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = fetcher.fetch("https://example.com/")
    assert result.status == fetcher.FETCHED
    assert result.html == body


def test_redirect_to_private_ip_is_rejected_on_revalidation(monkeypatch):
    """
    First hop resolves to a public IP and returns a redirect to a
    metadata-service URL; the guard must re-resolve and reject the
    second hop rather than following it.
    """
    call_count = {"n": 0}

    def fake_getaddrinfo(host, *a, **k):
        call_count["n"] += 1
        if host == "public.example.com":
            return _fake_addrinfo("93.184.216.34")
        return _fake_addrinfo("169.254.169.254")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    def fake_get(self, url, headers=None):
        if "public.example.com" in url:
            return httpx.Response(
                302,
                headers={"location": "http://169.254.169.254/latest/meta-data/"},
                request=httpx.Request("GET", url),
            )
        raise AssertionError("must not fetch the redirect target")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = fetcher.fetch("https://public.example.com/")
    assert result.status == fetcher.FAILED
    assert call_count["n"] == 2


def test_too_many_redirects_fails_without_looping_forever(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo("93.184.216.34"))

    def fake_get(self, url, headers=None):
        return httpx.Response(
            302,
            headers={"location": url + "x"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = fetcher.fetch("https://example.com/")
    assert result.status == fetcher.FAILED
    assert "redirect" in result.error


# ─── Stage 11: redirect-following, status taxonomy, cross-domain stop ──────

def test_apex_redirects_to_www_and_is_followed(monkeypatch):
    """F1/H3: apex -> www is the SAME registrable domain, so the redirect
    is followed to completion — final_url, http_status, and the
    redirect_chain are all recorded, and the result is never 'blocked'."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo("93.184.216.34"))
    body = "<html><body><h1>Allbirds</h1><p>" + "Shoes made from wool. " * 6 + "</p></body></html>"

    def fake_get(self, url, headers=None):
        if url == "https://allbirds.com/":
            return httpx.Response(301, headers={"location": "https://www.allbirds.com/"}, request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = fetcher.fetch("https://allbirds.com/", check_short_body=True)

    assert result.status == fetcher.FETCHED
    assert result.url == "https://allbirds.com/"
    assert result.final_url == "https://www.allbirds.com/"
    assert result.http_status == 200
    assert result.redirect_chain == ["https://allbirds.com/"]


def test_ssrf_abort_on_a_later_hop_not_just_the_first(monkeypatch):
    """The guard re-validates on EVERY hop — a chain that's fine for its
    first two hops and only turns private on the third must still be
    caught, not just a first-hop check."""
    call_count = {"n": 0}

    def fake_getaddrinfo(host, *a, **k):
        call_count["n"] += 1
        if host == "hop3.example.com":
            return _fake_addrinfo("169.254.169.254")
        return _fake_addrinfo("93.184.216.34")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    def fake_get(self, url, headers=None):
        if "hop1" in url:
            return httpx.Response(302, headers={"location": "https://hop2.example.com/"}, request=httpx.Request("GET", url))
        if "hop2" in url:
            return httpx.Response(302, headers={"location": "https://hop3.example.com/"}, request=httpx.Request("GET", url))
        raise AssertionError("must not fetch the private-range hop")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = fetcher.fetch("https://hop1.example.com/")

    assert result.status == fetcher.FAILED
    assert call_count["n"] == 3


def test_cross_domain_redirect_stops_and_is_flagged(monkeypatch):
    """H3: a brand redirecting to an unrelated retailer is a finding,
    not a crawl target — the chain stops, the retailer domain is NEVER
    actually fetched, and the error names the stop."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo("93.184.216.34"))

    def fake_get(self, url, headers=None):
        if url == "https://brand.example/":
            return httpx.Response(302, headers={"location": "https://retailer.example/"}, request=httpx.Request("GET", url))
        raise AssertionError("must never fetch the cross-domain redirect target")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = fetcher.fetch("https://brand.example/")

    assert result.status == fetcher.FAILED
    assert "cross-domain redirect stopped" in result.error
    assert "retailer.example" in result.error


def test_www_and_apex_are_the_same_registrable_domain():
    assert fetcher._registrable_domain("www.allbirds.com") == fetcher._registrable_domain("allbirds.com")
    assert fetcher._registrable_domain("brand.example") != fetcher._registrable_domain("retailer.example")


def test_404_is_not_found_not_blocked_or_failed(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo("93.184.216.34"))

    def fake_get(self, url, headers=None):
        return httpx.Response(404, text="Not Found", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = fetcher.fetch("https://example.com/gone")
    assert result.status == fetcher.NOT_FOUND
    assert result.http_status == 404


def test_short_body_only_flagged_as_blocked_when_caller_opts_in(monkeypatch):
    """The <100-char heuristic is opt-in (check_short_body) — a short
    body from an infrastructure fetch (robots.txt, llms.txt) is normal
    and must not be flagged unless the caller asks for the check."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo("93.184.216.34"))

    def fake_get(self, url, headers=None):
        return httpx.Response(200, text="User-agent: *\nDisallow: /admin\n", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    default_result = fetcher.fetch("https://example.com/robots.txt")
    assert default_result.status == fetcher.FETCHED

    opted_in_result = fetcher.fetch("https://example.com/", check_short_body=True)
    assert opted_in_result.status == fetcher.BLOCKED
    assert "short body" in opted_in_result.error


def test_challenge_page_markers_flagged_as_blocked_regardless_of_check_short_body(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo("93.184.216.34"))
    challenge_body = "<html><body>Checking your browser before accessing example.com. " + ("Please wait. " * 10) + "</body></html>"

    def fake_get(self, url, headers=None):
        return httpx.Response(200, text=challenge_body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = fetcher.fetch("https://example.com/robots.txt")  # check_short_body left at default False
    assert result.status == fetcher.BLOCKED
    assert "challenge-page" in result.error
