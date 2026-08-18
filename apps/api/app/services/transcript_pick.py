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

DTC-vs-wholesale attribution (bug fix note): soa_price_observations.
entity_id names the BRAND BEING PRICED, not the source that quoted the
price — every row this module fetches is already entity_id=primary_
entity_id by construction (see the price_rows query in _fetch_
candidates), so entity_id can never discriminate "your own storefront"
from "a third-party retailer" on its own, despite how that column name
reads. The real signal is merchant_name/merchant_slug/attribution_
status, compared against the PRIMARY ENTITY'S OWN name/slug/aliases —
see _attribution(), the ONE place this comparison is made. Every
caller (selection ranking, clause copy, span painting) goes through
_attribution()/_accuracy() — never re-derive attribution_status or
net_price_accuracy logic ad hoc elsewhere in this file.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy import text

import soa_shared.config as config
from soa_shared.scan_dimensions import PURCHASE_INTENT_STAGES

_STRENGTH_RANK = {"Primary": 3, "Positive": 2, "Neutral": 1, "Negative": 0}


def _decode_json_field(value, default):
    """JSON columns come back already-decoded via psycopg2; defensively
    handle a driver (or SQLite test) that returns the raw string instead
    — same idiom as cycle_scoring.py::decode_json_field, duplicated here
    (not imported) to avoid a cycle_scoring <-> transcript_pick import
    cycle."""
    if isinstance(value, str):
        return json.loads(value) if value else default
    return value if value is not None else default


def _bare_domain(url) -> Optional[str]:
    """Same idiom as cycle_scoring.py::_bare_domain, duplicated here for
    the same reason as _decode_json_field above."""
    if not url:
        return None
    hostname = urlparse(url if '://' in url else f'https://{url}').hostname
    if not hostname:
        return None
    return hostname[4:] if hostname.startswith('www.') else hostname


@dataclass
class _PrimaryIdentity:
    name: str
    slug: str
    aliases: List[str]
    domain: Optional[str]


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
    price_observations: list = field(default_factory=list)   # primary's own, this run — see _fetch_candidates
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
            deal_types=tuple(_decode_json_field(deal_types, [])) if coded else (),
        )
    if not candidates:
        return []

    # entity_id = the brand being priced — always primary_entity_id here
    # (see module docstring). Ground truth is joined per-OBSERVATION via
    # price_observation_id (scoring_grain='observation'), not per-run —
    # a run can carry both a self-attributed and a third-party price
    # observation, and each needs its own accuracy verdict. A price
    # observation with no matching scored row (or measurement_status !=
    # 'measured') naturally comes back with all ground-truth fields
    # NULL, which _accuracy() reads as NOT_MEASURED — no separate
    # coverage flag invented on either row.
    price_rows = conn.execute(text("""
        SELECT po.run_id, po.id, po.stated_price, po.claimed_net_price, po.merchant_name,
               po.merchant_slug, po.attribution_status,
               s.ground_truth_true_cost, s.net_price_accuracy, s.measurement_status,
               s.ground_truth_applied_deals
        FROM soa_price_observations po
        JOIN soa_runs r ON r.id = po.run_id
        LEFT JOIN soa_incentive_scores s
          ON s.price_observation_id = po.id AND s.scoring_grain = 'observation' AND s.status = 'scored'
        WHERE r.cycle_id = :cid AND po.entity_id = :pid
        ORDER BY po.id
    """), {"cid": cycle_id, "pid": primary_entity_id}).fetchall()
    for (run_id, obs_id, stated_price, claimed_net_price, merchant_name, merchant_slug,
         attribution_status, ground_truth_true_cost, net_price_accuracy, measurement_status,
         ground_truth_applied_deals) in price_rows:
        if run_id in candidates:
            candidates[run_id].price_observations.append({
                "id": obs_id, "stated_price": stated_price, "claimed_net_price": claimed_net_price,
                "merchant_name": merchant_name, "merchant_slug": merchant_slug,
                "attribution_status": attribution_status,
                "ground_truth_true_cost": ground_truth_true_cost,
                "net_price_accuracy": net_price_accuracy,
                "measurement_status": measurement_status,
                "ground_truth_applied_deals": _decode_json_field(ground_truth_applied_deals, []),
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
            candidates[run_id].competitor_deals.append({"name": name, "deal_types": tuple(_decode_json_field(deal_types, []))})

    return list(candidates.values())


# ─── The shared attribution/accuracy rule (used by selection, clause ──────
# ─── copy, AND span painting — never re-derived ad hoc elsewhere) ─────────

def _attribution(obs: dict, primary: _PrimaryIdentity) -> str:
    """
    'self' | 'third_party' | 'unattributed' — the ONLY place attribution
    is computed. NOT obs['entity_id'] (see module docstring): the real
    signal is whether the NAMED SOURCE (merchant_name/merchant_slug) is
    the primary brand's own storefront or a genuinely different one.

    'brand_self_reference' is the coder's own flag for "merchant_name
    resolved to the entity's own slug" and always counts as self. A
    merchant_name/slug that textually matches the primary's own name,
    slug, or an alias ALSO counts as self — this is the case the
    coder's merchant-mapping heuristic misses for a DTC brand with no
    listed retailer/merchant record (e.g. "Allbirds" quoted as its own
    source comes back attribution_status='unmapped', not 'brand_self_
    reference', because Allbirds isn't in the merchant registry —
    that's the actual bug this function fixes).
    """
    merchant_name = (obs.get("merchant_name") or "").strip()
    merchant_slug = (obs.get("merchant_slug") or "").strip()
    if not merchant_name and not merchant_slug:
        return "unattributed"
    if obs.get("attribution_status") == "brand_self_reference":
        return "self"
    self_tokens = {t.lower() for t in ([primary.name, primary.slug] + list(primary.aliases or [])) if t}
    if merchant_name.lower() in self_tokens or merchant_slug.lower() in self_tokens:
        return "self"
    return "third_party"


def _accuracy(obs: dict) -> str:
    """
    'accurate' | 'inaccurate' | 'not_measured' — the ONLY place accuracy
    is computed. NOT_MEASURED whenever Deal Engine has no ground truth
    for this observation (measurement_status != 'measured', including
    NULL/'unmeasured') — a missing comparison is NEVER treated as wrong.
    SQLite hands boolean columns back as plain 0/1 ints, not Python
    bool, so this reads net_price_accuracy by truthiness, not identity.
    """
    if obs.get("measurement_status") != "measured":
        return "not_measured"
    value = obs.get("net_price_accuracy")
    if value is None:
        return "not_measured"
    return "accurate" if value else "inaccurate"


def _obs_is_leak(obs: dict, primary: _PrimaryIdentity) -> bool:
    """A value leak on a price observation is exactly: third-party
    attribution, OR an inaccurate price (self-attributed and inaccurate
    is the sharpest DTC leak — see _dominant_leak below)."""
    return _attribution(obs, primary) == "third_party" or _accuracy(obs) == "inaccurate"


def _obs_delta(obs: dict) -> float:
    truth = obs.get("ground_truth_true_cost")
    stated = obs.get("stated_price")
    if not truth or stated is None:
        return 0.0
    return abs(stated - truth) / truth


def _fmt_price(value: Optional[float]) -> str:
    return f"${value:,.2f}" if value is not None else "an unstated price"


def _offer_label(applied_deals) -> Optional[str]:
    """No invented specifics (H1): only returns a label when the Deal
    Engine's own applied-deals payload names one; None otherwise."""
    if not applied_deals:
        return None
    d = applied_deals[0]
    if isinstance(d, dict):
        return d.get("name") or d.get("type") or d.get("description")
    if isinstance(d, str):
        return d
    return None


def _has_leak(candidate: _RunCandidate, primary: _PrimaryIdentity) -> bool:
    if any(_obs_is_leak(o, primary) for o in candidate.price_observations):
        return True
    if candidate.competitor_deals and not candidate.deal_cited:
        return True
    return False


def _leak_severity_key(c: _RunCandidate, primary: _PrimaryIdentity):
    """Ascending sort key (used with min()): SELF+INACCURATE ranks
    above THIRD_PARTY (by ground-truth delta if measured, else by
    count) above a competitor-deal-only leak — see module docstring's
    rule. Stable tiebreak by run_id last, always."""
    self_inaccurate = [o for o in candidate_price_leaks(c, primary) if o[0] == "self_inaccurate"]
    third_party = [o for o in candidate_price_leaks(c, primary) if o[0] in ("third_party_inaccurate", "third_party_accurate")]
    if self_inaccurate:
        delta = max(_obs_delta(o[1]) for o in self_inaccurate)
        return (0, -delta, 0, c.run_id)
    if third_party:
        measured = [o for o in third_party if o[0] == "third_party_inaccurate"]
        delta = max(_obs_delta(o[1]) for o in measured) if measured else 0.0
        return (1, -delta, -len(third_party), c.run_id)
    return (2, 0.0, -len(c.competitor_deals), c.run_id)


def candidate_price_leaks(c: _RunCandidate, primary: _PrimaryIdentity):
    """[(kind, obs), ...] for every leaking price observation on this
    candidate, kind in {self_inaccurate, third_party_inaccurate,
    third_party_accurate, unattributed_inaccurate}. Shared by ranking
    and by clause building so they can never disagree on what counts.

    third_party_accurate also covers third-party + NOT_MEASURED: its
    clause wording ("not your storefront's price") never asserts the
    number is right or wrong, so it's honest for both — only third_
    party_inaccurate, backed by a confirmed measured mismatch, may say
    "and it's wrong"."""
    out = []
    for o in c.price_observations:
        attr = _attribution(o, primary)
        acc = _accuracy(o)
        if attr == "self" and acc == "inaccurate":
            out.append(("self_inaccurate", o))
        elif attr == "third_party" and acc == "inaccurate":
            out.append(("third_party_inaccurate", o))
        elif attr == "third_party":
            out.append(("third_party_accurate", o))
        elif attr == "unattributed" and acc == "inaccurate":
            out.append(("unattributed_inaccurate", o))
    return out


def _dominant_leak(c: _RunCandidate, primary: _PrimaryIdentity) -> Tuple[Optional[str], Optional[dict]]:
    """The single price observation whose clause should lead LEAKED,
    in the same severity order as _leak_severity_key: self_inaccurate >
    third_party_inaccurate > third_party_accurate > unattributed_
    inaccurate > none."""
    leaks = candidate_price_leaks(c, primary)
    for wanted in ("self_inaccurate", "third_party_inaccurate", "third_party_accurate", "unattributed_inaccurate"):
        matches = [o for k, o in leaks if k == wanted]
        if matches:
            picked = max(matches, key=_obs_delta) if wanted != "third_party_accurate" else matches[0]
            return wanted, picked
    return None, None


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


def _find_price_span(text_: str, target_price: Optional[float], kind: str) -> Optional[dict]:
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
            return {"start": m.start(), "end": m.end(), "kind": kind}
    return None


_KIND_PRIORITY = {"brand": 0}


def _merge_spans(spans: List[dict]) -> List[dict]:
    """Non-overlapping, deterministic, brand-wins-on-overlap: brand
    spans are placed first (any overlapping merchant/price span loses,
    regardless of start position), then the rest are placed in start
    order, longest match wins a tie."""
    def overlaps(a, b):
        return a["start"] < b["end"] and b["start"] < a["end"]

    ordered = sorted(spans, key=lambda s: (_KIND_PRIORITY.get(s["kind"], 1), s["start"], -(s["end"] - s["start"])))
    merged: List[dict] = []
    for s in ordered:
        if not any(overlaps(s, m) for m in merged):
            merged.append(s)
    return sorted(merged, key=lambda s: s["start"])


def _locate_spans(candidate: _RunCandidate, primary: _PrimaryIdentity) -> List[dict]:
    """
    Amber 'value_claim' (off-site) underlines ONLY a THIRD_PARTY
    observation's merchant name/price — never the primary brand's own
    name as an off-site source. A SELF-attributed but INACCURATE price
    gets its own 'stale_price' kind (same amber dotted style, different
    legend/label — the sharpest DTC leak, not an off-site one). Brand
    (blue) spans always win any overlap — see _merge_spans.
    """
    text_ = candidate.response_text
    spans: List[dict] = []
    for name in [primary.name] + list(primary.aliases or []):
        spans.extend(_find_all(text_, name, "brand"))

    for obs in candidate.price_observations:
        attr = _attribution(obs, primary)
        acc = _accuracy(obs)
        if attr == "third_party":
            merchant_span = _find_all(text_, obs.get("merchant_name") or "", "value_claim")
            if merchant_span:
                spans.append(merchant_span[0])
            price_span = _find_price_span(text_, obs.get("stated_price") or obs.get("claimed_net_price"), "value_claim")
            if price_span:
                spans.append(price_span)
        elif attr == "self" and acc == "inaccurate":
            price_span = _find_price_span(text_, obs.get("stated_price") or obs.get("claimed_net_price"), "stale_price")
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

def _attribution_credit_clause(c: _RunCandidate, primary: _PrimaryIdentity) -> Optional[str]:
    """RIGHT-box credit for an accurate price — only for an observation
    that is NOT also a leak (an accurate observation never is, since
    leak == third_party-attribution OR inaccurate — so this can never
    credit and complain about the same number in LEAKED)."""
    for o in c.price_observations:
        if _attribution(o, primary) == "self" and _accuracy(o) == "accurate":
            return "and quoted your price correctly, from your own site."
    for o in c.price_observations:
        if _attribution(o, primary) in ("third_party", "unattributed") and _accuracy(o) == "accurate":
            return "and the price it quoted matches yours."
    return None


def _price_leak_clause(kind: str, obs: dict, primary: _PrimaryIdentity, page_price_encoded: Optional[bool]) -> str:
    stated = _fmt_price(obs.get("stated_price"))
    net = _fmt_price(obs.get("ground_truth_true_cost"))
    merchant = obs.get("merchant_name") or "a retailer"
    domain = primary.domain or "your site"
    offer = _offer_label(obs.get("ground_truth_applied_deals"))

    if kind == "self_inaccurate":
        offer_bit = f", with the {offer}" if offer else ""
        return f"The agent quoted your price as {stated} — your net right now is {net}{offer_bit}."
    if kind == "third_party_inaccurate":
        return f"The agent quoted {stated} from {merchant}, not from {domain} — and it's wrong: your net is {net}."
    if kind == "third_party_accurate":
        base = f"The price came from {merchant}, not from {domain} — the agent didn't use your storefront's price."
        if page_price_encoded is False:
            base += " Nothing on your page encoded a price it could quote."
        elif page_price_encoded is True:
            base += " Even though your page encodes one."
        return base
    if kind == "unattributed_inaccurate":
        return f"The agent quoted {stated} without saying where it came from — your net is {net}."
    return ""


def _not_measured_note(obs: dict) -> str:
    merchant = obs.get("merchant_name")
    if merchant:
        return f"Price attributed to {merchant}; accuracy not verifiable — Deal Engine has no ground truth for {merchant}."
    return "Price accuracy not verifiable — Deal Engine has no ground truth for this observation."


def _narrative_value_gap(
    c: _RunCandidate, primary: _PrimaryIdentity, share_pct, share_rank_label,
    total_queries: int, page_price_encoded: Optional[bool],
) -> Tuple[str, str]:
    share_bit = ""
    if share_pct is not None and share_rank_label:
        share_bit = f" — this conversation is one of the runs behind your {share_pct:.1f}% share and {share_rank_label} rank"
    strength_bit = " unprompted" if c.strength == "Primary" else ""
    credit = _attribution_credit_clause(c, primary)
    right = f"You're named{strength_bit}{share_bit}" + (f", {credit}" if credit else ".")

    leaked_parts = []
    kind, obs = _dominant_leak(c, primary)
    price_leak_fired = kind is not None
    if kind:
        leaked_parts.append(_price_leak_clause(kind, obs, primary, page_price_encoded))
    if c.competitor_deals and not c.deal_cited:
        leaked_parts.append(f"{c.competitor_deals[0]['name']}'s deal was quoted while yours went unmentioned.")
    if not leaked_parts:
        leaked_parts.append("Your value wasn't cited accurately here.")
    if price_leak_fired:
        leaked_parts.append(f"This is the Price Truth gap measured across all {total_queries} answers.")
    leaked = " ".join(leaked_parts)
    return right, leaked


def _narrative_mentioned_no_leak(c: _RunCandidate, primary: _PrimaryIdentity) -> Tuple[str, str]:
    right_parts = ["You're mentioned in this answer"]
    credit = _attribution_credit_clause(c, primary)
    if credit:
        right = f"{right_parts[0]}, {credit}"
    else:
        right = right_parts[0] + "."

    leaked_parts = []
    if c.strength in ("Neutral", "Negative") or (c.position and c.position > 1):
        leaked_parts.append("you're buried, not the lead pick")
    not_measured_obs = [o for o in c.price_observations if _accuracy(o) == "not_measured"]
    if not c.price_observations and not c.deal_cited:
        leaked_parts.append("no offer or price was cited at all — a citability gap, not a wrong number")
    leaked = ("Here, " + "; ".join(leaked_parts) + ".") if leaked_parts else "Nothing leaked in this run — it's a clean mention."
    if not_measured_obs and not leaked_parts:
        leaked = _not_measured_note(not_measured_obs[0])
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
    candidate: _RunCandidate, primary: _PrimaryIdentity, *, tier: int, case: str,
    query_index: int, total_queries: int,
    share_pct: Optional[float], share_rank_label: Optional[str],
    page_price_encoded: Optional[bool],
) -> dict:
    if case == "value_gap":
        right, leaked = _narrative_value_gap(candidate, primary, share_pct, share_rank_label, total_queries, page_price_encoded)
    elif case == "mentioned_no_leak":
        right, leaked = _narrative_mentioned_no_leak(candidate, primary)
    elif case == "not_mentioned":
        right, leaked = _narrative_not_mentioned(candidate)
    else:
        right, leaked = _narrative_uncoded(candidate)

    spans = _locate_spans(candidate, primary)
    payload = {
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
        "facts": {
            "mentioned": candidate.mentioned,
            "position": candidate.position,
            "strength": candidate.strength,
            "deal_cited": candidate.deal_cited,
            "deal_types": list(candidate.deal_types),
            "price_observations": [
                {
                    **o,
                    "attribution": _attribution(o, primary),
                    "accuracy": _accuracy(o),
                }
                for o in candidate.price_observations
            ],
            "competitor_deals": candidate.competitor_deals,
        },
    }
    # TRANSCRIPT_NARRATIVE_ENABLED gate (see soa_shared/config.py): the
    # clause-building functions above always run — every unit test that
    # calls them directly exercises the same logic regardless of the
    # flag — only the payload EXPOSURE of right/leaked is gated. Omitted
    # entirely when off, never empty strings, so the frontend's presence
    # check (`right != null`) is unambiguous.
    if config.TRANSCRIPT_NARRATIVE_ENABLED:
        payload["right"] = right
        payload["leaked"] = leaked
    return payload


def select_transcript(
    conn, cycle_id: int, primary_entity_id: int,
    *, share_pct: Optional[float] = None, share_rank_label: Optional[str] = None,
    page_price_encoded: Optional[bool] = None,
) -> Optional[dict]:
    """
    Deterministic 5-tier cascade over the cycle's own successful,
    non-empty-response runs, biased to always surface something:

      1. Purchase-intent stage · primary mentioned · a value leak
         present — ranked by leak severity: SELF+INACCURATE (the
         sharpest DTC leak — your own name, wrong number) first, then
         THIRD_PARTY (by ground-truth delta if measured, else by
         count), then a competitor-deal-only leak last.
      2. Any stage · primary mentioned · a leak present (same ranking).
      3. Any stage · primary mentioned, no leak — ranked by weakest
         visibility signal (lowest strength, then most buried position).
         A SELF+ACCURATE price observation is the GOOD case and never
         places a run in tiers 1/2 on its own.
      4. Primary NOT mentioned (a real coded 'no', not an uncoded run)
         — ranked by purchase-intent stage first, then most
         competitors mentioned.
      5. Any successful run at all, coded or not — the earliest one.

    None only when the cycle has zero successful, non-empty-response
    runs. share_pct/share_rank_label/page_price_encoded are the
    caller's own already-computed numbers (never recomputed here), so
    the generated copy can never drift from the scores.
    """
    candidates = _fetch_candidates(conn, cycle_id, primary_entity_id)
    if not candidates:
        return None

    entity_row = conn.execute(text("""
        SELECT name, slug, aliases, website_url FROM soa_entities WHERE id = :pid
    """), {"pid": primary_entity_id}).fetchone()
    primary = _PrimaryIdentity(
        name=entity_row[0] if entity_row else "",
        slug=entity_row[1] if entity_row else "",
        aliases=_decode_json_field(entity_row[2], []) if entity_row else [],
        domain=_bare_domain(entity_row[3]) if entity_row else None,
    )

    total_queries = conn.execute(text("""
        SELECT COUNT(DISTINCT query_id) FROM soa_runs WHERE cycle_id = :cid AND status = 'success'
    """), {"cid": cycle_id}).scalar() or 0
    query_index_rows = conn.execute(text("""
        SELECT DISTINCT query_id FROM soa_runs WHERE cycle_id = :cid AND status = 'success' ORDER BY query_id
    """), {"cid": cycle_id}).fetchall()
    query_index_by_id = {row[0]: i + 1 for i, row in enumerate(query_index_rows)}

    def pick(candidate: _RunCandidate, tier: int, case: str) -> dict:
        return _build_payload(
            candidate, primary, tier=tier, case=case,
            query_index=query_index_by_id.get(candidate.query_id, 1), total_queries=total_queries,
            share_pct=share_pct, share_rank_label=share_rank_label,
            page_price_encoded=page_price_encoded,
        )

    tier1 = [c for c in candidates if c.coded and c.mentioned and c.stage in PURCHASE_INTENT_STAGES and _has_leak(c, primary)]
    if tier1:
        return pick(min(tier1, key=lambda c: _leak_severity_key(c, primary)), 1, "value_gap")

    tier2 = [c for c in candidates if c.coded and c.mentioned and _has_leak(c, primary)]
    if tier2:
        return pick(min(tier2, key=lambda c: _leak_severity_key(c, primary)), 2, "value_gap")

    tier3 = [c for c in candidates if c.coded and c.mentioned]
    if tier3:
        return pick(min(tier3, key=_visibility_weakness_key), 3, "mentioned_no_leak")

    tier4 = [c for c in candidates if c.coded and not c.mentioned]
    if tier4:
        return pick(min(tier4, key=_absence_key), 4, "not_mentioned")

    return pick(min(candidates, key=lambda c: c.run_id), 5, "uncoded")
