"""
discovery.py — canonical host resolution and page discovery for the
Agent Scan engine.

Stage 11 (H1/H2): resolve_canonical_origin() fetches the submitted
URL's homepage, follows redirects (fetcher.py re-validates SSRF and
same-registrable-domain on every hop), and adopts the FINAL resolved
origin as the canonical origin for the entire scan — allbirds.com ->
https://www.allbirds.com; a store that redirects www->apex resolves
the other way. Every subsequent URL discover_pages() builds (robots.txt,
sitemap fallback, /llms.txt, /.well-known/*, discovered paths) uses
that one origin — never a mix of apex and www.

Stage 11 (D1): robots.txt, sitemap (recursed through Shopify-shaped
<sitemapindex> files), well-known-probe, and collection-hop fetches
all draw from their own small DISCOVERY_FETCH_BUDGET, independent of
the 12-fetch content-page budget passed in by the caller — a large or
malicious sitemapindex can never starve PDP sampling of its budget.

Product pages are recognized by URL shape (/products/, /p/, /dp/,
/item/) against sitemap and homepage/collection links; loyalty/shipping
pages by nav/footer link text; collection/category pages (/collections/,
/c/, /category/) are a fallback discovery hop (D2) when sitemap
traversal finds no products at all.

Sitemap-sampler rewrite (hotfix 5): a <sitemapindex> child is no longer
trusted by filename alone (the incident this fixes — a decoy child
whose name happened to contain "product" starved the real catalog
child of its share of the fetch budget). Up to
SITEMAP_CHILD_PROBE_LIMIT children are actually fetched and parsed
(gzip-aware), and the one with the highest product-URL density is
selected; filename is only a tiebreaker between equally-dense results.
The whole sampling decision — every child probed, which one was
chosen, how many candidates it yielded, how many were excluded by
robots.txt — is recorded on DiscoveryResult.sitemap_sampling for
engine.py to serialize onto the scan row (debuggability was the whole
point; this incident was invisible in logs).
"""
import gzip
import logging
import re
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from .fetcher import USER_AGENT, FetchBudget, FetchResult, fetch

log = logging.getLogger(__name__)

# Single-sourced (grep-tested): the one place product-shaped URLs are
# defined — scorer.py and anywhere else that needs this imports it from
# here rather than keeping a second, driftable copy.
PRODUCT_URL_PATTERNS = (
    re.compile(r"/products?/"),
    re.compile(r"/p/"),
    re.compile(r"/dp/"),
    re.compile(r"/item/"),
)
COLLECTION_URL_PATTERNS = (
    re.compile(r"/collections?/"),
    re.compile(r"/c/"),
    re.compile(r"/category/"),
)
LOYALTY_LINK_KEYWORDS = (
    "reward", "loyalty", "member", "perk", "insider", "circle", "plus",
)
SHIPPING_LINK_KEYWORDS = (
    "shipping", "returns", "return policy", "delivery",
)

MAX_PRODUCT_PAGES = 2
LLMS_TXT_PATH = "/llms.txt"
MCP_WELL_KNOWN_PATH = "/.well-known/mcp.json"
DISCOVERY_FETCH_BUDGET = 6
# S1.a: bounds both how many TOP-LEVEL declared sitemaps are followed
# and how many children of one <sitemapindex> are actually probed —
# same constant, same reasoning (a large or malicious sitemap tree can
# never consume more than this many fetches trying to find products).
SITEMAP_CHILD_PROBE_LIMIT = 6
GZIP_MAGIC = b"\x1f\x8b"


@dataclass
class PageCandidate:
    url: str
    kind: str  # homepage | product | loyalty | shipping_returns | llms_txt | mcp_well_known


@dataclass
class DiscoveryResult:
    robots_fetch: FetchResult
    robot_parser: Optional[urllib.robotparser.RobotFileParser]
    sitemap_urls: list = field(default_factory=list)     # final PAGE urls only — never child-sitemap urls
    candidates: list = field(default_factory=list)        # list[PageCandidate]
    homepage_fetch: Optional[FetchResult] = None
    llms_txt_fetch: Optional[FetchResult] = None
    mcp_well_known_fetch: Optional[FetchResult] = None
    products_found: int = 0
    discovery_path: str = "none"   # sitemap | collection_hop | homepage | none
    all_fetches: list = field(default_factory=list)        # every FetchResult discovery performed (F3 observability)
    sitemap_index_entries: list = field(default_factory=list)  # every child-sitemap URL seen (site_typing T1)
    # Sitemap-sampler stage (hotfix 5, S1.d): the sampling decision,
    # recorded regardless of outcome — children_probed is one entry per
    # child actually fetched (url, is_index, url_count, product_count,
    # or a "skipped" reason for gzip/parse/fetch failures);
    # child_chosen/candidates_found describe the winning child (None/0
    # if nothing usable was found); robots_excluded is how many
    # candidate product URLs were dropped because robots.txt disallows
    # them for our reader, BEFORE the MAX_PRODUCT_PAGES sample is taken.
    sitemap_sampling: dict = field(default_factory=lambda: {
        "children_probed": [], "child_chosen": None, "candidates_found": 0, "robots_excluded": 0,
    })


@dataclass
class CanonicalResolution:
    origin: Optional[str]
    homepage_fetch: FetchResult
    cross_domain_flag: Optional[str] = None


def resolve_canonical_origin(input_url: str) -> CanonicalResolution:
    """
    Stage 11 (H1/H2): fetches input_url's homepage and follows redirects
    (fetcher.py's own guard re-validates SSRF and same-registrable-
    domain on every hop). The final resolved origin becomes the
    canonical origin for the whole scan.

    Never raises. A cross-domain redirect stop, SSRF abort, timeout, or
    any other fetch failure still returns a best-effort origin (the
    original input's own scheme+host) so discovery can still attempt
    something against it — a scan degrades to a low or failed score,
    never an exception, and the cross-domain case is recorded on
    cross_domain_flag rather than silently adopting the other domain.
    """
    homepage_fetch = fetch(input_url, robot_parser=None, check_short_body=True)

    cross_domain_flag = None
    if homepage_fetch.error and "cross-domain redirect stopped" in homepage_fetch.error:
        cross_domain_flag = homepage_fetch.error

    origin = None
    if homepage_fetch.status == "fetched" and homepage_fetch.final_url:
        parsed = urlparse(homepage_fetch.final_url)
        if parsed.hostname:
            origin = f"{parsed.scheme}://{parsed.netloc}"

    if origin is None:
        parsed = urlparse(input_url)
        if parsed.hostname:
            origin = f"{parsed.scheme}://{parsed.netloc}"

    return CanonicalResolution(origin=origin, homepage_fetch=homepage_fetch, cross_domain_flag=cross_domain_flag)


def _sitemap_priority(url: str) -> int:
    """Tiebreaker ONLY (S1.a) — never the selector. Used to break a tie
    between two children with equal product-URL density."""
    lu = url.lower()
    if "product" in lu:
        return 0
    if "collection" in lu:
        return 1
    return 2


def _parse_sitemap(xml_text: str):
    """Returns (is_index, urls). Never raises — malformed sitemap XML
    yields (False, [])."""
    try:
        root = ElementTree.fromstring(xml_text)
    except Exception:
        return False, []

    try:
        tag = root.tag.rsplit("}", 1)[-1]
        is_index = tag == "sitemapindex"
    except Exception:
        is_index = False

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    try:
        urls = [el.text.strip() for el in root.findall(".//sm:loc", ns) if el.text]
        if not urls:
            urls = [el.text.strip() for el in root.findall(".//loc") if el.text]
    except Exception:
        urls = []
    return is_index, urls


def _sitemap_xml_text(url: str, result: FetchResult):
    """S1.b: returns (xml_text, skip_reason) — exactly one is None.
    Gzip-aware: a .gz-named URL, or a body starting with the gzip magic
    bytes (a backstop for a mislabeled URL), is decompressed first —
    the already-decoded `html` text is useless for a gzip body (its raw
    bytes were never valid UTF-8 to begin with). Never raises; a
    corrupt .gz is a skip reason, never a crash."""
    looks_gzipped = url.lower().endswith(".gz") or (result.content or b"")[:2] == GZIP_MAGIC
    if not looks_gzipped:
        if result.html:
            return result.html, None
        return None, "empty body"

    if not result.content:
        return None, "gzip sitemap had no raw body to decompress"
    try:
        decompressed = gzip.decompress(result.content)
    except Exception as e:
        return None, f"corrupt gzip ({e})"
    try:
        return decompressed.decode("utf-8", errors="replace"), None
    except Exception as e:
        return None, f"gzip decoded but not valid text ({e})"


def _fetch_and_parse_sitemap(url: str, robot_parser, discovery_budget: FetchBudget, all_fetches: list, sampling_log: dict):
    """Fetches and parses one sitemap URL (gzip-aware). Never raises.
    Returns (is_index, urls) on success, else None — every outcome
    (including budget exhaustion, fetch failure, and any parse/gzip
    failure) is recorded in sampling_log["children_probed"] with a
    reason, never silently dropped (S1.d)."""
    if not discovery_budget.has_capacity():
        sampling_log["children_probed"].append({"url": url, "skipped": "discovery budget exhausted"})
        return None
    discovery_budget.consume()
    try:
        result = fetch(url, robot_parser=robot_parser)
    except Exception:
        log.exception(f"[scan.discovery] unexpected error fetching sitemap {url}")
        sampling_log["children_probed"].append({"url": url, "skipped": "unexpected fetch error"})
        return None
    all_fetches.append(result)

    if result.status != "fetched":
        sampling_log["children_probed"].append({"url": url, "skipped": f"fetch failed (status={result.status})"})
        return None

    xml_text, skip_reason = _sitemap_xml_text(url, result)
    if xml_text is None:
        sampling_log["children_probed"].append({"url": url, "skipped": skip_reason})
        return None

    is_index, urls = _parse_sitemap(xml_text)
    if not is_index and not urls:
        sampling_log["children_probed"].append({"url": url, "skipped": "no URLs found (empty or unparseable)"})
        return None

    sampling_log["children_probed"].append({
        "url": url, "is_index": is_index, "url_count": len(urls),
        "product_count": (sum(1 for u in urls if _looks_like_product_url(u)) if not is_index else None),
    })
    return is_index, urls


def _select_best_sitemap_child(child_urls: list, robot_parser, discovery_budget: FetchBudget, all_fetches: list, sampling_log: dict) -> list:
    """
    S1.a: probes up to SITEMAP_CHILD_PROBE_LIMIT children (declaration
    order — filename never decides WHICH to try, only breaks a tie
    among results that parsed with equal product-URL density) and
    selects the one with the highest density. Returns that child's page
    URLs, or [] if nothing usable was found among the probed children.
    """
    candidates = []  # (density, product_count, url, urls)
    probed = 0
    for child_url in child_urls:
        if probed >= SITEMAP_CHILD_PROBE_LIMIT or not discovery_budget.has_capacity():
            break
        probed += 1
        parsed = _fetch_and_parse_sitemap(child_url, robot_parser, discovery_budget, all_fetches, sampling_log)
        if parsed is None:
            continue
        is_index, urls = parsed
        if is_index or not urls:
            continue
        product_count = sum(1 for u in urls if _looks_like_product_url(u))
        density = product_count / len(urls)
        candidates.append((density, product_count, child_url, urls))

    if not candidates:
        return []

    candidates.sort(key=lambda c: (-c[0], _sitemap_priority(c[2])))
    best_density, best_product_count, best_url, best_urls = candidates[0]
    sampling_log["child_chosen"] = best_url
    sampling_log["candidates_found"] = best_product_count
    return best_urls


def _resolve_sitemaps(
    initial_urls: list, robot_parser, discovery_budget: FetchBudget,
    all_fetches: list, index_entries: list, sampling_log: dict,
) -> list:
    """
    Sitemap-sampler rewrite (hotfix 5, S1.a): fetches each declared
    (top-level) sitemap, bounded by SITEMAP_CHILD_PROBE_LIMIT and
    discovery_budget. A FLAT sitemap's URLs are used directly
    (unchanged fast path for a simple, unindexed store). A
    <sitemapindex>'s children are NEVER trusted by filename — see
    _select_best_sitemap_child. Never raises. Returns the flat list of
    real PAGE URLs sampled — child-sitemap URLs themselves are never
    returned here, but every one declared by an index (probed or not)
    is still appended to index_entries for site_typing.py's T1 signal
    check — a Shopify sitemapindex naming "sitemap_products_1.xml" is
    itself commerce evidence, even if that exact child was never the
    one actually chosen.
    """
    page_urls: list = []
    queue = list(initial_urls)
    seen: set = set()
    followed = 0

    while queue and followed < SITEMAP_CHILD_PROBE_LIMIT and discovery_budget.has_capacity():
        sm_url = queue.pop(0)
        if sm_url in seen:
            continue
        seen.add(sm_url)
        followed += 1

        parsed = _fetch_and_parse_sitemap(sm_url, robot_parser, discovery_budget, all_fetches, sampling_log)
        if parsed is None:
            continue
        is_index, urls = parsed

        if not is_index:
            page_urls.extend(urls)
            continue

        index_entries.extend(urls)
        page_urls.extend(_select_best_sitemap_child(urls, robot_parser, discovery_budget, all_fetches, sampling_log))

    return page_urls


def _looks_like_product_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(p.search(path) for p in PRODUCT_URL_PATTERNS)


def _looks_like_collection_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(p.search(path) for p in COLLECTION_URL_PATTERNS)


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


def _find_links_matching(html: str, base_url: str, matcher) -> list:
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []

    matches = []
    for a in soup.find_all("a", href=True):
        full_url = urljoin(base_url, a["href"])
        if matcher(full_url):
            matches.append(full_url)
    return matches


def discover_pages(
    base_url: str,
    budget: FetchBudget,
    *,
    homepage_fetch: Optional[FetchResult] = None,
) -> DiscoveryResult:
    """
    Never raises — every internal step degrades to an empty/partial
    result rather than propagating. base_url must already be the
    resolved canonical origin (see resolve_canonical_origin) — every
    relative URL built here uses this one origin (H2).

    homepage_fetch, when given, is the already-completed fetch from
    canonical-origin resolution — reused here (not re-fetched, not
    re-charged against any budget, since engine.py already charged it
    against the content-page budget). When omitted (e.g. a caller using
    this function standalone), discover_pages fetches the homepage
    itself, charged against `budget` — the same content-page budget
    used for product/loyalty/shipping pages, matching pre-Stage-11
    behavior for that one fetch.

    Every OTHER discovery-internal fetch (robots.txt, sitemap traversal,
    well-known probes, the collection hop) draws from its own separate
    DISCOVERY_FETCH_BUDGET, per Stage 11 D1.
    """
    all_fetches: list = []
    discovery_budget = FetchBudget(max_fetches=DISCOVERY_FETCH_BUDGET)

    try:
        robots_url = urljoin(base_url, "/robots.txt")
        robot_parser = None
        robots_fetch = FetchResult(url=robots_url, status="failed", error="discovery budget exhausted before robots.txt")
        if discovery_budget.has_capacity():
            discovery_budget.consume()
            robots_fetch = fetch(robots_url, robot_parser=None)
            all_fetches.append(robots_fetch)
            if robots_fetch.status == "fetched" and robots_fetch.html:
                try:
                    rp = urllib.robotparser.RobotFileParser()
                    rp.set_url(robots_url)
                    rp.parse(robots_fetch.html.splitlines())
                    robot_parser = rp
                except Exception:
                    log.exception(f"[scan.discovery] failed to parse robots.txt for {base_url}")

        declared_sitemaps = []
        if robot_parser is not None:
            try:
                declared_sitemaps = list(robot_parser.site_maps() or [])
            except Exception:
                declared_sitemaps = []
        if not declared_sitemaps:
            declared_sitemaps = [urljoin(base_url, "/sitemap.xml")]

        sitemap_index_entries: list = []
        sampling_log = {"children_probed": [], "child_chosen": None, "candidates_found": 0, "robots_excluded": 0}
        sitemap_urls = _resolve_sitemaps(
            declared_sitemaps, robot_parser, discovery_budget, all_fetches, sitemap_index_entries, sampling_log,
        )

        if homepage_fetch is None:
            if budget.has_capacity():
                budget.consume()
                homepage_fetch = fetch(base_url, robot_parser=robot_parser, check_short_body=True)
            else:
                homepage_fetch = FetchResult(url=base_url, status="failed", error="content budget exhausted before homepage")
        homepage_html = homepage_fetch.html if homepage_fetch and homepage_fetch.status == "fetched" else None

        candidates = [PageCandidate(url=base_url, kind="homepage")]

        product_urls = [u for u in sitemap_urls if _looks_like_product_url(u)]
        discovery_path = "sitemap" if product_urls else "none"

        if not product_urls and homepage_html:
            product_urls = _find_links_matching(homepage_html, base_url, _looks_like_product_url)
            if product_urls:
                discovery_path = "homepage"

        if not product_urls and homepage_html and discovery_budget.has_capacity():
            collection_links = _find_links_matching(homepage_html, base_url, _looks_like_collection_url)
            if collection_links:
                discovery_budget.consume()
                coll_result = fetch(collection_links[0], robot_parser=robot_parser, check_short_body=True)
                all_fetches.append(coll_result)
                if coll_result.status == "fetched" and coll_result.html:
                    product_urls = _find_links_matching(coll_result.html, collection_links[0], _looks_like_product_url)
                    if product_urls:
                        discovery_path = "collection_hop"

        seen_products: set = set()
        deduped_product_urls = []
        for u in product_urls:
            if u in seen_products:
                continue
            seen_products.add(u)
            deduped_product_urls.append(u)

        # S1.c: robots-disallowed candidates are excluded from the
        # sample BEFORE MAX_PRODUCT_PAGES is taken — not fetched-and-
        # discarded one at a time, which would waste the tiny sample on
        # URLs disallowed to our reader when other candidates exist.
        # Counted honestly (never silently dropped) for Agent Access
        # evidence — disallowed-by-robots is its own finding, never
        # "rate-limited" (that's a fetch-time signal, this is a crawl-
        # policy one).
        if robot_parser is not None and deduped_product_urls:
            allowed_product_urls = [u for u in deduped_product_urls if robot_parser.can_fetch(USER_AGENT, u)]
            sampling_log["robots_excluded"] = len(deduped_product_urls) - len(allowed_product_urls)
            deduped_product_urls = allowed_product_urls

        for u in deduped_product_urls[:MAX_PRODUCT_PAGES]:
            candidates.append(PageCandidate(url=u, kind="product"))

        if homepage_html:
            loyalty_links = _find_links_by_keyword(homepage_html, base_url, LOYALTY_LINK_KEYWORDS)
            if loyalty_links:
                candidates.append(PageCandidate(url=loyalty_links[0], kind="loyalty"))

            shipping_links = _find_links_by_keyword(homepage_html, base_url, SHIPPING_LINK_KEYWORDS)
            if shipping_links:
                candidates.append(PageCandidate(url=shipping_links[0], kind="shipping_returns"))

        # Not appended to all_fetches (unlike robots/sitemap/collection-hop):
        # these become PageCandidates below and are reused (not re-fetched)
        # by engine.py's _gather_pages, which is where they surface in
        # pages_fetched — appending here too would double-list them.
        llms_txt_fetch = None
        mcp_well_known_fetch = None
        if discovery_budget.has_capacity():
            discovery_budget.consume()
            llms_txt_fetch = fetch(urljoin(base_url, LLMS_TXT_PATH), robot_parser=robot_parser)
        if discovery_budget.has_capacity():
            discovery_budget.consume()
            mcp_well_known_fetch = fetch(urljoin(base_url, MCP_WELL_KNOWN_PATH), robot_parser=robot_parser)

        candidates.append(PageCandidate(url=urljoin(base_url, LLMS_TXT_PATH), kind="llms_txt"))
        candidates.append(PageCandidate(url=urljoin(base_url, MCP_WELL_KNOWN_PATH), kind="mcp_well_known"))

        return DiscoveryResult(
            robots_fetch=robots_fetch,
            robot_parser=robot_parser,
            sitemap_urls=sitemap_urls,
            candidates=candidates,
            homepage_fetch=homepage_fetch,
            llms_txt_fetch=llms_txt_fetch,
            mcp_well_known_fetch=mcp_well_known_fetch,
            products_found=len(deduped_product_urls),
            discovery_path=discovery_path,
            all_fetches=all_fetches,
            sitemap_index_entries=sitemap_index_entries,
            sitemap_sampling=sampling_log,
        )
    except Exception:
        log.exception(f"[scan.discovery] discovery failed for {base_url}")
        return DiscoveryResult(
            robots_fetch=FetchResult(url=urljoin(base_url, "/robots.txt"), status="failed", error="discovery error"),
            robot_parser=None,
            sitemap_urls=[],
            candidates=[PageCandidate(url=base_url, kind="homepage")],
            homepage_fetch=None,
            all_fetches=all_fetches,
        )
