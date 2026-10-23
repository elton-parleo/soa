"""
2N-2: three leftovers from the FL14 rescore (FL14-pampers-20261023).

1. After the rescore the Overview's Changes counted the accuracy answers
   ("11 of 18 accuracy answers on Size 4 gave the range pampers.com
   states", Size 1 11 of 12, Size 3 9 of 12) while the Attribute accuracy
   tile read "pages 11 of 20, answers 0 of 0". Both read
   rm.attribute_answers (the cycle's truth_index); the tile is /score's,
   and /score served the score stored before 2N-1, which a re-score with no
   reference refresh never recomputed. The stored score now recomputes when
   the cycle's outcomes were written after it ('outcomes re-scored'), and
   the tile and the Changes lines count the same answers.
2. The promo tile's note read "Amazon Rollback: named 3 of 6", that same
   stored score. Every reader of the deal's kind takes kind_label, the
   Trade promotions row's.
3. The narratives' facts: a deal as its title, never the shelf's evidence
   (run-15013, 15118, 15342); a where-to-buy claim as the stores it named
   (named_stores), never the scorer's label (run-15031, 15036, 15064,
   15069, 15185, 15163); a quoted fragment dropped (run-15161).
"""
from app.services import console_read_models as rm
from app.services import console_score as score_svc
from soa_shared import narratives as nv
from soa_shared import promo_pass_through as ppt
from tests import console_fixture_2j2 as f2j2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2j4 import BEFORE, _cycle, _get, _supply
from tests.test_console_2n1_parity import FL14_DEAL
from tests.test_console_read_models import http, upstream  # noqa: F401  (fixtures)
from sqlalchemy import text

SURFACES = ('grounded_api', 'consumer_ui')
#: FL14's accuracy answers after the rescore: (size, judged, matched), as its Changes read them
FL14_SIZES = [('Size 4', 18, 11), ('Size 1', 12, 11), ('Size 3', 12, 9)]
FL14_PAGES = {'n': 20, 'k': 11}


def _fl14_answers():
    """rm.attribute_answers' rows on FL14's shape, the misses first on each size."""
    out, run = [], 0
    for size, judged, matched in FL14_SIZES:
        for i in range(judged):
            run += 1
            out.append({'run_id': run, 'platform': 'claude', 'surface': SURFACES[i % 2], 'variant_id': f'v-{size}',
                        'variant': f'Swaddlers {size}', 'size': size, 'site': 'pampers.com',
                        'stated': {'min': 22.0, 'max': 37.0}, 'truth': {'min': 15.0, 'max': 34.0},
                        'verdict': 'match' if i >= judged - matched else 'mismatch', 'evidence': None})
    return out


def _fl14_reference():
    return {'attributes': [{'variant_label': 'Size 4, 120 ct', 'truth': {'min': 15.0, 'max': 34.0},
                            'pages': {**FL14_PAGES, 'rows': []}}]}


def _tile(accuracy, surface):
    counts = score_svc.brand_counts({'attribute_accuracy': accuracy}, [], surface, 'all',
                                    {'named': 0, 'named_of': 0, 'first': 0}, surface_set=list(SURFACES))
    return counts['attribute']


def test_the_tile_counts_the_answers_the_changes_lines_count():
    answers = _fl14_answers()
    accuracy = rm.build_attribute_accuracy(answers, _fl14_reference())
    # every size missed on `all`, so the Changes lines (one per size with a miss) cover every judged answer
    tile = _tile(accuracy, 'all')
    changes = rm.attribute_changes(answers, None, None, 'all', compared=False, site='pampers.com')
    assert tile['answers'] == {'n': sum(c['of_now'] for c in changes), 'k': sum(c['now'] for c in changes)} == \
        {'n': 42, 'k': 31}
    assert (tile['of'], tile['value']) == (FL14_PAGES['n'] + 42, FL14_PAGES['k'] + 31)
    assert [c['detail'].split('.')[0] for c in changes] == [
        '11 of 18 accuracy answers on Size 4 gave the range pampers', '11 of 12 accuracy answers on Size 1 gave the range pampers',
        '9 of 12 accuracy answers on Size 3 gave the range pampers']
    assert score_svc._brand_sub('attribute', _tile(accuracy, 'all')) == \
        'Weight range for the size asked: pages 11 of 20, answers 31 of 42'


def test_a_score_stored_before_its_outcomes_were_re_scored_recomputes():
    stored = {'scorer_version': score_svc.SCORER_VERSION, 'adapter_revision': score_svc.ADAPTER_REVISION,
              'measured': [], 'inputs': {'scored_at': '2026-10-23T15:00:00+00:00'}}
    assert score_svc.needs_recompute(stored, None, None) is None
    assert score_svc.needs_recompute(stored, None, None, '2026-10-23T14:59:59+00:00') is None
    assert score_svc.needs_recompute(stored, None, None, '2026-10-23T21:30:00+00:00') == 'outcomes re-scored'
    # a stamp with no zone is UTC (NOW() into the column; sqlite's text)
    assert score_svc.needs_recompute(stored, None, None, '2026-10-23 21:30:00') == 'outcomes re-scored'
    assert score_svc.needs_recompute(stored, None, None, '2026-10-23 14:00:00') is None
    assert score_svc.needs_recompute({**stored, 'inputs': {}}, None, None, '2026-10-23T21:30:00+00:00') is None


def _rescored(db, at: str) -> None:
    with db.begin() as c:
        c.execute(text("UPDATE soa_expectation_outcomes SET scored_at = :t WHERE cycle_id = "
                       "(SELECT id FROM soa_cycles WHERE cycle_code = :c)"), {'t': at, 'c': f2j2.CYCLE})


def test_the_stored_score_recomputes_once_after_a_re_score(http, db, upstream):
    _cycle(db, BEFORE)
    kind = 'TIMESTAMP WITH TIME ZONE' if db.dialect.name == 'postgresql' else 'TEXT'
    with db.begin() as c:
        c.exec_driver_sql(f"ALTER TABLE soa_expectation_outcomes ADD COLUMN scored_at {kind}")
    _rescored(db, '2026-10-01T09:00:00+00:00')
    _supply(upstream)
    first = _get(http, 'score', merchant=f2j2.MERCHANT)
    scored_at = first['inputs']['scored_at']
    assert first['stored'] is True and _get(http, 'score', merchant=f2j2.MERCHANT)['inputs']['scored_at'] == scored_at

    _rescored(db, '2099-01-01T00:00:00+00:00')     # rescore_cycle.py, after the score was stored
    again = _get(http, 'score', merchant=f2j2.MERCHANT)
    assert again['history'][-1]['replaced_because'] == 'outcomes re-scored'
    assert again['history'][-1]['scored_at'] == scored_at
    _rescored(db, '2026-10-01T09:00:00+00:00')
    assert _get(http, 'score', merchant=f2j2.MERCHANT)['inputs']['scored_at'] == again['inputs']['scored_at']


def test_every_reader_of_the_deal_s_kind_says_what_the_row_says():
    judged = [{'run_id': i, 'surface': SURFACES[i % 2], 'intent': ppt.CHEAPEST_PLACE,
               'source_ref': {'intent': ppt.CHEAPEST_PLACE, 'sku': 'amore-1'},
               'text': 'Amazon has it at $36.18, was $47.99' if i < 3 else 'Try Amazon at $36.18'} for i in range(6)]
    deals = {'deals': [FL14_DEAL], 'walled': []}
    promo = rm.build_promo_pass_through(judged, deals, '2026-10-23')
    [entry] = promo['per_deal']
    assert entry['kind_label'] == 'list price cut' and entry['short'] == 'Amazon list price cut'
    assert promo['note'] == 'Cheapest-place answers naming a deal live that day. Amazon list price cut: named 3 of 6'
    counts = score_svc.brand_counts({'promo_pass_through': promo}, [], 'all', 'all',
                                    {'named': 0, 'named_of': 0, 'first': 0}, surface_set=list(SURFACES))
    assert counts['promo']['deal']['kind_label'] == 'list price cut'
    assert score_svc._brand_sub('promo', counts['promo']) == \
        'Cheapest-place answers naming a deal live that day. Amazon list price cut: named 3 of 6'
    [row] = rm.build_prove(promo, deals, 'Pampers', '2026-10-23')['rows']
    assert row['kind_label'] == entry['kind_label']
    (line,) = rm.promo_changes(promo, None, None, 'all', compared=False)
    assert 'Amazon list price cut ran on 1 SKU' in line['detail'] and 'Rollback' not in line['detail']


# ─── 3. Narrative facts for deals, and two quote problems (FL14 --narratives) ───


PAMPERS = nv.Merchant(name='Pampers', kind='brand', terms=('Pampers',))
LABEL = "'told the reader to buy it at Walgreens, Walmart, Target' — where to buy, stated with no source"


def test_a_deal_s_facts_are_its_title_never_the_shelf_s_evidence():
    fact = nv._deal_fact({**FL14_DEAL, 'variant': FL14_DEAL['variants'][0]})
    assert fact == {'retailer': 'Amazon', 'deal': '25% off list price on AMORE Size 1, $36.18 from $47.99',
                    'price_that_day': '36.18', 'was_price': '47.99', 'deal_price': '36.18'}
    facts = {'kind': nv.ANSWER, 'why': ['promo_missed'], 'agent': 'Copilot', 'brand': 'Pampers',
             'question': 'Cheapest place to buy Pampers AMORE Size 1?', 'deals_live_that_day': [fact],
             'agent_quoted': [{'price_quoted': '66.98', 'asked_at': 'Amazon'}]}
    line = ('Copilot quoted $66.98 at Amazon. Amazon charged $36.18 that day and ran 25% off list price on '
            'AMORE Size 1, which the answer never mentions.')
    assert nv.check(line, facts) is None
    # run-15342's line, written from the evidence the facts no longer carry
    run_15342 = ('Copilot quoted $66.98 at Amazon. Amazon charged $36.18 that day and ran $36.18 with 25 percent '
                 'savings -25% $ 36 . 18 $0.27 per count ( $0.27 $0.27 / count) List Price: $47.99, which the '
                 'answer never mentions.')
    assert nv.check(run_15342, facts) is not None


def _where_run():
    return {'id': 15031, 'platform': 'gemini_grounded', 'surface': 'grounded_api', 'answer_status': 'answered',
            'tier': 'brand_direct', 'raw_response': 'You can buy Pampers at Walgreens, Walmart and Target.',
            'query_text': 'Where can I buy Pampers Swaddlers?', 'source_ref': {'merchant_slug': 'pampers'}}


def test_a_where_to_buy_claim_gives_the_stores_and_never_the_scorer_s_label():
    outcome = {'outcome': 'fabricated', 'outcome_reason': LABEL, 'extraction': {}}
    facts = nv.answer_facts(_where_run(), outcome, [], PAMPERS, {})
    assert facts['why'] == ['brand_fabricated']
    assert facts['named_stores'] == ['Walgreens', 'Walmart', 'Target']
    assert facts['scorer_note'] == 'where to buy, stated with no source' and 'reader' not in nv.facts_text(facts)
    assert nv.claim_texts(facts) == []
    assert nv.system_prompt(facts) == nv.STORES_PROMPT
    assert 'Gemini named Walgreens, Walmart and Target as places to buy it. Pampers never published that list.' \
        in nv.STORES_PROMPT
    assert nv.check('Gemini named Walgreens, Walmart and Target as places to buy it. Pampers never published that list.',
                    facts) is None
    assert nv.check('Gemini named Walgreens, Costco and Target as places to buy it. Pampers never published that list.',
                    facts) == 'name_not_in_facts:costco'
    assert nv.check('Gemini said "told the reader to buy it at Walgreens, Walmart, Target". Pampers never published '
                    'it and no source backs it.', facts) == 'banned:reader'
    # any other claim keeps its note, its prompt and its request
    other = {'outcome': 'fabricated', 'extraction': {},
             'outcome_reason': "'Pampers Zzz is still available' — a product claim, stated with no source"}
    facts = nv.answer_facts(_where_run(), other, [], PAMPERS, {})
    assert 'named_stores' not in facts and nv.system_prompt(facts) == nv.SYSTEM_PROMPT
    assert nv.claim_texts(facts) == ['Pampers Zzz is still available']


def test_a_quoted_fragment_is_dropped():
    facts = {'kind': nv.ANSWER, 'why': ['brand_fabricated'], 'agent': 'Google AI Mode', 'brand': 'Pampers',
             'answer_spans': ["Pampers Swaddlers Overnights are Pampers' dedicated, strongest option for overnight "
                              "protection."]}
    tail = ' Pampers never published it and no source backs it.'
    # run-15161, accepted on FL14
    assert nv.check('Google AI Mode said "Pampers\' never published it and no source backs it.', facts) == \
        'quote_unclosed'
    assert nv.check('Google AI Mode said "Pampers\'".' + tail, facts) == 'quote_too_short:8'
    assert nv.check('Google AI Mode said "Pampers Swaddlers Overnig".' + tail, facts) == 'quote_cut'
    assert nv.check('Google AI Mode said "Swaddlers Overnights are Pampers\'".' + tail, facts) == 'quote_cut'
    assert nv.check('Google AI Mode said "are Pampers\' dedicated, strongest option for overnight protection."' + tail,
                    facts) is None
