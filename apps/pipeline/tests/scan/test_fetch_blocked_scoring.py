"""
Tests for the fetch-resilience stage's Part B: fetch-status-aware
scoring (the honesty fix). A product page that terminally failed to
fetch (429/403/5xx — fetch_result.status in {'blocked','failed'}) must
never be silently treated as 'checked, nothing found': engine.py only
extracts data from a 'fetched' result, so an unread page has
extracted=None, and folding that into a scored zero was the bug this
stage fixes (the exact incident: 'no machine-readable price' rendered
for a page our reader never actually saw).

Direct scorer-level tests (PageScanData constructed directly), same
style as test_variant_extraction_downstream.py — this is about the
readable/unreadable partition scorer.py now applies, not discovery or
fetch behavior, so there's nothing to gain from exercising the full
httpx-mocked engine.run_scan() pipeline for most of these.
"""
import json

from scan import scorer, structured_data
from scan.discovery import PageCandidate
from scan.engine import PageScanData
from scan.fetcher import FetchResult
from scan.site_typing import SITE_TYPE_COMMERCE, SiteTypeResult

_COMMERCE = SiteTypeResult(site_type=SITE_TYPE_COMMERCE, reason="test fixture", signals=[])

_LOYALTY_HTML = """
<html><body>
  <h1>Insider Rewards</h1>
  <p>Earn points on every purchase and unlock member tiers with exclusive perks.</p>
</body></html>
"""


def _priced_product_html(price="29.99") -> str:
    data = {
        "@context": "https://schema.org", "@type": "Product", "name": "Widget",
        "offers": {
            "@type": "Offer", "price": price, "priceCurrency": "USD",
            "availability": "https://schema.org/InStock",
        },
    }
    return f"""
    <html><body>
      <script type="application/ld+json">{json.dumps(data)}</script>
      <h1>Widget</h1>
      <p>Now ${price}</p>
    </body></html>
    """


def _fetched_product_page(url: str, html: str) -> PageScanData:
    return PageScanData(
        candidate=PageCandidate(url=url, kind="product"),
        fetch_result=FetchResult(url=url, status="fetched", html=html, http_status=200),
        extracted=structured_data.extract(html),
    )


def _blocked_product_page(url: str, http_status=429) -> PageScanData:
    return PageScanData(
        candidate=PageCandidate(url=url, kind="product"),
        fetch_result=FetchResult(url=url, status="blocked", http_status=http_status, attempts=3),
        extracted=None,
    )


def _failed_product_page(url: str, http_status=503) -> PageScanData:
    return PageScanData(
        candidate=PageCandidate(url=url, kind="product"),
        fetch_result=FetchResult(url=url, status="failed", http_status=http_status, attempts=3),
        extracted=None,
    )


def _loyalty_page() -> PageScanData:
    return PageScanData(
        candidate=PageCandidate(url="https://example.com/rewards", kind="loyalty"),
        fetch_result=FetchResult(url="https://example.com/rewards", status="fetched", html=_LOYALTY_HTML),
        extracted=structured_data.extract(_LOYALTY_HTML),
    )


# ─── all sampled product pages blocked -> coverage='blocked' (NOT MEASURABLE) ──

def test_price_truth_seen_is_blocked_when_every_product_page_is_rate_limited():
    pages = [_blocked_product_page("https://example.com/products/a"), _blocked_product_page("https://example.com/products/b")]
    result = scorer.score_price_truth_seen(pages, _COMMERCE)
    assert result.coverage == "blocked"
    assert result.score == 0.0
    assert "2 of 2 product pages rate-limited our reader (HTTP 429) — couldn't be evaluated." in result.evidence


def test_catalog_context_is_blocked_when_every_product_page_is_rate_limited():
    pages = [_blocked_product_page("https://example.com/products/a"), _blocked_product_page("https://example.com/products/b")]
    result = scorer.score_catalog_context(pages, _COMMERCE)
    assert result.coverage == "blocked"
    assert result.score == 0.0


def test_deal_citability_seen_is_blocked_when_every_product_page_is_rate_limited():
    pages = [_blocked_product_page("https://example.com/products/a"), _blocked_product_page("https://example.com/products/b")]
    result = scorer.score_deal_citability_seen(pages, _COMMERCE)
    assert result.coverage == "blocked"
    assert result.score == 0.0


def test_member_value_seen_scores_loyalty_alone_when_member_price_side_is_all_blocked():
    """The member-price HALF is blocked, not the whole dimension — it's
    excluded from raw_score/raw_max and rescaled onto the full weight
    exactly like the existing member-value N/A path, so loyalty-surface
    discoverability alone still produces a real, measurable score."""
    pages = [
        _loyalty_page(),
        _blocked_product_page("https://example.com/products/a"),
        _blocked_product_page("https://example.com/products/b"),
    ]
    result = scorer.score_member_value_seen(pages, _COMMERCE)
    assert result.coverage == "full"
    assert result.score == result.max  # loyalty page fetchable + program terms present -> full marks
    assert any("rate-limited our reader (HTTP 429)" in line for line in result.evidence)


def test_all_blocked_evidence_names_mixed_status_codes_generically():
    pages = [
        _blocked_product_page("https://example.com/products/a", http_status=403),
        _failed_product_page("https://example.com/products/b", http_status=503),
    ]
    result = scorer.score_price_truth_seen(pages, _COMMERCE)
    assert result.coverage == "blocked"
    assert "HTTP 403" in result.evidence[0]
    assert "HTTP 503" in result.evidence[0]


# ─── partial: 1 ok + 1 blocked -> scores over the readable page, blocked count noted ──

def test_price_truth_seen_scores_over_the_readable_page_when_one_of_two_is_blocked():
    pages = [
        _fetched_product_page("https://example.com/products/a", _priced_product_html()),
        _blocked_product_page("https://example.com/products/b"),
    ]
    result = scorer.score_price_truth_seen(pages, _COMMERCE)
    assert result.coverage == "full"
    assert result.score == result.max
    assert "1/1 product pages expose a machine-readable price consistent with the page's own text" in result.evidence
    assert any("1 of 2 product pages rate-limited our reader (HTTP 429)" in line for line in result.evidence)


def test_deal_citability_seen_scores_over_the_readable_page_when_one_of_two_is_blocked():
    pages = [
        _fetched_product_page("https://example.com/products/a", _priced_product_html()),
        _blocked_product_page("https://example.com/products/b"),
    ]
    result = scorer.score_deal_citability_seen(pages, _COMMERCE)
    assert any("1 of 2 product pages rate-limited our reader (HTTP 429)" in line for line in result.evidence)


def test_catalog_context_scores_over_the_readable_page_when_one_of_two_is_blocked():
    pages = [
        _fetched_product_page("https://example.com/products/a", _priced_product_html()),
        _blocked_product_page("https://example.com/products/b"),
    ]
    result = scorer.score_catalog_context(pages, _COMMERCE)
    assert any("1 of 2 product pages rate-limited our reader (HTTP 429)" in line for line in result.evidence)


# ─── the incident regression: "no machine-readable price" must never fire for an unread page ──

def test_price_truth_evidence_never_claims_no_markup_when_every_page_was_blocked():
    """The exact incident this stage fixes: a 429-blocked page has no
    extracted data at all — it must never be folded into a bare 'no
    schema.org Product/Offer price markup' claim, which implies the
    page WAS read and genuinely had nothing."""
    pages = [_blocked_product_page("https://example.com/products/a"), _blocked_product_page("https://example.com/products/b")]
    result = scorer.score_price_truth_seen(pages, _COMMERCE)
    assert "no schema.org Product/Offer price markup" not in result.evidence
    assert result.coverage == "blocked"


def test_price_truth_evidence_no_markup_claim_stays_scoped_to_the_page_actually_read():
    """Companion: when ONE page genuinely has no price (fetched, empty)
    and the OTHER is blocked, the 'no markup' claim is honest — it
    reflects the one page that was actually read, not a blanket claim
    covering the blocked page too."""
    no_price_html = "<html><body><h1>Widget</h1><p>Contact us for pricing.</p></body></html>"
    pages = [
        _fetched_product_page("https://example.com/products/a", no_price_html),
        _blocked_product_page("https://example.com/products/b"),
    ]
    result = scorer.score_price_truth_seen(pages, _COMMERCE)
    assert "no schema.org Product/Offer price markup" in result.evidence
    assert any("1 of 2 product pages rate-limited our reader" in line for line in result.evidence)
    assert result.coverage == "full"


# ─── all-ok (nothing blocked) stays byte-identical to the pre-stage baseline ──

def test_price_truth_seen_unaffected_when_nothing_is_blocked():
    html = _priced_product_html()
    pages = [
        _fetched_product_page("https://example.com/products/a", html),
        _fetched_product_page("https://example.com/products/b", html),
    ]
    result = scorer.score_price_truth_seen(pages, _COMMERCE)
    assert result.coverage == "full"
    assert result.evidence == [
        "2/2 product pages expose a machine-readable price consistent with the page's own text",
        "2/2 product pages declare priceCurrency",
    ]


def test_catalog_context_unaffected_when_nothing_is_blocked():
    html = _priced_product_html()
    pages = [
        _fetched_product_page("https://example.com/products/a", html),
        _fetched_product_page("https://example.com/products/b", html),
    ]
    result = scorer.score_catalog_context(pages, _COMMERCE)
    assert result.coverage == "full"
    assert not any("rate-limited" in line or "excluded from this check" in line for line in result.evidence)
