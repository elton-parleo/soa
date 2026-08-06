"""
offer_feed.py — F1/F2 (V4 report redesign): the report's OfferFeed rows
and product image, built from facts scorer.py/structured_data.py already
extract during the normal crawl. No new fetches — this module only
re-shapes ExtractedData/DimensionScore objects run_scan() already has in
scope, the same "sibling key on the existing dimensions JSON blob, no
migration" pattern engine.py already uses for sitemap_sampling/
agent_access_matrix/signing_enabled.
"""
from typing import Dict, List, Optional
from urllib.parse import urljoin

# H1: a row whose underlying dimension couldn't be measured this run
# (blocked/na) reads "unmeasured" — never "invisible", which would claim
# a real, absent signal rather than an unread one.
READABLE_SEEN = "seen"
READABLE_PARTIAL = "partial"
READABLE_INVISIBLE = "invisible"
READABLE_UNMEASURED = "unmeasured"


def _is_unmeasured(dim) -> bool:
    return dim is None or dim.coverage in ("blocked", "na")


def _readable_from_dimension(dim) -> str:
    if _is_unmeasured(dim):
        return READABLE_UNMEASURED
    if dim.score <= 0:
        return READABLE_INVISIBLE
    if dim.score >= dim.max:
        return READABLE_SEEN
    return READABLE_PARTIAL


def _all_products(pages) -> List:
    return [p for page in pages for p in (page.extracted.products if page.extracted else [])]


def _all_offers(products) -> List:
    return [o for p in products for o in p.offers]


def extract_product_image(pages) -> Optional[str]:
    """F2: the first schema.org Product.image found across the sampled
    pages, absolutized against the page it came from. None if no product
    on any sampled page declared one — never an OG tag, never a scraped
    <img>, never a placeholder."""
    for page in pages:
        if not page.extracted:
            continue
        for product in page.extracted.products:
            if not product.image:
                continue
            base_url = (page.fetch_result.final_url or page.fetch_result.url) if page.fetch_result else None
            return urljoin(base_url, product.image) if base_url else product.image
    return None


def extract_product_name(pages) -> Optional[str]:
    """1c: the first schema.org Product.name found across the sampled
    pages — same markup, same iteration order as extract_product_image,
    but resolved independently so a product with a name and no image (or
    vice versa) still surfaces the field it has. None if no product on
    any sampled page declared one."""
    for page in pages:
        if not page.extracted:
            continue
        for product in page.extracted.products:
            if product.name:
                return product.name
    return None


def build_offer_feed(pages, dim_scores: Dict) -> List[Dict]:
    """F1: one row per value signal — list price, availability, shipping,
    member price, deals/promos, checkout value — as {name, value, channel,
    eligibility, freshness, readable}. Every row is re-serialized from
    data scorer.py/structured_data.py already computed for the crawl-
    derived dimensions; nothing here re-fetches or re-parses a page."""
    products = _all_products(pages)
    offers = _all_offers(products)
    shipping_hits = [h for page in pages for h in (page.extracted.shipping_returns_text_hits if page.extracted else [])]

    price_dim = dim_scores.get("price_truth_seen")
    member_dim = dim_scores.get("member_value_seen")
    deal_dim = dim_scores.get("deal_citability_seen")
    protocol_dim = dim_scores.get("value_protocols_seen")

    priced_offers = [o for o in offers if o.price is not None]
    available_offers = [o for o in offers if o.availability]
    member_products = [p for p in products if p.has_member_price_hint]
    deal_products = [p for p in products if p.has_concrete_discount_hint]

    return [
        {
            "name": "List price",
            "value": f"${priced_offers[0].price:,.2f}" if priced_offers else "Not encoded",
            "channel": "schema.org" if priced_offers else "none found",
            "eligibility": f"{len(priced_offers)} of {len(offers)} offers" if offers else "no offers found",
            "freshness": "live" if priced_offers else "stale",
            "readable": _readable_from_dimension(price_dim),
        },
        {
            "name": "Availability",
            "value": available_offers[0].availability if available_offers else "Not declared",
            "channel": "schema.org" if available_offers else "none found",
            "eligibility": f"{len(available_offers)} of {len(offers)} offers" if offers else "no offers found",
            "freshness": "live" if available_offers else "stale",
            "readable": (
                READABLE_UNMEASURED if _is_unmeasured(price_dim)
                else READABLE_SEEN if available_offers else READABLE_INVISIBLE
            ),
        },
        {
            "name": "Shipping",
            "value": shipping_hits[0] if shipping_hits else "Not declared",
            "channel": "page copy" if shipping_hits else "none found",
            "eligibility": "text only, no structured threshold" if shipping_hits else "not found",
            "freshness": "live" if shipping_hits else "stale",
            "readable": (
                READABLE_UNMEASURED if _is_unmeasured(price_dim)
                else READABLE_PARTIAL if shipping_hits else READABLE_INVISIBLE
            ),
        },
        {
            "name": "Member price",
            "value": "Encoded on product data" if member_products else "N/A",
            "channel": "schema.org" if member_products else "none found",
            "eligibility": f"{len(member_products)} of {len(products)} products" if products else "no products found",
            "freshness": "live" if member_products else "stale",
            "readable": _readable_from_dimension(member_dim),
        },
        {
            "name": "Deals and promos",
            "value": "Encoded on product data" if deal_products else "Not encoded",
            "channel": "schema.org" if deal_products else "none",
            "eligibility": f"{len(deal_products)} of {len(products)} products" if products else "no products found",
            "freshness": "live" if deal_products else "stale",
            "readable": _readable_from_dimension(deal_dim),
        },
        {
            "name": "Checkout value",
            "value": "Declared" if protocol_dim and protocol_dim.score > 0 else "Nothing declared",
            "channel": "UCP / ACP",
            "eligibility": (
                "declaration found" if protocol_dim and protocol_dim.score > 0 else "no declaration found"
            ),
            "freshness": "live" if protocol_dim and protocol_dim.score > 0 else "stale",
            "readable": _readable_from_dimension(protocol_dim),
        },
    ]
