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


# ---------------------------------------------------------------------------
# B4: product rows
# ---------------------------------------------------------------------------

def _amore_quotes(amazon='exact', walmart='exact'):
    """AMORE Size 1 on FL14: six agents at each of Amazon, Walmart and Target; Target walled every read."""
    agents = ('ChatGPT', 'Gemini', 'Google AI Mode', 'Perplexity', 'Copilot', 'Claude')
    out = []
    for a in agents:
        out.append({'agent': a, 'asked_at': 'Amazon', 'quoted': '36.18', 'verdict': amazon})
        out.append({'agent': a, 'asked_at': 'Walmart', 'quoted': '36.47', 'verdict': walmart})
        out.append({'agent': a, 'asked_at': 'Target', 'quoted': '36.99', 'verdict': 'unverifiable'})
    return out


def test_b4_unverifiable_only_when_every_retailer_was_walled():
    before = '6 of 6 agents quoted a price that could not be checked'
    issue, _d = nv.issue_sentence(_amore_quotes(), 6, {})
    assert issue != before and issue == '6 of 6 agents quoted the right price. Target could not be read'
    assert nv.issue_rule(_amore_quotes()) == ('product.right', 12, 12)
    # Pure Protection: Amazon read and wrong, Target walled
    pure = [q for q in _amore_quotes(amazon='wrong') if q['asked_at'] != 'Walmart']
    assert nv.issue_sentence(pure, 6, {})[0] == '6 of 6 agents quoted a wrong price at Amazon. Target could not be read'
    # every retailer walled: the issue is the unchecked price, as before
    walled = [{**q, 'verdict': 'unverifiable'} for q in _amore_quotes()]
    assert nv.issue_sentence(walled, 6, {})[0] == before


def test_b4_the_console_issue_follows_the_same_rule():
    quotes = [{'outcome': {'exact': 'exact', 'unverifiable': 'unverifiable'}[q['verdict']], 'reason': None,
               'retailer': {'Amazon': 'amazon.com', 'Walmart': 'walmart.com', 'Target': 'target.com'}[q['asked_at']]}
              for q in _amore_quotes()]
    assert parity.product_issue(quotes) == ('product.right', 'Right in 12 of 12 runs. Target could not be read.')
    walled = [{**q, 'outcome': 'unverifiable'} for q in quotes]
    assert parity.product_issue(walled)[0] == 'product.unverifiable'


def test_b4_the_issue_is_its_own_sentence():
    facts = {'kind': nv.PRODUCT, 'issue': '6 of 6 agents quoted the right price. Target could not be read'}
    line = 'Claude quoted $36.18 at Amazon. Amazon charged $36.18 on Oct 23 6 of 6 agents quoted the right price. Target could not be read.'
    assert nv.normalise(line, facts) == ('Claude quoted $36.18 at Amazon. Amazon charged $36.18 on Oct 23. 6 of 6 agents '
                                         'quoted the right price. Target could not be read.')
    ok = 'Claude quoted $36.18 at Amazon. Amazon charged $36.18 on Oct 23. ' + facts['issue'] + '.'
    assert nv.normalise(ok, facts) == ok


def test_b4_the_check_label_follows_the_issue_rule():
    """Swaddlers Newborn on FL14: "No price quoted in 12 of 18 runs" beside a wrong cell read Wrong price."""
    def cell(quotes, status):
        return {'quotes': quotes, 'by_surface': {'all': {'status': status, 'quoted': '$9.99'}}, 'live': '$9.99'}
    q = lambda run, outcome, stated: {'agent': 'chatgpt', 'surface': 'grounded_api', 'outcome': outcome,  # noqa: E731
                                      'stated': stated, 'run': f'run-{run}'}
    walmart = [q(i, 'absent', None) for i in range(6)]
    amazon = [q(10 + i, 'absent', None) for i in range(6)]
    target = [q(20, 'wrong', '24.99'), q(21, 'wrong', '24.99')] + [q(22 + i, 'exact', '27.97') for i in range(4)]
    tv = {'retailer_columns': [{'id': 'pampers.com', 'you': True}, {'id': 'walmart.com'}, {'id': 'amazon.com'},
                               {'id': 'target.com'}],
          'rows': [{'product': 'Pampers Swaddlers Newborn', 'sku': 'nb', 'cells': {
              'pampers.com': cell([], 'none'), 'walmart.com': cell(walmart, 'missed'),
              'amazon.com': cell(amazon, 'missed'), 'target.com': cell(target, 'wrong')}}]}
    [row] = parity.build_products(tv, [], 'all', variant_of_run={}, reason_of_run={})
    assert row['issue'] == 'No price quoted in 12 of 18 runs.'
    assert (row['cell_status'], row['status']) == ('wrong', 'none')
    assert parity.status_for('product.right', 'partial') == 'partial' and parity.status_for('product.wrong', 'exact') == 'wrong'


# ---------------------------------------------------------------------------
# B5: Visibility and routing hygiene
# ---------------------------------------------------------------------------

ENTITIES = [{'name': 'Pampers', 'aliases': '[]', 'role': 'primary'}, {'name': 'Huggies', 'aliases': '[]', 'role': 'tracked'},
            {'name': 'The Honest Company', 'aliases': '[]', 'role': 'tracked'}]


def _vis_runs():
    """30 category questions (180 brand-choice answers) and 43 brand-direct ones that name Pampers (258)."""
    runs, mentions, extractions, rid = [], [], {}, 0
    for q in range(73):
        choice = q < 30
        for agent in AGENTS:
            rid += 1
            runs.append({'id': rid, 'platform': agent, 'run_number': 1, 'surface': SURFACE[agent], 'answer_status': 'answered',
                         'query_code': f'Q{q:02d}', 'tier': 'category_control' if choice else 'brand_direct',
                         'query_text': 'Best diapers for a newborn?' if choice else 'Is Pampers Swaddlers hypoallergenic?',
                         'stage': 'Discovery', 'source_ref': {}})
            if not choice or rid % 3 == 0:    # every brand-direct answer names Pampers; a third of the category ones
                mentions.append({'run_id': rid, 'name': 'Pampers', 'position': 1, 'role': 'primary'})
            if choice:
                mentions.append({'run_id': rid, 'name': 'Huggies', 'position': 1 if rid % 3 else 2, 'role': 'tracked'})
                extractions[rid] = {'spans': [], 'other_brands_named': [
                    {'name': 'Swaddlers', 'presented_as': 'recommendation'}, {'name': 'Honest', 'presented_as': 'recommendation'},
                    {'name': 'Walmart', 'presented_as': 'recommendation'}, {'name': 'Kirkland', 'presented_as': 'recommendation'},
                    {'name': 'Hy-Vee', 'presented_as': 'recommendation'}, {'name': 'Cruisers', 'presented_as': 'recommendation'}]}
    return runs, mentions, extractions


def test_b5_a_brand_s_ranking_opens_on_its_brand_choice_answers():
    runs, mentions, extractions = _vis_runs()
    lines = rm.line_aliases(['Pampers Swaddlers Diapers', 'Pampers Baby Dry Diapers', 'Pampers Cruisers 360',
                             'Pampers Pure Protection Diapers'], 'Pampers')
    assert lines == ['Swaddlers', 'Baby Dry', 'Cruisers 360', 'Pure Protection']
    body = rm.build_visibility('FL14', runs=runs, entities=ENTITIES, mentions=mentions, extractions=extractions,
                               terms=['Pampers'], kind='brand', lines=lines + ['Cruisers'])
    every = {r['name']: r for r in body['ranking']['rows']}
    # every question: the 258 brand-direct answers name Pampers because the question does
    assert body['ranking']['denom'] == 438 and every['Pampers']['first'] == 258 + 60
    choice = body['ranking']['brand_choice']
    assert body['ranking']['default_tier'] == 'brand_choice' and choice['denom'] == 180
    assert choice['title'] == 'Who agents pick first, Pampers category prompts'
    assert choice['sub'] == '180 category and comparison answers'
    mine = {r['name']: r for r in choice['rows']}
    # sub-lines are Pampers; Honest is The Honest Company; retailers are not brands
    assert set(mine) == {'Pampers', 'Huggies', 'The Honest Company'}
    assert (mine['Pampers']['named'], mine['The Honest Company']['named'], mine['Huggies']['first']) == (180, 180, 120)
    # a retailer merchant keeps the one ranking
    store = rm.build_visibility('FL14', runs=runs, entities=ENTITIES, mentions=mentions, extractions=extractions,
                                terms=['Pampers'], kind='retailer')
    assert 'brand_choice' not in store['ranking'] and 'default_tier' not in store['ranking']


def test_b5_the_brand_s_own_names_are_its_site_in_routing():
    rows, runs, extractions = [], [], {}
    for i, store in enumerate(['Pampers', 'Pampers Official Store', 'Pampers official site / product page', 'Amazon',
                               'Hy-Vee']):
        rid = 100 + i
        runs.append({'id': rid, 'source_ref': {'intent': 'where_to_buy'}})
        rows.append({'run': f'run-{rid}', 'answered': True, 'surface': 'grounded_api'})
        extractions[rid] = {'spans': [], 'retailer_mentions': [{'name': store, 'role': 'retailer'}]}
    block = rm.build_routing(rows, runs, extractions, surface_list=['all', 'grounded_api'], brand='Pampers',
                             retailers=['amazon.com', 'walmart.com'], own_domains=['pampers.com'])
    table = {r['name']: r for r in block['rows']}
    assert table['pampers.com']['first'] == 3 and table['pampers.com']['you'] is True
    assert table['Other stores']['note'] == 'Hy-Vee' and table['Amazon']['first'] == 1


# ---------------------------------------------------------------------------
# B6: the live deal, Changes, Impact
# ---------------------------------------------------------------------------

FL14_DEAL = {'retailer_domain': 'amazon.com', 'kind': 'rollback_or_was', 'value': 25, 'value_unit': 'percent',
             'text': '$36.18 with 25 percent savings -25% $ 36 . 18 $0.27 per count ( $0.27 $0.27 / count) List Price: $47.99',
             'variants': [{'sku': 'amore-1', 'product_name': 'Pampers AMORE Diapers', 'variant_label': 'Size 1, 132 ct',
                           'shelf_price': '36.18', 'price': '36.18', 'was_price': '47.99'}]}


def test_b6_the_deal_is_titled_from_its_fields_in_its_retailer_s_words():
    from soa_shared import promo_pass_through as ppt
    assert ppt.title(FL14_DEAL) == 'Amazon: 25% off list price on AMORE Size 1, $36.18 from $47.99'
    assert ppt.short(FL14_DEAL) == 'Amazon list price cut'          # was "Amazon Rollback"
    assert [ppt.kind_words({**FL14_DEAL, 'retailer_domain': d}) for d in
            ('walmart.com', 'amazon.com', 'target.com', 'kroger.com')] == ['Rollback', 'list price cut', 'sale', 'sale price']
    assert ppt.evidence(FL14_DEAL['text']) == '$36.18 with 25 percent savings -25% List Price: $47.99'
    promo = {'n': 6, 'k': 3, 'subscribe': 0, 'per_deal': [{'title': ppt.title(FL14_DEAL), 'short': ppt.short(FL14_DEAL),
                                                           'asked': 6, 'named': 3}]}
    body = rm.build_prove(promo, {'deals': [FL14_DEAL], 'walled': []}, 'Pampers', '2026-10-23')
    [row] = body['rows']
    assert row['title'] == 'Amazon: 25% off list price on AMORE Size 1, $36.18 from $47.99' and row['kind_label'] == 'list price cut'
    assert row['detail'] == ('Live on Pampers AMORE Diapers. Pampers AMORE Diapers $47.99 to $36.18. '
                             'The shelf said: $36.18 with 25 percent savings -25% List Price: $47.99.')
    assert body['aside']['sub'] == 'Answers named Amazon list price cut 3 times.'


def _brand_vis(first_you=5, first_huggies=9, named=25, n=29, coverage=(45, 49), retired=(10, 0)):
    rows = []
    for i in range(n):
        you_first = i < first_you
        rows.append({'answered': True, 'brand_choice': True, 'surface': 'grounded_api',
                     'first': {'name': 'Pampers', 'you': True} if you_first else
                     ({'name': 'Huggies', 'you': False} if i < first_you + first_huggies else None),
                     'named': [{'name': 'Pampers', 'you': True}] if i < named else []})
    return {'byQuestion': rows,
            'routing': {'coverage': {'all': {'answers': coverage[1], 'named_two_plus': coverage[0]}},
                        'retailers': ['Walmart', 'Target', 'Amazon']},
            'retired_named': {'lines': [{'line': 'Pure Protection', 'label': 'Pure',
                                         'successor': {'label': 'AMORE'},
                                         'brand_choice': {'all': {'answers': n, 'named': retired[0],
                                                                  'successor_named': retired[1]}}}]}}


def test_b6_the_brand_s_first_cycle_changes_in_the_demo_s_order():
    lines = rm.brand_changes(_brand_vis(), None, None, 'all', compared=False, brand='Pampers')
    assert [(c['label'], c['delta']) for c in lines] == [
        ('Retired product named', 'new'), ('First pick, category questions', 'new'), ('Retailer coverage', 'new')]
    assert lines[0]['detail'] == 'Pure in 10 of 29 category answers, AMORE in 0. First cycle with this question.'
    assert lines[1]['detail'] == 'Pampers 5 of 29, Huggies 9. First cycle with these questions.'
    assert lines[2]['detail'] == ('45 of 49 where-to-buy answers named at least two of Walmart, Target and Amazon. '
                                  'First cycle with this question.')
    assert [c['tone'] for c in lines] == ['bad', 'warn', 'ok']
    # afterwards, a delta as 2K-4's lines take one
    later = rm.brand_changes(_brand_vis(first_you=8, coverage=(47, 49), retired=(6, 2)), _brand_vis(), 'FL14', 'all',
                             compared=True, brand='Pampers')
    assert [(c['delta'], c['tone']) for c in later] == [('-4', 'ok'), ('+3', 'ok'), ('+2', 'ok')]
    assert later[1]['detail'] == '8 of 29 this cycle against 5 of 29 in FL14.'


def test_b6_impact_s_baseline_has_the_demo_s_four():
    rows = rm.brand_baseline(attribute={'n': 79, 'k': 61, 'site': 'pampers.com'}, vis=_brand_vis(),
                             promo={'n': 50, 'k': 4}, brand='Pampers', day='Oct 23')
    assert [(r['label'], r['value'], r['note']) for r in rows] == [
        ('Attribute accuracy', '61 of 79', 'Weight range matches pampers.com, Oct 23'),
        ('Retailer coverage', '45 of 49', 'Names 2 of Walmart, Target, Amazon'),
        ('Promo pass-through', '4 of 50', 'Named a deal live that day'),
        ('Category presence', '25 of 29', 'Pampers named, first in 5')]
    # a measure not taken this cycle is left out, never a zero
    assert [r['key'] for r in rm.brand_baseline(attribute=None, vis={}, promo=None, brand='Pampers', day='Oct 23')] == []


def test_b6_impact_counts_brand_choice_answers_when_the_cycle_asked_comparison():
    from app.services import console_revenue as rev
    rows = [{'answered': True, 'brand_choice': True, 'tier': 'category_control', 'agent': 'chatgpt', 'surface': 'grounded_api', 'run': 'run-1', 'first': {'name': 'Huggies', 'you': False}},
            {'answered': True, 'brand_choice': True, 'tier': 'comparison', 'agent': 'chatgpt', 'surface': 'grounded_api', 'run': 'run-2', 'first': {'name': 'Pampers', 'you': True}}]
    shares = rev.revenue_shares(rows, [], 0.3, kind='brand')
    assert shares['set'] == 'brand-choice' and (shares['lost']['n'], shares['lost']['of']) == (1, 2)


def test_a_cell_priced_for_another_pack_says_so():
    """Cruisers 360 Size 5 at Amazon on FL14: "live $49.77, couldn't verify". The page's pack is 56 ct."""
    reads = [{'retailer_domain': 'amazon.com', 'variant_ref': 'v6', 'sku': 'v6', 'price': '49.77', 'currency': 'USD',
              'observed_at': '2026-10-23T14:00:00+00:00',
              'findings': [{'finding': 'pack_differs', 'expected': '66', 'observed': '56', 'detail': {'page_numbers': [56]}},
                           {'finding': 'price_observed', 'observed': '49.77'}]}]
    assert rm.other_pack(reads, {'variant_id': 'v6'}, 'amazon.com') == {
        'price': '$49.77', 'pack': '56 ct', 'text': 'other pack ($49.77 for 56 ct)'}
    assert rm.other_pack(reads, {'variant_id': 'v6'}, 'walmart.com') is None
    assert rm.other_pack([{**reads[0], 'findings': []}], {'variant_id': 'v6'}, 'amazon.com') is None
