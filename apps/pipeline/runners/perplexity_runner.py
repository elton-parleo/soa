"""
Perplexity runner for SoA measurement.

Perplexity's API is OpenAI-compatible. Uses the AsyncOpenAI client
pointed at Perplexity's base URL with an online (web-retrieval) model.

Live web retrieval is intentional — it replicates the experience a
real user has when querying Perplexity. Response variance from live
retrieval is expected and must NOT be reduced or normalized; the SoA
methodology depends on natural output variance across runs.

2I-6: the model is SOA_PERPLEXITY_MODEL (soa_shared/config.py, default
sonar-pro), not a constant: the hard-coded llama-3.1-sonar-large-128k-online
was retired and every run answered 400 invalid_model. Perplexity ended
support for Sonar Chat Completions on 2026-09-27; synchronous requests like
these keep working, reformulated as Agent API requests (docs.perplexity.ai,
"Migrate from Sonar", read 2026-10-17).

Temperature is supported by Perplexity and defaults to 0.8, providing
moderate response variance across repeated runs of the same query.

Token extraction uses the same field paths as OpenAI:
    response.usage.prompt_tokens / completion_tokens
"""
from typing import Optional

from openai import AsyncOpenAI

import soa_shared.config as config
from soa_shared.config import SOA_PERPLEXITY_TIMEOUT_SECONDS
from runners import grounding
from runners.base_runner import BasePlatformRunner
from runners.platform_response import PlatformResponse

_BASE_URL = "https://api.perplexity.ai"


class PerplexityRunner(BasePlatformRunner):

    platform = "perplexity"

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.8,
        timeout_seconds: int = SOA_PERPLEXITY_TIMEOUT_SECONDS,
    ):
        if not config.PERPLEXITY_API_KEY:
            raise RuntimeError(
                "PERPLEXITY_API_KEY is not set. Add it to /soa/.env."
            )
        super().__init__(model=model or config.SOA_PERPLEXITY_MODEL, timeout_seconds=timeout_seconds)
        self.temperature = temperature
        self._client = AsyncOpenAI(
            api_key=config.PERPLEXITY_API_KEY,
            base_url=_BASE_URL,
            max_retries=0,  # BasePlatformRunner.run() owns retries
        )

    async def _call_api(self, query_text: str) -> PlatformResponse:
        response = await self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[{"role": "user", "content": query_text}],
        )
        usage = response.usage
        # Perplexity's OpenAI-compatible response includes a top-level
        # "citations" list of source URLs when retrieval was used. Not part
        # of the openai SDK's typed model, so it only appears via the raw
        # parsed JSON — read tolerantly and never raise if absent.
        retrieved_sources = list(getattr(response, "citations", None) or []) or None

        return PlatformResponse(
            response_text=response.choices[0].message.content or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            latency_ms=0,  # set by base run()
            platform=self.platform,
            model=self.model,
            status="success",
            retrieved_sources=retrieved_sources,
            grounding=grounding.from_perplexity(
                response, response.choices[0].message.content or ""),
        )
