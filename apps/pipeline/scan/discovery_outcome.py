"""
discovery_outcome.py — classifies WHY discover_pages() ended up with the
product-page candidates it did (often zero), from the trace discovery.py
already records on every run (sitemap_sampling, all_fetches, robots_fetch)
plus the pages engine.py actually gathered. Never a second discovery
pass — pure read of what already happened.

Written for the Nike-shaped `complete`-but-zero-PDP report state: before
this module, a run like that carried discovery_trace/sitemap_sampling
(too raw for a report) but no degraded_reason and no honest sentence a
visitor could read. classify_site()/scorer.py answer "does this look
like a store"; this module answers a narrower, more mechanical question
— "what, specifically, happened when we tried to find its product
pages" — for BOTH a complete run (zero-PDP or not) and a degraded one.

Never raises (rule 4's discipline, same as every other scan/ module): a
bug in classification degrades to code="unknown" with a plain, honest
summary, never breaks the scan that's carrying it.
"""
import logging
from urllib.parse import urljoin, urlparse

from .discovery import (
    _PRODUCT_FILENAME_HINTS,
    _looks_non_catalog_filename,
    _matches_filename_hint,
)

log = logging.getLogger(__name__)

CODE_PRODUCT_PAGES_READ = "product_pages_read"
CODE_PRODUCT_PAGES_REFUSED = "product_pages_refused"
CODE_PRODUCT_PAGES_UNREADABLE = "product_pages_unreadable"
CODE_SHORT_CIRCUITED = "short_circuited"
# Walled-site runtime (this session): discovery.py now has a SECOND
# short-circuit — robots.txt served, store root and first declared
# sitemap both refused (the Warby Parker shape). It gets its own code
# rather than folding into short_circuited above, because the sentence
# a reader needs is genuinely different: "your robots.txt was fine, the
# wall is on HTML and your sitemap", not "you refused us twice at the
# door".
CODE_HOMEPAGE_AND_SITEMAP_REFUSED = "homepage_and_sitemap_refused"
# Product-candidate verification (this session): engine.py now re-kinds
# a candidate that fetched fine but carries no product markup to
# product_candidate_rejected and excludes it from _product_pages. That
# is a genuinely different outcome from "we couldn't read them" — those
# pages read fine; they just weren't product pages — and saying
# otherwise would be exactly the kind of sentence this module exists to
# stop the report making. Walmart's live run is the fixture: 50,000 real
# /ip/ URLs behind the sitemap, four candidates fetched, three of them
# served as something other than a product page.
CODE_PRODUCT_CANDIDATES_NOT_PRODUCTS = "product_candidates_not_products"
CODE_SITEMAPS_REFUSED = "sitemaps_refused"
CODE_SITEMAPS_ROBOTS_DISALLOWED = "sitemaps_robots_disallowed"
CODE_NO_SITEMAP = "no_sitemap"
CODE_PRODUCT_SITEMAP_UNRECOGNIZED = "product_sitemap_unrecognized"
CODE_SITEMAP_CHILDREN_UNPROBED = "sitemap_children_unprobed"
CODE_SITEMAPS_NON_CATALOG = "sitemaps_non_catalog"
CODE_HOMEPAGE_NO_LINKS = "homepage_no_links"
CODE_RESCUE_TIERS_SKIPPED = "rescue_tiers_skipped"
CODE_UNKNOWN = "unknown"

# A child this large is a real catalog shard whatever its filename says
# — Nike/Michael-Kors-shaped stores' PDP sitemaps routinely carry
# thousands of URLs; a help/locator/landing-page sitemap virtually never
# does.
_LARGE_CHILD_URL_COUNT = 1000

# Sitemap-file fetches that came back with a real, hostile HTTP response
# — the shared signal behind both sitemaps_refused and
# product_pages_refused.
_HOSTILE_STATUSES = (403, 429)

_EMPTY_OUTCOME = {
    "code": CODE_UNKNOWN,
    "summary": "we couldn't determine why product pages weren't found this run",
    "found_candidates": 0,
    "product_pages_attempted": 0,
    "product_pages_fetched": 0,
    "sitemaps": [],
    "child_chosen": None,
    "example_urls": [],
    "tiers": [],
    "robots_excluded": 0,
    "llm": None,
    "short_circuited": False,
    "product_candidates_rejected": 0,
}


def _rejected_candidates(pages) -> list:
    """Candidates engine.py re-kinded because they fetched fine and
    turned out not to be product pages. Matched on the kind string
    rather than imported from engine.py — discovery_outcome.py is
    imported BY engine.py, and reaching back would be a cycle."""
    return [p for p in pages if p.candidate.kind == "product_candidate_rejected"]


def _sitemap_name(url) -> str:
    try:
        path = urlparse(url).path
        return path.rsplit("/", 1)[-1] or url
    except Exception:
        return str(url)


def _skip_outcome(skip_reason: str) -> str:
    if skip_reason in ("discovery budget exhausted", "reserved for rescue tiers"):
        return "skipped"
    if skip_reason == "fetch failed (status=not_found)":
        return "not_found"
    if skip_reason == "fetch failed (status=robots_disallowed)":
        return "robots_disallowed"
    if skip_reason == "fetch failed (status=blocked)":
        return "refused"
    return "failed"


def _to_sitemap_entry(child_probed: dict) -> dict:
    url = child_probed.get("url")
    name = _sitemap_name(url)
    if "skipped" not in child_probed:
        return {
            "name": name, "outcome": "read",
            "urls": child_probed.get("url_count"), "product_urls": child_probed.get("product_count"),
            "http_status": child_probed.get("http_status"), "note": None,
        }
    reason = child_probed["skipped"]
    if reason == "no URLs found (empty or unparseable)":
        # The fetch itself succeeded (a real 2xx response) — it's the
        # sitemap's OWN content that was empty or unparseable, a
        # meaningfully different fact than "we never reached it" or "it
        # refused us." Recorded as a genuine (empty) read, not a skip —
        # this is what keeps a declared-but-empty sitemap from being
        # misread as "no sitemap at all" (no_sitemap) downstream.
        return {
            "name": name, "outcome": "read", "urls": 0, "product_urls": 0,
            "http_status": child_probed.get("http_status"), "note": reason,
        }
    return {
        "name": name, "outcome": _skip_outcome(reason),
        "urls": None, "product_urls": None,
        "http_status": child_probed.get("http_status"), "note": reason,
    }


def _sitemap_entries(discovery, base_url: str) -> list:
    """Every declared/child sitemap actually touched, in probe order —
    _fetch_and_parse_sitemap logs BOTH top-level and child fetches into
    the same children_probed list, in the order they were tried, so
    that list alone already IS this order. Declared sitemaps that were
    never reached at all (the sitemap-sub-budget ran out before the
    top-level walk got to them) get an honest "skipped" entry of their
    own too, appended at the end — they have no children_probed record
    to draw from."""
    ss = discovery.sitemap_sampling
    children_probed = ss.get("children_probed") or []
    entries = [_to_sitemap_entry(cp) for cp in children_probed]
    seen_urls = {cp.get("url") for cp in children_probed}
    for url in ss.get("declared_order") or []:
        if url in seen_urls:
            continue
        entries.append({
            "name": _sitemap_name(url), "outcome": "skipped",
            "urls": None, "product_urls": None, "http_status": None,
            "note": "not reached this run — discovery budget was spent before we got to it",
        })
    return entries


def _example_urls(discovery) -> list:
    ss = discovery.sitemap_sampling
    content_sampled = ss.get("content_sampled")
    if content_sampled and content_sampled.get("confirmed_product_urls"):
        return list(content_sampled["confirmed_product_urls"])[:3]
    children = ss.get("children_probed") or []
    child_chosen = ss.get("child_chosen")
    if child_chosen:
        for cp in children:
            if cp.get("url") == child_chosen and cp.get("example_urls"):
                return list(cp["example_urls"])[:3]
    for cp in children:
        if cp.get("example_urls"):
            return list(cp["example_urls"])[:3]
    return []


def _tier_entry(tier_attempt: dict) -> dict:
    tier = tier_attempt.get("tier")
    if "skipped" in tier_attempt:
        return {"tier": tier, "outcome": f"skipped: {tier_attempt['skipped']}"}
    return {"tier": tier, "outcome": f"found {tier_attempt.get('candidates_found', 0)}"}


def _find_unrecognized_product_child(discovery) -> dict:
    """A sitemap-INDEX CHILD (never a top-level flat sitemap — see
    below) that parsed fine but matched zero PRODUCT_URL_PATTERNS, and
    is either named like a catalog (_PRODUCT_FILENAME_HINTS) or is
    simply too large to be anything else (_LARGE_CHILD_URL_COUNT+
    URLs) — Michael Kors/Walmart's own shape before their URL
    patterns/content-sampling caught up with them. Returns the raw
    children_probed entry, or None.

    Deliberately excludes top-level declared sitemaps (a URL present in
    declared_order): those are never eligible for content-sampling
    (_select_best_sitemap_child, and therefore this whole rescue path,
    only ever runs on the CHILDREN of a <sitemapindex> — a flat,
    unindexed sitemap's own URLs are matched directly, with nothing
    left to "sample" if the pattern match comes up empty). A large,
    flat, non-catalog sitemap (Loreal: 2,530 URLs, a corporate content
    sitemap, not a product one) would otherwise be misread as an
    unrecognized PRODUCT catalog purely because of its size.
    """
    declared_order = set(discovery.sitemap_sampling.get("declared_order") or [])
    for cp in discovery.sitemap_sampling.get("children_probed") or []:
        if cp.get("is_index") is not False:
            continue
        if cp.get("url") in declared_order:
            continue
        if (cp.get("product_count") or 0) != 0:
            continue
        name = _sitemap_name(cp.get("url", "")).lower()
        is_hinted = _matches_filename_hint(name, _PRODUCT_FILENAME_HINTS)
        is_large = (cp.get("url_count") or 0) >= _LARGE_CHILD_URL_COUNT
        if is_hinted or is_large:
            return cp
    return None


def _refusal_label(statuses) -> str:
    unique = {s for s in statuses if s in _HOSTILE_STATUSES}
    if unique == {403}:
        return "403"
    if unique == {429}:
        return "429"
    return "429/403"


def _classify(discovery, pages, base_url: str, sitemap_entries: list) -> tuple:
    """Returns (code, summary) — see this module's docstring and the
    task-level spec for the full decision table. First match wins."""
    ss = discovery.sitemap_sampling
    product_pages = [p for p in pages if p.candidate.kind == "product"]
    product_pages_attempted = len(product_pages)
    product_pages_fetched = sum(1 for p in product_pages if p.fetch_result.status == "fetched")
    rejected = _rejected_candidates(pages)
    found_candidates = ss.get("candidates_found") or 0
    tiers_attempted = ss.get("tiers_attempted") or []

    if product_pages_fetched >= 1:
        # product_pages_attempted/fetched (both counted fresh from this
        # run's own `pages`), never sitemap_sampling.candidates_found —
        # that field is only ever populated by index-child SELECTION
        # (_select_best_sitemap_child) and stays 0 for every other
        # discovery_path (a flat sitemap's direct pattern match,
        # homepage/collection_hop links, platform_endpoint, llm_
        # assisted) even when it found and read real product pages —
        # "found 0, read 1" would be a straightforwardly false sentence.
        return CODE_PRODUCT_PAGES_READ, (
            f"we found {product_pages_attempted} product page(s) and read {product_pages_fetched} of them"
        )

    if product_pages_attempted >= 1:
        hostile = [p for p in product_pages if p.fetch_result.status == "blocked"]
        if hostile:
            statuses = [p.fetch_result.http_status for p in hostile if p.fetch_result.http_status]
            label = _refusal_label(statuses)
            return CODE_PRODUCT_PAGES_REFUSED, (
                f"we found {product_pages_attempted} product page(s) and asked for each one; "
                f"your site refused every request (HTTP {label})"
            )

    # Product-candidate verification: checked after a READ (top of this
    # function) and after a REFUSAL (just above) — both of those are
    # stronger, more specific facts about the run. It is checked BEFORE
    # "unreadable", because a run whose candidates mostly opened-but-
    # weren't-products is not a run that couldn't read anything, and the
    # unreadable sentence would be the wrong story about it. Walmart's
    # live run is exactly this: four /ip/ candidates, three served
    # without product markup and one a 404.
    if rejected and product_pages_fetched == 0:
        opened = len(rejected)
        return CODE_PRODUCT_CANDIDATES_NOT_PRODUCTS, (
            f"we found product-shaped URLs and opened {opened} of them, but every page we "
            "opened came back without product markup — a category or landing page, or a "
            "page served to our reader without its product details"
        )

    if product_pages_attempted >= 1:
        # "network error or timeout" is only honest when no HTTP
        # response ever came back. A 404/5xx is a real answer from a
        # real server, and calling it a network error sends a store
        # owner looking in the wrong place.
        responded = [p for p in product_pages if p.fetch_result.http_status is not None]
        if responded:
            statuses = sorted({p.fetch_result.http_status for p in responded})
            label = ", ".join(str(code) for code in statuses)
            return CODE_PRODUCT_PAGES_UNREADABLE, (
                f"we found {product_pages_attempted} product page(s) and asked for each one, "
                f"but none of them served us a page we could read (HTTP {label})"
            )
        return CODE_PRODUCT_PAGES_UNREADABLE, (
            f"we found {product_pages_attempted} product page(s) and asked for each one, "
            "but couldn't read any of them (network error or timeout, not a refusal)"
        )

    short_circuit = ss.get("short_circuit")
    if short_circuit:
        # The two short-circuits describe two different walls — keyed
        # off the reason discovery.py recorded, never inferred here.
        if short_circuit.get("reason") == "homepage_and_sitemap_refused":
            return CODE_HOMEPAGE_AND_SITEMAP_REFUSED, (
                "your robots.txt was served, but your store root and your first declared "
                "sitemap both refused our reader, so we stopped probing your catalog"
            )
        return CODE_SHORT_CIRCUITED, (
            "robots.txt and your store root both refused our reader, so we stopped without probing further"
        )

    real_entries = [e for e in sitemap_entries if e["outcome"] != "skipped" or e.get("http_status") is not None]
    statuses = [e["http_status"] for e in sitemap_entries if e.get("http_status") is not None]
    if statuses and all(s in _HOSTILE_STATUSES for s in statuses):
        label = _refusal_label(statuses)
        return CODE_SITEMAPS_REFUSED, (
            f"we found your sitemap(s), but every one refused our reader (HTTP {label})"
        )

    non_skip_entries = [e for e in sitemap_entries if e["outcome"] != "skipped" or e.get("note") != "not reached this run — discovery budget was spent before we got to it"]
    if non_skip_entries and all(e["outcome"] == "robots_disallowed" for e in non_skip_entries):
        return CODE_SITEMAPS_ROBOTS_DISALLOWED, (
            "your robots.txt disallows every declared sitemap to readers like ours, "
            "and your homepage links didn't lead to a product page"
        )

    declared = ss.get("declared_order") or []
    default_fallback = urljoin(base_url, "/sitemap.xml")
    if declared == [default_fallback]:
        matching = next((e for e in sitemap_entries if _sitemap_name(default_fallback) == e["name"]), None)
        if matching and matching["outcome"] in ("not_found", "failed"):
            return CODE_NO_SITEMAP, (
                "your site doesn't declare a sitemap, and the default /sitemap.xml location didn't have one either"
            )

    unrecognized = _find_unrecognized_product_child(discovery)
    if unrecognized is not None and not ss.get("content_sampled"):
        # unrecognized is always a genuine sitemapindex CHILD by this
        # point (_find_unrecognized_product_child excludes top-level
        # flat sitemaps entirely) — every such child that parses with
        # zero pattern density is exactly what _select_best_sitemap_
        # child's own fallback always tries content-sampling on next
        # (budget permitting), so claiming a sample was attempted is
        # honest here, unlike for a flat top-level sitemap (which is
        # never eligible for content-sampling at all).
        name = _sitemap_name(unrecognized.get("url", ""))
        url_count = unrecognized.get("url_count") or 0
        return CODE_PRODUCT_SITEMAP_UNRECOGNIZED, (
            f"we read {_sitemaps_read_count(ss)} of your sitemaps, including {name} ({url_count} URLs), "
            "but its product URLs use a shape our reader doesn't recognise, and our page sample "
            "of it found no product markup"
        )

    index_entries = discovery.sitemap_index_entries or []
    probed_urls = {cp.get("url") for cp in (ss.get("children_probed") or [])}
    unprobed = [u for u in index_entries if u not in probed_urls]
    unprobed_product_hinted = any(
        _matches_filename_hint(_sitemap_name(u).lower(), _PRODUCT_FILENAME_HINTS) for u in unprobed
    )
    probed_children = [cp for cp in (ss.get("children_probed") or []) if cp.get("is_index") is False]
    all_probed_non_catalog = bool(probed_children) and all(
        _looks_non_catalog_filename(cp.get("url", "")) for cp in probed_children
    )
    if unprobed and (unprobed_product_hinted or all_probed_non_catalog):
        return CODE_SITEMAP_CHILDREN_UNPROBED, (
            "your sitemap index declares more product-shaped sitemaps than we had budget to read this run"
        )

    # sitemap_entries (mapped), not raw children_probed — an empty-but-
    # successfully-fetched sitemap is genuinely "read" (outcome="read",
    # product_urls=0) even though _fetch_and_parse_sitemap's OWN raw
    # entry carries a "skipped" key for it (S1.d's reason-string, not a
    # verdict on whether the fetch itself succeeded — see
    # _to_sitemap_entry). Using the raw dict here would silently drop
    # this case from read_entries and miss it entirely.
    read_entries = [e for e in sitemap_entries if e["outcome"] == "read"]
    if read_entries and not any((e.get("product_urls") or 0) > 0 for e in read_entries):
        homepage_tier = next((t for t in tiers_attempted if t.get("tier") == "homepage"), None)
        homepage_found = homepage_tier.get("candidates_found", 0) if homepage_tier else 0
        rescue_ran_empty = any(
            t.get("tier") in ("platform_endpoint", "llm_assisted")
            and "skipped" not in t and t.get("candidates_found", 0) == 0
            for t in tiers_attempted
        )
        if homepage_found == 0 and rescue_ran_empty:
            return CODE_SITEMAPS_NON_CATALOG, (
                "we read your sitemaps and checked your homepage and category links, "
                "but found nothing that looked like a product catalog"
            )

    if not (ss.get("children_probed") or []):
        homepage_page = next((p for p in pages if p.candidate.kind == "homepage"), None)
        homepage_fetched = homepage_page is not None and homepage_page.fetch_result.status == "fetched"
        if homepage_fetched:
            homepage_tier = next((t for t in tiers_attempted if t.get("tier") == "homepage"), None)
            collection_tier = next((t for t in tiers_attempted if t.get("tier") == "collection_hop"), None)
            homepage_found = homepage_tier.get("candidates_found", 0) if homepage_tier else 0
            collection_found = collection_tier.get("candidates_found", 0) if collection_tier else 0
            if homepage_found == 0 and collection_found == 0:
                return CODE_HOMEPAGE_NO_LINKS, (
                    "your site doesn't declare a sitemap, and your homepage's own links "
                    "didn't lead to any product or category pages we could follow"
                )

    skipped_rescue_tiers = [
        t for t in tiers_attempted
        if t.get("tier") in ("collection_hop", "platform_endpoint", "llm_assisted") and "skipped" in t
    ]
    if skipped_rescue_tiers:
        return CODE_RESCUE_TIERS_SKIPPED, (
            "we couldn't find your product pages this run, and skipped one or more rescue "
            "options before trying them ({reasons})"
        ).format(reasons=", ".join(f"{t['tier']}: {t['skipped']}" for t in skipped_rescue_tiers))

    return CODE_UNKNOWN, "we couldn't determine why product pages weren't found this run"


def _sitemaps_read_count(sitemap_sampling: dict) -> int:
    return sum(1 for e in sitemap_sampling.get("children_probed", []) if "skipped" not in e)


def build_discovery_outcome(discovery, pages: list, base_url: str) -> dict:
    """
    The ONE place "why did/didn't discovery find product pages this
    run" is answered, in a shape a report can render directly — see
    this module's docstring for the full field list. Recorded on EVERY
    run (complete or degraded) as dimensions["discovery_outcome"],
    additive, never a scoring input. Never raises.
    """
    try:
        ss = discovery.sitemap_sampling
        product_pages = [p for p in pages if p.candidate.kind == "product"]
        product_pages_attempted = len(product_pages)
        product_pages_fetched = sum(1 for p in product_pages if p.fetch_result.status == "fetched")
        found_candidates = ss.get("candidates_found") or 0

        sitemap_entries = _sitemap_entries(discovery, base_url)
        code, summary = _classify(discovery, pages, base_url, sitemap_entries)

        llm_trace = ss.get("llm_discovery")
        llm = None
        if llm_trace:
            llm = {
                "urls_returned": llm_trace.get("urls_returned", 0),
                "urls_verified": llm_trace.get("urls_verified", 0),
            }

        return {
            "code": code,
            "summary": summary,
            "found_candidates": found_candidates,
            "product_pages_attempted": product_pages_attempted,
            "product_pages_fetched": product_pages_fetched,
            "sitemaps": sitemap_entries,
            "child_chosen": ss.get("child_chosen"),
            "example_urls": _example_urls(discovery),
            "tiers": [_tier_entry(t) for t in (ss.get("tiers_attempted") or [])],
            "robots_excluded": ss.get("robots_excluded") or 0,
            "llm": llm,
            "short_circuited": bool(ss.get("short_circuit")),
            # Product-candidate verification: how many URLs this run
            # opened that matched a product URL pattern and turned out
            # not to be product pages. 0 on almost every run.
            "product_candidates_rejected": len(_rejected_candidates(pages)),
        }
    except Exception:
        log.exception("[scan.discovery_outcome] classification failed")
        return dict(_EMPTY_OUTCOME)
