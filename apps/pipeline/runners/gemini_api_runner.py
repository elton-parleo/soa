"""
Gemini through the Gemini API with no grounding tool — platform "gemini_api" (2B).

The ungrounded surface beside "gemini_grounded". Before 2B a cycle could
not run it: "gemini" is aliased to gemini_grounded (run_orchestrator.py
PLATFORM_ALIASES) because the ungrounded API answers from training data
alone. That alias stays — an old cycle asking for "gemini" still runs
grounded — and this explicit id makes the ungrounded surface selectable
beside it, labelled as what it is, so the two are compared rather than
confused.
"""
from runners.gemini_runner import GeminiRunner


class GeminiApiRunner(GeminiRunner):

    platform = "gemini_api"
