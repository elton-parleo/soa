"""
Google Gemini runner for SoA measurement.

Uses the google-genai SDK (NOT google-generativeai which is deprecated).
Install: pip install google-genai

The Gemini API approximates but does not perfectly replicate Google AI
Overviews behavior. Responses reflect the Gemini model's training and
retrieval, not the exact AI Overview product shown in Google Search.
Always set platform='gemini' — never 'google_aio'.

Async execution uses google-genai's native async support:
    await client.aio.models.generate_content(...)

Token extraction uses Gemini-specific metadata fields:
    response.usage_metadata.prompt_token_count   → prompt_tokens
    response.usage_metadata.candidates_token_count → completion_tokens

Temperature is intentionally not set. Google recommends keeping Gemini
at its default temperature of 1.0. Setting it below 1.0 can cause
degraded performance or looping on reasoning tasks.

503 UNAVAILABLE handling:
    Transient server capacity errors are retried with exponential backoff
    and jitter (10s, 20s, 40s + 0–5s jitter per attempt). After
    SOA_GEMINI_503_MAX_RETRIES consecutive 503s on the primary model,
    one final attempt is made on SOA_GEMINI_FALLBACK_MODEL. The actual
    model used is recorded in PlatformResponse.model so soa_runs accurately
    reflects which model produced each response.
"""
import asyncio
import logging
import random
import time

from google import genai
from google.genai import types
from google.genai.errors import ServerError

import soa_shared.config as config
from soa_shared.config import SOA_GEMINI_FALLBACK_MODEL, SOA_GEMINI_TIMEOUT_SECONDS
from runners.base_runner import BasePlatformRunner
from runners.platform_response import PlatformResponse

logger = logging.getLogger(__name__)


class GeminiRunner(BasePlatformRunner):

    platform = "gemini"

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        timeout_seconds: int = SOA_GEMINI_TIMEOUT_SECONDS,
    ):
        if not config.GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to /soa/.env."
            )
        super().__init__(model=model, timeout_seconds=timeout_seconds)
        self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.fallback_model: str = SOA_GEMINI_FALLBACK_MODEL

        # 503 statistics — read by RunOrchestrator after run_cycle() completes
        self.gemini_503_count: int = 0
        self.gemini_503_fallback_successes: int = 0

    # ------------------------------------------------------------------
    # 503 detection
    # ------------------------------------------------------------------

    def _is_503(self, exc: Exception) -> bool:
        """
        Returns True if exc is a transient Gemini 503 UNAVAILABLE error.

        Primary check: google.genai.errors.ServerError with code == 503.
        The SDK routes all 5xx responses to ServerError and all 4xx to
        ClientError, so authentication (401), quota (429), and invalid
        request (400) errors are in a different class and are never matched.

        String fallback: catches any exception whose string representation
        contains "503" and "UNAVAILABLE" or "high demand" — for forward
        compatibility if the SDK exception hierarchy changes.
        """
        # Primary: SDK-typed check
        if isinstance(exc, ServerError):
            if exc.code == 503:
                return True
            if getattr(exc, "status", "") == "UNAVAILABLE":
                return True

        # Fallback: string-based check (does not match 429/400/401)
        msg = str(exc)
        return "503" in msg and ("UNAVAILABLE" in msg or "high demand" in msg)

    # ------------------------------------------------------------------
    # API call helpers
    # ------------------------------------------------------------------

    async def _call_api_for_model(
        self, query_text: str, model: str
    ) -> PlatformResponse:
        """
        Make one Gemini API call using the specified model name.
        Records the actual model used in PlatformResponse.model so
        soa_runs is accurate when the fallback model fires.
        """
        response = await self._client.aio.models.generate_content(
            model=model,
            contents=query_text,
            config=types.GenerateContentConfig(
                # temperature intentionally omitted
                # Gemini default of 1.0 is recommended
            ),
        )
        meta = response.usage_metadata
        return PlatformResponse(
            response_text=response.text or "",
            prompt_tokens=meta.prompt_token_count if meta else 0,
            completion_tokens=meta.candidates_token_count if meta else 0,
            latency_ms=0,  # set by caller
            platform=self.platform,
            model=model,   # actual model, may differ from self.model on fallback
            status="success",
        )

    async def _call_api(self, query_text: str) -> PlatformResponse:
        """Satisfies the BasePlatformRunner abstract method."""
        return await self._call_api_for_model(query_text, self.model)

    # ------------------------------------------------------------------
    # run() override — 503 retry with exponential backoff + fallback model
    # ------------------------------------------------------------------

    async def run(self, query_text: str) -> PlatformResponse:
        """
        Overrides BasePlatformRunner.run() to add Gemini-specific 503
        UNAVAILABLE retry logic.

        Retry sequence:
          attempt 1 → 503 → wait 10s + jitter → retry
          attempt 2 → 503 → wait 20s + jitter → retry
          attempt 3 → 503 → wait 40s + jitter → switch to fallback model
          attempt 4 (fallback) → 503 → return error

        For non-503 exceptions (timeout, auth, connection, other server
        errors) encountered on the first API call, the run is immediately
        delegated to super().run() which applies the base retry logic.
        If a non-503 exception occurs on a later attempt (after one or more
        503s), the run is abandoned and returned as an error — the
        pipeline's resume capability will retry the query on the next cycle.
        """
        preview = query_text[:60].replace("\n", " ")
        max_retries = config.SOA_GEMINI_503_MAX_RETRIES  # default 3

        for attempt in range(1, max_retries + 2):  # 1 … max_retries, then fallback
            use_model = self.fallback_model if attempt > max_retries else self.model

            if attempt == max_retries + 1:
                # Switching to fallback after max_retries consecutive 503s
                logger.warning(
                    "[gemini] %d consecutive 503 errors on %s. "
                    "Switching to fallback %s for this query.",
                    max_retries, self.model, self.fallback_model,
                )

            t0 = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    self._call_api_for_model(query_text, use_model),
                    timeout=self.timeout_seconds,
                )
                latency_ms = int((time.monotonic() - t0) * 1000)
                response.latency_ms = latency_ms

                if use_model == self.fallback_model and attempt > 1:
                    logger.warning(
                        "[gemini] Fallback %s succeeded after primary model 503s.",
                        self.fallback_model,
                    )
                    self.gemini_503_fallback_successes += 1

                logger.info(
                    "[gemini/%s] attempt=%d query='%s...' latency=%dms status=success",
                    use_model, attempt, preview, latency_ms,
                )
                return response

            except asyncio.TimeoutError:
                # Timeout is not a 503 — on the first attempt, delegate to base
                # class which will apply its own timeout retry logic. On later
                # attempts (after 503s have already occurred), return as error.
                latency_ms = int((time.monotonic() - t0) * 1000)
                if attempt == 1:
                    return await super().run(query_text)
                logger.error(
                    "[gemini/%s] TIMEOUT after %ds on attempt %d "
                    "(after %d 503 retries) query='%s...'",
                    use_model, self.timeout_seconds, attempt,
                    attempt - 1, preview,
                )
                return PlatformResponse(
                    response_text="",
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=latency_ms,
                    platform=self.platform,
                    model=use_model,
                    error=f"Timeout after {self.timeout_seconds}s (attempt {attempt})",
                    status="timeout",
                )

            except Exception as exc:
                latency_ms = int((time.monotonic() - t0) * 1000)

                if not self._is_503(exc):
                    # Not a 503 — on the first attempt, delegate to base class
                    # for generic retry. On later attempts (post-503), return error.
                    if attempt == 1:
                        return await super().run(query_text)
                    logger.error(
                        "[gemini/%s] Non-503 error on attempt %d "
                        "(after %d 503 retries) query='%s...': %s",
                        use_model, attempt, attempt - 1, preview, exc,
                    )
                    return PlatformResponse(
                        response_text="",
                        prompt_tokens=0,
                        completion_tokens=0,
                        latency_ms=latency_ms,
                        platform=self.platform,
                        model=use_model,
                        error=str(exc),
                        status="error",
                    )

                # It's a 503 UNAVAILABLE error
                self.gemini_503_count += 1

                if attempt > max_retries:
                    # Fallback model also returned 503 — give up
                    logger.error(
                        "[gemini] All retries exhausted including fallback %s. "
                        "Recording as error and continuing.",
                        self.fallback_model,
                    )
                    return PlatformResponse(
                        response_text="",
                        prompt_tokens=0,
                        completion_tokens=0,
                        latency_ms=latency_ms,
                        platform=self.platform,
                        model=use_model,
                        error=(
                            f"503 UNAVAILABLE after {attempt} attempts "
                            f"including fallback model"
                        ),
                        status="error",
                    )

                # Exponential backoff with jitter before next retry
                base_wait = 10 * (2 ** (attempt - 1))  # 10, 20, 40
                jitter = random.uniform(0, 5)
                wait = base_wait + jitter

                logger.warning(
                    "[gemini/%s] 503 UNAVAILABLE (attempt %d/%d) — server capacity. "
                    "Waiting %.1fs before retry.",
                    use_model, attempt, max_retries, wait,
                )

                await asyncio.sleep(wait)

        # Should never reach here — satisfies type checker
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
