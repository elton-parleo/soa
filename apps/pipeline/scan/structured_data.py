"""
structured_data.py — JSON-LD + microdata extraction for the Agent Scan
engine. Pulls Product/ProductGroup/Offer/PriceSpecification/
Organization data plus loyalty, "was price" (compare-at/strikethrough),
identifier (gtin/mpn/sku/brand), and agentic-protocol markup signals out
of a page's HTML; scorer.py turns these into dimension scores.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# Provenance marker for this module's extraction logic — bumped whenever
# a change here would materially affect what a scan pulls out of a page
# (not scoring methodology; that's soa_shared.scan_dimensions.SCORER_
# VERSION). Stored as a sibling key on the scan's dimensions dict (see
# engine.py), same "absence on older rows implies the prior generation"
# convention SCORER_VERSION already uses — no migration needed. Bumped
# here: the JSON-LD traversal fix that makes nested product structures
# (hasVariant, isVariantOf, itemOffered, mainEntity) visible at all;
# "1" (never itself stored) is the generation before this fix existed.
EXTRACTION_REV = "2"

WAS_PRICE_CSS_HINTS = (
    "was-price", "compare-at", "strikethrough", "original-price", "list-price",
)
LOYALTY_TEXT_KEYWORDS = (
    "reward", "loyalty program", "member", "points", "tier", "insider", "vip",
)
SHIPPING_RETURNS_TEXT_KEYWORDS = (
    "free shipping", "return policy", "returns within", "ships in",
)
# Stage 25 (Part 2, P3): evidence-only signals — these never change a
# score (price_truth_seen/deal_citability_seen still treat these pages
# exactly as "no price"/"no deal shown", same as before), they only make
# the evidence string honest about WHY nothing was crawlable: a real
# gate the crawler correctly can't see behind, not a missing feature.
LOGIN_GATED_PRICE_TEXT_KEYWORDS = (
    "sign in to see price", "log in to see price", "sign in to view price",
    "login to view pricing", "members-only pricing", "sign in for pricing",
    "log in to view price",
)
EMAIL_GATED_DEAL_TEXT_KEYWORDS = (
    "enter your email to unlock", "sign up to reveal your discount",
    "get your code by email", "unlock your discount code",
    "join our email list for a discount", "subscribe for a discount code",
    "enter your email for a discount",
)

# Stage 25 (Part 2, P2): the exact schema.org vocabulary a member-price
# claim must use to count — the same vocabulary the landing page's own
# JSON-LD excerpt documents as valid (apps/api/web/src/lite/__tests__/
# AnatomyOfAnAnswer.test.jsx's JSONLD_KEY_ALLOWLIST: membershipPointsEarned,
# eligibleCustomerType) plus the memberPrice/loyaltyPrice convention
# scorer.py's own fix text already recommends. Replaces the old whole-blob
# substring scan (any of these words ANYWHERE in the node, including an
# unrelated description sentence) with structural validation at the right
# nesting level — see _detect_member_price_structure.
MEMBER_PRICE_FIELD_KEYS = ("memberPrice", "loyaltyPrice")
# Stage 25 (Part 2, P1): visible, currency-symbol-led prices in the page's
# own rendered text — the other half of the price-consistency check
# (scorer.py's _visible_body_price_mismatch). Requires a decimal component
# so stray non-price numerals ("5 reviews") don't count; ambiguity from
# ANY other dollar-looking text (a promo amount, a variant price) is
# handled by the scorer's own "exactly one distinct value" guard, not by
# a smarter regex here.
VISIBLE_PRICE_PATTERN = re.compile(r"\$\s?\d[\d,]*\.\d{2}\b")
# Stage 10 (D3): V4's CONCRETE/ACTIONABLE sub-checks mirror the deal_cited
# rubric's own CONCRETE/ACTIONABLE tests (apps/pipeline/parser/prompts.py,
# "DEAL CITATION RULES" — frozen per Stage 8 H1, read-only reference here).
CONCRETE_DISCOUNT_JSON_HINTS = (
    "discount", "% off", "percentoff", "bogo", "buy one", "save $", "savingsamount",
)
ACTIONABLE_JSON_HINTS = (
    "eligib", "promo code", "promocode", "coupon", "stackable", "combinable",
)
# Stage 10 (D2): no universal registry for these declarations exists to
# probe — these are same-origin, crawl-observable heuristics only (never
# a third-party lookup). Evidence strings always name the exact match.
AGENTIC_PROTOCOL_LINK_HINTS = ("mcp", "ucp", "uip")
AGENTIC_PROTOCOL_JSON_HINTS = (
    "mcp", "ucp", "uip", "agentic-commerce", "agent-discount", "machine-payable",
)
# F5: Open Graph / product: social-preview price meta — <meta
# property="og:price:amount" ...> or <meta property="product:price:
# amount" ...>, whichever a page uses. Evidence-only (see ExtractedData.
# og_price_meta_present's docstring) — never a price/currency source,
# since these tags are meant for link-preview cards, not agent parsing.
OG_PRICE_META_PROPERTIES = ("og:price:amount", "product:price:amount")


@dataclass
class OfferData:
    price: Optional[float] = None
    price_currency: Optional[str] = None
    availability: Optional[str] = None
    valid_through: Optional[str] = None


@dataclass
class ProductData:
    name: Optional[str] = None
    offers: list = field(default_factory=list)  # list[OfferData]
    has_member_price_hint: bool = False
    has_concrete_discount_hint: bool = False
    has_actionable_hint: bool = False
    gtin: Optional[str] = None
    mpn: Optional[str] = None
    sku: Optional[str] = None
    brand: Optional[str] = None
    # F2: schema.org Product.image — first value if the node declares a
    # list, exactly as-is from the markup (relative or absolute); the
    # caller absolutizes against the page URL, since this module never
    # sees it. Never OG/img-scraped — only the merchant's own product
    # markup, same discipline as every other structured field here.
    image: Optional[str] = None


@dataclass
class ExtractedData:
    products: list = field(default_factory=list)  # list[ProductData]
    organization_present: bool = False
    has_jsonld: bool = False
    has_microdata: bool = False
    was_price_signals: list = field(default_factory=list)       # list[str] evidence
    was_price_numeric: Optional[float] = None                   # best-effort was-price value
    loyalty_text_hits: list = field(default_factory=list)       # list[str]
    shipping_returns_text_hits: list = field(default_factory=list)  # list[str]
    raw_jsonld_types: list = field(default_factory=list)        # list[str]
    agentic_protocol_hints: list = field(default_factory=list)  # list[str] evidence
    visible_prices: list = field(default_factory=list)          # list[float], distinct, sorted
    login_gated_price_text_hits: list = field(default_factory=list)  # list[str], evidence-only
    email_gated_deal_text_hits: list = field(default_factory=list)   # list[str], evidence-only
    # F5: social-preview (Open Graph / product:) price meta — evidence-
    # only, never a scoring input. Lets score_price_truth_seen's "no
    # price found" evidence distinguish "nothing at all" from "a social
    # card exists, but not the schema.org markup agents actually parse."
    og_price_meta_present: bool = False
    # 1a: brand-icon candidates — <link rel="apple-touch-icon"> and
    # <link rel="icon"> declarations, each {"href": str, "sizes":
    # Optional[str]} exactly as declared (relative or absolute; the
    # caller in scan/brand_icon.py absolutizes against the page URL,
    # same division of labor as Product.image above). Only ever
    # meaningful on the homepage page — extracted uniformly here like
    # every other field, filtered to the homepage by the caller.
    apple_touch_icons: list = field(default_factory=list)
    icon_links: list = field(default_factory=list)
    # schema.org Organization.logo — first value found, string or
    # ImageObject.url, exactly as declared. Lowest-priority icon
    # candidate (see scan/brand_icon.py's precedence order).
    organization_logo: Optional[str] = None


def _coerce_price(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def _extract_offer(node: dict) -> OfferData:
    price = _coerce_price(node.get("price"))
    currency = node.get("priceCurrency")
    availability = node.get("availability")
    if isinstance(availability, str):
        availability = availability.rsplit("/", 1)[-1]

    price_spec = node.get("priceSpecification")
    valid_through = node.get("priceValidUntil")
    if isinstance(price_spec, dict):
        if price is None:
            price = _coerce_price(price_spec.get("price"))
        currency = currency or price_spec.get("priceCurrency")
        valid_through = valid_through or price_spec.get("validThrough")

    return OfferData(
        price=price,
        price_currency=currency,
        availability=availability,
        valid_through=valid_through,
    )


def _has_valid_eligible_customer_type(offer_node: dict) -> bool:
    """A real Offer.eligibleCustomerType — a non-empty string (or list of
    them), at the offer level, not merely the phrase appearing somewhere
    in the JSON."""
    value = offer_node.get("eligibleCustomerType")
    if isinstance(value, list):
        return any(isinstance(v, str) and v.strip() for v in value)
    return isinstance(value, str) and bool(value.strip())


def _has_valid_membership_points(offer_node: dict) -> bool:
    """A real numeric priceSpecification.membershipPointsEarned — schema.org's
    own UnitPriceSpecification property, not a stray text mention."""
    price_spec = offer_node.get("priceSpecification")
    if not isinstance(price_spec, dict):
        return False
    points = price_spec.get("membershipPointsEarned")
    return isinstance(points, (int, float)) and not isinstance(points, bool)


def _has_valid_member_price_field(node: dict) -> bool:
    """A dedicated memberPrice/loyaltyPrice field with an actual numeric
    price — either a bare number or a PriceSpecification-shaped dict."""
    for key in MEMBER_PRICE_FIELD_KEYS:
        value = node.get(key)
        if value is None:
            continue
        if isinstance(value, dict):
            if _coerce_price(value.get("price")) is not None:
                return True
        elif _coerce_price(value) is not None:
            return True
    return False


def _detect_member_price_structure(node: dict, offer_nodes: list) -> bool:
    """
    Stage 25 (Part 2, P2): strict-parse member-price detection — true only
    when an actually-typed schema.org structure is present at the right
    nesting level (a memberPrice/loyaltyPrice field on the product, or an
    Offer with eligibleCustomerType or priceSpecification.
    membershipPointsEarned), never a substring match anywhere in the raw
    JSON blob. A product description that merely mentions "member price"
    in prose no longer counts — the old MEMBER_PRICE_JSON_HINTS behavior.
    """
    if _has_valid_member_price_field(node):
        return True
    for offer_node in offer_nodes:
        if not isinstance(offer_node, dict):
            continue
        if _has_valid_eligible_customer_type(offer_node) or _has_valid_membership_points(offer_node):
            return True
    return False


def _first_str(value) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list) and value:
        return _first_str(value[0])
    return None


def _parse_money(text: str) -> Optional[float]:
    """Best-effort numeric parse of a price-looking text fragment — never
    raises; returns None for anything that isn't recognizably a number."""
    if not text:
        return None
    match = re.search(r"[\d,]+\.?\d*", text)
    if not match:
        return None
    return _coerce_price(match.group(0))


_MAX_JSONLD_DEPTH = 12


def _walk_jsonld_node(node, extracted: ExtractedData, _depth: int = 0) -> None:
    """
    Never raises — a malformed, self-referencing, or pathologically deep
    blob just stops descending past _MAX_JSONLD_DEPTH rather than
    stack-overflowing.

    Generic descent: after handling this node itself (type collection,
    Product/ProductGroup/Organization), recurse into every dict/list
    value the node carries, so nested product structures are visited
    wherever they appear — hasVariant, isVariantOf, itemOffered,
    mainEntity, @graph, and any future nesting — without a per-key
    special case. @graph used to be handled as its own explicit
    recursion; that's now just one more list-valued key the generic
    descent walks into, so it's folded in rather than kept separate.

    Offer nodes are still collected ONLY via a Product/ProductGroup's own
    `offers` key (inside the branch below) — the generic descent below
    will walk INTO an offers node too (e.g. to reach a legitimate nested
    Offer.itemOffered Product), but an Offer node itself is never typed
    Product/ProductGroup, so walking into one never appends a second,
    free-floating product for it.
    """
    if _depth > _MAX_JSONLD_DEPTH:
        return
    if isinstance(node, list):
        for item in node:
            _walk_jsonld_node(item, extracted, _depth + 1)
        return
    if not isinstance(node, dict):
        return

    node_type = node.get("@type")
    types = node_type if isinstance(node_type, list) else ([node_type] if node_type else [])
    extracted.raw_jsonld_types.extend(t for t in types if t)

    if any(t in ("Product", "ProductGroup") for t in types):
        product = ProductData(name=node.get("name") if isinstance(node.get("name"), str) else None)
        offers = node.get("offers")
        offer_nodes = offers if isinstance(offers, list) else ([offers] if offers else [])
        for offer_node in offer_nodes:
            if isinstance(offer_node, dict):
                product.offers.append(_extract_offer(offer_node))

        product.gtin = _first_str(node.get("gtin") or node.get("gtin13") or node.get("gtin12") or node.get("gtin8"))
        product.mpn = _first_str(node.get("mpn"))
        product.sku = _first_str(node.get("sku"))
        brand = node.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        product.brand = _first_str(brand)

        image = node.get("image")
        if isinstance(image, dict):
            # ImageObject shape: {"@type": "ImageObject", "url": "..."}
            image = image.get("url")
        product.image = _first_str(image)

        try:
            blob = json.dumps(node).lower()
        except (TypeError, ValueError):
            blob = ""
        product.has_member_price_hint = _detect_member_price_structure(node, offer_nodes)
        product.has_concrete_discount_hint = any(kw in blob for kw in CONCRETE_DISCOUNT_JSON_HINTS)
        product.has_actionable_hint = any(kw in blob for kw in ACTIONABLE_JSON_HINTS)
        if any(kw in blob for kw in AGENTIC_PROTOCOL_JSON_HINTS):
            matched = sorted(kw for kw in AGENTIC_PROTOCOL_JSON_HINTS if kw in blob)
            extracted.agentic_protocol_hints.append(f"structured data mentions: {matched}")

        extracted.products.append(product)

    if "Organization" in types:
        extracted.organization_present = True
        if extracted.organization_logo is None:
            logo = node.get("logo")
            if isinstance(logo, dict):
                # ImageObject shape: {"@type": "ImageObject", "url": "..."}
                logo = logo.get("url")
            logo = _first_str(logo)
            if logo:
                extracted.organization_logo = logo

    for value in node.values():
        if isinstance(value, (dict, list)):
            _walk_jsonld_node(value, extracted, _depth + 1)


def extract(html: str) -> ExtractedData:
    """
    Never raises — malformed JSON-LD blocks, garbage HTML, or missing
    markup entirely all yield an ExtractedData with empty/default
    fields rather than propagating.
    """
    extracted = ExtractedData()
    if not html:
        return extracted

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        log.exception("[scan.structured_data] failed to parse HTML")
        return extracted

    try:
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = (script.string or script.get_text() or "").strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            extracted.has_jsonld = True
            _walk_jsonld_node(data, extracted)
    except Exception:
        log.exception("[scan.structured_data] failed to extract JSON-LD")

    try:
        if soup.find(attrs={"itemtype": re.compile(r"schema\.org/Product", re.I)}):
            extracted.has_microdata = True
    except Exception:
        pass

    try:
        # Stage 25 (Part 2, P1): strip script/style before any visible-text
        # scan below — without this, a page's own JSON-LD price would
        # trivially "match itself" as the visible-text price, defeating the
        # whole point of the consistency check (and the pre-existing
        # loyalty/shipping keyword scans would pick up script contents too).
        for tag in soup.find_all(["script", "style"]):
            tag.decompose()
    except Exception:
        log.exception("[scan.structured_data] failed to strip script/style before text scans")

    try:
        was_price_matches = set()
        was_price_texts = []
        for el in soup.find_all(["del", "s", "strike"]):
            text = el.get_text(strip=True)
            if text:
                was_price_matches.add(f"strikethrough element: {text!r}")
                was_price_texts.append(text)
        for el in soup.find_all(class_=True):
            classes = " ".join(el.get("class", [])).lower()
            if any(hint in classes for hint in WAS_PRICE_CSS_HINTS):
                text = el.get_text(strip=True)
                if text:
                    was_price_matches.add(f"class={classes!r}: {text!r}")
                    was_price_texts.append(text)
        extracted.was_price_signals = sorted(was_price_matches)
        # Stage 10 (D4): best-effort numeric value of a was-price signal,
        # needed to compute discount depth against the current offer price.
        # Never raises — an unparseable fragment just leaves this None.
        for text in was_price_texts:
            parsed = _parse_money(text)
            if parsed is not None:
                extracted.was_price_numeric = parsed
                break
    except Exception:
        log.exception("[scan.structured_data] failed to scan for was-price signals")

    try:
        # Stage 25 (Part 2, P1): every distinct dollar-formatted price in
        # the page's own visible text (script/style already stripped
        # above) — the scorer compares this against the structured Offer
        # price; more than one distinct value here means the page is
        # ambiguous (variants, a sale pair, an unrelated dollar figure)
        # and the scorer's own guard skips the check entirely rather than
        # guessing which one is "the" price.
        prices = set()
        for match in VISIBLE_PRICE_PATTERN.findall(soup.get_text(" ", strip=True)):
            parsed = _parse_money(match)
            if parsed is not None:
                prices.add(round(parsed, 2))
        extracted.visible_prices = sorted(prices)
    except Exception:
        log.exception("[scan.structured_data] failed to scan for visible body prices")

    try:
        # "link markup" (D2) means an explicit <link>/<meta> declaration,
        # e.g. <link rel="mcp-manifest" href="...">  — deliberately NOT
        # scanning <a> hrefs/text, which would false-positive on ordinary
        # navigation links far too easily for a 3-letter substring match.
        for tag in soup.find_all(["link", "meta"]):
            rel = " ".join(tag.get("rel", []) if isinstance(tag.get("rel"), list) else [tag.get("rel") or ""])
            name_attr = tag.get("name") or ""
            haystack = f"{rel} {name_attr}".lower()
            matched = [kw for kw in AGENTIC_PROTOCOL_LINK_HINTS if kw in haystack]
            if matched:
                extracted.agentic_protocol_hints.append(
                    f"<{tag.name}> markup mentions: {sorted(set(matched))}"
                )
    except Exception:
        log.exception("[scan.structured_data] failed to scan for agentic-protocol link markup")

    try:
        # 1a: brand-icon <link> declarations — apple-touch-icon(-precomposed)
        # and icon/shortcut-icon, each kept with its own `sizes` attribute
        # (if any) so the caller (scan/brand_icon.py) can pick the largest
        # per tier. href/sizes kept exactly as declared; absolutizing
        # against the page URL is the caller's job, same division of
        # labor as Product.image above.
        for tag in soup.find_all("link"):
            rel = tag.get("rel") or []
            if isinstance(rel, str):
                rel = rel.split()
            href = tag.get("href")
            if not href:
                continue
            if "apple-touch-icon" in rel or "apple-touch-icon-precomposed" in rel:
                extracted.apple_touch_icons.append({"href": href, "sizes": tag.get("sizes")})
            elif "icon" in rel:
                extracted.icon_links.append({"href": href, "sizes": tag.get("sizes")})
    except Exception:
        log.exception("[scan.structured_data] failed to scan for icon <link> tags")

    try:
        # F5: evidence-only — never a price/currency source (see
        # ExtractedData.og_price_meta_present's docstring).
        for tag in soup.find_all("meta"):
            prop = (tag.get("property") or "").strip().lower()
            if prop in OG_PRICE_META_PROPERTIES and tag.get("content"):
                extracted.og_price_meta_present = True
                break
    except Exception:
        log.exception("[scan.structured_data] failed to scan for OG price meta")

    try:
        body_text = soup.get_text(" ", strip=True).lower()
        extracted.loyalty_text_hits = [kw for kw in LOYALTY_TEXT_KEYWORDS if kw in body_text]
        extracted.shipping_returns_text_hits = [
            kw for kw in SHIPPING_RETURNS_TEXT_KEYWORDS if kw in body_text
        ]
        extracted.login_gated_price_text_hits = [
            kw for kw in LOGIN_GATED_PRICE_TEXT_KEYWORDS if kw in body_text
        ]
        extracted.email_gated_deal_text_hits = [
            kw for kw in EMAIL_GATED_DEAL_TEXT_KEYWORDS if kw in body_text
        ]
    except Exception:
        log.exception("[scan.structured_data] failed to scan body text")

    return extracted
