"""
OpenAI platform runner for SoA measurement.

Uses the Responses API with the web_search tool available but not forced.
The model decides whether to search on each query, emulating real consumer
ChatGPT behavior where search is triggered on approximately 34% of queries
based on the model's judgment of whether live web data would improve the
response.

Whether search was triggered is captured in the search_triggered field of
PlatformResponse and written to soa_runs.search_triggered, enabling analysis
of how Sephora's mention rate differs between search-backed and
non-search-backed responses.

Temperature is not passed to the Responses API. Sampling behavior is
controlled via reasoning.effort. The model's default sampling behavior is
used, consistent with the consumer ChatGPT experience.
"""
from openai import AsyncOpenAI

import soa_shared.config as config
from soa_shared.config import SOA_OPENAI_TIMEOUT_SECONDS
from runners.base_runner import BasePlatformRunner
from runners.platform_response import PlatformResponse


class OpenAIRunner(BasePlatformRunner):

    platform = "chatgpt"

    def __init__(
        self,
        model: str = "gpt-5.5",
        reasoning_effort: str = "medium",
        timeout_seconds: int = SOA_OPENAI_TIMEOUT_SECONDS,
    ):
        if not config.OPEN_AI_API_KEY:
            raise RuntimeError(
                "OPEN_AI_API_KEY is not set. Add it to /soa/.env."
            )
        super().__init__(model=model, timeout_seconds=timeout_seconds)
        self.reasoning_effort = reasoning_effort
        self._client = AsyncOpenAI(api_key=config.OPEN_AI_API_KEY)

    async def _call_api(self, query_text: str) -> PlatformResponse:
        response = await self._client.responses.create(
            model=self.model,
            tools=[{"type": "web_search"}],
            input=[{"role": "user", "content": query_text}],
            reasoning={"effort": self.reasoning_effort},
        )

        search_triggered = any(
            getattr(item, "type", None) == "web_search_call"
            for item in response.output
        )

        retrieved_sources = self._extract_retrieved_sources(response.output)

        usage = response.usage
        return PlatformResponse(
            response_text=response.output_text or "",
            prompt_tokens=usage.input_tokens if usage else 0,
            completion_tokens=usage.output_tokens if usage else 0,
            latency_ms=0,  # set by base run()
            platform=self.platform,
            model=self.model,
            status="success",
            search_triggered=search_triggered,
            retrieved_sources=retrieved_sources or None,
        )

    @staticmethod
    def _extract_retrieved_sources(output) -> list[str]:
        """
        Pulls source URLs from web_search_call items' action.sources (when
        present) and from any url_citation annotations on output text, so
        provenance is captured whenever the Responses API exposes it.
        """
        urls: list[str] = []
        for item in output:
            if getattr(item, "type", None) == "web_search_call":
                action = getattr(item, "action", None)
                for source in (getattr(action, "sources", None) or []):
                    url = getattr(source, "url", None) or (
                        source.get("url") if isinstance(source, dict) else None
                    )
                    if url:
                        urls.append(url)
            for annotation in (getattr(item, "annotations", None) or []):
                if getattr(annotation, "type", None) == "url_citation":
                    url = getattr(annotation, "url", None)
                    if url:
                        urls.append(url)
        return urls
