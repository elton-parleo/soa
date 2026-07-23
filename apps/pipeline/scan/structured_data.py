"""
structured_data.py — JSON-LD + microdata extraction for the Agent Scan
engine. Pulls Product/ProductGroup/Offer/PriceSpecification/
Organization data plus loyalty and "was price" (compare-at/
strikethrough) signals out of a page's HTML; scorer.py turns these into
dimension scores.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

WAS_PRICE_CSS_HINTS = (
    "was-price", "compare-at", "strikethrough", "original-price", "list-price",
)
LOYALTY_TEXT_KEYWORDS = (
    "reward", "loyalty program", "member", "points", "tier", "insider", "vip",
)
SHIPPING_RETURNS_TEXT_KEYWORDS = (
    "free shipping", "return policy", "returns within", "ships in",
)
MEMBER_PRICE_JSON_HINTS = (
    "memberprice", "member price", "loyaltyprice",
    "eligiblecustomertype", "membershippointsearned",
)


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


@dataclass
class ExtractedData:
    products: list = field(default_factory=list)  # list[ProductData]
    organization_present: bool = False
    has_jsonld: bool = False
    has_microdata: bool = False
    was_price_signals: list = field(default_factory=list)       # list[str] evidence
    loyalty_text_hits: list = field(default_factory=list)       # list[str]
    shipping_returns_text_hits: list = field(default_factory=list)  # list[str]
    raw_jsonld_types: list = field(default_factory=list)        # list[str]


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


def _walk_jsonld_node(node, extracted: ExtractedData) -> None:
    if isinstance(node, list):
        for item in node:
            _walk_jsonld_node(item, extracted)
        return
    if not isinstance(node, dict):
        return

    node_type = node.get("@type")
    types = node_type if isinstance(node_type, list) else ([node_type] if node_type else [])
    extracted.raw_jsonld_types.extend(t for t in types if t)

    if "@graph" in node:
        _walk_jsonld_node(node["@graph"], extracted)

    if any(t in ("Product", "ProductGroup") for t in types):
        product = ProductData(name=node.get("name") if isinstance(node.get("name"), str) else None)
        offers = node.get("offers")
        offer_nodes = offers if isinstance(offers, list) else ([offers] if offers else [])
        for offer_node in offer_nodes:
            if isinstance(offer_node, dict):
                product.offers.append(_extract_offer(offer_node))

        try:
            blob = json.dumps(node).lower()
        except (TypeError, ValueError):
            blob = ""
        product.has_member_price_hint = any(kw in blob for kw in MEMBER_PRICE_JSON_HINTS)

        extracted.products.append(product)

    if "Organization" in types:
        extracted.organization_present = True


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
        was_price_matches = set()
        for el in soup.find_all(["del", "s", "strike"]):
            text = el.get_text(strip=True)
            if text:
                was_price_matches.add(f"strikethrough element: {text!r}")
        for el in soup.find_all(class_=True):
            classes = " ".join(el.get("class", [])).lower()
            if any(hint in classes for hint in WAS_PRICE_CSS_HINTS):
                text = el.get_text(strip=True)
                if text:
                    was_price_matches.add(f"class={classes!r}: {text!r}")
        extracted.was_price_signals = sorted(was_price_matches)
    except Exception:
        log.exception("[scan.structured_data] failed to scan for was-price signals")

    try:
        body_text = soup.get_text(" ", strip=True).lower()
        extracted.loyalty_text_hits = [kw for kw in LOYALTY_TEXT_KEYWORDS if kw in body_text]
        extracted.shipping_returns_text_hits = [
            kw for kw in SHIPPING_RETURNS_TEXT_KEYWORDS if kw in body_text
        ]
    except Exception:
        log.exception("[scan.structured_data] failed to scan body text")

    return extracted
