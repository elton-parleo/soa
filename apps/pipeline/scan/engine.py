"""
engine.py — public entry point for the Agent Scan.

run_scan() never raises. Every internal step (discovery, fetching,
extraction, scoring) is itself defensive, and this function wraps the
whole pipeline in a final try/except so an unanticipated bug degrades
to status='failed' with an error message instead of propagating out of
the only function callers are meant to use.

Terminal statuses: complete | blocked | failed | skipped. 'skipped' is
returned only when no input was given at all — an unknown-but-reachable
DTC store always produces a score (status='complete', however low), and
a store that actively blocks automated access produces status='blocked'
rather than an exception.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from . import scorer
from .discovery import DiscoveryResult, discover_pages
from .fetcher import FetchBudget, fetch
from .structured_data import ExtractedData, extract

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
        elif not budget.has_capacity():
            continue
        else:
            budget.consume()
            result = fetch(candidate.url, robot_parser=discovery.robot_parser)

        extracted = None
        if result.status == "fetched" and result.html:
            extracted = extract(result.html)

        pages.append(PageScanData(candidate=candidate, fetch_result=result, extracted=extracted))
    return pages


def _derive_status(discovery: DiscoveryResult, pages: list) -> str:
    if discovery.robots_fetch.status == "blocked":
        return STATUS_BLOCKED

    fetched_pages = [p for p in pages if p.fetch_result.status == "fetched"]
    if fetched_pages:
        return STATUS_COMPLETE

    blocked_pages = [p for p in pages if p.fetch_result.status == "blocked"]
    if blocked_pages:
        return STATUS_BLOCKED

    return STATUS_FAILED


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

        base_url = _normalize_input(input_url_or_domain)
        if base_url is None:
            return ScanResult(
                status=STATUS_FAILED,
                error="could not parse a usable URL/domain from input",
                started_at=started_at,
                finished_at=_now(),
            )

        budget = FetchBudget()
        discovery = discover_pages(base_url, budget)
        pages = _gather_pages(discovery, budget)

        pages_fetched = [
            {"url": p.fetch_result.url, "status": p.fetch_result.status} for p in pages
        ]
        status = _derive_status(discovery, pages)

        if status != STATUS_COMPLETE:
            return ScanResult(
                status=status,
                pages_fetched=pages_fetched,
                started_at=started_at,
                finished_at=_now(),
                error=(
                    "site blocked automated access" if status == STATUS_BLOCKED
                    else "no pages could be fetched"
                ),
            )

        dim_scores = {
            "F1": scorer.score_f1_agent_access(discovery, pages),
            "F2": scorer.score_f2_catalog_context(pages),
            "F3": scorer.score_f3_transaction_rails(pages),
            "V1": scorer.score_v1_offer_legibility(pages),
            "V2": scorer.score_v2_loyalty_surface(pages),
            "V3": scorer.score_v3_member_value(pages),
            "V4": scorer.score_v4_value_rails(pages),
        }
        v5_score, integrity_capped = scorer.score_v5_offer_integrity(pages)
        dim_scores["V5"] = v5_score

        raw_total = sum(d.score for d in dim_scores.values())
        capped_total = min(raw_total, scorer.INTEGRITY_CAP) if integrity_capped else raw_total
        total_score = int(round(capped_total))

        dimensions = {
            code: {"score": d.score, "max": d.max, "evidence": d.evidence, "fix": d.fix}
            for code, d in dim_scores.items()
        }

        return ScanResult(
            status=STATUS_COMPLETE,
            total_score=total_score,
            integrity_capped=integrity_capped,
            dimensions=dimensions,
            pages_fetched=pages_fetched,
            started_at=started_at,
            finished_at=_now(),
        )

    except Exception as e:
        log.exception(f"[scan.engine] run_scan failed for input {input_url_or_domain!r}")
        return ScanResult(
            status=STATUS_FAILED,
            error=f"unexpected error: {e}",
            started_at=started_at,
            finished_at=_now(),
        )
