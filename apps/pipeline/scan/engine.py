"""
engine.py — public entry point for the Agent Scan.

run_scan() never raises. Every internal step (canonical-host
resolution, discovery, fetching, extraction, scoring) is itself
defensive, and this function wraps the whole pipeline in a final
try/except so an unanticipated bug degrades to status='failed' with an
error message instead of propagating out of the only function callers
are meant to use.

Terminal statuses: complete | blocked | failed | skipped. 'skipped' is
returned only when no input was given at all — an unknown-but-reachable
DTC store always produces a score (status='complete', however low), and
a store that actively blocks automated access produces status='blocked'
rather than an exception.

Stage 11 (H1/H2): the canonical origin is resolved ONCE, before
discovery ever runs — every subsequent URL discover_pages() builds uses
that one resolved origin, never a mix of apex and www.

Nike discovery fix: STATUS_COMPLETE no longer implies every crawl-
dependent dimension was actually measured. _derive_status only ever
degrades the run to blocked/failed when the store root ALSO failed to
fetch (see that function's own docstring) — a run whose homepage reads
fine but whose sampler never found a single product page (a starved,
Nike-shaped discovery run, or any commerce site discovery genuinely
couldn't crawl this time) still lands on STATUS_COMPLETE, same as
before. What changed is what that "complete" run's dimensions dict
looks like: scorer.py's commerce_discovery_failure branch (see
scorer.py's module docstring) now marks catalog_context/price_truth_
seen/deal_citability_seen coverage="blocked" instead of a scored zero,
so build_pillars_payload (apps/api/app/services/lite_pillars.py)
excludes them from the applicable-max sum and withholds the composite/
verdict (state="composite_withheld" or "unverified", never a fabricated
score) rather than computing one against data that was never sampled.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from soa_shared.degraded_dimensions import (
    DEGRADED_REASON_BLOCKED,
    DEGRADED_REASON_FAILED,
    DEGRADED_REASON_NO_PRODUCT_PAGES_TEMPLATE,
    DIMENSION_INPUT_MAP,
    build_degraded_dimensions,
)
from soa_shared.scan_dimensions import SCORER_VERSION

from . import scorer, signing, site_typing
from .agent_access_matrix import build_agent_access_matrix
from .discovery import DiscoveryResult, discover_pages, resolve_canonical_origin
from .fetcher import FetchBudget, fetch
from .brand_icon import extract_brand_icon
from .offer_feed import build_offer_feed, extract_product_image, extract_product_name
from .structured_data import EXTRACTION_REV, ExtractedData, extract

log = logging.getLogger(__name__)

STATUS_COMPLETE = "complete"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


@dataclass
class PageScanData:
    candidate: object        # discovery.PageCandidate
    fetch_result: object     # fetcher.FetchResult
    extracted: Optional[ExtractedData]


@dataclass
class ScanResult:
    status: str
    total_score: Optional[int] = None
    integrity_capped: bool = False
    dimensions: dict = field(default_factory=dict)
    pages_fetched: list = field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    cross_domain_redirect: Optional[str] = None  # Stage 11 (H3): set whenever a redirect hop stopped at a different domain
    # Part 2 (P1): the URL worker.py's fetch probe should ask ChatGPT to
    # open — first a successfully-fetched PDP, else the first ATTEMPTED
    # PDP (even if it failed), else the store root. Always a real URL
    # once discovery ran at all; None only when the scan never got that
    # far (skipped, or an unparseable input).
    fetch_probe_url: Optional[str] = None
    # N4 (not-measurable consistency stage): which rung of the ladder
    # fetch_probe_url came from — "product_page" | "store_root" — so
    # every rendered probe line can honestly name what was actually
    # opened ("your homepage" vs "your product page") instead of a raw
    # URL, and a homepage price quote is never mistaken for product-
    # page price evidence.
    fetch_probe_kind: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_input(input_url_or_domain: str) -> Optional[str]:
    value = (input_url_or_domain or "").strip()
    if not value:
        return None
    if "://" not in value:
        value = f"https://{value}"
    try:
        parsed = urlparse(value)
    except Exception:
        return None
    if not parsed.hostname:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _gather_pages(discovery: DiscoveryResult, budget: FetchBudget) -> list:
    pages = []
    for candidate in discovery.candidates:
        if candidate.kind == "homepage" and discovery.homepage_fetch is not None:
            result = discovery.homepage_fetch
        elif candidate.kind == "llms_txt" and discovery.llms_txt_fetch is not None:
            result = discovery.llms_txt_fetch
        elif candidate.kind == "mcp_well_known" and discovery.mcp_well_known_fetch is not None:
            result = discovery.mcp_well_known_fetch
        elif candidate.url in discovery.reused_product_fetches:
            # Part 3 (3b): the LLM-assisted tier already fetched-and-
            # verified this exact URL during discovery (charged to
            # discovery_budget) — reused here rather than fetched again
            # against the content budget, same reuse idea as homepage_
            # fetch/llms_txt_fetch/mcp_well_known_fetch above.
            result = discovery.reused_product_fetches[candidate.url]
        elif not budget.has_capacity():
            continue
        else:
            budget.consume()
            # Stage 11 (F2): the <100-char "blocked" heuristic only makes
            # sense for real content pages — llms_txt/mcp_well_known are
            # infrastructure probes that legitimately come back short/empty.
            check_short_body = candidate.kind in ("homepage", "product", "loyalty", "shipping_returns")
            result = fetch(candidate.url, robot_parser=discovery.robot_parser, check_short_body=check_short_body)

        extracted = None
        if result.status == "fetched" and result.html:
            extracted = extract(result.html)

        pages.append(PageScanData(candidate=candidate, fetch_result=result, extracted=extracted))
    return pages


FETCH_PROBE_KIND_PRODUCT_PAGE = "product_page"
FETCH_PROBE_KIND_STORE_ROOT = "store_root"


def _choose_fetch_probe_url(canonical_origin: str, pages: list) -> tuple:
    """Part 2 (P1), kind-aware (N4): first successfully-fetched PDP;
    else the first ATTEMPTED PDP (present in `pages` regardless of its
    fetch outcome — `pages` only ever contains candidates actually
    fetched, per _gather_pages); else the store root. Always returns a
    real (url, kind) pair — canonical_origin is a plain string by the
    time pages exist."""
    product_pages = [p for p in pages if p.candidate.kind == "product"]
    fetched = next((p for p in product_pages if p.fetch_result.status == "fetched"), None)
    if fetched:
        return fetched.candidate.url, FETCH_PROBE_KIND_PRODUCT_PAGE
    if product_pages:
        return product_pages[0].candidate.url, FETCH_PROBE_KIND_PRODUCT_PAGE
    return canonical_origin, FETCH_PROBE_KIND_STORE_ROOT


def _short_circuited(discovery: DiscoveryResult) -> bool:
    """Fetcher hardening: did discovery stop before it started because
    robots.txt and the store root both refused us (see discovery.py's
    hard_refused)? Threaded into the scorers whose evidence would
    otherwise report an absence they never actually checked for — never
    a scoring input, only a wording one."""
    try:
        return bool(discovery.sitemap_sampling.get("short_circuit"))
    except Exception:
        return False


def _compute_agent_access(discovery: DiscoveryResult, pages: list) -> tuple:
    """
    Part 1 (M1-M5): builds the Agent Access Matrix exactly once and
    scores agent_access for real with its M5 divergence evidence folded
    in. Shared by both the degraded and complete paths below — Agent
    Access is real-scored on both (S4, hotfix 5), so the matrix and its
    divergence evidence must be too. Returns (DimensionScore, matrix_list)
    — the DimensionScore so callers can fold it into the same
    applicable-sum machinery every other dimension uses; matrix_list is
    serialized additively onto dimensions["agent_access_matrix"]
    regardless of run status.
    """
    product_urls = [p.candidate.url for p in pages if p.candidate.kind == "product"]
    matrix, divergence_evidence = build_agent_access_matrix(discovery, product_urls)
    result = scorer.score_agent_access(discovery, pages, divergence_evidence=divergence_evidence)
    return result, matrix


# N1 (not-measurable plumbing consistency): per-dimension measurability
# derives from ITS OWN required inputs, not a per-run blanket.
# agent_access/value_protocols only ever read discovery-surface fetches
# (robots.txt, the MCP well-known page) — never a sampled PDP
# (value_protocols' scorer never even looks at PDPs; agent_access was
# already real-scored on a degraded run, hotfix 5 S4). requires_pdp=False
# dims are ALWAYS real-scored, complete run or degraded — table-driven
# so the split is one declared fact, not per-dimension judgment calls.
#
# protocol_feed is deliberately NOT in this set despite ALSO reading
# only discovery-surface fetches (llms.txt/MCP) in its own scorer logic
# (Stage 11 T3) — it additionally depends on site_typing.classify_site,
# which can't distinguish a genuinely brand-only site from a site that
# 403'd EVERY fetch including robots.txt/homepage (both present as zero
# commerce signals to classify_site). Real-scoring protocol_feed on a
# uniform-block run would silently misreport it as "not applicable"
# instead of "couldn't be measured" — a different, unscoped bug this
# stage doesn't touch (site_typing's own decision table is out of
# scope: "no methodology change"). Stays on the synthetic NOT MEASURABLE
# path here; only value_protocols (which never consults site typing at
# all) gets the fix.
#
# Production outage (2026-09-22): DIMENSION_INPUT_MAP itself now lives
# in soa_shared.degraded_dimensions (imported above), not here — it has
# to be reachable from apps/api/app/services/cycle_scoring.py too, for
# a legacy row that reached a terminal status with no dimensions ever
# written. See that module's own docstring for why it stays dependency-
# free rather than living in this file.


def _compute_discovery_surface_scores(discovery: DiscoveryResult, pages: list) -> tuple:
    """
    N1: the two dimensions whose required inputs are discovery-surface
    fetches only, with no site-typing dependency either (see
    soa_shared.degraded_dimensions.DIMENSION_INPUT_MAP and its comment
    on why protocol_feed is excluded) — real-scored unconditionally,
    complete run or degraded. Returns ({dim_key: DimensionScore, ...},
    agent_access_matrix).
    """
    agent_access_score, agent_access_matrix = _compute_agent_access(discovery, pages)
    scores = {
        "agent_access": agent_access_score,
        "value_protocols_seen": scorer.score_value_protocols(
            pages, short_circuited=_short_circuited(discovery),
        ),
    }
    return scores, agent_access_matrix


def _serialize_dim_score(score) -> dict:
    return {
        "score": score.score, "max": score.max, "evidence": score.evidence, "fix": score.fix,
        "fix_human": score.fix_human, "coverage": score.coverage,
        "deferred_items": score.deferred_items, "cap_basis": score.cap_basis,
    }


def _fetch_entry(fr) -> dict:
    """Stage 11 (F3): one pages_fetched row — every fetch the scan
    performed, including robots.txt/sitemap/well-known probes that were
    previously invisible. A4 (fetch resilience): attempts/retry_after_seen/
    bytes give the scorer (and the report) the structured facts behind
    a status, instead of re-deriving them from evidence strings.

    Block evidence (fetcher hardening): additive diagnostic keys —
    error is the fetcher's own reason string (it was always computed,
    it just never got serialized, so a Cloudflare block, an Akamai
    "Access Denied" page and a client-rendered app shell were
    indistinguishable after the fact), and the rest are the response
    facts fetcher.py now records at the moment of refusal. These are
    for us: cycle_scoring.build_scan_payload filters pages_fetched back
    down to its long-standing public keys before the report payload
    reaches a browser."""
    return {
        "url": fr.url,
        "final_url": fr.final_url,
        "status": fr.status,
        "http_status": fr.http_status,
        "attempts": fr.attempts,
        "retry_after_seen": fr.retry_after_seen,
        "bytes": fr.bytes,
        "error": fr.error,
        "redirect_chain": list(fr.redirect_chain or []),
        "response_headers": fr.response_headers or {},
        "set_cookie_names": list(fr.set_cookie_names or []),
        "title": fr.title,
        "body_excerpt": fr.body_excerpt,
        "edge_vendor_hint": fr.edge_vendor_hint,
        # The per-host gap robots.txt asked us to keep, when it asked for
        # one — additive, None on the overwhelming majority of rows.
        "crawl_delay_seconds": fr.crawl_delay_seconds,
    }


BLOCK_EVIDENCE_MAX_TITLES = 5
BLOCK_EVIDENCE_MAX_BODY_SIZES = 8


def _block_evidence_summary(entries) -> dict:
    """Block evidence (fetcher hardening): the run-level rollup of what
    the per-fetch evidence above adds up to — which edge vendor's
    fingerprint showed up and how often, and the distinct refusal-page
    titles and body sizes. Identical titles and byte counts across every
    URL on a run are the signature of one WAF answering everything, which
    is the question this whole record exists to answer.

    vendor_hints counts EVERY entry, not just blocked ones — knowing a
    run's successful fetches also came through Cloudflare is part of
    reading the blocked ones. Pure and never raises."""
    vendor_hints: dict = {}
    blocked_titles: list = []
    blocked_body_sizes: list = []
    try:
        for entry in entries or []:
            vendor = entry.get("edge_vendor_hint")
            if vendor:
                vendor_hints[vendor] = vendor_hints.get(vendor, 0) + 1
            if entry.get("status") != "blocked":
                continue
            title = entry.get("title")
            if title and title not in blocked_titles and len(blocked_titles) < BLOCK_EVIDENCE_MAX_TITLES:
                blocked_titles.append(title)
            size = entry.get("bytes")
            if size is not None and size not in blocked_body_sizes and len(blocked_body_sizes) < BLOCK_EVIDENCE_MAX_BODY_SIZES:
                blocked_body_sizes.append(size)
    except Exception:
        log.exception("[scan.engine] block evidence summary failed")
    return {
        "vendor_hints": vendor_hints,
        "blocked_titles": blocked_titles,
        "blocked_body_sizes": blocked_body_sizes,
    }


def _derive_status(discovery: DiscoveryResult, pages: list) -> tuple:
    """
    R1 (fetch resilience, hotfix 3), refined by S2 (sitemap sampler,
    hotfix 5): the run-blocked rule, evaluated after every fetch has
    already completed — no early short-circuit on robots.txt's own
    status, no separate blocked_pages fallback. Returns (status,
    reason); reason is None for STATUS_COMPLETE and otherwise one of
    "no_product_pages_found" | "blocked" | "unreachable" — the same
    STATUS_BLOCKED/STATUS_FAILED values as before (no new DB status,
    no migration), but the reason distinguishes WHY, since each needs
    genuinely different report wording.

    A run is degraded-blocked ONLY IF at least one product page was
    actually ATTEMPTED and none fetched successfully, AND the store
    root (homepage) also failed to fetch. Homepage failure alone, with
    product pages read fine, is not a run-level event at all — it's
    page-level evidence (see score_f1_agent_access).

    S2: if the sampler produced ZERO product-page candidates to even
    attempt, that is USUALLY a different, honest answer —
    "no_product_pages_found" — never blamed on the site (S4's exact
    concern: an all-normal-responses sampler miss is OUR limitation).
    But zero candidates can also happen BECAUSE robots.txt or the
    sitemap itself came back hostile (403/429 — the Sephora shape,
    S4) — that's still honestly "blocked", not a sampler limitation,
    even though it too means no product URL was ever found. Once ≥1
    real product-page attempt happened, the remaining "nothing
    readable" distinction applies: an actively hostile response
    (rate-limited, bot-blocked, a real 404) means the site is there
    and rejected/lacks what we asked for — "blocked". Total
    unreachability (DNS/network failure on every single attempt,
    including robots.txt and the sitemap) is "unreachable" — no
    server ever actually responded to call this "the site blocked
    us." FetchResult.http_status is only ever set when a real HTTP
    response was received, so its presence anywhere is exactly this
    signal.

    Nike discovery fix: this function's own "no_product_pages_found"
    branch above only ever fires when the HOMEPAGE ALSO never fetched —
    it does NOT cover the STATUS_COMPLETE, zero-product-pages shape
    (homepage read fine, sampler still found nothing), which is by far
    the more common starved-discovery run in practice. That shape never
    reaches this function's degraded branch at all — it returns
    STATUS_COMPLETE at the very top (any_product_page_fetched or
    homepage_fetched), same as it always has. What used to be silently
    wrong about that COMPLETE-but-unmeasured shape lived downstream, in
    scorer.py's per-dimension coverage (see that module's own docstring)
    — not here.
    """
    product_pages = [p for p in pages if p.candidate.kind == "product"]
    homepage_page = next((p for p in pages if p.candidate.kind == "homepage"), None)
    homepage_fetched = homepage_page is not None and homepage_page.fetch_result.status == "fetched"
    any_product_page_fetched = any(p.fetch_result.status == "fetched" for p in product_pages)

    if any_product_page_fetched or homepage_fetched:
        return STATUS_COMPLETE, None

    if not product_pages:
        # S2/S4: zero candidates isn't automatically "our limitation" —
        # if robots.txt or the sitemap itself came back hostile (403/429,
        # the Sephora shape), that's still honestly "the site blocked
        # us," even though it also means no product URL was ever found
        # to sample. Only when discovery genuinely came up empty despite
        # normal responses is this "no_product_pages_found" (never a
        # site-blame). discovery.all_fetches already includes robots_fetch
        # and every sitemap/child probe made.
        sampling_saw_hostile_status = any(fr.http_status in (403, 429) for fr in discovery.all_fetches)
        if sampling_saw_hostile_status:
            return STATUS_BLOCKED, "blocked"
        return STATUS_FAILED, "no_product_pages_found"

    responded = discovery.robots_fetch.http_status is not None or any(
        p.fetch_result.http_status is not None for p in pages
    )
    if responded:
        return STATUS_BLOCKED, "blocked"
    return STATUS_FAILED, "unreachable"


# R2 (fetch resilience, hotfix 3), narrowed by N1: used to synthesize an
# honest, fully-v4-shaped dimensions dict for a run that never reached
# PDP-dependent scoring (BLOCKED or FAILED) so the report renders
# through the exact same pillars/NOT-MEASURABLE machinery as a normal
# scan, rather than an empty {} that public_lite.py/lite_pillars.py
# have no honest way to distinguish from "never scored under this
# version at all."
#
# Production outage (2026-09-22): the actual dimension table and
# builder now live in soa_shared.degraded_dimensions (imported above,
# alongside the DEGRADED_REASON_* constants) — this is just a thin,
# engine.py-local convenience that pins scan_engine_rev to the real
# crawl revision this process is actually running, which only engine.py
# (not a caller synthesizing this after the fact for a run that never
# started) has any business knowing.
def _degraded_dimensions(reason: str) -> dict:
    return build_degraded_dimensions(reason, scan_engine_rev=EXTRACTION_REV)


def _sitemaps_read_count(discovery: DiscoveryResult) -> int:
    return sum(
        1 for entry in discovery.sitemap_sampling.get("children_probed", [])
        if "skipped" not in entry
    )


def _degraded_banner_facts(discovery: DiscoveryResult, pages: list, reason: str) -> dict:
    """S3: the dynamic facts the report banner needs — computed here
    since only engine.py has access to the underlying FetchResults.
    The banner's STATIC wording lives in the frontend (grep-testable);
    these are just the numbers it fills in."""
    if reason == "no_product_pages_found":
        return {"sitemaps_read": _sitemaps_read_count(discovery)}

    if reason == "blocked":
        all_relevant = [discovery.robots_fetch] + [p.fetch_result for p in pages]
        walled_statuses = {fr.http_status for fr in all_relevant if fr.http_status in (403, 429)}
        if walled_statuses == {403}:
            refusal = "403"
        elif walled_statuses == {429}:
            refusal = "429"
        elif walled_statuses:
            refusal = "mixed"
        else:
            refusal = None
        attempts_total = sum(fr.attempts or 0 for fr in all_relevant)
        robots_included = discovery.robots_fetch.http_status in (403, 429)
        return {"refusal": refusal, "attempts": attempts_total, "robots_included": robots_included}

    return {}


def _discovery_trace_facts(discovery: DiscoveryResult, pages: list) -> dict:
    """Partial-read report state (Part 3): the same underlying discovery
    record sitemap_sampling already carries, reshaped into the facts
    the report's four-step discovery trace needs. Recorded on every
    run — same "debuggability was the point" rationale as
    sitemap_sampling itself — not just degraded ones, since a
    complete-status run (homepage fetched, zero product pages) can
    still have individually blocked True Value dimensions worth
    explaining."""
    homepage_page = next((p for p in pages if p.candidate.kind == "homepage"), None)
    homepage_fetched = homepage_page is not None and homepage_page.fetch_result.status == "fetched"
    product_pages_fetched = sum(
        1 for p in pages if p.candidate.kind == "product" and p.fetch_result.status == "fetched"
    )
    robots_status = discovery.robots_fetch.http_status
    robots_ok = None if robots_status is None else robots_status not in (403, 429)
    return {
        "sitemaps_read": _sitemaps_read_count(discovery),
        "product_urls_found": discovery.sitemap_sampling.get("candidates_found") or 0,
        "tiers_attempted": [t.get("tier") for t in discovery.sitemap_sampling.get("tiers_attempted", [])],
        "robots_ok": robots_ok,
        "homepage_fetched": homepage_fetched,
        "product_pages_fetched": product_pages_fetched,
        # Fetcher hardening: additive key, nothing in the frontend reads
        # it yet. It exists so the trace is honest about WHY
        # tiers_attempted is short on a hard-refused run — discovery
        # stopped on purpose, it didn't fail to find anything.
        "short_circuited": bool(discovery.sitemap_sampling.get("short_circuit")),
    }


def run_scan(input_url_or_domain: str, api_key: Optional[str] = None) -> ScanResult:
    """
    api_key (Part 3, rescue session): optional — threaded down to
    discover_pages' LLM-assisted last-resort tier ONLY. Every other
    step of this pipeline is plain crawl logic and never touches it.
    Absence must never break discovery (3c) — the tier simply never
    fires without a key, exactly as if this parameter didn't exist.
    """
    started_at = _now()

    try:
        if not (input_url_or_domain or "").strip():
            return ScanResult(
                status=STATUS_SKIPPED,
                error="no input URL/domain provided",
                started_at=started_at,
                finished_at=_now(),
            )

        input_origin = _normalize_input(input_url_or_domain)
        if input_origin is None:
            return ScanResult(
                status=STATUS_FAILED,
                error="could not parse a usable URL/domain from input",
                started_at=started_at,
                finished_at=_now(),
            )

        budget = FetchBudget()

        # Stage 11 (H1): resolve the canonical origin ONCE, following
        # redirects — this one homepage fetch is charged against the
        # content-page budget, matching pre-Stage-11 cost accounting.
        resolution = resolve_canonical_origin(input_origin)
        budget.consume()
        canonical_origin = resolution.origin or input_origin

        discovery = discover_pages(canonical_origin, budget, homepage_fetch=resolution.homepage_fetch, api_key=api_key)
        pages = _gather_pages(discovery, budget)

        pages_fetched = [_fetch_entry(fr) for fr in discovery.all_fetches]
        pages_fetched.extend(_fetch_entry(p.fetch_result) for p in pages)

        # Part 2 (P1), kind-aware (N4): computed once, regardless of what
        # status this run lands on below — the fetch probe still has a
        # URL worth asking ChatGPT to open even on a blocked/failed run
        # (the ladder's own store-root fallback covers that case).
        fetch_probe_url, fetch_probe_kind = _choose_fetch_probe_url(canonical_origin, pages)

        status, degraded_reason = _derive_status(discovery, pages)

        if status != STATUS_COMPLETE:
            # R2 (fetch resilience, hotfix 3), refined by S2 and N1:
            # every degraded status gets a real, fully-shaped dimensions
            # dict so the report renders through the standard v4 pillars
            # machinery instead of a bespoke legacy fallback —
            # total_score stays None either way (R3), since nothing PDP-
            # dependent was actually scored. degraded_reason/degraded_
            # banner_facts and the sitemap sampling record ride along as
            # additive sibling keys (no migration) so the report can
            # render the right first-person banner (S3) and the sampling
            # decision stays debuggable regardless of outcome (S1.d).
            if degraded_reason == "no_product_pages_found":
                sitemaps_read = _sitemaps_read_count(discovery)
                dimensions = _degraded_dimensions(
                    DEGRADED_REASON_NO_PRODUCT_PAGES_TEMPLATE.format(n=sitemaps_read)
                )
            elif degraded_reason == "blocked":
                dimensions = _degraded_dimensions(DEGRADED_REASON_BLOCKED)
            else:
                dimensions = _degraded_dimensions(DEGRADED_REASON_FAILED)
            dimensions["degraded_reason"] = degraded_reason
            dimensions["degraded_banner_facts"] = _degraded_banner_facts(discovery, pages, degraded_reason)
            dimensions["sitemap_sampling"] = discovery.sitemap_sampling
            # Partial-read report state (Part 3): additive sibling key,
            # same no-migration pattern as sitemap_sampling above.
            dimensions["discovery_trace"] = _discovery_trace_facts(discovery, pages)
            # Rescue session (Part 4a): recorded regardless of outcome,
            # same rationale as sitemap_sampling above — a run that
            # still ended degraded (e.g. candidates were found but every
            # one of them failed to fetch) is exactly when knowing WHICH
            # tier produced those candidates matters most for debugging.
            dimensions["discovery_path"] = discovery.discovery_path
            # N1: agent_access/value_protocols never depend on sampled
            # PDPs (see soa_shared.degraded_dimensions.DIMENSION_INPUT_MAP)
            # — real-scored here exactly
            # like a complete run, instead of synthesized as blocked.
            # This is what makes the robots-403-itself fact (Sephora),
            # the robots-disallow-exclusion count (S1.c), and an honest
            # "no protocol profile found" 0/7 (rather than a page-
            # sampling blanket that was never true for this dimension)
            # reach a degraded report at all.
            discovery_surface_scores, agent_access_matrix = _compute_discovery_surface_scores(discovery, pages)
            for dim_key, score in discovery_surface_scores.items():
                dimensions[dim_key] = _serialize_dim_score(score)
            dimensions["agent_access_matrix"] = agent_access_matrix
            # W6: recorded on every run (mirrors sitemap_sampling/
            # agent_access_matrix's own "debuggability was the point"
            # rationale) — the one flag the report's evidence wording
            # (scorer.py's _reader_phrase) and the degraded banner
            # (public_lite.py) both key off, so they can never disagree
            # about whether this run's fetches were actually signed.
            dimensions["signing_enabled"] = signing.is_signing_enabled()
            # W2/W3: recorded unconditionally for the same reason as the
            # line above — debuggability was the point. signing_enabled
            # says THAT this run was signed; signing_kid says which key
            # did it, so a rotation is checkable from the database
            # instead of from a running container's environment. Public
            # material (it is in the served key directory); it is not put
            # on the report payload because the report has no use for it.
            dimensions["signing_kid"] = signing.key_id()
            # Block evidence (fetcher hardening): recorded unconditionally,
            # same "debuggability was the point" rationale as
            # sitemap_sampling/signing_enabled above — a degraded run is
            # exactly when "who refused us, and did the same thing refuse
            # every URL?" is the question being asked.
            dimensions["block_evidence"] = _block_evidence_summary(pages_fetched)
            return ScanResult(
                status=status,
                dimensions=dimensions,
                pages_fetched=pages_fetched,
                started_at=started_at,
                finished_at=_now(),
                cross_domain_redirect=resolution.cross_domain_flag,
                fetch_probe_url=fetch_probe_url,
                fetch_probe_kind=fetch_probe_kind,
                error=(
                    "site blocked automated access" if status == STATUS_BLOCKED
                    else "no product pages found to sample" if degraded_reason == "no_product_pages_found"
                    else "no pages could be fetched"
                ),
            )

        # Stage 16: v3 crawl-derived dimensions — the Accessibility
        # pillar in full, plus the SEEN half of each True Value
        # dimension. The SAID half needs the LITE_QUERY_COUNT-query coded/metrics data
        # this crawl-only engine never sees — that's computed at report-
        # build time instead (apps/api/app/services/lite_pillars.py) and
        # combined with these seen scores there. Dict keys use the
        # *_seen suffix for the split dimensions so a partial (seen-only)
        # result is never mistaken for a final combined dimension score.
        # Part 1 (M1-M5) / N1: the two discovery-surface dims (incl. the
        # Agent Access Matrix) come from the same helper the degraded
        # path uses — one definition of "how these two are scored," not
        # two.
        site_type_result = site_typing.classify_site(pages, discovery)
        discovery_surface_scores, agent_access_matrix = _compute_discovery_surface_scores(discovery, pages)

        dim_scores = {
            **discovery_surface_scores,
            "catalog_context": scorer.score_catalog_context(pages, site_type_result),
            "protocol_feed": scorer.score_protocol_feed(
                pages, site_type_result, short_circuited=_short_circuited(discovery),
            ),
            "price_truth_seen": scorer.score_price_truth_seen(pages, site_type_result),
            "member_value_seen": scorer.score_member_value_seen(pages, site_type_result),
            "deal_citability_seen": scorer.score_deal_citability_seen(pages, site_type_result),
        }

        # Stage 16 (Part 6): price-honesty checks are UNSCORED under v3
        # — no cap, no contribution to total_score or the dimensions
        # sum below. Still run (same crawl logic, byte-identical) and
        # recorded as an advisory finding for the fixes/evidence path.
        v5_result, v5_would_have_capped = scorer.score_v5_offer_integrity(pages)

        # Same rescale-over-applicable-dimensions pattern as v2 (A2/S3):
        # 'na' dimensions are excluded from both numerator and
        # denominator, never scored as zero. This total_score is the
        # CRAWL-ONLY portion of the v3 rubric (Accessibility + True
        # Value's seen halves) — not the public composite, which also
        # needs the Visibility pillar and True Value's said halves and
        # is assembled fresh at the report layer, never read from here.
        # B4 (fetch resilience): 'blocked' is excluded the same way 'na'
        # is — a dimension we couldn't read is not a dimension that
        # scored zero.
        applicable = {code: d for code, d in dim_scores.items() if d.coverage not in ("na", "blocked")}
        applicable_score = sum(d.score for d in applicable.values())
        applicable_max = sum(d.max for d in applicable.values())
        total_score = int(round(applicable_score / applicable_max * 100)) if applicable_max else 0

        dimensions = {
            code: {
                "score": d.score, "max": d.max, "evidence": d.evidence, "fix": d.fix,
                "fix_human": d.fix_human,
                "coverage": d.coverage, "deferred_items": d.deferred_items, "cap_basis": d.cap_basis,
            }
            for code, d in dim_scores.items()
        }
        # Stage 10 (S4) precedent, still followed: a sibling key, not a
        # per-dimension one — no migration needed (JSON column); absence
        # on older rows means scorer_version "1" is implied.
        dimensions["scorer_version"] = SCORER_VERSION
        dimensions["scan_engine_rev"] = EXTRACTION_REV
        # S1.d: recorded on every run, not just degraded ones —
        # debuggability was the whole point ("this incident was
        # invisible in logs").
        dimensions["sitemap_sampling"] = discovery.sitemap_sampling
        # Rescue session (Part 4a): see the degraded branch's identical
        # line — recorded unconditionally, same rationale.
        dimensions["discovery_path"] = discovery.discovery_path
        # Partial-read report state (Part 3): recorded unconditionally —
        # a complete-status run (homepage fetched, zero product pages)
        # can still have individually blocked True Value dimensions.
        dimensions["discovery_trace"] = _discovery_trace_facts(discovery, pages)
        # Part 1 (M4): recorded on every run, same rationale as
        # sitemap_sampling above — additive sibling key, no migration.
        dimensions["agent_access_matrix"] = agent_access_matrix
        # W6: see the degraded branch's identical line for why this is
        # recorded unconditionally.
        dimensions["signing_enabled"] = signing.is_signing_enabled()
        # W2/W3: see the degraded branch's identical line — recorded
        # unconditionally, same rationale.
        dimensions["signing_kid"] = signing.key_id()
        # Block evidence (fetcher hardening): see the degraded branch's
        # identical line — recorded unconditionally, same rationale. A
        # complete run can still have individually refused fetches worth
        # attributing.
        dimensions["block_evidence"] = _block_evidence_summary(pages_fetched)
        dimensions["price_honesty_advisory"] = {
            "scored": False,
            "would_have_capped": v5_would_have_capped,
            "evidence": v5_result.evidence,
            "fix": v5_result.fix,
            "cap_basis": v5_result.cap_basis,
        }
        # F1/F2: additive sibling keys, same no-migration pattern as
        # sitemap_sampling/agent_access_matrix above — re-serialized from
        # data this run already extracted, no new fetches. discovery_path
        # (Part 4b) lets the OfferFeed eligibility column state coverage
        # honestly when it came from a non-sitemap tier.
        dimensions["offers"] = build_offer_feed(pages, dim_scores, discovery_path=discovery.discovery_path)
        dimensions["product_image_url"] = extract_product_image(pages)
        dimensions["product_name"] = extract_product_name(pages)
        # 1a/1b: the brand's own icon, from the homepage document already
        # fetched above — no new fetch. Additive sibling key, same pattern.
        dimensions["brand_icon_url"] = extract_brand_icon(pages)

        return ScanResult(
            status=STATUS_COMPLETE,
            total_score=total_score,
            integrity_capped=False,  # Part 6: the cap no longer exists under v3 — always False
            dimensions=dimensions,
            pages_fetched=pages_fetched,
            started_at=started_at,
            finished_at=_now(),
            cross_domain_redirect=resolution.cross_domain_flag,
            fetch_probe_url=fetch_probe_url,
            fetch_probe_kind=fetch_probe_kind,
        )

    except Exception as e:
        log.exception(f"[scan.engine] run_scan failed for input {input_url_or_domain!r}")
        return ScanResult(
            status=STATUS_FAILED,
            error=f"unexpected error: {e}",
            started_at=started_at,
            finished_at=_now(),
        )
