"""
fetcher.py — SSRF-guarded HTTP fetch for the Agent Scan engine.

Every fetch validates the target before connecting: scheme must be
http/https, every IP the hostname resolves to must not land in a
private, loopback, link-local, or other reserved/metadata address
range, and the port must be 80 or 443. Redirects are followed manually
(httpx's own follow_redirects is never used) so the same validation
runs again on every hop, up to MAX_REDIRECTS times — a same-origin
fetch can still redirect into a private range, and validating only the
original URL would miss that.
"""
import ipaddress
import logging
import socket
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "ParleoScanBot/1.0 (+https://parleo.io/scan)"
TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 5
ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}
POLITENESS_DELAY_SECONDS = 1.0
MAX_PAGE_FETCHES = 12

FETCHED = "fetched"
BLOCKED = "blocked"
ROBOTS_DISALLOWED = "robots_disallowed"
FAILED = "failed"


@dataclass
class FetchResult:
    url: str
    status: str  # fetched | blocked | robots_disallowed | failed
    html: Optional[str] = None
    error: Optional[str] = None


class SsrfRejected(Exception):
    """Raised internally when a URL/redirect target fails the SSRF guard."""


class FetchBudget:
    """
    Per-scan fetch budget — one instance is created per run_scan() call
    and threaded through discovery and page fetches so a single scan
    never issues more than max_fetches HTTP requests, regardless of how
    many candidate pages discovery finds.
    """

    def __init__(self, max_fetches: int = MAX_PAGE_FETCHES):
        self.max_fetches = max_fetches
        self.used = 0

    def has_capacity(self) -> bool:
        return self.used < self.max_fetches

    def consume(self) -> None:
        self.used += 1


def _is_disallowed_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable — don't trust it
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _validate_url(url: str) -> None:
    """Raises SsrfRejected if the URL fails the scheme/port/DNS guard."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SsrfRejected(f"disallowed scheme: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise SsrfRejected("no hostname in URL")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise SsrfRejected(f"disallowed port: {port}")

    try:
        addrinfo = socket.getaddrinfo(hostname, port)
    except socket.gaierror as e:
        raise SsrfRejected(f"DNS resolution failed: {e}")

    resolved_ips = {info[4][0] for info in addrinfo}
    if not resolved_ips:
        raise SsrfRejected("DNS resolution returned no addresses")

    for ip_str in resolved_ips:
        if _is_disallowed_ip(ip_str):
            raise SsrfRejected(f"resolved to disallowed address: {ip_str}")


_last_fetch_at: dict = {}


def _politeness_wait(hostname: str) -> None:
    last = _last_fetch_at.get(hostname)
    if last is not None:
        elapsed = time.monotonic() - last
        if elapsed < POLITENESS_DELAY_SECONDS:
            time.sleep(POLITENESS_DELAY_SECONDS - elapsed)
    _last_fetch_at[hostname] = time.monotonic()


def fetch(
    url: str,
    robot_parser: Optional[urllib.robotparser.RobotFileParser] = None,
) -> FetchResult:
    """
    Fetches a single URL, enforcing the SSRF guard on the original URL
    and on every redirect hop. Never raises: every failure mode — DNS
    failure, disallowed address, robots disallow, timeout, HTTP error,
    or anything unexpected — becomes a FetchResult with the appropriate
    status instead of propagating.
    """
    current_url = url

    try:
        if robot_parser is not None and not robot_parser.can_fetch(USER_AGENT, current_url):
            return FetchResult(url=url, status=ROBOTS_DISALLOWED, error="disallowed by robots.txt")

        for _ in range(MAX_REDIRECTS + 1):
            _validate_url(current_url)

            hostname = urlparse(current_url).hostname
            _politeness_wait(hostname)

            with httpx.Client(follow_redirects=False, timeout=TIMEOUT_SECONDS) as client:
                resp = client.get(current_url, headers={"User-Agent": USER_AGENT})

            if resp.is_redirect:
                location = resp.headers.get("location", "")
                next_url = urljoin(current_url, location) if location else None
                if not next_url:
                    return FetchResult(url=url, status=FAILED, error="redirect with no Location header")
                current_url = next_url
                continue

            if resp.status_code in (403, 429):
                return FetchResult(url=url, status=BLOCKED, error=f"HTTP {resp.status_code}")

            if resp.status_code >= 400:
                return FetchResult(url=url, status=FAILED, error=f"HTTP {resp.status_code}")

            return FetchResult(url=current_url, status=FETCHED, html=resp.text)

        return FetchResult(url=url, status=FAILED, error="too many redirects")

    except SsrfRejected as e:
        return FetchResult(url=url, status=FAILED, error=f"blocked by SSRF guard: {e}")
    except httpx.TimeoutException as e:
        return FetchResult(url=url, status=FAILED, error=f"timeout: {e}")
    except httpx.HTTPError as e:
        return FetchResult(url=url, status=FAILED, error=f"HTTP error: {e}")
    except Exception as e:
        log.exception(f"[scan.fetcher] unexpected error fetching {url}")
        return FetchResult(url=url, status=FAILED, error=f"unexpected error: {e}")
