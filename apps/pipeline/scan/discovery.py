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

Rescue session: when sitemap/homepage/collection_hop ALL find nothing
(the "no_product_pages_found" starved-run shape — usually a catalog
that renders client-side, so the raw HTML this reader parses never
contains a single product link), two more tiers run in order before
the run gives up. Part 2, _probe_platform_endpoints: deterministic,
no LLM — cheap platform fingerprinting on the already-fetched homepage
HTML, then a couple of well-known catalog JSON/sitemap endpoints
(Shopify's /products.json shape today; "don't build a taxonomy of
bespoke APIs" per the session's own instructions). Part 3,
_probe_llm_discovery: last resort only, gated by LLM_DISCOVERY_
FALLBACK — asks the model for candidate product URLs, then verifies
every one ourselves (host match, robots, our own fetch, product-page
shape) before it counts for anything; the model supplies a pointer,
never a scored fact. Both tiers set discovery_path accordingly
("platform_endpoint" | "llm_assisted") and extend sitemap_sampling
with their own trace, same "recorded regardless of outcome"
discipline as the sitemap sampler above. discovery_coverage_note()
is the one place the "how we found your product pages" report copy
is written for these non-sitemap paths — offer_feed.py and scorer.py
both read it rather than composing their own.

Fetcher hardening: discover_pages short-circuits before it starts when
robots.txt AND the store root both refused us (403/429). On 5 of the 13
blocked runs in the export, every follow-up probe returned the same 403
with the same body — nothing was learned, and the budget and the
politeness were both spent for it. BOTH signals are required: robots 200
with a refused homepage is a shape where llms.txt and the MCP manifest
are still served and still worth reading. See hard_refused, and
sitemap_sampling["short_circuit"] for the record it leaves.
"""
import gzip
import json
import logging
import os
import re
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from .fetcher import ROBOTS_USER_AGENT, FetchBudget, FetchResult, fetch
from .structured_data import extract as extract_structured_data

log = logging.getLogger(__name__)

# Single-sourced (grep-tested): the one place product-shaped URLs are
# defined — scorer.py and anywhere else that needs this imports it from
# here rather than keeping a second, driftable copy.
#
# Rescue-session widening (Part 1): real retailers use a lot more
# shapes than the original four. -p<digits>/-p<digits> is the trailing
# numeric-SKU suffix a lot of big-box retailers use (e.g.
# /some-product-name-p12345 or /p/some-product-name/p12345), anchored
# to the END of the path so it never fires on an unrelated path that
# merely contains a "p" followed by digits somewhere in the middle.
PRODUCT_URL_PATTERNS = (
    re.compile(r"/products?/"),
    re.compile(r"/p/"),
    re.compile(r"/dp/"),
    re.compile(r"/item/"),
    re.compile(r"/shop/"),
    re.compile(r"/pd/"),
    re.compile(r"/prod/"),
    re.compile(r"/sku/"),
    re.compile(r"/buy/"),
    re.compile(r"/detail/"),
    re.compile(r"-p\d+(?:\.html?)?/?$"),
    re.compile(r"/p\d+(?:\.html?)?/?$"),
    # Nike discovery fix: /t/<slug> (Nike's own PDP shape) is a stopgap,
    # not the real fix — the real fix is the content-based sitemap-child
    # sampling below (_sample_child_for_product_content), which confirms
    # a product page by its own markup rather than needing a dedicated
    # regex for every retailer's URL convention. This pattern just lets
    # Nike's URLs also short-circuit straight to a pattern match when one
    # already exists, same as any other known shape.
    re.compile(r"/t/"),
)
# /shop/ is deliberately in BOTH pattern sets — real stores use it for
# either a catalog root or a single PDP depending on the retailer. See
# _looks_like_product_url: a collection match always wins over a
# product match on overlap (the more conservative reading — sampling a
# category page as a "product" is worse than missing a real PDP that
# happens to share this one ambiguous segment).
COLLECTION_URL_PATTERNS = (
    re.compile(r"/collections?/"),
    re.compile(r"/c/"),
    re.compile(r"/category/"),
    re.compile(r"/shop/"),
    re.compile(r"/browse/"),
    re.compile(r"/departments?/"),
    re.compile(r"/catalog/"),
)
LOYALTY_LINK_KEYWORDS = (
    "reward", "loyalty", "member", "perk", "insider", "circle", "plus",
)
SHIPPING_LINK_KEYWORDS = (
    "shipping", "returns", "return policy", "delivery",
)

# Part 4 (rescue session): the ONE place the "how we found your product
# pages" clause is written for every non-sitemap discovery_path —
# offer_feed.py's OfferFeed eligibility column and scorer.py's Agent
# Access evidence line both read discovery_coverage_note() instead of
# composing their own copy, same single-sourcing discipline as
# PRODUCT_URL_PATTERNS above. "sitemap" and "none" are deliberately
# absent — sitemap is the unremarkable default (nothing to say) and
# "none" is the no_product_pages_found path, whose banner wording lives
# entirely in the frontend (untouched by this session).
DISCOVERY_PATH_COVERAGE_NOTE = {
    "homepage": "found via your site's links, not your sitemap",
    "collection_hop": "found via your site's category pages, not your sitemap",
    "platform_endpoint": "found via your store platform's catalog endpoint",
    "llm_assisted": "found via AI-assisted discovery, not your sitemap",
    # Nike discovery fix: a sitemap child whose declared URLs matched no
    # known pattern at all, confirmed instead by sampling and reading a
    # few of its own pages (_sample_child_for_product_content) — still
    # your sitemap, just not a URL shape this reader already recognized.
    "sitemap_sampled": "found by reading a sample of your sitemap's own pages, not by URL pattern",
}


def discovery_coverage_note(discovery_path: Optional[str]) -> Optional[str]:
    return DISCOVERY_PATH_COVERAGE_NOTE.get(discovery_path)

MAX_PRODUCT_PAGES = 2
LLMS_TXT_PATH = "/llms.txt"
MCP_WELL_KNOWN_PATH = "/.well-known/mcp.json"
# Nike discovery fix: raised from 6 (6 + RESCUE_FETCH_RESERVE below) —
# sitemap traversal keeps its old 6-fetch ceiling (see
# _SITEMAP_SUB_BUDGET), and the 3 extra fetches are permanently
# ring-fenced for collection_hop/platform_endpoint/llm_assisted so a
# sitemap walk that legitimately needs its whole old budget (a large
# <sitemapindex>, several locale children) can never again starve every
# rescue tier the way the Nike run did — robots.txt + 3 top-level
# sitemaps + 2 children left nothing for the tiers built to rescue
# exactly that shape.
DISCOVERY_FETCH_BUDGET = 9
# Nike discovery fix: fetches sitemap traversal (_resolve_sitemaps,
# _select_best_sitemap_child, and this stage's own content-sampling
# fallback) can never dip into, no matter how many candidates it still
# has left to probe — collection_hop/platform_endpoint/llm_assisted
# draw from this reserve instead by checking discovery_budget.
# has_capacity() directly (the full DISCOVERY_FETCH_BUDGET), never the
# reduced sitemap-only ceiling. See _sitemap_budget_has_capacity.
RESCUE_FETCH_RESERVE = 3
# S1.a: bounds both how many TOP-LEVEL declared sitemaps are followed
# and how many children of one <sitemapindex> are actually probed —
# same constant, same reasoning (a large or malicious sitemap tree can
# never consume more than this many fetches trying to find products).
SITEMAP_CHILD_PROBE_LIMIT = 6
GZIP_MAGIC = b"\x1f\x8b"
# Nike discovery fix (requirement 3): up to this many of a zero-
# pattern-density sitemap child's own URLs are fetched and read for
# real product markup before giving up on that child — see
# _sample_child_for_product_content.
CONTENT_SAMPLE_LIMIT = 2
DEFAULT_SITE_LOCALE = "en-us"


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
    # sitemap | sitemap_sampled | homepage | collection_hop | platform_endpoint | llm_assisted | none
    discovery_path: str = "none"
    all_fetches: list = field(default_factory=list)        # every FetchResult discovery performed (F3 observability)
    sitemap_index_entries: list = field(default_factory=list)  # every child-sitemap URL seen (site_typing T1)
    # Rescue session (Part 3): product-page URLs the LLM-assisted tier
    # already fetched-and-verified during discovery itself (charged to
    # discovery_budget, not the content budget) — keyed by URL so
    # engine.py's _gather_pages can REUSE that FetchResult instead of
    # fetching the same URL a second time against the content budget,
    # same reuse idea as homepage_fetch/llms_txt_fetch/mcp_well_known_fetch.
    reused_product_fetches: dict = field(default_factory=dict)
    # Sitemap-sampler stage (hotfix 5, S1.d): the sampling decision,
    # recorded regardless of outcome — children_probed is one entry per
    # child actually fetched (url, is_index, url_count, product_count,
    # or a "skipped" reason for gzip/parse/fetch failures);
    # child_chosen/candidates_found describe the winning child (None/0
    # if nothing usable was found); robots_excluded is how many
    # candidate product URLs were dropped because robots.txt disallows
    # them for our reader, BEFORE the MAX_PRODUCT_PAGES sample is taken.
    #
    # Rescue session (Part 4a): extended with the rest of the discovery
    # ladder's trace — tiers_attempted is one entry per tier actually
    # tried (name + how many candidates it produced), platform_detected/
    # platform_endpoints_probed cover the Part 2 platform-endpoint tier,
    # and llm_discovery covers the Part 3 LLM-assisted tier (counts
    # only — the raw model response text is never recorded here).
    # Fetcher hardening: short_circuit is None on every ordinary run, and
    # the record of why discovery stopped before it started on a run
    # where robots.txt AND the store root both refused us (see
    # discover_pages' hard_refused). Always present, so a reader never
    # has to tell "not short-circuited" apart from "written before this
    # key existed."
    #
    # Nike discovery fix: declared_order is robots.txt's declared
    # sitemaps AFTER product-hint reordering (the order actually walked,
    # not robots.txt's own declared order — see _reorder_declared_
    # sitemaps); locale_preferred is the site locale discovery resolved
    # before picking which <sitemapindex> children to probe first (see
    # _derive_site_locale); content_sampled is None unless a child won
    # by content-sampling rather than URL-pattern density (see
    # _sample_child_for_product_content) — {"child_url", "confirmed_
    # product_urls"} when it did. Every one of these is recorded
    # regardless of outcome, same "debuggability was the point"
    # discipline as the rest of this dict.
    sitemap_sampling: dict = field(default_factory=lambda: {
        "children_probed": [], "child_chosen": None, "candidates_found": 0, "robots_excluded": 0,
        "tiers_attempted": [], "platform_detected": None, "platform_endpoints_probed": [],
        "platform_endpoint_used": None, "llm_discovery": None, "short_circuit": None,
        "declared_order": [], "locale_preferred": None, "content_sampled": None,
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


# Nike discovery fix (requirement 1): filename hints that a declared
# sitemap or sitemapindex child is likely to be the real PDP catalog —
# shared by _reorder_declared_sitemaps (top-level declared order) and
# _sitemap_priority (child tiebreak) so the two never drift apart.
# ORDER ONLY, in both places — see each function's own docstring for
# why filename is never trusted as the selector by itself.
_PRODUCT_FILENAME_HINTS = ("pdp", "product", "products", "catalog", "item")

# Nike discovery fix (requirement 3): filenames that are recognizably
# NOT a product catalog — content-sampling skips these unless nothing
# else was probed, so a starved run doesn't burn its sample budget
# reading a help center or blog before trying anything else.
_NON_CATALOG_FILENAME_HINTS = ("help", "article", "blog", "locator", "store", "landingpage", "gridwall")


def _matches_filename_hint(path: str, hints) -> bool:
    """A hint match bounded on both sides by a non-letter/digit (or the
    string's own start/end) — a bare substring test would false-match
    "item" against every single sitemap URL, since "sitemap" itself
    contains "item" (s-ITEM-ap). Case-insensitive; `path` is expected
    already-lowercased by the caller."""
    for h in hints:
        if re.search(rf"(?<![a-z0-9]){re.escape(h)}(?![a-z0-9])", path):
            return True
    return False

# Nike discovery fix (requirement 1): a language-region locale token
# embedded in a sitemap filename or path segment — "-en-us", "-de-at",
# "/en_us/" — matched case-insensitively. The LAST match in the path
# wins (a locale segment is conventionally the trailing one, e.g.
# "sitemap-v2-landingpage-de-at.xml"), never a bare two-letter language
# code alone (too likely to false-match an unrelated word).
_LOCALE_TOKEN_RE = re.compile(r"(?:^|[/_-])([a-z]{2})[-_]([a-z]{2})(?=[/_.-]|$)", re.IGNORECASE)
_HTML_LANG_RE = re.compile(r'<html[^>]+lang=["\']([a-zA-Z]{2})(?:[-_]([a-zA-Z]{2}))?', re.IGNORECASE)
# Only the leading slice of a homepage document is ever scanned for
# <html lang> — it's always in the opening tag, and a multi-hundred-KB
# document has no business being regex-scanned in full for one attribute.
_LOCALE_SCAN_CHARS = 4000


def _sitemap_locale_hint(url: str) -> Optional[str]:
    """The locale token embedded in a sitemap child's own filename/path
    (e.g. '-en-us' or '/en_us/'), lowercased and hyphenated ('en-us'),
    or None when the filename carries no locale segment at all. Order-
    only, exactly like every other filename hint in this module — never
    a selector on its own."""
    path = urlparse(url).path.lower()
    match = None
    for m in _LOCALE_TOKEN_RE.finditer(path):
        match = m  # last match wins — the trailing segment is the locale
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}"


def _derive_site_locale(base_url: str, homepage_html: Optional[str]) -> str:
    """Nike discovery fix (requirement 1): the site's own locale,
    preferred when ordering which <sitemapindex> children to probe
    first — from the canonical origin's own URL (a locale segment in
    its path, when the final redirect landed on one), else the
    homepage's <html lang> attribute, else DEFAULT_SITE_LOCALE. Never
    raises; any parse failure just falls through to the default."""
    try:
        url_hint = _sitemap_locale_hint(urlparse(base_url).path)
        if url_hint:
            return url_hint
    except Exception:
        pass
    if homepage_html:
        try:
            m = _HTML_LANG_RE.search(homepage_html[:_LOCALE_SCAN_CHARS])
            if m:
                lang = m.group(1).lower()
                region = (m.group(2) or lang).lower()
                return f"{lang}-{region}"
        except Exception:
            pass
    return DEFAULT_SITE_LOCALE


def _reorder_declared_sitemaps(urls: list) -> list:
    """Nike discovery fix (requirement 1): robots.txt's declared
    sitemaps, walked product-hint-first — a stable sort, so two
    sitemaps with the same hint status keep robots.txt's own declared
    order. ORDER ONLY: a decoy whose filename merely contains a hint
    (the hotfix-5 incident this whole module already guards against
    one layer down, in _select_best_sitemap_child) is still probed and
    still loses on content density once fetched — it's just probed
    sooner, so a genuine PDP index declared later than several
    unrelated indexes (Nike's shape: sitemap-v2-pdp-index.xml is third
    of seven) doesn't lose its share of the budget to them first."""
    return sorted(
        urls,
        key=lambda u: 0 if _matches_filename_hint(urlparse(u).path.lower(), _PRODUCT_FILENAME_HINTS) else 1,
    )


def _reorder_children_by_locale(child_urls: list, preferred_locale: Optional[str]) -> list:
    """Nike discovery fix (requirement 1): when a <sitemapindex>'s
    children carry locale segments (Nike's 64 sitemap-v2-landingpage-
    <locale>.xml children), probe the ones matching the resolved site
    locale first. A stable sort: children with NO locale segment keep
    their original position (neither promoted nor demoted), and a
    locale MISMATCH is pushed later, never dropped — every child is
    still eligible to be probed if budget allows."""
    if not preferred_locale:
        return list(child_urls)

    def _rank(url: str) -> int:
        hint = _sitemap_locale_hint(url)
        if hint is None:
            return 1
        return 0 if hint == preferred_locale else 2

    return sorted(child_urls, key=_rank)


def _looks_non_catalog_filename(url: str) -> bool:
    name = urlparse(url).path.lower()
    return _matches_filename_hint(name, _NON_CATALOG_FILENAME_HINTS)


def _sitemap_priority(url: str) -> int:
    """Tiebreaker ONLY (S1.a) — never the selector. Used to break a tie
    between two children with equal product-URL density. Nike discovery
    fix: hint list widened to match _PRODUCT_FILENAME_HINTS (was just
    "product")."""
    lu = urlparse(url).path.lower()
    if _matches_filename_hint(lu, _PRODUCT_FILENAME_HINTS):
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


def _sitemap_budget_has_capacity(discovery_budget: FetchBudget) -> bool:
    """Nike discovery fix (requirement 2): sitemap traversal's own share
    of discovery_budget — RESCUE_FETCH_RESERVE fetches are permanently
    off-limits to it, so a large or deeply-indexed sitemap tree (Nike:
    seven declared sitemaps, one a 64-child locale index) can never again
    consume the ENTIRE discovery budget and leave collection_hop/
    platform_endpoint/llm_assisted with nothing to work with. Those three
    tiers call discovery_budget.has_capacity() directly instead — they're
    exactly what the reserve exists for."""
    return discovery_budget.used < max(0, discovery_budget.max_fetches - RESCUE_FETCH_RESERVE)


def _fetch_and_parse_sitemap(url: str, robot_parser, discovery_budget: FetchBudget, all_fetches: list, sampling_log: dict):
    """Fetches and parses one sitemap URL (gzip-aware). Never raises.
    Returns (is_index, urls) on success, else None — every outcome
    (including budget exhaustion, fetch failure, and any parse/gzip
    failure) is recorded in sampling_log["children_probed"] with a
    reason, never silently dropped (S1.d)."""
    if not discovery_budget.has_capacity():
        sampling_log["children_probed"].append({"url": url, "skipped": "discovery budget exhausted"})
        return None
    if not _sitemap_budget_has_capacity(discovery_budget):
        sampling_log["children_probed"].append({"url": url, "skipped": "reserved for rescue tiers"})
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


def _sample_child_for_product_content(
    urls: list, robot_parser, discovery_budget: FetchBudget, all_fetches: list,
) -> tuple:
    """
    Nike discovery fix (requirement 3): the real fix behind the /t/
    pattern stopgap above — when a probed child's own declared URLs
    matched no known PRODUCT_URL_PATTERNS shape at all (a URL
    convention this reader has never seen before, not necessarily
    "not a catalog"), fetch up to CONTENT_SAMPLE_LIMIT of its own URLs
    and check each one's actual markup with the same content-level
    verification the LLM-assisted tier already uses to confirm a
    model's guess (_looks_like_product_page) — reused here, not
    redefined, so "is this a product page" has exactly one definition
    in this module.

    Draws from the same reserved sitemap sub-budget as the rest of
    sitemap traversal (_sitemap_budget_has_capacity) — this is still
    sitemap-child verification, not a rescue tier of its own. Never
    raises: any one URL's fetch/extract failure just isn't confirmed,
    never aborts the rest of the sample.

    Returns (confirmed_urls, reused_fetches) — reused_fetches is
    {url: FetchResult} for every confirmed URL so the caller can reuse
    that fetch (charged here, to discovery_budget) instead of fetching
    it again against the content budget, same reuse idea as the
    LLM-assisted tier's own reused_product_fetches.
    """
    confirmed: list = []
    reused: dict = {}
    for candidate_url in urls[:CONTENT_SAMPLE_LIMIT]:
        if robot_parser is not None and not robot_parser.can_fetch(USER_AGENT, candidate_url):
            continue
        if not discovery_budget.has_capacity() or not _sitemap_budget_has_capacity(discovery_budget):
            break
        discovery_budget.consume()
        try:
            result = fetch(candidate_url, robot_parser=robot_parser)
        except Exception:
            log.exception(f"[scan.discovery] unexpected error content-sampling {candidate_url}")
            continue
        all_fetches.append(result)
        if result.status != "fetched" or not result.html:
            continue
        extracted = extract_structured_data(result.html)
        if _looks_like_product_page(extracted):
            confirmed.append(candidate_url)
            reused[candidate_url] = result
    return confirmed, reused


def _select_best_sitemap_child(
    child_urls: list, robot_parser, discovery_budget: FetchBudget, all_fetches: list, sampling_log: dict,
    sample_reused_fetches: dict, preferred_locale: Optional[str] = None,
) -> list:
    """
    S1.a: probes up to SITEMAP_CHILD_PROBE_LIMIT children and selects
    the one with the highest URL-pattern product density. Nike
    discovery fix (requirement 1): children are probed in LOCALE-
    preferred order, not raw declaration order, when they carry locale
    segments (see _reorder_children_by_locale) — filename/locale never
    decide WHICH child wins, only the order they're tried in and, for
    _sitemap_priority, a tiebreak among equally-dense results.

    Nike discovery fix (requirement 3): when every probed child parses
    but NONE show any URL-pattern density at all (S2's starved shape —
    a URL convention this reader doesn't recognize, not necessarily an
    empty catalog), falls back to content-sampling eligible children
    (see _sample_child_for_product_content) before giving up. Returns
    that child's page URLs, or [] if nothing usable was found among the
    probed children by either method.
    """
    ordered = _reorder_children_by_locale(child_urls, preferred_locale)
    candidates = []  # (density, product_count, url, urls)
    probed = 0
    for child_url in ordered:
        if probed >= SITEMAP_CHILD_PROBE_LIMIT or not discovery_budget.has_capacity() or not _sitemap_budget_has_capacity(discovery_budget):
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

    if any(c[1] > 0 for c in candidates):
        candidates.sort(key=lambda c: (-c[0], _sitemap_priority(c[2])))
        best_density, best_product_count, best_url, best_urls = candidates[0]
        sampling_log["child_chosen"] = best_url
        sampling_log["candidates_found"] = best_product_count
        return best_urls

    # Requirement 3: zero pattern density on every probed child — try
    # content-sampling before giving up. Catalog-shaped filenames first
    # (skip the obvious non-catalog ones), but fall back to sampling
    # whatever was probed if nothing else is available, in probe order.
    catalog_like = [c for c in candidates if not _looks_non_catalog_filename(c[2])]
    for _density, _product_count, child_url, urls in (catalog_like or candidates):
        if not discovery_budget.has_capacity() or not _sitemap_budget_has_capacity(discovery_budget):
            break
        confirmed, reused = _sample_child_for_product_content(urls, robot_parser, discovery_budget, all_fetches)
        if confirmed:
            sampling_log["child_chosen"] = child_url
            sampling_log["candidates_found"] = len(confirmed)
            sampling_log["content_sampled"] = {"child_url": child_url, "confirmed_product_urls": list(confirmed)}
            sample_reused_fetches.update(reused)
            return list(confirmed)

    return []


def _resolve_sitemaps(
    initial_urls: list, robot_parser, discovery_budget: FetchBudget,
    all_fetches: list, index_entries: list, sampling_log: dict,
    sample_reused_fetches: dict, preferred_locale: Optional[str] = None,
) -> list:
    """
    Sitemap-sampler rewrite (hotfix 5, S1.a): fetches each declared
    (top-level) sitemap, bounded by SITEMAP_CHILD_PROBE_LIMIT and
    discovery_budget's reserved sitemap share (_sitemap_budget_has_
    capacity). A FLAT sitemap's URLs are used directly (unchanged fast
    path for a simple, unindexed store). A <sitemapindex>'s children are
    NEVER trusted by filename — see _select_best_sitemap_child. Never
    raises. Returns the flat list of real PAGE URLs sampled — child-
    sitemap URLs themselves are never returned here, but every one
    declared by an index (probed or not) is still appended to
    index_entries for site_typing.py's T1 signal check — a Shopify
    sitemapindex naming "sitemap_products_1.xml" is itself commerce
    evidence, even if that exact child was never the one actually
    chosen.
    """
    page_urls: list = []
    queue = list(initial_urls)
    seen: set = set()
    followed = 0

    while queue and followed < SITEMAP_CHILD_PROBE_LIMIT and discovery_budget.has_capacity() and _sitemap_budget_has_capacity(discovery_budget):
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
        page_urls.extend(_select_best_sitemap_child(
            urls, robot_parser, discovery_budget, all_fetches, sampling_log,
            sample_reused_fetches, preferred_locale=preferred_locale,
        ))

    return page_urls


def _looks_like_collection_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(p.search(path) for p in COLLECTION_URL_PATTERNS)


def _looks_like_product_url(url: str) -> bool:
    """Part 1: a collection match always wins over a product match on
    overlap (e.g. /shop/) — the conservative reading. Checked first,
    not as a filter afterward, so it's the one place this rule lives."""
    path = urlparse(url).path.lower()
    if any(p.search(path) for p in COLLECTION_URL_PATTERNS):
        return False
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


# ─── Part 2: deterministic platform-endpoint probes ─────────────────────
#
# Tried before any LLM call, only once the sitemap/homepage/collection-
# hop tiers all came up empty. 2b: cheap fingerprinting first so this
# never blindly probes an endpoint set the detected platform can't
# have — only "shopify" (or no fingerprint at all — the two Shopify
# JSON paths are cheap and by far the most common shape even when
# undetected) gets real endpoint probes. Detecting a non-Shopify
# platform (bigcommerce/magento/woocommerce/nextjs) is still recorded
# on sampling_log for the trace (Part 4a) even though — per the "don't
# build a taxonomy of bespoke APIs" instruction — no endpoint is tried
# for it here.
PLATFORM_SHOPIFY = "shopify"
_PLATFORM_FINGERPRINT_MARKERS = (
    (PLATFORM_SHOPIFY, ("cdn.shopify.com", "shopify.theme")),
    ("bigcommerce", ("bigcommerce",)),
    ("magento", ("magento",)),
    ("woocommerce", ("wp-content/plugins/woocommerce",)),
    # Next.js is not a commerce platform, but it's the classic shape
    # behind a starved run (client-rendered catalog — the raw HTML this
    # reader parses never contains a single product link) — worth
    # naming in the trace even though it selects no endpoint of its own.
    ("nextjs", ("/_next/",)),
)

# 2a: three probes, hard-stopping at the first that yields candidates.
# name is recorded on sampling_log, never re-derived from the URL.
PLATFORM_ENDPOINT_PROBES = (
    ("/products.json?limit=24", "shopify_products_json"),
    ("/collections/all/products.json?limit=24", "shopify_collections_all_json"),
    ("/sitemap_products_1.xml", "shopify_sitemap_products"),
)


def _detect_platform(homepage_html: Optional[str]) -> Optional[str]:
    if not homepage_html:
        return None
    lowered = homepage_html.lower()
    for platform, markers in _PLATFORM_FINGERPRINT_MARKERS:
        if any(m in lowered for m in markers):
            return platform
    return None


def _parse_products_json(json_text: str, base_url: str) -> list:
    """Shopify's /products.json and /collections/all/products.json share
    this exact {"products": [{"handle": ...}, ...]} shape. Never raises
    — malformed JSON or an unexpected shape yields []."""
    try:
        data = json.loads(json_text)
    except Exception:
        return []
    products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(products, list):
        return []
    urls = []
    for p in products:
        if not isinstance(p, dict):
            continue
        handle = p.get("handle")
        if isinstance(handle, str) and handle.strip():
            urls.append(urljoin(base_url, f"/products/{handle.strip()}"))
    return urls


def _parse_platform_endpoint(name: str, endpoint_url: str, base_url: str, result: FetchResult) -> list:
    """Never raises. sitemap_products_1.xml is a real sitemap (gzip-
    aware, same parse as every other sitemap child); both *.json paths
    share _parse_products_json's shape."""
    if name == "shopify_sitemap_products":
        xml_text, skip_reason = _sitemap_xml_text(endpoint_url, result)
        if xml_text is None:
            return []
        _is_index, urls = _parse_sitemap(xml_text)
        return [u for u in urls if _looks_like_product_url(u)]
    return _parse_products_json(result.html or "", base_url)


def _probe_platform_endpoints(
    base_url: str, homepage_html: Optional[str], robot_parser, discovery_budget: FetchBudget,
    all_fetches: list, sampling_log: dict,
) -> tuple:
    """Returns (urls, endpoint_name) — endpoint_name is "none" when
    nothing was probed or nothing yielded candidates. Never raises;
    every outcome (skipped, fetch failure, empty parse) is recorded on
    sampling_log["platform_endpoints_probed"] (Part 4a)."""
    platform = _detect_platform(homepage_html)
    sampling_log["platform_detected"] = platform
    # nextjs is a rendering-layer signal, not a commerce-backend one —
    # a headless-Shopify storefront commonly runs on Next.js, so
    # detecting it doesn't rule out Shopify's JSON endpoints the way a
    # genuinely different backend (bigcommerce/magento/woocommerce)
    # does. Those three DO rule it out — probing Shopify's endpoints
    # against a confirmed-Magento store would just waste a fetch.
    if platform not in (None, PLATFORM_SHOPIFY, "nextjs"):
        return [], "none"

    for path, name in PLATFORM_ENDPOINT_PROBES:
        endpoint_url = urljoin(base_url, path)

        if robot_parser is not None and not robot_parser.can_fetch(ROBOTS_USER_AGENT, endpoint_url):
            sampling_log["platform_endpoints_probed"].append(
                {"endpoint": name, "url": endpoint_url, "skipped": "robots disallowed"}
            )
            continue
        if not discovery_budget.has_capacity():
            sampling_log["platform_endpoints_probed"].append(
                {"endpoint": name, "url": endpoint_url, "skipped": "discovery budget exhausted"}
            )
            continue

        discovery_budget.consume()
        try:
            result = fetch(endpoint_url, robot_parser=robot_parser)
        except Exception:
            log.exception(f"[scan.discovery] unexpected error probing platform endpoint {endpoint_url}")
            sampling_log["platform_endpoints_probed"].append(
                {"endpoint": name, "url": endpoint_url, "skipped": "unexpected fetch error"}
            )
            continue
        all_fetches.append(result)

        if result.status != "fetched" or not result.html:
            sampling_log["platform_endpoints_probed"].append(
                {"endpoint": name, "url": endpoint_url, "outcome": f"fetch failed (status={result.status})"}
            )
            continue

        urls = _parse_platform_endpoint(name, endpoint_url, base_url, result)
        sampling_log["platform_endpoints_probed"].append(
            {"endpoint": name, "url": endpoint_url, "candidates_found": len(urls)}
        )
        if urls:
            return urls, name

    return [], "none"


# ─── Part 3: LLM-assisted discovery (last resort, pointer only) ─────────

LLM_DISCOVERY_FALLBACK_ENV = "LLM_DISCOVERY_FALLBACK"


def _llm_discovery_enabled(api_key: Optional[str]) -> bool:
    """3c: default ON when an OpenAI key is present, OFF otherwise —
    absence of the env var never breaks discovery either way. An
    explicit LLM_DISCOVERY_FALLBACK env value always wins (a kill
    switch, both directions) over the key-presence default."""
    flag = os.environ.get(LLM_DISCOVERY_FALLBACK_ENV)
    if flag is not None:
        return flag.strip().lower() in ("1", "true", "on", "yes")
    return bool(api_key)


def _homepage_reached(homepage_fetch: Optional[FetchResult]) -> bool:
    """3a's "the site is NOT blocked (the run reached the homepage)"
    gate. Deliberately NOT the same thing as homepage_html being
    present: fetcher.py's check_short_body heuristic (F2) marks a real
    200-OK response as status='blocked' whenever the body is under
    MIN_BODY_LENGTH chars — the exact shape of a client-rendered
    (Next.js-style) homepage shell, which is precisely the case this
    tier exists to rescue. What actually means "blocked" for THIS
    gate's purpose is a real HTTP response outside 2xx/3xx (403/429/a
    genuine challenge status), a network failure, or an SSRF/cross-
    domain abort — none of which carry an http_status in the 2xx-3xx
    range at all."""
    if homepage_fetch is None or homepage_fetch.http_status is None:
        return False
    return homepage_fetch.http_status < 400


def _looks_like_product_page(extracted) -> bool:
    """3b's verification check: real Product/ProductGroup structured
    data, or — when a store skips JSON-LD entirely — the same microdata
    + visible-price shape the scorer already treats as product-page
    evidence elsewhere. Never a URL-shape guess; this is content-level,
    exactly what "parses as a product page" means."""
    if extracted is None:
        return False
    if extracted.products:
        return True
    return bool(extracted.has_microdata and extracted.visible_prices)


def _probe_llm_discovery(
    base_url: str, robot_parser, discovery_budget: FetchBudget, all_fetches: list, api_key: Optional[str],
) -> tuple:
    """
    3a/3b: asks the model for candidate product URLs, then
    independently verifies every one before trusting it — host must
    equal the canonical origin's host (no subdomain drift, no
    marketplaces), robots must allow it, and OUR OWN fetch must parse
    as a product page. At most MAX_PRODUCT_PAGES survive. Never raises.

    Returns (verified_urls, reused_fetches, trace) — reused_fetches is
    {url: FetchResult} for every verified URL, so engine.py's
    _gather_pages can reuse the fetch already made here (charged to
    discovery_budget) instead of fetching it again against the content
    budget. trace is the Part 4a sampling record — counts and per-URL
    rejection reasons only, NEVER the raw model response text.
    """
    from generation.discovery_probe import probe_discover_urls

    canonical_host = (urlparse(base_url).hostname or "").lower()
    probe_result = probe_discover_urls(base_url, api_key)
    returned_urls = probe_result.get("urls") or []

    verified: list = []
    reused_fetches: dict = {}
    rejections: list = []

    for candidate_url in returned_urls:
        if len(verified) >= MAX_PRODUCT_PAGES:
            break

        host = (urlparse(candidate_url).hostname or "").lower()
        if not host or host != canonical_host:
            rejections.append({"url": candidate_url, "reason": "off-domain"})
            continue

        if robot_parser is not None and not robot_parser.can_fetch(ROBOTS_USER_AGENT, candidate_url):
            rejections.append({"url": candidate_url, "reason": "robots disallowed"})
            continue

        if not discovery_budget.has_capacity():
            rejections.append({"url": candidate_url, "reason": "discovery budget exhausted"})
            continue

        discovery_budget.consume()
        try:
            result = fetch(candidate_url, robot_parser=robot_parser)
        except Exception:
            log.exception(f"[scan.discovery] unexpected error verifying LLM-discovered URL {candidate_url}")
            rejections.append({"url": candidate_url, "reason": "unexpected fetch error"})
            continue
        all_fetches.append(result)

        if result.status != "fetched" or not result.html:
            rejections.append({"url": candidate_url, "reason": f"fetch failed (status={result.status})"})
            continue

        extracted = extract_structured_data(result.html)
        if not _looks_like_product_page(extracted):
            rejections.append({"url": candidate_url, "reason": "no product markup found"})
            continue

        verified.append(candidate_url)
        reused_fetches[candidate_url] = result

    trace = {"urls_returned": len(returned_urls), "urls_verified": len(verified), "rejections": rejections}
    return verified, reused_fetches, trace


def _build_discovery_result(
    *, robots_fetch, robot_parser, sitemap_urls, candidates, homepage_fetch,
    llms_txt_fetch, mcp_well_known_fetch, products_found, discovery_path,
    all_fetches, sitemap_index_entries, sitemap_sampling, reused_product_fetches,
) -> DiscoveryResult:
    """Every field, named — the one place discover_pages builds its
    result. Both the ordinary return and the hard-refused short-circuit
    go through here precisely so a new DiscoveryResult field can never be
    silently left at its default on one path and set on the other."""
    return DiscoveryResult(
        robots_fetch=robots_fetch,
        robot_parser=robot_parser,
        sitemap_urls=sitemap_urls,
        candidates=candidates,
        homepage_fetch=homepage_fetch,
        llms_txt_fetch=llms_txt_fetch,
        mcp_well_known_fetch=mcp_well_known_fetch,
        products_found=products_found,
        discovery_path=discovery_path,
        all_fetches=all_fetches,
        sitemap_index_entries=sitemap_index_entries,
        sitemap_sampling=sitemap_sampling,
        reused_product_fetches=reused_product_fetches,
    )


def discover_pages(
    base_url: str,
    budget: FetchBudget,
    *,
    homepage_fetch: Optional[FetchResult] = None,
    api_key: Optional[str] = None,
) -> DiscoveryResult:
    """
    Never raises — every internal step degrades to an empty/partial
    result rather than propagating. base_url must already be the
    resolved canonical origin (see resolve_canonical_origin) — every
    relative URL built here uses this one origin (H2).

    api_key (Part 3, rescue session): optional — used ONLY to gate and
    run the last-resort LLM-assisted discovery tier (_probe_llm_discovery)
    when every deterministic tier finds nothing. None (the default)
    simply means that tier never fires — every other discovery path is
    completely unaffected.

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

        sitemap_index_entries: list = []
        sampling_log = {
            "children_probed": [], "child_chosen": None, "candidates_found": 0, "robots_excluded": 0,
            "tiers_attempted": [], "platform_detected": None, "platform_endpoints_probed": [],
            "platform_endpoint_used": None, "llm_discovery": None, "short_circuit": None,
            "declared_order": [], "locale_preferred": None, "content_sampled": None,
        }

        # Fetcher hardening: when robots.txt AND the store root both
        # refuse us, stop here and issue no further requests. On 5 of the
        # 13 blocked runs in the export, every one of the 6-7 follow-up
        # probes (sitemap.xml, sitemap_products_1.xml, products.json
        # twice, llms.txt, .well-known/mcp.json) came back 403 with the
        # same body as robots.txt did. Nothing was learned from any of
        # them, and a reader that keeps knocking after being told no
        # twice is the kind of reader these systems are built to refuse.
        #
        # BOTH signals are required, deliberately. robots 200 + homepage
        # 403 is the Warby Parker shape from the export — robots.txt,
        # llms.txt and the MCP manifest were all served while HTML was
        # refused, and those probes are exactly the ones worth keeping.
        # robots 403 + homepage 200 is not a wall either. And a caller
        # using discover_pages standalone passes no homepage_fetch at
        # all, which is one signal, not two, so it never short-circuits.
        hard_refused = (
            robots_fetch.http_status in (403, 429)
            and homepage_fetch is not None
            and homepage_fetch.status != "fetched"
            and homepage_fetch.http_status in (403, 429)
        )
        if hard_refused:
            sampling_log["short_circuit"] = {
                "reason": "robots_and_homepage_refused",
                "robots_http_status": robots_fetch.http_status,
                "homepage_http_status": homepage_fetch.http_status,
                "skipped": [
                    "sitemap", "platform_endpoint", "llm_assisted",
                    "llms_txt", "mcp_well_known", "product_pages",
                ],
            }
            sampling_log["tiers_attempted"].append({"tier": "short_circuit", "candidates_found": 0})
            log.info(
                f"[scan.discovery] short-circuiting discovery for "
                f"{urlparse(base_url).hostname}: robots.txt returned "
                f"{robots_fetch.http_status} and the store root returned "
                f"{homepage_fetch.http_status} — issuing no further requests"
            )
            return _build_discovery_result(
                robots_fetch=robots_fetch,
                robot_parser=robot_parser,
                sitemap_urls=[],
                candidates=[PageCandidate(url=base_url, kind="homepage")],
                homepage_fetch=homepage_fetch,
                llms_txt_fetch=None,
                mcp_well_known_fetch=None,
                products_found=0,
                discovery_path="none",
                all_fetches=[robots_fetch],
                sitemap_index_entries=[],
                sitemap_sampling=sampling_log,
                reused_product_fetches={},
            )

        declared_sitemaps = []
        if robot_parser is not None:
            try:
                declared_sitemaps = list(robot_parser.site_maps() or [])
            except Exception:
                declared_sitemaps = []
        if not declared_sitemaps:
            declared_sitemaps = [urljoin(base_url, "/sitemap.xml")]

        # Nike discovery fix (requirement 1): product-hint-first order,
        # not robots.txt's own declared order — recorded either way so
        # the decision is debuggable (S1.d's discipline). Locale is
        # resolved from whatever homepage_fetch the caller already gave
        # us (engine.py always does, by the time discover_pages runs) —
        # a standalone caller with none yet just falls back to the
        # URL-derived/default locale, since the homepage fetch below
        # hasn't happened yet at this point in the function.
        declared_sitemaps = _reorder_declared_sitemaps(declared_sitemaps)
        sampling_log["declared_order"] = list(declared_sitemaps)
        preferred_locale = _derive_site_locale(
            base_url, homepage_fetch.html if homepage_fetch and homepage_fetch.status == "fetched" else None,
        )
        sampling_log["locale_preferred"] = preferred_locale

        content_sample_reused: dict = {}
        sitemap_urls = _resolve_sitemaps(
            declared_sitemaps, robot_parser, discovery_budget, all_fetches, sitemap_index_entries, sampling_log,
            content_sample_reused, preferred_locale=preferred_locale,
        )

        if homepage_fetch is None:
            if budget.has_capacity():
                budget.consume()
                homepage_fetch = fetch(base_url, robot_parser=robot_parser, check_short_body=True)
            else:
                homepage_fetch = FetchResult(url=base_url, status="failed", error="content budget exhausted before homepage")
        homepage_html = homepage_fetch.html if homepage_fetch and homepage_fetch.status == "fetched" else None

        candidates = [PageCandidate(url=base_url, kind="homepage")]
        reused_product_fetches: dict = {}

        content_sampled = sampling_log.get("content_sampled")
        if content_sampled:
            # Requirement 3: these URLs were independently confirmed by
            # their own markup (_sample_child_for_product_content), not
            # by URL shape — re-applying the pattern filter here would
            # defeat the entire point (they matched no pattern, that's
            # why sampling ran at all), so they're used exactly as
            # confirmed. Their fetches were already charged to
            # discovery_budget — reused by engine.py's _gather_pages
            # rather than fetched again against the content budget.
            product_urls = list(content_sampled["confirmed_product_urls"])
            discovery_path = "sitemap_sampled"
            reused_product_fetches.update(content_sample_reused)
        else:
            product_urls = [u for u in sitemap_urls if _looks_like_product_url(u)]
            discovery_path = "sitemap" if product_urls else "none"
        sampling_log["tiers_attempted"].append({"tier": "sitemap", "candidates_found": len(product_urls)})

        if not product_urls and homepage_html:
            product_urls = _find_links_matching(homepage_html, base_url, _looks_like_product_url)
            if product_urls:
                discovery_path = "homepage"
            sampling_log["tiers_attempted"].append({"tier": "homepage", "candidates_found": len(product_urls)})

        if not product_urls and homepage_html:
            # Requirement 2: this tier, and the two below, draw from the
            # FULL discovery_budget (not the reduced sitemap-only share)
            # — that's the whole point of RESCUE_FETCH_RESERVE. A skip
            # here is recorded with a reason rather than silently
            # vanishing from tiers_attempted (requirement 2's other half).
            if discovery_budget.has_capacity():
                collection_links = _find_links_matching(homepage_html, base_url, _looks_like_collection_url)
                if collection_links:
                    discovery_budget.consume()
                    coll_result = fetch(collection_links[0], robot_parser=robot_parser, check_short_body=True)
                    all_fetches.append(coll_result)
                    if coll_result.status == "fetched" and coll_result.html:
                        product_urls = _find_links_matching(coll_result.html, collection_links[0], _looks_like_product_url)
                        if product_urls:
                            discovery_path = "collection_hop"
                sampling_log["tiers_attempted"].append({"tier": "collection_hop", "candidates_found": len(product_urls)})
            else:
                sampling_log["tiers_attempted"].append(
                    {"tier": "collection_hop", "candidates_found": 0, "skipped": "discovery budget exhausted"}
                )

        # Part 2 (2a/2b/2c): deterministic platform-endpoint probes —
        # tried before any LLM call, only once the three tiers above
        # came up empty. Cheap platform fingerprinting first (2b) means
        # this never blindly probes an endpoint set the detected
        # platform can't have.
        if not product_urls:
            if discovery_budget.has_capacity():
                platform_urls, endpoint_used = _probe_platform_endpoints(
                    base_url, homepage_html, robot_parser, discovery_budget, all_fetches, sampling_log,
                )
                if platform_urls:
                    product_urls = platform_urls
                    discovery_path = "platform_endpoint"
                    sampling_log["platform_endpoint_used"] = endpoint_used
                sampling_log["tiers_attempted"].append({"tier": "platform_endpoint", "candidates_found": len(platform_urls)})
            else:
                sampling_log["tiers_attempted"].append(
                    {"tier": "platform_endpoint", "candidates_found": 0, "skipped": "discovery budget exhausted"}
                )

        # Part 3 (3a/3b/3c): last-resort LLM-assisted discovery — only
        # when every deterministic tier above found nothing AND the
        # site is not blocked (we actually reached the homepage), and
        # only when the flag/key gate allows it. Every URL the model
        # returns is independently verified (host match, robots, our
        # own fetch, product-page shape) before it counts as anything —
        # see _probe_llm_discovery.
        if not product_urls and _homepage_reached(homepage_fetch) and _llm_discovery_enabled(api_key):
            if discovery_budget.has_capacity():
                llm_urls, llm_fetches, llm_trace = _probe_llm_discovery(
                    base_url, robot_parser, discovery_budget, all_fetches, api_key,
                )
                sampling_log["llm_discovery"] = llm_trace
                sampling_log["tiers_attempted"].append({"tier": "llm_assisted", "candidates_found": len(llm_urls)})
                if llm_urls:
                    product_urls = llm_urls
                    discovery_path = "llm_assisted"
                    reused_product_fetches.update(llm_fetches)
            else:
                sampling_log["tiers_attempted"].append(
                    {"tier": "llm_assisted", "candidates_found": 0, "skipped": "discovery budget exhausted"}
                )

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
            allowed_product_urls = [u for u in deduped_product_urls if robot_parser.can_fetch(ROBOTS_USER_AGENT, u)]
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

        return _build_discovery_result(
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
            reused_product_fetches=reused_product_fetches,
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
