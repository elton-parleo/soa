"""
Grounded Gemini runner for SoA measurement — platform "gemini_grounded".

Separate from gemini_runner.py / platform "gemini" by design. The base
Gemini API (gemini_runner.py) does not replicate Google AI Mode/AI
Overviews — it's the weakest incentive surface in the study because it has
no live retrieval. This runner enables the google_search grounding tool so
the model can ground its answer in live search results, which is a much
closer proxy for a feed/search-discoverable shopping surface (the model
can surface time-bound incentives it finds via search, the way AI
Overviews / AI Mode do).

Uses the same google-genai SDK as gemini_runner.py. Intentionally does NOT
share gemini_runner's 503 retry/fallback override — that complexity is
specific to the existing "gemini" platform's operational history. This
runner uses the BasePlatformRunner's generic retry/timeout behavior.

Grounding metadata: response.candidates[0].grounding_metadata.grounding_chunks
contains the search-result sources the model actually grounded on. Each
chunk's web.uri is extracted into PlatformResponse.retrieved_sources.
"""
import logging

from google import genai
from google.genai import types

import soa_shared.config as config
from soa_shared.config import SOA_GEMINI_TIMEOUT_SECONDS
from runners.base_runner import BasePlatformRunner
from runners.platform_response import PlatformResponse

logger = logging.getLogger(__name__)


class GeminiGroundedRunner(BasePlatformRunner):

    platform = "gemini_grounded"

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

    async def _call_api(self, query_text: str) -> PlatformResponse:
        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=query_text,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                # temperature intentionally omitted — see gemini_runner.py
            ),
        )

        meta = response.usage_metadata
        retrieved_sources = self._extract_retrieved_sources(response)
        search_triggered = bool(retrieved_sources)

        return PlatformResponse(
            response_text=response.text or "",
            prompt_tokens=meta.prompt_token_count if meta else 0,
            completion_tokens=meta.candidates_token_count if meta else 0,
            latency_ms=0,  # set by base run()
            platform=self.platform,
            model=self.model,
            status="success",
            search_triggered=search_triggered,
            retrieved_sources=retrieved_sources or None,
        )

    @staticmethod
    def _extract_retrieved_sources(response) -> list[str]:
        """
        Pulls source URLs from grounding_metadata.grounding_chunks across
        all candidates. Tolerant of missing/partial metadata — grounding
        does not fire on every query.
        """
        urls: list[str] = []
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            grounding_metadata = getattr(candidate, "grounding_metadata", None)
            if grounding_metadata is None:
                continue
            chunks = getattr(grounding_metadata, "grounding_chunks", None) or []
            for chunk in chunks:
                web = getattr(chunk, "web", None)
                uri = getattr(web, "uri", None) if web else None
                if uri:
                    urls.append(uri)
        return urls
