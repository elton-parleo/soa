"""
2C-3: the Share of Algorithm score on the console, from loop data.

The Audit's formula (scan_dimensions.py and the per-dimension scorers in
lite_pillars.py / cycle_scoring_full.py, called, never changed) over the W&S
fixture cycle and a two-surface extension of it. Every expected number below
is computed by hand in the test's docstring, dimension by dimension; the
same computation is in docs/console-read-models.md ("2C-3").
"""
import json

import pytest
from sqlalchemy import text

from tests.test_console_read_models import (  # noqa: F401  (pytest fixtures)
    CYCLE, TOKEN_A, _fixture, as_, db, http, upstream,
)
from tests.test_console_visibility_record import WS, WS_REFERENCE, ws_supply
from tests.test_console_2c2a import _add
from app.services import console_score as score
from app.services import console_read_models as rm
from soa_shared.scan_dimensions import DIMENSIONS, DIMENSIONS_BY_CODE, FULL_CYCLE_SCORER_VERSION, TOTAL_MAX

ACCESS = _fixture('supply_access_ws.json')


def _supply(upstream, *, access=True):
    ws_supply(upstream)
    if access:
        upstream.answer('GET', f'{WS}/access', body=ACCESS, token=TOKEN_A)


def _score(http, **params):
    response = http.get('/api/console/score', params={'cycle': CYCLE, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _dims(body):
    return {d['code']: d for p in body['pillars'] for d in p['dimensions']}


def _with_store(db):
    """The migration's two columns (sqlite: JSON is TEXT)."""
    with db.begin() as c:
        c.exec_driver_sql("ALTER TABLE soa_cycles ADD COLUMN share_of_algorithm TEXT")
        c.exec_driver_sql("ALTER TABLE soa_cycles ADD COLUMN share_of_algorithm_version TEXT")


# ═══ the mapping adapter ═════════════════════════════════════════════════

def test_crawl_counts_are_accessibility_s_counts_on_the_w_s_reads():
    """Agent identities: OAI-SearchBot, Googlebot, PerplexityBot through;
    Claude-User has no verified UA (not measured) and the Parleo control is
    not an agent. Pages: the 19 Oct 14 reads, all json_ld, 6 with a GTIN, 19
    with a price, 7 with a member price."""
    counts = score.crawl_counts(rm.accessibility_from_supply(ACCESS), WS_REFERENCE['rows'])
    assert {k: counts[k] for k in ('identities', 'through', 'pages', 'catalog', 'price', 'member_price')} == \
        {'identities': 3, 'through': 3, 'pages': 19, 'catalog': 6, 'price': 19, 'member_price': 7}
    # 2E: the Oct 14 reads are from a supply before #21: no incentive field at all
    assert counts['incentive_fields'] is False and counts['incentive_scanned'] == 0


def test_crawl_counts_with_nothing_read_are_zero_denominators():
    assert score.crawl_counts(None, None) == {'identities': 0, 'through': 0, 'pages': 0, 'catalog': 0,
                                              'price': 0, 'member_price': 0, 'incentive_fields': False,
                                              'incentive_scanned': 0, 'incentive_any': 0,
                                              'incentive_flags': {'member_price': 0, 'promo': 0, 'subscription': 0,
                                                                  'code': 0},
                                              'incentive_flags_text': {'member_price': 0, 'promo': 0, 'subscription': 0,
                                                                       'code': 0}}


def test_visibility_inputs_are_metrics_calculator_s():
    """som_pct = ours / every cycle entity's mentions (x100), rsi_score = the
    mean strength weight over ours (Primary 3, Positive 1, Neutral 0,
    Negative -1), over answered unprompted runs of the surface only."""
    runs = [{'run_id': 1, 'surface': 'api', 'tier': None, 'answer_status': 'answered'},
            {'run_id': 2, 'surface': 'api', 'tier': None, 'answer_status': 'answered'},
            {'run_id': 3, 'surface': 'api', 'tier': 'catalog_accuracy', 'answer_status': 'answered'},
            {'run_id': 4, 'surface': 'grounded_api', 'tier': None, 'answer_status': 'answered'},
            {'run_id': 5, 'surface': 'api', 'tier': None, 'answer_status': 'no_ai_answer'}]
    m = lambda run, role, strength=None, mentioned=True: {'run_id': run, 'role': role, 'strength': strength,
                                                          'mentioned': mentioned}
    mentions = [m(1, 'primary', 'Primary'), m(1, 'competitor'), m(2, 'primary', 'Negative'), m(2, 'competitor'),
                m(2, 'competitor', mentioned=False), m(3, 'primary', 'Primary'), m(4, 'primary', 'Primary'),
                m(5, 'primary', 'Primary')]
    v = score.visibility_inputs(runs, mentions, 'api')
    assert (v['runs'], v['ours'], v['all'], v['picks']) == (2, 2, 4, 1)
    assert v['som_pct'] == 50.0 and v['rsi_score'] == 1.0


def test_said_signals_are_the_scored_runs_cited_when_exact():
    runs = [{'surface': 'api', 'tier': 'catalog_accuracy', 'outcome': o, 'stage': 'Research'}
            for o in ('exact', 'wrong', 'stale', 'partial', 'unverifiable', 'absent', 'unscoreable')]
    signals = score.said_signals(runs, 'api', tier='catalog_accuracy')
    assert len(signals) == 4 and sum(s.primary_price_quoted for s in signals) == 1
    assert all(s.primary_mentioned and s.pass2_coded for s in signals)
    value = [{'surface': 'api', 'tier': 'value_incentives', 'outcome': 'exact', 'expected_type': t}
             for t in ('member_price', 'code', 'points')]
    member = score.said_signals(value, 'api', tier='value_incentives', types=score.MEMBER_TYPES)
    deal = score.said_signals(value, 'api', tier='value_incentives', types=score.DEAL_TYPES)
    assert len(member) == 1 and len(deal) == 2
    # placed in a purchase-intent stage, so the scorer's own filter keeps them
    from soa_shared.scan_dimensions import PURCHASE_INTENT_STAGES
    assert all(s.stage in PURCHASE_INTENT_STAGES for s in member + deal)


# ═══ the W&S fixture, by hand ════════════════════════════════════════════

def test_the_w_s_fixture_scores_60_on_34_applicable_points(http, upstream):
    """
    One pooled surface, the grounded API (the consumer UI's one run is
    no_ai_answer: left out, no answer on it).

    Visibility: the cycle asked no unprompted question. Share of Mentions
      and Recommendation Strength are not measured: 32 points out.
    Accessibility: Agent Access 3 of 3 measured identities, 3/3 x 5 = 5.0.
      Catalog & Context 6 of 19 pages json_ld with a GTIN, 6/19 x 8 = 2.53,
      2.5 (one place, as scan/scorer.py rounds). Protocol & Feed not
      measured: 5 out. 7.5 of 13.
    True Value: Price Truth seen 19/19 x 7 = 7.0. Said: 5 scored catalog
      runs, 1 exact, 20%, RATE_BAND 0.40 x 9 = 3.6, round 4 (the scorer's
      round). 11 of 16. Member Value: 7 pages with a member price, so the
      scorer's member_value_applicable holds. Seen 7/19 x 5 = 1.84, 1.8.
      Said: no value question, fewer than 2 in the set, the scorer's na,
      so dimension_max(said_na) = the seen 5. 1.8 of 5. Deal Citability:
      no seen source, the whole dimension out: 12. Value Protocols not
      measured: 14 out. 12.8 of 21.
    Earned 7.5 + 12.8 = 20.3 of 13 + 21 = 34. 20.3 / 34 x 100 = 59.7, 60.
    Not measured: 32 + 5 + 12 + 14 = 63 points, so no readiness verdict.
    """
    _supply(upstream)
    as_('alice')
    body = _score(http)
    assert (body['score'], body['earned'], body['applicable_max']) == (60, 20.3, 34.0)
    # 2I-6: the console's scorer is 8, the full-cycle scorer it reuses still 7
    assert body['scorer_version'] == '9' and FULL_CYCLE_SCORER_VERSION == '7'
    assert body['readiness_bar'] == 60 and body['total_max'] == 100.0
    assert body['verdict'] is None
    assert body['verdict_note'] == ('No readiness verdict while 63 of 100 points are not measured. '
                                    'The Audit gives one only when every dimension is.')
    [s] = body['surfaces']
    assert s['surface'] == 'grounded_api' and s['score'] == pytest.approx(20.3 / 34 * 100)
    assert body['surfaces_left_out'] == [{'surface': 'consumer_ui', 'label': 'Consumer UI, logged out',
                                          'reason': 'no answer on this surface'}]
    d = _dims(body)
    assert {k: (v['state'], v['score'], v['applicable_max']) for k, v in d.items()} == {
        'share_of_mentions': ('not_measured', None, 0.0), 'recommendation_strength': ('not_measured', None, 0.0),
        'agent_access': ('measured', 5.0, 5.0), 'catalog_context': ('measured', 2.5, 8.0),
        'protocol_feed': ('not_measured', None, 0.0),
        'price_truth': ('measured', 11.0, 16.0), 'member_value': ('measured', 1.8, 5.0),
        'deal_citability': ('not_measured', None, 0.0), 'value_protocols': ('not_measured', None, 0.0)}
    assert (d['catalog_context']['numerator'], d['catalog_context']['denominator']) == (6, 19)
    price = {p['half']: p for p in d['price_truth']['parts']}
    assert (price['seen']['score'], price['seen']['numerator'], price['seen']['denominator']) == (7.0, 19, 19)
    assert (price['said']['score'], price['said']['numerator'], price['said']['denominator']) == (4.0, 1, 5)
    member = {p['half']: p for p in d['member_value']['parts']}
    assert member['said']['state'] == 'na' and member['seen']['line'] == 'Member price in markup 7 of 19 pages'
    assert {p['name']: (p['score'], p['applicable_max'], p['max']) for p in body['pillars']} == {
        'Visibility': (None, 0.0, 32.0), 'Accessibility': (7.5, 13.0, 18.0), 'True Value': (12.8, 21.0, 50.0)}
    # the most points left: Catalog & Context, 8 - 2.5
    assert body['biggest_gap'] == {'dimension': 'Catalog & Context', 'code': 'catalog_context', 'points': 5.5,
                                   'line': 'Product markup with a GTIN 6 of 19 pages', 'surface': None,
                                   'numerator': 6, 'denominator': 19}
    # 2C-3a: a surface that ran with no answers is named in the coverage line
    assert body['coverage'] == {'surfaces': 1, 'questions': 6, 'agents': 2, 'runs': 7, 'ran_no_answers': ['consumer_ui'],
                                'line': '1 surface, 6 questions, 2 agents · pooled across surfaces, equal weight'
                                        ' · the consumer UI ran, no answers'}
    assert body['previous'] is None and body['stored'] is False   # no column before the migration


def test_the_w_s_metric_rows_are_the_overview_s_counts(http, upstream):
    _supply(upstream)
    as_('alice')
    body = _score(http)
    rows = {m['key']: (m['value'], m['denominator'], m['delta']) for m in body['metrics']}
    assert rows == {'first': (6, 7, None), 'share': (6, 7, None), 'program': (0, 6, None),
                    'exact': (1, 5, None), 'terms': (0, 0, None)}
    first = body['metrics'][0]
    assert first['surface_note'] == 'on the grounded API, every answered question'
    assert first['delta_reason'] == 'First cycle. Changes appear from the next one.'
    overview = http.get('/api/console/overview', params={'cycle': CYCLE}).json()['by_surface']['grounded_api']['totals']
    assert (overview['first'], overview['named'], overview['named_of']) == (6, 6, 7)


# ═══ the applicable max falls by exactly the unmeasured points ═══════════

def test_the_applicable_max_is_100_less_exactly_what_was_not_measured(http, upstream):
    _supply(upstream)
    as_('alice')
    body = _score(http)
    [s] = body['surfaces']
    d = _dims(body)
    out = sum(DIMENSIONS_BY_CODE[c].weight for c, v in d.items() if v['state'] == 'not_measured')
    rescaled = sum(DIMENSIONS_BY_CODE[c].said_max for c, v in d.items()
                   if v['state'] == 'measured' and any(p['half'] == 'said' and p['state'] == 'na' for p in v['parts']))
    assert (out, rescaled) == (63, 3)
    assert s['applicable_max'] == TOTAL_MAX - out - rescaled == 34


def test_a_failed_access_read_takes_out_exactly_agent_access_s_five(http, upstream):
    _supply(upstream, access=False)
    upstream.answer('GET', f'{WS}/access', status=502, body={'detail': 'down'}, token=TOKEN_A)
    as_('alice')
    body = _score(http)
    aa = _dims(body)['agent_access']
    assert aa['state'] == 'not_measured' and aa['score'] is None and 'access read failed' in aa['reason']
    assert body['applicable_max'] == 34 - 5 and body['earned'] == pytest.approx(20.3 - 5)
    assert body['stored'] is False and 'access' in body['read_errors']


def test_a_not_measured_dimension_is_never_a_zero(http, upstream):
    _supply(upstream)
    as_('alice')
    for d in _dims(_score(http)).values():
        if d['state'] == 'not_measured':
            assert d['score'] is None and d['applicable_max'] == 0 and d['reason']


# ═══ a two-surface fixture: pooled = the mean of the surface scores ══════

def _two_surfaces(db):
    """W&S plus unprompted and value-tier runs on the grounded API (ChatGPT,
    Gemini) and the consumer UI (AI Mode). Entity 1 is ours, 2 Huggies."""
    q = lambda qid, tier, expected, stage='Comparison': _add(db, 'soa_queries', {
        'id': qid, 'query_code': f'WIG_{qid}', 'query_text': f'question {qid}', 'stage': stage,
        'study_type': 'ws-2b-fixture', 'tier': tier, 'expected_answer': expected, 'provenance': 'catalog',
        'source_ref': {'merchant_slug': 'wiggle-and-snug'}})
    q(7, None, {}), q(8, None, {}, 'Ready to Buy')
    q(9, 'value_incentives', {'type': 'member_price', 'amount': '12.09'})
    q(10, 'value_incentives', {'type': 'code', 'code': 'WELCOME10'})

    def run(rid, qid, platform, surface, tier=None, outcome=None, mentions=()):
        _add(db, 'soa_runs', {'id': rid, 'cycle_id': 1, 'query_id': qid, 'platform': platform, 'run_number': 1,
                              'run_at': '2026-10-09T15:00:00+00:00', 'raw_response': 'answer', 'status': 'success',
                              'surface': surface, 'answer_status': 'answered'})
        if tier:
            _add(db, 'soa_expectation_outcomes', {'run_id': rid, 'query_id': qid, 'cycle_id': 1, 'platform': platform,
                                                  'tier': tier, 'outcome': outcome, 'surface': surface,
                                                  'expected_answer': {}, 'flags': [], 'outcome_reason': 'r'})
        for entity, strength in mentions:
            _add(db, 'soa_coded_mentions', {'run_id': rid, 'entity_id': entity, 'mentioned': True,
                                            'position': 1 if entity == 1 else 2, 'strength': strength})

    g, c = 'grounded_api', 'consumer_ui'
    # grounded API, unprompted: ours 2 of 6 mentions, Primary and Positive
    run(3101, 7, 'chatgpt', g, mentions=[(1, 'Primary'), (2, 'Positive')])
    run(3102, 7, 'gemini_grounded', g, mentions=[(1, 'Positive'), (2, 'Neutral')])
    run(3103, 8, 'chatgpt', g, mentions=[(2, 'Primary')])
    run(3104, 8, 'gemini_grounded', g, mentions=[(2, 'Positive')])
    # grounded API, value tier: Member+ 1 of 2 exact, codes 2 of 2
    run(3105, 9, 'chatgpt', g, 'value_incentives', 'exact')
    run(3106, 9, 'gemini_grounded', g, 'value_incentives', 'wrong')
    run(3107, 10, 'chatgpt', g, 'value_incentives', 'exact')
    run(3108, 10, 'gemini_grounded', g, 'value_incentives', 'exact')
    # consumer UI (AI Mode): unprompted ours 1 of 3, Positive
    run(3201, 7, 'aimode', c, mentions=[(1, 'Positive'), (2, 'Neutral')])
    run(3202, 8, 'aimode', c, mentions=[(2, 'Primary')])
    # consumer UI, catalog 2 of 3 exact, Member+ 2 of 2
    run(3203, 1, 'aimode', c, 'catalog_accuracy', 'exact')
    run(3204, 2, 'aimode', c, 'catalog_accuracy', 'exact')
    run(3205, 3, 'aimode', c, 'catalog_accuracy', 'wrong')
    run(3206, 9, 'aimode', c, 'value_incentives', 'exact')
    run(3207, 9, 'aimode', c, 'value_incentives', 'exact')


def test_the_pooled_score_is_the_mean_of_the_surface_scores(http, upstream, db):
    """
    Accessibility on both: 5.0 + 2.5 = 7.5 of 13 (crawl-side, one value).
    Price Truth seen 7.0, Member Value seen 1.8 on both.

    Grounded API. SoM: 2 of 6 = 33.3%, round(33.3/50 x 22) = round(14.7) = 15.
      RS: rsi (3 + 1)/2 = 2.0, round((2 + 1)/4 x 10) = round(7.5) = 8.
      Visibility 23 of 32. Price said 1 of 5 (the fixture's), 4: 11 of 16.
      Member said 1 of 2, 50%, 0.70 x 3 = 2.1, 2: 1.8 + 2 = 3.8 of 8.
      Deal said 2 of 2, 100%, 5: shown, not counted (no seen half).
      Earned 23 + 7.5 + 11 + 3.8 = 45.3 of 32 + 13 + 16 + 8 = 69: 65.652.
    Consumer UI. SoM: 1 of 3 = 33.3%, 15. RS: rsi 1.0, round(2/4 x 10) = 5.
      Visibility 20 of 32. Price said 2 of 3, 66.7%, 1.0 x 9 = 9: 16 of 16.
      Member said 2 of 2, 3: 4.8 of 8. Deal said: none asked, na.
      Earned 20 + 7.5 + 16 + 4.8 = 48.3 of 69: 70.0.
    Pooled: (65.652 + 70.0) / 2 = 67.83, rounded once: 68.
    """
    _two_surfaces(db)
    _supply(upstream)
    as_('alice')
    body = _score(http)
    by = {s['surface']: s for s in body['surfaces']}
    assert set(by) == {'grounded_api', 'consumer_ui'} and body['surfaces_left_out'] == []
    assert (by['grounded_api']['earned'], by['grounded_api']['applicable_max']) == (45.3, 69)
    assert (by['consumer_ui']['earned'], by['consumer_ui']['applicable_max']) == (48.3, 69)
    assert by['grounded_api']['score'] == pytest.approx(45.3 / 69 * 100)
    assert by['consumer_ui']['score'] == pytest.approx(70.0)
    assert body['score'] == round((by['grounded_api']['score'] + by['consumer_ui']['score']) / 2) == 68
    d = _dims(body)
    som = d['share_of_mentions']
    assert som['by_surface']['grounded_api']['score'] == 15 and som['by_surface']['consumer_ui']['score'] == 15
    assert som['numerator'] is None and som['denominator'] is None   # per surface, never pooled
    rs = d['recommendation_strength']['by_surface']
    assert (rs['grounded_api']['score'], rs['consumer_ui']['score']) == (8.0, 5.0)
    assert d['recommendation_strength']['score'] == 6.5
    deal = d['deal_citability']
    assert deal['state'] == 'not_measured' and deal['applicable_max'] == 0
    said = next(p for p in deal['by_surface']['grounded_api']['parts'] if p['half'] == 'said')
    assert (said['state'], said['score'], said['numerator'], said['denominator']) == ('measured', 5.0, 2, 2)
    mv = d['member_value']['by_surface']
    assert (mv['grounded_api']['score'], mv['consumer_ui']['score']) == (3.8, 4.8)
    # the pooled pillar is the mean of the surfaces' pillar points
    vis = next(p for p in body['pillars'] if p['code'] == 'visibility')
    assert (vis['score'], vis['applicable_max']) == (21.5, 32.0)
    # biggest gap: Share of Mentions, 22 - 15 = 7 points left on both
    assert body['biggest_gap']['dimension'] == 'Share of Mentions' and body['biggest_gap']['points'] == 7.0
    assert body['biggest_gap']['line'].startswith('Share of mentions ')
    assert body['coverage']['line'] == '2 surfaces, 10 questions, 3 agents · pooled across surfaces, equal weight'
    # the five rows stay per surface, on the highest-fidelity one, every surface beside
    first = body['metrics'][0]
    assert first['surface'] == 'consumer_ui' and set(first['by_surface']) == {'consumer_ui', 'grounded_api'}
    assert (first['value'], first['denominator']) == (1, 2)
    terms = next(m for m in body['metrics'] if m['key'] == 'terms')
    assert (terms['value'], terms['denominator']) == (2, 2)
    assert terms['by_surface']['grounded_api'] == {'value': 3, 'of': 4}


def test_no_count_is_summed_across_surfaces(http, upstream, db):
    _two_surfaces(db)
    _supply(upstream)
    as_('alice')
    body = _score(http)
    for d in _dims(body).values():
        surfaces_ = d['by_surface']
        if d['numerator'] is not None:
            # a pooled numerator only where every surface reads the same one
            assert all(p['numerator'] == d['numerator'] for s in surfaces_.values() for p in s['parts'])


# ═══ stored, versioned, compared ═════════════════════════════════════════

def _previous_cycle(db, stored=None):
    _add(db, 'soa_cycles', {'id': 2, 'cycle_code': 'WS-EARLIER', 'study_type': 'ws-2b-fixture', 'status': 'complete',
                            'start_date': '2026-10-01', 'platforms': ['chatgpt'], 'runs_per_query': 1,
                            'organization_id': 1})
    _add(db, 'soa_expectation_outcomes', {'run_id': 9001, 'query_id': 1, 'cycle_id': 2, 'platform': 'chatgpt',
                                          'tier': 'catalog_accuracy', 'outcome': 'exact', 'surface': 'grounded_api',
                                          'expected_answer': {}, 'flags': [], 'outcome_reason': 'r'})
    if stored is not None:
        with db.begin() as c:
            c.execute(text("UPDATE soa_cycles SET share_of_algorithm = :b, share_of_algorithm_version = :v WHERE id = 2"),
                      {'b': json.dumps(stored), 'v': stored['scorer_version']})


def test_the_score_is_stored_with_its_version_and_served_from_the_row(http, upstream, db):
    _with_store(db)
    _supply(upstream)
    as_('alice')
    first = _score(http)
    assert first['stored'] is True
    with db.connect() as c:
        raw, version = c.execute(text("SELECT share_of_algorithm, share_of_algorithm_version FROM soa_cycles WHERE id = 1")).one()
    assert version == '9' and json.loads(raw)['score'] == 60
    calls = len(upstream.calls)
    again = _score(http)
    assert len(upstream.calls) == calls          # served from the row: no supply read
    assert again['score'] == 60 and again['inputs'] == first['inputs']


def test_a_score_stored_under_another_version_is_recomputed(http, upstream, db):
    _with_store(db)
    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET share_of_algorithm = :b, share_of_algorithm_version = '5' WHERE id = 1"),
                  {'b': json.dumps({'scorer_version': '5', 'adapter_revision': 1, 'score': 12})})
    _supply(upstream)
    as_('alice')
    body = _score(http)
    assert (body['score'], body['scorer_version'], body['stored']) == (60, '9', True)


def test_a_previous_cycle_scored_under_another_version_is_not_comparable(http, upstream, db):
    _with_store(db)
    _previous_cycle(db, stored={'scorer_version': '5', 'adapter_revision': 1, 'score': 41, 'surfaces': []})
    _supply(upstream)
    as_('alice')
    body = _score(http)
    assert body['previous'] == {'cycle': 'WS-EARLIER', 'scorer_version': '5', 'score': 41, 'comparable': False,
                                'reason': 'Scored under v5, re-score to compare.'}
    assert all(m['delta'] is None and m['delta_reason'] == 'Scored under v5, re-score to compare.'
               for m in body['metrics'])


def test_a_previous_cycle_with_no_stored_score_is_not_comparable(http, upstream, db):
    _with_store(db)
    _previous_cycle(db)
    _supply(upstream)
    as_('alice')
    prev = _score(http)['previous']
    assert prev['comparable'] is False and prev['reason'] == 'Not comparable: WS-EARLIER has no stored score yet. Open it to score it.'


def test_a_comparable_previous_cycle_gives_deltas(http, upstream, db):
    _with_store(db)
    _supply(upstream)
    as_('alice')
    now = _score(http)
    earlier = json.loads(json.dumps({k: now[k] for k in ('scorer_version', 'adapter_revision', 'surfaces', 'metric_counts')}))
    earlier['score'] = 55
    earlier['metric_counts']['grounded_api']['exact'] = {'value': 3, 'of': 5}
    _previous_cycle(db, stored=earlier)
    body = _score(http)
    assert body['previous']['comparable'] is True and body['previous']['delta'] == 5
    rows = {m['key']: m for m in body['metrics']}
    assert rows['exact']['delta'] == 1 - 3 and rows['exact']['delta_reason'] is None
    assert rows['first']['delta'] == 0


def test_a_previous_cycle_on_other_agents_is_not_comparable(http, upstream, db):
    _with_store(db)
    _supply(upstream)
    as_('alice')
    now = _score(http)
    earlier = json.loads(json.dumps({k: now[k] for k in ('scorer_version', 'adapter_revision', 'surfaces', 'metric_counts', 'score')}))
    earlier['metric_counts']['grounded_api']['agent_set'] = ['chatgpt']
    _previous_cycle(db, stored=earlier)
    prev = _score(http)['previous']
    assert prev['comparable'] is False
    assert prev['reason'] == 'Not comparable: on the grounded API WS-EARLIER ran ChatGPT, this cycle ran ChatGPT and Gemini.'


# ═══ tenancy ═════════════════════════════════════════════════════════════

def test_the_score_is_tenant_scoped(http, upstream):
    _supply(upstream)
    as_('bob')
    assert http.get('/api/console/score', params={'cycle': CYCLE}).status_code == 404
    as_('alice')
    assert http.get('/api/console/score', params={'cycle': CYCLE, 'org': 20}).status_code == 403
    as_('op')
    assert http.get('/api/console/score', params={'cycle': CYCLE, 'org': 10}).json()['score'] == 60


def test_only_an_operator_can_rescore(http, upstream):
    _supply(upstream)
    as_('alice')
    assert http.get('/api/console/score', params={'cycle': CYCLE, 'rescore': 'true'}).status_code == 403
    as_('op')
    assert http.get('/api/console/score', params={'cycle': CYCLE, 'org': 10, 'rescore': 'true'}).status_code == 200


def test_every_supply_read_went_up_with_the_tenant_s_token(http, upstream):
    _supply(upstream)
    as_('alice')
    _score(http)
    reads = [c for c in upstream.calls if c['path'].endswith(('/access', '/reference'))]
    assert len(reads) == 2 and all(c['token'] == TOKEN_A for c in reads)


# ═══ house rules and the registry ════════════════════════════════════════

def test_no_template_has_a_dash_or_a_semicolon():
    for rule, text_ in score.TEMPLATES.items():
        assert '—' not in text_ and '–' not in text_ and ';' not in text_, rule


def test_every_audit_dimension_has_a_row_in_registry_order(http, upstream):
    _supply(upstream)
    as_('alice')
    body = _score(http)
    assert [d['code'] for d in _dims(body).values()] == [
        'share_of_mentions', 'recommendation_strength', 'agent_access', 'catalog_context', 'protocol_feed',
        'price_truth', 'member_value', 'deal_citability', 'value_protocols']
    assert {d.code for d in DIMENSIONS} == set(_dims(body))
    assert [p['max'] for p in body['pillars']] == [32.0, 18.0, 50.0]
