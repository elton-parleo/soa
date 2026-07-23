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

    def fake_get(self, url, headers=None):
        return httpx.Response(200, text="<html>ok</html>", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = fetcher.fetch("https://example.com/")
    assert result.status == fetcher.FETCHED
    assert result.html == "<html>ok</html>"


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
