"""
2O-1 (H27): the brand-claim coder makes two calls that must agree
(apps/pipeline/scoring/brand_direct_classifier.settle), and the console's
scorer is "12".

A cycle is compared on scorer 12 only once every brand-direct outcome it
holds was coded by the two-call coder (console_score.comparable_version):
FL14 after `rescore_cycle.py --cycle FL14-pampers-20261023`. A cycle whose
outcomes one call wrote compares as "11", so FL14 re-scored is not
comparable to a cycle still on the old coder, and says so.

An answer the coder could not settle is `unscoreable` (coder_disagreed):
outside every count, and its Answers line says so.
"""
from app.services import console_parity as parity
from app.services import console_read_models as rm
from app.services import console_score as score_svc
from soa_shared import expected_answers as ea


def _runs(n, coded):
    """n scored brand-direct runs, `coded` of them by the two-call coder, and a
    catalog run beside them (which carries no coder)."""
    rows = [{'tier': 'brand_direct', 'outcome': 'echoed',
             'coder_version': ea.BRAND_CODER_VERSION if i < coded else None} for i in range(n)]
    return rows + [{'tier': 'catalog_accuracy', 'outcome': 'exact'}]


def _body(version, coded, of=258):
    return {'scorer_version': version, 'score': 50, 'surfaces': [{'surface': 'grounded_api'}],
            'metric_counts': {}, 'metric_surface': None,
            **({'brand_coder': {'version': ea.BRAND_CODER_VERSION, 'coded': coded, 'of': of}} if coded is not None else {})}


def test_the_version():
    assert score_svc.SCORER_VERSION == '12' and score_svc.SINGLE_CALL_CODER_VERSION == '11'
    assert score_svc.SCORER_CHANGES['12'] == 'brand-direct answers coded by two agreeing calls'
    # no dimension reads the brand-direct outcome: the version never explains a moved score
    assert score_svc.SCORER_CHANGE_APPLIES['12']({}) is False
    assert ea.BRAND_CODER_VERSION == 2


def test_the_coder_count_reads_the_scored_brand_direct_runs():
    assert score_svc.brand_coder(_runs(258, 258)) == {'version': 2, 'coded': 258, 'of': 258}
    assert score_svc.brand_coder(_runs(258, 0)) == {'version': 2, 'coded': 0, 'of': 258}
    # an unscored run is not counted; a cycle with no brand-direct tier is all coded
    unscored = [{'tier': 'brand_direct', 'outcome': None}]
    assert score_svc.brand_coder(unscored) == {'version': 2, 'coded': 0, 'of': 0}


def test_the_overview_rows_carry_the_coder_that_scored_them():
    """load_overview_rows reads it off the stored extraction (no new column)."""
    class Conn:
        def execute(self, *_a, **_k):
            return self

        def mappings(self):
            return iter([
                {'run_id': 1, 'platform': 'perplexity', 'surface': 'grounded_api', 'answer_status': 'answered',
                 'tier': 'brand_direct', 'stage': None, 'query_code': 'PAM_210', 'query_text': 'q',
                 'source_ref': '{}', 'outcome': 'echoed', 'reason_code': None,
                 'extraction': '{"brand_mentioned": true, "coder": {"version": 2, "calls": []}}'},
                {'run_id': 2, 'platform': 'perplexity', 'surface': 'grounded_api', 'answer_status': 'answered',
                 'tier': 'brand_direct', 'stage': None, 'query_code': 'PAM_211', 'query_text': 'q',
                 'source_ref': '{}', 'outcome': 'echoed', 'reason_code': None,
                 'extraction': '{"brand_mentioned": true}'},
            ])

    import app.services.console_read_models as rmod
    real = rmod.brand_sets_no_price_runs
    rmod.brand_sets_no_price_runs = lambda *_a: set()
    try:
        rows = parity.load_overview_rows(Conn(), {'id': 236})
    finally:
        rmod.brand_sets_no_price_runs = real
    assert [r['coder_version'] for r in rows] == [2, None]


def test_a_cycle_compares_on_12_only_once_its_brand_direct_outcomes_are_re_scored():
    assert score_svc.comparable_version(_body('12', 258)) == '12'
    assert score_svc.comparable_version(_body('12', 0)) == '11'
    assert score_svc.comparable_version(_body('12', 257)) == '11'
    assert score_svc.comparable_version(_body('12', 0, of=0)) == '12'
    assert score_svc.comparable_version(_body('11', None)) == '11'


def test_fl14_re_scored_is_not_comparable_to_a_cycle_on_the_old_coder():
    fl14 = _body('12', 258)
    # FL13 stored under 11, before the bump
    prev = score_svc.compare(fl14, 'FL13-pampers-20261022', _body('11', None))
    assert prev['comparable'] is False and prev['condition'] == 'version'
    assert prev['reason'] == 'Scored under v11, re-score to compare.'
    # FL13 opened after the deploy: recomputed under 12, its outcomes still one call's
    prev = score_svc.compare(fl14, 'FL13-pampers-20261022', _body('12', 0))
    assert prev['comparable'] is False and prev['reason'] == 'Scored under v11, re-score to compare.'
    # both re-scored on the two-call coder: the version no longer stands between them
    prev = score_svc.compare(fl14, 'FL13-pampers-20261022', _body('12', 258))
    assert prev['condition'] != 'version'


def test_fl14_before_its_rescore_is_stale_and_after_it_current():
    """Elton's rerun: the stored v11 score recomputes on its next read
    ('stale'); recomputed over two-call outcomes it is current."""
    assert score_svc.needs_recompute({'scorer_version': '11', 'adapter_revision': score_svc.ADAPTER_REVISION},
                                     None) == 'stale'
    assert score_svc.is_current({'scorer_version': '12', 'adapter_revision': score_svc.ADAPTER_REVISION})


def test_an_unsettled_answer_reads_the_coder_could_not_settle_it():
    run = {'id': 15342, 'platform': 'copilot', 'run_number': 1, 'answer_status': 'answered', 'raw_response': 'x'}
    query = {'tier': 'brand_direct', 'query_text': 'Is Pampers AMORE good for newborns?', 'source_ref': {}}
    outcome = {'outcome': 'unscoreable', 'reason_code': ea.CODER_DISAGREED, 'outcome_reason': ea.CODER_DISAGREED_NOTE,
               'expected_answer': {'type': 'brand_mention', 'brand': 'Pampers'}, 'extraction': {}}
    a = rm.build_answer(run, query, outcome, [], runs_per_query=1, cycle_code='FL14')
    assert a['summary'] == 'the coder could not settle this answer'
    assert (a['brand_verdict'], a['reason'], a['tone']) == ('unscoreable', 'coder_disagreed', 'neu')


def test_an_unsettled_answer_is_outside_every_brand_count():
    rows = [{'run_id': i, 'platform': 'perplexity', 'surface': 'grounded_api', 'answer_status': 'answered',
             'tier': 'brand_direct', 'query_code': f'Q{i}', 'query_text': 'q', 'outcome': o,
             'reason_code': ea.CODER_DISAGREED if o == 'unscoreable' else None, 'claim_kind': None}
            for i, o in enumerate(['fabricated', 'grounded', 'unscoreable'])]
    totals = parity.surface_metrics(rows, [], 'grounded_api')['total']
    assert totals['brand_scored'] == 2 and totals['fabricated'] == 1
