"""
2O-3: the brand-claim verdict is decided by code from the claim's facts
(brand-claim coder version 3; apps/pipeline/scoring/brand_claim_verdict.py),
and the console's scorer is "13".

Comparability as 2O-1 made it, one version on: a cycle compares as the
version its OLDEST brand-direct outcome was coded under (console_score.
CODER_SCORER_VERSIONS): every outcome on version 3, "13"; any on version 2,
"12"; any written by one call, "11". So FL14 re-scored on the new verdict is
not comparable to a cycle still on version 2 until that one is re-scored too.

The Answers drawer and the narratives' facts carry the span that decided the
verdict and its facts found and missing (extraction.brand_claim).
"""
from app.services import console_read_models as rm
from app.services import console_score as score_svc
from soa_shared import expected_answers as ea
from soa_shared import narratives


def _body(version, coded, of=258, oldest=None):
    return {'scorer_version': version, 'score': 50, 'surfaces': [{'surface': 'grounded_api'}],
            'metric_counts': {}, 'metric_surface': None,
            'brand_coder': {'version': ea.BRAND_CODER_VERSION, 'coded': coded, 'of': of, 'oldest': oldest}}


def test_the_version():
    # 2O-4 moved the current version on (test_console_2o4); version 3's outcomes still compare as "13"
    assert score_svc.SCORER_CHANGES['13'] == "brand-direct verdict decided from the claim's facts"
    # no dimension reads the brand-direct outcome: the version never explains a moved score
    assert score_svc.SCORER_CHANGE_APPLIES['13']({}) is False
    assert {k: score_svc.CODER_SCORER_VERSIONS[k] for k in (None, 1, 2, 3)} == {None: '11', 1: '11', 2: '12', 3: '13'}


def test_a_cycle_compares_as_its_oldest_brand_direct_outcome():
    assert score_svc.comparable_version(_body('13', 258, oldest=3)) == '13'
    assert score_svc.comparable_version(_body('13', 200, oldest=2)) == '12'
    assert score_svc.comparable_version(_body('13', 200, oldest=1)) == '11'
    assert score_svc.comparable_version(_body('13', 0, of=0)) == '13'
    # a score stored under 12, whose count was of version-2 rows
    stored = {**_body('12', 258), 'brand_coder': {'version': 2, 'coded': 258, 'of': 258}}
    assert score_svc.comparable_version(stored) == '12'


def test_fl14_re_scored_is_not_comparable_to_a_cycle_on_version_2():
    fl14 = _body('13', 258, oldest=3)
    prev = score_svc.compare(fl14, 'FL13-pampers-20261022', _body('13', 0, oldest=2))
    assert prev['comparable'] is False and prev['reason'] == 'Scored under v12, re-score to compare.'
    prev = score_svc.compare(fl14, 'FL13-pampers-20261022', _body('13', 258, oldest=3))
    assert prev['condition'] != 'version'


def test_the_coder_count_names_the_oldest_version():
    rows = [{'tier': 'brand_direct', 'outcome': 'echoed', 'coder_version': v} for v in (3, 3, 2, None)]
    assert score_svc.brand_coder(rows) == {'version': ea.BRAND_CODER_VERSION, 'coded': 0, 'of': 4, 'oldest': 1, 'unanswered': 0}


CLAIM = {'version': 3, 'index': {'version': 1, 'digest': 'abc123', 'size': 40, 'types_read': ['weight']},
         'decided_by': 0, 'spans': [{'text': 'Pampers Swaddlers fit babies 2-9 lbs.', 'kind': 'attribute',
                                     'verdict': 'fabricated', 'line': 'Swaddlers', 'facts_found': [],
                                     'facts_missing': [{'type': 'weight', 'text': '2-9 lbs'}],
                                     'facts_unchecked': []}]}
REASON = "'Pampers Swaddlers fit babies 2-9 lbs.' — '2-9 lbs' is not on pampers.com's Swaddlers page"


def test_the_drawer_shows_the_claim_and_the_fact_missing():
    run = {'id': 15342, 'platform': 'copilot', 'run_number': 1, 'answer_status': 'answered',
           'raw_response': 'Pampers Swaddlers fit babies 2-9 lbs.'}
    query = {'tier': 'brand_direct', 'query_text': 'What weight do Pampers Swaddlers fit?', 'source_ref': {}}
    outcome = {'outcome': 'fabricated', 'reason_code': 'fact_not_published', 'outcome_reason': REASON,
               'expected_answer': {'type': 'brand_mention', 'brand': 'Pampers'},
               'extraction': {'brand_mentioned': True, 'brand_claim': CLAIM}}
    a = rm.build_answer(run, query, outcome, [], runs_per_query=1, cycle_code='FL14')
    assert a['summary'] == REASON and a['brand_verdict'] == 'fabricated'
    assert a['brand_claim'] == {'span': 'Pampers Swaddlers fit babies 2-9 lbs.', 'kind': 'attribute',
                                'facts_found': [], 'facts_missing': [{'type': 'weight', 'text': '2-9 lbs'}],
                                'facts_unchecked': [], 'spans': 1, 'index': CLAIM['index'],
                                # 2O-4: every judged sentence, the one that decided marked
                                'sentences': [{'text': 'Pampers Swaddlers fit babies 2-9 lbs.', 'kind': 'attribute',
                                               'verdict': 'fabricated', 'facts_found': [],
                                               'facts_missing': [{'type': 'weight', 'text': '2-9 lbs'}],
                                               'facts_unchecked': [], 'decided': True,
                                               # 2P-1: none, a coder-3 fact carries no evidence line
                                               'evidence': []}]}


def test_a_row_before_the_new_verdict_carries_no_claim_evidence():
    assert rm.brand_claim_evidence({'brand_mentioned': True}) is None
    assert rm.brand_claim_evidence({'brand_claim': {**CLAIM, 'decided_by': None}})['span'] is None


def test_the_narratives_facts_carry_the_claim_and_its_facts():
    assert narratives.claim_facts({'brand_claim': CLAIM}) == {
        'said': 'Pampers Swaddlers fit babies 2-9 lbs.', 'never_published': ['2-9 lbs']}
    assert narratives.claim_facts({'brand_claim': {**CLAIM, 'decided_by': None}}) is None
    assert narratives.claim_facts({}) is None
