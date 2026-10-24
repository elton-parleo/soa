"""
2O-5: a brand-direct fact is fabricated only when the brand's pages state it
otherwise (brand-claim coder version 5, apps/pipeline/scoring/
brand_fact_index.check); one the index does not hold, that nothing
contradicts, is `unverified`. The console's scorer is "15".

`unverified` is stored `unscoreable` with reason code `unverified` (the
outcome column's constraint is unchanged, as 2N-1's per_unit), so it is
outside every count and the fabricated signal; the console reads it as
`unverified` and the Answers summary says "not on the pages read; nothing
contradicts it". The drawer's line for a fabricated answer names the slot,
the claim's value and the page's.
"""
from app.services import console_parity as parity
from app.services import console_read_models as rm
from app.services import console_score as score_svc
from soa_shared import expected_answers as ea


def _body(version, coded, of=258, oldest=None, coder=None):
    return {'scorer_version': version, 'score': 50, 'surfaces': [{'surface': 'grounded_api'}],
            'metric_counts': {}, 'metric_surface': None,
            'brand_coder': {'version': coder or ea.BRAND_CODER_VERSION, 'coded': coded, 'of': of, 'oldest': oldest}}


def test_the_version():
    assert score_svc.SCORER_VERSION == '15' and ea.BRAND_CODER_VERSION == 5
    assert score_svc.SCORER_CHANGES['15'] == \
        'brand-direct fabricated means contradicted by the brand; absent is unverified'
    assert score_svc.SCORER_CHANGE_APPLIES['15']({}) is False
    assert score_svc.CODER_SCORER_VERSIONS == {None: '11', 1: '11', 2: '12', 3: '13', 4: '14', 5: '15'}
    assert (ea.UNVERIFIED, ea.UNVERIFIED_NOTE) == ('unverified', 'not on the pages read; nothing contradicts it')
    # the outcome column's vocabulary is unchanged: unverified is a reason code, as per_unit is
    assert 'unverified' not in ea.BRAND_OUTCOMES


def test_fl14_re_scored_compares_as_its_oldest_outcome():
    assert score_svc.comparable_version(_body('15', 258, oldest=5)) == '15'
    assert score_svc.comparable_version(_body('15', 200, oldest=4)) == '14'
    # a score stored under 14 whose block counted version-4 rows, some not coded by 4
    assert score_svc.comparable_version(_body('14', 200, oldest=3, coder=4)) == '13'
    prev = score_svc.compare(_body('15', 258, oldest=5), 'FL13-pampers-20261022', _body('15', 0, oldest=4))
    assert prev['comparable'] is False and prev['reason'] == 'Scored under v14, re-score to compare.'


def test_an_unverified_row_reads_unverified_and_stays_out_of_the_counts():
    assert rm.read_outcome('unscoreable', ea.UNVERIFIED) == 'unverified'
    assert rm.read_outcome('unscoreable', ea.NO_CHECKABLE_FACT) == 'unscoreable'
    assert rm.read_outcome('fabricated', 'fact_contradicted') == 'fabricated'
    assert rm.BRAND_TONE['unverified'] == 'neu' and rm.CELL_TONE['unverified'] == 'neu'
    # never the worst of several runs while a scored outcome is there
    assert rm.worst(['unverified', 'grounded']) in ('unverified', 'grounded')
    assert rm.SEVERITY.index('unverified') > rm.SEVERITY.index('fabricated')



def test_the_fabricated_signal_and_the_brand_counts_leave_unverified_out():
    row = {'tier': 'brand_direct', 'platform': 'perplexity', 'surface': 'grounded_api', 'answer_status': 'answered'}
    rows = [{**row, 'outcome': 'fabricated', 'reason_code': 'fact_contradicted'},
            {**row, 'outcome': 'unscoreable', 'reason_code': ea.UNVERIFIED},
            {**row, 'outcome': 'grounded', 'reason_code': 'facts_published'}]
    totals = parity.surface_metrics(rows, [], 'grounded_api', tier='brand_direct')['total']
    assert (totals['fabricated'], totals['brand_scored']) == (1, 2)


SPANS = [
    {'text': 'Pampers Swaddlers cost $38.49 at Walgreens.', 'kind': 'price', 'verdict': 'unverified',
     'facts_found': [], 'facts_missing': [], 'facts_unchecked': [],
     'facts_unverified': [{'type': 'price', 'text': '$38.49'}, {'type': 'retailer', 'text': 'walgreens.com'}]},
    {'text': 'Pampers Swaddlers Newborn fits babies 2 to 9 lbs.', 'kind': 'attribute', 'verdict': 'fabricated',
     'facts_found': [], 'facts_unchecked': [], 'facts_unverified': [],
     'facts_missing': [{'type': 'weight', 'text': '2 to 9 lbs', 'slot': 'ranges', 'claimed': '2 to 9 lbs',
                        'published': 'under 10 lb', 'line': 'Swaddlers', 'size': '0'}]},
]
REASON = "fabricated: '2 to 9 lbs' for Swaddlers Newborn — pampers.com's chart says under 10 lb"


def _answer(outcome, reason_code, reason, spans, decided):
    run = {'id': 15400, 'platform': 'perplexity', 'run_number': 1, 'answer_status': 'answered',
           'raw_response': ' '.join(s['text'] for s in spans)}
    query = {'tier': 'brand_direct', 'query_text': 'Tell me about Pampers Swaddlers.', 'source_ref': {}}
    claim = {'version': 5, 'decided_by': decided, 'spans': spans,
             'index': {'version': 2, 'digest': 'abc', 'size': 195,
                       'by_source': {'record': 3, 'catalog': 34, 'brand_pages': 158}}}
    outcome_row = {'outcome': outcome, 'reason_code': reason_code, 'outcome_reason': reason,
                   'expected_answer': {'type': 'brand_mention', 'brand': 'Pampers'},
                   'extraction': {'brand_mentioned': True, 'coder': {'version': 5, 'calls': []}, 'brand_claim': claim}}
    return rm.build_answer(run, query, outcome_row, [], runs_per_query=1, cycle_code='FL14')


def test_the_drawer_line_names_the_slot_and_both_values():
    a = _answer('fabricated', 'fact_contradicted', REASON, SPANS, 1)
    assert (a['brand_verdict'], a['summary'], a['tone'], a['severity']) == ('fabricated', REASON, 'bad', 'high')
    claim = a['brand_claim']
    assert claim['facts_missing'][0]['published'] == 'under 10 lb' and claim['facts_unverified'] == []
    assert [(s['verdict'], s['decided']) for s in claim['sentences']] == [('unverified', False), ('fabricated', True)]
    assert claim['sentences'][0]['facts_unverified'][1] == {'type': 'retailer', 'text': 'walgreens.com'}


def test_an_unverified_answer_reads_unverified_on_answers():
    reason = f"'{SPANS[0]['text']}' — {ea.UNVERIFIED_NOTE}"
    a = _answer('unscoreable', ea.UNVERIFIED, reason, SPANS[:1], 0)
    assert (a['brand_verdict'], a['tone'], a['severity']) == ('unverified', 'neu', 'low')
    assert a['summary'].endswith('not on the pages read; nothing contradicts it')
    assert a['brand_claim']['facts_unverified'] == SPANS[0]['facts_unverified']
