"""
discovery.py — page discovery for the Agent Scan engine.

Finds robots.txt, resolves declared (or conventional) sitemaps, and
ranks candidate pages to fetch: the homepage, 1-2 product pages, a
loyalty/rewards page, and a shipping/returns page. Product pages are
recognized by URL shape (/products/, /p/, /dp/) against sitemap and
homepage links; loyalty/shipping pages by nav/footer link text.
"""
import logging
import re
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from .fetcher import FetchBudget, FetchResult, fetch

log = logging.getLogger(__name__)

PRODUCT_URL_PATTERNS = (
    re.compile(r"/products?/"),
    re.compile(r"/p/"),
    re.compile(r"/dp/"),
)
LOYALTY_LINK_KEYWORDS = (
    "reward", "loyalty", "member", "perk", "insider", "circle", "plus",
)
SHIPPING_LINK_KEYWORDS = (
    "shipping", "returns", "return policy", "delivery",
)

MAX_PRODUCT_PAGES = 2


@dataclass
class PageCandidate:
    url: str
    kind: str  # homepage | product | loyalty | shipping_returns


@dataclass
class DiscoveryResult:
    robots_fetch: FetchResult
    robot_parser: Optional[urllib.robotparser.RobotFileParser]
    sitemap_urls: list = field(default_factory=list)
    candidates: list = field(default_factory=list)  # list[PageCandidate]
    homepage_fetch: Optional[FetchResult] = None


def _build_robot_parser(base_url: str):
    """Never raises — a missing/unfetchable robots.txt yields (None, FetchResult)."""
    robots_url = urljoin(base_url, "/robots.txt")
    result = fetch(robots_url, robot_parser=None)
    if result.status != "fetched" or not result.html:
        return None, result
    try:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.parse(result.html.splitlines())
        return rp, result
    except Exception:
        log.exception(f"[scan.discovery] failed to parse robots.txt for {base_url}")
        return None, result


def _sitemap_urls_from_robots(robot_parser) -> list:
    if robot_parser is None:
        return []
    try:
        return list(robot_parser.site_maps() or [])
    except Exception:
        return []


def _parse_sitemap_urls(xml_text: str) -> list:
    """Never raises — malformed sitemap XML just yields an empty list."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    except Exception:
        return []

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [el.text.strip() for el in root.findall(".//sm:loc", ns) if el.text]
    if not urls:
        urls = [el.text.strip() for el in root.findall(".//loc") if el.text]
    return urls


def _looks_like_product_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(p.search(path) for p in PRODUCT_URL_PATTERNS)


def _find_links_by_keyword(html: str, base_url: str, keywords) -> list:
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []

    matches = []
    for a in soup.find_all("a", href=True):
        text = (a.get_text() or "").strip().lower()
        href = a["href"]
        if any(kw in text or kw in href.lower() for kw in keywords):
            matches.append(urljoin(base_url, href))
    return matches


def _find_product_links(html: str, base_url: str) -> list:
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []

    matches = []
    for a in soup.find_all("a", href=True):
        full_url = urljoin(base_url, a["href"])
        if _looks_like_product_url(full_url):
            matches.append(full_url)
    return matches


def discover_pages(base_url: str, budget: FetchBudget) -> DiscoveryResult:
    """
    Never raises — every internal step degrades to an empty/partial
    result rather than propagating. base_url must already be a
    normalized http(s)://host URL (see engine.py::_normalize_input).

    Sitemap/robots.txt fetches don't count against the page-fetch
    budget; only the homepage and the selected candidate pages do —
    "MAX 12 page fetches" governs pages a shopper/agent would actually
    read, not crawler infrastructure lookups.
    """
    try:
        robot_parser, robots_fetch = _build_robot_parser(base_url)

        sitemap_urls: list = []
        for sm_url in _sitemap_urls_from_robots(robot_parser):
            sm_result = fetch(sm_url, robot_parser=robot_parser)
            if sm_result.status == "fetched" and sm_result.html:
                sitemap_urls.extend(_parse_sitemap_urls(sm_result.html))

        if not sitemap_urls:
            fallback_sitemap = urljoin(base_url, "/sitemap.xml")
            sm_result = fetch(fallback_sitemap, robot_parser=robot_parser)
            if sm_result.status == "fetched" and sm_result.html:
                sitemap_urls.extend(_parse_sitemap_urls(sm_result.html))

        homepage_fetch = None
        if budget.has_capacity():
            budget.consume()
            homepage_fetch = fetch(base_url, robot_parser=robot_parser)

        candidates = [PageCandidate(url=base_url, kind="homepage")]

        product_urls = [u for u in sitemap_urls if _looks_like_product_url(u)]
        homepage_html = homepage_fetch.html if homepage_fetch and homepage_fetch.status == "fetched" else None

        if not product_urls and homepage_html:
            product_urls = _find_product_links(homepage_html, base_url)

        seen = set()
        for u in product_urls:
            if u in seen:
                continue
            seen.add(u)
            candidates.append(PageCandidate(url=u, kind="product"))
            if len([c for c in candidates if c.kind == "product"]) >= MAX_PRODUCT_PAGES:
                break

        if homepage_html:
            loyalty_links = _find_links_by_keyword(homepage_html, base_url, LOYALTY_LINK_KEYWORDS)
            if loyalty_links:
                candidates.append(PageCandidate(url=loyalty_links[0], kind="loyalty"))

            shipping_links = _find_links_by_keyword(homepage_html, base_url, SHIPPING_LINK_KEYWORDS)
            if shipping_links:
                candidates.append(PageCandidate(url=shipping_links[0], kind="shipping_returns"))

        return DiscoveryResult(
            robots_fetch=robots_fetch,
            robot_parser=robot_parser,
            sitemap_urls=sitemap_urls,
            candidates=candidates,
            homepage_fetch=homepage_fetch,
        )
    except Exception:
        log.exception(f"[scan.discovery] discovery failed for {base_url}")
        return DiscoveryResult(
            robots_fetch=FetchResult(url=urljoin(base_url, "/robots.txt"), status="failed", error="discovery error"),
            robot_parser=None,
            sitemap_urls=[],
            candidates=[PageCandidate(url=base_url, kind="homepage")],
            homepage_fetch=None,
        )
