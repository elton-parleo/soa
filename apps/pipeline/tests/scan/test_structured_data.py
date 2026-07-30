"""
Stage 25 (Part 2, P1): direct unit tests for structured_data.extract()'s
new visible_prices field — the "what the page's own text shows" half of
the price-consistency check (scorer.py's _price_consistency_mismatch
combines this with the structured Offer price). Full end-to-end fixture
tests for the check itself, run through score_price_truth_seen, live in
test_scorer.py.
"""
import json

from scan import structured_data


def _page_with_jsonld_price(price: str) -> str:
    product = {
        "@context": "https://schema.org", "@type": "Product", "name": "Widget",
        "offers": {"@type": "Offer", "price": price, "priceCurrency": "USD"},
    }
    return f"""
    <html><head>
      <script type="application/ld+json">{json.dumps(product)}</script>
      <style>.price::before {{ content: "$999.99"; }}</style>
    </head><body>
      <h1>Widget</h1>
      <p>Now ${price}</p>
      <script>var trackingPrice = "$999.99";</script>
    </body></html>
    """


def test_visible_prices_extracts_the_single_dollar_price_in_body_text():
    extracted = structured_data.extract(_page_with_jsonld_price("29.99"))
    assert extracted.visible_prices == [29.99]


def test_visible_prices_excludes_script_and_style_contents():
    """Regression guard: without stripping script/style first, this page's
    JSON-LD price and the <style> block's content would leak into
    visible_prices as spurious matches (999.99), making the structured
    price trivially 'agree' with itself or falsely disagree with noise
    that was never actually shown to a shopper."""
    extracted = structured_data.extract(_page_with_jsonld_price("29.99"))
    assert 999.99 not in extracted.visible_prices


def test_visible_prices_is_empty_when_no_dollar_price_in_body_text():
    html = """
    <html><body>
      <script type="application/ld+json">{"@type": "Product", "name": "Widget"}</script>
      <h1>Widget</h1>
      <p>Contact us for pricing.</p>
    </body></html>
    """
    extracted = structured_data.extract(html)
    assert extracted.visible_prices == []


def test_visible_prices_collects_every_distinct_value_sorted():
    html = """
    <html><body>
      <p>Small: $19.99</p>
      <p>Large: $24.99</p>
      <p>Small: $19.99</p>
    </body></html>
    """
    extracted = structured_data.extract(html)
    assert extracted.visible_prices == [19.99, 24.99]


def test_visible_prices_requires_a_decimal_component():
    """A bare '$5' (e.g. '$5 off') shouldn't count as a priced amount for
    this check — requiring cents keeps the extraction confident rather
    than catching every dollar-sign mention on the page."""
    html = "<html><body><p>Get $5 off your first order!</p></body></html>"
    extracted = structured_data.extract(html)
    assert extracted.visible_prices == []


def test_extract_never_raises_on_malformed_html():
    assert structured_data.extract("<html><body><script>oops(").visible_prices == []
    assert structured_data.extract("").visible_prices == []
