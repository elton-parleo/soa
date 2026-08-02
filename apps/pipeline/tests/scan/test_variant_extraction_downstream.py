"""
F3/F5: downstream sanity for the structured_data.py JSON-LD traversal
fix (F1) — no scoring-logic changes here, only assertions that the
newly-visible ProductGroup+hasVariant data actually flows through
scorer.py's checks the way F1's fix intends, plus F5's evidence-wording
precision on the "no price found" path.

Direct scorer-level tests (PageScanData/SiteTypeResult constructed
directly) rather than the full httpx-mocked engine.run_scan() pipeline
in test_scorer.py — these are about extraction-to-scoring wiring, not
discovery/fetch behavior, so there's nothing to gain from exercising
that machinery too.
"""
import json

from scan import scorer, structured_data
from scan.discovery import PageCandidate
from scan.engine import PageScanData
from scan.fetcher import FetchResult
from scan.site_typing import SITE_TYPE_COMMERCE, SiteTypeResult

_COMMERCE = SiteTypeResult(site_type=SITE_TYPE_COMMERCE, reason="test fixture", signals=[])


def _product_page(url: str, html: str) -> PageScanData:
    return PageScanData(
        candidate=PageCandidate(url=url, kind="product"),
        fetch_result=FetchResult(url=url, status="fetched", html=html),
        extracted=structured_data.extract(html),
    )


def _variant_page_html(*, valid_through="2026-12-31") -> str:
    """The Vuori/Allbirds shape: a ProductGroup whose own offers are
    empty, with two hasVariant Products each carrying a real Offer —
    distinct prices so the page's own visible text has 2 distinct
    dollar amounts (the price-consistency check's conservative
    multiplicity gate then correctly no-ops on this page, same as any
    other multi-price page — F3's first assertion)."""
    offer = {
        "@type": "Offer", "priceCurrency": "USD", "availability": "https://schema.org/InStock",
    }
    if valid_through:
        offer["priceValidUntil"] = valid_through
    blue_offer = {**offer, "price": "29.99"}
    red_offer = {**offer, "price": "34.99"}
    data = {
        "@context": "https://schema.org", "@type": "ProductGroup", "name": "Classic Tee",
        "hasVariant": [
            {"@type": "Product", "name": "Classic Tee - Blue - M", "sku": "TEE-BLU-M", "offers": blue_offer},
            {"@type": "Product", "name": "Classic Tee - Red - M", "sku": "TEE-RED-M", "offers": red_offer},
        ],
    }
    return f"""
    <html><body>
      <script type="application/ld+json">{json.dumps(data)}</script>
      <h1>Classic Tee</h1>
      <p>Blue: $29.99</p>
      <p>Red: $34.99</p>
    </body></html>
    """


def test_price_consistency_check_no_ops_on_a_variant_priced_page():
    """F3: many distinct structured prices on one page (one per variant)
    must still trip the conservative 'exactly one visible price' gate —
    no false mismatch, same as before this stage's fix."""
    page = _product_page("https://example.com/products/classic-tee", _variant_page_html())
    assert scorer._price_consistency_mismatch(page) is False


def test_score_price_truth_seen_is_nonzero_on_a_variant_page():
    """F3: with the traversal fix, the ProductGroup's hasVariant offers
    are now visible to price_truth.seen — this page should score full
    price + currency credit, not the pre-fix zero (variants invisible)."""
    page = _product_page("https://example.com/products/classic-tee", _variant_page_html())
    result = scorer.score_price_truth_seen([page], _COMMERCE)
    assert result.score > 0
    assert "1/1 product pages expose a machine-readable price consistent with the page's own text" in result.evidence
    assert "1/1 product pages declare priceCurrency" in result.evidence


def test_score_deal_citability_seen_active_count_reflects_variant_level_valid_through():
    """F3: priceValidUntil declared on a VARIANT's own Offer (never the
    group's, since the group has no offers of its own) must be seen —
    deal_citability.seen's ACTIVE sub-check requires a not-yet-expired
    priceValidUntil somewhere on the page."""
    page = _product_page("https://example.com/products/classic-tee", _variant_page_html(valid_through="2026-12-31"))
    result = scorer.score_deal_citability_seen([page], _COMMERCE)
    assert any("currently-active validity window" in line and "1/1" in line for line in result.evidence)


def test_score_deal_citability_seen_reflects_no_valid_through_when_variants_lack_one():
    """Companion to the above: with no priceValidUntil anywhere (on
    either variant), the ACTIVE sub-check correctly reads 0/1 — proving
    the prior test's 1/1 genuinely comes from the variant data, not a
    default/always-true fallback."""
    page = _product_page("https://example.com/products/classic-tee", _variant_page_html(valid_through=None))
    result = scorer.score_deal_citability_seen([page], _COMMERCE)
    assert any("currently-active validity window" in line and "0/1" in line for line in result.evidence)


def test_catalog_context_price_and_availability_check_passes_on_variant_page():
    """F3: Catalog & Context's per-page completeness check (name + offers
    + price + availability, any()-over-products-on-the-page) now passes
    because the variants — not the offer-less group — carry that data."""
    page = _product_page("https://example.com/products/classic-tee", _variant_page_html())
    result = scorer.score_catalog_context([page], _COMMERCE)
    assert result.score > 0


# ─── F5: evidence-wording precision on the "no price found" path ───────

def _no_price_page_html(*, og_meta: bool) -> str:
    meta = '<meta property="og:price:amount" content="29.99">' if og_meta else ""
    return f"""
    <html><head>{meta}</head><body>
      <h1>Widget</h1>
      <p>Contact us for pricing.</p>
    </body></html>
    """


def test_price_truth_evidence_names_absent_schema_markup_when_nothing_found():
    page = _product_page("https://example.com/products/widget", _no_price_page_html(og_meta=False))
    result = scorer.score_price_truth_seen([page], _COMMERCE)
    assert "no schema.org Product/Offer price markup" in result.evidence


def test_price_truth_evidence_names_og_meta_when_present_but_no_schema_price():
    page = _product_page("https://example.com/products/widget", _no_price_page_html(og_meta=True))
    result = scorer.score_price_truth_seen([page], _COMMERCE)
    assert "social-preview (OG) price metadata found — not the schema.org offers agents parse" in result.evidence
    assert "no schema.org Product/Offer price markup" not in result.evidence


def test_price_truth_evidence_omits_the_absence_line_when_mismatch_explains_the_zero():
    """F5's exclusion case: when with_price is empty because every priced
    page was flagged as a structured/visible mismatch (real markup
    exists, it just disagrees), the 'no schema.org markup' line would be
    false — it must not appear."""
    html = f"""
    <html><body>
      <script type="application/ld+json">{json.dumps({
        "@context": "https://schema.org", "@type": "Product", "name": "Widget",
        "offers": {"@type": "Offer", "price": "19.99", "priceCurrency": "USD"},
    })}</script>
      <h1>Widget</h1>
      <p>Now $29.99</p>
    </body></html>
    """
    page = _product_page("https://example.com/products/widget", html)
    assert scorer._price_consistency_mismatch(page) is True  # sanity: fixture is genuinely a mismatch
    result = scorer.score_price_truth_seen([page], _COMMERCE)
    assert "no schema.org Product/Offer price markup" not in result.evidence
    assert "social-preview (OG) price metadata found — not the schema.org offers agents parse" not in result.evidence
    assert any("disagrees with the page's own visible price text" in line for line in result.evidence)
