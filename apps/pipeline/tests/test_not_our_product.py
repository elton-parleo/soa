"""
§3 rule 2 narrowed (list and member price): variant_clash needs OUR product named and a
variant descriptor the record lacks. Anything else that conflicts with the
asked variant and names no record variant scores as main did: absent.
"""
import json
import os

from clients.truesync_catalog import build_snapshot
from scoring import expectation_comparator as cmp
from scoring import record_variants as rv
from soa_shared import expected_answers as ea

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')
S3 = {'merchant_slug': 'wiggle-and-snug', 'variant_id': 'snug-fit-overnight-s3',
      'attribution': ['Size 3'], 'attribution_rivals': ['Size 4', 'Size 5', 'Size 6']}


def _variants():
    with open(os.path.join(FIXTURES, 'wiggle_and_snug_catalog.json')) as fh:
        ws = json.load(fh)
    return rv.from_snapshot(build_snapshot(ws['catalog'], merchants=ws['merchants'],
                                           incentives=ws['incentives'],
                                           price_history=ws['price_history']))


def _price(amount, product):
    return {'prices': [{'amount': amount, 'currency': None, 'attributed_product': product}],
            'member_prices': []}


def _judge(expectation, extraction):
    return cmp.compare(expectation, extraction, source_ref=S3, record_variants=_variants())


def test_another_brand_is_not_our_product():
    v = _judge(ea.price('23.99'), _price('14.99', 'Huggies Overnites'))
    assert (v.outcome, v.reason_code) == ('absent', 'not_our_product')


def test_an_unnamed_pack_is_not_our_product():
    v = _judge(ea.price('23.99'), _price('9.90', 'an $11.00 pack'))
    assert (v.outcome, v.reason_code) == ('absent', 'not_our_product')


def test_our_product_with_no_variant_stated_is_dropped_as_on_main():
    v = _judge(ea.price('23.99'), _price('21.99', 'Wiggle & Snug Snug-Fit Overnight Diapers'))
    assert (v.outcome, v.reason_code) == ('absent', None)


def test_our_product_with_a_count_the_record_lacks_is_a_variant_clash():
    v = _judge(ea.price('23.99'), _price('44.99', 'Snug-Fit Overnight Diapers 300 ct'))
    assert (v.outcome, v.reason_code) == ('wrong', 'variant_clash')


def test_a_brand_alias_names_our_product():
    assert rv.names_our_product('Wiggle and Snug nappies, Size 7', _variants())
    assert not rv.names_our_product('eligible purchases made at Costco', _variants())


def test_the_member_path_uses_the_same_rule():
    extraction = {'prices': [], 'member_prices': [
        {'amount': '2', 'tier': 'Member+', 'attributed_product': 'eligible purchases made at Costco'}]}
    v = _judge(ea.member_price('17.79', 'Member+'), extraction)
    assert (v.outcome, v.reason_code) == ('absent', 'not_our_product')
    extraction['member_prices'][0]['attributed_product'] = 'Snug-Fit Overnight Diapers 300 ct'
    v = _judge(ea.member_price('17.79', 'Member+'), extraction)
    assert (v.outcome, v.reason_code) == ('wrong', 'variant_clash')
