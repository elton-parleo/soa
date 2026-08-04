"""
Tests for scan/fetcher.py's A1-A3 resilience layer: the one honest UA
+ standard headers on every request, per-domain jittered politeness
delay, and the 429/403/5xx retry ladder (Retry-After honored when
present, otherwise exponential backoff, plus a first-request-to-a-host
429 cool-off). No real network access — socket.getaddrinfo and
httpx.Client.get are monkeypatched; retry timing constants are zeroed
process-wide by tests/conftest.py's autouse _zero_retry_timing fixture,
so individual tests that care about the actual timing values restore
them explicitly and mock time.sleep to observe (never wait for) them.
"""
import inspect
import socket
import time

import httpx
import pytest

from scan import fetcher


def _fake_addrinfo(ip="93.184.216.34"):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


@pytest.fixture(autouse=True)
def reset_politeness_state(monkeypatch):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    fetcher._last_fetch_at.clear()
    fetcher._domain_seen.clear()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo())
    yield
    fetcher._last_fetch_at.clear()
    fetcher._domain_seen.clear()


# ─── A1: honest identification ──────────────────────────────────────────

def test_every_request_sends_the_honest_ua_and_standard_headers(monkeypatch):
    seen_headers = []

    def fake_get(self, url, headers=None, **kw):
        seen_headers.append(headers)
        return httpx.Response(200, text="hello world " * 20, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    fetcher.fetch("https://example.com/")

    assert seen_headers
    for headers in seen_headers:
        assert headers["User-Agent"] == (
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); "
            "compatible; ParleoAuditBot/1.0; +https://www.parleo.io/bots"
        )
        assert headers["Accept"] == fetcher.ACCEPT_HEADER
        assert headers["Accept-Language"] == fetcher.ACCEPT_LANGUAGE_HEADER


def test_fetch_never_falls_back_to_the_old_bare_ua_only_header_dict():
    """Regression: every call site inside fetch() must build headers via
    _request_headers() (UA + Accept + Accept-Language) — never the old
    inline {'User-Agent': USER_AGENT} dict that skipped Accept/
    Accept-Language, which would be a silent A1 regression a future edit
    could reintroduce without any test noticing."""
    source = inspect.getsource(fetcher)
    assert 'headers={"User-Agent": USER_AGENT}' not in source


# ─── A2: per-domain politeness (jitter + serialization) ────────────────

def test_jittered_delay_stays_within_plus_minus_40_percent(monkeypatch):
    monkeypatch.setattr(fetcher, "POLITENESS_JITTER_FRACTION", 0.40)
    base = 2.5
    samples = [fetcher._jittered_delay(base) for _ in range(500)]
    assert all(base * 0.6 - 1e-9 <= s <= base * 1.4 + 1e-9 for s in samples)
    assert min(samples) < base < max(samples)  # sanity: genuinely jittered, not constant


def test_jittered_delay_is_zero_for_non_positive_base():
    assert fetcher._jittered_delay(0) == 0.0
    assert fetcher._jittered_delay(-5) == 0.0


def test_politeness_wait_serializes_repeat_calls_to_the_same_hostname(monkeypatch):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 5.0)
    monkeypatch.setattr(fetcher, "POLITENESS_JITTER_FRACTION", 0.0)
    fetcher._last_fetch_at.clear()
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    fetcher._politeness_wait("example.com")
    fetcher._politeness_wait("example.com")

    assert len(sleeps) == 1
    assert 4.9 <= sleeps[0] <= 5.0


def test_politeness_wait_is_independent_per_hostname(monkeypatch):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 5.0)
    fetcher._last_fetch_at.clear()
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    fetcher._politeness_wait("a.example.com")
    fetcher._politeness_wait("b.example.com")

    assert sleeps == []


# ─── A5: env-tunable delay/retries ──────────────────────────────────────

def test_env_int_helper_parses_or_falls_back_never_raising(monkeypatch):
    monkeypatch.setenv("SCAN_FETCH_DELAY_MS", "9000")
    assert fetcher._env_int("SCAN_FETCH_DELAY_MS", 2500) == 9000

    monkeypatch.delenv("SCAN_FETCH_DELAY_MS", raising=False)
    assert fetcher._env_int("SCAN_FETCH_DELAY_MS", 2500) == 2500

    monkeypatch.setenv("SCAN_FETCH_DELAY_MS", "not-a-number")
    assert fetcher._env_int("SCAN_FETCH_DELAY_MS", 2500) == 2500


def test_scan_fetch_retries_is_read_live_not_captured_at_import(monkeypatch):
    """A retarget of SCAN_FETCH_RETRIES (directly, or via the env var it's
    seeded from) must take effect on the very next call — no closure is
    allowed to have captured the old value at import time."""
    monkeypatch.setattr(fetcher, "SCAN_FETCH_RETRIES", 5)
    calls = {"n": 0}

    def fake_get(self, url, headers=None, **kw):
        calls["n"] += 1
        return httpx.Response(503, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    resp, attempts, _ = fetcher._fetch_with_retries("https://example.com/", "example.com")
    assert attempts == 5
    assert calls["n"] == 5


# ─── A3: retry ladder ────────────────────────────────────────────────────

def test_non_retryable_status_returns_immediately_without_retrying(monkeypatch):
    monkeypatch.setattr(fetcher, "SCAN_FETCH_RETRIES", 3)
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    def fake_get(self, url, headers=None, **kw):
        return httpx.Response(404, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    resp, attempts, retry_after = fetcher._fetch_with_retries("https://example.com/", "example.com")
    assert attempts == 1
    assert resp.status_code == 404
    assert sleeps == []


def test_retry_ladder_uses_exponential_backoff_when_no_retry_after_header(monkeypatch):
    monkeypatch.setattr(fetcher, "RETRY_BACKOFF_BASE_SECONDS", 4.0)
    monkeypatch.setattr(fetcher, "SCAN_FETCH_RETRIES", 3)
    fetcher._domain_seen.add("example.com")  # first-request cool-off doesn't apply here
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    codes = iter([503, 503, 200])

    def fake_get(self, url, headers=None, **kw):
        return httpx.Response(next(codes), text="ok", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    resp, attempts, retry_after = fetcher._fetch_with_retries("https://example.com/", "example.com")
    assert attempts == 3
    assert resp.status_code == 200
    assert sleeps == [4.0, 8.0]  # doubling each attempt
    assert retry_after is None


def test_retry_after_header_is_honored_and_capped_at_30s(monkeypatch):
    monkeypatch.setattr(fetcher, "SCAN_FETCH_RETRIES", 2)
    fetcher._domain_seen.add("example.com")
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    def fake_get(self, url, headers=None, **kw):
        return httpx.Response(
            429, text="", headers={"Retry-After": "9999"}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    resp, attempts, retry_after = fetcher._fetch_with_retries("https://example.com/", "example.com")
    assert attempts == 2  # exhausted at SCAN_FETCH_RETRIES
    assert retry_after == 30.0
    assert sleeps == [30.0]


def test_first_request_429_triggers_one_cooloff_before_the_ladder(monkeypatch):
    monkeypatch.setattr(fetcher, "SCAN_FETCH_RETRIES", 3)
    monkeypatch.setattr(fetcher, "FIRST_REQUEST_429_COOLOFF_SECONDS", 20.0)
    monkeypatch.setattr(fetcher, "RETRY_BACKOFF_BASE_SECONDS", 4.0)
    fetcher._domain_seen.clear()
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    codes = iter([429, 429, 200])

    def fake_get(self, url, headers=None, **kw):
        return httpx.Response(next(codes), text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    resp, attempts, retry_after = fetcher._fetch_with_retries("https://example.com/", "example.com")
    assert attempts == 3
    assert sleeps == [20.0, 4.0, 8.0]  # cool-off, then the ordinary ladder continues underneath it
    assert "example.com" in fetcher._domain_seen


def test_second_domain_first_request_429_is_unaffected_by_a_prior_domains_history(monkeypatch):
    """The cool-off is keyed per hostname — a different domain's first
    429 this process is still its own 'first request', regardless of
    what already happened to some other domain."""
    monkeypatch.setattr(fetcher, "SCAN_FETCH_RETRIES", 1)
    monkeypatch.setattr(fetcher, "FIRST_REQUEST_429_COOLOFF_SECONDS", 20.0)
    fetcher._domain_seen.clear()
    fetcher._domain_seen.add("already-seen.example.com")
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    def fake_get(self, url, headers=None, **kw):
        return httpx.Response(429, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    # SCAN_FETCH_RETRIES=1 means the ladder returns after the first
    # attempt regardless — this only proves _domain_seen tracking is
    # genuinely per-hostname, not a single global flag.
    fetcher._fetch_with_retries("https://new-domain.example.com/", "new-domain.example.com")
    assert "new-domain.example.com" in fetcher._domain_seen
    assert "already-seen.example.com" in fetcher._domain_seen


# ─── A4: structured per-URL fetch outcome on FetchResult ────────────────

def test_fetch_records_attempts_and_bytes_on_eventual_success(monkeypatch):
    monkeypatch.setattr(fetcher, "SCAN_FETCH_RETRIES", 3)
    calls = {"n": 0}
    body = "hello world, this is a real page body here"

    def fake_get(self, url, headers=None, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = fetcher.fetch("https://example.com/")
    assert result.status == fetcher.FETCHED
    assert result.attempts == 3
    assert result.bytes == len(body)
    assert result.retry_after_seen is None


def test_fetch_records_all_attempts_when_blocked_status_survives_the_full_ladder(monkeypatch):
    monkeypatch.setattr(fetcher, "SCAN_FETCH_RETRIES", 3)

    def fake_get(self, url, headers=None, **kw):
        return httpx.Response(429, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = fetcher.fetch("https://example.com/")
    assert result.status == fetcher.BLOCKED
    assert result.http_status == 429
    assert result.attempts == 3


def test_fetch_records_retry_after_seen_on_the_result(monkeypatch):
    monkeypatch.setattr(fetcher, "SCAN_FETCH_RETRIES", 2)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def fake_get(self, url, headers=None, **kw):
        return httpx.Response(
            429, text="", headers={"Retry-After": "12"}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = fetcher.fetch("https://example.com/")
    assert result.status == fetcher.BLOCKED
    assert result.retry_after_seen == 12.0
