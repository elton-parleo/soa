"""
Scaffold for true agentic-shopping surfaces — interface only, not wired
into any live run.

These surfaces (Amazon Rufus, ChatGPT Shopping) are conversational
shopping agents embedded in a retailer/platform UI, not public completion
APIs. There is no documented, supported API for either as of this
writing — querying them programmatically would require a browser-
automation path (driving the actual web/app UI, e.g. via Playwright)
rather than the request/response runner pattern used elsewhere in
runners/. That is a materially different integration (session/auth
handling, UI scraping, ToS considerations) and is intentionally NOT
implemented here.

AgenticShoppingRunner is NOT a BasePlatformRunner subclass — it does not
participate in run_orchestrator's _RUNNER_CLASSES registry, and nothing
in run_orchestrator.py references this module. Wiring it in is future
work once a browser-automation harness exists.
"""
from abc import ABC, abstractmethod

from runners.platform_response import PlatformResponse


class AgenticShoppingRunner(ABC):
    """
    Base interface for true agentic-shopping surfaces. Intentionally does
    not extend BasePlatformRunner — these surfaces have no API endpoint to
    wrap with retry/timeout logic; a real implementation needs a browser-
    automation session lifecycle (launch, navigate, query, scrape, close)
    that the request/response runner model does not fit.
    """

    @property
    @abstractmethod
    def platform(self) -> str:
        """Platform identifier, e.g. 'amazon_rufus', 'chatgpt_shopping'."""

    @abstractmethod
    async def run(self, query_text: str) -> PlatformResponse:
        """
        Drive the shopping surface's UI for one query and return a
        PlatformResponse. Not implemented — see module docstring.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__}.run() requires a browser-automation "
            "path (e.g. Playwright driving the real UI) — there is no public "
            "API for this surface. Not implemented."
        )


class AmazonRufusRunner(AgenticShoppingRunner):
    """
    Amazon Rufus is a conversational shopping assistant embedded in the
    Amazon app/site. No public API. A real implementation would need to
    drive the Amazon UI (web or app) via browser automation, handle
    Amazon account/session state, and scrape Rufus's chat responses —
    out of scope for this scaffold.
    """

    platform = "amazon_rufus"

    async def run(self, query_text: str) -> PlatformResponse:
        # TODO: implement via browser automation (e.g. Playwright) driving
        # the Amazon Rufus chat UI. Needs: authenticated session handling,
        # UI element selectors for the Rufus chat panel, and response
        # scraping/parsing into PlatformResponse. Track ToS implications
        # before building — Amazon's terms govern automated UI access.
        raise NotImplementedError(
            "AmazonRufusRunner requires a browser-automation path — "
            "Rufus has no public API. Not implemented."
        )


class ChatGPTShoppingRunner(AgenticShoppingRunner):
    """
    ChatGPT Shopping is OpenAI's in-product shopping experience (product
    carousels, checkout flows) surfaced inside chatgpt.com / the ChatGPT
    apps, distinct from the Responses API used by openai_runner.py. No
    public API exposes the shopping-specific UI/behavior. A real
    implementation would need to drive the ChatGPT web UI via browser
    automation and scrape the shopping surface's rendered output.
    """

    platform = "chatgpt_shopping"

    async def run(self, query_text: str) -> PlatformResponse:
        # TODO: implement via browser automation driving chatgpt.com,
        # distinct from openai_runner.py's Responses API integration.
        # Needs: authenticated ChatGPT session, UI selectors for product
        # carousel/checkout surfaces, and response scraping into
        # PlatformResponse.
        raise NotImplementedError(
            "ChatGPTShoppingRunner requires a browser-automation path — "
            "the in-product shopping surface has no public API. "
            "Not implemented."
        )
