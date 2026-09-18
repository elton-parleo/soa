"""
Cross-app parity test for the competitor prompt.

apps/pipeline/generation/competitor_generator.py and apps/api/app/
services/competitor_suggestion.py are separate deployable services that
never import each other (they communicate only through Postgres), so
the prompt lives in two deliberately duplicated copies — see either
module's LOCKSTEP note. Duplication only stays honest if drift is
loud: this asserts the two _build_competitor_prompt functions return
byte-identical strings for identical inputs, with and without the
site_context grounding block, so a change to one copy fails here rather
than silently producing two different competitor lists in production.

Same discipline as test_lite_status_parity.py and test_scan_dimensions_
parity.py, but loading the pipeline module and comparing its rendered
output rather than AST-scanning its source — the thing under test is
the prompt string, not the source shape. competitor_generator.py
imports nothing from inside apps/pipeline (stdlib + openai only), so it
loads cleanly from its path.

Deliberately NOT via sys.path: putting apps/pipeline on sys.path makes
its tests/ package (which has an __init__.py) shadow apps/api's
namespace-package tests/, and a regular package beats a namespace
portion no matter where it sits in the path — that breaks the four
apps/api test modules that do `from tests.test_x import ...`. Loading
the single file by path keeps this test entirely side-effect-free for
the rest of the suite.
"""
import importlib.util
from pathlib import Path

import pytest

from app.services.competitor_suggestion import _build_competitor_prompt as api_prompt

PIPELINE_GENERATOR = (
    Path(__file__).resolve().parents[2] / "pipeline" / "generation" / "competitor_generator.py"
)


def _load_pipeline_generator():
    spec = importlib.util.spec_from_file_location("_parity_competitor_generator", PIPELINE_GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pipeline_prompt = _load_pipeline_generator()._build_competitor_prompt

SITE_BLOCK = (
    "Homepage: https://acme.example.com\n"
    "Page title: Acme Coffee — Small-batch roasted beans\n"
    "Site description: Single-origin coffee beans, roasted weekly in Portland.\n"
    "Products listed on the page: Ethiopia Yirgacheffe, Colombia Huila"
)

CASES = [
    ("brand only", ("Acme", None, None, None)),
    ("store url", ("Acme", "https://acme.example.com", None, None)),
    ("category hint", ("Acme", None, "Coffee", None)),
    ("store url + category hint", ("Acme", "https://acme.example.com", "Coffee", None)),
    ("site context only", ("Acme", None, None, SITE_BLOCK)),
    ("site context + store url", ("Acme", "https://acme.example.com", None, SITE_BLOCK)),
    ("everything", ("Acme", "https://acme.example.com", "Coffee", SITE_BLOCK)),
    ("quotes in the brand name", ('O\'Neill "Classic"', None, None, SITE_BLOCK)),
]


@pytest.mark.parametrize("label,args", CASES, ids=[c[0] for c in CASES])
def test_both_copies_render_an_identical_prompt(label, args):
    assert pipeline_prompt(*args) == api_prompt(*args)


def test_the_default_positional_call_matches_too():
    """The pre-grounding call shape (three positional args, no
    site_context) must stay identical across both copies as well."""
    assert pipeline_prompt("Acme", "https://acme.example.com", "Coffee") == \
        api_prompt("Acme", "https://acme.example.com", "Coffee")


def test_the_grounded_prompt_actually_differs_from_the_ungrounded_one():
    """Guards the parity assertions above from passing vacuously — if
    site_context were silently dropped by BOTH copies, every case above
    would still match."""
    assert pipeline_prompt("Acme", None, None, SITE_BLOCK) != pipeline_prompt("Acme", None, None, None)
    assert SITE_BLOCK in api_prompt("Acme", None, None, SITE_BLOCK)
