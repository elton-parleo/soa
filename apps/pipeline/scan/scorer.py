"""
scorer.py — the 8-dimension Agent Scan rubric. Deterministic and
rule-based (no LLM calls in this stage). Each dimension function takes
the scan's collected page data and returns a DimensionScore; engine.py
sums them into ScanResult.total_score and applies the V5 integrity cap.

Weights (Foundation 35 / Value 65):
  F1 agent_access       10
  F2 catalog_context    15
  F3 transaction_rails  10
  V1 offer_legibility   15
  V2 loyalty_surface    14
  V3 member_value       14
  V4 value_rails        10
  V5 offer_integrity    12
"""
from dataclasses import dataclass, field
from typing import Optional

WEIGHTS = {
    "F1": 10, "F2": 15, "F3": 10,
    "V1": 15, "V2": 14, "V3": 14, "V4": 10, "V5": 12,
}

INTEGRITY_CAP = 59


@dataclass
class DimensionScore:
    score: float
    max: float
    evidence: list = field(default_factory=list)
    fix: Optional[str] = None


def _product_pages(pages):
    return [p for p in pages if p.candidate.kind == "product"]


def score_f1_agent_access(discovery, pages) -> DimensionScore:
    weight = WEIGHTS["F1"]
    evidence = []
    points = 0.0

    if discovery.robots_fetch.status == "fetched":
        points += weight * 0.3
        evidence.append("robots.txt is fetchable")

        product_urls = [p.candidate.url for p in _product_pages(pages)]
        disallowed = []
        if discovery.robot_parser is not None:
            disallowed = [
                u for u in product_urls
                if not discovery.robot_parser.can_fetch("ParleoScanBot/1.0", u)
            ]
        if not disallowed:
            points += weight * 0.4
            evidence.append("robots.txt allows product paths")
        else:
            evidence.append(f"robots.txt disallows: {disallowed}")
    else:
        evidence.append(f"robots.txt not fetchable (status={discovery.robots_fetch.status})")

    blocked_pages = [p for p in pages if p.fetch_result.status == "blocked"]
    if not blocked_pages:
        points += weight * 0.2
        evidence.append("no bot-blocking encountered on sampled pages")
    else:
        evidence.append(f"{len(blocked_pages)} page(s) returned bot-blocked responses")

    if discovery.sitemap_urls:
        points += weight * 0.1
        evidence.append(f"sitemap present ({len(discovery.sitemap_urls)} URLs)")
    else:
        evidence.append("no sitemap found")

    fix = None
    if points < weight - 0.01:
        fix = (
            "Ensure robots.txt allows crawler access to product pages and "
            "publish a sitemap.xml with <loc> entries for every product."
        )
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix)


def score_f2_catalog_context(pages) -> DimensionScore:
    weight = WEIGHTS["F2"]
    product_pages = _product_pages(pages)
    evidence = []

    if not product_pages:
        evidence.append("no product pages sampled")
        return DimensionScore(
            score=0.0, max=weight, evidence=evidence,
            fix="Publish Product+Offer JSON-LD on product pages so agents can read name, price, and availability directly.",
        )

    complete_count = 0
    for p in product_pages:
        products = p.extracted.products if p.extracted else []
        page_ok = False
        for prod in products:
            has_price = any(o.price is not None for o in prod.offers)
            has_availability = any(o.availability for o in prod.offers)
            if prod.name and prod.offers and has_price and has_availability:
                page_ok = True
        if page_ok:
            complete_count += 1
            evidence.append(f"{p.candidate.url}: complete Product+Offer JSON-LD")
        else:
            evidence.append(f"{p.candidate.url}: missing/incomplete Product+Offer JSON-LD")

    ratio = complete_count / len(product_pages)
    score = round(weight * ratio, 1)
    fix = None
    if ratio < 1.0:
        fix = (
            'Add complete Product JSON-LD (name, offers[].price, offers[].priceCurrency, '
            'offers[].availability) to every product page, e.g. '
            '{"@type":"Product","name":"...","offers":{"@type":"Offer","price":"29.99",'
            '"priceCurrency":"USD","availability":"https://schema.org/InStock"}}.'
        )
    return DimensionScore(score=score, max=weight, evidence=evidence, fix=fix)


def score_f3_transaction_rails(pages) -> DimensionScore:
    weight = WEIGHTS["F3"]
    evidence = []
    points = 0.0
    product_pages = _product_pages(pages)

    with_availability = [
        p for p in product_pages
        if p.extracted and any(o.availability for prod in p.extracted.products for o in prod.offers)
    ]
    if product_pages:
        avail_ratio = len(with_availability) / len(product_pages)
        points += weight * 0.5 * avail_ratio
        if avail_ratio == 1.0:
            evidence.append("all sampled product pages declare availability")
        elif avail_ratio > 0:
            evidence.append(f"{len(with_availability)}/{len(product_pages)} product pages declare availability")
        else:
            evidence.append("no product pages declare machine-readable availability")
    else:
        evidence.append("no product pages sampled")

    shipping_pages = [p for p in pages if p.candidate.kind == "shipping_returns"]
    shipping_found = any(
        p.fetch_result.status == "fetched" and p.extracted and p.extracted.shipping_returns_text_hits
        for p in shipping_pages
    )
    if shipping_found:
        points += weight * 0.5
        evidence.append("shipping/returns terms discoverable as text")
    else:
        evidence.append("no discoverable shipping/returns terms")

    fix = None
    if points < weight - 0.01:
        fix = (
            "Declare `availability` on every Offer and publish shipping/returns terms as "
            "crawlable text or OfferShippingDetails structured data."
        )
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix)


def score_v1_offer_legibility(pages) -> DimensionScore:
    weight = WEIGHTS["V1"]
    product_pages = _product_pages(pages)

    if not product_pages:
        return DimensionScore(
            score=0.0, max=weight, evidence=["no product pages sampled"],
            fix="Publish machine-readable prices with declared currency on product pages.",
        )

    with_price = [
        p for p in product_pages
        if p.extracted and any(o.price is not None for prod in p.extracted.products for o in prod.offers)
    ]
    with_currency = [
        p for p in product_pages
        if p.extracted and any(o.price_currency for prod in p.extracted.products for o in prod.offers)
    ]

    price_ratio = len(with_price) / len(product_pages)
    currency_ratio = len(with_currency) / len(product_pages)
    points = weight * 0.6 * price_ratio + weight * 0.4 * currency_ratio

    evidence = [
        f"{len(with_price)}/{len(product_pages)} product pages expose machine-readable price",
        f"{len(with_currency)}/{len(product_pages)} product pages declare priceCurrency",
    ]
    fix = None
    if points < weight - 0.01:
        fix = (
            'Expose price and priceCurrency in Offer JSON-LD, e.g. '
            '"offers": {"@type": "Offer", "price": "29.99", "priceCurrency": "USD"} '
            '— not just in an image or JS-rendered banner.'
        )
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix)


def score_v2_loyalty_surface(pages) -> DimensionScore:
    weight = WEIGHTS["V2"]
    loyalty_pages = [p for p in pages if p.candidate.kind == "loyalty"]

    if not loyalty_pages:
        return DimensionScore(
            score=0.0, max=weight, evidence=["no loyalty/rewards page found in nav/footer"],
            fix="Add a discoverable loyalty/rewards page linked from the nav or footer (e.g. link text containing 'Rewards' or 'Loyalty').",
        )

    evidence = []
    points = 0.0
    lp = loyalty_pages[0]

    if lp.fetch_result.status == "fetched":
        points += weight * 0.4
        evidence.append(f"loyalty page found and fetchable: {lp.candidate.url}")
        hits = lp.extracted.loyalty_text_hits if lp.extracted else []
        if hits:
            points += weight * 0.6
            evidence.append(f"program terms present in text: {hits}")
        else:
            evidence.append("loyalty page fetchable but no program terms detected")
    else:
        evidence.append(f"loyalty page found but not fetchable (status={lp.fetch_result.status})")

    fix = None
    if points < weight - 0.01:
        fix = (
            "Publish loyalty program terms (tiers, points, benefits) as crawlable text or "
            "structured data on the rewards page, not behind login/JS."
        )
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix)


def score_v3_member_value(pages) -> DimensionScore:
    weight = WEIGHTS["V3"]
    product_pages = _product_pages(pages)

    if not product_pages:
        return DimensionScore(
            score=0.0, max=weight, evidence=["no product pages sampled"],
            fix="Expose member/tier pricing in structured data on product pages.",
        )

    with_member_price = [
        p for p in product_pages
        if p.extracted and any(prod.has_member_price_hint for prod in p.extracted.products)
    ]
    ratio = len(with_member_price) / len(product_pages)
    points = weight * ratio

    if with_member_price:
        evidence = [f"{len(with_member_price)}/{len(product_pages)} product pages expose member/tier pricing in structured data"]
    else:
        evidence = ["no structured member/tier pricing found on sampled product pages"]

    fix = None
    if ratio < 0.99:
        fix = (
            'Add member pricing as structured data, not just marketing copy — e.g. a second '
            'Offer with "eligibleCustomerType": "https://schema.org/LoyaltyProgramMember" or a '
            "memberPrice field."
        )
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix)


def score_v4_value_rails(pages) -> DimensionScore:
    weight = WEIGHTS["V4"]
    product_pages = _product_pages(pages)

    if not product_pages:
        return DimensionScore(
            score=0.0, max=weight, evidence=["no product pages sampled"],
            fix="Declare discounts/bundles as Offers with priceValidUntil.",
        )

    with_validity = [
        p for p in product_pages
        if p.extracted and any(o.valid_through for prod in p.extracted.products for o in prod.offers)
    ]
    ratio = len(with_validity) / len(product_pages)
    points = weight * ratio

    if with_validity:
        evidence = [f"{len(with_validity)}/{len(product_pages)} product pages declare offer validity dates"]
    else:
        evidence = ["no offer validity dates (priceValidUntil) found"]

    fix = None
    if ratio < 0.99:
        fix = 'Declare discount/bundle validity with "priceValidUntil" on the Offer so agents know if a promotion is still live.'
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix)


def score_v5_offer_integrity(pages):
    """
    Returns (DimensionScore, integrity_cap_triggered). Starts at full
    marks; deducts when a "was" price (strikethrough/compare-at) appears
    with no evidence it was ever the real price. Heuristic: a was-price
    signal present on every sampled product page reads as always-on-sale
    — a store with an occasional, genuine sale would not show a
    strikethrough price on literally every page sampled.
    """
    weight = WEIGHTS["V5"]
    product_pages = _product_pages(pages)

    if not product_pages:
        return (
            DimensionScore(score=weight, max=weight, evidence=["no product pages sampled — no dishonest pricing signal detected"], fix=None),
            False,
        )

    pages_with_was_price = [p for p in product_pages if p.extracted and p.extracted.was_price_signals]
    ratio = len(pages_with_was_price) / len(product_pages)

    always_on_sale = ratio >= 1.0
    if always_on_sale:
        evidence = [
            f"was-price signal present on {len(pages_with_was_price)}/{len(product_pages)} "
            "sampled product pages with no evidence of a genuine baseline price — treated as always-on-sale",
        ]
        for p in pages_with_was_price:
            evidence.extend(f"{p.candidate.url}: {sig}" for sig in p.extracted.was_price_signals)
        fix = (
            'Only show a "was" price when it reflects a genuine prior selling price for a '
            "limited time — a compare-at price shown on every visit reads as fabricated to a "
            "price-integrity check."
        )
        return DimensionScore(score=0.0, max=weight, evidence=evidence, fix=fix), True

    if pages_with_was_price:
        evidence = [
            f"was-price signal present on {len(pages_with_was_price)}/{len(product_pages)} "
            "sampled pages — no always-on-sale pattern detected",
        ]
        score = round(weight * (1 - 0.3 * ratio), 1)
        return DimensionScore(score=score, max=weight, evidence=evidence, fix=None), False

    return (
        DimensionScore(score=weight, max=weight, evidence=["no dishonest pricing signals detected"], fix=None),
        False,
    )
