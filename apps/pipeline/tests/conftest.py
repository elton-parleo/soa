import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)
# 2D: the shared test databases (sqlite, and the local Postgres CI runs).
sys.path.insert(0, os.path.join(_APP, '..', '..', 'packages', 'testing'))

import pytest

from scan import fetcher
from soa_pg_harness import any_engine, pg_engine  # noqa: F401  (pytest fixtures)


@pytest.fixture(autouse=True)
def _zero_retry_timing(monkeypatch):
    """A3: every test gets a fast, deterministic retry ladder — real
    sleeps here (backoff, first-request-429 cool-off) would make any
    test whose mocked response is 429/403/5xx take many seconds for no
    reason. Per-file fixtures still separately zero POLITENESS_DELAY_
    SECONDS and clear _last_fetch_at; this only covers the retry-ladder
    constants those fixtures don't know about."""
    monkeypatch.setattr(fetcher, "RETRY_BACKOFF_BASE_SECONDS", 0)
    monkeypatch.setattr(fetcher, "FIRST_REQUEST_429_COOLOFF_SECONDS", 0)
    fetcher._domain_seen.clear()
    fetcher._host_timeouts.clear()


@pytest.fixture(autouse=True)
def _no_real_dns_vendor_lookups(monkeypatch):
    """engine.py asks DNS who fronts a blocked/unreachable host
    (fetcher.dns_vendor_hint). Suites that monkeypatch getaddrinfo to a
    fixed address would otherwise still hit real reverse DNS for it —
    slow, and dependent on the network. Tests of the hint itself patch
    _dns_names_for back in explicitly."""
    monkeypatch.setattr(fetcher, "_dns_names_for", lambda hostname: [])


@pytest.fixture(autouse=True)
def _no_live_citation_checks(monkeypatch):
    """2B: the fabricated_citation check resolves and requests cited
    domains. Tests may not reach the network, so the scorer's default
    checker is off for the whole suite; tests of the check inject a fake
    resolver and prober (tests/test_citation_check.py)."""
    monkeypatch.setenv("SOA_CITATION_CHECK_ENABLED", "0")
