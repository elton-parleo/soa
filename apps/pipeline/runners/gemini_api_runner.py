"""
Gemini through the Gemini API with no grounding tool — platform "gemini_api" (2B).

The ungrounded surface beside "gemini_grounded", labelled as what it is,
so the two are compared rather than confused. 2D: the name "gemini"
resolves here (soa_shared/surfaces.py ALIASES), what the pre-2B "gemini"
rows were; until 2D it was aliased to gemini_grounded when a cycle ran.
"""
from runners.gemini_runner import GeminiRunner


class GeminiApiRunner(GeminiRunner):

    platform = "gemini_api"
