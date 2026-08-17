"""
cycle_scoring.py — Full Analysis coexistence, Phase 3a: the report-
assembly logic extracted from app/routers/public_lite.py, parameterized
by cycle_id rather than lite-request internals.

This is a behavior-preserving extraction (Phase 3a) — build_cycle_report
is byte-identical in output to the pre-extraction _build_report_payload
for the same (scan_row, cycle_id) inputs; see
tests/test_cycle_scoring_parity.py for the snapshot proof this claim is
built on. Phase 3b's SCORER_VERSION generalization lands in a SEPARATE
function (build_full_cycle_report, added alongside this one, never by
mutating it) so this function keeps rendering scorer_version "5" v3
pillars-shaped reports exactly as it always has.

Deliberately does NOT know about lite_request_id or soa_lite_requests at
all — the caller (public_lite.py) fetches its own scan_row (1:1 via
lite_request_id) and passes it in; a future full-cycle caller fetches
its own scan_row (via soa_lite_scan_results.cycle_id, Phase 1) the same
way. Nor does it know about competitor_source (soa_lite_requests-only,
lite-specific) — public_lite.py adds that field itself, after calling
this.
"""
import json
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import text

from soa_shared.scan_dimensions import SCORER_VERSION
from app.routers.metrics import build_entity_metrics
from app.services.lite_crosswalk import GAP_THRESHOLD, RunSignal, link_dimensions, link_incentive_citation
from app.services.lite_incentive_citation import build_incentive_citation_payload
from app.services.lite_pillars import build_pillars_payload, member_value_applicable
from app.services.lite_visibility import build_visibility_payload
from app.services.transcript_pick import select_transcript
from app.schemas import (
    EntityMetrics,
    PublicLiteEntityMetrics,
    PublicLiteReportResponse,
    PublicLiteScan,
    PublicLiteScanDimension,
    PublicLiteScanFamily,
)

# Re-weighting session (Part 4): the first scorer_version that ever
# computed a `pillars` payload via build_pillars_payload (Stage 25). A
# row at this version or newer, but behind the CURRENT SCORER_VERSION, is
# retired to the "expired" report state rather than re-rendered — see
# build_cycle_report. Versions before this were never pillars-shaped in
# the first place, so they keep using the historical fallback below,
# unaffected by any future bump of this constant.
FIRST_PILLARS_SCORER_VERSION = 4

# Stage 19 (R4): lite_crosswalk.py still reasons in v1/v2 dimension
# codes (its rules predate the v3 registry) — this maps its output onto
# the v3 dimension a visitor actually sees a chip on. Reflects the same
# conceptual regrouping the v3 registry itself made (V1 Offer
# Legibility -> price_truth; V2 Loyalty Surface + V3 Member Value ->
# member_value; V4 Value Rails + V5 Offer Integrity -> deal_citability;
# F1/F2 map straight across). Not exhaustive over every old code —
# F3 never appears in link_dimensions()' output today.
_CROSSWALK_CODE_TO_V3 = {
    "F1": "agent_access", "F2": "catalog_context",
    "V1": "price_truth", "V2": "member_value", "V3": "member_value",
    "V4": "deal_citability", "V5": "deal_citability",
}

DIMENSION_ORDER = ("F1", "F2", "F3", "V1", "V2", "V3", "V4", "V5")
DIMENSION_NAMES = {
    "F1": "Agent Access",
    "F2": "Catalog Context",
    "F3": "Protocol & Feed Presence",  # was "Transaction Rails" (Stage 10, scorer_version "2")
    "V1": "Offer Legibility",
    "V2": "Loyalty Surface",
    "V3": "Member Value",
    "V4": "Value Rails",
    "V5": "Offer Integrity",
}
FOUNDATION_CODES = {"F1", "F2", "F3"}
FOUNDATION_MAX = 35
VALUE_MAX = 65
FREE_FIX_RANK = 3  # top 3 opportunities (by score gap) get their fix text for free


def decode_json_field(value, default):
    """JSON columns come back already-decoded via psycopg2; defensively
    handle a driver (or SQLite test) that returns the raw string instead —
    same idiom as worker.py::process_lite_requests."""
    if isinstance(value, str):
        return json.loads(value) if value else default
    return value if value is not None else default


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def share_rank_label_for(share_of_mentions: list, primary_name: str) -> Optional[str]:
    """'1st of 6' style label matching the mock's "1st-of-6 rank" copy —
    ranked by the SAME share_of_mentions rows the visibility pillar
    already renders, so the transcript widget's copy can never
    contradict that section's own numbers."""
    if not share_of_mentions:
        return None
    ranked = sorted(share_of_mentions, key=lambda r: -r["mentions"])
    for i, row in enumerate(ranked):
        if row["entity"] == primary_name:
            return f"{_ordinal(i + 1)} of {len(ranked)}"
    return None


def _bare_domain(url) -> Optional[str]:
    """Logo feature, Part 1c: the bare hostname (no scheme, no leading
    www.) BrandLogo's domain-keyed fallback tiers need — the target's
    own domain is always known (it's what the crawl was asked to read),
    independent of whether the crawl itself found an icon."""
    if not url:
        return None
    hostname = urlparse(url if '://' in url else f'https://{url}').hostname
    if not hostname:
        return None
    return hostname[4:] if hostname.startswith('www.') else hostname


def _fetch_run_signals(conn, cycle_id: int, primary_entity_id: int) -> list:
    """
    One RunSignal (apps/api/app/services/lite_crosswalk.py) per successful
    run in the cycle. Every query joins through r.cycle_id/r.id rather
    than an explicit run-id list, so this reads identically against
    SQLite (tests) and Postgres (production) — no IN-list expansion.
    """
    run_rows = conn.execute(text("""
        SELECT r.id, q.stage
        FROM soa_runs r
        JOIN soa_queries q ON q.id = r.query_id
        WHERE r.cycle_id = :cid AND r.status = 'success'
    """), {"cid": cycle_id}).fetchall()
    if not run_rows:
        return []
    stage_by_run = {row[0]: row[1] for row in run_rows}

    primary_rows = conn.execute(text("""
        SELECT r.id, cm.mentioned, cm.deal_cited, cm.deal_types, cm.member_value_cited
        FROM soa_runs r
        LEFT JOIN soa_coded_mentions cm ON cm.run_id = r.id AND cm.entity_id = :eid
        WHERE r.cycle_id = :cid AND r.status = 'success'
    """), {"cid": cycle_id, "eid": primary_entity_id}).fetchall()
    primary_by_run = {row[0]: (row[1], row[2], row[3], row[4]) for row in primary_rows}

    # Part 1 (P4): pass2_coded (soa_pass2_coding_log, coding_pass_version=2)
    # is a SEPARATE join from soa_price_observations — a sentineled run
    # with zero observation rows for this entity is a real "coded, no
    # price stated" zero, honestly distinct from a run pass 2 never
    # touched at all. LEFT JOINing observations alone (as before this
    # stage) could never tell the two apart.
    price_rows = conn.execute(text("""
        SELECT r.id,
               MAX(CASE WHEN po.stated_price IS NOT NULL OR po.claimed_net_price IS NOT NULL THEN 1 ELSE 0 END),
               MAX(CASE WHEN po.member_price_claimed THEN 1 ELSE 0 END),
               MAX(CASE WHEN log.id IS NOT NULL THEN 1 ELSE 0 END)
        FROM soa_runs r
        LEFT JOIN soa_price_observations po ON po.run_id = r.id AND po.entity_id = :eid
        LEFT JOIN soa_pass2_coding_log log ON log.run_id = r.id AND log.coding_pass_version = 2
        WHERE r.cycle_id = :cid AND r.status = 'success'
        GROUP BY r.id
    """), {"cid": cycle_id, "eid": primary_entity_id}).fetchall()
    price_by_run = {row[0]: (bool(row[1]), bool(row[2]), bool(row[3])) for row in price_rows}

    competitor_rows = conn.execute(text("""
        SELECT r.id,
               MAX(CASE WHEN cm.mentioned THEN 1 ELSE 0 END),
               MAX(CASE WHEN cm.mentioned AND cm.deal_cited THEN 1 ELSE 0 END)
        FROM soa_runs r
        JOIN soa_cycle_entities ce ON ce.cycle_id = r.cycle_id AND ce.role = 'competitor'
        LEFT JOIN soa_coded_mentions cm ON cm.run_id = r.id AND cm.entity_id = ce.entity_id
        WHERE r.cycle_id = :cid AND r.status = 'success'
        GROUP BY r.id
    """), {"cid": cycle_id}).fetchall()
    competitor_by_run = {row[0]: (bool(row[1]), bool(row[2])) for row in competitor_rows}

    signals = []
    for run_id, stage in stage_by_run.items():
        mentioned, deal_cited, deal_types, member_value_cited = primary_by_run.get(
            run_id, (False, False, None, False),
        )
        deal_types = decode_json_field(deal_types, [])
        price_quoted, member_price_claimed, pass2_coded = price_by_run.get(run_id, (False, False, False))
        competitor_mentioned, competitor_deal_cited = competitor_by_run.get(run_id, (False, False))

        signals.append(RunSignal(
            stage=stage,
            primary_mentioned=bool(mentioned),
            primary_deal_cited=bool(deal_cited),
            primary_deal_types=tuple(deal_types or []),
            primary_price_quoted=price_quoted,
            primary_member_price_claimed=member_price_claimed,
            primary_member_value_cited=bool(member_value_cited),
            pass2_coded=pass2_coded,
            competitor_mentioned=competitor_mentioned,
            competitor_deal_cited=competitor_deal_cited,
        ))
    return signals


def _fetch_probe_banner_note(fetch_probe: dict) -> dict | None:
    """
    Part 2 (P4.b), kind-aware (N4): the fact the blocked/degraded banner
    needs to stop "agents would hit the same wall" from being an
    inference — whether ChatGPT itself could open the same URL our
    reader tried, AND which URL that was (product page vs the store
    root) so the frontend can name it honestly instead of a generic
    "it". None when the probe hasn't run yet or came back inconclusive
    (nothing confident enough to append to the banner).
    """
    outcome = (fetch_probe or {}).get("outcome")
    if outcome not in ("quoted_price", "opened_no_price", "could_not_access"):
        return None
    return {
        "outcome": outcome,
        "agent_could_access": outcome in ("quoted_price", "opened_no_price"),
        "url": fetch_probe.get("url"),
        "kind": fetch_probe.get("kind"),
    }


def build_scan_payload(scan_row, linked: dict) -> dict | None:
    """
    Shapes one soa_lite_scan_results row into the public 'scan' object.
    Never blocks the report (rule 7): any non-'complete' status — or no
    row at all — degrades to a status-only/absent object rather than
    raising or omitting the honest status badge.

    Stage 10 (A2): a dimension's 'coverage' is 'na' when it's inapplicable
    to this site type (Stage 10 D5) — those dimensions are excluded from
    fix-ranking and from each family's applicable_max entirely, not
    scored as zero. A pre-Stage-10 row has no coverage/deferred_items/
    cap_basis/scorer_version keys at all; every one of those defaults to
    its Stage-1 meaning ('full' coverage, scorer_version "1") so an old
    row renders exactly as it always has, no crash, no stray tags.

    Family `max` stays the nominal 35/65 always (rule 6 — an existing
    field's meaning never changes); `applicable_max` is the new, additive
    ceiling to use instead when something in that family is 'na' (W2).
    subtotal itself is left as the raw sum over applicable dimensions
    (not independently re-projected onto /35) so it always reads
    correctly against whichever denominator the UI chooses.
    """
    if not scan_row:
        return None

    (status, total_score, integrity_capped, dimensions, pages_fetched,
     _membership_probe, _revenue_probe, fetch_probe_raw, _input_url) = scan_row
    pages_fetched = decode_json_field(pages_fetched, [])
    fetch_probe = decode_json_field(fetch_probe_raw, {})

    if status != 'complete':
        # Sitemap-sampler stage (hotfix 5, S2/S3): degraded_reason/
        # degraded_banner_facts are sibling keys inside the same
        # dimensions jsonb engine.py already writes (no migration) —
        # decoded here just enough to surface them, never the full
        # per-dimension breakdown (that stays complete-only, unchanged).
        degraded = decode_json_field(dimensions, {})
        banner_facts = dict(degraded.get('degraded_banner_facts') or {})
        # Part 2 (P4.b): the probe runs AFTER the scan writes its own
        # banner facts (it needs the scan's own fetch_probe_url), so
        # this is the earliest point the two can be combined.
        probe_note = _fetch_probe_banner_note(fetch_probe)
        if probe_note:
            banner_facts['fetch_probe'] = probe_note
        # W6: whether this run's fetches were signed (Web Bot Auth) —
        # engine.py records signing_enabled unconditionally, so this is
        # always present (never absent-vs-false ambiguity) on any row
        # scanned since that stage shipped; a pre-W6 row has no such
        # key at all and defaults to False (unsigned wording), honest
        # for a row that predates signing existing.
        banner_facts['signed'] = bool(degraded.get('signing_enabled'))
        return PublicLiteScan(
            status=status,
            total_score=total_score,
            integrity_capped=bool(integrity_capped),
            pages_fetched=pages_fetched,
            degraded_reason=degraded.get('degraded_reason'),
            degraded_banner_facts=banner_facts or None,
            agent_access_matrix=degraded.get('agent_access_matrix'),
            discovery_trace=degraded.get('discovery_trace'),
        ).model_dump()

    dimensions = decode_json_field(dimensions, {})
    scorer_version = dimensions.get('scorer_version') or '1'

    def _coverage(code: str) -> str:
        return dimensions.get(code, {}).get('coverage') or 'full'

    applicable_codes = [c for c in DIMENSION_ORDER if _coverage(c) != 'na']

    # Rank by opportunity size (max - score) descending — biggest gaps
    # first — deterministic tiebreak by code. 'na' dimensions have no
    # fixable gap and are excluded entirely so they can't crowd a real
    # dimension out of the free top-3 (Stage 10). Only the top
    # FREE_FIX_RANK dimensions' fix text is given away free; the rest
    # are locked.
    ranked_codes = sorted(
        applicable_codes,
        key=lambda code: (
            -(dimensions.get(code, {}).get('max', 0) - dimensions.get(code, {}).get('score', 0)),
            code,
        ),
    )
    rank_by_code = {code: i + 1 for i, code in enumerate(ranked_codes)}

    dim_rows = []
    foundation_subtotal = 0.0
    value_subtotal = 0.0
    foundation_applicable_max = 0.0
    value_applicable_max = 0.0
    for code in DIMENSION_ORDER:
        d = dimensions.get(code, {})
        score = d.get('score', 0)
        max_ = d.get('max', 0)
        fix = d.get('fix')
        fix_human = d.get('fix_human')
        evidence = d.get('evidence', [])
        coverage = _coverage(code)
        is_applicable = coverage != 'na'

        rank = rank_by_code.get(code)
        locked = fix is not None and rank is not None and rank > FREE_FIX_RANK
        if locked:
            fix = None
            fix_human = None

        if is_applicable:
            if code in FOUNDATION_CODES:
                foundation_subtotal += score
                foundation_applicable_max += max_
            else:
                value_subtotal += score
                value_applicable_max += max_

        reason = linked.get(code)
        dim_rows.append(PublicLiteScanDimension(
            code=code,
            name=DIMENSION_NAMES[code],
            score=score,
            max=max_,
            evidence=evidence,
            fix=fix,
            fix_human=fix_human,
            locked=locked,
            linked={"reason": reason} if reason else None,
            coverage=coverage,
            deferred_items=d.get('deferred_items') or [],
            cap_basis=d.get('cap_basis') or [],
        ).model_dump())

    return PublicLiteScan(
        status=status,
        total_score=total_score,
        integrity_capped=bool(integrity_capped),
        scorer_version=scorer_version,
        foundation=PublicLiteScanFamily(
            subtotal=round(foundation_subtotal, 1), max=FOUNDATION_MAX,
            applicable_max=round(foundation_applicable_max, 1),
        ).model_dump(),
        value=PublicLiteScanFamily(
            subtotal=round(value_subtotal, 1), max=VALUE_MAX,
            applicable_max=round(value_applicable_max, 1),
        ).model_dump(),
        dimensions=dim_rows,
        pages_fetched=pages_fetched,
        agent_access_matrix=dimensions.get('agent_access_matrix'),
        discovery_trace=dimensions.get('discovery_trace'),
    ).model_dump()


def _attach_v3_linked_reasons(pillars_payload: dict | None, linked: dict) -> None:
    """Mutates pillars_payload in place, adding a {"reason": ...} onto
    the matching v3 dimension row — same {"reason": ...} shape
    build_scan_payload already puts on v1/v2 rows, so the widget's
    existing chip-rendering logic needs no new shape to handle. Never
    fires on an 'na' dimension (R4) since there's no fixable/citable
    gap to explain there.

    Stage 21 (bug fix 1): the source rule (e.g. F1/F2's "absent from
    most answers") fires on MENTION absence, not on the dimension's own
    crawl score — so remapping it blindly could attach an alarm chip to
    a dimension that's actually scoring well (real case: agent_access at
    4.8/6 = 80%). A chip only means something next to a dimension that's
    ALSO failing — same GAP_THRESHOLD (lite_crosswalk.py) every other
    linking rule in this codebase already uses to decide "is this
    dimension actually a gap," not a second threshold definition.
    """
    if not pillars_payload or not linked:
        return
    v3_linked: dict = {}
    for old_code, reason in linked.items():
        v3_code = _CROSSWALK_CODE_TO_V3.get(old_code)
        if v3_code:
            v3_linked.setdefault(v3_code, reason)
    if not v3_linked:
        return
    for pillar_key in ("accessibility", "true_value"):
        for dim in pillars_payload[pillar_key]["dimensions"]:
            if dim["code"] not in v3_linked or dim["na"] or dim.get("blocked"):
                continue
            is_failing = dim["max"] > 0 and dim["earned"] < GAP_THRESHOLD * dim["max"]
            if is_failing:
                dim["linked"] = {"reason": v3_linked[dim["code"]]}


def _fetch_metrics_rows(conn, cycle_id: int):
    """
    Same column order (indices 0-11) as soa_dashboard_summary, so
    build_entity_metrics (app/routers/metrics.py) works unchanged — see
    that function's docstring. role/comparison_code are appended after,
    used here for grouping/ordering only; comparison_code is never
    returned to the caller.

    Only the 'overall' slice is fetched — per-stage rows are no longer
    assembled into the public payload at all (Stage 7, G1: stage-level
    mention data is paid-diagnostic material and must never reach this
    router's response). soa_metrics_results still has 'stage' rows for
    every cycle; a future internal-only table can query them directly
    without this router touching them.
    """
    # Logo feature, Part 2b: e.website_url appended at the END (index 14)
    # — build_entity_metrics is documented to work off indices 0-11
    # unchanged (same shape as soa_dashboard_summary), and role/
    # comparison_code are already read positionally at 12/13 elsewhere
    # in this file, so nothing existing may shift.
    return conn.execute(text("""
        SELECT
          e.slug, e.name, mr.slice_type, mr.slice_value,
          mr.total_runs, mr.total_mentions, mr.mention_rate, mr.soa_pct,
          mr.position_index, mr.rsi_score, mr.deal_citation_rate, mr.platform_dist_index,
          ce.role, ce.comparison_code, e.website_url
        FROM soa_metrics_results mr
        JOIN soa_entities e ON e.id = mr.entity_id
        JOIN soa_cycle_entities ce
          ON ce.cycle_id = mr.cycle_id AND ce.entity_id = mr.entity_id
        WHERE mr.cycle_id = :cid
          AND mr.slice_type = 'overall'
        ORDER BY ce.comparison_code, mr.slice_value
    """), {"cid": cycle_id}).fetchall()


def build_cycle_report(conn, cycle_id: int, scan_row) -> dict:
    """
    Assembles the full report payload for one cycle — the SAME shape
    _build_report_payload (public_lite.py) always returned, minus the
    lite-only competitor_source field (the caller adds that itself).
    scan_row is the caller's own already-fetched soa_lite_scan_results
    row (or None) — how to find it differs by caller (lite: 1:1 via
    lite_request_id; a future full-cycle caller: via cycle_id, Phase 1),
    so that lookup deliberately stays outside this function.
    """
    rows = _fetch_metrics_rows(conn, cycle_id)

    entity_info: dict = {}    # comparison_code -> {"name":, "role":} (internal grouping key only)
    overall_metrics: dict = {}
    # Stage 8 (A1): the raw, unnormalized 0.0-1.0 deal_citation_rate
    # (row[10]) — kept separate from overall_metrics' *100-normalized
    # copy (build_entity_metrics' 'deal_citation_rate') because
    # lite_incentive_citation.py needs the un-rounded-to-1dp original to
    # recover deal_cited_count exactly. Instrument itself (row[10]'s
    # source column) is unmodified this stage.
    raw_deal_citation_rate: dict = {}
    primary_code = None

    for row in rows:
        name, role, comp_code, website_url = row[1], row[12], row[13], row[14]
        entity_info.setdefault(comp_code, {"name": name, "role": role, "website_url": website_url})
        if role == 'primary':
            primary_code = comp_code
        overall_metrics[comp_code] = build_entity_metrics(row)
        raw_deal_citation_rate[comp_code] = row[10]

    scan_status = scan_row[0] if scan_row else None
    # R2 (fetch resilience, hotfix 3): a 'blocked' or 'failed' scan under
    # the CURRENT scorer version now carries a real, honestly-degraded
    # dimensions dict too (engine.py's _degraded_dimensions — every
    # crawl-derived dimension coverage='blocked', see scan/engine.py) —
    # scan_scorable is the broader gate that lets those render through
    # the same v4 pillars machinery as a normal scan, rather than an
    # empty {} routing to the retired legacy fallback. scan_complete
    # itself stays narrow (status == 'complete') for the one place that
    # still needs exactly that: the old-scorer-version historical
    # fallback below, which only has real numbers to show for a scan
    # that genuinely completed under its own (retired) rubric.
    scan_complete = bool(scan_row and scan_row[0] == 'complete')
    scan_scorable = bool(scan_row and scan_row[0] in ('complete', 'blocked', 'failed'))
    dimensions_raw = decode_json_field(scan_row[3], {}) if scan_scorable else {}
    scorer_version = dimensions_raw.get('scorer_version') or '1'

    # Logo feature, Part 1c: unconditional on scan_scorable — the target
    # domain is known the instant a request names a store_url, whether
    # or not the crawl itself ever completed. BrandLogo's rail fallback
    # needs this even on a blocked/failed run.
    store_domain = _bare_domain(scan_row[8]) if scan_row else None

    # Re-weighting session (Part 4): a scan scored under an earlier
    # PILLARS-CAPABLE version (scorer_version "4", the direct predecessor
    # of this session's weight change) carries earned points computed
    # against OLD dimension maxes — rendering it against the CURRENT
    # registry would produce incoherent output (earned exceeding max,
    # wrong composite, wrong verdict) that still looks plausible.
    # Backward compatibility is explicitly not required: retire the
    # report to an honest "expired" state instead of rendering it,
    # recomputing it, or showing the stale score alongside a warning.
    #
    # Scoped to scorer_version >= FIRST_PILLARS_SCORER_VERSION deliberately
    # — a genuinely pre-Stage-25 row (scorer_version "1"/"2"/"3") never
    # went through build_pillars_payload at all (it was ALREADY on the
    # historical foundation/value-family fallback below, byte-identically,
    # long before this session), so it isn't newly "incoherent" the way a
    # stale-but-pillars-shaped v4 row is — it keeps rendering exactly as
    # it always has. Gated on scan_scorable too — a request with no scan
    # row at all (dimensions_raw = {}, scorer_version defaults to "1")
    # has nothing to expire.
    try:
        is_stale_pillars_version = int(scorer_version) >= FIRST_PILLARS_SCORER_VERSION and scorer_version != SCORER_VERSION
    except (TypeError, ValueError):
        is_stale_pillars_version = False
    if scan_scorable and is_stale_pillars_version:
        return {
            "status": "expired",
            "store_domain": store_domain,
            "store_url": scan_row[8] if scan_row else None,
        }

    # Part 5 (R3): independent of scan_complete/scorer_version — the
    # revenue probe is a brand-level OpenAI call, same as the membership
    # probe, not gated on the crawl succeeding.
    revenue_probe = decode_json_field(scan_row[6], {}) if scan_row else {}
    revenue_estimate_usd = revenue_probe.get('annual_revenue_usd')

    # Part 2 (P4): same unconditional read as revenue_probe above — the
    # fetch probe is a brand/URL-level OpenAI call, not gated on
    # scan_scorable (it's meaningful evidence on a blocked run too, see
    # build_scan_payload's banner-merge above).
    fetch_probe = decode_json_field(scan_row[7], {}) if scan_row else {}

    # Stage 16 (Part 7): primary_entity_id/run_signals are fetched once,
    # ahead of the teaser/report branch, because BOTH need them for a
    # scorer_version "3" pillars computation (not just the crosswalk
    # 'linked' step below, which reuses the same run_signals — no
    # second query).
    primary_entity_id = None
    if primary_code:
        primary_entity_row = conn.execute(text("""
            SELECT entity_id FROM soa_cycle_entities WHERE cycle_id = :cid AND role = 'primary'
        """), {"cid": cycle_id}).fetchone()
        primary_entity_id = primary_entity_row[0] if primary_entity_row else None

    run_signals: list = []
    if scan_scorable and primary_entity_id is not None:
        run_signals = _fetch_run_signals(conn, cycle_id, primary_entity_id)

    # Stage 16 (Part 7), updated Stage 25 (R1/R2): the ONE composite
    # function — a scan at the CURRENT scorer version computes
    # visibility/accessibility/composite from the registry-driven
    # pillars breakdown (build_pillars_payload); every other case
    # (older scan at a retired scorer_version, no scan, no primary
    # entity) falls back to the pre-Stage-16 formula byte-identically,
    # so historical rows keep rendering exactly as they always have
    # (Stage 10 W6 precedent). Compared against the registry's own
    # SCORER_VERSION rather than a hard-coded literal so a v3 row now
    # correctly falls through to that same historical fallback the
    # instant this file bumps to v4 — no second "is this current"
    # definition to keep in sync by hand.
    pillars_payload = None
    if scan_scorable and scorer_version == SCORER_VERSION and primary_entity_id is not None:
        primary_metrics = overall_metrics.get(primary_code) or {}
        membership_probe = decode_json_field(scan_row[5], {})
        pillars_payload = build_pillars_payload(
            som_pct=primary_metrics.get("som"),
            rsi_score=primary_metrics.get("rsi"),
            total_mentions=primary_metrics.get("total_mentions") or 0,
            crawl_dimensions=dimensions_raw,
            run_signals=run_signals,
            membership_probe_result=membership_probe.get("result"),
            membership_probe_evidence=membership_probe.get("raw_evidence"),
            fetch_probe_result=fetch_probe or None,
        )

    if pillars_payload is not None:
        visibility = pillars_payload["visibility"]["score"]
        accessibility = pillars_payload["accessibility"]["score"]
        composite = pillars_payload["composite"]
    else:
        # visibility reuses the same share-of-voice metric already
        # computed for the report (build_entity_metrics' 'som') — no
        # second metrics path. Already stage-agnostic (only ever reads
        # the 'overall' slice), so no rebasing was needed for Stage 7 (A2).
        visibility = overall_metrics.get(primary_code, {}).get("som") if primary_code else None
        accessibility = scan_row[1] if scan_complete else None
        composite = None
        if visibility is not None:
            composite = (
                round(0.6 * visibility + 0.4 * accessibility)
                if accessibility is not None
                else visibility
            )

    overall = [
        PublicLiteEntityMetrics(
            name=info["name"],
            role=info["role"],
            metrics=EntityMetrics(**overall_metrics.get(code, {})),
        ).model_dump()
        for code, info in entity_info.items()
    ]

    # Stage 7 (A1): reshapes the SAME overall_metrics values already
    # built above — mentioned_queries/mentions both read total_mentions
    # (mention_rate's numerator and share_of_mentions' numerator are the
    # same count in this system; see lite_visibility.py's docstring) —
    # no second counting path.
    visibility_entities = [
        {
            "name": info["name"],
            "is_primary": info["role"] == "primary",
            "mentioned_queries": overall_metrics.get(code, {}).get("total_mentions") or 0,
            "total_queries": overall_metrics.get(code, {}).get("total_runs") or 0,
            "mentions": overall_metrics.get(code, {}).get("total_mentions") or 0,
            "domain": info.get("website_url"),
        }
        for code, info in entity_info.items()
    ]
    visibility_breakdown = build_visibility_payload(visibility_entities)

    # Stage 8 (A1): incentive_citation reshapes the same overall_metrics
    # rows above (no second query) — deal_citation_rate is a pre-existing,
    # already-computed column (H1: the coding/metrics instrument is
    # frozen this stage).
    incentive_citation_entities = [
        {
            "name": info["name"],
            "is_primary": info["role"] == "primary",
            "mentions": overall_metrics.get(code, {}).get("total_mentions") or 0,
            "deal_citation_rate_raw": raw_deal_citation_rate.get(code),
        }
        for code, info in entity_info.items()
    ]
    incentive_citation = build_incentive_citation_payload(incentive_citation_entities)
    visibility_breakdown["incentive_citation"] = incentive_citation

    # Stage 16 (Part 7): reuses dimensions_raw/run_signals/primary_
    # entity_id already fetched above for the pillars computation — no
    # second query for either.
    linked: dict = {}
    if scan_scorable and primary_entity_id is not None:
        linked = link_dimensions(run_signals, dimensions_raw)

        # Stage 8 (A4): merged via setdefault so an existing Stage-7
        # rule's reason on V2/V3 always wins if one already fired.
        for code, reason in link_incentive_citation(incentive_citation, dimensions_raw).items():
            linked.setdefault(code, reason)

    _attach_v3_linked_reasons(pillars_payload, linked)
    scan_payload = build_scan_payload(scan_row, linked)

    # "From the transcript" widget: renders whenever the cycle has at
    # least one successful, non-empty-response run for the primary
    # entity — independent of scan_scorable (it's about the runs
    # themselves, not the crawl). share_pct/rank_label come from the
    # SAME visibility_breakdown rows just built above, never recomputed
    # inside select_transcript, so the widget's copy can never drift
    # from the visibility pillar's own numbers.
    transcript_payload = None
    if primary_entity_id is not None:
        primary_share_row = next(
            (r for r in visibility_breakdown["share_of_mentions"] if r["is_primary"]), None,
        )
        share_pct = primary_share_row["share_pct"] if primary_share_row else None
        share_rank_label = share_rank_label_for(
            visibility_breakdown["share_of_mentions"],
            entity_info.get(primary_code, {}).get("name") if primary_code else None,
        )
        transcript_payload = select_transcript(
            conn, cycle_id, primary_entity_id,
            share_pct=share_pct, share_rank_label=share_rank_label,
            # F1/F2's own gate (engine.py, STATUS_COMPLETE only) — a
            # non-empty offers list means the PDP encoded at least one
            # machine-readable price the agent could have quoted.
            page_price_encoded=bool(dimensions_raw.get("offers")),
        )

    return PublicLiteReportResponse(
        status="complete", locked=False, overall=overall, by_stage=None,
        scan=scan_payload,
        visibility=visibility, accessibility=accessibility, composite=composite,
        scan_status=scan_status,
        visibility_breakdown=visibility_breakdown,
        competitor_source=None,  # stamped by the caller (public_lite.py) when applicable
        pillars=pillars_payload,
        revenue_estimate_usd=revenue_estimate_usd,
        # F1/F2: only ever present on the crawl_dimensions dict of a
        # STATUS_COMPLETE run (engine.py) — naturally None on a degraded/
        # blocked/pre-this-stage row, same additive gating as `pillars`.
        offers=dimensions_raw.get("offers"),
        product_image_url=dimensions_raw.get("product_image_url"),
        product_name=dimensions_raw.get("product_name"),
        generated_headlines=dimensions_raw.get("generated_headlines"),
        brand_icon_url=dimensions_raw.get("brand_icon_url"),
        store_domain=store_domain,
        transcript=transcript_payload,
    ).model_dump()
