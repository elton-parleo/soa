"""
A price whose attributed_product names a brand Layer 2 stored in
other_brands_named is that brand's, never ours, whatever size or count phrase
it carries: absent / other_brand. A claim that also names our brand keeps its
ordinary path. No Layer 2 change: this reads what Layer 2 stored.
"""
from scoring import expectation_comparator as cmp
from soa_shared import expected_answers as ea

S3 = {'variant_id': 'snug-fit-overnight-s3', 'attribution': ['Size 3'],
      'attribution_rivals': ['Size 4', 'Size 5', 'Size 6']}
FACTS = {'brand': 'Wiggle & Snug', 'product_titles': ['Snug-Fit Overnight Diapers']}


def _ext(prices=(), member=(), others=()):
    return {'prices': [{'amount': a, 'currency': None, 'attributed_product': p} for a, p in prices],
            'member_prices': [{'amount': a, 'tier': 'Member+', 'attributed_product': p} for a, p in member],
            'other_brands_named': [{'name': n, 'presented_as': 'comparison', 'relation': r}
                                   for n, r in others]}


def _judge(expectation, extraction):
    return cmp.compare(expectation, extraction, source_ref=S3, brand_facts=FACTS)


def test_another_brands_size_3_is_not_our_size_3():
    v = _judge(ea.price('23.99'), _ext([('15.49', 'Huggies Size 3')], others=[('Huggies', 'comparison')]))
    assert (v.outcome, v.reason_code) == ('absent', 'other_brand')


def test_a_relation_layer_2_did_not_label_still_counts():
    v = _judge(ea.price('23.99'), _ext([('15.49', 'Huggies Size 3')], others=[('Huggies', None)]))
    assert (v.outcome, v.reason_code) == ('absent', 'other_brand')


def test_the_member_price_path_too():
    v = _judge(ea.member_price('17.79', 'Member+'),
               _ext(member=[('12.00', 'Pampers Swaddlers Size 3')], others=[('Pampers', 'closest_match_described')]))
    assert (v.outcome, v.reason_code) == ('absent', 'other_brand')


def test_a_claim_naming_both_brands_keeps_its_ordinary_path():
    v = _judge(ea.price('23.99'), _ext([('23.99', 'Wiggle & Snug vs Huggies Size 3')],
                                       others=[('Huggies', 'comparison')]))
    assert (v.outcome, v.reason_code) == ('exact', None)


def test_not_a_brand_and_our_own_brand_are_never_other_brands():
    v = _judge(ea.price('23.99'), _ext([('23.99', 'Amazon Size 3')], others=[('Amazon', 'not_a_brand')]))
    assert v.outcome == 'exact'
    v = _judge(ea.price('23.99'), _ext([('23.99', 'Wiggle & Snug Size 3')], others=[('Wiggle & Snug', None)]))
    assert v.outcome == 'exact'


def test_no_other_brands_stored_changes_nothing():
    v = _judge(ea.price('23.99'), _ext([('15.49', 'Huggies Size 3')]))
    assert v.outcome == 'wrong'
