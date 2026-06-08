"""
Abstract base class for all SoA platform runners.

The public interface is run(), which subclasses must NOT override.
Subclasses implement _call_api() only.

Guarantees enforced here (not delegatable to subclasses):
  - Session isolation: every call is a single user message, no history
  - Retry: up to 3 attempts on transient errors (429, timeout, connection)
  - No retry on 401 / 400 — return error immediately
  - Timeout: asyncio.wait_for cancels after timeout_seconds
  - Latency: measured on every call regardless of outcome
  - Logging: structured INFO on every call, ERROR on failure
"""
import asyncio
import logging
import time
from abc import ABC, abstractmethod

import anthropic
from openai import APIConnectionError, APIStatusError, APITimeoutError

from runners.platform_response import PlatformResponse

logger = logging.getLogger(__name__)

# Retry delays in seconds for attempts 1 and 2 (attempt 3 gives up)
_RETRY_DELAYS = [5, 15]

# Fallback retry delays for 429 errors when no Retry-After header is present
_RATE_LIMIT_RETRY_DELAYS = [10, 30]

# HTTP status codes that are non-retriable
_NON_RETRIABLE_STATUS = {400, 401, 403}


def _is_retriable(exc: Exception) -> bool:
    if isinstance(exc, APIStatusError):
        return exc.status_code not in _NON_RETRIABLE_STATUS
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code not in _NON_RETRIABLE_STATUS
    return isinstance(exc, (
        APIConnectionError, APITimeoutError, asyncio.TimeoutError,
        anthropic.APIConnectionError, anthropic.APITimeoutError,
    ))


def _wait_seconds_for(exc: Exception, attempt: int) -> float:
    """
    Return how many seconds to sleep before the next retry attempt.

    For 429 rate-limit errors, reads the Retry-After header (Anthropic
    responses include it) and adds a 1-second buffer.  Falls back to
    _RATE_LIMIT_RETRY_DELAYS if the header is absent or unparseable.
    All other retriable errors use the standard _RETRY_DELAYS schedule.
    """
    is_rate_limit = (
        isinstance(exc, anthropic.RateLimitError)
        or (isinstance(exc, anthropic.APIStatusError) and exc.status_code == 429)
        or (isinstance(exc, APIStatusError) and exc.status_code == 429)
    )

    if is_rate_limit:
        retry_after: str | None = None
        try:
            retry_after = exc.response.headers.get("retry-after")  # type: ignore[attr-defined]
        except AttributeError:
            pass

        if retry_after is not None:
            try:
                wait = float(retry_after) + 1.0
                logger.warning(
                    "Rate-limited (429) — Retry-After=%s, waiting %.1fs before retry %d",
                    retry_after, wait, attempt + 1,
                )
                return wait
            except (ValueError, TypeError):
                pass

        # No usable header — fall back to fixed delays
        delay = _RATE_LIMIT_RETRY_DELAYS[attempt - 1] if attempt <= len(_RATE_LIMIT_RETRY_DELAYS) else 30
        logger.warning(
            "Rate-limited (429) — no Retry-After header, waiting %ds before retry %d",
            delay, attempt + 1,
        )
        return float(delay)

    # Standard retriable error (connection reset, server timeout, etc.)
    return float(_RETRY_DELAYS[attempt - 1] if attempt <= len(_RETRY_DELAYS) else 15)


class BasePlatformRunner(ABC):

    def __init__(
        self,
        model: str,
        timeout_seconds: int = 30,
    ):
        self.model = model
        self.timeout_seconds = timeout_seconds

    @property
    @abstractmethod
    def platform(self) -> str:
        """Platform identifier: chatgpt | perplexity | gemini."""

    @abstractmethod
    async def _call_api(self, query_text: str) -> PlatformResponse:
        """
        Make one API call and return a PlatformResponse.
        Do NOT catch exceptions here — let them propagate to run().
        Do NOT include system prompt or conversation history.
        """

    async def run(self, query_text: str) -> PlatformResponse:
        """
        Public entry point. Wraps _call_api with retry, timeout, and
        latency measurement. Never raises — always returns a PlatformResponse.
        """
        preview = query_text[:60].replace("\n", " ")

        for attempt in range(1, 4):  # attempts 1, 2, 3
            t0 = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    self._call_api(query_text),
                    timeout=self.timeout_seconds,
                )
                latency_ms = int((time.monotonic() - t0) * 1000)
                response.latency_ms = latency_ms

                logger.info(
                    "[%s/%s] attempt=%d query='%s...' latency=%dms status=%s",
                    self.platform, self.model, attempt, preview,
                    latency_ms, response.status,
                )

                # Warn (DEBUG) if the run consumed >80% of the timeout budget
                budget_ms = self.timeout_seconds * 1000
                if latency_ms > budget_ms * 0.8:
                    logger.debug(
                        "[%s/%s] Slow run: %dms (%.0f%% of %ds timeout) "
                        "search_triggered=%s",
                        self.platform, self.model,
                        latency_ms,
                        latency_ms / budget_ms * 100,
                        self.timeout_seconds,
                        getattr(response, "search_triggered", None),
                    )

                return response

            except asyncio.TimeoutError:
                latency_ms = int((time.monotonic() - t0) * 1000)
                msg = (
                    f"Timeout after {self.timeout_seconds}s "
                    f"(attempt {attempt}/3)"
                )
                will_retry = attempt < 3
                logger.error(
                    "[%s/%s] attempt=%d TIMEOUT after %ds query='%s...' "
                    "latency=%dms — %s",
                    self.platform, self.model, attempt,
                    self.timeout_seconds, preview, latency_ms,
                    "will retry" if will_retry else "giving up",
                )
                if attempt == 3:
                    return PlatformResponse(
                        response_text="",
                        prompt_tokens=0,
                        completion_tokens=0,
                        latency_ms=latency_ms,
                        platform=self.platform,
                        model=self.model,
                        error=msg,
                        status="timeout",
                    )
                await asyncio.sleep(_RETRY_DELAYS[attempt - 1])

            except Exception as exc:
                latency_ms = int((time.monotonic() - t0) * 1000)
                logger.error(
                    "[%s/%s] attempt=%d ERROR query='%s...' latency=%dms: %s",
                    self.platform, self.model, attempt, preview,
                    latency_ms, exc, exc_info=True,
                )

                if not _is_retriable(exc) or attempt == 3:
                    if attempt == 3:
                        logger.error(
                            "[%s/%s] Exhausted all 3 retries for query='%s...'",
                            self.platform, self.model, preview,
                        )
                    return PlatformResponse(
                        response_text="",
                        prompt_tokens=0,
                        completion_tokens=0,
                        latency_ms=latency_ms,
                        platform=self.platform,
                        model=self.model,
                        error=str(exc),
                        status="error",
                    )
                await asyncio.sleep(_wait_seconds_for(exc, attempt))

        # Should never reach here, but satisfy type checker
        return PlatformResponse(
            response_text="",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=0,
            platform=self.platform,
            model=self.model,
            error="Exhausted retries",
            status="error",
        )
