"""
2V-0: an external seller's value-tier questions name each product by its own
brand, and the per-dollar question names the store.

Live (Petco, a seller with a 10-SKU, 9-brand feed), every points question
carried the first feed row's brand ("the Purina Pro Plan Purina ONE Lamb &
Rice ..."), doubled on that brand's own rows, because the value tier named a
product with snapshot.brand. A fictional two-brand seller here: Northpaw, whose
title starts with its brand, and Trailmix, whose title does not. Northpaw is
the first row, so snapshot.brand is Northpaw, as Purina Pro Plan was Petco's.

The brand fixtures (Wiggle & Snug, a hosted Pampers) are pinned to the text
they produced before the change.

2V-3: each seller product here is one variant whose label states a size, so
every subject now ends with it (", 30 lb"). test_subject_size_2v3.py.
"""
import json
import os

from clients.truesync_catalog import build_snapshot, merge_merchant_record
from generation import catalog_tiers as ct

K = dict(category='Pet Supplies', persona='Value-Conscious Pet Owner', study_pattern='brand_at_retail')
NORTHPAW = 'Northpaw Salmon & Rice Adult Dog Food'
TRAILMIX = 'Adult Dog Food'


def _seller():
    catalog = {'merchant': 'acme-pets', 'listings': [
        {'listing_id': 1, 'title': NORTHPAW, 'brand': 'Northpaw', 'variants': [
            {'variant_id': '00990001100031', 'title': '30 lb', 'list_price': '64.99', 'currency': 'USD',
             'gtin': '00990001100031'}]},
        {'listing_id': 2, 'title': TRAILMIX, 'brand': 'Trailmix', 'variants': [
            {'variant_id': '00990001100017', 'title': 'Chicken & Rice 35 lb', 'list_price': '74.98',
             'currency': 'USD', 'gtin': '00990001100017'}]},
    ]}
    snap = build_snapshot(catalog, merchants=[{'slug': 'acme-pets', 'display_name': 'Acme Pets',
                                               'domain': 'acme-pets.test'}])
    merge_merchant_record(snap, merchant={'slug': 'acme-pets', 'name': 'Acme Pets', 'domain': 'acme-pets.test',
                                          'kind': 'seller', 'hosting': 'external'},
                          retailers={'own_domain': 'acme-pets.test', 'domains': []},
                          feed={'rows': [{'gtin14': v.variant_id, 'retailers': [
                              {'domain': 'acme-pets.test', 'url': f'https://www.acme-pets.test/p/{v.variant_id}'}]}
                              for _p, v in snap.variants()]})
    for product in snap.products:
        product.variants[0].points_rules = [{'points': 120, 'program_name': 'Acme Perks'}]
    snap.products[0].variants[0].points_rules.append({'points_multiplier': '2', 'program_name': 'Acme Perks'})
    return snap


def _value_texts(snap):
    rows, _ = ct.build_value_incentives(snap, **K)
    return [r['query_text'] for r in rows]


def _intent_texts(snap):
    rows, _ = ct.build_intent_questions(snap, **K)
    return [r['query_text'] for r in rows if r['source_ref']['intent'] in ct.ABSORBED_INTENTS]


def test_the_fixture_is_the_petco_shape():
    snap = _seller()
    assert snap.is_external and snap.merchant_kind == 'seller'
    assert snap.brand == 'Northpaw'            # the first row's, as Purina Pro Plan was Petco's
    assert snap.study_brand == 'Acme Pets'


def test_a_sellers_points_questions_name_each_product_by_its_own_brand_once():
    assert _value_texts(_seller()) == [
        'How many Acme Perks points does the Northpaw Salmon & Rice Adult Dog Food, 30 lb earn?',
        'How many Acme Perks points do you earn per dollar at Acme Pets?',
        'How many Acme Perks points does the Trailmix Adult Dog Food, Chicken & Rice 35 lb earn?',
    ]


def test_a_sellers_brand_direct_questions_name_each_product_by_its_own_brand_once():
    assert _intent_texts(_seller()) == [
        'Where can I buy Northpaw Salmon & Rice Adult Dog Food, 30 lb?',
        'Where can I buy Trailmix Adult Dog Food, Chicken & Rice 35 lb?',
        'Cheapest place to buy Northpaw Salmon & Rice Adult Dog Food, 30 lb?',
        'Cheapest place to buy Trailmix Adult Dog Food, Chicken & Rice 35 lb?',
    ]


def test_no_seller_question_names_the_other_brand_or_a_brand_twice():
    snap = _seller()
    for text in _value_texts(snap) + _intent_texts(snap):
        assert 'Northpaw Northpaw' not in text, text
        if TRAILMIX in text and NORTHPAW not in text:
            assert 'Northpaw' not in text, text
        if NORTHPAW in text:
            assert 'Trailmix' not in text, text


def test_the_per_dollar_question_falls_back_to_the_stores_domain_name():
    snap = _seller()
    snap.display_name = None
    texts = _value_texts(snap)
    assert 'Northpaw products' not in ' '.join(texts)
    assert any(t.startswith('How many Acme Perks points do you earn per dollar at ') for t in texts)


# ── the brand fixtures produce the text they did before ────────────────────

def test_wiggle_and_snug_value_tier_is_unchanged():
    path = os.path.join(os.path.dirname(__file__), 'fixtures', 'wiggle_and_snug_catalog.json')
    with open(path) as fh:
        p = json.load(fh)
    snap = build_snapshot(p['catalog'], merchants=p['merchants'], incentives=p['incentives'],
                          price_history=p['price_history'])
    assert _value_texts(snap) == [
        'Is there a first-order promo code for Wiggle & Snug, and what does it take off?',
        'Are there any promo codes for Wiggle & Snug Snug-Fit Diapers right now, and what do they take off?',
        'What do Member+ members pay for the Wiggle & Snug Snug-Fit Overnight Diapers Size 3?',
        'What do Member+ members pay for the Wiggle & Snug Cloud Wipes 3-Pack?',
        'What do Member+ members pay for the Wiggle & Snug Snug-Fit Trial Pack?',
        'How many Member Rewards points do you earn per dollar on Wiggle & Snug products?',
    ]
    assert _intent_texts(snap)[0] == 'Where can I buy Wiggle & Snug Snug-Fit Diapers Size 1 small pack?'


def test_a_hosted_pampers_value_tier_is_unchanged():
    # A hosted brand is named by snapshot.brand, as before. Its line titles
    # start with the brand, so the fixed-points subject still reads
    # "Pampers Pampers": pinned as it was, not fixed here (2V-0 is sellers).
    catalog = {'merchant': 'pampers', 'listings': [
        {'listing_id': 1, 'title': 'Pampers Swaddlers', 'brand': 'Pampers', 'variants': [
            {'variant_id': 'sw-1', 'title': 'Size 1, 96 ct', 'count': 96, 'list_price': '29.99', 'currency': 'USD'}]},
        {'listing_id': 2, 'title': 'Pampers Zzz', 'brand': 'Pampers', 'variants': [
            {'variant_id': 'zzz-4', 'title': 'Size 4, 104 ct', 'count': 104, 'list_price': '29.99',
             'currency': 'USD'}]},
    ]}
    snap = build_snapshot(catalog, merchants=[{'slug': 'pampers', 'display_name': 'Pampers', 'domain': 'pampers.com'}],
                          merchant_slug='pampers')
    for product in snap.products:
        product.variants[0].points_rules = [{'points': 50, 'program_name': 'Pampers Club'}]
    snap.products[0].variants[0].points_rules.append({'points_multiplier': '2', 'program_name': 'Pampers Club'})
    assert _value_texts(snap) == [
        'How many Pampers Club points does the Pampers Pampers Swaddlers earn?',
        'How many Pampers Club points do you earn per dollar on Pampers products?',
        'How many Pampers Club points does the Pampers Pampers Zzz earn?',
    ]
