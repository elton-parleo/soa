"""
robots.txt Crawl-delay is honored — the second claim bots.parleo.io makes
about this crawler ("Honors robots.txt, including Crawl-delay"), which
until now it did not do at all.

Crawl-delay is a FLOOR on the per-host gap _politeness_wait already
keeps, never a replacement: a delay below our own 2.5 s politeness delay
never speeds us up, and no jitter is applied on top of a site's declared
number. A delay above SCAN_CRAWL_DELAY_CAP_SECONDS ends the fetch rather
than being silently capped.

time.sleep is mocked to record (never wait for) the gaps, and
time.monotonic is driven by a controllable clock, following the existing
politeness tests in test_fetcher.py.
"""
import socket
import time
import urllib.robotparser

import httpx
import pytest

from scan import engine, fetcher

ORIGIN = "https://store.example.com"
PAGE_A = f"{ORIGIN}/products/a"
PAGE_B = f"{ORIGIN}/products/b"
BODY = "a real page body with plenty of copy to clear the short-body heuristic " * 3


@pytest.fixture(autouse=True)
def reset_politeness_state(monkeypatch):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    fetcher._last_fetch_at.clear()
    fetcher._domain_seen.clear()
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    yield
    fetcher._last_fetch_at.clear()
    fetcher._domain_seen.clear()


def _parser(robots_txt: str):
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"{ORIGIN}/robots.txt")
    rp.parse(robots_txt.splitlines())
    return rp


def _robots(named_delay=None, star_delay=None, *, named_raw=None):
    star = "User-agent: *\nAllow: /\n"
    if star_delay is not None:
        star += f"Crawl-delay: {star_delay}\n"
    named = "\nUser-agent: ParleoAuditBot\nAllow: /\n"
    if named_raw is not None:
        named += f"Crawl-delay: {named_raw}\n"
    elif named_delay is not None:
        named += f"Crawl-delay: {named_delay}\n"
    return star + named


@pytest.fixture
def frozen_clock(monkeypatch):
    """A clock that only advances when a recorded sleep says it should —
    so the second fetch sees zero elapsed time and the full gap is
    visible in `sleeps`."""
    now = {"t": 1000.0}
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        now["t"] += seconds

    monkeypatch.setattr(time, "sleep", fake_sleep)
    monkeypatch.setattr(time, "monotonic", lambda: now["t"])
    return sleeps


def _fetch_twice(monkeypatch, robots_txt):
    def fake_get(self, url, headers=None, **kw):
        return httpx.Response(200, text=BODY, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    rp = _parser(robots_txt)
    return fetcher.fetch(PAGE_A, robot_parser=rp), fetcher.fetch(PAGE_B, robot_parser=rp)


# ─── the floor is honored ────────────────────────────────────────────────

def test_a_crawl_delay_above_our_politeness_delay_sets_the_gap(monkeypatch, frozen_clock):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 2.5)

    first, second = _fetch_twice(monkeypatch, _robots(named_delay=10))

    assert first.status == fetcher.FETCHED
    assert second.status == fetcher.FETCHED
    # The first request to a host has nothing to be spaced from.
    assert frozen_clock == [10.0]
    assert first.crawl_delay_seconds == 10.0
    assert second.crawl_delay_seconds == 10.0


def test_a_crawl_delay_below_our_politeness_delay_never_speeds_us_up(monkeypatch, frozen_clock):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 2.5)
    monkeypatch.setattr(fetcher, "POLITENESS_JITTER_FRACTION", 0.0)

    _fetch_twice(monkeypatch, _robots(named_delay=1))

    assert frozen_clock == [2.5]


def test_the_politeness_gap_is_still_jittered_when_crawl_delay_is_lower(monkeypatch, frozen_clock):
    """The floor only ever raises the gap — below it, the ordinary
    jittered politeness delay is still what runs."""
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 2.5)
    monkeypatch.setattr(fetcher, "POLITENESS_JITTER_FRACTION", 0.40)

    _fetch_twice(monkeypatch, _robots(named_delay=1))

    assert len(frozen_clock) == 1
    assert 2.5 * 0.6 - 1e-9 <= frozen_clock[0] <= 2.5 * 1.4 + 1e-9


def test_a_star_group_crawl_delay_applies_when_we_have_no_named_one(monkeypatch, frozen_clock):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 2.5)

    first, _ = _fetch_twice(monkeypatch, "User-agent: *\nAllow: /\nCrawl-delay: 10\n")

    assert frozen_clock == [10.0]
    assert first.crawl_delay_seconds == 10.0


def test_our_own_group_beats_the_star_group(monkeypatch, frozen_clock):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 2.5)

    first, _ = _fetch_twice(monkeypatch, _robots(named_delay=20, star_delay=5))

    assert frozen_clock == [20.0]
    assert first.crawl_delay_seconds == 20.0


# ─── the cap refuses rather than silently capping ────────────────────────

def test_a_crawl_delay_above_the_cap_refuses_the_fetch(monkeypatch):
    requested = []

    def fake_get(self, url, headers=None, **kw):
        requested.append(url)
        return httpx.Response(200, text=BODY, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setattr(fetcher, "SCAN_CRAWL_DELAY_CAP_SECONDS", 30)

    result = fetcher.fetch(PAGE_A, robot_parser=_parser(_robots(named_delay=120)))

    assert result.status == fetcher.ROBOTS_DISALLOWED
    assert requested == [], "a capped-out delay must not produce a request"
    assert result.crawl_delay_seconds == 120.0
    # Both numbers, so the record says what was asked and what we allow.
    assert "120" in result.error and "30" in result.error


def test_the_cap_is_read_live_not_captured_at_import(monkeypatch):
    """Same contract as SCAN_FETCH_RETRIES — a retarget takes effect on
    the very next call, so the ceiling can be retuned without a deploy."""
    def fake_get(self, url, headers=None, **kw):
        return httpx.Response(200, text=BODY, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setattr(fetcher, "SCAN_CRAWL_DELAY_CAP_SECONDS", 200)

    result = fetcher.fetch(PAGE_A, robot_parser=_parser(_robots(named_delay=120)))

    assert result.status == fetcher.FETCHED
    assert result.crawl_delay_seconds == 120.0


# ─── degrades, never raises ──────────────────────────────────────────────

@pytest.mark.parametrize("robots_txt,expected", [
    (_robots(named_raw="abc"), None),          # unparseable
    (_robots(named_raw="-5"), None),           # nonsensical
    (_robots(), None),                          # no directive at all
    ("User-agent: *\nAllow: /\n", None),
])
def test_an_unusable_crawl_delay_reads_as_no_floor(robots_txt, expected):
    assert fetcher._robots_crawl_delay(_parser(robots_txt)) is expected


def test_no_parser_at_all_reads_as_no_floor():
    assert fetcher._robots_crawl_delay(None) is None


def test_the_helper_never_raises_on_a_broken_parser():
    class Exploding:
        def crawl_delay(self, agent):
            raise RuntimeError("boom")

    assert fetcher._robots_crawl_delay(Exploding()) is None


def test_an_unparseable_delay_still_fetches_normally(monkeypatch, frozen_clock):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 2.5)
    monkeypatch.setattr(fetcher, "POLITENESS_JITTER_FRACTION", 0.0)

    first, second = _fetch_twice(monkeypatch, _robots(named_raw="abc"))

    assert first.status == fetcher.FETCHED
    assert second.status == fetcher.FETCHED
    assert frozen_clock == [2.5]
    assert first.crawl_delay_seconds is None


# ─── serialized onto the scan row ────────────────────────────────────────

def test_fetch_entry_carries_the_honored_crawl_delay():
    entry = engine._fetch_entry(
        fetcher.FetchResult(url=PAGE_A, status="fetched", http_status=200, crawl_delay_seconds=10.0)
    )
    assert entry["crawl_delay_seconds"] == 10.0


def test_fetch_entry_crawl_delay_defaults_to_none():
    entry = engine._fetch_entry(fetcher.FetchResult(url=PAGE_A, status="fetched"))
    assert entry["crawl_delay_seconds"] is None
