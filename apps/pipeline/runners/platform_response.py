from dataclasses import dataclass
from typing import List, Optional


@dataclass
class PlatformResponse:
    """Standardized output of every platform runner call."""

    response_text: str
    """Full raw LLM response, stored verbatim in soa_runs.raw_response."""

    prompt_tokens: int
    """Input token count. 0 when the platform does not return it."""

    completion_tokens: int
    """Output token count. Stored in soa_runs.response_tokens. 0 when unavailable."""

    latency_ms: int
    """Wall-clock time from request send to response received, in milliseconds."""

    platform: str
    """One of: chatgpt, perplexity, gemini, claude, gemini_grounded. Must match soa_runs CHECK constraint."""

    model: str
    """Exact model string used, e.g. gpt-5.5, llama-3.1-sonar-large-128k-online."""

    error: Optional[str] = None
    """None on success. Error message string on any failure."""

    status: str = "success"
    """success | error | timeout. Must match soa_runs.status CHECK constraint."""

    search_triggered: Optional[bool] = None
    """True/False for OpenAI Responses API runs. None for platforms that do not expose this signal."""

    retrieved_sources: Optional[List[str]] = None
    """
    Grounding/search source URLs, where the platform exposes them — OpenAI
    web_search result items, Gemini grounding metadata, Perplexity citations.
    None when the platform does not expose sources or none were used.
    Seeds source attribution (M26).
    """
