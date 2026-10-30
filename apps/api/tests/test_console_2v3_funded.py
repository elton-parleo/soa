"""
2V-3 Q6: Funded offers measures the catalog-built cheapest-place rows.

FL17's Prove -> Funded offers read "Promo pass-through is not measured for
this cycle. This cycle asked no cheapest-place question." The study had ten:
the catalog-built cheapest-place rows, which the console files under the
brand-direct tier. The seller's Prove now carries promo_pass_through over
the cheapest-place answers, found by each row's source (provenance 'catalog'
and source_ref.intent, rm.catalog_intent), never by its tier label. The price
paths are the ones 2V-2 recorded from supply on the Petco fixture.
"""
import json
import os

from app.services import console_read_models as rm
from app.services import console_seller as cs

PATHS = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'supply_2v2', 'price-paths.json')


def _paths():
    with open(PATHS) as fh:
        body = json.load(fh)['body']
    return body.get('skus') or body.get('rows') or []


def test_a_catalog_built_row_is_found_by_its_source_whatever_its_tier():
    ref = {'intent': 'cheapest_place', 'variant_id': 'sku:2579466'}
    assert rm.catalog_intent(ref, 'catalog', 'brand_direct') == 'cheapest_place'
    assert rm.catalog_intent(json.dumps(ref), 'catalog', None) == 'cheapest_place'
    assert rm.catalog_intent(ref, 'catalog', 'category_control') == 'cheapest_place'
    # a row from before provenance was stored counts by its tier, as it did
    assert rm.catalog_intent(ref, None, 'brand_direct') == 'cheapest_place'
    # an AI-written row with no intent, or one that is not catalog-built, is not one
    assert rm.catalog_intent({}, 'catalog', 'brand_direct') is None
    assert rm.catalog_intent(ref, 'ai', 'brand_direct') is None


def test_funded_offers_measures_the_cheapest_place_answers():
    paths = _paths()
    purina = next(r for r in paths if (r['price_path']['steps'] or [{}])[0].get('funded_by') == 'purina')
    first = purina['price_path']['steps'][0]['price']
    name = purina.get('product_name') or purina.get('title')
    answers = [
        {'intent': 'cheapest_place', 'text': f"{name} is ${first} on your first Autoship order at Petco."},
        {'intent': 'cheapest_place', 'text': f"{name} is cheapest at Chewy."},
        {'intent': 'cheapest_place', 'text': 'Tidy Cats is $19.99 at Walmart.'},
        {'intent': 'where_to_buy', 'text': f"{name} at Petco, ${first} on Autoship."},
        {'intent': None, 'text': f"{name} ${first}"},
    ]
    passed = cs.funded_pass_through(paths=paths, answers=answers)
    assert passed == {'n': 2, 'k': 1, 'asked': 3, 'intent': 'cheapest_place', 'source': 'catalog'}


def test_not_measured_only_when_no_cheapest_place_question_was_asked():
    assert cs.funded_pass_through(paths=_paths(), answers=[{'intent': 'where_to_buy', 'text': 'x'}]) is None
