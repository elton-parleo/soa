"""
2V-3 Q5: the Overview's product rows of an external seller are named as its
Product record names them: the feed's product name and the variant label.

FL17's /overview read "30 lb", "36 ct, 36 oz", "31.1 lb", two rows both
"30 lb". The feed here is the one 2V-2 recorded from supply on the Petco
fixture (tests/fixtures/console/supply_2v2/feed.json). A brand's rows are not
renamed: name_products is called for a seller_external merchant only
(console_manufacturer.brand_overview), and test_console_2u5's recorded
Pampers overview pins the brand.
"""
import json
import os

from app.services import console_brand_overview as bo
from app.services import console_product_record as pr

FEED = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'supply_2v2', 'feed.json')


def _feed_rows():
    with open(FEED) as fh:
        return json.load(fh)['body']['rows']


def test_record_name_is_the_product_name_and_the_variant():
    assert pr.record_name('Purina Pro Plan Sensitive Skin & Stomach', '30 lb') == \
        'Purina Pro Plan Sensitive Skin & Stomach, 30 lb'
    # a label that leads with the name does not repeat it
    assert pr.record_name('Pampers Swaddlers', 'Pampers Swaddlers, Newborn, 84 ct') == 'Pampers Swaddlers, Newborn, 84 ct'
    assert pr.record_name(None, '30 lb') == '30 lb'
    assert pr.record_name('Tidy Cats', '') == 'Tidy Cats'


def test_the_seller_s_rows_are_named_by_the_feed():
    products = [{'sku': '2579466', 'name': '30 lb'}, {'sku': '3089211', 'name': '17 lb'},
                {'sku': '2174511', 'name': '36 ct'}, {'sku': 'not-in-feed', 'name': '8 lb'}]
    assert [p['name'] for p in bo.name_products(products, _feed_rows())] == [
        'Purina Pro Plan Sensitive Skin & Stomach Salmon & Rice, 30 lb',
        'Tidy Cats LightWeight 24/7 Performance, 17 lb',
        'Greenies Original Regular Dental Treats, 36 ct',
        '8 lb',
    ]


def test_two_rows_with_one_label_are_two_names():
    rows = [{'sku': 'a', 'product_name': 'Purina Pro Plan Sensitive Skin & Stomach', 'variant_label': '30 lb'},
            {'sku': 'b', 'product_name': 'Purina Pro Plan Large Breed', 'variant_label': '30 lb'}]
    named = bo.name_products([{'sku': 'a', 'name': '30 lb'}, {'sku': 'feed_sku:b', 'name': '30 lb'}], rows)
    assert len({p['name'] for p in named}) == 2


def test_a_gtin_row_is_found_by_its_gtin14():
    rows = [{'sku': '7', 'gtin': '17800149501', 'product_name': 'Purina ONE Lamb & Rice Formula', 'variant_label': '31.1 lb'}]
    (p,) = bo.name_products([{'sku': '00017800149501', 'name': '31.1 lb'}], rows)
    assert p['name'] == 'Purina ONE Lamb & Rice Formula, 31.1 lb'


def test_record_sub_is_unchanged():
    v = {'label': 'Pampers Swaddlers, Newborn, 84 ct', 'product_name': 'Pampers Swaddlers'}
    assert pr.record_sub(v, None) == 'Newborn, 84 ct'
