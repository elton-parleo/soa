"""
2O-6: the console's scorer is "16": brand-direct pack counts are an open set
(a count off the line's page is unverified, never fabricated) and the line
list closes only when complete (brand-claim coder version 6). No dimension
reads it, so it never explains a moved score.
"""
from app.services import console_score as score_svc
from soa_shared import expected_answers as ea


def _body(version, coded, of=258, oldest=None, coder=None):
    return {'scorer_version': version, 'score': 50, 'surfaces': [{'surface': 'grounded_api'}],
            'metric_counts': {}, 'metric_surface': None,
            'brand_coder': {'version': coder or ea.BRAND_CODER_VERSION, 'coded': coded, 'of': of, 'oldest': oldest}}


def test_the_version():
    assert score_svc.SCORER_VERSION == '16' and ea.BRAND_CODER_VERSION == 6
    assert score_svc.SCORER_CHANGES['16'] == 'brand-direct pack counts an open set; a count off the page is unverified'
    assert score_svc.SCORER_CHANGE_APPLIES['16']({}) is False
    assert score_svc.CODER_SCORER_VERSIONS == {None: '11', 1: '11', 2: '12', 3: '13', 4: '14', 5: '15', 6: '16'}


def test_fl14_re_scored_compares_as_its_oldest_outcome():
    assert score_svc.comparable_version(_body('16', 258, oldest=6)) == '16'
    # a score stored under 16 whose block still counts version-5 rows compares as 15
    assert score_svc.comparable_version(_body('16', 200, oldest=5)) == '15'
    # one stored under 15, some of its version-5 rows not coded by 5
    assert score_svc.comparable_version(_body('15', 200, oldest=4, coder=5)) == '14'
    prev = score_svc.compare(_body('16', 258, oldest=6), 'FL14-pampers-20261023', _body('16', 0, oldest=5))
    assert prev['comparable'] is False and prev['reason'] == 'Scored under v15, re-score to compare.'
