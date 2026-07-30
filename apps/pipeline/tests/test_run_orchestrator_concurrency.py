"""
Stage 25 (Part 4, Q2): lite-specific concurrency override tests.
resolve_platform_concurrency is a pure function (no DB/session_factory
access), so these test it directly rather than instantiating a full
RunOrchestrator (which requires a real cycle row) — the override logic
itself is what Q2 asks to prove: bounded (uses the configured value, not
unlimited) and isolated (never touches non-lite cycles or non-chatgpt
platforms).
"""
import soa_shared.config as config
from runners.run_orchestrator import resolve_platform_concurrency


def test_lite_cycle_chatgpt_uses_the_lite_concurrency_override():
    assert resolve_platform_concurrency("lite-a1b2c3d4", "chatgpt", 3) == config.LITE_QUERY_CONCURRENCY


def test_lite_override_is_bounded_by_the_configured_value_not_unlimited():
    """The override is a specific configured number (env-overridable),
    never 'no limit' — asyncio.Semaphore(resolve_platform_concurrency(...))
    still throttles a lite cycle's chatgpt dispatch."""
    assert isinstance(config.LITE_QUERY_CONCURRENCY, int)
    assert config.LITE_QUERY_CONCURRENCY > 0
    assert resolve_platform_concurrency("lite-x", "chatgpt", 3) == config.LITE_QUERY_CONCURRENCY


def test_non_lite_cycle_chatgpt_uses_the_shared_default_unaffected():
    assert resolve_platform_concurrency("standard-abc123", "chatgpt", 3) == config.SOA_OPENAI_MAX_CONCURRENT


def test_lite_cycle_non_chatgpt_platform_is_unaffected():
    """Isolated: the override is chatgpt-specific — a lite cycle asking
    for another platform (not the normal case, lite is chatgpt-only, but
    the function must not silently apply the override elsewhere) falls
    through to that platform's own normal limit."""
    assert resolve_platform_concurrency("lite-a1b2c3d4", "claude", 3) == config.SOA_CLAUDE_MAX_CONCURRENT
    assert resolve_platform_concurrency("lite-a1b2c3d4", "perplexity", 3) == config.SOA_PERPLEXITY_MAX_CONCURRENT
    assert resolve_platform_concurrency("lite-a1b2c3d4", "gemini", 3) == config.SOA_GEMINI_MAX_CONCURRENT


def test_non_lite_cycle_every_platform_is_completely_unaffected():
    assert resolve_platform_concurrency("standard-abc123", "claude", 3) == config.SOA_CLAUDE_MAX_CONCURRENT
    assert resolve_platform_concurrency("standard-abc123", "perplexity", 3) == config.SOA_PERPLEXITY_MAX_CONCURRENT
    assert resolve_platform_concurrency("standard-abc123", "gemini", 3) == config.SOA_GEMINI_MAX_CONCURRENT


def test_unknown_platform_falls_back_to_the_caller_supplied_max_concurrent():
    assert resolve_platform_concurrency("standard-abc123", "some_future_platform", 7) == 7
    assert resolve_platform_concurrency("lite-a1b2c3d4", "some_future_platform", 7) == 7


def test_a_cycle_code_that_merely_contains_lite_but_lacks_the_prefix_is_unaffected():
    """Exact prefix match only — 'elite-2026' or a cycle_code that
    happens to contain 'lite' elsewhere must never accidentally qualify."""
    assert resolve_platform_concurrency("elite-2026", "chatgpt", 3) == config.SOA_OPENAI_MAX_CONCURRENT
    assert resolve_platform_concurrency("client-lite-test", "chatgpt", 3) == config.SOA_OPENAI_MAX_CONCURRENT
