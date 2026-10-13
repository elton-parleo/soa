"""
ChatGPT through the OpenAI API with no tools — platform "chatgpt_api" (2B).

The ungrounded surface beside "chatgpt", which carries the web_search tool
(runners/openai_runner.py). Same client, same model and reasoning effort,
the one difference being the tools list: none. So the two surfaces differ
in exactly the thing their labels say they differ in.
"""
from runners.openai_runner import OpenAIRunner
from runners.platform_response import PlatformResponse


class OpenAIApiRunner(OpenAIRunner):

    platform = "chatgpt_api"

    async def _call_api(self, query_text: str) -> PlatformResponse:
        response = await self._client.responses.create(
            model=self.model,
            input=[{"role": "user", "content": query_text}],
            reasoning={"effort": self.reasoning_effort},
        )
        usage = response.usage
        return PlatformResponse(
            response_text=response.output_text or "",
            prompt_tokens=usage.input_tokens if usage else 0,
            completion_tokens=usage.output_tokens if usage else 0,
            latency_ms=0,
            platform=self.platform,
            model=self.model,
            status="success",
            search_triggered=False,
            retrieved_sources=None,
        )
