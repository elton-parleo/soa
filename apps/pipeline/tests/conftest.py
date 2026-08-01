import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from scan import fetcher


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
