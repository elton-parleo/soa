"""
2N-1: what the first parity cycle (FL14-pampers-20261023) showed, on FL14's shape.

B2: brand-direct holds 43 questions on FL14, 12 AI-written and 31 the catalog
built (10 where-to-buy, 10 cheapest-place, 10 accuracy, the retired line),
six agents each: 258 answers. The brand-claim rule ("stated a fact Pampers
never published") judged all 258. The shape below gives the classifier's
`fabricated` to 123 of them (121 stating a fact, 2 only recommending), as
FL14's Overview showed: 30 on the AI-written questions (29 and 1) and 93 on
the catalog-built ones (92 and 1). After: only the 72 AI-written answers are
the rule's, and the catalog-built ones carry their own verdict.
"""
from app.services import console_parity as parity
from app.services import console_read_models as rm
from soa_shared import claim_kinds
from soa_shared import narratives as nv

AGENTS = ('chatgpt', 'gemini', 'aimode', 'perplexity', 'copilot', 'claude')
SURFACE = {'chatgpt': 'grounded_api', 'gemini': 'grounded_api', 'claude': 'grounded_api', 'perplexity': 'grounded_api',
           'aimode': 'consumer_ui', 'copilot': 'consumer_ui'}

#: (intent, questions, fabricated stating a fact, fabricated recommending only)
FL14_BRAND_DIRECT = [
    (None, 12, 29, 1),
    ('where_to_buy', 10, 52, 0),
    ('cheapest_place', 10, 20, 1),
    ('attribute', 10, 18, 0),
    ('retired', 1, 2, 0),
]


def _ref(intent, i):
    if intent is None:
        return {'merchant_slug': 'pampers'}
    if intent == 'retired':
        return {'retired_line': {'line': 'Pampers Pure Protection', 'variant_ids': ['v9']}}
    return {'intent': intent, 'variant_id': f'v{i}'}


def fl14_rows():
    """One row per answer, as load_overview_rows and load_answers_summary give them."""
    rows, run = [], 0
    for intent, questions, attr, rec in FL14_BRAND_DIRECT:
        n = 0
        for q in range(questions):
            ref = _ref(intent, q)
            for agent in AGENTS:
                run += 1
                outcome, kind = 'grounded', claim_kinds.ATTRIBUTE
                if n < attr:
                    outcome = 'fabricated'
                elif n < attr + rec:
                    outcome, kind = 'fabricated', claim_kinds.RECOMMENDATION_ONLY
                n += 1
                rows.append({'run_id': run, 'platform': agent, 'surface': SURFACE[agent], 'answer_status': 'answered',
                             'tier': 'brand_direct', 'outcome': outcome, 'reason_code': None, 'flags': None,
                             'claim_kind': kind if claim_kinds.is_brand_claim('brand_direct', ref) else None, 'kind': kind,
                             'intent': claim_kinds.catalog_intent(ref), 'source_ref': ref})
    return rows


def _as_main(rows):
    """main's read: no intent, every brand-direct answer the brand-claim rule's."""
    return [{**r, 'intent': None, 'claim_kind': r['kind']} for r in rows]


def test_b2_the_catalog_built_answers_are_outside_the_brand_claim_counts():
    rows = fl14_rows()
    assert len(rows) == 258 and sum(1 for r in rows if r['intent'] is None) == 72
    before = parity.surface_metrics(_as_main(rows), [], 'all')['total']
    after = parity.surface_metrics(rows, [], 'all')['total']
    # Overview "By tier": 123 fabricated of 258; the Week in short: 121 stated a fact
    assert (before['brand_scored'], before['fabricated'] + before['recommended'], before['fabricated']) == (258, 123, 121)
    assert (after['brand_scored'], after['fabricated'] + after['recommended'], after['fabricated']) == (72, 30, 29)
    sig = parity.build_signals({'total': after, 'agents': {}}, [], surface='all', brand='Pampers',
                               cycle_start='2026-10-23', access_problems=[])
    assert next(s for s in sig if s['id'] == 'fabricated')['title'] == '29 brand answers stated facts Pampers never published.'


def test_b2_the_by_tier_cells_count_the_ai_written_answers_and_name_the_rest():
    rows = fl14_rows()
    main = rm.build_answers_summary(_as_main(rows), cycle_code='FL14')
    now = rm.build_answers_summary(rows, cycle_code='FL14')
    cell = lambda body: next(t for t in body['tiers'] if t['tier'] == 'brand_direct')['surfaces'][0]  # noqa: E731
    assert (cell(main)['runs'], cell(main)['counts']['fabricated']) == (258, 123)
    assert (cell(now)['runs'], cell(now)['counts']['fabricated'], cell(now)['catalog_built']) == (72, 30, 186)
    assert 'catalog_built' not in cell(main)


def _answer(intent, ref, raw, outcome='fabricated', extraction=None, flags=None, deals=None):
    query = {'tier': 'brand_direct', 'query_text': 'q', 'source_ref': ref}
    run = {'id': 1, 'platform': 'chatgpt', 'raw_response': raw, 'answer_status': 'answered', 'run_number': 1}
    o = {'outcome': outcome, 'extraction': extraction or {'spans': [{'id': 1, 'text': raw}]},
         'outcome_reason': 'told the reader to buy it at Amazon, Target, Walmart, where to buy, stated with no source',
         'flags': flags or []}
    return rm.build_answer(run, query, o, [], runs_per_query=1, cycle_code='FL14', deals=deals,
                           truths={'v1': {'truth': {'min': 8.0, 'max': 14.0}, 'source': 'feed'}})


def test_b2_an_answer_to_a_catalog_built_question_carries_only_its_own_verdict():
    # accuracy: "8 to 14 lb" for Size 1 is right, not a High red fabricated row
    a = _answer('attribute', {'intent': 'attribute', 'size': 'Size 1', 'variant_id': 'v1', 'own_domain': 'pampers.com'},
                'Pampers Swaddlers Size 1 is for babies 8 to 14 lb.')
    assert (a['severity'], a['tone'], a['summary'], a.get('brand_verdict')) == \
        ('ok', 'ok', 'stated 8 to 14 lb, as pampers.com says', None)
    # where to buy: coverage against the brand's retailer list
    stores = [{'name': n, 'role': 'retailer'} for n in ('Amazon', 'Target', 'Walmart')]
    w = _answer('where_to_buy', {'intent': 'where_to_buy', 'variant_id': 'v2',
                                 'retailer_list': ['amazon.com', 'target.com', 'walmart.com']},
                'Buy it at Amazon, Target or Walmart.',
                extraction={'spans': [{'id': 1, 'text': 'Buy it at Amazon, Target or Walmart.'}], 'retailer_mentions': stores})
    assert (w['severity'], w['intent_verdict'], w['summary']) == \
        ('ok', 'covered', "named Amazon, Target and Walmart, 3 of the brand's retailers")
    assert w.get('brand_verdict') is None and w.get('claim_kind') is None
    # cheapest place: deal pass-through against the deals live that day
    deals = {'deals': [{'retailer_domain': 'amazon.com', 'kind': 'multi_buy', 'text': 'Save 40% on 1 when you buy 2',
                        'terms': 'buy 2', 'value': 40, 'value_unit': 'percent', 'variants': [{'sku': 'v3'}]}]}
    c = _answer('cheapest_place', {'intent': 'cheapest_place', 'variant_id': 'v3'}, 'Walmart is cheapest.',
                extraction={'spans': [{'id': 1, 'text': 'Walmart is cheapest.'}],
                            'retailer_mentions': [{'name': 'Walmart', 'role': 'retailer'}]}, deals=deals)
    assert (c['severity'], c['intent_verdict']) == ('medium', 'missed_deal')
    assert c['summary'] == 'named Walmart as the cheapest place and named none of the deals live that day (Amazon multi-buy)'
    # retired: still sold / successor, never fabricated
    r = _answer('retired', {'retired_line': {'line': 'Pampers Pure Protection'}}, 'It is still sold.')
    assert r['severity'] == 'low' and 'fabricated' not in (r.get('brand_verdict') or '')
    # an AI-written question keeps the rule
    q = _answer(None, {'merchant_slug': 'pampers'}, 'Pampers is made of bamboo.')
    assert (q['severity'], q['brand_verdict']) == ('high', 'fabricated')


def test_b2_the_narratives_flag_the_brand_claim_on_ai_written_questions_only():
    merchant = nv.Merchant(name='Pampers', kind='brand', terms=('Pampers',))
    outcome = {'outcome': 'fabricated'}
    assert nv.why_flagged('brand_direct', outcome, None, False, merchant) == ['brand_fabricated']
    assert nv.why_flagged('brand_direct', outcome, None, False, merchant, catalog_intent='where_to_buy') == []


# ---------------------------------------------------------------------------
# B3: a per-unit quote on Answers and True Value
# ---------------------------------------------------------------------------

def test_b3_a_per_unit_run_reads_per_unit_on_answers_and_true_value():
    query = {'tier': 'catalog_accuracy', 'query_text': 'What does Pampers Swaddlers Size 1 cost?',
             'source_ref': {'variant_id': '00037000863441'}}
    run = {'id': 7, 'platform': 'chatgpt', 'raw_response': 'About $0.33 per diaper.', 'answer_status': 'answered',
           'run_number': 1}
    outcome = {'outcome': 'unscoreable', 'reason_code': 'per_unit', 'outcome_reason': 'per-diaper price, not comparable',
               'expected_answer': {'type': 'price', 'amount': None, 'attributed_to': 'walmart.com'},
               'claim_results': [{'stated': '0.33', 'amount': '0.33', 'product': 'per diaper', 'target': 'asked',
                                  'outcome': 'per_unit', 'reason': 'per-diaper price, not comparable',
                                  'reason_code': 'per_unit'}]}
    a = rm.build_answer(run, query, outcome, [], runs_per_query=1, cycle_code='FL14')
    assert (a['verdict'], a['tone'], a['severity']) == ('per_unit', 'neu', 'low')
    assert a['checks'][0]['verdict'] == 'per_unit' and a['checks'][0]['reason'] == 'per_unit'
    # a cell whose quotes are per diaper reads per_unit, never wrong or "not ours"
    assert rm.aggregate_cell([{'stated': '0.33', 'outcome': 'per_unit'}]) == ('per_unit', '0.33')
    assert rm.aggregate_cell([{'stated': '0.33', 'outcome': 'per_unit'}, {'stated': '27.97', 'outcome': 'exact'}]) == \
        ('exact', '27.97')
    assert rm.TV_STATUS['per_unit'] == 'per_unit' and rm.PER_UNIT_LABEL == 'per-diaper price, not comparable'
