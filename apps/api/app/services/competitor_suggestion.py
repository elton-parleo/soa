"""
competitor_suggestion.py — Full Analysis coexistence, Phase 2: brand
competitor auto-suggestion for NewCycleFlow's step 1.

apps/api never imports apps/pipeline (see app/routers/public_lite.py's
module docstring — the two communicate only through Postgres), so this
cannot reuse apps/pipeline/generation/competitor_generator.py directly.
This is a minimal, self-contained duplicate with the SAME contract as
that module (same prompt, same never-throw one-retry behavior, same
dedupe/top-up rules) — same convention as app/services/
demo_request_email.py's duplication of apps/pipeline/email_sender.py.
Deliberately not promoted into soa_shared: unlike a DB model, an LLM
prompt isn't schema, and the two call sites (worker-side lite
processing vs. this synchronous authed endpoint) have different
failure/latency tolerances.

LOCKSTEP: the prompt builder and generate_competitors' signature must
change in BOTH files together, or not at all; a parity test asserts the
two prompts are byte-identical for identical inputs
(tests/test_competitor_prompt_parity.py). Only the differences already
there are allowed to differ: the module docstrings and the log prefix.

site_context (competitor grounding): accepted here for parity, but
nothing on this side populates it yet — the homepage fetcher that
renders the block lives in apps/pipeline and this app cannot import it.
See app/routers/full_analysis.py::suggest_competitors.
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


def _build_competitor_prompt(
    brand_name: str,
    store_url: Optional[str],
    category_hint: Optional[str],
    site_context: Optional[str] = None,
) -> str:
    """site_context is an already-rendered prompt block (a plain string,
    never a dataclass — see this module's docstring on why the two copies
    of this file share a contract but no imports): a few short labelled
    lines of what the brand's own homepage says about itself, produced
    worker-side by apps/pipeline/scan/site_context.py::SiteContext::
    as_prompt_block. It is the authoritative category signal when
    present, because a brand NAME alone is often ambiguous and the model
    would otherwise guess the category from it."""
    context_lines = []
    if store_url:
        context_lines.append(f"Its store is at {store_url}.")
    if category_hint:
        context_lines.append(f"Its product category is: {category_hint}.")
    context = " ".join(context_lines)

    grounding = ""
    if site_context:
        grounding = (
            f"\n\nWhat the brand's own website says about itself (fetched from its homepage):\n"
            f"{site_context}\n"
            f'Treat this as the authoritative description of what "{brand_name}" sells. '
            f"If the brand name alone could belong to several categories, use the website, "
            f"not the name, to decide."
        )

    return f"""You are identifying direct consumer-brand competitors for "{brand_name}" for a brand comparison study. {context}{grounding}

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
    site_context: Optional[str] = None,
) -> list:
    client = OpenAI(api_key=api_key)
    prompt = _build_competitor_prompt(brand_name, store_url, category_hint, site_context)
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
    site_context: Optional[str] = None,
) -> list:
    """Returns up to 5 CompetitorCandidate rows, or [] if both the
    initial attempt and its one retry fail (bad JSON, API error, timeout,
    anything) — never raises. Same contract as apps/pipeline/generation/
    competitor_generator.py::generate_competitors."""
    for attempt in (1, 2):
        try:
            return _call_once(brand_name, store_url, category_hint, api_key, site_context)
        except Exception:
            log.warning(
                f"[full-analysis] competitor generation attempt {attempt} failed for '{brand_name}'", exc_info=True
            )
    return []


def select_competitors(manual_names: list, candidates: list, brand_name: str):
    """
    Merges manual_names (kept first, in full) with generated candidates,
    topping up to MAX_CANDIDATES total. Dedupe is case-insensitive across
    both sets and against brand_name. Same contract as apps/pipeline/
    generation/competitor_generator.py::select_competitors — see that
    module's docstring for the full rationale.

    Returns (final: list[{"name", "domain"}], source: str).
    """
    seen = {brand_name.strip().lower()}
    final = []

    for name in manual_names or []:
        name = (name or '').strip()
        key = name.lower()
        if not (MIN_NAME_LENGTH <= len(name) <= MAX_NAME_LENGTH) or key in seen:
            continue
        seen.add(key)
        final.append({"name": name, "domain": None})
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
        final.append({"name": name, "domain": candidate.domain})
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
