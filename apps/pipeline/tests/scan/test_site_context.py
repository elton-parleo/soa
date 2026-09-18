"""
Tests for scan/site_context.py — the one homepage read that grounds
competitor auto-suggest in what a store actually sells.

scan.site_context.fetch is patched in every test (never the real
fetcher, never the network), same idiom as test_discovery.py. The
contract under test is mostly negative: read_site_context must return
None — never raise — for every way a homepage read can go wrong, since
its caller (worker.py::process_lite_requests) treats None as "fall back
to the name-only prompt" rather than as an error.
"""
from unittest.mock import patch

import pytest

from scan.site_context import (
    MAX_FIELD_LENGTH,
    MAX_PRODUCT_NAMES,
    SiteContext,
    read_site_context,
)


class _FetchResult:
    """Minimal stand-in for fetcher.FetchResult — only the four fields
    read_site_context actually reads, so this stays unaffected by the
    real dataclass's (many) diagnostic fields."""

    def __init__(self, status="fetched", html=None, final_url=None, url="https://acme.example.com", error=None):
        self.status = status
        self.html = html
        self.final_url = final_url
        self.url = url
        self.error = error


def _patch_fetch(result):
    return patch("scan.site_context.fetch", return_value=result)


FULL_HTML = """
<html>
  <head>
    <title>Acme Coffee — Small-batch roasted beans</title>
    <meta name="description" content="Single-origin coffee beans, roasted weekly in Portland.">
    <meta property="og:site_name" content="Acme Coffee">
    <script type="application/ld+json">
      {"@type": "Product", "name": "Ethiopia Yirgacheffe", "brand": "Acme Coffee"}
    </script>
  </head>
  <body>
    <h1>Coffee worth waking up for</h1>
  </body>
</html>
"""


# ── the happy path ──────────────────────────────────────────────────────

def test_fetched_html_with_all_fields_populates_every_one():
    with _patch_fetch(_FetchResult(html=FULL_HTML, final_url="https://www.acme.example.com/")):
        ctx = read_site_context("acme.example.com")

    assert ctx.title == "Acme Coffee — Small-batch roasted beans"
    assert ctx.meta_description == "Single-origin coffee beans, roasted weekly in Portland."
    assert ctx.og_site_name == "Acme Coffee"
    assert ctx.h1 == "Coffee worth waking up for"
    assert ctx.product_names == ["Ethiopia Yirgacheffe"]
    assert ctx.jsonld_brand == "Acme Coffee"
    assert ctx.final_url == "https://www.acme.example.com/"


def test_bare_domain_input_is_normalized_to_an_https_origin_before_fetching():
    with _patch_fetch(_FetchResult(html=FULL_HTML)) as mock_fetch:
        read_site_context("acme.example.com")

    assert mock_fetch.call_args.args[0] == "https://acme.example.com"


def test_deep_link_input_is_reduced_to_the_homepage_origin():
    with _patch_fetch(_FetchResult(html=FULL_HTML)) as mock_fetch:
        read_site_context("https://acme.example.com/collections/beans?page=2")

    assert mock_fetch.call_args.args[0] == "https://acme.example.com"


def test_only_a_title_is_enough_to_return_a_context():
    html = "<html><head><title>Acme Coffee</title></head><body></body></html>"
    with _patch_fetch(_FetchResult(html=html)):
        ctx = read_site_context("https://acme.example.com")

    assert ctx.title == "Acme Coffee"
    assert ctx.meta_description is None
    assert ctx.h1 is None
    assert ctx.product_names == []


def test_og_description_is_used_when_there_is_no_meta_description():
    html = """<html><head><title>Acme</title>
      <meta property="og:description" content="Roasted in Portland."></head></html>"""
    with _patch_fetch(_FetchResult(html=html)):
        ctx = read_site_context("https://acme.example.com")

    assert ctx.meta_description == "Roasted in Portland."


def test_meta_description_wins_over_og_description_when_both_are_present():
    html = """<html><head><title>Acme</title>
      <meta name="description" content="The real one.">
      <meta property="og:description" content="The fallback."></head></html>"""
    with _patch_fetch(_FetchResult(html=html)):
        ctx = read_site_context("https://acme.example.com")

    assert ctx.meta_description == "The real one."


def test_final_url_falls_back_to_the_requested_url_when_the_fetch_reports_none():
    with _patch_fetch(_FetchResult(html=FULL_HTML, final_url=None, url="https://acme.example.com")):
        ctx = read_site_context("https://acme.example.com")

    assert ctx.final_url == "https://acme.example.com"


# ── every way this returns None instead of raising ──────────────────────

def test_none_url_returns_none_without_fetching():
    with _patch_fetch(_FetchResult(html=FULL_HTML)) as mock_fetch:
        assert read_site_context(None) is None
    mock_fetch.assert_not_called()


def test_empty_url_returns_none_without_fetching():
    with _patch_fetch(_FetchResult(html=FULL_HTML)) as mock_fetch:
        assert read_site_context("") is None
    mock_fetch.assert_not_called()


def test_unparseable_url_returns_none_without_fetching():
    with _patch_fetch(_FetchResult(html=FULL_HTML)) as mock_fetch:
        assert read_site_context("https://") is None
    mock_fetch.assert_not_called()


@pytest.mark.parametrize("status", ["blocked", "robots_disallowed", "not_found", "failed"])
def test_any_non_fetched_status_returns_none(status):
    """A bot-challenge page comes back as 'blocked' (fetcher.py's own
    challenge-marker detection), and a challenge page's HTML would
    otherwise parse into a perfectly plausible — and completely wrong —
    'what this brand sells' block."""
    with _patch_fetch(_FetchResult(status=status, html="<html><title>Just a moment…</title></html>")):
        assert read_site_context("https://acme.example.com") is None


def test_fetched_but_empty_html_returns_none():
    with _patch_fetch(_FetchResult(html="")):
        assert read_site_context("https://acme.example.com") is None


def test_fetched_with_html_none_returns_none():
    with _patch_fetch(_FetchResult(html=None)):
        assert read_site_context("https://acme.example.com") is None


def test_garbage_html_returns_none_without_raising():
    with _patch_fetch(_FetchResult(html="<<<>>> not really html &&& \x00 <title")):
        assert read_site_context("https://acme.example.com") is None


def test_valid_html_with_nothing_worth_saying_returns_none():
    with _patch_fetch(_FetchResult(html="<html><head></head><body><p>hi</p></body></html>")):
        assert read_site_context("https://acme.example.com") is None


def test_whitespace_only_fields_count_as_empty():
    html = "<html><head><title>   </title><meta name='description' content='  '></head></html>"
    with _patch_fetch(_FetchResult(html=html)):
        assert read_site_context("https://acme.example.com") is None


def test_a_fetch_that_somehow_raises_returns_none():
    """fetch() is documented never-throw, but read_site_context must not
    depend on that being true forever — the caller's whole reason for
    existing is that grounding can fail silently."""
    with patch("scan.site_context.fetch", side_effect=RuntimeError("boom")):
        assert read_site_context("https://acme.example.com") is None


def test_an_exception_inside_parsing_returns_none():
    with _patch_fetch(_FetchResult(html=FULL_HTML)), \
         patch("scan.site_context.BeautifulSoup", side_effect=ValueError("parser exploded")):
        assert read_site_context("https://acme.example.com") is None


# ── caps ────────────────────────────────────────────────────────────────

def test_long_strings_are_capped_at_max_field_length():
    long_title = "x" * 500
    html = f"<html><head><title>{long_title}</title></head></html>"
    with _patch_fetch(_FetchResult(html=html)):
        ctx = read_site_context("https://acme.example.com")

    assert len(ctx.title) == MAX_FIELD_LENGTH


def test_product_names_are_capped_and_deduped():
    products = "".join(
        f'<script type="application/ld+json">{{"@type":"Product","name":"Bean {i}"}}</script>'
        for i in range(20)
    )
    dupes = '<script type="application/ld+json">{"@type":"Product","name":"Bean 0"}</script>'
    html = f"<html><head><title>Acme</title>{products}{dupes}</head></html>"
    with _patch_fetch(_FetchResult(html=html)):
        ctx = read_site_context("https://acme.example.com")

    assert len(ctx.product_names) == MAX_PRODUCT_NAMES
    assert len(set(ctx.product_names)) == MAX_PRODUCT_NAMES


def test_whitespace_in_a_field_is_collapsed():
    html = "<html><head><title>Acme\n   Coffee\tRoasters</title></head></html>"
    with _patch_fetch(_FetchResult(html=html)):
        ctx = read_site_context("https://acme.example.com")

    assert ctx.title == "Acme Coffee Roasters"


# ── as_prompt_block ─────────────────────────────────────────────────────

def test_prompt_block_renders_only_populated_fields():
    block = SiteContext(title="Acme Coffee", final_url="https://acme.example.com").as_prompt_block()

    assert block == "Homepage: https://acme.example.com\nPage title: Acme Coffee"


def test_prompt_block_renders_every_field_when_all_are_present():
    block = SiteContext(
        title="Acme Coffee",
        meta_description="Single-origin beans.",
        og_site_name="Acme Coffee",
        h1="Coffee worth waking up for",
        product_names=["Yirgacheffe", "Huila"],
        jsonld_brand="Acme Coffee",
        final_url="https://acme.example.com",
    ).as_prompt_block()

    assert block.splitlines() == [
        "Homepage: https://acme.example.com",
        "Page title: Acme Coffee",
        "Site name: Acme Coffee",
        "Site description: Single-origin beans.",
        "Main heading: Coffee worth waking up for",
        "Brand named in its product markup: Acme Coffee",
        "Products listed on the page: Yirgacheffe, Huila",
    ]


def test_prompt_block_of_an_empty_context_is_empty():
    assert SiteContext().as_prompt_block() == ""
