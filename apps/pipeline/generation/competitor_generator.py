"""
Stage 13 (G1-G4): worker-side competitor auto-generation. Identifies up
to 5 direct consumer-brand competitors for a SoA Lite brand via one
OpenAI call, so the visitor no longer has to name rivals themselves.

generate_competitors() never raises — competitor identification is a
lookup that enriches the run, not something that may block or fail it
(rule 4's never-throw philosophy extended to this stage): one attempt,
one retry, and any failure on both returns [] so the caller proceeds
with whatever manual competitors (if any) were already on the request.

select_competitors() is the separate, pure post-validation step (never
trust the model alone): manual competitor_names are user intent and
always kept in full, topped up with generated candidates to
MAX_CANDIDATES total, deduped case-insensitively across both sets and
against the primary brand.
"""
import json
import logging
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

log = logging.getLogger(__name__)

COMPETITOR_MODEL = "gpt-5.4-mini"
MAX_CANDIDATES = 5
MIN_NAME_LENGTH = 2
MAX_NAME_LENGTH = 80


@dataclass
class CompetitorCandidate:
    name: str
    domain: Optional[str] = None


def _build_competitor_prompt(brand_name: str, store_url: Optional[str], category_hint: Optional[str]) -> str:
    context_lines = []
    if store_url:
        context_lines.append(f"Its store is at {store_url}.")
    if category_hint:
        context_lines.append(f"Its product category is: {category_hint}.")
    context = " ".join(context_lines)

    return f"""You are identifying direct consumer-brand competitors for "{brand_name}" for a brand comparison study. {context}

Selection rules — follow exactly:
- List brands a shopper would genuinely consider INSTEAD of "{brand_name}" — same product category, roughly the same price tier.
- ONLY consumer brands. Do NOT list retailers or marketplaces (e.g. Amazon, Target, Walmart) — those are sales channels, not competitors.
- Do NOT list "{brand_name}" itself, its parent company, sub-brands, or aliases of it.
- Do NOT list defunct or discontinued brands.
- Prefer widely recognizable names a general shopper would know.
- List up to 5 competitors. Fewer is fine if the category is thin — do not pad the list with weak or irrelevant matches.

Respond with ONLY a JSON array of up to 5 objects, each with keys:
name (string, required), domain (string or null — the brand's primary storefront domain if you're confident of it, otherwise null).
No markdown, no explanation, just the JSON array."""


def _parse_candidates(content: str) -> list:
    content = (content or '').strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[1]
        content = content.rsplit('```', 1)[0]

    parsed = json.loads(content)

    if isinstance(parsed, dict):
        for key in ('competitors', 'brands', 'items', 'data'):
            if key in parsed:
                parsed = parsed[key]
                break

    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON array, got {type(parsed)}")

    candidates = []
    for row in parsed:
        if not isinstance(row, dict):
            continue
        name = (row.get('name') or '').strip()
        if not name:
            continue
        domain = row.get('domain')
        domain = domain.strip() if isinstance(domain, str) and domain.strip() else None
        candidates.append(CompetitorCandidate(name=name, domain=domain))
    return candidates


def _call_once(
    brand_name: str,
    store_url: Optional[str],
    category_hint: Optional[str],
    api_key: str,
) -> list:
    client = OpenAI(api_key=api_key)
    prompt = _build_competitor_prompt(brand_name, store_url, category_hint)
    response = client.chat.completions.create(
        model=COMPETITOR_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    content = response.choices[0].message.content
    return _parse_candidates(content)


def generate_competitors(
    brand_name: str,
    api_key: str,
    *,
    store_url: Optional[str] = None,
    category_hint: Optional[str] = None,
) -> list:
    """Returns up to 5 CompetitorCandidate rows, or [] if both the
    initial attempt and its one retry fail (bad JSON, API error, timeout,
    anything) — never raises."""
    for attempt in (1, 2):
        try:
            return _call_once(brand_name, store_url, category_hint, api_key)
        except Exception:
            log.warning(
                f"[lite] competitor generation attempt {attempt} failed for '{brand_name}'", exc_info=True
            )
    return []


def select_competitors(manual_names: list, candidates: list, brand_name: str):
    """
    Merges manual_names (kept first, in full — explicit visitor intent)
    with generated candidates, topping up to MAX_CANDIDATES total.
    Dedupe is case-insensitive across both sets and against brand_name;
    empty or absurd-length names are dropped defensively.

    Returns (final_names: list[str], source: str) where source is:
      'mixed'     — manual names present AND at least one generated name added
      'manual'    — manual names present, nothing generated got added
      'generated' — no manual names, at least one generated name added
      'none'      — no manual names and nothing usable was generated
    """
    seen = {brand_name.strip().lower()}
    final = []

    for name in manual_names or []:
        name = (name or '').strip()
        key = name.lower()
        if not (MIN_NAME_LENGTH <= len(name) <= MAX_NAME_LENGTH) or key in seen:
            continue
        seen.add(key)
        final.append(name)
    manual_count = len(final)

    generated_added = 0
    for candidate in candidates or []:
        if len(final) >= MAX_CANDIDATES:
            break
        name = (candidate.name or '').strip()
        key = name.lower()
        if not (MIN_NAME_LENGTH <= len(name) <= MAX_NAME_LENGTH) or key in seen:
            continue
        seen.add(key)
        final.append(name)
        generated_added += 1

    if manual_count and generated_added:
        source = 'mixed'
    elif manual_count:
        source = 'manual'
    elif generated_added:
        source = 'generated'
    else:
        source = 'none'

    return final, source
