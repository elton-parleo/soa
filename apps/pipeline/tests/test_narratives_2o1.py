"""
2O-1 (B3): two narrative nits from FL14, replayed on its shape. No model.

1. A missed deal. The old pattern's optional quote, left out, wrote
   "Gemini Amazon charged $36.18 that day and ran 25% off list price ...":
   Amazon's price as Gemini's quote (run-15118, 15342, dropped on
   who_said_what). The pattern now: "<Agent> sent the shopper to <retailer it
   named> and never mentioned Amazon's 25% off list price on AMORE Size 1,
   $36.18 from $47.99, live that day.", the agent's own quote, when it gave
   one, its own sentence before it. sent_to is the retailers it named; an
   agent's name with a retailer's right after it is refused.
2. One store is "the place to buy it", not "places".

The facts are FL14's shape (its deal as 2N-1's tests hold it), not its
stored rows: those are not in the repository and were not read.
"""
from soa_shared import narratives as nv

MERCHANT = nv.Merchant(name='Pampers', kind='brand', terms=('Pampers',))
#: FL14's Amazon deal (tests/test_console_2n1_parity.FL14_DEAL)
FL14_DEAL = {'retailer_domain': 'amazon.com', 'kind': 'rollback_or_was', 'value': 25, 'value_unit': 'percent',
             'text': '$36.18 with 25 percent savings -25% $ 36 . 18 $0.27 per count ( $0.27 $0.27 / count) List Price: $47.99',
             'variants': [{'sku': 'amore-1', 'product_name': 'Pampers AMORE Diapers', 'variant_label': 'Size 1, 132 ct',
                           'shelf_price': '36.18', 'price': '36.18', 'was_price': '47.99'}]}
DEALS = {'deals': [FL14_DEAL]}
DEAL = "Amazon's 25% off list price on AMORE Size 1, $36.18 from $47.99, live that day."


def _run(run_id, platform, text):
    return {'id': run_id, 'platform': platform, 'surface': 'grounded_api', 'answer_status': 'answered',
            'tier': 'brand_direct', 'raw_response': text, 'query_text': 'Cheapest place to buy Pampers AMORE Size 1?',
            'source_ref': {'intent': 'cheapest_place', 'variant_id': 'amore-1', 'merchant_slug': 'pampers'}}


def _facts(run_id, platform, text, extraction, claims=None):
    outcome = {'outcome': 'grounded', 'extraction': extraction, 'claim_results': claims or []}
    return nv.answer_facts(_run(run_id, platform, text), outcome, [], MERCHANT, {}, None, DEALS)


def gemini_15118():
    """Gemini sent the shopper to Walmart and quoted no price."""
    return _facts(15118, 'gemini_grounded', 'Walmart usually has the lowest price on Pampers AMORE Size 1.',
                  {'retailer_mentions': [{'name': 'Walmart', 'role': 'recommendation'}]})


def copilot_15342():
    """Copilot quoted $66.98 at Amazon."""
    return _facts(15342, 'copilot', 'Amazon has Pampers AMORE Size 1 for $66.98.',
                  {'retailer_mentions': [{'name': 'Amazon', 'role': 'recommendation'}]},
                  claims=[{'stated': '66.98', 'amount': '66.98', 'asked_at': 'amazon.com', 'outcome': 'wrong',
                           'target': 'asked'}])


def test_the_facts_say_where_the_answer_sent_the_shopper():
    facts = gemini_15118()
    assert facts['why'] == ['promo_missed'] and nv.system_prompt(facts) == nv.PROMO_PROMPT
    assert facts['sent_to'] == ['Walmart']
    assert facts['deals_live_that_day'][0]['deal'] == '25% off list price on AMORE Size 1, $36.18 from $47.99'
    # no recommendation labelled: the retailer its quote was judged at
    quoted = _facts(1, 'copilot', 'Amazon has it for $66.98.', {},
                    claims=[{'stated': '66.98', 'outcome': 'wrong',
                             'reference': {'against': '36.18', 'retailer_domain': 'amazon.com'}}])
    assert quoted['sent_to'] == ['Amazon']
    # and none at all: no sent_to, and the line is "<Agent> never mentioned ..."
    assert 'sent_to' not in _facts(2, 'claude', 'It depends on the week.', {})


def test_the_prompt_is_the_new_pattern():
    assert ('[<assistant> quoted $<price> at <retailer>. ]<assistant> sent the shopper to <retailer in sent_to> '
            "and never mentioned <deal's retailer>'s <deal>, live that day.") in nv.PROMO_PROMPT
    assert ('"Gemini sent the shopper to Walmart and never mentioned Amazon\'s 25% off list price on AMORE Size 1, '
            '$36.18 from $47.99, live that day."') in nv.PROMO_PROMPT
    assert 'charged $<price that day> that day and ran' not in nv.PROMO_PROMPT


def test_run_15118_before_and_after():
    facts = gemini_15118()
    before = ('Gemini Amazon charged $36.18 that day and ran 25% off list price on AMORE Size 1, $36.18 from $47.99, '
              'which the answer never mentions.')
    assert nv.check(before, facts) == 'who_said_what:Gemini Amazon'
    after = 'Gemini sent the shopper to Walmart and never mentioned ' + DEAL
    assert nv.check(nv.normalise(after, facts), facts) is None
    # a retailer it did not name is not in the facts
    assert nv.check('Gemini sent the shopper to Target and never mentioned ' + DEAL, facts) == 'name_not_in_facts:target'


def test_run_15342_before_and_after():
    facts = copilot_15342()
    assert facts['sent_to'] == ['Amazon']
    before = ('Copilot quoted $66.98 at Amazon. Amazon charged $36.18 that day and ran 25% off list price on AMORE '
              'Size 1, which the answer never mentions.')
    after = 'Copilot quoted $66.98 at Amazon. Copilot sent the shopper to Amazon and never mentioned ' + DEAL
    assert nv.check(before, facts) is None
    assert nv.check(nv.normalise(after, facts), facts) is None
    # the retailer's price in the agent's sentence is still the agent's quote, and refused
    assert nv.check('Copilot quoted $36.18 at Amazon and never mentioned ' + DEAL, facts) is not None


def test_one_store_is_the_place_to_buy_it():
    facts = {'kind': nv.ANSWER, 'why': ['brand_fabricated'], 'agent': 'Google AI Mode', 'brand': 'Pampers',
             'named_stores': ['Walmart'], 'scorer_note': 'where to buy, stated with no source'}
    before = 'Google AI Mode named Walmart as places to buy it. Pampers never published that list.'
    after = nv.normalise(before, facts)
    assert after == 'Google AI Mode named Walmart as the place to buy it. Pampers never published that list.'
    assert nv.check(after, facts) is None
    assert 'With one store in named_stores: <assistant> named <store> as the place to buy it.' in nv.STORES_PROMPT
    # two or more stay places
    three = {**facts, 'named_stores': ['Walgreens', 'Walmart', 'Target']}
    line = 'Gemini named Walgreens, Walmart and Target as places to buy it. Pampers never published that list.'
    assert nv.normalise(line, three) == line
