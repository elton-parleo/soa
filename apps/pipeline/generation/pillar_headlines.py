"""
pillar_headlines.py — Part 3: one OpenAI call per audit that turns the
run's own facts into three one-line pillar summaries (visibility,
accessibility, true_value), replacing the report's hardcoded section/
hero-card titles. Same never-raise, retry-once shape as generation/
revenue_probe.py.

Deliberately pipeline-local and leaner than apps/api's
build_pillars_payload: every fact handed to the model here is either a
raw metric already computed and stored by soa_metrics_results (soa_pct,
mention_rate, rsi_score), or a crawl dimension's own already-scored
earned/max (scan/scorer.py computes these once; nothing here
re-derives a different number). True Value facts are seen-side (site
markup) only — the said-side (agent-answer) signals need lite_
crosswalk.py's pass-2/sentinel-gating to report honestly, and that
machinery is apps/api-only. Rather than duplicate it (a second scorer
to keep in sync, real drift risk) or hand-roll an ungated approximation
(real risk of a silently wrong count in customer-facing copy), this
module simply never hands the model a said-side number or a pillar-
level True Value/Visibility point total — the prompt's own "no number
not in the facts" constraint (enforced by _validate_headline) makes
that omission a hard guarantee, not a convention.
"""
import json
import logging
import re
from typing import Optional

from openai import OpenAI

from soa_shared.scan_dimensions import DIMENSIONS_BY_CODE

log = logging.getLogger(__name__)

PILLAR_HEADLINE_MODEL = "gpt-5.4-mini"
MAX_HEADLINE_LEN = 90

PILLARS = ("visibility", "accessibility", "true_value")

# Registry defaults — the report's own hardcoded titles before this
# stage, kept as the fallback so a failed/malformed generation (or a
# pillar with nothing measured) still renders something true.
DEFAULT_HEADLINES = {
    "visibility": "Agents know who you are",
    "accessibility": "Agents can knock, but can't read much",
    "true_value": "Your value leaks before it reaches the answer",
}

NOT_MEASURABLE_HEADLINE = "Couldn't be measured this run"

SOURCE_GENERATED = "generated"
SOURCE_DEFAULT = "default"

_ACCESSIBILITY_CODES = ("agent_access", "catalog_context", "protocol_feed")
_TRUE_VALUE_SEEN_CODES = ("price_truth", "member_value", "deal_citability", "value_protocols")

_FEW_SHOT_EXAMPLES = (
    "Agents mention you, but your prices never make it into their answers.",
    "Half your catalog is unreadable to the agents evaluating it.",
    "Your price is right there in the code — nothing else about your value is.",
)

_PLACEHOLDER_PATTERNS = (
    re.compile(r'\blorem ipsum\b', re.I),
    re.compile(r'\btodo\b', re.I),
    re.compile(r'\btbd\b', re.I),
    re.compile(r'\[.*?\]'),           # bracketed placeholder tokens, e.g. "[brand]"
    re.compile(r'\{.*?\}'),           # unfilled template braces
    re.compile(r'—\s*—'),             # empty-interpolation double-dash artifact
    re.compile(r'at — '),
    re.compile(r'at %'),
    re.compile(r'example\.com', re.I),
)


def _dim_earned_max(dimensions_raw: dict, code: str) -> Optional[dict]:
    """A crawl dimension's already-scored {earned, max, evidence} —
    None when the dimension is missing, na, or blocked (nothing to
    honestly report)."""
    dim = dimensions_raw.get(code)
    if not isinstance(dim, dict):
        return None
    coverage = dim.get("coverage")
    if coverage in ("na", "blocked"):
        return None
    score = dim.get("score")
    max_ = dim.get("max")
    if score is None or max_ is None:
        return None
    name = DIMENSIONS_BY_CODE[code].name if code in DIMENSIONS_BY_CODE else code
    return {"name": name, "earned": score, "max": max_, "evidence": list(dim.get("evidence") or [])[:2]}


def build_pillar_facts(dimensions_raw: dict, visibility_metrics: dict) -> dict:
    """Assembles the lean, honest fact set for each pillar. Returns
    {"visibility": {...}|None, "accessibility": {...}|None,
    "true_value": {...}|None} — a pillar is None when nothing about it
    was measurable this run (empty facts -> caller skips the model
    entirely for that pillar and uses NOT_MEASURABLE_HEADLINE)."""
    dimensions_raw = dimensions_raw or {}

    vis = {k: v for k, v in (visibility_metrics or {}).items() if v is not None}
    visibility = vis or None

    acc_dims = [d for d in (_dim_earned_max(dimensions_raw, c) for c in _ACCESSIBILITY_CODES) if d]
    accessibility = None
    if acc_dims:
        accessibility = {
            "earned": round(sum(d["earned"] for d in acc_dims), 1),
            "max": round(sum(d["max"] for d in acc_dims), 1),
            "dimensions": acc_dims,
        }

    tv_dims = []
    for code in _TRUE_VALUE_SEEN_CODES:
        seen_code = f"{code}_seen" if code != "value_protocols" else "value_protocols_seen"
        d = _dim_earned_max(dimensions_raw, seen_code)
        if d:
            tv_dims.append(d)
    true_value = {"dimensions": tv_dims} if tv_dims else None

    return {"visibility": visibility, "accessibility": accessibility, "true_value": true_value}


def _facts_text_for_pillar(pillar: str, facts: dict) -> str:
    lines = []
    if pillar == "visibility":
        if facts.get("som_pct") is not None:
            lines.append(f"Share of brand mentions: {facts['som_pct']}%")
        if facts.get("mention_rate") is not None:
            lines.append(f"Mentioned in {facts['mention_rate']}% of shopper questions")
        if facts.get("rsi_score") is not None:
            lines.append(f"Recommendation strength score: {facts['rsi_score']}")
        if facts.get("rank_line"):
            lines.append(f"Rank: {facts['rank_line']}")
    else:
        for d in facts.get("dimensions", []):
            line = f"{d['name']}: {d['earned']}/{d['max']} points"
            if d.get("evidence"):
                line += " — " + "; ".join(d["evidence"])
            lines.append(line)
    return "\n".join(f"- {l}" for l in lines)


def _build_prompt(pillars_with_facts: dict) -> str:
    sections = []
    for pillar in PILLARS:
        if pillar not in pillars_with_facts:
            continue
        label = {"visibility": "VISIBILITY", "accessibility": "ACCESSIBILITY", "true_value": "TRUE VALUE"}[pillar]
        sections.append(f"{label} FACTS:\n{_facts_text_for_pillar(pillar, pillars_with_facts[pillar])}")

    keys = ", ".join(f'"{p}"' for p in pillars_with_facts)
    examples = "\n".join(f'- "{e}"' for e in _FEW_SHOT_EXAMPLES)

    return f"""You are writing one-line summaries for a report measuring how well an AI shopping agent (like ChatGPT) can see and evaluate a brand's store.

{chr(10).join(sections)}

Write ONE sentence per pillar listed above ({keys}), plain language, max {MAX_HEADLINE_LEN} characters each.
Rules:
- Use ONLY the numbers/facts given above — never invent, estimate, or infer a number not listed.
- Never claim anything about a dimension not mentioned in the facts above.
- No exclamation marks.
- No second person beyond "your" (no commands, no "you should").
Examples of the tone (facts differ every run, do not reuse these verbatim):
{examples}

Respond with ONLY a JSON object with exactly these keys: {{{keys}}} (each a string).
No markdown, no explanation outside the JSON object."""


def _parse_result(content: str) -> dict:
    content = (content or '').strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[1]
        content = content.rsplit('```', 1)[0]
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed)}")
    return parsed


def _looks_like_placeholder_or_encoded_claim(text: str) -> bool:
    return any(p.search(text) for p in _PLACEHOLDER_PATTERNS)


def _numbers_are_grounded(headline: str, facts_text: str) -> bool:
    for number in re.findall(r'\d+(?:\.\d+)?', headline):
        if number not in facts_text:
            return False
    return True


def _validate_headline(headline, facts_text: str) -> Optional[str]:
    """None on any violation — length, sentence count, exclamation
    marks, an ungrounded number, or placeholder/encoded-claim prose —
    so the caller falls back to the registry default for that pillar
    alone (3d: reject -> fallback, never a partial/guessed headline)."""
    if not isinstance(headline, str):
        return None
    headline = headline.strip()
    if not headline or len(headline) > MAX_HEADLINE_LEN:
        return None
    if '!' in headline:
        return None
    # one sentence: at most one terminal '.' and it must be the last char
    # (allows none, e.g. "Half your catalog is unreadable to agents").
    if headline.count('.') > 1:
        return None
    if '.' in headline and not headline.endswith('.'):
        return None
    if not _numbers_are_grounded(headline, facts_text):
        return None
    if _looks_like_placeholder_or_encoded_claim(headline):
        return None
    return headline


def _call_once(pillars_with_facts: dict, api_key: str) -> dict:
    client = OpenAI(api_key=api_key)
    prompt = _build_prompt(pillars_with_facts)
    response = client.chat.completions.create(
        model=PILLAR_HEADLINE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    return _parse_result(response.choices[0].message.content)


def generate_pillar_headlines(dimensions_raw: dict, visibility_metrics: dict, api_key: str) -> dict:
    """Returns {"visibility": {"headline": str, "source": "generated"|
    "default"}, "accessibility": {...}, "true_value": {...}}. Never
    raises: any pillar the model didn't honestly earn (nothing
    measured, API failure on both attempts, malformed JSON, or a
    validation rejection) falls back to that pillar's own registry
    default — the other pillars still get their generated line."""
    facts = build_pillar_facts(dimensions_raw, visibility_metrics)
    pillars_with_facts = {p: f for p, f in facts.items() if f}

    result = {
        p: {"headline": NOT_MEASURABLE_HEADLINE if not facts.get(p) else DEFAULT_HEADLINES[p], "source": SOURCE_DEFAULT}
        for p in PILLARS
    }

    if not pillars_with_facts:
        return result

    parsed = None
    for attempt in (1, 2):
        try:
            parsed = _call_once(pillars_with_facts, api_key)
            break
        except Exception:
            log.warning(f"[lite] pillar headline generation attempt {attempt} failed", exc_info=True)

    if not isinstance(parsed, dict):
        return result

    for pillar, pillar_facts in pillars_with_facts.items():
        facts_text = _facts_text_for_pillar(pillar, pillar_facts)
        validated = _validate_headline(parsed.get(pillar), facts_text)
        if validated:
            result[pillar] = {"headline": validated, "source": SOURCE_GENERATED}

    return result
