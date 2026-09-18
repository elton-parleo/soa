"""
robots.txt must be matched on the bot's OWN token, not its User-Agent.

urllib.robotparser takes the text before the first "/" as the agent
token. BOT_UA begins "Mozilla/5.0 ...", so every can_fetch() call that
passed USER_AGENT was really asking about an agent named "Mozilla" — a
named `User-agent: ParleoAuditBot` group never matched, and only the `*`
group ever applied. Both directions were wrong:

  robots.txt                              was      correct
  ParleoAuditBot Disallow / + * Allow /   fetched  refused
  * Disallow / + ParleoAuditBot Allow /   refused  fetched

The bots page (apps/api/web/src/lite/BotsPage.jsx) tells site operators
that the first shape blocks us entirely, and CDN reviewers test exactly
that, so this is a truthfulness bug before it is a crawling one.

No real network access — socket.getaddrinfo and httpx.Client.get are
monkeypatched, following tests/scan/test_fetcher.py.
"""
import socket
import urllib.robotparser
from pathlib import Path

import httpx
import pytest

from scan import discovery, fetcher, scorer
from scan.discovery import PageCandidate
from scan.engine import PageScanData
from scan.fetcher import FetchBudget, FetchResult

ORIGIN = "https://store.example.com"
PRODUCT_URL = f"{ORIGIN}/products/blue-widget"

NAMED_DISALLOW = (
    "User-agent: ParleoAuditBot\nDisallow: /\n\n"
    "User-agent: *\nAllow: /\n"
)
NAMED_ALLOW = (
    "User-agent: *\nDisallow: /\n\n"
    "User-agent: ParleoAuditBot\nAllow: /\n"
)
# A named group that blocks only product paths. NAMED_DISALLOW's
# "Disallow: /" also refuses the sitemap, so discovery never reaches the
# candidate-exclusion counter at all — correct, but it exercises a
# different step. This shape isolates robots_excluded.
NAMED_DISALLOW_PRODUCTS = (
    "User-agent: ParleoAuditBot\nDisallow: /products/\n\n"
    "User-agent: *\nAllow: /\n"
)

SITEMAP_ONE_PRODUCT = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    f"<url><loc>{PRODUCT_URL}</loc></url>"
    "</urlset>"
)
PRODUCT_HTML = (
    "<html><head><title>Blue Widget</title></head><body>"
    "<h1>Blue Widget</h1><p>A real product page with enough copy to clear "
    "the short-body heuristic like any genuine page would.</p></body></html>"
)


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


def _parser(robots_txt: str) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"{ORIGIN}/robots.txt")
    rp.parse(robots_txt.splitlines())
    return rp


# ─── fetch() honors a named group ────────────────────────────────────────

def test_a_named_disallow_group_stops_the_fetch_before_any_request(monkeypatch):
    requested = []

    def fake_get(self, url, headers=None, **kw):
        requested.append(url)
        return httpx.Response(200, text=PRODUCT_HTML, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = fetcher.fetch(PRODUCT_URL, robot_parser=_parser(NAMED_DISALLOW))

    assert result.status == fetcher.ROBOTS_DISALLOWED
    assert requested == [], "a disallowed URL must never be requested"


def test_a_named_allow_group_beats_a_wildcard_disallow(monkeypatch):
    def fake_get(self, url, headers=None, **kw):
        return httpx.Response(200, text=PRODUCT_HTML, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = fetcher.fetch(PRODUCT_URL, robot_parser=_parser(NAMED_ALLOW))

    assert result.status == fetcher.FETCHED


def test_the_token_is_the_bot_name_not_the_full_user_agent():
    """The mechanism itself, stated once: these two disagree, and the
    bot name is the one that is right."""
    rp = _parser(NAMED_DISALLOW)
    assert rp.can_fetch(fetcher.USER_AGENT, PRODUCT_URL) is True   # matches "Mozilla"
    assert rp.can_fetch(fetcher.ROBOTS_USER_AGENT, PRODUCT_URL) is False
    assert fetcher.ROBOTS_USER_AGENT == "ParleoAuditBot"


# ─── discovery excludes named-disallowed candidates ──────────────────────

def _discovery_server(monkeypatch, robots_txt):
    def fake_get(self, url, headers=None, **kw):
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=robots_txt, request=httpx.Request("GET", url))
        if url.endswith("/sitemap.xml"):
            return httpx.Response(200, text=SITEMAP_ONE_PRODUCT, request=httpx.Request("GET", url))
        if url == PRODUCT_URL:
            return httpx.Response(200, text=PRODUCT_HTML, request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)


def _discover(monkeypatch, robots_txt):
    _discovery_server(monkeypatch, robots_txt)
    return discovery.discover_pages(
        ORIGIN, FetchBudget(),
        homepage_fetch=FetchResult(url=ORIGIN, status="fetched", html=PRODUCT_HTML, http_status=200),
    )


def test_discovery_excludes_a_product_url_its_named_group_disallows(monkeypatch):
    result = _discover(monkeypatch, NAMED_DISALLOW_PRODUCTS)

    assert result.sitemap_sampling["robots_excluded"] == 1
    assert not [c for c in result.candidates if c.kind == "product"]


def test_a_full_named_disallow_refuses_the_sitemap_itself(monkeypatch):
    """"Disallow: /" means everything, including the sitemap — so the
    run finds no product URLs at all rather than finding and then
    excluding them. Before the token fix this sitemap fetched happily."""
    result = _discover(monkeypatch, NAMED_DISALLOW)

    sitemap_fetch = next(f for f in result.all_fetches if f.url.endswith("/sitemap.xml"))
    assert sitemap_fetch.status == "robots_disallowed"
    assert result.sitemap_urls == []
    assert not [c for c in result.candidates if c.kind == "product"]


def test_discovery_keeps_a_product_url_its_named_group_allows(monkeypatch):
    result = _discover(monkeypatch, NAMED_ALLOW)

    assert result.sitemap_sampling["robots_excluded"] == 0
    assert [c.url for c in result.candidates if c.kind == "product"] == [PRODUCT_URL]


# ─── the Agent Access evidence line reflects it ──────────────────────────

def _score_agent_access(robots_txt):
    rp = _parser(robots_txt)
    disco = discovery.DiscoveryResult(
        robots_fetch=FetchResult(url=f"{ORIGIN}/robots.txt", status="fetched", html=robots_txt, http_status=200),
        robot_parser=rp,
        sitemap_urls=[PRODUCT_URL],
    )
    pages = [PageScanData(
        candidate=PageCandidate(url=PRODUCT_URL, kind="product"),
        fetch_result=FetchResult(url=PRODUCT_URL, status="fetched", html=PRODUCT_HTML, http_status=200),
        extracted=None,
    )]
    return scorer.score_f1_agent_access(disco, pages)


def test_agent_access_names_the_disallow_when_the_named_group_blocks_us():
    evidence = " ".join(_score_agent_access(NAMED_DISALLOW).evidence)
    assert "robots.txt disallows:" in evidence
    assert PRODUCT_URL in evidence


def test_agent_access_reports_allowed_when_the_named_group_allows_us():
    evidence = " ".join(_score_agent_access(NAMED_ALLOW).evidence)
    assert "robots.txt allows product paths" in evidence
    assert "robots.txt disallows:" not in evidence


# ─── grep-kill: the wrong token must not come back ───────────────────────

_BAD_CALL = "can_fetch(" + "USER_AGENT"  # never spelled whole, same rationale as test_identity.py


def test_grep_kill_no_scan_module_matches_robots_on_the_full_user_agent():
    """Same style as test_identity.py's grep-kill: the pattern is gone
    from scan/ and must stay gone. ROBOTS_USER_AGENT is a distinct name
    precisely so this test can tell the two apart — a future
    "simplification" back to USER_AGENT silently re-breaks a claim the
    bots page makes to CDN reviewers."""
    scan_dir = Path(__file__).resolve().parents[2] / "scan"
    assert scan_dir.is_dir(), f"unexpected scan dir guess: {scan_dir}"

    offenders = []
    for path in sorted(scan_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(errors="ignore")
        # ROBOTS_USER_AGENT legitimately ends in USER_AGENT; only the
        # bare-USER_AGENT call is the offender.
        if _BAD_CALL in text.replace("can_fetch(ROBOTS_USER_AGENT", "can_fetch(OK"):
            offenders.append(path.name)
    assert offenders == []
