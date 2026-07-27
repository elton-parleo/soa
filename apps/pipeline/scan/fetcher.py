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

Stage 11 (H3): a redirect hop landing on a different REGISTRABLE
domain than the one originally requested stops the chain — a store
redirecting to an unrelated domain (an acquisition, a rebrand, an
expired-domain squatter) is a finding, not a crawl target. "Registrable
domain" here is a naive last-two-labels heuristic (no public suffix
list dependency, per rule 8) — same pragmatic-heuristic style as
liteDerive.js::deriveBrandFromUrl; multi-part TLDs (co.uk, com.au) are
a known, accepted limitation.
"""
import ipaddress
import logging
import socket
import time
import urllib.robotparser
from dataclasses import dataclass, field
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
MIN_BODY_LENGTH = 100

FETCHED = "fetched"
NOT_FOUND = "not_found"
BLOCKED = "blocked"
ROBOTS_DISALLOWED = "robots_disallowed"
FAILED = "failed"

# Stage 11 (F2): a final 2xx body under MIN_BODY_LENGTH chars, or one of
# these bot-challenge signatures, reads as 'blocked' rather than a
# genuine page — a real product/homepage is never this short or this
# markered.
CHALLENGE_PAGE_MARKERS = (
    "checking your browser", "cf-browser-verification", "cf-chl",
    "attention required", "ddos protection by", "captcha",
    "please enable javascript and cookies",
)


@dataclass
class FetchResult:
    url: str
    status: str  # fetched | not_found | blocked | robots_disallowed | failed
    html: Optional[str] = None
    error: Optional[str] = None
    final_url: Optional[str] = None       # last URL reached, even if unchanged
    http_status: Optional[int] = None     # raw HTTP status code, when one was received
    redirect_chain: list = field(default_factory=list)  # URLs that redirected onward, in order


class SsrfRejected(Exception):
    """Raised internally when a URL/redirect target fails the SSRF guard."""


class FetchBudget:
    """
    Per-scan fetch budget — one instance is created per run_scan() call
    and threaded through discovery and page fetches so a single scan
    never issues more than max_fetches HTTP requests, regardless of how
    many candidate pages discovery finds. Stage 11 (D1): discovery now
    uses a SEPARATE, smaller budget instance for robots/sitemap/
    well-known traversal so index recursion can never starve PDP
    sampling of its own 12-fetch budget.
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


def _registrable_domain(hostname: Optional[str]) -> str:
    """Naive eTLD+1 heuristic — last two dot-separated labels, lowercased.
    Treats allbirds.com and www.allbirds.com as the same registrable
    domain (redirect follows), but allbirds.com and retailer.com as
    different (redirect stops). Never raises."""
    if not hostname:
        return ""
    labels = hostname.lower().split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else hostname.lower()


def _looks_like_challenge_page(html: Optional[str]) -> bool:
    if not html:
        return False
    lowered = html.lower()
    return any(marker in lowered for marker in CHALLENGE_PAGE_MARKERS)


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
    check_short_body: bool = False,
) -> FetchResult:
    """
    Fetches a single URL, enforcing the SSRF guard on the original URL
    and on every redirect hop, and stopping the chain if a hop lands on
    a different registrable domain (Stage 11, H3). Never raises: every
    failure mode — DNS failure, disallowed address, cross-domain
    redirect, robots disallow, timeout, HTTP error, or anything
    unexpected — becomes a FetchResult with the appropriate status
    instead of propagating.

    3xx is never a terminal status (F2): a redirect is either followed
    or the fetch ends 'failed' (too many hops, SSRF-abort, cross-domain
    stop) — it never comes back as a bare "redirect" status.

    check_short_body (F2) flags a final 2xx body under MIN_BODY_LENGTH
    chars as 'blocked' — but only when the caller opts in. A real
    robots.txt, sitemap, or /llms.txt is routinely well under 100 chars
    and that's completely normal; the heuristic only makes sense for
    actual content pages (homepage, product, loyalty, shipping), where
    a real page is never this short. Challenge-page marker detection is
    unconditional regardless of this flag — a bot-challenge response is
    never legitimate, on any URL.
    """
    current_url = url
    redirect_chain: list = []
    starting_domain = _registrable_domain(urlparse(url).hostname)

    try:
        if robot_parser is not None and not robot_parser.can_fetch(USER_AGENT, current_url):
            return FetchResult(url=url, status=ROBOTS_DISALLOWED, error="disallowed by robots.txt")

        for _ in range(MAX_REDIRECTS + 1):
            _validate_url(current_url)

            hop_domain = _registrable_domain(urlparse(current_url).hostname)
            if hop_domain != starting_domain:
                return FetchResult(
                    url=url, final_url=current_url, status=FAILED,
                    redirect_chain=redirect_chain,
                    error=(
                        f"cross-domain redirect stopped at {current_url!r} "
                        f"(registrable domain {hop_domain!r} != {starting_domain!r})"
                    ),
                )

            hostname = urlparse(current_url).hostname
            _politeness_wait(hostname)

            with httpx.Client(follow_redirects=False, timeout=TIMEOUT_SECONDS) as client:
                resp = client.get(current_url, headers={"User-Agent": USER_AGENT})

            if resp.is_redirect:
                redirect_chain.append(current_url)
                location = resp.headers.get("location", "")
                next_url = urljoin(current_url, location) if location else None
                if not next_url:
                    return FetchResult(
                        url=url, final_url=current_url, status=FAILED,
                        http_status=resp.status_code, redirect_chain=redirect_chain,
                        error="redirect with no Location header",
                    )
                current_url = next_url
                continue

            if resp.status_code in (404, 410):
                return FetchResult(
                    url=url, final_url=current_url, status=NOT_FOUND,
                    http_status=resp.status_code, redirect_chain=redirect_chain,
                    error=f"HTTP {resp.status_code}",
                )

            if resp.status_code in (403, 429):
                return FetchResult(
                    url=url, final_url=current_url, status=BLOCKED,
                    http_status=resp.status_code, redirect_chain=redirect_chain,
                    error=f"HTTP {resp.status_code}",
                )

            if resp.status_code >= 400:
                return FetchResult(
                    url=url, final_url=current_url, status=FAILED,
                    http_status=resp.status_code, redirect_chain=redirect_chain,
                    error=f"HTTP {resp.status_code}",
                )

            body = resp.text
            if _looks_like_challenge_page(body):
                return FetchResult(
                    url=url, final_url=current_url, status=BLOCKED, html=body,
                    http_status=resp.status_code, redirect_chain=redirect_chain,
                    error="challenge-page markers detected in response body",
                )
            if check_short_body and len(body.strip()) < MIN_BODY_LENGTH:
                return FetchResult(
                    url=url, final_url=current_url, status=BLOCKED, html=body,
                    http_status=resp.status_code, redirect_chain=redirect_chain,
                    error=f"suspiciously short body ({len(body.strip())} chars) after following redirects",
                )

            return FetchResult(
                url=url, final_url=current_url, status=FETCHED, html=body,
                http_status=resp.status_code, redirect_chain=redirect_chain,
            )

        return FetchResult(
            url=url, final_url=current_url, status=FAILED,
            redirect_chain=redirect_chain, error="too many redirects",
        )

    except SsrfRejected as e:
        return FetchResult(
            url=url, final_url=current_url, status=FAILED,
            redirect_chain=redirect_chain, error=f"blocked by SSRF guard: {e}",
        )
    except httpx.TimeoutException as e:
        return FetchResult(
            url=url, final_url=current_url, status=FAILED,
            redirect_chain=redirect_chain, error=f"timeout: {e}",
        )
    except httpx.HTTPError as e:
        return FetchResult(
            url=url, final_url=current_url, status=FAILED,
            redirect_chain=redirect_chain, error=f"HTTP error: {e}",
        )
    except Exception as e:
        log.exception(f"[scan.fetcher] unexpected error fetching {url}")
        return FetchResult(
            url=url, final_url=current_url, status=FAILED,
            redirect_chain=redirect_chain, error=f"unexpected error: {e}",
        )
