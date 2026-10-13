"""
2B §2: fabricated_citation — does a cited domain exist at all?

A cited URL is fabricated when its domain does not resolve (DNS), or
resolves and its root returns no HTTP response within the timeout. ANY
HTTP status is a response: a 403 from a bot wall is a real site refusing
us, not an invented one.

The rules this keeps:

  * Once per domain per cycle. A DomainChecker lives for one scoring batch
    and memoises every answer it gives.
  * A 24-hour cache across batches, in soa_domain_checks. A re-score the
    same day reads the cache, which is also what makes a classify-only
    re-score produce identical output twice.
  * An honest UA: scan.fetcher.USER_AGENT, the same declared bot every
    other request this pipeline makes sends. One HEAD request to the root,
    no redirects followed, no body read. Never a scraper, never a browser.
  * Never a private address: a domain that resolves only to a private,
    loopback or link-local address is not requested (the scan fetcher's
    own SSRF rule), and is recorded as resolving but unchecked — never as
    fabricated.

Recorded on the ANSWER (soa_expectation_outcomes.flags), not on a span.
"""
import logging
import socket
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

CACHE_TTL = timedelta(hours=24)
DEFAULT_TIMEOUT_SECONDS = 8.0


@dataclass
class DomainCheck:
    domain: str
    #: False: the name does not resolve. None: not checked.
    resolves: Optional[bool]
    #: False: resolved, and the root gave no HTTP response in time.
    #: None: not requested (did not resolve, or a non-public address).
    responds: Optional[bool]
    detail: str
    checked_at: str

    @property
    def fabricated(self) -> bool:
        return self.resolves is False or (self.resolves is True and self.responds is False)

    def as_dict(self) -> dict:
        return {**asdict(self), 'fabricated': self.fabricated}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def default_resolver(domain: str):
    """IP addresses for a domain; raises socket.gaierror when it does not resolve."""
    return sorted({info[4][0] for info in socket.getaddrinfo(domain, 443, proto=socket.IPPROTO_TCP)})


def default_prober(url: str, timeout: float) -> Optional[int]:
    """One HEAD to the root with the declared bot UA. The HTTP status, or
    None when no response came back in time."""
    import httpx

    from scan.fetcher import USER_AGENT

    try:
        response = httpx.head(url, headers={'User-Agent': USER_AGENT},
                              timeout=timeout, follow_redirects=False)
    except Exception as exc:  # noqa: BLE001 - no response is the finding
        logger.info("[citation-check] %s: no response (%s)", url, type(exc).__name__)
        return None
    return response.status_code


class DbDomainCheckStore:
    """The 24-hour cache, in soa_domain_checks. One row per domain."""

    def __init__(self, engine=None) -> None:
        if engine is None:
            from soa_shared.database import engine as default_engine
            engine = default_engine
        self.engine = engine

    def get(self, domain: str) -> Optional[DomainCheck]:
        from sqlalchemy import text
        with self.engine.connect() as conn:
            row = conn.execute(text(
                "SELECT domain, resolves, responds, detail, checked_at "
                "FROM soa_domain_checks WHERE domain = :d"
            ), {'d': domain}).fetchone()
        if row is None:
            return None
        checked = _parse(row[4])
        return DomainCheck(row[0], row[1], row[2], row[3] or '',
                           checked.isoformat() if checked else str(row[4]))

    def put(self, check: DomainCheck) -> None:
        from sqlalchemy import text
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM soa_domain_checks WHERE domain = :d"), {'d': check.domain})
            conn.execute(text(
                "INSERT INTO soa_domain_checks (domain, resolves, responds, detail, checked_at) "
                "VALUES (:domain, :resolves, :responds, :detail, :checked_at)"
            ), {'domain': check.domain, 'resolves': check.resolves, 'responds': check.responds,
                'detail': check.detail[:500], 'checked_at': _parse(check.checked_at)})


class MemoryDomainCheckStore:
    def __init__(self, seed: Optional[Dict[str, DomainCheck]] = None) -> None:
        self.rows: Dict[str, DomainCheck] = dict(seed or {})

    def get(self, domain):
        return self.rows.get(domain)

    def put(self, check):
        self.rows[check.domain] = check


class DomainChecker:
    def __init__(self, *, resolver: Callable = None, prober: Callable = None,
                 store=None, clock: Callable[[], datetime] = None,
                 timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.resolver = resolver or default_resolver
        self.prober = prober or default_prober
        self.store = store
        self.clock = clock or _utcnow
        self.timeout_seconds = timeout_seconds
        self._memo: Dict[str, DomainCheck] = {}
        #: How many live checks this instance made: what the per-cycle
        #: and 24-hour rules are tested against.
        self.live_checks = 0

    def check(self, domain: str) -> DomainCheck:
        domain = (domain or '').strip().lower()
        if domain in self._memo:
            return self._memo[domain]
        cached = self.store.get(domain) if self.store is not None else None
        if cached is not None:
            checked = _parse(cached.checked_at)
            if checked is not None and self.clock() - checked < CACHE_TTL:
                self._memo[domain] = cached
                return cached
        result = self._live(domain)
        if self.store is not None:
            try:
                self.store.put(result)
            except Exception:  # noqa: BLE001 - a cache write never fails scoring
                logger.exception("[citation-check] could not cache %s", domain)
        self._memo[domain] = result
        return result

    def _live(self, domain: str) -> DomainCheck:
        from scan.fetcher import _is_disallowed_ip

        self.live_checks += 1
        now = self.clock().isoformat()
        try:
            addresses = list(self.resolver(domain))
        except (socket.gaierror, socket.herror, UnicodeError) as exc:
            return DomainCheck(domain, False, None, f"does not resolve ({exc})", now)
        if not addresses:
            return DomainCheck(domain, False, None, 'does not resolve (no addresses)', now)
        if all(_is_disallowed_ip(ip) for ip in addresses):
            return DomainCheck(domain, True, None,
                               'resolves only to a non-public address; not requested', now)
        for scheme in ('https', 'http'):
            status = self.prober(f'{scheme}://{domain}/', self.timeout_seconds)
            if status is not None:
                return DomainCheck(domain, True, True, f'{scheme} root answered HTTP {status}', now)
        return DomainCheck(domain, True, False,
                           f'resolves, but the root gave no HTTP response within '
                           f'{self.timeout_seconds:g}s', now)

    def fabricated(self, domains) -> list:
        """The checks for every domain that came back fabricated."""
        return [c.as_dict() for c in (self.check(d) for d in domains) if c.fabricated]
