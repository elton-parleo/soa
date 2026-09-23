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
  product pages read, no Offer on any, retailer
    links, no store controls (see below)         -> manufacturer
  commerce signals + product pages sampled       -> commerce_normal
  commerce signals + NO product pages found      -> commerce_discovery_failure
  no commerce signals anywhere                   -> brand_only

Manufacturer sites (Clorox, request 146): real product pages with
Product JSON-LD and GTINs, but no Offer anywhere — the brand sells
through retailers ("please enable cookies to find retailers"). Its zero
price truth and deal citability are correct scores; what is wrong is a
report that asks it to publish prices it has no way to publish. The
type is positive evidence only, and deliberately narrow: at least one
product page READ, zero Offer markup on every read product page, a
where-to-buy/find-a-retailer signal on a product page or the homepage,
and none of the things a store has — no add-to-cart control on a
product page, no store-platform marker. A single Offer anywhere rules it
out. Presentation only: no scorer branches on this type (scorer.py
checks brand_only alone), so every score is exactly what it would have
been as commerce_normal.

Discovery follow-up (Part 5): _has_commerce_path_in_robots_or_sitemap
used to do a bare substring test for "/products"/"/collections"
against every sitemap PAGE URL — which reads a real editorial/
corporate site's own prose ("...for-our-products/", "...creating-
breakthrough-products-through-collaborative-play/") as a commerce
signal, purely because the English word "products" shows up in a URL
slug. Now requires an actual PATH SEGMENT match for page URLs; the
looser bare-word check stays only for child-SITEMAP FILENAMES (e.g.
Shopify's "sitemap_products_1.xml"), which are never prose to begin
with. loreal.com is the fixture this was caught against — see
test_site_typing.py.
"""
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

SITE_TYPE_COMMERCE = "commerce_normal"
SITE_TYPE_DISCOVERY_FAILURE = "commerce_discovery_failure"
SITE_TYPE_BRAND_ONLY = "brand_only"
SITE_TYPE_MANUFACTURER = "manufacturer"

DISCOVERY_FAILURE_REASON = "product pages could not be discovered from sitemap or navigation"
BRAND_ONLY_REASON = "no cart, commerce paths, platform markers, or Offer markup found"
MANUFACTURER_REASON = "product pages carry no Offer markup and point shoppers to retailers"

# Visible text on a link or button that sends a shopper to someone
# else's store. "find retailers" is Clorox's own wording.
RETAILER_LINK_PHRASES = (
    "where to buy", "find a retailer", "find retailers", "buy now", "buy online", "find a store near",
)
# Embedded where-to-buy widgets, recognized in the markup itself —
# PriceSpider and Destini are the two brand sites use most.
RETAILER_WIDGET_MARKERS = ("ps-widget", "pricespider", "destini", "where-to-buy", "wheretobuy")
# A product page that offers its own basket is a store, whatever else
# it lacks.
ADD_TO_CART_PHRASES = ("add to cart", "add to bag", "add to basket")

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


# Discovery follow-up (Part 5): /products or /collections as a genuine
# PATH SEGMENT — bounded by slashes on both sides — never a bare
# substring test. loreal.com (a corporate/editorial site, no catalog)
# was misread as commerce_discovery_failure purely because its OWN
# prose URL slugs happen to contain the word "products" —
# ".../for-our-products/", ".../creating-breakthrough-products-
# through-collaborative-play/" — English sentences, not a /products/
# catalog path. Applied to real page URLs (discovery.sitemap_urls) and
# to robots.txt's own directive text; sitemap_index_entries (child-
# sitemap FILENAMES, e.g. Shopify's "sitemap_products_1.xml" — never a
# page URL with unrelated path segments a bare word could collide
# with) keeps the looser bare-word check it always had.
_COMMERCE_PATH_SEGMENT_RE = re.compile(r"/(?:products?|collections?)(?:/|$)")


def _has_commerce_path_in_robots_or_sitemap(discovery) -> bool:
    robots_html = (discovery.robots_fetch.html or "") if discovery.robots_fetch else ""
    if _COMMERCE_PATH_SEGMENT_RE.search(robots_html.lower()):
        return True

    for u in discovery.sitemap_urls or []:
        if _COMMERCE_PATH_SEGMENT_RE.search(urlparse(u).path.lower()):
            return True

    bare_hints = tuple(hint.lstrip("/") for hint in COMMERCE_PATH_HINTS)
    index_entries = [u.lower() for u in (discovery.sitemap_index_entries or [])]
    return any(hint in u for u in index_entries for hint in bare_hints)


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


def _control_texts(html: str) -> list:
    """Lowercased visible text and aria-label of every link and button.
    Never raises."""
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")
        texts = []
        for el in soup.find_all(["a", "button"]):
            texts.append((el.get_text(" ", strip=True) or "").lower())
            label = el.get("aria-label")
            if label:
                texts.append(str(label).lower())
        return texts
    except Exception:
        log.exception("[scan.site_typing] failed to read link/button text")
        return []


def _has_retailer_link(html: str) -> bool:
    if not html:
        return False
    lowered = html.lower()
    if any(marker in lowered for marker in RETAILER_WIDGET_MARKERS):
        return True
    return any(phrase in text for text in _control_texts(html) for phrase in RETAILER_LINK_PHRASES)


def _has_add_to_cart(html: str) -> bool:
    return any(phrase in text for text in _control_texts(html) for phrase in ADD_TO_CART_PHRASES)


def _manufacturer_signals(pages, homepage_html) -> list:
    """The manufacturer evidence (see this module's docstring), or []
    when any part of it is missing. Never raises."""
    try:
        read_pdps = [
            p for p in _product_pages(pages)
            if p.fetch_result is not None and p.fetch_result.status == "fetched" and p.extracted
        ]
        if not read_pdps:
            return []
        if any(prod.offers for p in read_pdps for prod in p.extracted.products):
            return []
        if not any(p.extracted.products for p in read_pdps):
            return []
        if _has_platform_marker(homepage_html):
            return []
        if any(_has_add_to_cart(p.fetch_result.html) for p in read_pdps):
            return []
        on_pdp = any(_has_retailer_link(p.fetch_result.html) for p in read_pdps)
        if not on_pdp and not _has_retailer_link(homepage_html):
            return []
        return [
            f"{len(read_pdps)} product page(s) read with Product markup and no Offer markup",
            "where-to-buy / find-a-retailer link found on "
            + ("a product page" if on_pdp else "the homepage"),
            "no add-to-cart control or store-platform marker found",
        ]
    except Exception:
        log.exception("[scan.site_typing] manufacturer check failed")
        return []


def _has_any_offer_markup(pages) -> bool:
    return any(
        prod.offers
        for p in pages if p.extracted
        for prod in p.extracted.products
    )


def commerce_signals(homepage_html, discovery, pages=()) -> list:
    """The positive commerce evidence classify_site types a site on, as
    evidence strings — empty means none. Split out (loyalty-candidate
    fix) so discovery.py can ask the same question, the same way, before
    it samples a loyalty page: a brand-only site has no loyalty PROGRAM
    to score, and Loreal's corporate "Executive Committee" link scored
    member value 5/5 because nothing asked first. `discovery` needs only
    robots_fetch, sitemap_urls and sitemap_index_entries; `pages` only
    matters for the Offer-markup signal. Never raises."""
    signals = []
    try:
        if _has_cart_checkout_link(homepage_html):
            signals.append("cart/checkout link or form found in homepage nav/footer")
        if _has_commerce_path_in_robots_or_sitemap(discovery):
            signals.append("/products or /collections path present in robots.txt or sitemap entries")
        if _has_platform_marker(homepage_html):
            signals.append("commerce platform marker found (Shopify/BigCommerce/WooCommerce)")
        if _has_any_offer_markup(pages):
            signals.append("Offer markup found on at least one fetched page")
    except Exception:
        log.exception("[scan.site_typing] commerce signal check failed")
    return signals


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

        manufacturer = _manufacturer_signals(pages, homepage_html)
        if manufacturer:
            return SiteTypeResult(site_type=SITE_TYPE_MANUFACTURER, reason=MANUFACTURER_REASON, signals=manufacturer)

        signals = commerce_signals(homepage_html, discovery, pages)

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
