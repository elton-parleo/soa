"""
Claude platform runner for SoA measurement.

Uses the Anthropic Messages API with the web_search tool available but not
forced. Claude decides whether to search on each query, emulating real
claude.ai consumer behavior where search is triggered based on the model's
judgment of whether live web data improves the response.

Whether search was triggered is captured in the search_triggered field of
PlatformResponse and written to soa_runs.search_triggered, enabling analysis
of how Sephora's mention rate differs between search-backed and
non-search-backed Claude responses.

Model: claude-sonnet-4-6
Temperature: not set — uses model default, consistent with claude.ai
consumer experience.
"""
import logging
import time

import anthropic

import soa_shared.config as config
from soa_shared.config import SOA_CLAUDE_TIMEOUT_SECONDS
from runners.base_runner import BasePlatformRunner
from runners.platform_response import PlatformResponse

logger = logging.getLogger(__name__)


class ClaudeRunner(BasePlatformRunner):

    platform = "claude"

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        timeout_seconds: int = SOA_CLAUDE_TIMEOUT_SECONDS,
    ):
        if not config.ANTHROPIC_CLAUDE_API_KEY:
            raise ValueError(
                "ANTHROPIC_CLAUDE_API_KEY is not set. Add it to /soa/.env."
            )
        super().__init__(model=model, timeout_seconds=timeout_seconds)
        self.client = anthropic.AsyncAnthropic(
            api_key=config.ANTHROPIC_CLAUDE_API_KEY,
        )

    async def _call_api(self, query_text: str) -> PlatformResponse:
        preview = query_text[:60].replace("\n", " ")
        logger.info("[claude/%s] Starting run — query='%s...'", self.model, preview)

        t0 = time.monotonic()
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
            }],
            messages=[{
                "role": "user",
                "content": query_text,
            }],
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        # Extract all text blocks and join them into the final response
        text_blocks = [
            block.text
            for block in response.content
            if block.type == "text"
        ]
        response_text = "\n".join(text_blocks).strip()

        # Detect search: web_search_20250305 produces "server_tool_use" blocks
        # with name="web_search" when search is triggered. Also check "tool_use"
        # for forward-compatibility with potential API changes.
        search_triggered = any(
            getattr(block, "type", "") in ("tool_use", "server_tool_use")
            and getattr(block, "name", None) == "web_search"
            for block in response.content
        )

        logger.info(
            "[claude/%s] Completed — latency=%dms search_triggered=%s tokens=%d",
            self.model, latency_ms, search_triggered, response.usage.output_tokens,
        )

        return PlatformResponse(
            response_text=response_text,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            latency_ms=0,       # set by base class run()
            platform=self.platform,
            model=self.model,
            status="success",
            search_triggered=search_triggered,
        )
