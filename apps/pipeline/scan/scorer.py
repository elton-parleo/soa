"""
scorer.py — the 8-dimension Agent Scan rubric. Deterministic and
rule-based (no LLM calls in this stage). Each dimension function takes
the scan's collected page data and returns a DimensionScore; engine.py sums
them into ScanResult.total_score. The V5 integrity cap itself no longer
exists (Stage 16, Part 6) — score_v5_offer_integrity's output is now an
unscored advisory finding only.

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

Fetch-resilience stage (Part B): a fourth coverage value, "blocked",
covers an offer/markup-dependent check whose sampled product pages
ALL terminally failed to fetch (429/403/5xx/timeout, after fetcher.py's
retry ladder already tried) — the check has nothing to evaluate, which
is a different honest answer than either a genuine zero or "na".
Excluded from every applicable-max sum exactly like "na" (lite_pillars.py).
A page that fetched but simply had no matching markup is still a
genuine, scored zero — "blocked" only ever means "never read."
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from soa_shared.scan_dimensions import DIMENSIONS_BY_CODE

from . import site_typing
from .discovery import discovery_coverage_note
from .fetcher import USER_AGENT
from .signing import is_signing_enabled

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

# W6: ONE template, ONE conditional — every evidence line that names
# "our reader" this way reads the SAME flag (signing.is_signing_enabled,
# a single process-wide source, see that module's own docstring), so a
# run's fetches were either signed or not, never inconsistently worded
# across evidence lines within the same scan.
def _reader_phrase() -> str:
    return "our cryptographically verified reader (Web Bot Auth)" if is_signing_enabled() else "our identified reader"


@dataclass
class DimensionScore:
    score: float
    max: float
    evidence: list = field(default_factory=list)
    fix: Optional[str] = None
    # Part 5 (H1): plain-language, outcome-first rewrite of `fix` — no
    # markup, no schema vocabulary. `fix` itself stays the exact-markup
    # version and becomes Full Diagnostic deliverable material only
    # (never serialized to the free report — see public_lite.py's
    # fixes-list builder); fix_human is what the free report shows.
    fix_human: Optional[str] = None
    coverage: str = "full"  # full | partial | na | blocked
    deferred_items: list = field(default_factory=list)  # [{label, reason}]
    cap_basis: list = field(default_factory=list)  # V5 only — evidence lines that justified a cap


def _product_pages(pages):
    return [p for p in pages if p.candidate.kind == "product"]


def _no_product_pages_score(
    weight: float, site_type_result, fix: Optional[str], *,
    fix_human: Optional[str] = None, na_on_brand_only: bool = False,
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
        evidence=[site_type_result.reason], fix=fix, fix_human=fix_human,
    )


def _readable_product_pages(product_pages):
    """B1: only pages whose fetch actually succeeded feed an offer/
    markup-dependent check — a page that terminally failed after
    fetcher.py's retry ladder (429/403/5xx/timeout) has no extracted
    data at all (engine.py only extracts from a 'fetched' result), and
    must never be silently counted as 'checked, nothing found' — the
    exact incident this stage fixes. Returns (readable, unreadable);
    `product_pages` itself is untouched (still every sampled candidate,
    for denominator/evidence purposes upstream)."""
    readable = [p for p in product_pages if p.fetch_result.status == "fetched"]
    unreadable = [p for p in product_pages if p.fetch_result.status != "fetched"]
    return readable, unreadable


def _unreadable_status_detail(unreadable_pages) -> str:
    """Honest, first-person wording keyed off the actual HTTP status(es)
    seen — never a generic 'blocked' claim when we know exactly what
    happened."""
    codes = sorted({p.fetch_result.http_status for p in unreadable_pages if p.fetch_result.http_status})
    if codes == [429]:
        return "rate-limited our reader (HTTP 429)"
    if len(codes) == 1:
        return f"returned HTTP {codes[0]} to our reader"
    if codes:
        return "returned errors to our reader (" + ", ".join(f"HTTP {c}" for c in codes) + ")"
    return "could not be reached by our reader (network error or timeout)"


def _all_blocked_score(weight: float, product_pages) -> DimensionScore:
    """B1/B2: every sampled product page was unreadable — this check has
    nothing to evaluate. coverage='blocked' renders NOT MEASURABLE
    (lite_pillars.py), distinct from both a genuine zero and 'na': the
    site may well pass this check, we simply couldn't read the pages
    that would prove it, so it must never render as a failing 0."""
    n = len(product_pages)
    return DimensionScore(
        score=0.0, max=weight, coverage="blocked",
        evidence=[f"{n} of {n} product pages {_unreadable_status_detail(product_pages)} — couldn't be evaluated."],
    )


def _blocked_pages_evidence_line(total: int, unreadable_pages) -> str:
    """B2: partial fetch success — the check still scores normally over
    the pages actually read; this line makes the exclusion honest
    rather than silent."""
    n = len(unreadable_pages)
    return (
        f"{n} of {total} product pages {_unreadable_status_detail(unreadable_pages)} "
        "— excluded from this check; scored over the page(s) actually read."
    )


def _pages_with_only_readable_products(pages, readable_product_pages):
    """Rebuilds a pages list for a pass-through call into one of the
    frozen v2 functions: every non-product page is kept untouched, and
    product-kind entries are restricted to the ones that actually
    fetched — so the v2 function underneath never sees an unreadable
    product page and silently treats it as 'checked, nothing found'.
    A no-op (returns `pages` itself) when nothing was unreadable, which
    is what keeps the all-fetched case byte-identical to before this
    stage."""
    readable_ids = {id(p) for p in readable_product_pages}
    return [p for p in pages if p.candidate.kind != "product" or id(p) in readable_ids]


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


def score_f1_agent_access(discovery, pages, divergence_evidence=()) -> DimensionScore:
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
                if not discovery.robot_parser.can_fetch(USER_AGENT, u)
            ]
        if not disallowed:
            points += weight * 0.4
            evidence.append("robots.txt allows product paths")
        else:
            evidence.append(f"robots.txt disallows: {disallowed}")
    else:
        # S4 (sitemap sampler, hotfix 5): refusing robots.txt itself to
        # an identified reader is its own notable, factual, first-
        # person observation — not just a generic "not fetchable."
        if discovery.robots_fetch.http_status == 403:
            evidence.append(f"robots.txt itself refused {_reader_phrase()} (HTTP 403) — a notable accessibility signal on its own")
        else:
            evidence.append(f"robots.txt not fetchable (status={discovery.robots_fetch.status})")

    # S1.c (sitemap sampler, hotfix 5): candidate product URLs excluded
    # from sampling because robots.txt disallows them for our reader —
    # its own honest finding, counted before the sample was even taken,
    # never conflated with "rate-limited" (a fetch-time signal) or
    # silently dropped.
    robots_excluded = discovery.sitemap_sampling.get("robots_excluded", 0)
    if robots_excluded:
        evidence.append(f"robots.txt disallows {robots_excluded} candidate product page(s) to our reader")

    # M5 (Agent Access Matrix, Part 1): a named agent's own robots.txt
    # group disagreeing with the general '*' group — "blocking 2-4
    # crawlers without knowing" — is a receipt-backed finding on its
    # own. Computed by agent_access_matrix.py and passed in by the
    # caller (engine.py, which also serializes the full matrix onto
    # dimensions["agent_access_matrix"]) rather than recomputed here, so
    # the matrix is built exactly once per scan. No scoring impact —
    # evidence only.
    evidence.extend(divergence_evidence)

    blocked_pages = [p for p in pages if p.fetch_result.status == "blocked"]
    if not blocked_pages:
        points += weight * 0.2
        evidence.append("no bot-blocking encountered on sampled pages")
    else:
        evidence.append(f"{len(blocked_pages)} page(s) returned bot-blocked responses")

    # B5: a 429-hostile edge is itself a real accessibility signal —
    # named honestly here without changing the score off it. Our UA is
    # not necessarily the UA an agent's own browsing tool sends, so this
    # stays a first-person observation about our reader, not a claim
    # about how agents generally fare against this site.
    rate_limited_pages = [p for p in pages if p.fetch_result.http_status == 429]
    if rate_limited_pages:
        evidence.append(
            f"{len(rate_limited_pages)} page request(s) rate-limited (HTTP 429) — a bot-hostile edge"
        )

    # R1 (fetch resilience, hotfix 3): a homepage that specifically
    # failed to fetch, on a run that still completed (product pages
    # read fine), is page-level evidence — not a run-level event
    # (_derive_status no longer degrades the whole run over this).
    # Named honestly here, without changing the score off it.
    homepage_page = next((p for p in pages if p.candidate.kind == "homepage"), None)
    if homepage_page and homepage_page.fetch_result.status != "fetched":
        fr = homepage_page.fetch_result
        attempts_note = f"; {fr.attempts} attempt{'s' if fr.attempts != 1 else ''}" if fr.attempts else ""
        if fr.http_status == 429:
            evidence.append(f"store root rate-limited our reader (HTTP 429{attempts_note}) — product pages read successfully")
        elif fr.http_status:
            evidence.append(f"store root returned HTTP {fr.http_status} to our reader{attempts_note} — product pages read successfully")
        else:
            evidence.append("store root could not be reached by our reader (network error) — product pages read successfully")

    if discovery.sitemap_urls:
        points += weight * 0.1
        evidence.append(f"sitemap present ({len(discovery.sitemap_urls)} URLs)")
    else:
        evidence.append("no sitemap found")

    # Rescue session (Part 4c): honest, no-score-impact evidence for
    # whichever run this run's product pages actually came from —
    # discovery.py's DISCOVERY_PATH_COVERAGE_NOTE registry is the one
    # place this wording lives (offer_feed.py's eligibility column
    # draws from the same registry, never a second literal copy).
    if discovery.discovery_path not in ("sitemap", "none"):
        note = discovery_coverage_note(discovery.discovery_path) or discovery.discovery_path
        evidence.append(
            f"{_reader_phrase()} couldn't find product pages through your declared sitemaps — {note}"
        )

    fix = None
    fix_human = None
    if points < weight - 0.01:
        fix = (
            "Ensure robots.txt allows crawler access to product pages and "
            "publish a sitemap.xml with <loc> entries for every product."
        )
        fix_human = "Make sure your site allows AI shopping agents to crawl your product pages, and publish a sitemap so they can find them."
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix, fix_human=fix_human)


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
            fix_human="Add complete structured product data to your product pages so agents can read what you sell.",
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
    fix_human = None
    if points < weight - 0.01:
        fix = (
            'Add complete Product JSON-LD (name, offers[].price, offers[].priceCurrency, '
            'offers[].availability), a crawlable shipping/returns page, and product identifiers '
            '(gtin/mpn/sku) with a consistent brand name across every product page, e.g. '
            '{"@type":"Product","name":"...","brand":{"@type":"Brand","name":"Acme"},"gtin13":"...",'
            '"offers":{"@type":"Offer","price":"29.99","priceCurrency":"USD",'
            '"availability":"https://schema.org/InStock"}}.'
        )
        fix_human = "Add complete structured product data to your product pages so agents can read what you sell."
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix, fix_human=fix_human)


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
    fix_human = None
    if points < weight - 0.01:
        fix = (
            "Publish /llms.txt, declare an MCP endpoint (well-known manifest or <link> markup), "
            "expose UCP/UIP capability markup, and mark agentic-commerce capabilities in structured "
            "data so agent checkout protocols can discover your store."
        )
        fix_human = "Publish the files that let AI agents and checkout protocols discover and interact with your store directly."
    return DimensionScore(
        score=round(points, 1), max=weight, evidence=evidence, fix=fix, fix_human=fix_human,
        coverage="partial", deferred_items=list(PROTOCOL_FEED_DEFERRED_ITEMS),
    )


def score_v1_offer_legibility(pages, site_type_result) -> DimensionScore:
    weight = WEIGHTS["V1"]
    product_pages = _product_pages(pages)

    if not product_pages:
        return _no_product_pages_score(
            weight, site_type_result,
            fix="Publish machine-readable prices with declared currency on product pages.",
            fix_human="Show your prices in a format agents can read directly from the page, not just as text or an image.",
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
    fix_human = None
    if points < weight - 0.01:
        fix = (
            'Expose price and priceCurrency in Offer JSON-LD, e.g. '
            '"offers": {"@type": "Offer", "price": "29.99", "priceCurrency": "USD"} '
            '— not just in an image or JS-rendered banner.'
        )
        fix_human = "Show your prices in a format agents can read directly from the page, not just as text or an image."
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix, fix_human=fix_human)


def score_v2_loyalty_surface(pages) -> DimensionScore:
    weight = WEIGHTS["V2"]
    loyalty_pages = [p for p in pages if p.candidate.kind == "loyalty"]

    if not loyalty_pages:
        return DimensionScore(
            score=0.0, max=weight, evidence=["no loyalty/rewards page found in nav/footer"],
            fix="Add a discoverable loyalty/rewards page linked from the nav or footer (e.g. link text containing 'Rewards' or 'Loyalty').",
            fix_human="Publish a rewards page agents can find from your menu or footer.",
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
    fix_human = None
    if points < weight - 0.01:
        fix = (
            "Publish loyalty program terms (tiers, points, benefits) as crawlable text or "
            "structured data on the rewards page, not behind login/JS."
        )
        fix_human = "Describe your loyalty program's tiers, points, and perks in plain text agents can read, not hidden behind login or JavaScript."
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix, fix_human=fix_human)


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
            fix_human="Attach your member price to each product's listing data, not just in marketing copy.",
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
    fix_human = None
    if ratio < 0.99:
        fix = (
            'Add member pricing as structured data, not just marketing copy — e.g. a second '
            'Offer with "eligibleCustomerType": "https://schema.org/LoyaltyProgramMember" or a '
            "memberPrice field."
        )
        fix_human = "Attach your member price to each product's listing data, not just in marketing copy."
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix, fix_human=fix_human)


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
            fix_human="Make your current deals and bundles readable to agents, with clear terms and an end date.",
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
    fix_human = None
    if points < weight - 0.01:
        fix = (
            'Declare offers as CONCRETE (a stated amount or mechanic), ACTIVE (a "priceValidUntil" '
            "that has not passed), and ACTIONABLE (eligibility, a code, or stackability terms an "
            "agent can read) — the same three checks used to judge whether an agent's answer cites "
            "a deal."
        )
        fix_human = "Make your current deals and bundles readable to agents, with clear terms and an end date."
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix, fix_human=fix_human)


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
        fix_human = "Only advertise a discount when it reflects a real, time-limited price drop — a permanent \"was\" price reads as dishonest to agents checking value."
        return (
            DimensionScore(
                score=0.0, max=weight, evidence=evidence, fix=fix, fix_human=fix_human, coverage="partial",
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
    same evidence, fix, fix_human, coverage, and deferred_items; only
    score/max move, proportionally."""
    ratio = (new_max / v2_score.max) if v2_score.max else 0.0
    return DimensionScore(
        score=round(v2_score.score * ratio, 1),
        max=new_max,
        evidence=list(v2_score.evidence),
        fix=v2_score.fix,
        fix_human=v2_score.fix_human,
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


def score_agent_access(discovery, pages, divergence_evidence=()) -> DimensionScore:
    """Stage 16: v2's score_f1_agent_access, rescaled onto the v3
    agent_access dimension's weight. divergence_evidence: see M5 in
    score_f1_agent_access — threaded through unchanged."""
    return _rescale_dimension_score(
        score_f1_agent_access(discovery, pages, divergence_evidence=divergence_evidence),
        DIMENSIONS_BY_CODE["agent_access"].weight,
    )


def score_catalog_context(pages, site_type_result) -> DimensionScore:
    """Stage 16: v2's score_f2_catalog_context, rescaled onto the v3
    catalog_context dimension's weight. B1/B2 (fetch resilience): a
    product page that terminally failed to fetch is excluded before the
    frozen v2 check ever sees it (all-unreadable short-circuits to
    coverage='blocked' without calling v2 at all; partial exclusion
    passes v2 a filtered pages list) — see _readable_product_pages."""
    weight = DIMENSIONS_BY_CODE["catalog_context"].weight
    product_pages = _product_pages(pages)
    readable_pages, unreadable_pages = _readable_product_pages(product_pages)

    if product_pages and not readable_pages:
        return _all_blocked_score(weight, product_pages)

    scoped_pages = _pages_with_only_readable_products(pages, readable_pages) if unreadable_pages else pages
    result = _rescale_dimension_score(score_f2_catalog_context(scoped_pages, site_type_result), weight)
    if unreadable_pages:
        result.evidence.append(_blocked_pages_evidence_line(len(product_pages), unreadable_pages))
    return result


def score_protocol_feed(pages, site_type_result) -> DimensionScore:
    """Stage 16: v2's score_f3_protocol_feed_presence, rescaled onto the
    v3 protocol_feed dimension's weight."""
    return _rescale_dimension_score(
        score_f3_protocol_feed_presence(pages, site_type_result),
        DIMENSIONS_BY_CODE["protocol_feed"].weight,
    )


def _price_consistency_mismatch(page) -> bool:
    """
    Stage 25 (Part 2, P1): conservative-by-construction price-consistency
    check — flags a product page only when we're confident its structured
    Offer price disagrees with the price the page's own visible text
    shows. Four guards keep this from ever false-flagging an honest page:
      1. skip unless at least one structured Offer price exists to compare
      2. skip unless the page has EXACTLY one distinct visible price —
         zero (no-text-price) or more than one (variant-priced pages,
         where different sizes/colors legitimately price differently)
         are both too ambiguous to call
      3. skip if a was-price/strikethrough signal is present (a sale-pair
         page shows two prices by design; we don't know which the
         structured price should match)
      4. skip differences within a small rounding/formatting tolerance
    A page counts as mismatched only if ALL of its structured offer
    prices disagree with the single visible price — if any one variant's
    price matches, that's a legitimate variant selection, not dishonesty.
    A confident mismatch degrades that page to the same state as having
    no machine-readable price at all — never a separate, harsher penalty
    (Part 0 clarification)."""
    if not page.extracted:
        return False
    structured_prices = [
        o.price for prod in page.extracted.products for o in prod.offers
        if o.price is not None
    ]
    if not structured_prices:
        return False
    visible = page.extracted.visible_prices
    if len(visible) != 1:
        return False
    if page.extracted.was_price_signals:
        return False
    visible_price = visible[0]
    tolerance = max(0.02, 0.01 * visible_price)
    return all(abs(sp - visible_price) > tolerance for sp in structured_prices)


def score_price_truth_seen(pages, site_type_result) -> DimensionScore:
    """
    Stage 25 (Part 2, P1): the v4 price_truth.seen check. Built directly
    against price_truth's own seen_max rather than rescaling v2's
    score_v1_offer_legibility (Stage 16's approach) — the price-
    consistency guard below needs to affect only the price component, not
    currency legibility, and v1/v2 stay byte-identical/frozen for old scan
    rows (rule 6, no cross-version blending). Same 60/40 price/currency
    weighting v1 used.
    """
    weight = DIMENSIONS_BY_CODE["price_truth"].seen_max
    product_pages = _product_pages(pages)

    if not product_pages:
        return _no_product_pages_score(
            weight, site_type_result,
            fix="Publish machine-readable prices with declared currency on product pages.",
            fix_human="Show your prices in a format agents can read directly from the page, not just as text or an image.",
        )

    readable_pages, unreadable_pages = _readable_product_pages(product_pages)
    if not readable_pages:
        return _all_blocked_score(weight, product_pages)

    with_currency = [
        p for p in readable_pages
        if p.extracted and any(o.price_currency for prod in p.extracted.products for o in prod.offers)
    ]

    with_price = []
    mismatched_pages = []
    login_gated_pages = []
    for p in readable_pages:
        has_price = p.extracted and any(
            o.price is not None for prod in p.extracted.products for o in prod.offers
        )
        if not has_price:
            # Stage 25 (Part 2, P3): evidence-only — a page whose price
            # is behind a login wall still scores exactly like any other
            # page with no crawlable price (no scoring change); this only
            # makes the evidence honest about WHY, instead of silently
            # implying no price exists on the site at all.
            if p.extracted and p.extracted.login_gated_price_text_hits:
                login_gated_pages.append(p)
            continue
        if _price_consistency_mismatch(p):
            mismatched_pages.append(p)
            continue
        with_price.append(p)

    price_ratio = len(with_price) / len(readable_pages)
    currency_ratio = len(with_currency) / len(readable_pages)
    points = weight * 0.6 * price_ratio + weight * 0.4 * currency_ratio

    evidence = [
        f"{len(with_price)}/{len(readable_pages)} product pages expose a machine-readable price consistent with the page's own text",
        f"{len(with_currency)}/{len(readable_pages)} product pages declare priceCurrency",
    ]
    if not with_price and not mismatched_pages:
        # F5: exact about what was and wasn't found, rather than leaving
        # a bare 0/N ratio to imply "nothing here at all" when a social-
        # preview card exists but isn't what agents actually parse.
        # Excludes the mismatched-price case deliberately — there,
        # schema.org markup DOES exist (it just disagrees with the page's
        # own text), so "no ... markup" would be false; that case already
        # gets its own evidence line below.
        og_meta_pages = [p for p in readable_pages if p.extracted and p.extracted.og_price_meta_present]
        if og_meta_pages:
            evidence.append(
                "social-preview (OG) price metadata found — not the schema.org offers agents parse"
            )
        else:
            evidence.append("no schema.org Product/Offer price markup")
    if mismatched_pages:
        evidence.append(
            f"{len(mismatched_pages)} product page(s) show a structured price that disagrees with the page's own visible price text"
        )
    if login_gated_pages:
        evidence.append(
            f"{len(login_gated_pages)} product page(s) show a login-gated price rather than no price at all"
        )
    if unreadable_pages:
        evidence.append(_blocked_pages_evidence_line(len(product_pages), unreadable_pages))

    fix = None
    fix_human = None
    if points < weight - 0.01:
        fix = (
            'Expose price and priceCurrency in Offer JSON-LD, e.g. '
            '"offers": {"@type": "Offer", "price": "29.99", "priceCurrency": "USD"} '
            '— not just in an image or JS-rendered banner — and make sure it matches the price shown on the page.'
        )
        fix_human = "Show your prices in a format agents can read directly from the page, and make sure it matches what shoppers actually see."
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix, fix_human=fix_human)


def score_deal_citability_seen(pages, site_type_result) -> DimensionScore:
    """Stage 16 (T1): deal_citability.seen (4) = v2's score_v4_value_rails
    (CONCRETE/ACTIVE/ACTIONABLE, weighted equally), rescaled onto the
    seen sub-max. B1/B2 (fetch resilience): same unreadable-product-page
    exclusion as score_catalog_context/score_price_truth_seen — see
    _readable_product_pages."""
    weight = DIMENSIONS_BY_CODE["deal_citability"].seen_max
    product_pages = _product_pages(pages)
    readable_pages, unreadable_pages = _readable_product_pages(product_pages)

    if product_pages and not readable_pages:
        return _all_blocked_score(weight, product_pages)

    scoped_pages = _pages_with_only_readable_products(pages, readable_pages) if unreadable_pages else pages
    result = _rescale_dimension_score(score_v4_value_rails(scoped_pages, site_type_result), weight)
    if unreadable_pages:
        result.evidence.append(_blocked_pages_evidence_line(len(product_pages), unreadable_pages))
    # Stage 25 (Part 2, P3): evidence-only — a deal gated behind an
    # email/signup popup still scores exactly like any other page with no
    # crawlable deal (no scoring change, score/max untouched above); this
    # only makes the evidence honest about WHY nothing was found.
    gated_pages = [
        p for p in readable_pages
        if p.extracted and p.extracted.email_gated_deal_text_hits
    ]
    if gated_pages:
        result.evidence.append(
            f"{len(gated_pages)} product page(s) show a deal gated behind an email/signup popup rather than shown outright"
        )
    return result


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

    B1/B2 (fetch resilience): 'blocked' (every sampled product page
    terminally failed to fetch) is excluded from raw_score/raw_max the
    exact same way 'na' already is — rescaled exactly like the existing
    member-value N/A path, per the stage spec. Loyalty-surface
    discoverability doesn't depend on product pages at all, so it's
    unaffected either way.
    """
    new_max = DIMENSIONS_BY_CODE["member_value"].seen_max

    loyalty = score_v2_loyalty_surface(pages)

    product_pages = _product_pages(pages)
    readable_pages, unreadable_pages = _readable_product_pages(product_pages)
    if product_pages and not readable_pages:
        member_price = _all_blocked_score(WEIGHTS["V3"], product_pages)
    else:
        scoped_pages = _pages_with_only_readable_products(pages, readable_pages) if unreadable_pages else pages
        member_price = score_v3_member_value(scoped_pages, site_type_result)
        if unreadable_pages:
            member_price.evidence.append(_blocked_pages_evidence_line(len(product_pages), unreadable_pages))

    excluded = member_price.coverage in ("na", "blocked")
    components = [loyalty] if excluded else [loyalty, member_price]
    raw_max = sum(c.max for c in components)
    raw_score = sum(c.score for c in components)
    ratio = (new_max / raw_max) if raw_max else 0.0

    evidence = []
    deferred_items = []
    fix = None
    fix_human = None
    for c in components:
        evidence.extend(c.evidence)
        deferred_items.extend(c.deferred_items)
        fix = fix or c.fix
        fix_human = fix_human or c.fix_human
    if excluded:
        evidence.extend(member_price.evidence)

    return DimensionScore(
        score=round(raw_score * ratio, 1),
        max=new_max,
        evidence=evidence,
        fix=fix,
        fix_human=fix_human,
        coverage=_combine_coverage(*components),
        deferred_items=deferred_items,
        cap_basis=[],
    )


# ─── Value Protocols (Stage 25, Part 3, V1-V4) ───────────────────────────
#
# V1: reuses F3's already-fetched MCP well-known page (score_protocol_feed
# above discovers/fetches it via discovery.py's candidate list) — never a
# second fetch. Absent or unparseable manifest scores 0, "no protocol
# profile found" — never-throw, and never 'na' (unlike protocol_feed's
# brand-only na rule): an agent-checkout protocol declaration either
# exists or it doesn't, on every site type, so this dimension always
# scores rather than excluding itself (see lite_pillars.py's Stage 25
# comment on why value_protocols has no member_value-style na branch).
#
# V2: no real public UCP/MCP capability-list schema exists yet (Part 0's
# explicit call) — the manifest shape below is INVENTED, documented here
# as the one place this scorer's expectations live, not derived from any
# external spec:
#   {
#     "capabilities": ["dev.ucp.shopping.discount", "dev.ucp.shopping.loyalty", "dev.acp.promotions"],
#     "specVersion": "2025-01"
#   }
# "capabilities" is a flat list of exact namespaced strings, matched
# EXACTLY (V2's "conservative exact-namespace match") — never by prefix
# or substring, so a differently-shaped or future-versioned capability
# string never silently counts as today's.
#
# V4: "version currency & schema integrity" is scored from the manifest
# content already in hand — no new network call. An earlier design
# considered a live HEAD request against a declared spec URL, but that
# URL would come from crawled (store-controlled) content, and adding a
# second unaudited network path for a single point isn't worth the SSRF
# surface; every fetch in this codebase goes through fetcher.py's
# guarded, redirect-validated fetch() specifically, and a bespoke HEAD
# call would either duplicate that guard or bypass it, undoing rule 5.
#
# Wording discipline: every evidence/fix string says a store "declares" a
# capability, never that it "supports" one — this dimension scores what a
# manifest declares, not verified live checkout behavior (grep-tested,
# see test_value_protocols.py's wording test).
UCP_DISCOUNT_CAPABILITY = "dev.ucp.shopping.discount"
UCP_LOYALTY_CAPABILITY = "dev.ucp.shopping.loyalty"
ACP_PROMOTIONS_CAPABILITY = "dev.acp.promotions"
CURRENT_SPEC_VERSIONS = {"2025-01"}

VALUE_PROTOCOLS_POINTS = {
    "ucp_discount": 3,
    "loyalty_extension": 2,
    "acp_promotions": 1,
    "version_schema": 1,
}


def _parse_protocol_manifest(mcp_page) -> Optional[dict]:
    """Never raises: a missing page, an unfetched status, an empty body,
    or unparseable/non-object JSON all return None — the caller treats
    every one of these identically to "no protocol profile found"."""
    if mcp_page is None or mcp_page.fetch_result.status != "fetched":
        return None
    html = mcp_page.fetch_result.html
    if not html or not html.strip():
        return None
    try:
        manifest = json.loads(html)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def score_value_protocols(pages) -> DimensionScore:
    """
    Stage 25 (Part 3, V1-V4): value_protocols.seen — whether a store
    DECLARES agent-checkout protocol capabilities. Encode-only: there is
    no said half (an agent's answer has no way to state whether a store
    "declares" a checkout protocol), so unlike price_truth/member_value/
    deal_citability there's nothing here corresponding to a said sub-lens
    — see lite_pillars.py for how the seen-only result is combined into
    True Value.
    """
    weight = DIMENSIONS_BY_CODE["value_protocols"].weight
    mcp_page = next((p for p in pages if p.candidate.kind == "mcp_well_known"), None)
    manifest = _parse_protocol_manifest(mcp_page)

    if manifest is None:
        return DimensionScore(score=0.0, max=weight, evidence=["no protocol profile found"])

    capabilities = manifest.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, list) else []

    has_ucp_discount = UCP_DISCOUNT_CAPABILITY in capabilities
    has_loyalty = UCP_LOYALTY_CAPABILITY in capabilities
    has_acp_promotions = ACP_PROMOTIONS_CAPABILITY in capabilities

    spec_version = manifest.get("specVersion")
    schema_valid_and_current = isinstance(spec_version, str) and spec_version in CURRENT_SPEC_VERSIONS

    points = 0.0
    evidence = []

    if has_ucp_discount:
        points += VALUE_PROTOCOLS_POINTS["ucp_discount"]
        evidence.append(f"declares a UCP shopping-discount capability ({UCP_DISCOUNT_CAPABILITY!r})")
    else:
        evidence.append("does not declare a UCP shopping-discount capability")

    if has_loyalty:
        points += VALUE_PROTOCOLS_POINTS["loyalty_extension"]
        evidence.append(f"declares a loyalty/member protocol extension ({UCP_LOYALTY_CAPABILITY!r})")
    else:
        evidence.append("does not declare a loyalty/member protocol extension")

    if has_acp_promotions:
        points += VALUE_PROTOCOLS_POINTS["acp_promotions"]
        evidence.append(f"declares an ACP promotions capability ({ACP_PROMOTIONS_CAPABILITY!r})")
    else:
        evidence.append("does not declare an ACP promotions capability")

    if schema_valid_and_current:
        points += VALUE_PROTOCOLS_POINTS["version_schema"]
        evidence.append(f"declared protocol manifest version is current ({spec_version!r})")
    else:
        evidence.append("declared protocol manifest version is missing, unrecognized, or out of date")

    fix = None
    fix_human = None
    if points < weight - 0.01:
        fix = (
            "Declare agent-checkout protocol capabilities in your MCP well-known manifest, e.g. "
            f'"capabilities": ["{UCP_DISCOUNT_CAPABILITY}", "{UCP_LOYALTY_CAPABILITY}", "{ACP_PROMOTIONS_CAPABILITY}"], '
            "with a current specVersion."
        )
        fix_human = (
            "Declare which agent-checkout capabilities your store offers — discounts, member pricing, "
            "promotions — in your protocol manifest, so agents can see what's declared before checkout."
        )
    return DimensionScore(score=round(points, 1), max=weight, evidence=evidence, fix=fix, fix_human=fix_human)
