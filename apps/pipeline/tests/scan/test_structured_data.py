"""
Stage 25 (Part 2, P1): direct unit tests for structured_data.extract()'s
new visible_prices field — the "what the page's own text shows" half of
the price-consistency check (scorer.py's _price_consistency_mismatch
combines this with the structured Offer price). Full end-to-end fixture
tests for the check itself, run through score_price_truth_seen, live in
test_scorer.py.
"""
import json

import pytest

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


# ─── F1/F2: generic descent — nested product structures (hasVariant,
# isVariantOf, itemOffered, mainEntity, @graph) are visited wherever they
# appear, not just at the top level. ────────────────────────────────────

def _html_with_jsonld(data) -> str:
    return f'<html><body><script type="application/ld+json">{json.dumps(data)}</script></body></html>'


def _product_group_with_variants(offer_shape: str) -> dict:
    """offer_shape: 'dict' (a single Offer object) or 'list' (a one-item
    Offer array) — the real-world Vuori/Allbirds ProductGroup+hasVariant
    shape, either way a variant's own product markup declares offers."""
    def offer(price):
        o = {"@type": "Offer", "price": price, "priceCurrency": "USD", "availability": "https://schema.org/InStock"}
        return [o] if offer_shape == "list" else o

    return {
        "@context": "https://schema.org",
        "@type": "ProductGroup",
        "name": "Classic Tee",
        "hasVariant": [
            {"@type": "Product", "name": "Classic Tee - Blue - M", "sku": "TEE-BLU-M", "offers": offer("29.99")},
            {"@type": "Product", "name": "Classic Tee - Red - M", "sku": "TEE-RED-M", "offers": offer("34.99")},
        ],
    }


@pytest.mark.parametrize("offer_shape", ["dict", "list"])
def test_product_group_has_variant_extracts_variant_products_with_prices(offer_shape):
    """F2 a/b: a ProductGroup's hasVariant Products were previously
    invisible entirely (only the offer-less group itself was collected)
    — the generic descent now visits them regardless of whether each
    variant's own offers is a single dict or a one-item list."""
    html = _html_with_jsonld(_product_group_with_variants(offer_shape))
    extracted = structured_data.extract(html)

    assert len(extracted.products) == 3  # the group itself + 2 variants
    group = next(p for p in extracted.products if p.name == "Classic Tee")
    assert group.offers == []  # the group node itself declares no offers of its own

    blue = next(p for p in extracted.products if p.name == "Classic Tee - Blue - M")
    red = next(p for p in extracted.products if p.name == "Classic Tee - Red - M")
    assert blue.sku == "TEE-BLU-M"
    assert blue.offers[0].price == 29.99
    assert blue.offers[0].price_currency == "USD"
    assert red.offers[0].price == 34.99


def test_flat_product_with_offers_dict_is_unchanged():
    """F2c (control): a plain, non-variant Product still extracts exactly
    as before — the generic descent adds coverage, it doesn't change
    behavior for the shape that already worked."""
    html = _html_with_jsonld({
        "@context": "https://schema.org", "@type": "Product", "name": "Widget",
        "offers": {"@type": "Offer", "price": "19.99", "priceCurrency": "USD"},
    })
    extracted = structured_data.extract(html)

    assert len(extracted.products) == 1
    assert extracted.products[0].offers[0].price == 19.99


# ─── F2: Product.image ────────────────────────────────────────────────

def test_product_image_extracted_as_a_plain_string():
    html = _html_with_jsonld({
        "@type": "Product", "name": "Widget",
        "image": "https://cdn.example.com/widget.jpg",
        "offers": {"@type": "Offer", "price": "19.99", "priceCurrency": "USD"},
    })
    extracted = structured_data.extract(html)
    assert extracted.products[0].image == "https://cdn.example.com/widget.jpg"


def test_product_image_takes_the_first_value_from_a_list():
    html = _html_with_jsonld({
        "@type": "Product", "name": "Widget",
        "image": ["https://cdn.example.com/a.jpg", "https://cdn.example.com/b.jpg"],
    })
    extracted = structured_data.extract(html)
    assert extracted.products[0].image == "https://cdn.example.com/a.jpg"


def test_product_image_extracted_from_an_imageobject_url():
    html = _html_with_jsonld({
        "@type": "Product", "name": "Widget",
        "image": {"@type": "ImageObject", "url": "https://cdn.example.com/imageobject.jpg"},
    })
    extracted = structured_data.extract(html)
    assert extracted.products[0].image == "https://cdn.example.com/imageobject.jpg"


def test_product_image_is_none_when_absent():
    html = _html_with_jsonld({
        "@type": "Product", "name": "Widget",
        "offers": {"@type": "Offer", "price": "19.99", "priceCurrency": "USD"},
    })
    extracted = structured_data.extract(html)
    assert extracted.products[0].image is None


def test_product_with_aggregate_offer_does_not_regress_to_zero_products():
    """F2d: AggregateOffer (lowPrice/highPrice) isn't parsed by
    _extract_offer's price/priceSpecification reads today — this fixture
    documents that actual, current partial support (offer.price stays
    None) rather than asserting a scoring outcome this stage never
    touched. What matters here is there's still exactly one product with
    one offer, never zero."""
    html = _html_with_jsonld({
        "@type": "Product", "name": "Multi Tee",
        "offers": {"@type": "AggregateOffer", "lowPrice": "19.99", "highPrice": "39.99", "priceCurrency": "USD", "offerCount": 3},
    })
    extracted = structured_data.extract(html)

    assert len(extracted.products) == 1
    assert len(extracted.products[0].offers) == 1
    assert extracted.products[0].offers[0].price is None  # documented gap, not this stage's fix
    assert extracted.products[0].offers[0].price_currency == "USD"


def test_graph_wrapped_product_group_matches_the_unwrapped_shape():
    """F2e: regression guard for folding the old explicit @graph special
    case into the generic descent — a @graph-wrapped hasVariant blob
    must extract identically to the same blob unwrapped."""
    wrapped = _html_with_jsonld({"@context": "https://schema.org", "@graph": [_product_group_with_variants("dict")]})
    unwrapped = _html_with_jsonld(_product_group_with_variants("dict"))

    wrapped_names = sorted(p.name for p in structured_data.extract(wrapped).products)
    unwrapped_names = sorted(p.name for p in structured_data.extract(unwrapped).products)
    assert wrapped_names == unwrapped_names == ["Classic Tee", "Classic Tee - Blue - M", "Classic Tee - Red - M"]


def test_deeply_nested_blob_returns_without_raising_and_respects_depth_guard():
    """F2f (deep, non-cyclic): 20 levels of legitimate nesting — well past
    _MAX_JSONLD_DEPTH (12) — must never raise; the guard silently stops
    descending rather than exhausting the stack."""
    node = {"@type": "Thing", "name": "leaf"}
    for i in range(20):
        node = {"@type": "Thing", "name": f"level-{i}", "child": node}
    html = _html_with_jsonld(node)

    extracted = structured_data.extract(html)  # must not raise
    assert isinstance(extracted, structured_data.ExtractedData)


def test_self_referencing_dict_fed_directly_to_walk_never_raises_or_hangs():
    """F2f (cyclic): JSON itself can't encode a cycle, so this constructs
    one directly in Python and calls _walk_jsonld_node — the actual
    unit under the never-raises contract — to prove the depth guard
    holds against a genuinely circular object, not just a deep tree."""
    cyclic = {"@type": "Product", "name": "Loop"}
    cyclic["self"] = cyclic

    extracted = structured_data.ExtractedData()
    structured_data._walk_jsonld_node(cyclic, extracted)  # must return, not raise or hang

    assert len(extracted.products) >= 1
    assert extracted.products[0].name == "Loop"


def test_member_price_on_a_variant_product_is_detected_via_the_variants_own_call():
    """F2g: a memberPrice field on a hasVariant Product (not the group)
    must be detected — _detect_member_price_structure is called with each
    node's own fields as _walk_jsonld_node visits it, so a variant's
    memberPrice was always structurally supported once the variant itself
    is actually visited."""
    html = _html_with_jsonld({
        "@type": "ProductGroup", "name": "Loyalty Tee",
        "hasVariant": [{
            "@type": "Product", "name": "Loyalty Tee - Blue - M",
            "offers": {"@type": "Offer", "price": "29.99", "priceCurrency": "USD"},
            "memberPrice": {"@type": "PriceSpecification", "price": "24.99"},
        }],
    })
    extracted = structured_data.extract(html)

    group = next(p for p in extracted.products if p.name == "Loyalty Tee")
    variant = next(p for p in extracted.products if p.name == "Loyalty Tee - Blue - M")
    assert variant.has_member_price_hint is True
    assert group.has_member_price_hint is False  # the group itself has no memberPrice/offers of its own


def test_offers_are_never_collected_as_free_floating_nodes():
    """F1's explicit guard: an Offer reachable via generic descent (e.g.
    nested under a ProductGroup that isn't itself under a Product/
    ProductGroup ancestor) must never be appended as its own product —
    only Product/ProductGroup-typed nodes ever produce a ProductData."""
    html = _html_with_jsonld({
        "@type": "ItemList",
        "itemListElement": [
            {"@type": "Offer", "price": "9.99", "priceCurrency": "USD"},
        ],
    })
    extracted = structured_data.extract(html)
    assert extracted.products == []


# ─── F5: OG/product: social-preview price meta — evidence-only ─────────

def test_og_price_meta_detected_from_og_price_amount():
    html = '<html><head><meta property="og:price:amount" content="29.99"></head><body></body></html>'
    assert structured_data.extract(html).og_price_meta_present is True


def test_og_price_meta_detected_from_product_price_amount():
    html = '<html><head><meta property="product:price:amount" content="29.99"></head><body></body></html>'
    assert structured_data.extract(html).og_price_meta_present is True


def test_og_price_meta_absent_when_no_matching_meta_tag():
    html = '<html><head><meta property="og:title" content="Widget"></head><body></body></html>'
    assert structured_data.extract(html).og_price_meta_present is False


def test_og_price_meta_ignored_when_content_is_empty():
    html = '<html><head><meta property="og:price:amount" content=""></head><body></body></html>'
    assert structured_data.extract(html).og_price_meta_present is False


# ─── Never-raises fuzz: malformed variants of the hasVariant fixture ────

_MALFORMED_VARIANT_BLOBS = [
    # hasVariant isn't a list at all
    {"@type": "ProductGroup", "name": "Tee", "hasVariant": {"@type": "Product", "name": "Tee - M"}},
    # hasVariant entries aren't dicts
    {"@type": "ProductGroup", "name": "Tee", "hasVariant": ["not-a-product", 42, None, True]},
    # a variant's own offers is a malformed type
    {"@type": "ProductGroup", "name": "Tee", "hasVariant": [{"@type": "Product", "name": "Tee - M", "offers": "free-text, not an object"}]},
    # a variant's offers is a list containing non-dict entries
    {"@type": "ProductGroup", "name": "Tee", "hasVariant": [{"@type": "Product", "name": "Tee - M", "offers": [None, "x", 1, {"@type": "Offer", "price": "9.99"}]}]},
    # hasVariant contains itself again (a real, JSON-encodable — non-
    # cyclic — repeat), nested a few levels
    {"@type": "ProductGroup", "name": "Tee", "hasVariant": [{"@type": "ProductGroup", "name": "Tee Jr", "hasVariant": [{"@type": "Product", "name": "Tee - S"}]}]},
    # price/priceCurrency on a variant offer are the wrong type
    {"@type": "ProductGroup", "name": "Tee", "hasVariant": [{"@type": "Product", "name": "Tee - M", "offers": {"@type": "Offer", "price": {"nested": "object"}, "priceCurrency": 12345}}]},
    # @type itself malformed on a variant
    {"@type": "ProductGroup", "name": "Tee", "hasVariant": [{"@type": {"not": "a string or list"}, "name": "Tee - M"}]},
    # empty / null variants
    {"@type": "ProductGroup", "name": "Tee", "hasVariant": []},
    {"@type": "ProductGroup", "name": "Tee", "hasVariant": None},
]


@pytest.mark.parametrize("blob", _MALFORMED_VARIANT_BLOBS, ids=range(len(_MALFORMED_VARIANT_BLOBS)))
def test_extract_never_raises_on_malformed_variants_of_the_has_variant_fixture(blob):
    html = _html_with_jsonld(blob)
    extracted = structured_data.extract(html)  # must not raise
    assert isinstance(extracted, structured_data.ExtractedData)
