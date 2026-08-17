"""
transcript_pick.py — "From the transcript": selects ONE live query +
verbatim agent response from a cycle's own coded runs, for the shared
TranscriptSection widget (both the lite audit report and the Full
Analysis report render it from this same service, parameterized by
cycle_id).

Selection is a deterministic 5-tier cascade over the cycle's own
successful, non-empty-response runs — biased to ALWAYS surface
something (see select_transcript's docstring for the exact tiers).
"No suitable transcript" (None) is reserved for zero successful runs;
every other cycle state has a tier that fires.

Numbers used in the generated right/leaked copy (share_pct, rank) are
NEVER recomputed here — they're passed in by the caller, which already
computed them the same way the pillars/visibility section does
(build_visibility_payload), so the transcript can never contradict the
scores by construction.

Highlights are located here, not on the frontend or at coding time:
coded_mentions/price_observations store no character offsets, so this
module does case-insensitive/tolerant text search over the run's own
raw_response and returns {start, end, kind} spans for the frontend to
paint. A claim that can't be located contributes to `leaked` copy only
— never an injected/approximated highlight (H1 convention).
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text

from app.services.cycle_scoring import decode_json_field
from soa_shared.scan_dimensions import PURCHASE_INTENT_STAGES

_STRENGTH_RANK = {"Primary": 3, "Positive": 2, "Neutral": 1, "Negative": 0}


@dataclass
class _RunCandidate:
    run_id: int
    platform: str
    run_at: object
    response_text: str
    query_id: int
    stage: str
    persona: str
    query_text: str
    coded: bool = False              # a soa_coded_mentions row exists for the primary on this run
    mentioned: bool = False          # only meaningful when coded=True
    position: Optional[int] = None
    strength: Optional[str] = None
    deal_cited: bool = False
    deal_types: tuple = ()
    price_observations: list = field(default_factory=list)   # primary's own, this run
    incentive_scores: list = field(default_factory=list)     # primary's own, this run (ground truth)
    competitor_deals: list = field(default_factory=list)      # [{name, deal_types}] competitors with deal_cited this run
    competitor_mentions: list = field(default_factory=list)   # [name, ...] every competitor mentioned this run


def _fetch_candidates(conn, cycle_id: int, primary_entity_id: int) -> List[_RunCandidate]:
    run_rows = conn.execute(text("""
        SELECT r.id, r.platform, r.run_at, r.raw_response, r.query_id,
               q.stage, q.persona, q.query_text,
               cm.id IS NOT NULL AS coded, cm.mentioned, cm.position, cm.strength,
               cm.deal_cited, cm.deal_types
        FROM soa_runs r
        JOIN soa_queries q ON q.id = r.query_id
        LEFT JOIN soa_coded_mentions cm ON cm.run_id = r.id AND cm.entity_id = :pid
        WHERE r.cycle_id = :cid AND r.status = 'success'
          AND r.raw_response IS NOT NULL AND r.raw_response != ''
        ORDER BY r.id
    """), {"cid": cycle_id, "pid": primary_entity_id}).fetchall()

    candidates: Dict[int, _RunCandidate] = {}
    for row in run_rows:
        (run_id, platform, run_at, raw_response, query_id, stage, persona, query_text,
         coded, mentioned, position, strength, deal_cited, deal_types) = row
        candidates[run_id] = _RunCandidate(
            run_id=run_id, platform=platform, run_at=run_at, response_text=raw_response,
            query_id=query_id, stage=stage, persona=persona, query_text=query_text,
            coded=bool(coded), mentioned=bool(mentioned) if coded else False,
            position=position, strength=strength,
            deal_cited=bool(deal_cited) if coded else False,
            deal_types=tuple(decode_json_field(deal_types, [])) if coded else (),
        )
    if not candidates:
        return []

    price_rows = conn.execute(text("""
        SELECT po.run_id, po.stated_price, po.claimed_net_price, po.merchant_name,
               po.attribution_status
        FROM soa_price_observations po
        JOIN soa_runs r ON r.id = po.run_id
        WHERE r.cycle_id = :cid AND po.entity_id = :pid
    """), {"cid": cycle_id, "pid": primary_entity_id}).fetchall()
    for run_id, stated_price, claimed_net_price, merchant_name, attribution_status in price_rows:
        if run_id in candidates:
            candidates[run_id].price_observations.append({
                "stated_price": stated_price, "claimed_net_price": claimed_net_price,
                "merchant_name": merchant_name, "attribution_status": attribution_status,
            })

    incentive_rows = conn.execute(text("""
        SELECT s.run_id, s.stated_price, s.ground_truth_true_cost, s.net_price_accuracy,
               s.measurement_status
        FROM soa_incentive_scores s
        JOIN soa_runs r ON r.id = s.run_id
        WHERE r.cycle_id = :cid AND s.entity_id = :pid
          AND s.scoring_grain = 'observation' AND s.status = 'scored'
    """), {"cid": cycle_id, "pid": primary_entity_id}).fetchall()
    for run_id, stated_price, ground_truth_true_cost, net_price_accuracy, measurement_status in incentive_rows:
        if run_id in candidates:
            candidates[run_id].incentive_scores.append({
                "stated_price": stated_price, "ground_truth_true_cost": ground_truth_true_cost,
                "net_price_accuracy": net_price_accuracy, "measurement_status": measurement_status,
            })

    competitor_rows = conn.execute(text("""
        SELECT cm.run_id, e.name, cm.deal_cited, cm.deal_types, cm.mentioned
        FROM soa_coded_mentions cm
        JOIN soa_runs r ON r.id = cm.run_id
        JOIN soa_cycle_entities ce ON ce.cycle_id = r.cycle_id AND ce.entity_id = cm.entity_id AND ce.role = 'competitor'
        JOIN soa_entities e ON e.id = cm.entity_id
        WHERE r.cycle_id = :cid AND cm.entity_id != :pid AND cm.mentioned = TRUE
    """), {"cid": cycle_id, "pid": primary_entity_id}).fetchall()
    for run_id, name, deal_cited, deal_types, _mentioned in competitor_rows:
        if run_id not in candidates:
            continue
        candidates[run_id].competitor_mentions.append(name)
        if deal_cited:
            candidates[run_id].competitor_deals.append({"name": name, "deal_types": tuple(decode_json_field(deal_types, []))})

    return list(candidates.values())


def _is_offsite(obs: dict, ground_truth_mismatch: bool) -> bool:
    """
    'mapped'/'unmapped' both name a real (or real-looking) third-party
    retailer — a genuine off-site signal. 'brand_self_reference' is
    excluded on purpose: it means the coder matched the entity's OWN
    merchant slug, i.e. likely a miscoded on-site claim, not evidence
    of an outside source. 'unattributed' (no retailer named at all) is
    ambiguous on its own, but paired with a real ground-truth mismatch
    it's still evidence the number didn't come from the entity's own
    page — the OR the task spec calls for.
    """
    if obs.get("attribution_status") in ("mapped", "unmapped"):
        return True
    if obs.get("attribution_status") == "unattributed" and ground_truth_mismatch:
        return True
    return False


def _ground_truth_mismatch(candidate: _RunCandidate) -> bool:
    # SQLite (tests) hands back BOOLEAN columns as plain 0/1 ints, not
    # Python bool — `is False` would silently miss every SQLite-backed
    # mismatch, so compare by value (`==`), same idiom as the net_price_
    # accuracy Postgres/SQLite fix in select_evidence_exemplar.
    return any(
        s["measurement_status"] == "measured" and s["net_price_accuracy"] == False  # noqa: E712
        for s in candidate.incentive_scores
    )


def _has_offsite_observation(candidate: _RunCandidate) -> bool:
    mismatch = _ground_truth_mismatch(candidate)
    return any(_is_offsite(obs, mismatch) for obs in candidate.price_observations)


def _has_leak(candidate: _RunCandidate) -> bool:
    if _has_offsite_observation(candidate):
        return True
    if candidate.competitor_deals and not candidate.deal_cited:
        return True
    if _ground_truth_mismatch(candidate):
        return True
    return False


def _max_gt_delta(candidate: _RunCandidate) -> float:
    deltas = [
        abs(s["stated_price"] - s["ground_truth_true_cost"]) / s["ground_truth_true_cost"]
        for s in candidate.incentive_scores
        if s["measurement_status"] == "measured" and s["ground_truth_true_cost"]
        and s["stated_price"] is not None
    ]
    return max(deltas) if deltas else 0.0


def _leak_severity_key(c: _RunCandidate):
    # Sort descending on (gt_delta, competitor_deal_count); ascending on
    # run_id as the final, stable tiebreak — achieved by negating the
    # first two and leaving run_id as-is, then sorting ascending overall.
    return (-_max_gt_delta(c), -len(c.competitor_deals), c.run_id)


def _visibility_weakness_key(c: _RunCandidate):
    strength_rank = _STRENGTH_RANK.get(c.strength, -1)
    position_val = c.position if c.position is not None else 999
    return (strength_rank, -position_val, c.run_id)


def _absence_key(c: _RunCandidate):
    is_purchase_intent = c.stage in PURCHASE_INTENT_STAGES
    return (0 if is_purchase_intent else 1, -len(set(c.competitor_mentions)), c.run_id)


# ─── Sentence-aligned preview cutoff ───────────────────────────────────────

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


def _preview_cutoff(text_: str, sentences: int = 3) -> int:
    if not text_:
        return 0
    boundaries = list(_SENTENCE_BOUNDARY_RE.finditer(text_))
    if not boundaries:
        return len(text_)
    idx = min(sentences, len(boundaries)) - 1
    return boundaries[idx].start()


# ─── Span location ──────────────────────────────────────────────────────────

def _find_all(text_: str, needle: str, kind: str) -> List[dict]:
    if not needle:
        return []
    text_lower = text_.lower()
    needle_lower = needle.lower()
    spans = []
    start = 0
    while True:
        idx = text_lower.find(needle_lower, start)
        if idx == -1:
            break
        spans.append({"start": idx, "end": idx + len(needle), "kind": kind})
        start = idx + len(needle)
    return spans


_PRICE_RE = re.compile(r"\$[\d,]+(?:\.\d{1,2})?(?:\s*(?:[-–—]|to)\s*\$?[\d,]+(?:\.\d{1,2})?)?", re.IGNORECASE)


def _find_price_span(text_: str, target_price: Optional[float]) -> Optional[dict]:
    """Tolerant of currency formatting and ranges ("$275–$325") — a
    single matched number or a range that CONTAINS the target price
    (within a cent of rounding) counts as locating the claim."""
    if target_price is None:
        return None
    for m in _PRICE_RE.finditer(text_):
        nums = re.findall(r"[\d,]+(?:\.\d{1,2})?", m.group())
        if not nums:
            continue
        values = [float(n.replace(",", "")) for n in nums]
        lo, hi = min(values), max(values)
        if lo - 0.01 <= target_price <= hi + 0.01:
            return {"start": m.start(), "end": m.end(), "kind": "value_claim"}
    return None


def _merge_spans(spans: List[dict]) -> List[dict]:
    """Non-overlapping, deterministic: longest match wins a tie on
    start position, earliest start wins otherwise — the frontend just
    paints whatever comes back, no overlap resolution of its own."""
    ordered = sorted(spans, key=lambda s: (s["start"], -(s["end"] - s["start"])))
    merged: List[dict] = []
    last_end = -1
    for s in ordered:
        if s["start"] >= last_end:
            merged.append(s)
            last_end = s["end"]
    return merged


def _locate_spans(candidate: _RunCandidate, primary_name: str, primary_aliases: List[str]) -> List[dict]:
    text_ = candidate.response_text
    spans: List[dict] = []
    for name in [primary_name] + list(primary_aliases or []):
        spans.extend(_find_all(text_, name, "brand"))

    mismatch = _ground_truth_mismatch(candidate)
    for obs in candidate.price_observations:
        if not _is_offsite(obs, mismatch):
            continue
        merchant_span = _find_all(text_, obs.get("merchant_name") or "", "value_claim")
        if merchant_span:
            spans.append(merchant_span[0])
        price_span = _find_price_span(text_, obs.get("stated_price") or obs.get("claimed_net_price"))
        if price_span:
            spans.append(price_span)

    for comp in candidate.competitor_deals:
        for deal_type in comp["deal_types"]:
            located = _find_all(text_, deal_type.replace("_", " "), "value_claim")
            if located:
                spans.append(located[0])
                break

    return _merge_spans(spans)


# ─── Narrative copy ─────────────────────────────────────────────────────────

def _fmt_price(value: Optional[float]) -> str:
    return f"${value:,.2f}" if value is not None else "an unstated price"


def _narrative_value_gap(c: _RunCandidate, share_pct, share_rank_label) -> Tuple[str, str]:
    share_bit = ""
    if share_pct is not None and share_rank_label:
        share_bit = f" — this conversation is one of the runs behind your {share_pct:.1f}% share and {share_rank_label} rank"
    strength_bit = " unprompted" if c.strength == "Primary" else ""
    right = f"You're named{strength_bit}{share_bit}."

    leaked_parts = []
    mismatch = _ground_truth_mismatch(c)
    offsite = [o for o in c.price_observations if _is_offsite(o, mismatch)]
    if offsite:
        merchant = offsite[0].get("merchant_name")
        source = f"**{merchant}**" if merchant else "a retailer, not your site"
        leaked_parts.append(f"Your price came from {source}, not your site")
    if c.competitor_deals and not c.deal_cited:
        leaked_parts.append(f"{c.competitor_deals[0]['name']}'s deal was quoted while yours went unmentioned")
    if not leaked_parts and mismatch:
        leaked_parts.append("the price quoted for you doesn't match ground truth")
    leaked = " — and ".join(leaked_parts) + ". That's the gap Pillar 03 measures." if leaked_parts else "Your value wasn't cited accurately here."
    return right, leaked


def _narrative_mentioned_no_leak(c: _RunCandidate) -> Tuple[str, str]:
    right_parts = ["You're mentioned in this answer"]
    if c.price_observations:
        right_parts.append("with an accurate price")
    right = " ".join(right_parts) + "."

    leaked_parts = []
    if c.strength in ("Neutral", "Negative") or (c.position and c.position > 1):
        leaked_parts.append("you're buried, not the lead pick")
    if not c.price_observations and not c.deal_cited:
        leaked_parts.append("no offer or price was cited at all — a citability gap, not a wrong number")
    leaked = ("Here, " + "; ".join(leaked_parts) + ".") if leaked_parts else "Nothing leaked in this run — it's a clean mention."
    return right, leaked


def _narrative_not_mentioned(c: _RunCandidate) -> Tuple[str, str]:
    if c.competitor_mentions:
        right = f"The agent understood the category and named a real competitor set ({', '.join(sorted(set(c.competitor_mentions))[:3])})."
    else:
        right = "Nothing — this is the visibility gap Pillar 01 measures."
    leaked = "You weren't named in this answer"
    if c.competitor_mentions:
        leaked += f" — {c.competitor_mentions[0]} took the slot instead."
    else:
        leaked += "."
    return right, leaked


def _narrative_uncoded(_c: _RunCandidate) -> Tuple[str, str]:
    return "This run is recorded.", "Coding is still pending for it."


def _build_payload(
    candidate: _RunCandidate, *, tier: int, case: str,
    query_index: int, total_queries: int,
    primary_name: str, primary_aliases: List[str],
    share_pct: Optional[float], share_rank_label: Optional[str],
) -> dict:
    if case == "value_gap":
        right, leaked = _narrative_value_gap(candidate, share_pct, share_rank_label)
    elif case == "mentioned_no_leak":
        right, leaked = _narrative_mentioned_no_leak(candidate)
    elif case == "not_mentioned":
        right, leaked = _narrative_not_mentioned(candidate)
    else:
        right, leaked = _narrative_uncoded(candidate)

    spans = _locate_spans(candidate, primary_name, primary_aliases)
    return {
        "run_id": candidate.run_id,
        "platform": candidate.platform,
        "query_text": candidate.query_text,
        "stage": candidate.stage,
        "persona": candidate.persona,
        "query_index": query_index,
        "total_queries": total_queries,
        "asked_at": str(candidate.run_at) if candidate.run_at else None,
        "response_text": candidate.response_text,
        "preview_cutoff": _preview_cutoff(candidate.response_text),
        "spans": spans,
        "narrative_case": case,
        "selection_tier": tier,
        "right": right,
        "leaked": leaked,
        "facts": {
            "mentioned": candidate.mentioned,
            "position": candidate.position,
            "strength": candidate.strength,
            "deal_cited": candidate.deal_cited,
            "deal_types": list(candidate.deal_types),
            "price_observations": candidate.price_observations,
            "incentive_scores": candidate.incentive_scores,
            "competitor_deals": candidate.competitor_deals,
        },
    }


def select_transcript(
    conn, cycle_id: int, primary_entity_id: int,
    *, share_pct: Optional[float] = None, share_rank_label: Optional[str] = None,
) -> Optional[dict]:
    """
    Deterministic 5-tier cascade over the cycle's own successful,
    non-empty-response runs, biased to always surface something:

      1. Purchase-intent stage · primary mentioned · a value leak
         present — ranked by leak severity (largest ground-truth
         delta, then most competitor deals cited).
      2. Any stage · primary mentioned · a leak present (same ranking).
      3. Any stage · primary mentioned, no leak — ranked by weakest
         visibility signal (lowest strength, then most buried position).
      4. Primary NOT mentioned (a real coded 'no', not an uncoded run)
         — ranked by purchase-intent stage first, then most
         competitors mentioned.
      5. Any successful run at all, coded or not — the earliest one.

    None only when the cycle has zero successful, non-empty-response
    runs. share_pct/share_rank_label are the caller's own already-
    computed visibility numbers (never recomputed here), so the
    generated copy can never drift from the scores.
    """
    candidates = _fetch_candidates(conn, cycle_id, primary_entity_id)
    if not candidates:
        return None

    entity_row = conn.execute(text("""
        SELECT name, aliases FROM soa_entities WHERE id = :pid
    """), {"pid": primary_entity_id}).fetchone()
    primary_name = entity_row[0] if entity_row else ""
    primary_aliases = decode_json_field(entity_row[1], []) if entity_row else []

    total_queries = conn.execute(text("""
        SELECT COUNT(DISTINCT query_id) FROM soa_runs WHERE cycle_id = :cid AND status = 'success'
    """), {"cid": cycle_id}).scalar() or 0
    query_index_rows = conn.execute(text("""
        SELECT DISTINCT query_id FROM soa_runs WHERE cycle_id = :cid AND status = 'success' ORDER BY query_id
    """), {"cid": cycle_id}).fetchall()
    query_index_by_id = {row[0]: i + 1 for i, row in enumerate(query_index_rows)}

    def pick(candidate: _RunCandidate, tier: int, case: str) -> dict:
        return _build_payload(
            candidate, tier=tier, case=case,
            query_index=query_index_by_id.get(candidate.query_id, 1), total_queries=total_queries,
            primary_name=primary_name, primary_aliases=primary_aliases,
            share_pct=share_pct, share_rank_label=share_rank_label,
        )

    tier1 = [c for c in candidates if c.coded and c.mentioned and c.stage in PURCHASE_INTENT_STAGES and _has_leak(c)]
    if tier1:
        return pick(min(tier1, key=_leak_severity_key), 1, "value_gap")

    tier2 = [c for c in candidates if c.coded and c.mentioned and _has_leak(c)]
    if tier2:
        return pick(min(tier2, key=_leak_severity_key), 2, "value_gap")

    tier3 = [c for c in candidates if c.coded and c.mentioned]
    if tier3:
        return pick(min(tier3, key=_visibility_weakness_key), 3, "mentioned_no_leak")

    tier4 = [c for c in candidates if c.coded and not c.mentioned]
    if tier4:
        return pick(min(tier4, key=_absence_key), 4, "not_mentioned")

    return pick(min(candidates, key=lambda c: c.run_id), 5, "uncoded")
