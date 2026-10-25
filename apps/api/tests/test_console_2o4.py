"""
2O-4: brand-direct claims are selected by rule (brand-claim coder version 4,
apps/pipeline/scoring/brand_claim_selector.py), with no model call, and the
console's scorer is "14".

Comparability as 2O-3 made it: a cycle compares as the version its oldest
brand-direct outcome was coded under (console_score.CODER_SCORER_VERSIONS),
so FL14 re-scored on version 4 compares as "14", and a cycle still on
version 3 as "13" until it is re-scored too. The Answers drawer lists every
claim sentence the verdict judged, not only the one that decided.
"""
from app.services import console_read_models as rm
from app.services import console_score as score_svc
from soa_shared import expected_answers as ea


def _body(version, coded, of=258, oldest=None, coder=None):
    return {'scorer_version': version, 'score': 50, 'surfaces': [{'surface': 'grounded_api'}],
            'metric_counts': {}, 'metric_surface': None,
            'brand_coder': {'version': coder or ea.BRAND_CODER_VERSION, 'coded': coded, 'of': of, 'oldest': oldest}}


def test_the_version():
    # 2O-5 moved the current version on (test_console_2o5); version 4's outcomes still compare as "14"
    assert score_svc.SCORER_CHANGES['14'] == 'brand-direct claims selected by rule, no model call'
    # no dimension reads the brand-direct outcome: the version never explains a moved score
    assert score_svc.SCORER_CHANGE_APPLIES['14']({}) is False
    assert {k: score_svc.CODER_SCORER_VERSIONS[k] for k in (None, 1, 2, 3, 4)} == \
        {None: '11', 1: '11', 2: '12', 3: '13', 4: '14'}


def test_a_cycle_compares_as_its_oldest_brand_direct_outcome():
    assert score_svc.comparable_version(_body('14', 258, oldest=4, coder=4)) == '14'
    assert score_svc.comparable_version(_body('14', 200, oldest=3, coder=4)) == '13'
    assert score_svc.comparable_version(_body('14', 200, oldest=2, coder=4)) == '12'
    # a score stored under 13, whose block counted version-3 rows
    assert score_svc.comparable_version(_body('13', 258, oldest=3, coder=3)) == '13'
    assert score_svc.comparable_version(_body('13', 200, oldest=2, coder=3)) == '12'


def test_fl14_re_scored_is_not_comparable_to_a_cycle_on_version_3():
    fl14 = _body('14', 258, oldest=4)
    prev = score_svc.compare(fl14, 'FL13-pampers-20261022', _body('14', 0, oldest=3))
    assert prev['comparable'] is False and prev['reason'] == 'Scored under v13, re-score to compare.'
    prev = score_svc.compare(fl14, 'FL13-pampers-20261022', _body('14', 258, oldest=4))
    assert prev['condition'] != 'version'


def test_the_coder_count():
    rows = [{'tier': 'brand_direct', 'outcome': 'echoed', 'coder_version': v} for v in (4, 4, 3)]
    # 2O-5: coded counts the current coder's (5) rows
    assert score_svc.brand_coder(rows) == {'version': ea.BRAND_CODER_VERSION, 'coded': 0, 'of': 3, 'oldest': 3, 'unanswered': 0}


SPANS = [
    {'text': 'Pampers is one of the most trusted diaper brands.', 'kind': 'recommendation', 'verdict': 'echoed',
     'facts_found': [], 'facts_missing': [], 'facts_unchecked': [], 'via': 'named', 'qualifier': None},
    {'text': 'Pampers is the #1 pediatrician recommended brand in the United States.', 'kind': 'attribute',
     'verdict': 'fabricated', 'facts_found': [], 'via': 'named', 'qualifier': None,
     'facts_missing': [{'type': 'attribute', 'text': 'pediatrician recommended'}, {'type': 'attribute', 'text': '#1'}],
     'facts_unchecked': []},
    {'text': 'Pampers Swaddlers and Cruisers are its best-known lines.', 'kind': 'attribute', 'verdict': 'grounded',
     'facts_found': [{'type': 'name', 'text': 'Swaddlers'}, {'type': 'name', 'text': 'Cruisers'}],
     'facts_missing': [], 'facts_unchecked': [], 'via': 'named', 'qualifier': 'Swaddlers'},
]
CLAIM = {'version': 4, 'index': {'version': 1, 'digest': 'e0502b471d41', 'size': 83, 'types_read': ['attribute'],
                                 'by_source': {'record': 3, 'catalog': 27, 'brand_pages': 53}},
         'decided_by': 1, 'spans': SPANS, 'selector': {'units': 3, 'about_brand': 3, 'hedged': 0, 'no_fact': 0},
         'vocabulary': 'abc123'}


def test_the_drawer_lists_every_judged_sentence():
    run = {'id': 15321, 'platform': 'perplexity', 'run_number': 1, 'answer_status': 'answered',
           'raw_response': ' '.join(s['text'] for s in SPANS)}
    query = {'tier': 'brand_direct', 'query_text': 'Is Pampers a good diaper brand?', 'source_ref': {}}
    outcome = {'outcome': 'fabricated', 'reason_code': 'fact_not_published',
               'outcome_reason': f"{SPANS[1]['text']!r} — 'pediatrician recommended' is not on Pampers' record",
               'expected_answer': {'type': 'brand_mention', 'brand': 'Pampers'},
               'extraction': {'brand_mentioned': True, 'coder': {'version': 4, 'calls': []}, 'brand_claim': CLAIM}}
    a = rm.build_answer(run, query, outcome, [], runs_per_query=1, cycle_code='FL14')
    claim = a['brand_claim']
    assert claim['span'] == SPANS[1]['text'] and claim['spans'] == 3
    assert [(s['text'], s['verdict'], s['decided']) for s in claim['sentences']] == [
        (SPANS[0]['text'], 'echoed', False), (SPANS[1]['text'], 'fabricated', True),
        (SPANS[2]['text'], 'grounded', False)]
    assert claim['sentences'][2]['facts_found'] == SPANS[2]['facts_found']
    assert claim['index']['by_source'] == {'record': 3, 'catalog': 27, 'brand_pages': 53}


def test_an_answer_with_no_claim_lists_none():
    claim = rm.brand_claim_evidence({'brand_claim': {**CLAIM, 'spans': [], 'decided_by': None}})
    assert claim['span'] is None and claim['sentences'] == []
