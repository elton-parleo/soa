"""
lite_pillars.py — pure scoring for the v3 Agent Scan dimensions that are
derived from the LITE_QUERY_COUNT-query coded/metrics data
(soa_coded_mentions, soa_price_observations via MetricsCalculator), not
from the crawl.

These dimensions don't exist inside apps/pipeline/scan/scorer.py's
crawl-only engine — that module never sees mention/metrics data — so
they're scored here, where apps/api/app/routers/public_lite.py already
joins both data sources to build the report. Weights/bands/opportunity
sets all come from soa_shared/scan_dimensions.py; nothing here is a
second definition of the rubric.

Pure functions: no DB access. Callers pass in values already fetched
from overall_metrics (the same dict build_entity_metrics produces —
no second counting path, same convention as lite_visibility.py and
lite_incentive_citation.py).
"""
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse

from soa_shared.scan_dimensions import (
    BAND_TYPE_COUNT,
    BAND_TYPE_RATE,
    COUNT_BAND_TABLE,
    DIMENSIONS_BY_CODE,
    FIX_OWNER_TRUESYNC,
    GAP_AREA_COUNT,
    LITE_QUERY_COUNT,
    MIN_OPPORTUNITY_SET_MENTIONS,
    PARLEO_OWNED_GAP_AREA_COUNT,
    PILLAR_WEIGHTS,
    PURCHASE_INTENT_STAGES,
    RATE_BAND_TABLE,
    apply_count_band,
    apply_rate_band,
    compute_composite,
    compute_verdict,
    dimension_max,
)

from app.services.lite_crosswalk import LOYALTY_DEAL_TYPES, RunSignal
from app.services.exposure_reasons import select_exposure_reasons

# ─── Check states (Part 1, A1) ────────────────────────────────────────────
#
# checks[] powers the report's live WHAT WE CHECK/YOUR RESULT chips. The
# crawl-derived dimensions (agent_access, catalog_context, protocol_feed,
# the seen halves of price_truth/member_value/deal_citability,
# value_protocols) only carry free-text evidence strings from apps/pipeline/
# scan/scorer.py — no pipeline diff is in scope this stage, so each check's
# pass/fail/na/advisory state is parsed here from scorer.py's own fixed
# evidence wording (confirmed verbatim by reading scorer.py directly).
# Labels are drawn from soa_shared.scan_dimensions's Dimension.how_measured
# tuples — the same registry both this file and the landing page's
# methodology section already read — so a parity test can assert every
# check's label is one of its dimension's how_measured strings.
CHECK_PASS = "pass"
CHECK_FAIL = "fail"
CHECK_NA = "na"
CHECK_ADVISORY = "advisory"
# Fetch-resilience stage (Part C): a dimension whose sampled product
# pages all terminally failed to fetch (scorer.py coverage='blocked')
# has nothing for the ordinary evidence-parsing check functions below
# to read — those parse for specific phrasings a blocked dimension's
# evidence never contains, and would silently misread "never checked"
# as "checked and failed" if run on it. CHECK_BLOCKED short-circuits
# that entirely; see _blocked_checks.
CHECK_BLOCKED = "blocked"


def _check(check_code: str, label: str, state: str, evidence: Optional[str] = None) -> Dict:
    # Stage 27 (A1): "code", not "id" — this payload's blanket "no
    # internal id keys" invariant (test_public_lite_report.py) forbids a
    # literal "id" key anywhere in the public report, and every other
    # identifier in this payload already uses "code" (see dimension rows
    # themselves) — same convention, not a special case.
    row = {"code": check_code, "label": label, "state": state}
    if evidence is not None:
        row["evidence"] = evidence
    return row


def _said_check_state(said_result: Dict) -> str:
    """Shared by price_truth/member_value's said-outcome check: na when
    the sub-lens itself is na (too few mentions to judge), else pass/fail
    on whether its own evidence string's leading citation count is > 0."""
    if said_result.get("na"):
        return CHECK_NA
    evidence = (said_result.get("evidence") or [""])[0]
    m = re.match(r"(\d+)", evidence)
    cited = int(m.group(1)) if m else 0
    return CHECK_PASS if cited > 0 else CHECK_FAIL


def _agent_access_checks(evidence: List[str]) -> List[Dict]:
    dim = DIMENSIONS_BY_CODE["agent_access"]
    if any(e.startswith("robots.txt allows product paths") for e in evidence):
        robots_state = CHECK_PASS
    elif any(e.startswith("robots.txt disallows:") for e in evidence):
        robots_state = CHECK_FAIL
    else:
        robots_state = CHECK_NA
    blocks_state = CHECK_PASS if any("no bot-blocking encountered" in e for e in evidence) else CHECK_FAIL
    sitemap_state = CHECK_PASS if any(e.startswith("sitemap present") for e in evidence) else CHECK_FAIL
    return [
        _check("robots_allows", dim.how_measured[0], robots_state),
        _check("no_bot_blocks", dim.how_measured[1], blocks_state),
        _check("sitemap", dim.how_measured[2], sitemap_state),
    ]


def _catalog_context_checks(evidence: List[str]) -> List[Dict]:
    dim = DIMENSIONS_BY_CODE["catalog_context"]
    # ": complete Product+Offer JSON-LD" (colon-space), not a bare
    # endswith("complete...") — "incomplete" itself ends in "complete",
    # which would otherwise false-match the missing/incomplete lines.
    has_complete = any(e.endswith(": complete Product+Offer JSON-LD") for e in evidence)
    has_incomplete = any(e.endswith("missing/incomplete Product+Offer JSON-LD") for e in evidence)
    all_complete = has_complete and not has_incomplete
    identifier_line = next((e for e in evidence if "expose a gtin/mpn/sku identifier" in e), None)
    brand_inconsistent = any("brand field inconsistent" in e for e in evidence)
    identifiers_ok = False
    if identifier_line:
        m = re.match(r"(\d+)/(\d+)", identifier_line)
        if m:
            n, total = int(m.group(1)), int(m.group(2))
            identifiers_ok = total > 0 and n == total and not brand_inconsistent
    return [
        _check("product_data", dim.how_measured[0], CHECK_PASS if has_complete else CHECK_FAIL),
        _check("completeness", dim.how_measured[1], CHECK_PASS if all_complete else CHECK_FAIL),
        _check("identifiers", dim.how_measured[2], CHECK_PASS if identifiers_ok else CHECK_FAIL),
    ]


def _protocol_feed_checks(evidence: List[str]) -> List[Dict]:
    dim = DIMENSIONS_BY_CODE["protocol_feed"]
    llms_state = (
        CHECK_PASS if any(e.startswith("/llms.txt present and non-empty") for e in evidence)
        else CHECK_NA if any(e.startswith("could not verify /llms.txt") for e in evidence)
        else CHECK_FAIL
    )
    mcp_state = (
        CHECK_PASS if any(e.startswith("MCP endpoint declaration discoverable") for e in evidence)
        else CHECK_NA if any(e.startswith("could not verify MCP endpoint") for e in evidence)
        else CHECK_FAIL
    )
    ucp_state = CHECK_PASS if any(e.startswith("UCP/UIP capability markup present") for e in evidence) else CHECK_FAIL
    return [
        _check("llms_txt", dim.how_measured[0], llms_state),
        _check("mcp", dim.how_measured[1], mcp_state),
        _check("ucp", dim.how_measured[2], ucp_state),
    ]


def _fetch_probe_evidence_line(fetch_probe: Optional[Dict]) -> Optional[str]:
    """
    Part 2 (P4.a), kind-aware (N4): the fetch probe's own three fixed
    sentences, keyed off its outcome — ChatGPT's own attempt to open
    the same product URL our reader sampled. Never changes any check's
    state (P4.c); None when the probe hasn't run yet or came back
    inconclusive (nothing confident enough to state as evidence).

    N4: a probe opened against the STORE ROOT (the ladder's fallback
    rung — no product page was ever sampled to ask about) is never
    presented as product-page price evidence here, regardless of
    outcome — a homepage price quote is not evidence about whether the
    PRODUCT PAGE's price is in code. That fact still reaches the
    visitor, just only via the degraded/no-product-pages banner
    (public_lite.py::_fetch_probe_banner_note), labeled as the
    homepage, not here.
    """
    if not fetch_probe:
        return None
    if fetch_probe.get("kind") == "store_root":
        return None
    outcome = fetch_probe.get("outcome")
    path = urlparse(fetch_probe.get("url") or "").path or fetch_probe.get("url") or ""
    if outcome == "quoted_price":
        return f"ChatGPT itself opened your product page and quoted {fetch_probe.get('price')} ({path})."
    if outcome == "opened_no_price":
        return f"ChatGPT itself opened your product page ({path}) but could not find a price to quote."
    if outcome == "could_not_access":
        return f"ChatGPT itself reported it could not access your product page ({path})."
    return None


def _price_truth_checks(
    seen_evidence: List[str], said_result: Dict, price_honesty: Optional[Dict],
    fetch_probe: Optional[Dict] = None,
) -> List[Dict]:
    dim = DIMENSIONS_BY_CODE["price_truth"]
    price_line = next((e for e in seen_evidence if "expose a machine-readable price" in e), None)
    m = re.match(r"(\d+)/(\d+)", price_line) if price_line else None
    has_any_price = bool(m and int(m.group(1)) > 0)
    price_state = CHECK_PASS if has_any_price else CHECK_FAIL
    mismatch = any("disagrees with the page's own visible price text" in e for e in seen_evidence)
    match_state = CHECK_NA if not has_any_price else (CHECK_FAIL if mismatch else CHECK_PASS)
    said_evidence = (said_result.get("evidence") or [None])[0]
    capped = bool((price_honesty or {}).get("would_have_capped"))
    advisory_label = f"fake sale prices · {'flagged' if capped else 'none flagged'}"
    return [
        _check("price_in_code", dim.how_measured[0], price_state, evidence=_fetch_probe_evidence_line(fetch_probe)),
        _check("price_matches_page", dim.how_measured[2], match_state),
        _check("said_price_cited", said_evidence or "mentions citing a price", _said_check_state(said_result)),
        # Always the dashed advisory chip (mock: permanently .adv-styled) —
        # only its text varies between flagged/none-flagged, never its state.
        _check("fake_sale_prices", advisory_label, CHECK_ADVISORY),
    ]


def _member_value_checks(seen_evidence: List[str], said_result: Dict) -> List[Dict]:
    dim = DIMENSIONS_BY_CODE["member_value"]
    loyalty_state = CHECK_PASS if any("loyalty page found and fetchable" in e for e in seen_evidence) else CHECK_FAIL
    member_price_state = (
        CHECK_PASS if any("expose member/tier pricing in structured data" in e for e in seen_evidence)
        else CHECK_FAIL
    )
    said_evidence = (said_result.get("evidence") or [None])[0]
    return [
        _check("loyalty_page", dim.how_measured[0], loyalty_state),
        _check("member_price_encoded", dim.how_measured[1], member_price_state),
        # Not independently observable from scorer.py's evidence strings —
        # strict-parse validity has no dedicated evidence line to parse.
        _check("markup_parses", dim.how_measured[2], CHECK_NA),
        _check("said_member_value", said_evidence or "purchase-intent mentions citing member value", _said_check_state(said_result)),
    ]


def _deal_citability_checks(seen_evidence: List[str]) -> List[Dict]:
    dim = DIMENSIONS_BY_CODE["deal_citability"]

    def _parse_ratio(line: str) -> tuple:
        m = re.match(r"(\d+)/(\d+)", line or "")
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

    concrete_line = next((e for e in seen_evidence if "concrete amount or discount mechanic" in e), "")
    active_line = next((e for e in seen_evidence if "currently-active validity window" in e), "")
    actionable_line = next((e for e in seen_evidence if "eligibility/code/stackability terms" in e), "")
    concrete_n, concrete_total = _parse_ratio(concrete_line)
    active_n, _ = _parse_ratio(active_line)
    actionable_n, _ = _parse_ratio(actionable_line)
    active_state = CHECK_NA if concrete_n == 0 else (CHECK_PASS if active_n > 0 else CHECK_FAIL)
    return [
        _check(
            "concrete_amount",
            f"{dim.how_measured[0]} ({concrete_n}/{concrete_total} pages)",
            CHECK_PASS if concrete_n > 0 else CHECK_FAIL,
        ),
        _check("not_expired", dim.how_measured[1], active_state),
        _check("actionable", dim.how_measured[2], CHECK_PASS if actionable_n > 0 else CHECK_FAIL),
    ]


def _blocked_checks(code: str, evidence: List[str]) -> List[Dict]:
    """Fetch-resilience stage (Part C): every one of a blocked
    dimension's registered checks reports state=CHECK_BLOCKED with the
    same honest fetch-facts line — there's no per-check granularity
    to report when the pages that would answer each check were never
    read at all."""
    dim = DIMENSIONS_BY_CODE[code]
    note = evidence[0] if evidence else "product pages could not be read this run"
    return [
        _check(f"{code}_blocked_{i}", label, CHECK_BLOCKED, evidence=note)
        for i, label in enumerate(dim.how_measured)
    ]


def _value_protocols_checks(evidence: List[str]) -> List[Dict]:
    dim = DIMENSIONS_BY_CODE["value_protocols"]
    if evidence == ["no protocol profile found"]:
        return [
            _check(check_id, label, CHECK_NA, evidence="no protocol profile found")
            for check_id, label in zip(
                ("ucp_discount", "loyalty", "acp_promotions", "version_schema"), dim.how_measured,
            )
        ]

    def _found(sub: str) -> bool:
        return any(sub in e for e in evidence)

    ucp_state = CHECK_PASS if _found("declares a UCP shopping-discount capability") else CHECK_FAIL
    loyalty_state = CHECK_PASS if _found("declares a loyalty/member protocol extension") else CHECK_FAIL
    acp_state = CHECK_PASS if _found("declares an ACP promotions capability") else CHECK_FAIL
    version_state = CHECK_PASS if _found("declared protocol manifest version is current") else CHECK_FAIL
    return [
        _check("ucp_discount", dim.how_measured[0], ucp_state),
        _check("loyalty", dim.how_measured[1], loyalty_state),
        _check("acp_promotions", dim.how_measured[2], acp_state),
        _check("version_schema", dim.how_measured[3], version_state),
    ]


# ─── Band context (Part 1, A2) ────────────────────────────────────────────
#
# Not new computation — apply_rate_band/apply_count_band already decide
# which band a said sub-lens landed in; these just report WHICH band index
# that was, so the frontend can put a "YOU" marker on the right rung of the
# band ladder it already renders from the registry's static bands array.

def _rate_band_index(rate_pct: Optional[float]) -> int:
    rate_pct = rate_pct or 0.0
    if rate_pct <= 0:
        return 0
    for i, (upper, _fraction) in enumerate(RATE_BAND_TABLE):
        if upper is None or rate_pct <= upper:
            return i
    return len(RATE_BAND_TABLE) - 1


def _count_band_index(count: Optional[int]) -> int:
    count = count or 0
    if count <= 0:
        return 0
    for i, (upper, _fraction) in enumerate(COUNT_BAND_TABLE):
        if upper is None or count <= upper:
            return i
    return len(COUNT_BAND_TABLE) - 1


def score_share_of_mentions(som_pct: Optional[float], total_mentions: int) -> Dict:
    """
    Stage 16 (Part 2, V1): points = round(min(som_pct, 50) / 50 * 25).
    Holding half of all mentions is dominance and earns full marks —
    calibrated and confirmed against real lite-run som distribution
    (median 60%, meaning most runs already clear this cap — the
    dimension is intentionally easy to ace; True Value is where the
    real differentiation lives).

    Zero-mention primary scores 0, not N/A — absence from every answer
    IS the visibility failure this dimension exists to catch (V3).
    """
    weight = DIMENSIONS_BY_CODE["share_of_mentions"].weight
    if not total_mentions or som_pct is None:
        return {
            "code": "share_of_mentions", "earned": 0.0, "max": weight,
            "evidence": [f"not mentioned in any of the {LITE_QUERY_COUNT} queries"],
            "your_value": 0.0,
        }
    capped = min(som_pct, 50.0)
    earned = round(capped / 50.0 * weight)
    return {
        "code": "share_of_mentions", "earned": earned, "max": weight,
        "evidence": [f"{som_pct:.1f}% share of mentions across all tracked brands"],
        # Part 1 (A2): the meter's live fill/YOU-marker position — the
        # same som_pct the evidence line already states, just as a raw
        # number the frontend can compute a percentage position from.
        "your_value": round(som_pct, 1),
    }


def _recommendation_strength_band(ratio: float) -> str:
    """
    Stage 21 (bug fix 2): plain-language, user-facing line — the raw
    rsi_score and its internal -1..+3 scale must never reach a visitor
    (a grep test over rendered report output asserts neither "rsi" nor
    "scale" ever appears). Banded off the dimension's own earned/max
    ratio, the same number the report already shows the visitor
    alongside this line, not a second, invisible metric.
    """
    if ratio >= 0.75:
        return "Consistently the top pick."
    if ratio >= 0.4:
        return "Often listed, rarely singled out as the pick."
    if ratio > 0:
        return "Mentioned, but rarely recommended outright."
    return "Named, but never actually recommended."


def score_recommendation_strength(rsi_score: Optional[float], total_mentions: int) -> Dict:
    """
    Stage 16 (Part 2, V2): a linear rescale of rsi_score's own bounded
    range [-1, +3] — the same Primary=+3/Positive=+1/Neutral=0/
    Negative=-1 per-mention weights MetricsCalculator already uses —
    onto [0, 15]. No new strength metric invented; this only rescales
    what the calculator computes.

    Zero-mention primary scores 0 (rsi_score is None with zero
    mentions — MetricsCalculator's total_mentions guard — an absence,
    not an undefined/N/A case, per V3).
    """
    weight = DIMENSIONS_BY_CODE["recommendation_strength"].weight
    if not total_mentions or rsi_score is None:
        return {
            "code": "recommendation_strength", "earned": 0.0, "max": weight,
            "evidence": [f"not mentioned in any of the {LITE_QUERY_COUNT} queries"],
            "your_band": 2,
        }
    raw = (rsi_score + 1.0) / 4.0 * weight
    earned = max(0, min(weight, round(raw)))
    return {
        "code": "recommendation_strength", "earned": earned, "max": weight,
        "evidence": [_recommendation_strength_band(earned / weight if weight else 0)],
        # Part 1 (A2): index into the registry's 3-rung ladder (1st +
        # endorsed / listed / absent) — matches the landing page's own
        # static visualParams.bands ordering.
        "your_band": 0 if earned >= weight else (1 if earned > 0 else 2),
    }


# ─── True Value 'said' sub-lenses (Stage 16, Part 3 T2) ──────────────────
#
# Each said sub-lens is a citation-rate/count OUTCOME over the primary
# entity's own mentions — did the answer actually state the thing, not
# just whether the store's pages encode it (that's 'seen', scorer.py).
# All three read the SAME List[RunSignal] the crosswalk already builds
# via public_lite.py::_fetch_run_signals (apps/api/app/services/
# lite_crosswalk.py) — no second query, no second counting path.
#
# <2 mentions in the sub-lens's own opportunity set -> N/A (not zero):
# too thin a sample to judge an outcome, as opposed to V1/V2's zero-
# mention primary case, where absence itself IS the failure being
# measured. Callers rescale the dimension onto its seen half when said
# is N/A (see soa_shared.scan_dimensions.dimension_max).
#
# Stage 7 discipline: PURCHASE_INTENT_STAGES is used only to FILTER
# signals server-side here — no stage name or stage-sliced count is
# ever placed in a returned dict's evidence/keys.

def _na_said_result(code: str, weight: float) -> Dict:
    return {
        "code": code, "earned": 0.0, "max": weight, "na": True,
        "evidence": ["fewer than 2 mentions in the relevant opportunity set"],
    }


def _not_evaluated_said_result(code: str, weight: float) -> Dict:
    """
    Part 1 (P4): a distinct honest state from _na_said_result — there
    WAS enough mention volume, but none of it has ever been through
    pass-2 price/citation coding (no soa_pass2_coding_log sentinel for
    any mention in the opportunity set), so there is no signal to rate
    at all. na=True keeps this on the existing NA rendering/rescaling
    path (rule 6, additive); not_evaluated distinguishes it from
    _na_said_result's "too few mentions" for the frontend's copy —
    "coded, none stated" (a real 0%) must never look identical to
    "never coded" (structural, this).
    """
    return {
        "code": code, "earned": 0.0, "max": weight, "na": True, "not_evaluated": True,
        "evidence": ["this audit predates price-observation coding — re-run for the full picture"],
    }


def score_price_truth_said(run_signals: List[RunSignal]) -> Dict:
    """
    Opportunity set: all mentions of the primary entity. Citation =
    RunSignal.primary_price_quoted (the same 'any stated/net price
    observed' signal apps/api/app/services/lite_crosswalk.py already
    uses for V1 linking — not a second definition).

    Part 1 (P4): primary_price_quoted only ever means something for a
    mention pass 2 has actually coded (RunSignal.pass2_coded — see
    public_lite.py::_fetch_run_signals's soa_pass2_coding_log join).
    The denominator is narrowed to sentineled mentions specifically so
    that "coded, none stated" (a real 0%, sentineled_mentions nonempty,
    cited=0) is never confused with "never coded" (sentineled_mentions
    empty) — the latter renders NOT EVALUATED, never a 0% rate the
    audit has no basis for.
    """
    weight = DIMENSIONS_BY_CODE["price_truth"].said_max
    mentions = [s for s in run_signals if s.primary_mentioned]
    total = len(mentions)
    if total < MIN_OPPORTUNITY_SET_MENTIONS:
        return _na_said_result("price_truth_said", weight)

    sentineled_mentions = [s for s in mentions if s.pass2_coded]
    if not sentineled_mentions:
        return _not_evaluated_said_result("price_truth_said", weight)

    coded_total = len(sentineled_mentions)
    cited = sum(1 for s in sentineled_mentions if s.primary_price_quoted)
    rate_pct = cited / coded_total * 100
    earned = round(apply_rate_band(rate_pct) * weight)
    return {
        "code": "price_truth_said", "earned": earned, "max": weight, "na": False,
        "evidence": [f"{cited}/{coded_total} coded answers ({rate_pct:.0f}%) cited a price"],
        "band_table_ref": BAND_TYPE_RATE, "your_value": round(rate_pct, 1), "your_band": _rate_band_index(rate_pct),
        # Part 4: raw counts, additive — exposure_reasons.py interpolates
        # these directly rather than parsing the evidence sentence above.
        "cited": cited, "total": coded_total,
    }


def score_member_value_said(run_signals: List[RunSignal]) -> Dict:
    """
    Opportunity set: purchase-intent-stage mentions of the primary
    entity only (Part 0 Q1 calibration — member-typed citations
    concentrate there). Citation = primary_member_price_claimed OR
    primary_deal_types intersecting LOYALTY_DEAL_TYPES
    (lite_crosswalk.py's own {member_price, loyalty_points} set —
    reused, not redefined) OR primary_member_value_cited (Part 5's
    coding extension — soa_coded_mentions.member_value_cited, a
    broader signal that also catches vague program-existence mentions
    the other two intentionally exclude).
    """
    weight = DIMENSIONS_BY_CODE["member_value"].said_max
    mentions = [
        s for s in run_signals
        if s.primary_mentioned and s.stage in PURCHASE_INTENT_STAGES
    ]
    total = len(mentions)
    if total < MIN_OPPORTUNITY_SET_MENTIONS:
        return _na_said_result("member_value_said", weight)

    cited = sum(
        1 for s in mentions
        if s.primary_member_price_claimed
        or s.primary_member_value_cited
        or (LOYALTY_DEAL_TYPES & set(s.primary_deal_types))
    )
    rate_pct = cited / total * 100
    earned = round(apply_rate_band(rate_pct) * weight)
    return {
        "code": "member_value_said", "earned": earned, "max": weight, "na": False,
        "evidence": [f"{cited}/{total} purchase-intent mentions ({rate_pct:.0f}%) cited member value"],
        "band_table_ref": BAND_TYPE_RATE, "your_value": round(rate_pct, 1), "your_band": _rate_band_index(rate_pct),
        "cited": cited, "total": total,
    }


def score_deal_citability_said(run_signals: List[RunSignal]) -> Dict:
    """
    Opportunity set: purchase-intent-stage mentions of the primary
    entity only (same Part 0 calibration as member_value.said).
    Citation = primary_deal_cited (the same existing field
    deal_citation_rate is built from — not a new definition).
    """
    weight = DIMENSIONS_BY_CODE["deal_citability"].said_max
    mentions = [
        s for s in run_signals
        if s.primary_mentioned and s.stage in PURCHASE_INTENT_STAGES
    ]
    total = len(mentions)
    if total < MIN_OPPORTUNITY_SET_MENTIONS:
        return _na_said_result("deal_citability_said", weight)

    cited = sum(1 for s in mentions if s.primary_deal_cited)
    earned = round(apply_count_band(cited) * weight)
    return {
        "code": "deal_citability_said", "earned": earned, "max": weight, "na": False,
        "evidence": [f"{cited} of {total} purchase-intent mentions cited a deal"],
        "band_table_ref": BAND_TYPE_COUNT, "your_value": cited, "your_band": _count_band_index(cited),
        "cited": cited, "total": total,
    }


# ─── member_value applicability (Stage 16, Part 4, P3) ───────────────────

def member_value_applicable(probe_result: Optional[str], seen_score: float) -> bool:
    """
    Whether the member_value dimension is scored at all this scan, vs.
    excluded entirely (N/A, Part 4 P4 — the whole-rubric /81
    normalization already built in soa_shared.scan_dimensions.
    applicable_max/compute_composite, not reimplemented here).

    Applicable when EITHER signal found a program: the membership probe
    said 'yes' (apps/pipeline/generation/membership_probe.py — a single
    out-of-band OpenAI call, metrically invisible), OR the crawl itself
    earned real credit (score_member_value_seen's score > 0 — a
    fetchable loyalty page, program terms, or member-price encoding).
    seen_score alone, NOT coverage, is the right crawl signal here:
    T1's merge (score_member_value_seen) always contributes loyalty-
    surface evidence and so its coverage is never 'na' even with zero
    credit earned (an un-findable loyalty page still scores 0 at
    coverage='full') — 'na' can't distinguish "found nothing" from
    "found something," only score can.

    Only excluded when BOTH come back empty: probe not 'yes' (an
    'unknown' probe result does NOT count as evidence — it's an
    abstention, not a finding) and the crawl earned zero credit. This
    is the case a bare "score 0" would otherwise misrepresent as
    "confirmed no program" when neither source actually confirmed
    anything.
    """
    return probe_result == "yes" or (seen_score or 0) > 0


# ─── Pillar/composite assembly (Stage 16, Part 7) ────────────────────────
#
# build_pillars_payload is the ONE place visibility/accessibility/true_
# value/composite are computed for scorer_version "3" — apps/api/app/
# routers/public_lite.py calls this once per report/teaser request and
# both responses render subsets of the same numbers; there is no second,
# ad-hoc blend anywhere else (Part 7's "ONE composite function").

_ACCESSIBILITY_CODES = ("agent_access", "catalog_context", "protocol_feed")
# The three True Value dimensions with a real seen/said split — Stage 25
# adds a 4th True Value dimension, value_protocols, which is encode-only
# (a seen half, no said half at all) and is therefore built separately,
# after this loop, rather than folded into it (see build_pillars_payload).
_TRUE_VALUE_SPLIT_CODES = ("price_truth", "member_value", "deal_citability")
_VALUE_PROTOCOLS_CODE = "value_protocols"

# Top FREE_FIX_RANK dimensions by opportunity size (max - earned) across
# the combined accessibility + True Value pool keep their fix text; the
# rest are nulled and locked=True — the same top-3-free-by-gap convention
# public_lite.py::_build_scan_payload already uses for v1/v2 rows, now
# the v3 report's only source of fix text (see build_pillars_payload's
# docstring — scan.dimensions is v1/v2-keyed and unusable for a v3 row).
FREE_FIX_RANK = 3


def _rank_and_lock_fixes(dims: List[Dict]) -> None:
    """Mutates dims in place: na rows are never ranked (no fixable gap,
    same as public_lite.py's applicable_codes exclusion); non-na rows
    outside the top FREE_FIX_RANK by gap have their fix nulled and
    locked set — paid-diagnostic fix text never leaves the process for
    a locked dimension. Fetch-resilience stage: blocked rows are excluded
    the same way — a dimension we couldn't read has no fix we can
    honestly attribute (fix/fix_human are already None on a blocked row)."""
    ranked = sorted(
        (d for d in dims if not d["na"] and not d.get("blocked")),
        key=lambda d: (-(d["max"] - d["earned"]), d["code"]),
    )
    free_codes = {d["code"] for d in ranked[:FREE_FIX_RANK]}
    for d in dims:
        if d["na"] or d.get("blocked"):
            d["locked"] = False
            continue
        d["locked"] = d["code"] not in free_codes
        if d["locked"]:
            d["fix"] = None


# Part 3 (F1): the free report's ranked-fixes list gives away only the
# top 2 (tightened from the pre-existing FREE_FIX_RANK=3 used above for
# pillars.*.dimensions[].fix/locked, which stays unchanged for rule-6
# back-compat — nothing currently reads it except the fixes list itself,
# which now reads _build_fixes_section's output instead).
FREE_FIX_VISIBLE_RANK = 2


def _build_fixes_section(dims: List[Dict]) -> Dict:
    """
    Builds the report's `fixes` field: {visible: [...], remaining_count}.
    This is a SEPARATE, purely additive payload field from `dims` itself
    — `dims` (accessibility_dims + true_value_dims) keeps carrying every
    dimension's earned/max/evidence unconditionally, because the True
    Value butterfly and Accessibility tiles need real scores for all 6
    dimensions regardless of fix-lock status. Only THIS field enforces
    the "top 2 fixes free, rest is a bare count" rule — ranks beyond
    FREE_FIX_VISIBLE_RANK never have their code/name/impact serialized
    anywhere in it (Part 3's leak test).

    Same ranking rule as _rank_and_lock_fixes (opportunity size, max -
    earned, descending; deterministic tiebreak by code), but additionally
    excludes any dimension with no fix_human at all — a dimension already
    scoring its full max has nothing to fix and must not count toward
    remaining_count or occupy a free slot.

    Part 2 (2a/2b): the ranked list must always surface a TrueSync-owned
    fix when one is honestly available — TrueSync fixes deal_citability
    and value_protocols directly, so a ranked list that only ever shows
    ENG-owned rows undersells what Parleo itself closes. If neither top
    slot is TrueSync-owned, the LAST ranked slot is swapped for the
    highest-impact TrueSync-owned dimension that still recovers >=1
    applicable point (already-ranked ordering of the untouched slots is
    left alone; the displaced dimension falls back into remaining_count,
    it doesn't vanish). If no TrueSync-owned dimension can recover >=1
    point this run (skipped/na or already at max), the rule does not
    fire and no row is forced — a fix worth zero points must never
    render as ranked.
    """
    ranked = sorted(
        (d for d in dims if not d["na"] and not d.get("blocked") and d.get("fix_human")),
        key=lambda d: (-(d["max"] - d["earned"]), d["code"]),
    )
    visible_dims = list(ranked[:FREE_FIX_VISIBLE_RANK])

    has_truesync = any(DIMENSIONS_BY_CODE[d["code"]].fix_owner == FIX_OWNER_TRUESYNC for d in visible_dims)
    if not has_truesync and visible_dims:
        truesync_candidates = [
            d for d in ranked
            if DIMENSIONS_BY_CODE[d["code"]].fix_owner == FIX_OWNER_TRUESYNC and (d["max"] - d["earned"]) >= 1
        ]
        if truesync_candidates:
            visible_dims[-1] = truesync_candidates[0]  # ranked is already sorted by gap desc

    visible = [
        {
            "code": d["code"], "name": d["name"],
            "fix_human": d["fix_human"],
            "impact": round(d["max"] - d["earned"], 1),
            # F3: ENG or TRUESYNC — see scan_dimensions.Dimension.fix_owner.
            "fix_owner": DIMENSIONS_BY_CODE[d["code"]].fix_owner,
        }
        for d in visible_dims
    ]
    return {
        "visible": visible,
        "remaining_count": max(0, len(ranked) - len(visible_dims)),
    }


def _parleo_fixable_points(dims: List[Dict]) -> float:
    """F4: the point pool TrueSync itself can recover on this run — the
    measured gap (max - earned) summed over the two TrueSync-owned
    dimensions (deal_citability, value_protocols), excluding na/blocked
    rows the same way _build_fixes_section does (nothing honestly
    fixable to report from a dimension we couldn't measure)."""
    return round(
        sum(
            d["max"] - d["earned"]
            for d in dims
            if not d["na"] and not d.get("blocked")
            and DIMENSIONS_BY_CODE[d["code"]].fix_owner == FIX_OWNER_TRUESYNC
        ),
        1,
    )


_ACCESSIBILITY_CHECKS_BY_CODE = {
    "agent_access": _agent_access_checks,
    "catalog_context": _catalog_context_checks,
    "protocol_feed": _protocol_feed_checks,
}


def _crawl_dim_row(code: str, crawl_dimensions: Dict[str, dict]) -> Dict:
    d = crawl_dimensions.get(code) or {}
    coverage = d.get("coverage") or "full"
    blocked = coverage == "blocked"
    evidence = d.get("evidence") or []
    checks_fn = _ACCESSIBILITY_CHECKS_BY_CODE.get(code)
    if blocked:
        checks = _blocked_checks(code, evidence)
    elif checks_fn and coverage != "na":
        checks = checks_fn(evidence)
    else:
        checks = None
    return {
        "code": code, "name": DIMENSIONS_BY_CODE[code].name,
        "earned": d.get("score") or 0.0, "max": d.get("max") or 0.0,
        "na": coverage == "na", "blocked": blocked, "evidence": evidence,
        "seen": None, "said": None,
        "checks": checks,
        "fix": d.get("fix"), "fix_human": d.get("fix_human"), "locked": False,
    }


def _mention_dim_row(result: Dict) -> Dict:
    row = {
        "code": result["code"], "name": DIMENSIONS_BY_CODE[result["code"]].name,
        "earned": result["earned"], "max": result["max"],
        "na": False, "evidence": result.get("evidence") or [],
        "seen": None, "said": None, "checks": None,
    }
    # Part 1 (A2): share_of_mentions' meter fill / recommendation_
    # strength's band-ladder index — whichever this result carries.
    if "your_value" in result:
        row["your_value"] = result["your_value"]
    if "your_band" in result:
        row["your_band"] = result["your_band"]
    return row


def _sub_lens(earned: float, max_: float, na: bool, evidence: List[str], extra: Optional[Dict] = None) -> Dict:
    row = {"earned": earned, "max": max_, "na": na, "evidence": evidence}
    if extra:
        row.update({k: v for k, v in extra.items() if k not in ("code", "earned", "max", "na", "evidence")})
    return row


def _pillar(earned: float, applicable_max: float, dimensions: List[Dict]) -> Dict:
    score = round(earned / applicable_max * 100) if applicable_max else 0
    return {"score": score, "max": 100.0, "dimensions": dimensions}


def _dim_by_code(dims: List[Dict], code: str) -> Dict:
    return next(d for d in dims if d["code"] == code)


def build_pillars_payload(
    *,
    som_pct: Optional[float],
    rsi_score: Optional[float],
    total_mentions: int,
    crawl_dimensions: Dict[str, dict],
    run_signals: List[RunSignal],
    membership_probe_result: Optional[str],
    membership_probe_evidence: Optional[str] = None,
    fetch_probe_result: Optional[Dict] = None,
) -> Dict:
    """
    Assembles the full v3 pillar/composite payload from already-fetched
    primitives — no DB access. crawl_dimensions is the scan row's
    decoded `dimensions` dict (engine.py's output: agent_access,
    catalog_context, protocol_feed, price_truth_seen, member_value_seen,
    deal_citability_seen, each {score, max, coverage, evidence, ...}).
    run_signals is the same List[RunSignal] the crosswalk already builds
    (apps/api/app/routers/public_lite.py::_fetch_run_signals) — no
    second query.

    Returns {"visibility", "accessibility", "true_value" (each a
    {score, max, dimensions}), "composite", "member_value_na"}.
    """
    # ── Visibility: share_of_mentions + recommendation_strength ──
    som_result = score_share_of_mentions(som_pct, total_mentions)
    rsi_result = score_recommendation_strength(rsi_score, total_mentions)
    visibility_earned = som_result["earned"] + rsi_result["earned"]
    visibility_dims = [_mention_dim_row(som_result), _mention_dim_row(rsi_result)]

    # ── Accessibility: agent_access + catalog_context + protocol_feed ──
    # protocol_feed is the only one of the three that can ever go 'na'
    # (brand-only sites, Stage 10 D5); excluded from both sums, not
    # scored as zero, same na-exclusion convention as engine.py's own
    # crawl-only total. Fetch-resilience stage: catalog_context can now
    # also come back 'blocked' (every sampled product page unreadable
    # this run) — excluded from both sums the same way, per B4.
    accessibility_earned = 0.0
    accessibility_applicable_max = 0.0
    accessibility_dims = []
    for code in _ACCESSIBILITY_CODES:
        row = _crawl_dim_row(code, crawl_dimensions)
        if not row["na"] and not row["blocked"]:
            accessibility_earned += row["earned"]
            accessibility_applicable_max += row["max"]
        accessibility_dims.append(row)

    # ── True Value: price_truth, member_value, deal_citability ──
    # Each combines its crawl-derived 'seen' half (engine.py) with its
    # mention-derived 'said' half (scored above) via dimension_max's
    # na-rescale when said's own opportunity set is too thin (T2).
    # member_value additionally has a whole-dimension P3 applicability
    # gate (probe result OR crawl credit) — excluded entirely, not just
    # rescaled onto seen, when neither signal found a program (P4).
    said_by_code = {
        "price_truth": score_price_truth_said(run_signals),
        "member_value": score_member_value_said(run_signals),
        "deal_citability": score_deal_citability_said(run_signals),
    }
    member_value_seen = crawl_dimensions.get("member_value_seen") or {}
    member_value_na = not member_value_applicable(
        membership_probe_result, member_value_seen.get("score") or 0.0,
    )

    true_value_earned = 0.0
    true_value_applicable_max = 0.0
    true_value_dims = []
    for code in _TRUE_VALUE_SPLIT_CODES:
        dim = DIMENSIONS_BY_CODE[code]
        seen = crawl_dimensions.get(f"{code}_seen") or {}
        said = said_by_code[code]
        seen_coverage = seen.get("coverage") or "full"
        seen_blocked = seen_coverage == "blocked"
        seen_row = _sub_lens(
            seen.get("score") or 0.0, seen.get("max") or 0.0,
            seen_coverage == "na", seen.get("evidence") or [],
            extra={"blocked": True} if seen_blocked else None,
        )
        said_row = _sub_lens(said["earned"], said["max"], said["na"], said.get("evidence") or [], extra=said)

        if code == "member_value" and member_value_na:
            # Stage 19 (R2): the probe's own verbatim answer, quoted
            # as-is — the report's only evidence for an otherwise
            # silent exclusion. Omitted (not a fabricated "no evidence
            # found") when the probe never ran or returned nothing.
            na_evidence = [f"probe: '{membership_probe_evidence}'"] if membership_probe_evidence else []
            true_value_dims.append({
                "code": code, "name": dim.name, "earned": 0.0, "max": 0.0,
                "na": True, "evidence": na_evidence, "seen": seen_row, "said": said_row,
                # Part 1 (A1): no live checks on the N/A path — the panel
                # shows the decision sentence + probe quote instead (T2).
                "checks": None,
                "fix": None, "fix_human": None, "locked": False,
            })
            continue

        if seen_blocked:
            # Fetch-resilience stage (B4): the encode sub-lens is NOT
            # MEASURABLE — excluded from the applicable max exactly like
            # the existing member-value N/A path above, rather than
            # rescaled onto said or scored as zero. said's own row is
            # still attached (real signal, unrelated to page fetches)
            # even though it doesn't count toward the composite here —
            # no methodology change, just an honest "couldn't verify."
            true_value_dims.append({
                "code": code, "name": dim.name, "earned": 0.0, "max": 0.0,
                "na": False, "blocked": True, "evidence": [], "seen": seen_row, "said": said_row,
                "checks": _blocked_checks(code, seen.get("evidence") or []),
                "fix": None, "fix_human": None, "locked": False,
            })
            continue

        if code == "member_value" and membership_probe_result == "yes" and not (seen.get("score") or 0):
            # Stage 21 (bug fix 3): the probe found a program but the
            # crawl found no surface to encode it — surface BOTH signals
            # on the applicable path. Stage 19 only threaded the probe's
            # evidence into the na branch above; the applicable path's
            # seen evidence was crawl-only, silently dropping the very
            # signal that made this dimension applicable in the first
            # place.
            probe_note = "program exists (probe) · not discoverable on site"
            seen_row = _sub_lens(
                seen_row["earned"], seen_row["max"], seen_row["na"],
                [probe_note] + seen_row["evidence"],
            )

        dim_max = dimension_max(dim, said_na=said["na"])
        earned = (seen.get("score") or 0.0) + (0.0 if said["na"] else said["earned"])
        true_value_earned += earned
        true_value_applicable_max += dim_max

        # Part 1 (A1): checks[] blends the seen-side structural checks
        # with the said-side outcome (and, for price_truth, the price-
        # honesty advisory) into one row — matching the mock's combined
        # WHAT WE CHECK/YOUR RESULT panel for these three dimensions.
        if code == "price_truth":
            checks = _price_truth_checks(
                seen.get("evidence") or [], said, crawl_dimensions.get("price_honesty_advisory"),
                fetch_probe=fetch_probe_result,
            )
        elif code == "member_value":
            checks = _member_value_checks(seen_row["evidence"], said)
        else:
            checks = _deal_citability_checks(seen.get("evidence") or [])

        true_value_dims.append({
            "code": code, "name": dim.name, "earned": earned, "max": dim_max,
            "na": False, "evidence": [], "seen": seen_row, "said": said_row,
            "checks": checks,
            "fix": seen.get("fix"), "fix_human": seen.get("fix_human"), "locked": False,
        })

    # Value Protocols (Stage 25, Part 1/3): encode-only — a seen half,
    # no said half at all, because an agent's answer has no way to state
    # whether a store "declares" a checkout protocol (Part 6, A1's
    # single-wing butterfly render). Built separately from the loop
    # above rather than folded in: `said` stays a real Python None (not
    # a _sub_lens with na=True), matching the schema's already-optional
    # `said` field, and there is no member_value-style na branch — V1
    # is explicit that absence scores 0, it never excludes this
    # dimension from the pillar the way member_value can be excluded.
    vp_dim = DIMENSIONS_BY_CODE[_VALUE_PROTOCOLS_CODE]
    vp_seen = crawl_dimensions.get(f"{_VALUE_PROTOCOLS_CODE}_seen") or {}
    vp_seen_row = _sub_lens(
        vp_seen.get("score") or 0.0, vp_seen.get("max") or 0.0,
        (vp_seen.get("coverage") or "full") == "na", vp_seen.get("evidence") or [],
    )
    vp_earned = vp_seen.get("score") or 0.0
    vp_max = dimension_max(vp_dim)  # no said/split -> always the full weight
    true_value_earned += vp_earned
    true_value_applicable_max += vp_max
    true_value_dims.append({
        "code": _VALUE_PROTOCOLS_CODE, "name": vp_dim.name, "earned": vp_earned, "max": vp_max,
        "na": False, "evidence": [], "seen": vp_seen_row, "said": None,
        "checks": _value_protocols_checks(vp_seen.get("evidence") or []),
        "fix": vp_seen.get("fix"), "fix_human": vp_seen.get("fix_human"), "locked": False,
    })

    # Part 4: table-driven exposure reasons — evaluated from the same
    # already-computed sub-lenses above (seen/said dicts per True Value
    # dim, accessibility's dim rows, visibility's som numbers), never a
    # second scoring pass.
    exposure_reasons_ctx = {
        "price_truth_seen": _dim_by_code(true_value_dims, "price_truth")["seen"],
        "price_truth_said": _dim_by_code(true_value_dims, "price_truth")["said"],
        "member_value_applicable": not member_value_na,
        "member_value_seen": _dim_by_code(true_value_dims, "member_value")["seen"],
        "member_value_said": _dim_by_code(true_value_dims, "member_value")["said"],
        "deal_citability_seen": _dim_by_code(true_value_dims, "deal_citability")["seen"],
        "deal_citability_said": _dim_by_code(true_value_dims, "deal_citability")["said"],
        "value_protocols": vp_seen_row,
        "catalog_context": _dim_by_code(accessibility_dims, "catalog_context"),
        "agent_access": _dim_by_code(accessibility_dims, "agent_access"),
        "visibility": {
            "earned": som_result["earned"], "max": som_result["max"], "na": False,
            "som_pct": som_pct if som_pct is not None else 0.0, "total_mentions": total_mentions,
        },
    }
    exposure_reasons = select_exposure_reasons(exposure_reasons_ctx)

    # Fix text only exists on the 7 crawl-derived dimensions above
    # (accessibility's 3 + True Value's 4 seen-halves) — visibility's
    # mention-derived dimensions have nothing crawl-fixable to offer, so
    # they're outside the ranking pool entirely (see _rank_and_lock_fixes).
    fixable_dims = accessibility_dims + true_value_dims
    _rank_and_lock_fixes(fixable_dims)
    fixes = _build_fixes_section(fixable_dims)
    parleo_fixable_points = _parleo_fixable_points(fixable_dims)

    total_earned = visibility_earned + accessibility_earned + true_value_earned
    raw_composite = compute_composite(total_earned, member_value_na=member_value_na)

    # Verdict gate template branching (G1): compute_composite's denominator
    # is a static registry constant — it never shrinks when a dimension
    # comes back 'blocked', so a run with unmeasurable accessibility
    # dimensions used to get a real (silently misleading, artificially
    # low) composite instead of an honest "can't score this run" — and
    # compute_verdict would then assert a failing verdict from data that
    # was never actually measured. state disambiguates three cases:
    #   scored: nothing blocked -> the numbers above are trustworthy.
    #   composite_withheld: accessibility has a blocked dimension, but
    #     True Value itself is clean -> tv_pct is still real, composite
    #     and verdict are withheld (None) rather than fabricated.
    #   unverified: True Value's OWN applicable set has a blocked
    #     dimension (the same "any blocked encode wing" condition the
    #     True Value section's UNVERIFIED chip already uses — see
    #     LiteFullReport.jsx's anyTrueValueEncodeBlocked/N3 — reused
    #     here, not redefined) -> True Value's own measurement is
    #     compromised enough that neither composite nor tv_pct means
    #     anything this run.
    unmeasured_count = sum(1 for d in accessibility_dims if d["blocked"])
    true_value_blocked = any(d.get("blocked") for d in true_value_dims)
    if true_value_blocked:
        state = "unverified"
    elif unmeasured_count > 0:
        state = "composite_withheld"
    else:
        state = "scored"

    if state == "unverified":
        tv_pct = None
    elif true_value_applicable_max > 0:
        tv_pct = round(true_value_earned / true_value_applicable_max * 100, 1)
    else:
        tv_pct = None

    if state == "scored":
        composite = raw_composite
        # Stage 25 (Part 5, G1): the verdict gate — deliberately
        # independent of the composite's straight-sum weighting. Uses
        # True Value's own applicable_max (already na-aware: excludes
        # member_value's weight when it's N/A), so a legitimately
        # program-less store is judged on the value dimensions that
        # actually apply to it, same discipline as the composite's own
        # /85 rescale. Only ever called in state=scored — the invariant
        # (asserted server-side by PublicLitePillars' model_validator)
        # is that AGENT-READY/NOT AGENT-READY exists only alongside a
        # real composite, never withheld/unverified data.
        verdict = compute_verdict(composite, true_value_earned, true_value_applicable_max)
    else:
        composite = None
        verdict = None

    return {
        "visibility": _pillar(visibility_earned, PILLAR_WEIGHTS["visibility"], visibility_dims),
        "accessibility": _pillar(accessibility_earned, accessibility_applicable_max, accessibility_dims),
        "true_value": _pillar(true_value_earned, true_value_applicable_max, true_value_dims),
        "composite": composite,
        "member_value_na": member_value_na,
        "fixes": fixes,
        "verdict": verdict,
        "state": state,
        "tv_pct": tv_pct,
        "tv_earned": true_value_earned,
        "tv_applicable": true_value_applicable_max,
        "unmeasured_count": unmeasured_count,
        # F4: gap-area counts for the S2 fixable-hook band ("Parleo can
        # fix N of your M major gaps") — gap_areas_total/parleo_fixes are
        # fixed framework facts (see scan_dimensions.GAP_AREA_COUNT);
        # parleo_fixable_points is this run's own measured recoverable
        # points within TrueSync's two owned dimensions.
        "gap_areas_total": GAP_AREA_COUNT,
        "gap_areas_parleo_fixes": PARLEO_OWNED_GAP_AREA_COUNT,
        "parleo_fixable_points": parleo_fixable_points,
        # Part 4: run-tailored exposure reasons — see exposure_reasons.py.
        "exposure_reasons": exposure_reasons,
    }
