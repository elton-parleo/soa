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
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from soa_shared.scan_dimensions import DIMENSIONS_BY_CODE, SCORER_VERSION

from . import scorer, site_typing
from .discovery import DiscoveryResult, discover_pages, resolve_canonical_origin
from .fetcher import FetchBudget, fetch
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


def _fetch_entry(fr) -> dict:
    """Stage 11 (F3): one pages_fetched row — every fetch the scan
    performed, including robots.txt/sitemap/well-known probes that were
    previously invisible. A4 (fetch resilience): attempts/retry_after_seen/
    bytes give the scorer (and the report) the structured facts behind
    a status, instead of re-deriving them from evidence strings."""
    return {
        "url": fr.url,
        "final_url": fr.final_url,
        "status": fr.status,
        "http_status": fr.http_status,
        "attempts": fr.attempts,
        "retry_after_seen": fr.retry_after_seen,
        "bytes": fr.bytes,
    }


def _derive_status(discovery: DiscoveryResult, pages: list) -> str:
    """
    R1 (fetch resilience, hotfix 3): the ONE run-blocked rule, evaluated
    after every fetch has already completed (R3) — no early short-
    circuit on robots.txt's own status, no separate blocked_pages
    fallback. A run is degraded-blocked ONLY IF zero sampled product
    pages fetched successfully AND the store root (homepage) also
    failed to fetch. Homepage failure alone, with product pages read
    fine, is not a run-level event at all — it's page-level evidence
    (see score_f1_agent_access), and any dimension that specifically
    needs homepage content simply has none to work with, same as any
    other unreadable page under hotfix 2's per-page rules.

    Within that "nothing readable from the store" case, one more
    distinction: an actively hostile response (rate-limited, bot-
    blocked, a real 404) means the site is there and rejected/lacks
    what we asked for — that's honestly 'blocked'. Total unreachability
    (DNS/network failure on every single attempt, including robots.txt
    and the sitemap) is a different, honest answer — 'failed' — since
    no server ever actually responded to call this "the site blocked
    us." FetchResult.http_status is only ever set when a real HTTP
    response was received, so its presence anywhere is exactly this
    signal.
    """
    product_pages = [p for p in pages if p.candidate.kind == "product"]
    homepage_page = next((p for p in pages if p.candidate.kind == "homepage"), None)
    homepage_fetched = homepage_page is not None and homepage_page.fetch_result.status == "fetched"
    any_product_page_fetched = any(p.fetch_result.status == "fetched" for p in product_pages)

    if any_product_page_fetched or homepage_fetched:
        return STATUS_COMPLETE

    responded = discovery.robots_fetch.http_status is not None or any(
        p.fetch_result.http_status is not None for p in pages
    )
    return STATUS_BLOCKED if responded else STATUS_FAILED


# R2 (fetch resilience, hotfix 3): every crawl-derived dimension code,
# paired with the soa_shared registry entry (and whether it's a seen/
# said-split True Value dimension, whose crawl-side weight is seen_max
# rather than the full weight) — used to synthesize an honest, fully-
# v4-shaped dimensions dict for a run that never reached scoring
# (BLOCKED or FAILED) so the report renders through the exact same
# pillars/NOT-MEASURABLE machinery as a normal scan, rather than an
# empty {} that public_lite.py/lite_pillars.py have no honest way to
# distinguish from "never scored under this version at all."
_DEGRADED_DIM_SPECS = (
    ("agent_access", "agent_access", False),
    ("catalog_context", "catalog_context", False),
    ("protocol_feed", "protocol_feed", False),
    ("price_truth_seen", "price_truth", True),
    ("member_value_seen", "member_value", True),
    ("deal_citability_seen", "deal_citability", True),
    ("value_protocols_seen", "value_protocols", False),
)


def _degraded_dimensions(reason: str) -> dict:
    dims = {}
    for dim_key, registry_code, is_split in _DEGRADED_DIM_SPECS:
        registry_dim = DIMENSIONS_BY_CODE[registry_code]
        weight = registry_dim.seen_max if is_split else registry_dim.weight
        dims[dim_key] = {
            "score": 0.0, "max": weight, "evidence": [reason],
            "fix": None, "fix_human": None, "coverage": "blocked",
            "deferred_items": [], "cap_basis": [],
        }
    dims["scorer_version"] = SCORER_VERSION
    dims["scan_engine_rev"] = EXTRACTION_REV
    return dims


DEGRADED_REASON_BLOCKED = (
    "the store root and every sampled product page were rate-limited or "
    "blocked this run — nothing could be measured on-site"
)
DEGRADED_REASON_FAILED = (
    "the store root and every sampled product page could not be reached "
    "this run (network error) — nothing could be measured on-site"
)


def run_scan(input_url_or_domain: str) -> ScanResult:
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

        discovery = discover_pages(canonical_origin, budget, homepage_fetch=resolution.homepage_fetch)
        pages = _gather_pages(discovery, budget)

        pages_fetched = [_fetch_entry(fr) for fr in discovery.all_fetches]
        pages_fetched.extend(_fetch_entry(p.fetch_result) for p in pages)

        status = _derive_status(discovery, pages)

        if status != STATUS_COMPLETE:
            # R2 (fetch resilience, hotfix 3): BLOCKED and FAILED both
            # get a real, fully-shaped dimensions dict (every crawl-
            # derived dimension honestly coverage='blocked') so the
            # report renders through the standard v4 pillars machinery
            # instead of a bespoke legacy fallback — total_score stays
            # None either way (R3), since nothing was actually scored.
            dimensions = {}
            if status == STATUS_BLOCKED:
                dimensions = _degraded_dimensions(DEGRADED_REASON_BLOCKED)
            elif status == STATUS_FAILED:
                dimensions = _degraded_dimensions(DEGRADED_REASON_FAILED)
            return ScanResult(
                status=status,
                dimensions=dimensions,
                pages_fetched=pages_fetched,
                started_at=started_at,
                finished_at=_now(),
                cross_domain_redirect=resolution.cross_domain_flag,
                error=(
                    "site blocked automated access" if status == STATUS_BLOCKED
                    else "no pages could be fetched"
                ),
            )

        site_type_result = site_typing.classify_site(pages, discovery)

        # Stage 16: v3 crawl-derived dimensions — the Accessibility
        # pillar in full, plus the SEEN half of each True Value
        # dimension. The SAID half needs the LITE_QUERY_COUNT-query coded/metrics data
        # this crawl-only engine never sees — that's computed at report-
        # build time instead (apps/api/app/services/lite_pillars.py) and
        # combined with these seen scores there. Dict keys use the
        # *_seen suffix for the split dimensions so a partial (seen-only)
        # result is never mistaken for a final combined dimension score.
        dim_scores = {
            "agent_access": scorer.score_agent_access(discovery, pages),
            "catalog_context": scorer.score_catalog_context(pages, site_type_result),
            "protocol_feed": scorer.score_protocol_feed(pages, site_type_result),
            "price_truth_seen": scorer.score_price_truth_seen(pages, site_type_result),
            "member_value_seen": scorer.score_member_value_seen(pages, site_type_result),
            "deal_citability_seen": scorer.score_deal_citability_seen(pages, site_type_result),
            # Stage 25 (Part 3): value_protocols is encode-only (seen half
            # only, no said half exists at all — see lite_pillars.py) and
            # reuses F3's already-fetched MCP well-known page, never a
            # second fetch. site_type_result is deliberately not passed —
            # unlike protocol_feed, this dimension is never 'na' on a
            # brand-only site (V1: absence always scores 0, it never
            # excludes the dimension).
            "value_protocols_seen": scorer.score_value_protocols(pages),
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
        dimensions["price_honesty_advisory"] = {
            "scored": False,
            "would_have_capped": v5_would_have_capped,
            "evidence": v5_result.evidence,
            "fix": v5_result.fix,
            "cap_basis": v5_result.cap_basis,
        }

        return ScanResult(
            status=STATUS_COMPLETE,
            total_score=total_score,
            integrity_capped=False,  # Part 6: the cap no longer exists under v3 — always False
            dimensions=dimensions,
            pages_fetched=pages_fetched,
            started_at=started_at,
            finished_at=_now(),
            cross_domain_redirect=resolution.cross_domain_flag,
        )

    except Exception as e:
        log.exception(f"[scan.engine] run_scan failed for input {input_url_or_domain!r}")
        return ScanResult(
            status=STATUS_FAILED,
            error=f"unexpected error: {e}",
            started_at=started_at,
            finished_at=_now(),
        )
