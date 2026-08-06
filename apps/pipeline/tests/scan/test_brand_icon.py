"""
1a/1b: direct unit tests for brand_icon.py's extract_brand_icon() — same
lightweight fixture convention as test_offer_feed.py, extended with a
`candidate.kind` field since icon resolution specifically targets the
homepage page (unlike offer_feed.py's product-image resolution, which
takes the first product found across any sampled page).
"""
from dataclasses import dataclass, field
from typing import Optional

from scan.brand_icon import extract_brand_icon
from scan.structured_data import ExtractedData


@dataclass
class _Candidate:
    kind: str


@dataclass
class _FetchResult:
    url: str
    final_url: Optional[str] = None


@dataclass
class _Page:
    candidate: _Candidate
    fetch_result: _FetchResult
    extracted: Optional[ExtractedData]


def _homepage(url, extracted=None, final_url=None):
    return _Page(
        candidate=_Candidate(kind="homepage"),
        fetch_result=_FetchResult(url=url, final_url=final_url),
        extracted=extracted or ExtractedData(),
    )


def _product_page(url, extracted=None):
    return _Page(
        candidate=_Candidate(kind="product"),
        fetch_result=_FetchResult(url=url),
        extracted=extracted or ExtractedData(),
    )


# ─── precedence: apple-touch-icon > icon > Organization.logo ────────────

def test_apple_touch_icon_wins_when_all_three_tiers_present():
    extracted = ExtractedData(
        apple_touch_icons=[{"href": "/apple.png", "sizes": "180x180"}],
        icon_links=[{"href": "/favicon.png", "sizes": "32x32"}],
        organization_logo="/org-logo.png",
    )
    pages = [_homepage("https://example.com", extracted)]
    assert extract_brand_icon(pages) == "https://example.com/apple.png"


def test_icon_link_wins_when_no_apple_touch_icon():
    extracted = ExtractedData(
        icon_links=[{"href": "/favicon.png", "sizes": "32x32"}],
        organization_logo="/org-logo.png",
    )
    pages = [_homepage("https://example.com", extracted)]
    assert extract_brand_icon(pages) == "https://example.com/favicon.png"


def test_organization_logo_used_as_last_resort():
    extracted = ExtractedData(organization_logo="/org-logo.png")
    pages = [_homepage("https://example.com", extracted)]
    assert extract_brand_icon(pages) == "https://example.com/org-logo.png"


def test_none_when_nothing_declared():
    pages = [_homepage("https://example.com", ExtractedData())]
    assert extract_brand_icon(pages) is None


# ─── largest-wins within a tier ──────────────────────────────────────────

def test_apple_touch_icon_picks_the_largest_by_declared_size():
    extracted = ExtractedData(apple_touch_icons=[
        {"href": "/icon-57.png", "sizes": "57x57"},
        {"href": "/icon-180.png", "sizes": "180x180"},
        {"href": "/icon-120.png", "sizes": "120x120"},
    ])
    pages = [_homepage("https://example.com", extracted)]
    assert extract_brand_icon(pages) == "https://example.com/icon-180.png"


def test_icon_link_picks_the_largest_by_declared_size():
    extracted = ExtractedData(icon_links=[
        {"href": "/favicon-16.png", "sizes": "16x16"},
        {"href": "/favicon-32.png", "sizes": "32x32"},
    ])
    pages = [_homepage("https://example.com", extracted)]
    assert extract_brand_icon(pages) == "https://example.com/favicon-32.png"


def test_unsized_icon_still_wins_over_no_icon_at_all():
    extracted = ExtractedData(apple_touch_icons=[{"href": "/icon.png", "sizes": None}])
    pages = [_homepage("https://example.com", extracted)]
    assert extract_brand_icon(pages) == "https://example.com/icon.png"


def test_sized_icon_preferred_over_unsized_icon_in_the_same_tier():
    extracted = ExtractedData(apple_touch_icons=[
        {"href": "/icon-unsized.png", "sizes": None},
        {"href": "/icon-180.png", "sizes": "180x180"},
    ])
    pages = [_homepage("https://example.com", extracted)]
    assert extract_brand_icon(pages) == "https://example.com/icon-180.png"


# ─── absolutizing ─────────────────────────────────────────────────────────

def test_relative_url_absolutized_against_the_page_url():
    extracted = ExtractedData(apple_touch_icons=[{"href": "/icon.png", "sizes": None}])
    pages = [_homepage("https://example.com/", extracted)]
    assert extract_brand_icon(pages) == "https://example.com/icon.png"


def test_already_absolute_url_kept_as_is():
    extracted = ExtractedData(apple_touch_icons=[{"href": "https://cdn.example.com/icon.png", "sizes": None}])
    pages = [_homepage("https://example.com", extracted)]
    assert extract_brand_icon(pages) == "https://cdn.example.com/icon.png"


def test_prefers_final_url_over_the_original_request_url():
    extracted = ExtractedData(apple_touch_icons=[{"href": "/icon.png", "sizes": None}])
    pages = [_homepage("https://example.com", extracted, final_url="https://www.example.com")]
    assert extract_brand_icon(pages) == "https://www.example.com/icon.png"


# ─── homepage-only targeting ──────────────────────────────────────────────

def test_ignores_icons_declared_on_a_non_homepage_page():
    extracted = ExtractedData(apple_touch_icons=[{"href": "/icon.png", "sizes": None}])
    pages = [_product_page("https://example.com/products/widget", extracted)]
    assert extract_brand_icon(pages) is None


def test_multiple_pages_only_the_homepage_is_consulted():
    homepage_extracted = ExtractedData(apple_touch_icons=[{"href": "/home-icon.png", "sizes": None}])
    product_extracted = ExtractedData(apple_touch_icons=[{"href": "/product-icon.png", "sizes": None}])
    pages = [
        _product_page("https://example.com/products/widget", product_extracted),
        _homepage("https://example.com", homepage_extracted),
    ]
    assert extract_brand_icon(pages) == "https://example.com/home-icon.png"


# ─── honest-state: blocked/failed runs ────────────────────────────────────

def test_none_when_no_homepage_page_at_all():
    assert extract_brand_icon([]) is None


def test_none_when_homepage_present_but_never_extracted():
    page = _homepage("https://example.com", extracted=None)
    page.extracted = None
    assert extract_brand_icon([page]) is None


def test_none_when_homepage_fetch_result_has_no_url_at_all():
    extracted = ExtractedData(apple_touch_icons=[{"href": "/icon.png", "sizes": None}])
    page = _homepage("", extracted)
    page.fetch_result = _FetchResult(url="", final_url=None)
    assert extract_brand_icon([page]) is None
