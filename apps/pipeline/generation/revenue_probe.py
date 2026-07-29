"""
revenue_probe.py — Part 5 (R1): a single, out-of-band OpenAI call
estimating a brand's annual revenue, feeding the exposure calculator's
default seed. Same pattern as generation/membership_probe.py.

probe_revenue() never raises (rule 4's never-throw philosophy) — one
attempt, one retry, and any failure on both returns
{"annual_revenue_usd": None, "basis": None, "quote": None} so the caller
(worker.py::process_lite_requests) always has a well-defined value to
persist.

This probe is METRICALLY INVISIBLE: it is not one of the 12 tracked
queries, is never inserted into soa_queries/soa_runs, and is excluded
from every mention/citation denominator. Its only purpose is seeding
the exposure calculator's default revenue (apps/api/app/routers/
public_lite.py) — it never feeds a score.
"""
import json
import logging
from typing import Optional

from openai import OpenAI

log = logging.getLogger(__name__)

REVENUE_PROBE_MODEL = "gpt-5.4-mini"

# Outside this range, the estimate is treated as unparseable — an LLM
# guess of $1 or $50 trillion is a refusal/hallucination, not a usable
# seed for a monthly-revenue slider.
MIN_PLAUSIBLE_REVENUE_USD = 100_000
MAX_PLAUSIBLE_REVENUE_USD = 100_000_000_000


def _build_probe_prompt(brand_name: str, store_url: Optional[str]) -> str:
    context = f" ({store_url})" if store_url else ""
    return f"""What is the estimated annual revenue of {brand_name}{context}?

Respond with ONLY a JSON object: {{"annual_revenue_usd": number or null, "basis": string or null}}.
"annual_revenue_usd": a single USD estimate (not a range), or null if you cannot estimate one.
"basis": one sentence explaining the basis for your estimate (e.g. company size, public filings, industry comparables), or null.
No markdown, no explanation outside the JSON object."""


def _parse_result(content: str) -> dict:
    content = (content or '').strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[1]
        content = content.rsplit('```', 1)[0]

    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed)}")

    revenue = parsed.get('annual_revenue_usd')
    if revenue is not None:
        revenue = float(revenue)
        if not (MIN_PLAUSIBLE_REVENUE_USD <= revenue <= MAX_PLAUSIBLE_REVENUE_USD):
            revenue = None

    basis = parsed.get('basis')
    basis = basis.strip() if isinstance(basis, str) and basis.strip() else None
    # basis is the model's one-sentence rationale; quote mirrors it
    # verbatim as a separate key so callers have an explicit audit-trail
    # field, same shape as membership_probe's raw_evidence convention —
    # revenue estimate is null'd above independently of this text
    # staying, so an absurd number can't stay silently unexplained.
    quote = basis

    return {"annual_revenue_usd": revenue, "basis": basis, "quote": quote}


def _call_once(brand_name: str, store_url: Optional[str], api_key: str) -> dict:
    client = OpenAI(api_key=api_key)
    prompt = _build_probe_prompt(brand_name, store_url)
    response = client.chat.completions.create(
        model=REVENUE_PROBE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    content = response.choices[0].message.content
    return _parse_result(content)


def probe_revenue(brand_name: str, api_key: str, *, store_url: Optional[str] = None) -> dict:
    """Returns {"annual_revenue_usd": float|None, "basis": str|None,
    "quote": str|None}. Never raises — both attempts failing (bad JSON,
    API error, timeout, anything) falls back to all-None."""
    for attempt in (1, 2):
        try:
            return _call_once(brand_name, store_url, api_key)
        except Exception:
            log.warning(
                f"[lite] revenue probe attempt {attempt} failed for '{brand_name}'", exc_info=True
            )
    return {"annual_revenue_usd": None, "basis": None, "quote": None}
