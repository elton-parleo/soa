"""
exposure_reasons.py — Part 4: a table-driven library of "why you're
leaking value" reasons, evaluated against this run's own measured
facts. Replaces the report's three static, run-agnostic exposure
causes (the old hardcoded CAUSE_WEIGHTS in ExposureSection.jsx) with
up to 3 reasons actually true of THIS run, ranked by severity.

Honest-state rule (4b): a reason's trigger only ever reads a MEASURED
sub-lens — an na/blocked/not_evaluated dimension produces no reason,
the same "never claim what we didn't measure" discipline as everywhere
else in this pipeline. severity is missed points (a sub-lens's own
weight minus what it earned) — directly comparable across pillars
since every sub-lens's weight already shares one rubric (soa_shared.
scan_dimensions.PILLAR_WEIGHTS).

Dollar amounts are deliberately NOT computed here: the frontend's
revenue/AI-share sliders are live and client-side, so only each
selected reason's impact_weight (its severity's share of the selected
group's total) is serialized — the report multiplies that share
against whatever modeled exposure total the current slider state
produces, exactly like the pre-Part-4 static CAUSE_WEIGHTS did.
"""
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

MAX_SELECTED_REASONS = 3


def _measured(dim: Optional[dict]) -> bool:
    return bool(dim) and not dim.get("na") and not dim.get("blocked")


def _missing(dim: Optional[dict]) -> float:
    """Missed points on a {earned, max, na, blocked} sub-lens dict — 0
    when absent/na/blocked (never a negative or fabricated number)."""
    if not _measured(dim):
        return 0.0
    return max(0.0, (dim.get("max") or 0.0) - (dim.get("earned") or 0.0))


@dataclass(frozen=True)
class ExposureReason:
    id: str
    trigger: Callable[[dict], bool]
    severity: Callable[[dict], float]
    copy: Callable[[dict], str]


# ─── trigger/copy per reason (severity is uniformly "missed points" —
# see _reason built from a ctx key below) ─────────────────────────────────

def _pt_said_trigger(ctx):
    return _measured(ctx["price_truth_said"]) and _missing(ctx["price_truth_said"]) > 0


def _pt_said_copy(ctx):
    said = ctx["price_truth_said"]
    return f"Your price was quoted in {said['cited']} of {said['total']} answers that named you."


def _pt_seen_trigger(ctx):
    return _measured(ctx["price_truth_seen"]) and _missing(ctx["price_truth_seen"]) > 0


def _pt_seen_copy(ctx):
    seen = ctx["price_truth_seen"]
    return f"Your price checks earn {seen['earned']:.0f} of {seen['max']:.0f} points on your own site."


def _mv_seen_trigger(ctx):
    return ctx["member_value_applicable"] and _measured(ctx["member_value_seen"]) and _missing(ctx["member_value_seen"]) > 0


def _mv_seen_copy(ctx):
    seen = ctx["member_value_seen"]
    return f"Your member pricing earns {seen['earned']:.0f} of {seen['max']:.0f} points on your own site."


def _mv_said_trigger(ctx):
    return ctx["member_value_applicable"] and _measured(ctx["member_value_said"]) and _missing(ctx["member_value_said"]) > 0


def _mv_said_copy(ctx):
    said = ctx["member_value_said"]
    return f"Member value was credited in {said['cited']} of {said['total']} purchase-intent answers."


def _dc_seen_trigger(ctx):
    return _measured(ctx["deal_citability_seen"]) and _missing(ctx["deal_citability_seen"]) > 0


def _dc_seen_copy(ctx):
    seen = ctx["deal_citability_seen"]
    return f"Your deals earn {seen['earned']:.0f} of {seen['max']:.0f} points on your own site."


def _dc_said_trigger(ctx):
    return _measured(ctx["deal_citability_said"]) and _missing(ctx["deal_citability_said"]) > 0


def _dc_said_copy(ctx):
    said = ctx["deal_citability_said"]
    return f"Deals were cited in {said['cited']} of {said['total']} purchase-intent answers."


def _vp_trigger(ctx):
    return _measured(ctx["value_protocols"]) and _missing(ctx["value_protocols"]) > 0


def _vp_copy(ctx):
    vp = ctx["value_protocols"]
    return f"Value Protocols earns {vp['earned']:.0f} of {vp['max']:.0f} points — no checkout capability declared."


def _catalog_trigger(ctx):
    return _measured(ctx["catalog_context"]) and _missing(ctx["catalog_context"]) > 0


def _catalog_copy(ctx):
    dim = ctx["catalog_context"]
    return f"Catalog & Context earns {dim['earned']:.0f} of {dim['max']:.0f} points — much of your catalog isn't readable to agents."


def _agent_access_trigger(ctx):
    return _measured(ctx["agent_access"]) and _missing(ctx["agent_access"]) > 0


def _agent_access_copy(ctx):
    dim = ctx["agent_access"]
    return f"Agent Access earns {dim['earned']:.0f} of {dim['max']:.0f} points — agents can't fully reach your site."


def _visibility_trigger(ctx):
    vis = ctx["visibility"]
    return vis.get("total_mentions", 0) > 0 and _missing(vis) > 0


def _visibility_copy(ctx):
    vis = ctx["visibility"]
    return f"You hold {vis['som_pct']:.0f}% share of brand mentions across {vis['total_mentions']} tracked mentions."


def _severity(ctx_key: str) -> Callable[[dict], float]:
    return lambda ctx: _missing(ctx[ctx_key])


REASONS: List[ExposureReason] = [
    ExposureReason("pt_said", _pt_said_trigger, _severity("price_truth_said"), _pt_said_copy),
    ExposureReason("pt_seen", _pt_seen_trigger, _severity("price_truth_seen"), _pt_seen_copy),
    ExposureReason("mv_seen", _mv_seen_trigger, _severity("member_value_seen"), _mv_seen_copy),
    ExposureReason("mv_said", _mv_said_trigger, _severity("member_value_said"), _mv_said_copy),
    ExposureReason("dc_seen", _dc_seen_trigger, _severity("deal_citability_seen"), _dc_seen_copy),
    ExposureReason("dc_said", _dc_said_trigger, _severity("deal_citability_said"), _dc_said_copy),
    ExposureReason("value_protocols", _vp_trigger, _severity("value_protocols"), _vp_copy),
    ExposureReason("catalog_context", _catalog_trigger, _severity("catalog_context"), _catalog_copy),
    ExposureReason("agent_access", _agent_access_trigger, _severity("agent_access"), _agent_access_copy),
    ExposureReason("visibility", _visibility_trigger, _severity("visibility"), _visibility_copy),
]


def select_exposure_reasons(ctx: Dict) -> List[Dict]:
    """
    4b: evaluate every reason's trigger against ctx, rank the ones that
    fire by severity (highest first, deterministic tiebreak by id), and
    return the top MAX_SELECTED_REASONS — {id, text, impact_weight,
    severity_rank}. Fewer than 3 reasons trigger -> fewer than 3
    returned, never padded or repeated (4b's honest-state rule already
    keeps an na/blocked dimension's reason from triggering at all;
    this only ranks what's real). Nothing triggers -> [].

    4c: impact_weight is each selected reason's severity share of the
    SELECTED group's total severity (renormalized among the top 3, not
    the full library) — the report multiplies this share against
    whatever modeled exposure total the visitor's current revenue/
    AI-share sliders produce, live, client-side.
    """
    triggered = [(r, r.severity(ctx)) for r in REASONS if r.trigger(ctx)]
    triggered = [(r, s) for r, s in triggered if s > 0]
    triggered.sort(key=lambda pair: (-pair[1], pair[0].id))
    selected = triggered[:MAX_SELECTED_REASONS]

    weights = _proportional_weights([s for _, s in selected])
    return [
        {"id": r.id, "text": r.copy(ctx), "impact_weight": w, "severity_rank": i + 1}
        for i, ((r, _s), w) in enumerate(zip(selected, weights))
    ]


_WEIGHT_PRECISION = 10_000  # 4 decimal places


def _proportional_weights(severities: List[float]) -> List[float]:
    """4c: severities/sum(severities), rounded to 4dp with the leftover
    remainder assigned to the largest share — so weights always sum to
    exactly 1.0 rather than drifting from independent per-reason
    rounding (which would otherwise compound into the dollar split the
    frontend renders against the live exposure total)."""
    total = sum(severities)
    if not total:
        return [0.0] * len(severities)

    raw = [s / total for s in severities]
    scaled = [round(w * _WEIGHT_PRECISION) for w in raw]
    drift = _WEIGHT_PRECISION - sum(scaled)
    if scaled:
        largest_idx = max(range(len(raw)), key=lambda i: raw[i])
        scaled[largest_idx] += drift
    return [s / _WEIGHT_PRECISION for s in scaled]
