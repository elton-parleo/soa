"""
2M-2: promo pass-through in the narratives. A cheapest-place answer that
named none of the deals live for its variant that day is a flagged answer
(`promo_missed`), the deal in its facts (deals_live_that_day), read from the
cycle's cached retailer-prices rows, which carry supply's `deals`
(parleo-supply-app 2M-2). Its own prompt, the demo's line; every other
answer's request is unchanged. No model.
"""
import filecmp
import os

from soa_shared import narratives as nv
from soa_shared import promo_pass_through as ppt

MERCHANT = nv.Merchant(name='Pampers', kind='brand', terms=('Pampers',))
MULTI = {'kind': 'multi_buy', 'text': 'save 40% on 1 when you buy 2', 'value': '40.00', 'value_unit': 'percent',
         'price': None, 'was_price': None, 'terms': 'when you buy 2', 'program': None,
         'evidence': 'Save 40% on 1 when you buy 2'}
ROWS = [
    {'variant_ref': 'feed_sku:amore_s1', 'gtin': None, 'sku': 'amore_s1', 'variant_label': 'Size 1, 132 ct',
     'retailer_domain': 'amazon.com', 'role': 'retailer', 'price': '47.99', 'deals': [MULTI]},
    {'variant_ref': 'feed_sku:amore_s1', 'gtin': None, 'sku': 'amore_s1', 'variant_label': 'Size 1, 132 ct',
     'retailer_domain': 'walmart.com', 'role': 'retailer', 'price': '45.97', 'deals': []},
    {'variant_ref': 'feed_sku:amore_s1', 'retailer_domain': 'pampers.com', 'role': 'own', 'price': None, 'deals': None},
]


def _run(text, intent='cheapest_place'):
    return {'id': 7, 'platform': 'perplexity', 'surface': 'grounded_api', 'answer_status': 'answered',
            'tier': 'brand_direct', 'raw_response': text, 'query_text': 'Cheapest place to buy Pampers AMORE Size 1?',
            'source_ref': {'intent': intent, 'variant_id': 'amore_s1', 'merchant_slug': 'pampers'}}


OUTCOME = {'outcome': 'grounded', 'extraction': {}}


def test_the_cached_rows_give_the_deals_shape():
    deals = ppt.deals_from_rows(ROWS)
    assert [(d['retailer_domain'], d['kind'], [v['sku'] for v in d['variants']]) for d in deals['deals']] == \
        [('amazon.com', 'multi_buy', ['amore_s1'])]
    assert deals['deals'][0]['variants'][0]['shelf_price'] == '47.99'


def test_a_cheapest_place_answer_that_names_no_live_deal_is_flagged_with_the_deal():
    deals = ppt.deals_from_rows(ROWS)
    facts = nv.answer_facts(_run('Amazon has it at $36.18.'), OUTCOME, [], MERCHANT, {}, None, deals)
    assert facts['why'] == ['promo_missed']
    assert facts['deals_live_that_day'] == [{'retailer': 'Amazon', 'deal': 'save 40% on 1 when you buy 2',
                                             'terms': 'when you buy 2', 'price_that_day': '47.99'}]
    assert nv.system_prompt(facts) == nv.PROMO_PROMPT
    # the demo's line passes the checks on these facts
    line = ('Perplexity named no deal. Amazon charged $47.99 that day and ran save 40% on 1 when you buy 2, '
            'which the answer never mentions.')
    assert nv.check(line, facts) is None


def test_an_answer_that_names_the_deal_is_not_flagged_and_other_intents_are_untouched():
    deals = ppt.deals_from_rows(ROWS)
    named = _run('Amazon is cheapest, and when you buy 2 you save 40% on one.')
    assert nv.answer_facts(named, OUTCOME, [], MERCHANT, {}, None, deals) is None
    assert nv.answer_facts(_run('Amazon has it.', intent='where_to_buy'), OUTCOME, [], MERCHANT, {}, None, deals) is None
    # no deal live for the variant: nothing to miss
    assert nv.answer_facts(_run('Amazon has it at $36.18.'), OUTCOME, [], MERCHANT, {}, None,
                           ppt.deals_from_rows(ROWS[1:])) is None
    # a price flag keeps its reason, the deal added after it
    wrong = {'outcome': 'wrong', 'extraction': {}}
    run = {**_run('Amazon has it at $36.18.'), 'tier': 'catalog_accuracy'}
    facts = nv.answer_facts(run, wrong, [], MERCHANT, {}, None, deals)
    assert facts['why'] == ['wrong_price', 'promo_missed']
    assert nv.system_prompt({'kind': nv.ANSWER, 'why': ['wrong_price']}) == nv.SYSTEM_PROMPT


def test_the_api_copies_are_identical():
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ('promo_pass_through.py', 'narratives.py'):
        assert filecmp.cmp(os.path.join(here, '..', 'soa_shared', name),
                           os.path.join(here, '..', '..', 'api', 'soa_shared', name), shallow=False), name
