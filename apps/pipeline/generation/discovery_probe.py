"""
generation/discovery_probe.py — Part 3 (rescue session): a single,
out-of-band OpenAI call asking ChatGPT for candidate product-detail-page
URLs on a store's own domain. This is the LAST-RESORT discovery tier
(scan/discovery.py::_probe_llm_discovery), used ONLY when every
deterministic tier — sitemap, homepage harvest, collection hop, platform-
endpoint probes — already found nothing.

Mirrors generation/fetch_probe.py's contract exactly: never raises, one
call, no retry (a malformed response degrades to an empty result rather
than being retried), strict JSON, no prose. Same Responses-API + web_search
client setup as fetch_probe.py, since finding real URLs benefits from
actual browsing rather than the model guessing at plausible-looking paths
from training data alone.

The model NEVER supplies a scored fact — only a pointer. Every URL it
returns is independently verified by discovery.py itself (host match,
robots check, our own fetch, product-page-shape check) before it is ever
treated as a real candidate — see discovery.py's _probe_llm_discovery.
"""
import json
import logging

from openai import OpenAI

log = logging.getLogger(__name__)

# Matches fetch_probe.py's model choice — same browsing-capable model,
# same client setup (Responses API + web_search tool).
DISCOVERY_PROBE_MODEL = "gpt-5.5"
MAX_URLS_REQUESTED = 4


def _build_prompt(homepage_url: str) -> str:
    return f"""This is the homepage of an online store: {homepage_url}

Return up to {MAX_URLS_REQUESTED} URLs of specific product detail pages on this exact domain — real pages for individual products, not category pages, search results, or marketplace/third-party listings.

Respond with ONLY a JSON object: {{"urls": [string, ...]}}. No prose, no explanation, no markdown."""


def _call_once(homepage_url: str, api_key: str) -> dict:
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=DISCOVERY_PROBE_MODEL,
        tools=[{"type": "web_search"}],
        input=[{"role": "user", "content": _build_prompt(homepage_url)}],
    )
    content = (response.output_text or "").strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0]

    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed)}")

    urls = parsed.get("urls")
    if not isinstance(urls, list):
        raise ValueError("Expected 'urls' to be a list")

    return {"urls": [u.strip() for u in urls if isinstance(u, str) and u.strip()][:MAX_URLS_REQUESTED]}


def probe_discover_urls(homepage_url: str, api_key: str) -> dict:
    """
    Returns {"urls": [str, ...]} — always a list, possibly empty. Never
    raises: any failure (missing/invalid api_key, API error, timeout,
    malformed JSON, unexpected shape) returns {"urls": []}, so the
    caller's tier falls through exactly as if it had never run.
    """
    if not api_key:
        return {"urls": []}
    try:
        return _call_once(homepage_url, api_key)
    except Exception:
        log.warning(f"[discovery] LLM discovery probe failed for {homepage_url!r}", exc_info=True)
        return {"urls": []}
