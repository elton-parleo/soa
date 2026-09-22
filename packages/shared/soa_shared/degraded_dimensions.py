"""
degraded_dimensions.py — the ONE place a fully-v4-shaped, honest
"nothing was measured on-site" dimensions dict is built for a scan row
that never reached (or never finished) real crawl scoring: a degraded
(blocked/failed) run, a run whose orchestration raised before
scan.engine.run_scan() even started, a watchdog-timed-out row, or (the
apps/api side) an old row that reached a terminal status with no
dimensions at all.

Dependency-free ON PURPOSE, and living in soa_shared rather than
apps/pipeline/scan/: apps/pipeline/scan/engine.py needs this at scan
time, and apps/api/app/services/cycle_scoring.py needs the exact same
shape at report-render time for rows that never got it written — two
separate deployables (apps/pipeline on Railway, apps/api on Vercel)
with no shared runtime import path between them (see README's "cp -r
packages/shared/soa_shared" deploy convention — each app carries its
own copy of this package), but both already depend on soa_shared.
Importing anything from apps/pipeline's scan/ package here would make
this module — and therefore apps/api — depend on apps/pipeline's own
fetcher/discovery/signing import chain, exactly the chain whose own
import-time bug (production outage, 2026-09-22 — see scan/signing.py's
module docstring) this module exists partly to render honestly even
when that chain itself is what failed. Keep it to this file's own
sibling, scan_dimensions.py, only.
"""
from typing import Optional

from .scan_dimensions import DIMENSIONS_BY_CODE, SCORER_VERSION

# R2 (fetch resilience, hotfix 3), narrowed by N1 (Stage 11): every
# crawl-derived dimension that actually REQUIRES sampled product pages,
# paired with the soa_shared registry entry (and whether it's a
# seen/said-split True Value dimension, whose crawl-side weight is
# seen_max rather than the full weight). agent_access/protocol_feed/
# value_protocols_seen (requires_pdp=False) are real-scored on a
# degraded run instead of synthesized here — see engine.py's
# _compute_discovery_surface_scores and its own N1 comment for why
# protocol_feed stays out of that real-scored set too.
DIMENSION_INPUT_MAP = (
    # (dim_key, registry_code, is_split, requires_pdp)
    ("agent_access", "agent_access", False, False),
    ("catalog_context", "catalog_context", False, True),
    ("protocol_feed", "protocol_feed", False, True),
    ("price_truth_seen", "price_truth", True, True),
    ("member_value_seen", "member_value", True, True),
    ("deal_citability_seen", "deal_citability", True, True),
    ("value_protocols_seen", "value_protocols", False, False),
)

DEGRADED_DIM_SPECS = tuple(
    (dim_key, registry_code, is_split)
    for dim_key, registry_code, is_split, requires_pdp in DIMENSION_INPUT_MAP
    if requires_pdp
)


def build_degraded_dimensions(reason: str, *, scan_engine_rev: Optional[str] = None) -> dict:
    """
    Synthesizes an honest, fully-v4-shaped dimensions dict for a run
    that never reached PDP-dependent scoring — every dimension in
    DEGRADED_DIM_SPECS scores 0/max at coverage='blocked' (NOT
    MEASURABLE; build_pillars_payload excludes these from the
    applicable-max sum and withholds the composite/verdict rather than
    computing one from data that was never sampled — the same honest
    rendering a normal blocked/failed scan already gets) with `reason`
    as its evidence line, so the report renders through the exact same
    pillars machinery as a normal scan instead of an empty {} that has
    no honest way to distinguish "never scored" from "scored, zero
    everywhere."

    scan_engine_rev is whatever the caller actually knows —
    apps/pipeline/scan/engine.py passes scan.structured_data.
    EXTRACTION_REV (the real crawl revision); a caller synthesizing
    this after the fact for a row whose crawl never ran, or never
    finished, at all has nothing real to put there, so it stays None.
    """
    dims = {}
    for dim_key, registry_code, is_split in DEGRADED_DIM_SPECS:
        registry_dim = DIMENSIONS_BY_CODE[registry_code]
        weight = registry_dim.seen_max if is_split else registry_dim.weight
        dims[dim_key] = {
            "score": 0.0, "max": weight, "evidence": [reason],
            "fix": None, "fix_human": None, "coverage": "blocked",
            "deferred_items": [], "cap_basis": [],
        }
    dims["scorer_version"] = SCORER_VERSION
    dims["scan_engine_rev"] = scan_engine_rev
    return dims


DEGRADED_REASON_BLOCKED = (
    "the store root and every sampled product page were rate-limited or "
    "blocked this run — nothing could be measured on-site"
)
DEGRADED_REASON_FAILED = (
    "the store root and every sampled product page could not be reached "
    "this run (network error) — nothing could be measured on-site"
)
# S2 (sitemap sampler, hotfix 5): a distinct, honest reason for the case
# where the sampler simply never found a product page to attempt at
# all — never worded as a site-blame ("blocked"/"refused"), since this
# can just as easily be our reader's own limitation.
DEGRADED_REASON_NO_PRODUCT_PAGES_TEMPLATE = (
    "we read {n} of your sitemaps but couldn't locate product pages to "
    "sample this run — this can be our reader's limitation; on-site "
    "checks weren't evaluated"
)
# Production outage (2026-09-22): the crawl's own orchestration raised
# before scan.engine.run_scan() ever started (or before it returned) —
# an internal bug (the signing-import NameError, or any future one like
# it), never anything the site did. worker.py's _run_lite_scan/
# _run_cycle_scan write this the moment that happens, instead of
# leaving the scan row 'running' forever for the watchdog to eventually
# mislabel as a timeout.
DEGRADED_REASON_ORCHESTRATION_FAILED = (
    "the crawl could not start this run (internal error) — nothing was "
    "measured on-site"
)
# worker.py's _sweep_lite_completions watchdog: a row still 'running'
# past SCAN_TIMEOUT_MINUTES. error stays the existing 'scan timed out'
# text for that path specifically — this is only the dimensions-level
# evidence reason, read by the report, not the scan row's error column.
DEGRADED_REASON_TIMED_OUT = (
    "the crawl was still running past our time limit and was stopped — "
    "nothing was measured on-site"
)
# apps/api/app/services/cycle_scoring.py: a blocked/failed row with no
# dimensions at all and no way to know WHY from here (an old row from
# before this stage, or any other row that reached a terminal status
# without dimensions ever getting written) — the honest generic
# fallback when none of the more specific reasons above apply.
DEGRADED_REASON_UNKNOWN = (
    "this run's on-site checks were never recorded — nothing could be "
    "measured on-site"
)
