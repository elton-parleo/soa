"""
2V-3 Q1: an external seller's one-variant product is asked about at its size.

Petco's first cycle (FL17) asked "What does the Purina ONE Lamb & Rice Formula
Dry Dog Food cost at Petco?", with no size, because a single-variant product
has no variant display. The agents priced the 8 lb bag, not the 31.1 lb one,
and were scored wrong. The record is Petco-shaped here (one variant per row,
a feed label per variant). Prices and GTINs are fictional.

Brand mode (an external brand, Pampers-shaped) and the hosted seller (Wiggle &
Snug) are pinned to the text they produced before the change.
"""
import json
import os

from clients.truesync_catalog import build_snapshot, merge_merchant_record
from generation import catalog_tiers as ct
from tests.test_external_mode_generation import snapshot_of

K = dict(category='Pet Supplies', persona='Value-Conscious Pet Owner', study_pattern='brand_at_retail')

PETCO_ROWS = [
    # (title, brand, label, price)
    ('Purina ONE Lamb & Rice Formula Dry Dog Food', 'Purina ONE', '31.1 lb', '49.99'),
    ('Greenies Original Regular Dental Dog Treats', 'Greenies', '36 ct, 36 oz', '44.99'),
    ('JustFoodForDogs Beef & Russet Potato Fresh Dog Food', 'JustFoodForDogs', '7 x 18 oz', '84.99'),
    ('Tidy Cats Free & Clean Unscented Clumping Litter', 'Tidy Cats', '', '19.99'),
    ('NexGard Chewables for Dogs', 'NexGard', 'NexGard Chewables for Dogs', '69.99'),
    ('Blue Buffalo Life Protection Adult Chicken', 'Blue Buffalo', 'Chicken', '29.99'),
]


def _petco():
    listings = []
    for i, (title, brand, label, price) in enumerate(PETCO_ROWS, start=1):
        gtin = f'0099000200{i:04d}'
        listings.append({'listing_id': i, 'title': title, 'brand': brand, 'variants': [
            {'variant_id': gtin, 'title': label or None, 'list_price': price, 'currency': 'USD', 'gtin': gtin}]})
    snap = build_snapshot({'merchant': 'petco', 'listings': listings},
                          merchants=[{'slug': 'petco', 'display_name': 'Petco', 'domain': 'petco.com'}])
    merge_merchant_record(snap, merchant={'slug': 'petco', 'name': 'Petco', 'domain': 'petco.com',
                                          'kind': 'seller', 'hosting': 'external'},
                          retailers={'own_domain': 'petco.com', 'domains': []},
                          feed={'rows': [{'gtin14': v.variant_id, 'retailers': [
                              {'domain': 'petco.com', 'url': f'https://www.petco.com/p/{v.variant_id}'}]}
                              for _p, v in snap.variants()]})
    return snap


def _accuracy(snap):
    rows, _ = ct.build_catalog_accuracy(snap, **K)
    return [r['query_text'] for r in rows]


def test_the_catalog_question_names_the_size_the_record_prices():
    assert _accuracy(_petco()) == [
        'What does the Purina ONE Lamb & Rice Formula Dry Dog Food, 31.1 lb cost at Petco?',
        'What does the Greenies Original Regular Dental Dog Treats, 36 ct, 36 oz cost at Petco?',
        'What does the JustFoodForDogs Beef & Russet Potato Fresh Dog Food, 7 x 18 oz cost at Petco?',
        # empty label, a label repeating the title, a label stating no size: as today
        'What does the Tidy Cats Free & Clean Unscented Clumping Litter cost at Petco?',
        'What does the NexGard Chewables for Dogs cost at Petco?',
        'What does the Blue Buffalo Life Protection Adult Chicken cost at Petco?',
    ]


def test_where_to_buy_and_cheapest_place_name_the_size():
    rows, _ = ct.build_intent_questions(_petco(), **K)
    texts = [r['query_text'] for r in rows if r['source_ref']['intent'] in ct.ABSORBED_INTENTS]
    assert 'Where can I buy Purina ONE Lamb & Rice Formula Dry Dog Food, 31.1 lb?' in texts
    assert 'Cheapest place to buy JustFoodForDogs Beef & Russet Potato Fresh Dog Food, 7 x 18 oz?' in texts
    assert 'Where can I buy Tidy Cats Free & Clean Unscented Clumping Litter?' in texts


def test_value_questions_name_the_size():
    snap = _petco()
    snap.products[0].variants[0].points_rules = [{'points': 250, 'program_name': 'Petco Perks'}]
    snap.products[1].variants[0].member_price = '40.49'
    snap.products[1].variants[0].member_tier_name = 'Vital Care'
    rows, _ = ct.build_value_incentives(snap, **K)
    assert [r['query_text'] for r in rows] == [
        'What do Vital Care members pay for the Greenies Original Regular Dental Dog Treats, 36 ct, 36 oz?',
        'How many Petco Perks points does the Purina ONE Lamb & Rice Formula Dry Dog Food, 31.1 lb earn?',
    ]


def test_a_label_that_starts_with_the_title_contributes_only_its_size():
    snap = _petco()
    snap.products[0].variants[0].attributes['label'] = 'Purina ONE Lamb & Rice Formula Dry Dog Food, 31.1 lb'
    assert _accuracy(snap)[0] == 'What does the Purina ONE Lamb & Rice Formula Dry Dog Food, 31.1 lb cost at Petco?'


# ── brand mode and the hosted seller are pinned ────────────────────────────

def test_an_external_brand_is_named_as_before():
    # A brand's single-variant row is not given its label: brand mode must not change.
    snap = _petco()
    snap.merchant_kind = 'brand'
    assert ct.single_variant_size(snap, snap.products[0], snap.products[0].variants[0]) == ''
    brand = snapshot_of('brand_two_retailers.json')
    assert _accuracy(brand) == [
        'What does the Acme Baby Swaddle Diapers Size 3 cost at Target?',
        'What does the Acme Baby Swaddle Diapers Size 3 value pack cost at Walmart?',
        'What does the Acme Baby Swaddle Diapers Size 4 cost at Walmart?',
    ]


def test_a_multi_variant_seller_product_is_named_as_before():
    assert _accuracy(snapshot_of('external_seller.json')) == [
        'What does the Trailmix Adult Dog Food Chicken & Rice 35 lb cost at Acme Pets?',
        'What does the Trailmix Adult Dog Food Lamb & Rice 35 lb cost at Acme Pets?',
    ]


def test_wiggle_and_snug_is_named_as_before():
    path = os.path.join(os.path.dirname(__file__), 'fixtures', 'wiggle_and_snug_catalog.json')
    with open(path) as fh:
        p = json.load(fh)
    snap = build_snapshot(p['catalog'], merchants=p['merchants'], incentives=p['incentives'],
                          price_history=p['price_history'])
    texts = _accuracy(snap)
    assert 'What does the Wiggle & Snug Cloud Wipes 3-Pack cost?' in texts
    assert all(', ' not in t.split(' cost')[0] for t in texts), texts
