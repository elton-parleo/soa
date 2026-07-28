"""
membership_probe.py — Stage 16 (Part 4): a single, out-of-band OpenAI
call asking whether a brand runs a paid membership or loyalty program.

probe_membership() never raises (rule 4's never-throw philosophy, same
discipline as generation/competitor_generator.py::generate_competitors)
— one attempt, one retry, and any failure on both returns
{"result": "unknown", "raw_evidence": None} so the caller
(worker.py::process_lite_requests) always has a well-defined value to
persist.

This probe is METRICALLY INVISIBLE: it is not one of the 12 tracked
queries, is never inserted into soa_queries/soa_runs, and is excluded
from every mention/citation denominator. Its only purpose is feeding
P3's member_value applicability decision
(apps/api/app/services/lite_pillars.py::member_value_applicable),
combined with crawl evidence — never used alone as a scored signal.
"""
import json
import logging
from typing import Optional

from openai import OpenAI

log = logging.getLogger(__name__)

MEMBERSHIP_PROBE_MODEL = "gpt-5.4-mini"
VALID_RESULTS = ("yes", "no", "unknown")


def _build_probe_prompt(brand_name: str, store_url: Optional[str]) -> str:
    context = f" Its store is at {store_url}." if store_url else ""
    return f"""Does the brand "{brand_name}" offer a PAID membership or loyalty rewards program (a paid subscription tier, or a free-to-join loyalty/rewards program with member-only pricing, points, or perks)?{context}

Respond with ONLY a JSON object: {{"result": "yes" | "no" | "unknown", "evidence": string or null}}.
"result": "yes" if you are confident the brand has such a program, "no" if you are confident it does not, "unknown" if you are not sure.
"evidence": a short (one sentence) reason for your answer, or null.
No markdown, no explanation outside the JSON object."""


def _parse_result(content: str) -> dict:
    content = (content or '').strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[1]
        content = content.rsplit('```', 1)[0]

    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed)}")

    result = (parsed.get('result') or '').strip().lower()
    if result not in VALID_RESULTS:
        raise ValueError(f"Unrecognized result value: {result!r}")

    evidence = parsed.get('evidence')
    evidence = evidence.strip() if isinstance(evidence, str) and evidence.strip() else None

    return {"result": result, "raw_evidence": evidence}


def _call_once(brand_name: str, store_url: Optional[str], api_key: str) -> dict:
    client = OpenAI(api_key=api_key)
    prompt = _build_probe_prompt(brand_name, store_url)
    response = client.chat.completions.create(
        model=MEMBERSHIP_PROBE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    content = response.choices[0].message.content
    return _parse_result(content)


def probe_membership(brand_name: str, api_key: str, *, store_url: Optional[str] = None) -> dict:
    """Returns {"result": "yes"|"no"|"unknown", "raw_evidence": str|None}.
    Never raises — both attempts failing (bad JSON, API error, timeout,
    anything) falls back to {"result": "unknown", "raw_evidence": None}."""
    for attempt in (1, 2):
        try:
            return _call_once(brand_name, store_url, api_key)
        except Exception:
            log.warning(
                f"[lite] membership probe attempt {attempt} failed for '{brand_name}'", exc_info=True
            )
    return {"result": "unknown", "raw_evidence": None}
