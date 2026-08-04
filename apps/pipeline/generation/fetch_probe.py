"""
fetch_probe.py — Part 2 (P1/P2): a single, out-of-band OpenAI call asking
ChatGPT to actually open one sampled product URL and report what it finds.

Unlike generation/membership_probe.py and generation/revenue_probe.py
(plain chat.completions calls — they only need the model's general
knowledge), this probe needs the model to actually fetch a URL, so it
uses the SAME client setup as the LITE_QUERY_COUNT tracked queries —
the Responses API with the web_search tool (runners/openai_runner.py) —
not the simpler pattern the other two probes use.

probe_fetch() never raises (rule 4's never-throw philosophy). Unlike
the other two probes, this is ONE call only, no retry: a malformed
response becomes outcome="inconclusive" directly (P2) rather than being
retried, since a retry would double the already-real cost of a
browsing-capable call for no better odds of a cleaner answer.

This probe is METRICALLY INVISIBLE: it is not one of the LITE_QUERY_COUNT
tracked queries, is never inserted into soa_queries/soa_runs, and is
excluded from every mention/citation denominator. Its only purpose is
feeding Price Truth evidence and the blocked/degraded banner (P4) —
apps/api/app/services/lite_pillars.py and apps/api/app/routers/
public_lite.py — never a scored signal itself.
"""
import json
import logging
from typing import Optional

from openai import OpenAI

log = logging.getLogger(__name__)

# Matches runners/openai_runner.py's default model for the tracked
# queries — this probe needs the same real-browsing capability
# (web_search tool), unlike membership_probe/revenue_probe's plain
# chat-completion call.
FETCH_PROBE_MODEL = "gpt-5.5"

OUTCOME_QUOTED_PRICE = "quoted_price"
OUTCOME_OPENED_NO_PRICE = "opened_no_price"
OUTCOME_COULD_NOT_ACCESS = "could_not_access"
OUTCOME_INCONCLUSIVE = "inconclusive"

# P5: scaffolded OFF. Enabling a Gemini twin of this probe later needs a
# deliberate stamp/copy review first — the report's stamp line ("24
# queries · ChatGPT only") and every P4 evidence sentence are written
# assuming a single, ChatGPT-only fetch probe; adding a second platform
# changes what "ChatGPT itself opened..." can honestly claim.
FETCH_PROBE_GEMINI = False


def _build_probe_prompt(url: str) -> str:
    return f"""Open this exact product page and report what you find: {url}

Respond with ONLY a JSON object: {{"accessed": true or false, "price_found": true or false, "price": string or null, "quote": string or null, "note": string}}.
"accessed": true if you were able to open and read the page, false if you could not (blocked, error, timeout, or anything else that stopped you).
"price_found": true if you found a price on the page, false otherwise.
"price": the exact price you found, as a short string (e.g. "$29.99"), or null.
"quote": a short exact quote from the page showing the price, or explaining why you couldn't access it, or null.
"note": one short sentence describing what happened.
No markdown, no explanation outside the JSON object."""


def _derive_outcome(parsed: dict) -> str:
    if not parsed.get("accessed"):
        return OUTCOME_COULD_NOT_ACCESS
    if parsed.get("price_found") and parsed.get("price"):
        return OUTCOME_QUOTED_PRICE
    return OUTCOME_OPENED_NO_PRICE


def _parse_result(content: str, url: str, kind: Optional[str]) -> dict:
    content = (content or "").strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0]

    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed)}")

    price = parsed.get("price")
    price = price.strip() if isinstance(price, str) and price.strip() else None
    quote = parsed.get("quote")
    quote = quote.strip() if isinstance(quote, str) and quote.strip() else None
    note = parsed.get("note")
    note = note.strip() if isinstance(note, str) and note.strip() else None

    return {
        "outcome": _derive_outcome(parsed),
        "url": url, "kind": kind, "price": price, "quote": quote, "note": note,
    }


def _inconclusive_result(url: str, kind: Optional[str]) -> dict:
    return {"outcome": OUTCOME_INCONCLUSIVE, "url": url, "kind": kind, "price": None, "quote": None, "note": None}


def _call_once(url: str, api_key: str, kind: Optional[str]) -> dict:
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=FETCH_PROBE_MODEL,
        tools=[{"type": "web_search"}],
        input=[{"role": "user", "content": _build_probe_prompt(url)}],
    )
    return _parse_result(response.output_text or "", url, kind)


def probe_fetch(url: str, api_key: str, kind: Optional[str] = None) -> dict:
    """
    Returns {"outcome": "quoted_price"|"opened_no_price"|
    "could_not_access"|"inconclusive", "url": str, "kind": str|None,
    "price": str|None, "quote": str|None, "note": str|None}. Never
    raises, never retried (P1: "Always exactly one call") — any failure
    (API error, timeout, malformed JSON, unexpected shape) falls back to
    an inconclusive result for this url.

    N4 (not-measurable consistency stage): kind is "product_page" |
    "store_root", supplied verbatim by the caller (engine.py's
    _choose_fetch_probe_url already knows which rung of the ladder
    picked this URL) — stored, never re-derived here, so every rendered
    probe line can honestly name what was actually opened instead of a
    raw URL, and a homepage price is never mistaken for product-page
    price evidence.
    """
    try:
        return _call_once(url, api_key, kind)
    except Exception:
        log.warning(f"[lite] fetch probe failed for {url!r}", exc_info=True)
        return _inconclusive_result(url, kind)
