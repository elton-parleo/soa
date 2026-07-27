"""
site_typing.py — Stage 11 (Layer 4) commerce-signal-based site typing.

Pure function: no DB access, no fetches of its own — consumes the
already-fetched pages/discovery data engine.py collected. Replaces
Stage 10 D5's absence-based inference ("no product pages found ->
brand-only") with a decision table requiring POSITIVE evidence, so a
discovery FAILURE (commerce signals present, but PDP sampling still
came up empty — e.g. a Shopify sitemap the crawl couldn't fully
traverse) can never again be reported as a "this isn't a commerce
site" finding.

Decision table (T2):
  commerce signals + product pages sampled       -> commerce_normal
  commerce signals + NO product pages found      -> commerce_discovery_failure
  no commerce signals anywhere                   -> brand_only
"""
import logging
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

SITE_TYPE_COMMERCE = "commerce_normal"
SITE_TYPE_DISCOVERY_FAILURE = "commerce_discovery_failure"
SITE_TYPE_BRAND_ONLY = "brand_only"

DISCOVERY_FAILURE_REASON = "product pages could not be discovered from sitemap or navigation"
BRAND_ONLY_REASON = "no cart, commerce paths, platform markers, or Offer markup found"

CART_CHECKOUT_LINK_KEYWORDS = ("cart", "checkout", "bag", "basket")
COMMERCE_PATH_HINTS = ("/products", "/collections")
PLATFORM_MARKER_HINTS = (
    "cdn.shopify.com", "myshopify.com", "shopify.com/s/files",
    "cdn11.bigcommerce", "bigcommerce.com",
    "woocommerce", "wp-content/plugins/woocommerce",
)
GENERATOR_META_HINTS = ("shopify", "bigcommerce", "woocommerce")


@dataclass
class SiteTypeResult:
    site_type: str
    reason: str
    signals: list = field(default_factory=list)  # evidence strings for the positive basis


def _product_pages(pages):
    return [p for p in pages if p.candidate.kind == "product"]


def _has_cart_checkout_link(homepage_html: str) -> bool:
    """Cart/checkout links or forms in the homepage's nav/footer — a
    same lightweight, deterministic keyword search as the rest of
    discovery.py, never raises."""
    if not homepage_html:
        return False
    try:
        soup = BeautifulSoup(homepage_html, "html.parser")
    except Exception:
        return False

    try:
        for a in soup.find_all("a", href=True):
            text = (a.get_text() or "").strip().lower()
            href = a["href"].lower()
            if any(kw in text or kw in href for kw in CART_CHECKOUT_LINK_KEYWORDS):
                return True
        for form in soup.find_all("form"):
            action = (form.get("action") or "").lower()
            if any(kw in action for kw in CART_CHECKOUT_LINK_KEYWORDS):
                return True
    except Exception:
        log.exception("[scan.site_typing] failed to scan for cart/checkout links")
    return False


def _has_commerce_path_in_robots_or_sitemap(discovery) -> bool:
    robots_html = (discovery.robots_fetch.html or "") if discovery.robots_fetch else ""
    if any(hint in robots_html.lower() for hint in COMMERCE_PATH_HINTS):
        return True

    # Sitemap/child-sitemap entries: a Shopify sitemapindex names its
    # children "sitemap_products_1.xml" — a filename, not a URL path
    # segment — so this checks the bare "product"/"collection" words
    # rather than requiring the leading slash COMMERCE_PATH_HINTS uses
    # for robots.txt rules.
    bare_hints = tuple(hint.lstrip("/") for hint in COMMERCE_PATH_HINTS)
    sitemap_entries = [u.lower() for u in (discovery.sitemap_urls or [])]
    sitemap_entries.extend(u.lower() for u in (discovery.sitemap_index_entries or []))
    return any(hint in u for u in sitemap_entries for hint in bare_hints)


def _has_platform_marker(homepage_html: str) -> bool:
    if not homepage_html:
        return False
    lowered = homepage_html.lower()
    if any(hint in lowered for hint in PLATFORM_MARKER_HINTS):
        return True
    try:
        soup = BeautifulSoup(homepage_html, "html.parser")
        for meta in soup.find_all("meta", attrs={"name": "generator"}):
            content = (meta.get("content") or "").lower()
            if any(hint in content for hint in GENERATOR_META_HINTS):
                return True
    except Exception:
        log.exception("[scan.site_typing] failed to scan for platform generator meta tag")
    return False


def _has_any_offer_markup(pages) -> bool:
    return any(
        prod.offers
        for p in pages if p.extracted
        for prod in p.extracted.products
    )


def classify_site(pages: list, discovery) -> SiteTypeResult:
    """
    Never raises. `pages` is the engine's list[PageScanData]; `discovery`
    is the DiscoveryResult from discover_pages(). Checkable even when PDP
    sampling entirely failed — every signal here comes from robots.txt,
    the sitemap, or the homepage, none of which require a product page
    to have been found.
    """
    try:
        homepage_page = next((p for p in pages if p.candidate.kind == "homepage"), None)
        homepage_html = homepage_page.fetch_result.html if homepage_page and homepage_page.fetch_result else None

        signals = []
        if _has_cart_checkout_link(homepage_html):
            signals.append("cart/checkout link or form found in homepage nav/footer")
        if _has_commerce_path_in_robots_or_sitemap(discovery):
            signals.append("/products or /collections path present in robots.txt or sitemap entries")
        if _has_platform_marker(homepage_html):
            signals.append("commerce platform marker found (Shopify/BigCommerce/WooCommerce)")
        if _has_any_offer_markup(pages):
            signals.append("Offer markup found on at least one fetched page")

        has_commerce_signals = bool(signals)
        has_product_pages = bool(_product_pages(pages))

        if has_commerce_signals and has_product_pages:
            return SiteTypeResult(site_type=SITE_TYPE_COMMERCE, reason="commerce signals present and product pages sampled", signals=signals)
        if has_commerce_signals:
            return SiteTypeResult(site_type=SITE_TYPE_DISCOVERY_FAILURE, reason=DISCOVERY_FAILURE_REASON, signals=signals)
        return SiteTypeResult(site_type=SITE_TYPE_BRAND_ONLY, reason=BRAND_ONLY_REASON, signals=signals)
    except Exception:
        log.exception("[scan.site_typing] classify_site failed unexpectedly")
        # Never-throw fallback: treat as a discovery failure rather than
        # a false brand-only claim — the honest-but-uncertain branch.
        return SiteTypeResult(site_type=SITE_TYPE_DISCOVERY_FAILURE, reason=DISCOVERY_FAILURE_REASON, signals=[])
