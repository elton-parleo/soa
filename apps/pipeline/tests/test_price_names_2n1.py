"""
2N-1 (B3): variant-name false positives in the price check, from FL14's True
Value and the TrueSync readback, each quoted string against its reference.

  * "$27.97 for Pampers Swaddlers Fragrance-Free Baby Diapers, Size 1, 96
    Count" against Walmart's $27.97 read "Wrong, a size or pack the record
    does not have": that is Walmart's own title for the variant. A quoted
    name is a sibling only when it names another line or size (Sensitive,
    Overnights, Pure, Ultra, another Size or count); descriptors are not
    variants; a name contained in the retailer page's own title is that
    variant. The Walmart cell reads Exact.
  * "$27.97 for the NB 84-count option" read "price wasn't for this
    product". It is the product: "not ours" needs another product's name,
    never a pronoun or a description of ours.
  * "$0.33 for per diaper" read "price wasn't for this product". A per-unit
    quote is its own outcome, per_unit, outside scored and outside wrong.
"""
import pytest

from scoring import expectation_comparator as cmp
from scoring import record_variants as rv
from scoring import retailer_reference as rr
from soa_shared import expected_answers as ea

SWADDLERS = 'Pampers Swaddlers Diapers'
GTIN = {'nb': '00037000863434', 's1': '00037000863441', 's2': '00037000863458', 'sens1': '00037000700001'}


def _variant(key, title, size, count, group='swaddlers'):
    return rv.RecordVariant(variant_id=GTIN[key], group=group, text=f"{title} {size} {count} ct",
                            naming=[rv._tokens(size)], count=count, gtin=GTIN[key],
                            product_name=rv.name_tokens(title), brand={'pampers'})


VARIANTS = [_variant('nb', SWADDLERS, 'Newborn', 84), _variant('s1', SWADDLERS, 'Size 1', 96),
            _variant('s2', SWADDLERS, 'Size 2', 84),
            _variant('sens1', 'Pampers Sensitive Diapers', 'Size 1', 96, group='sensitive')]
REFS = {'nb': {'attribution': ['Newborn'], 'attribution_rivals': ['Size 1', 'Size 2']},
        's1': {'attribution': ['Size 1'], 'attribution_rivals': ['Newborn', 'Size 2']}}
WALMART_TITLE = 'Pampers Swaddlers Fragrance-Free Baby Diapers, Size 1, 96 Count'


def _reference(title=None):
    rows = [{'retailer_domain': 'walmart.com', 'gtin': GTIN[k], 'price': p, 'verifiable': True, 'read_status': 'ok',
             'method': 'json_ld', 'role': 'retailer', **({'name': title} if title and k == 's1' else {})}
            for k, p in (('nb', '27.97'), ('s1', '27.97'), ('s2', '27.97'), ('sens1', '31.47'))]
    return rr.ReferenceSet({'prices': rows})


def _judge(key, amount, product, *, title=None, spans=()):
    ref = {'merchant_slug': 'pampers', 'variant_id': GTIN[key], 'gtin': GTIN[key], **REFS[key]}
    extraction = {'prices': [{'amount': amount, 'currency': 'USD', 'attributed_product': product}], 'member_prices': [],
                  'spans': [{'id': i, 'text': t} for i, t in enumerate(spans)]}
    return cmp.compare(ea.price(None, attributed_to='walmart.com'), extraction, source_ref=ref,
                       record_variants=VARIANTS, reference=_reference(title))


@pytest.mark.parametrize('product', [
    WALMART_TITLE,
    'Pampers Swaddlers Wetness Indicator Diapers, Size 1, 96 Count',
    'Pampers Swaddlers Soft and Absorbent Disposable Diapers Size 1',
    'Pampers Swaddlers Baby Diapers Size 1 96 ct',
])
def test_descriptors_are_not_variants(product):
    v = _judge('s1', '27.97', product)
    assert (v.outcome, v.reason_code) == ('exact', None), product


def test_the_retailer_s_own_title_names_the_variant():
    # with Walmart's title on the row, a quoted name inside it is the variant
    v = _judge('s1', '27.97', 'Swaddlers Fragrance-Free Baby Diapers 96 Count', title=WALMART_TITLE)
    assert v.outcome == 'exact'
    assert rv.in_title(WALMART_TITLE, WALMART_TITLE) and not rv.in_title('Pampers Sensitive Size 1', WALMART_TITLE)


@pytest.mark.parametrize('product, target', [
    ('Pampers Sensitive Diapers Size 1 96 ct', 'swap'),          # another line
    ('Pampers Swaddlers Overnights Size 1', 'clash'),            # another line the record lacks
    ('Pampers Pure Protection Size 1', 'clash'),
    ('Pampers Swaddlers Size 2 84 ct', 'swap'),                  # another size
])
def test_another_line_or_size_is_still_a_sibling(product, target):
    v = _judge('s1', '27.97', product)
    assert v.outcome != 'exact' and v.claims[0]['target'] == target, (product, v.claims)


def test_a_description_of_ours_is_ours():
    v = _judge('nb', '27.97', 'the NB 84-count option')
    assert (v.outcome, v.reason_code) == ('exact', None)
    # a pronoun names no product: judged as the asked variant's, never "not ours"
    v = _judge('nb', '27.97', 'it')
    assert (v.outcome, v.reason_code) == ('exact', None)
    # another product's name is still not ours; an unnamed pack still names nothing of ours
    assert _judge('nb', '14.99', 'Huggies Little Snugglers').reason_code == 'not_our_product'
    assert _judge('nb', '9.90', 'an $11.00 pack').reason_code == 'not_our_product'


def test_a_per_unit_quote_is_its_own_outcome():
    v = _judge('s1', '0.33', 'per diaper')
    assert (v.outcome, v.reason_code, v.reason) == ('unscoreable', 'per_unit', 'per-diaper price, not comparable')
    assert v.claims[0]['outcome'] == 'per_unit'
    # the words after the amount say so, or it is under $2 against a pack over $10
    said = _judge('s1', '0.29', 'Pampers Swaddlers Size 1', spans=['That works out to $0.29 per diaper at Walmart.'])
    assert said.reason_code == 'per_unit'
    assert _judge('s1', '1.79', 'Pampers Swaddlers Size 1').reason_code == 'per_unit'
    # beside a pack quote, the pack quote speaks
    ref = {'merchant_slug': 'pampers', 'variant_id': GTIN['s1'], 'gtin': GTIN['s1'], **REFS['s1']}
    both = {'prices': [{'amount': '0.33', 'currency': 'USD', 'attributed_product': 'per diaper'},
                       {'amount': '27.97', 'currency': 'USD', 'attributed_product': 'Pampers Swaddlers Size 1'}],
            'member_prices': []}
    v = cmp.compare(ea.price(None, attributed_to='walmart.com'), both, source_ref=ref, record_variants=VARIANTS,
                    reference=_reference())
    assert v.outcome == 'exact'
