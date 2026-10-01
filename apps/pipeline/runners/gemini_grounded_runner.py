"""
Grounded Gemini runner for SoA measurement — platform "gemini_grounded".

This is the only Gemini surface cycles run: a cycle that lists "gemini" is
run as "gemini_grounded" (see PLATFORM_ALIASES in run_orchestrator.py).
The base Gemini API (gemini_runner.py) has no live retrieval, so it answers
from training data alone — stale program names, stale prices, no sources.
This runner enables the google_search grounding tool so the model can
ground its answer in live search results, the way AI Overviews / AI Mode
do.

Subclasses GeminiRunner for its 503 UNAVAILABLE retry/backoff and fallback
model; only the API call differs (the grounding tool, and the sources it
returns).

Grounding metadata: response.candidates[0].grounding_metadata.grounding_chunks
contains the search-result sources the model actually grounded on. Each
chunk's web.uri is extracted into PlatformResponse.retrieved_sources.
"""
import logging

from google.genai import types

from runners.gemini_runner import GeminiRunner
from runners.platform_response import PlatformResponse

logger = logging.getLogger(__name__)


class GeminiGroundedRunner(GeminiRunner):

    platform = "gemini_grounded"

    async def _call_api_for_model(
        self, query_text: str, model: str
    ) -> PlatformResponse:
        response = await self._client.aio.models.generate_content(
            model=model,
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
            latency_ms=0,  # set by caller
            platform=self.platform,
            model=model,   # actual model, may differ from self.model on fallback
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
