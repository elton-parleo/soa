"""
scorer.py — the 8-dimension Agent Scan rubric. Deterministic and
rule-based (no LLM calls in this stage). Each dimension function takes
the scan's collected page data and returns a DimensionScore; engine.py
sums them into ScanResult.total_score and applies the V5 integrity cap.

Weights (Foundation 35 / Value 65) — numerically unchanged since Stage 1;
Stage 10 changed rubric semantics only (scorer_version "2"):
  F1 agent_access             10
  F2 catalog_context          15
  F3 protocol_feed_presence   10  (was "transaction_rails")
  V1 offer_legibility         15
  V2 loyalty_surface          14
  V3 member_value             14
  V4 value_rails              10
  V5 offer_integrity          12

Stage 10 (S2/S3): every DimensionScore carries a `coverage` of "full",
"partial" (some of its scored basis is crawl-unverifiable — see
deferred_items — but nothing here ever subtracts a point for a deferred
item), or "na" (inapplicable to this site type — excluded from every
sum by engine.py/public_lite.py, not scored as zero). F3 and V5 are
"partial" by definition under scorer_version "2": each always carries at
least one deferred_item.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from soa_shared.scan_dimensions import DIMENSIONS_BY_CODE

from . import site_typing

WEIGHTS = {
    "F1": 10, "F2": 15, "F3": 10,
    "V1": 15, "V2": 14, "V3": 14, "V4": 10, "V5": 12,
}

INTEGRITY_CAP = 59

PROTOCOL_FEED_DEFERRED_ITEMS = [
    {
        "label": "Merchant Center / Deal Directory participation",
        "reason": "loyalty-field participation in a merchant feed isn't observable from a same-origin crawl",
    },
    {
        "label": "ACP Promotions participation",
        "reason": "Agentic Commerce Protocol promotion enrollment lives in a third-party registry, not on-site markup",
    },
    {
        "label": "Feed-level incentive syndication",
        "reason": "syndicated feed contents aren't reachable by crawling the storefront itself",
    },
]

PRICE_HISTORY_DEFERRED_ITEM = {
    "label": "Price-history integrity",
    "reason": "requires repeat observation over time — a single crawl cannot verify whether a 'was' price was ever real",
}


@dataclass
class DimensionScore:
    score: float
    max: float
    evidence: list = field(default_factory=list)
    fix: Optional[str] = None
    coverage: str = "full"  # full | partial | na
    deferred_items: list = field(default_factory=list)  # [{label, reason}]
    cap_basis: list = field(default_factory=list)  # V5 only — evidence lines that justified a cap


def _product_pages(pages):
    return [p for p in pages if p.candidate.kind == "product"]


def _no_product_pages_score(
    weight: float, site_type_result, fix: Optional[str], *, na_on_brand_only: bool = False,
) -> DimensionScore:
    """
    Stage 11 (T2): a dimension whose scoring depends on sampled product
    pages, when none were found, is scored differently depending on
    WHY none were found — never as a blanket "not applicable" claim
    (Stage 10 D5's old behavior, which conflated the two):
      brand_only                 -> na_on_brand_only picks the coverage:
                                     'na' for a dimension that was already
                                     na-eligible under Stage 10 (V3), or
                                     honestly zero at coverage='full' for
                                     one that never was (F2/V1/V4) — a
                                     non-commerce site just has nothing
                                     for those to score, not "n/a".
      commerce_discovery_failure  -> coverage='partial' with the honest
                                     discovery-failure reason — the site
                                     IS commerce, the crawl just couldn't
                                     find its products this run.
    """
    if site_type_result.site_type == site_typing.SITE_TYPE_BRAND_ONLY:
        return DimensionScore(
            score=0.0, max=weight, coverage="na" if na_on_brand_only else "full",
            evidence=[f"no product pages sampled — {site_type_result.reason}"],
        )
    return DimensionScore(
        score=0.0, max=weight, coverage="partial",
        evidence=[site_type_result.reason], fix=fix,
    )


def _parse_date(value) -> Optional[datetime]:
    """Tolerant ISO-8601-ish date/datetime parse — never raises; returns
    None for anything unparseable rather than propagating."""
    if not value:
        return None
    text = str(value).strip()
    try:
        if len(text) == 10:
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


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


def score_f2_catalog_context(pages, site_type_result) -> DimensionScore:
    """
    Stage 10 (D1): three sub-checks — completeness (name/price/
    availability, 40%), shipping/returns terms (absorbed from the old
    F3, 20%), and identifier presence + cross-page brand consistency
    (gtin/mpn/sku/brand, 40%) — identifiers are now a weighted sub-check
    comparable to name/price completeness, not an afterthought.

    Stage 11 (T2): zero product pages sampled is scored differently
    depending on why — see _no_product_pages_score.
    """
    weight = WEIGHTS["F2"]
    product_pages = _product_pages(pages)

    if not product_pages:
        return _no_product_pages_score(
            weight, site_type_result,
            fix="Publish Product+Offer JSON-LD on product pages so agents can read name, price, availability, and identifiers directly.",
        )

    evidence = []
    completeness_weight = weight * 0.4
    shipping_weight = weight * 0.2
    identifier_weight = weight * 0.4

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
    completeness_ratio = complete_count / len(product_pages)

    shipping_pages = [p for p in pages if p.candidate.kind == "shipping_returns"]
    shipping_found = any(
        p.fetch_result.status == "fetched" and p.extracted and p.extracted.shipping_returns_text_hits
        for p in shipping_pages
    )
    evidence.append(
        "shipping/returns terms discoverable as text" if shipping_found
        else "no discoverable shipping/returns terms"
    )

    identifier_ok_count = 0
    brands_seen = set()
    for p in product_pages:
        products = p.extracted.products if p.extracted else []
        if any(prod.gtin or prod.mpn or prod.sku for prod in products):
            identifier_ok_count += 1
        for prod in products:
            if prod.brand:
                brands_seen.add(prod.brand.strip().lower())
    identifier_ratio = identifier_ok_count / len(product_pages)

    brand_consistent = len(brands_seen) <= 1
    if brands_seen and not brand_consistent:
        evidence.append(f"brand field inconsistent across sampled pages: {sorted(brands_seen)}")
        identifier_ratio *= 0.5
    elif brands_seen:
        evidence.append(f"brand field consistent across sampled pages ({next(iter(brands_seen))!r})")
    evidence.append(f"{identifier_ok_count}/{len(product_pages)} product pages expose a gtin/mpn/sku identifier")

    points = (
        completeness_weight * completeness_ratio
        + shipping_weight * (1.0 if shipping_found else 0.0)
        + identifier_weight * identifier_ratio
    )

    fix = None
    if points < weight - 0.01:
        fix = (
            'Add complete Product JSON-LD (name, offers[].price, offers[].priceCurrency, '
            'offers[].availability), a crawlable shipping/returns page, and product identifiers '
            '(gtin/mpn/sku) with a consistent brand name across every product page, e.g. '
            '{"@type":"Product","name":"...","brand":{"@type":"Brand","name":"Acme"},"gtin13":"...",'
            '"offers":{"@type":"Offer","price":"29.99","priceCurrency":"USD",'
            '"availability":"https://schema.org/InStock"}}.'
        )
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix)


def score_f3_protocol_feed_presence(pages, site_type_result) -> DimensionScore:
    """
    Stage 10 (D2): rescoped from "Transaction Rails" to Protocol & Feed
    Presence. Scored, crawl-observable checks only: /llms.txt, an MCP
    endpoint declaration (well-known path or <link>/<meta> markup),
    UCP/UIP capability markup, and agentic-commerce hints in structured
    data. Merchant Center/ACP/feed-syndication participation is not
    crawl-verifiable at all — always recorded as deferred_items (S2),
    never scored.

    Stage 11 (T3): na ONLY on a positively-typed non-commerce site —
    completely decoupled from whether PDP sampling succeeded. A
    discovery failure (commerce site, no product pages found this run)
    still runs every one of these checks against the canonical origin.

    Stage 11 (T4): llms.txt and the MCP well-known path each carry
    their own fetch status — 'not_found' is checked-and-absent (scores
    zero for that sub-check, still counts in the denominator);
    'failed' (network/timeout/SSRF-abort) is unverified and is EXCLUDED
    from the scored basis entirely, with an evidence note, rather than
    scoring as absent. UCP and the agentic-commerce hint are markup-
    derived from already-fetched pages with no fetch status of their
    own, so they stay simple present/absent checks.
    """
    weight = WEIGHTS["F3"]

    if site_type_result.site_type == site_typing.SITE_TYPE_BRAND_ONLY:
        return DimensionScore(
            score=0.0, max=weight, coverage="na",
            evidence=[f"protocol & feed presence is not applicable — {site_type_result.reason}"],
        )

    llms_txt_page = next((p for p in pages if p.candidate.kind == "llms_txt"), None)
    mcp_page = next((p for p in pages if p.candidate.kind == "mcp_well_known"), None)

    all_hints = [h for p in pages if p.extracted for h in p.extracted.agentic_protocol_hints]
    mcp_link_hint = any("mcp" in h.lower() for h in all_hints)
    ucp_hint = any("ucp" in h.lower() or "uip" in h.lower() for h in all_hints)
    agentic_hint = any(
        any(kw in h.lower() for kw in ("agentic-commerce", "agent-discount", "machine-payable"))
        for h in all_hints
    )

    # Each check tuple: (verifiable, present, evidence string).
    checks = []

    if llms_txt_page is None:
        checks.append((False, False, "could not verify /llms.txt — not attempted"))
    else:
        status = llms_txt_page.fetch_result.status
        if status == "fetched":
            present = bool(llms_txt_page.fetch_result.html and llms_txt_page.fetch_result.html.strip())
            checks.append((True, present, "/llms.txt present and non-empty" if present else "/llms.txt fetched but empty"))
        elif status == "not_found":
            checks.append((True, False, "/llms.txt not found (404)"))
        else:
            checks.append((False, False, f"could not verify /llms.txt — {status}"))

    if mcp_link_hint:
        checks.append((True, True, "MCP endpoint declaration discoverable (link/meta markup)"))
    elif mcp_page is None:
        checks.append((False, False, "could not verify MCP endpoint — not attempted; no link markup found"))
    else:
        status = mcp_page.fetch_result.status
        mcp_body_present = bool(mcp_page.fetch_result.html and mcp_page.fetch_result.html.strip())
        if status == "fetched" and mcp_body_present:
            checks.append((True, True, "MCP endpoint declaration discoverable (well-known path)"))
        elif status in ("fetched", "not_found"):
            checks.append((True, False, "no MCP endpoint declaration found (well-known path checked, absent; no link markup)"))
        else:
            checks.append((False, False, f"could not verify MCP endpoint — well-known path {status}; no link markup found"))

    checks.append((True, ucp_hint, "UCP/UIP capability markup present" if ucp_hint else "no UCP/UIP capability markup found"))
    checks.append((True, agentic_hint, "agentic-commerce hints present in structured data" if agentic_hint else "no agentic-commerce hints found in structured data"))

    verifiable_checks = [c for c in checks if c[0]]
    unverifiable_count = len(checks) - len(verifiable_checks)

    per_check = weight / len(verifiable_checks) if verifiable_checks else 0.0
    points = sum(per_check for c in verifiable_checks if c[1])
    evidence = [c[2] for c in checks]
    if unverifiable_count:
        evidence.append(
            f"{unverifiable_count} sub-check(s) excluded from scoring — network error, not counted as absent"
        )

    fix = None
    if points < weight - 0.01:
        fix = (
            "Publish /llms.txt, declare an MCP endpoint (well-known manifest or <link> markup), "
            "expose UCP/UIP capability markup, and mark agentic-commerce capabilities in structured "
            "data so agent checkout protocols can discover your store."
        )
    return DimensionScore(
        score=round(points, 1), max=weight, evidence=evidence, fix=fix,
        coverage="partial", deferred_items=list(PROTOCOL_FEED_DEFERRED_ITEMS),
    )


def score_v1_offer_legibility(pages, site_type_result) -> DimensionScore:
    weight = WEIGHTS["V1"]
    product_pages = _product_pages(pages)

    if not product_pages:
        return _no_product_pages_score(
            weight, site_type_result,
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


def score_v3_member_value(pages, site_type_result) -> DimensionScore:
    """
    Stage 11 (T3): na when no product pages were found ONLY on a
    positively-typed brand-only site (site_type_result) — a discovery
    failure (commerce signals present, PDP sampling still came up
    empty) instead gets coverage='partial' with the honest reason, via
    _no_product_pages_score.

    na unconditionally (unrelated to site typing, unchanged from Stage
    10) when product pages WERE sampled but none of them carry any
    Offer markup whatsoever — member pricing has nothing to be encoded
    on regardless of why.
    """
    weight = WEIGHTS["V3"]
    product_pages = _product_pages(pages)

    if not product_pages:
        return _no_product_pages_score(
            weight, site_type_result,
            fix="Expose member/tier pricing in structured data on product pages.",
            na_on_brand_only=True,
        )

    any_offer_markup = any(
        prod.offers for p in product_pages if p.extracted for prod in p.extracted.products
    )
    if not any_offer_markup:
        return DimensionScore(
            score=0.0, max=weight, coverage="na",
            evidence=["no Offer markup found on any sampled product page — member pricing is not applicable"],
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


def score_v4_value_rails(pages, site_type_result) -> DimensionScore:
    """
    Stage 10 (D3): three sub-checks, each 1/3 of the weight, mirroring
    the deal_cited rubric's own CONCRETE/ACTIVE/ACTIONABLE tests
    (apps/pipeline/parser/prompts.py, "DEAL CITATION RULES" — frozen per
    Stage 8 H1, read-only reference here so future edits to either stay
    in sync deliberately):
      CONCRETE   — a stated amount or discount mechanic
      ACTIVE     — a priceValidUntil that has not already passed
      ACTIONABLE — eligibility, a code, or stackability terms
    """
    weight = WEIGHTS["V4"]
    product_pages = _product_pages(pages)

    if not product_pages:
        return _no_product_pages_score(
            weight, site_type_result,
            fix="Declare discounts/bundles as Offers with priceValidUntil, eligibility, and stackability terms.",
        )

    now = datetime.now(timezone.utc)
    concrete_count = 0
    active_count = 0
    actionable_count = 0
    for p in product_pages:
        products = p.extracted.products if p.extracted else []
        has_price = any(o.price is not None for prod in products for o in prod.offers)
        has_discount_hint = any(prod.has_concrete_discount_hint for prod in products)
        if has_price or has_discount_hint:
            concrete_count += 1

        is_active = False
        for prod in products:
            for o in prod.offers:
                expires = _parse_date(o.valid_through)
                if expires is not None and expires >= now:
                    is_active = True
        if is_active:
            active_count += 1

        if any(prod.has_actionable_hint for prod in products):
            actionable_count += 1

    n = len(product_pages)
    points = weight * (concrete_count / n + active_count / n + actionable_count / n) / 3

    evidence = [
        f"{concrete_count}/{n} product pages state a concrete amount or discount mechanic",
        f"{active_count}/{n} product pages declare a currently-active validity window",
        f"{actionable_count}/{n} product pages expose eligibility/code/stackability terms",
    ]
    fix = None
    if points < weight - 0.01:
        fix = (
            'Declare offers as CONCRETE (a stated amount or mechanic), ACTIVE (a "priceValidUntil" '
            "that has not passed), and ACTIONABLE (eligibility, a code, or stackability terms an "
            "agent can read) — the same three checks used to judge whether an agent's answer cites "
            "a deal."
        )
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix)


def score_v5_offer_integrity(pages):
    """
    Returns (DimensionScore, integrity_cap_triggered).

    Stage 10 (D4): the cap is conservative — it fires only on strong,
    single-visit evidence: a was-price signal on every sampled page with
    no priceValidUntil found anywhere (an unbounded, permanent "sale"),
    or an implausible discount depth (>=70%) across every page that
    shows a was-price at all. A was-price on just some pages deducts
    points without capping — one suspicious PDP alone isn't sitewide
    evidence. Everything about whether a "was" price was ever honored
    over time is deferred (S2) — that needs repeat observation, not a
    single crawl.
    """
    weight = WEIGHTS["V5"]
    product_pages = _product_pages(pages)
    deferred_items = [dict(PRICE_HISTORY_DEFERRED_ITEM)]

    if not product_pages:
        return (
            DimensionScore(
                score=weight, max=weight, coverage="partial", deferred_items=deferred_items,
                evidence=["no product pages sampled — no dishonest pricing signal detected"],
            ),
            False,
        )

    pages_with_was_price = [p for p in product_pages if p.extracted and p.extracted.was_price_signals]
    ratio = len(pages_with_was_price) / len(product_pages)
    always_on_sale = ratio >= 1.0

    no_validity_anywhere = not any(
        o.valid_through
        for p in product_pages if p.extracted
        for prod in p.extracted.products for o in prod.offers
    )

    depths = []
    for p in pages_with_was_price:
        current_price = next(
            (o.price for prod in p.extracted.products for o in prod.offers if o.price is not None),
            None,
        )
        was = p.extracted.was_price_numeric
        if was and current_price is not None and was > 0:
            depths.append((was - current_price) / was * 100)
    implausible_depth = bool(depths) and all(d >= 70 for d in depths)

    should_cap = (always_on_sale and no_validity_anywhere) or implausible_depth

    if should_cap:
        evidence = [
            f"was-price signal present on {len(pages_with_was_price)}/{len(product_pages)} "
            "sampled product pages with no evidence of a genuine baseline price",
        ]
        cap_basis = []
        if always_on_sale and no_validity_anywhere:
            cap_basis.append(f"was-price signal on {len(pages_with_was_price)}/{len(product_pages)} sampled pages, sitewide")
            cap_basis.append("no priceValidUntil found on any sampled product page")
        if implausible_depth:
            cap_basis.append(f"discount depth averaging {round(sum(depths) / len(depths), 1)}% across pages with a was-price signal")
        for p in pages_with_was_price:
            evidence.extend(f"{p.candidate.url}: {sig}" for sig in p.extracted.was_price_signals)
        fix = (
            'Only show a "was" price when it reflects a genuine prior selling price for a '
            "limited time — a compare-at price shown on every visit, or a discount depth this "
            "steep sitewide, reads as fabricated to a price-integrity check."
        )
        return (
            DimensionScore(
                score=0.0, max=weight, evidence=evidence, fix=fix, coverage="partial",
                deferred_items=deferred_items, cap_basis=cap_basis,
            ),
            True,
        )

    if pages_with_was_price:
        evidence = [
            f"was-price signal present on {len(pages_with_was_price)}/{len(product_pages)} "
            "sampled pages — no sitewide always-on-sale or implausible-discount pattern detected",
        ]
        score = round(weight * (1 - 0.3 * ratio), 1)
        return (
            DimensionScore(score=score, max=weight, evidence=evidence, coverage="partial", deferred_items=deferred_items),
            False,
        )

    return (
        DimensionScore(
            score=weight, max=weight, coverage="partial", deferred_items=deferred_items,
            evidence=["no dishonest pricing signals detected"],
        ),
        False,
    )


# ─────────────────────────────────────────────────────────────────────────
# Stage 16: v3 crawl-derived dimensions (SCORER_VERSION "3").
#
# T1: these are NOT new crawl logic — every check above (score_f1_*
# through score_v4_*) is called unchanged and its output is rescaled
# onto the v3 registry's seen_max/weight. The v2 functions themselves
# are untouched (still used to render existing scorer_version "2" scan
# rows — rule 6, no cross-version blending, Stage 10 W6) and their
# check-level evidence/pass-fail is byte-identical before and after —
# see test_scorer.py's v3 regression tests.
#
# score_v5_offer_integrity (was-price honesty + the legacy score-
# capping behavior) is deliberately NOT wrapped here — Part 6 removes
# it from the scored set
# entirely. engine.py still calls it, but only to emit an unscored
# advisory finding (see engine.py's Stage 16 comments).
# ─────────────────────────────────────────────────────────────────────────

def _rescale_dimension_score(v2_score: DimensionScore, new_max: float) -> DimensionScore:
    """1:1 rescale of an unmodified v2 DimensionScore onto a new max —
    same evidence, fix, coverage, and deferred_items; only score/max
    move, proportionally."""
    ratio = (new_max / v2_score.max) if v2_score.max else 0.0
    return DimensionScore(
        score=round(v2_score.score * ratio, 1),
        max=new_max,
        evidence=list(v2_score.evidence),
        fix=v2_score.fix,
        coverage=v2_score.coverage,
        deferred_items=list(v2_score.deferred_items),
        cap_basis=list(v2_score.cap_basis),
    )


def _combine_coverage(*scores: DimensionScore) -> str:
    """'partial' wins over 'full' when combining two components into one
    sub-lens — an honest signal that part of the combined check
    couldn't be fully verified. Callers exclude 'na' components from
    `scores` before calling this (see score_member_value_seen)."""
    return "partial" if any(s.coverage == "partial" for s in scores) else "full"


def score_agent_access(discovery, pages) -> DimensionScore:
    """Stage 16: v2's score_f1_agent_access, rescaled onto the v3
    agent_access dimension's weight."""
    return _rescale_dimension_score(
        score_f1_agent_access(discovery, pages),
        DIMENSIONS_BY_CODE["agent_access"].weight,
    )


def score_catalog_context(pages, site_type_result) -> DimensionScore:
    """Stage 16: v2's score_f2_catalog_context, rescaled onto the v3
    catalog_context dimension's weight."""
    return _rescale_dimension_score(
        score_f2_catalog_context(pages, site_type_result),
        DIMENSIONS_BY_CODE["catalog_context"].weight,
    )


def score_protocol_feed(pages, site_type_result) -> DimensionScore:
    """Stage 16: v2's score_f3_protocol_feed_presence, rescaled onto the
    v3 protocol_feed dimension's weight."""
    return _rescale_dimension_score(
        score_f3_protocol_feed_presence(pages, site_type_result),
        DIMENSIONS_BY_CODE["protocol_feed"].weight,
    )


def score_price_truth_seen(pages, site_type_result) -> DimensionScore:
    """Stage 16 (T1): price_truth.seen (6) = v2's score_v1_offer_legibility
    (price/currency legibility checks), rescaled onto the seen sub-max."""
    return _rescale_dimension_score(
        score_v1_offer_legibility(pages, site_type_result),
        DIMENSIONS_BY_CODE["price_truth"].seen_max,
    )


def score_deal_citability_seen(pages, site_type_result) -> DimensionScore:
    """Stage 16 (T1): deal_citability.seen (4) = v2's score_v4_value_rails
    (CONCRETE/ACTIVE/ACTIONABLE, weighted equally), rescaled onto the
    seen sub-max."""
    return _rescale_dimension_score(
        score_v4_value_rails(pages, site_type_result),
        DIMENSIONS_BY_CODE["deal_citability"].seen_max,
    )


def score_member_value_seen(pages, site_type_result) -> DimensionScore:
    """
    Stage 16 (T1): member_value.seen (12) = v2's score_v2_loyalty_surface
    (program surface discoverability, unconditional) PLUS v2's
    score_v3_member_value (member/tier price encoding, conditional on
    product pages carrying Offer markup at all), combined and rescaled
    onto the seen sub-max.

    Both v2 checks run byte-identical. When member_value's own crawl
    result is 'na' (no Offer markup anywhere, or a brand-only site — the
    existing Stage 10/11 na rules), it's excluded from the combined
    raw_score/raw_max entirely (matches the existing na-exclusion
    convention — never scored as zero) and the sub-lens reduces to
    JUST loyalty-surface discoverability, rescaled onto the full 12.
    Its evidence is still surfaced (honest, not silent) even though it
    contributes no points.
    """
    new_max = DIMENSIONS_BY_CODE["member_value"].seen_max

    loyalty = score_v2_loyalty_surface(pages)
    member_price = score_v3_member_value(pages, site_type_result)

    components = [loyalty] if member_price.coverage == "na" else [loyalty, member_price]
    raw_max = sum(c.max for c in components)
    raw_score = sum(c.score for c in components)
    ratio = (new_max / raw_max) if raw_max else 0.0

    evidence = []
    deferred_items = []
    fix = None
    for c in components:
        evidence.extend(c.evidence)
        deferred_items.extend(c.deferred_items)
        fix = fix or c.fix
    if member_price.coverage == "na":
        evidence.extend(member_price.evidence)

    return DimensionScore(
        score=round(raw_score * ratio, 1),
        max=new_max,
        evidence=evidence,
        fix=fix,
        coverage=_combine_coverage(*components),
        deferred_items=deferred_items,
        cap_basis=[],
    )
