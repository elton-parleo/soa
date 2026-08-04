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
import os
import random
import re
import socket
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

from . import signing
from .identity import BOT_UA

log = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    """Never raises — an unset or unparseable env var falls back to
    default, same never-throw discipline as the rest of the scanner."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# Identifies honestly (A1): one real constant, sent on every page fetch
# — declared always (W5's UA_POLICY default), never per-call variation.
# The literal value lives in identity.py (W1, single source) — every
# other module that needs the bot's own UA (discovery.py, scorer.py,
# agent_access_matrix.py) imports THIS name, not identity.BOT_UA
# directly, so there is still exactly one name used repo-wide.
USER_AGENT = BOT_UA
ACCEPT_HEADER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
ACCEPT_LANGUAGE_HEADER = "en-US,en;q=0.9"
TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 5
ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}

# A2/A5: env-tunable so a hostile-edge rerun can be slowed without a
# deploy. POLITENESS_DELAY_SECONDS is the name existing tests already
# monkeypatch (see tests/scan/test_scorer.py, test_fetcher_ssrf.py) — kept
# as-is rather than renamed, just now derived from the env-tunable knob
# and jittered (see _jittered_delay) instead of being a bare constant.
SCAN_FETCH_DELAY_MS = _env_int("SCAN_FETCH_DELAY_MS", 2500)
SCAN_FETCH_RETRIES = _env_int("SCAN_FETCH_RETRIES", 3)
POLITENESS_DELAY_SECONDS = SCAN_FETCH_DELAY_MS / 1000.0
POLITENESS_JITTER_FRACTION = 0.40

# A3: retry ladder for 429/403/5xx — a terminal-looking response on the
# first attempt isn't necessarily the truth; it may be an edge that
# rate-limits bursts and would happily serve the second request a few
# seconds later. RETRY_BACKOFF_BASE_SECONDS/FIRST_REQUEST_429_COOLOFF_
# SECONDS are separate, zeroable module constants (not folded into
# SCAN_FETCH_DELAY_MS) so tests can silence retry sleeps without also
# silencing the ordinary per-page politeness delay, and vice versa.
RETRY_AFTER_CAP_SECONDS = 30.0
RETRY_BACKOFF_BASE_SECONDS = 4.0
FIRST_REQUEST_429_COOLOFF_SECONDS = 20.0
RETRYABLE_STATUS_CODES = {429, 403, 500, 502, 503, 504}

MAX_PAGE_FETCHES = 12
MIN_BODY_LENGTH = 100

FETCHED = "fetched"
NOT_FOUND = "not_found"
BLOCKED = "blocked"
ROBOTS_DISALLOWED = "robots_disallowed"
FAILED = "failed"

# Stage 11 (F2): a final 2xx body under MIN_BODY_LENGTH chars reads as
# 'blocked' rather than a genuine page — a real product/homepage is
# never this short.
#
# Challenge-page rewrite (hotfix 4): interstitials are tiny (a few KB);
# real PDPs run 100KB+. Bodies over CHALLENGE_MAX_BYTES are NEVER a
# challenge, full stop, regardless of anything else on the page — this
# alone rules out a real product page that happens to embed a
# grecaptcha script tag (routine on real storefronts, and the exact
# incident shape that used to misfire: "captcha" appearing anywhere in
# 150KB of real markup used to be enough to blank the page).
CHALLENGE_MAX_BYTES = _env_int("CHALLENGE_MAX_BYTES", 30_000)
# Signatures are scoped to <title> or this many leading bytes of the
# body — never a substring search over the whole page (same reasoning:
# a real page can legitimately mention any of these words far down the
# page without being an interstitial).
CHALLENGE_SCAN_BYTES = 2000
CHALLENGE_PAGE_SIGNATURES = (
    "just a moment", "attention required", "checking your browser",
    "verify you are human", "cf-browser-verification", "cf-chl",
    "ddos protection by", "complete the captcha", "solve the captcha",
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
    # A4: structured per-URL fetch outcome the scorer can read directly,
    # rather than re-deriving attempt/retry facts from evidence strings.
    attempts: int = 1                             # HTTP requests actually made for this URL
    retry_after_seen: Optional[float] = None       # max Retry-After (seconds, capped) honored, if any
    bytes: Optional[int] = None                    # response body size, when a response was received
    # Sitemap-sampler stage (hotfix 5): raw response bytes, populated
    # only on a successful fetch — needed for gzip-encoded sitemap
    # decompression, where the decoded `html` text is useless (a .gz
    # file's bytes aren't valid UTF-8). Never serialized to pages_fetched
    # or persisted anywhere — runtime-only, garbage-collected with the
    # rest of the scan's in-memory state.
    content: Optional[bytes] = None


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


def _challenge_signature_in(text: str) -> Optional[str]:
    for marker in CHALLENGE_PAGE_SIGNATURES:
        if marker in text:
            return marker
    return None


def _looks_like_challenge_page(html: Optional[str]) -> Optional[str]:
    """
    Challenge-page rewrite (hotfix 4): a conjunction of independent
    signals, never a bare substring-anywhere match. Returns None when
    the page is not a challenge, else a short string naming which rule
    fired — never a bare bool the caller has to re-derive an
    explanation for.
    """
    if not html:
        return None

    body_bytes = len(html.encode("utf-8", errors="replace"))
    if body_bytes > CHALLENGE_MAX_BYTES:
        return None

    lowered = html.lower()
    # Real-content override: a page shipping structured product data,
    # social-preview metadata, or a real nav bar is never a bare
    # challenge interstitial — those ship none of these.
    if (
        "application/ld+json" in lowered
        or "og:title" in lowered
        or "og:type" in lowered
        or "<nav" in lowered
    ):
        return None

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title_text = title_match.group(1).lower() if title_match else ""
    if _challenge_signature_in(title_text):
        return f"challenge-page: title signature + {body_bytes // 1000}KB body"

    if _challenge_signature_in(lowered[:CHALLENGE_SCAN_BYTES]):
        return f"challenge-page: body signature + {body_bytes // 1000}KB body"

    return None


_last_fetch_at: dict = {}
# A3: hostnames this process has made at least one HTTP request to —
# distinct from _last_fetch_at (which tracks timing, not "have we ever
# tried"). Backs the first-request-429 cool-off: a rate-limit on the
# very first request to a domain this run reads as sitewide hostility
# from the start, not an ordinary mid-run rate limit.
_domain_seen: set = set()


def _jittered_delay(base_seconds: float) -> float:
    """A2: ±40% jitter around the base politeness delay — never negative,
    never raises. base_seconds <= 0 (tests monkeypatch it to 0) returns 0
    unconditionally so tests stay fast regardless of jitter."""
    if base_seconds <= 0:
        return 0.0
    spread = base_seconds * POLITENESS_JITTER_FRACTION
    return max(0.0, base_seconds + random.uniform(-spread, spread))


def _politeness_wait(hostname: str) -> None:
    last = _last_fetch_at.get(hostname)
    if last is not None:
        elapsed = time.monotonic() - last
        delay = _jittered_delay(POLITENESS_DELAY_SECONDS)
        if elapsed < delay:
            time.sleep(delay - elapsed)
    _last_fetch_at[hostname] = time.monotonic()


def _request_headers(url: str) -> dict:
    """A1: the one honest identity, plus normal Accept/Accept-Language —
    never varied per call, never a browser impersonation. W2: signs the
    request (RFC 9421 / Web Bot Auth) when signing.is_signing_enabled()
    — signing.sign_request() itself returns {} when disabled, so this
    is a plain no-op merge (byte-identical headers) with signing off."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": ACCEPT_HEADER,
        "Accept-Language": ACCEPT_LANGUAGE_HEADER,
    }
    headers.update(signing.sign_request("GET", url))
    return headers


def _parse_retry_after(header_value: Optional[str]) -> Optional[float]:
    """A3: Retry-After as either delta-seconds or an HTTP-date, capped at
    RETRY_AFTER_CAP_SECONDS. Never raises — an absent or unparseable
    header returns None so the caller falls back to exponential backoff."""
    if not header_value:
        return None
    try:
        return max(0.0, min(float(header_value), RETRY_AFTER_CAP_SECONDS))
    except (TypeError, ValueError):
        pass
    try:
        dt = parsedate_to_datetime(header_value)
        if dt is None:
            return None
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        delta = (dt - now).total_seconds()
        return max(0.0, min(delta, RETRY_AFTER_CAP_SECONDS))
    except Exception:
        return None


def _fetch_with_retries(current_url: str, hostname: str):
    """
    A3: issues the GET request, retrying on 429/403/5xx up to
    SCAN_FETCH_RETRIES total attempts — Retry-After (capped) when the
    response sends one, otherwise exponential backoff (RETRY_BACKOFF_
    BASE_SECONDS, doubling each attempt). A 429 on the very first
    request this process has made to this hostname additionally
    triggers one FIRST_REQUEST_429_COOLOFF_SECONDS cool-off before the
    ladder starts — an immediate sitewide-hostility signal, distinct
    from an ordinary rate limit hit mid-run.

    Returns (response, attempts, retry_after_seen): response is the
    LAST httpx.Response received (whatever its final status — the
    caller decides what that means), attempts is how many requests were
    actually made, retry_after_seen is the largest Retry-After value
    honored in seconds, or None if the ladder ran on backoff alone (or
    never retried at all).
    """
    is_first_request_to_host = hostname not in _domain_seen
    _domain_seen.add(hostname)

    resp = None
    retry_after_seen: Optional[float] = None

    for attempt in range(1, SCAN_FETCH_RETRIES + 1):
        with httpx.Client(follow_redirects=False, timeout=TIMEOUT_SECONDS) as client:
            resp = client.get(current_url, headers=_request_headers(current_url))

        if resp.status_code not in RETRYABLE_STATUS_CODES or attempt >= SCAN_FETCH_RETRIES:
            return resp, attempt, retry_after_seen

        if resp.status_code == 429 and is_first_request_to_host and attempt == 1:
            time.sleep(FIRST_REQUEST_429_COOLOFF_SECONDS)
        is_first_request_to_host = False

        retry_after = _parse_retry_after(resp.headers.get("retry-after"))
        if retry_after is not None:
            retry_after_seen = max(retry_after_seen or 0.0, retry_after)
            time.sleep(retry_after)
        else:
            time.sleep(RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))

    return resp, SCAN_FETCH_RETRIES, retry_after_seen


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
    total_attempts = 0
    retry_after_seen: Optional[float] = None

    try:
        if robot_parser is not None and not robot_parser.can_fetch(USER_AGENT, current_url):
            return FetchResult(url=url, status=ROBOTS_DISALLOWED, error="disallowed by robots.txt")

        for _ in range(MAX_REDIRECTS + 1):
            _validate_url(current_url)

            hop_domain = _registrable_domain(urlparse(current_url).hostname)
            if hop_domain != starting_domain:
                return FetchResult(
                    url=url, final_url=current_url, status=FAILED,
                    redirect_chain=redirect_chain, attempts=total_attempts or 1,
                    retry_after_seen=retry_after_seen,
                    error=(
                        f"cross-domain redirect stopped at {current_url!r} "
                        f"(registrable domain {hop_domain!r} != {starting_domain!r})"
                    ),
                )

            hostname = urlparse(current_url).hostname
            _politeness_wait(hostname)

            resp, hop_attempts, hop_retry_after = _fetch_with_retries(current_url, hostname)
            total_attempts += hop_attempts
            if hop_retry_after is not None:
                retry_after_seen = max(retry_after_seen or 0.0, hop_retry_after)

            if resp.is_redirect:
                redirect_chain.append(current_url)
                location = resp.headers.get("location", "")
                next_url = urljoin(current_url, location) if location else None
                if not next_url:
                    return FetchResult(
                        url=url, final_url=current_url, status=FAILED,
                        http_status=resp.status_code, redirect_chain=redirect_chain,
                        attempts=total_attempts, retry_after_seen=retry_after_seen,
                        bytes=len(resp.content), error="redirect with no Location header",
                    )
                current_url = next_url
                continue

            if resp.status_code in (404, 410):
                return FetchResult(
                    url=url, final_url=current_url, status=NOT_FOUND,
                    http_status=resp.status_code, redirect_chain=redirect_chain,
                    attempts=total_attempts, retry_after_seen=retry_after_seen,
                    bytes=len(resp.content), error=f"HTTP {resp.status_code}",
                )

            if resp.status_code in (403, 429):
                return FetchResult(
                    url=url, final_url=current_url, status=BLOCKED,
                    http_status=resp.status_code, redirect_chain=redirect_chain,
                    attempts=total_attempts, retry_after_seen=retry_after_seen,
                    bytes=len(resp.content), error=f"HTTP {resp.status_code}",
                )

            if resp.status_code >= 400:
                return FetchResult(
                    url=url, final_url=current_url, status=FAILED,
                    http_status=resp.status_code, redirect_chain=redirect_chain,
                    attempts=total_attempts, retry_after_seen=retry_after_seen,
                    bytes=len(resp.content), error=f"HTTP {resp.status_code}",
                )

            body = resp.text
            challenge_reason = _looks_like_challenge_page(body)
            if challenge_reason:
                return FetchResult(
                    url=url, final_url=current_url, status=BLOCKED, html=body,
                    http_status=resp.status_code, redirect_chain=redirect_chain,
                    attempts=total_attempts, retry_after_seen=retry_after_seen,
                    bytes=len(resp.content),
                    error=challenge_reason,
                )
            if check_short_body and len(body.strip()) < MIN_BODY_LENGTH:
                return FetchResult(
                    url=url, final_url=current_url, status=BLOCKED, html=body,
                    http_status=resp.status_code, redirect_chain=redirect_chain,
                    attempts=total_attempts, retry_after_seen=retry_after_seen,
                    bytes=len(resp.content),
                    error=f"suspiciously short body ({len(body.strip())} chars) after following redirects",
                )

            return FetchResult(
                url=url, final_url=current_url, status=FETCHED, html=body,
                http_status=resp.status_code, redirect_chain=redirect_chain,
                attempts=total_attempts, retry_after_seen=retry_after_seen,
                bytes=len(resp.content), content=resp.content,
            )

        return FetchResult(
            url=url, final_url=current_url, status=FAILED,
            redirect_chain=redirect_chain, attempts=total_attempts or 1,
            retry_after_seen=retry_after_seen, error="too many redirects",
        )

    except SsrfRejected as e:
        return FetchResult(
            url=url, final_url=current_url, status=FAILED,
            redirect_chain=redirect_chain, attempts=total_attempts or 1,
            retry_after_seen=retry_after_seen, error=f"blocked by SSRF guard: {e}",
        )
    except httpx.TimeoutException as e:
        return FetchResult(
            url=url, final_url=current_url, status=FAILED,
            redirect_chain=redirect_chain, attempts=total_attempts or 1,
            retry_after_seen=retry_after_seen, error=f"timeout: {e}",
        )
    except httpx.HTTPError as e:
        return FetchResult(
            url=url, final_url=current_url, status=FAILED,
            redirect_chain=redirect_chain, attempts=total_attempts or 1,
            retry_after_seen=retry_after_seen, error=f"HTTP error: {e}",
        )
    except Exception as e:
        log.exception(f"[scan.fetcher] unexpected error fetching {url}")
        return FetchResult(
            url=url, final_url=current_url, status=FAILED,
            redirect_chain=redirect_chain, attempts=total_attempts or 1,
            retry_after_seen=retry_after_seen, error=f"unexpected error: {e}",
        )
