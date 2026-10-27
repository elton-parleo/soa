"""
2T-5 (Answers): the demo's Answers for a brand at retail, from the Oct 26
findings (org 12, Pampers, FL15-pampers-20261024, read after 2T-4: High 63,
Medium 30, Right 195, 306 not flagged).

  A1, A2  /answers/summary's `flagged` and `hero`: "<high> of <flagged>
          flagged · <high> answers give a wrong price, the wrong product, or
          leave <brand> out where it should be first", the clauses the kinds
          present; `worst_answer_id`
  A3      `chips`, one per flagged answer, by agent then severity
  A4      `kind` on every answer, the demo's four tabs
  A5      no flagged row reads "Not scored": a comparison answer with a rival
          first reads the coded ranking
  A5b     "could not find the product" is Medium
  A9      the evidence drawer's fields are served

Inputs, each named where it is used: the 2T-1 harness (2P-1's pair with
supply #33's answers RECORDED) and console_fixture_2t5's FL15 shape, DERIVED.
Nothing is read from production and no model is called.
"""
import pytest

from app.services import console_measure as measure
from app.services import console_read_models as rm
from soa_shared import severity as sev
from tests import console_fixture_2p1 as f2p1
from tests import console_fixture_2t5 as f2t5
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import _encode, http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_console_2t1_overview_truesync import _read, _shape

BRAND = f2t5.BRAND


def _fl15(db, http, upstream):
    _shape(db, http, upstream)
    return f2t5.comparison(db, _encode)


def _answers(http):
    return _read(http, 'answers', cycle=f2p1.CYCLE_2)


def _summary(http):
    return _read(http, 'answers/summary', cycle=f2p1.CYCLE_2)


# ── A4: the kind, the demo's tab ──────────────────────────────────────────

@pytest.mark.parametrize('tier,intent,kind', [
    ('brand_direct', 'attribute', rm.ACCURACY),
    ('brand_direct', 'where_to_buy', rm.VALUE),
    ('brand_direct', 'cheapest_place', rm.VALUE),
    ('catalog_accuracy', None, rm.VALUE),
    ('value_incentives', None, rm.VALUE),
    ('category_control', None, rm.CATEGORY),
    ('comparison', None, rm.CATEGORY),
    ('brand_direct', 'retired', rm.BRAND_DIRECT),
    ('brand_direct', None, rm.BRAND_DIRECT),
])
def test_each_tier_and_intent_has_the_demos_kind(tier, intent, kind):
    assert rm.answer_kind(tier, intent) == kind


def test_every_answer_carries_its_kind_and_keeps_its_tier(http, db, upstream):
    _fl15(db, http, upstream)
    answers = _answers(http)
    assert all(a['kind'] in rm.ANSWER_KINDS and a['tier'] for a in answers)
    assert {a['kind'] for a in answers} == set(rm.ANSWER_KINDS)
    assert {(a['tier'], a['kind']) for a in answers if a['tier'] == 'comparison'} == {('comparison', rm.CATEGORY)}


# ── A5: a flagged answer never reads "Not scored" ─────────────────────────

def test_a_comparison_answer_with_a_rival_first_reads_the_coded_ranking(http, db, upstream):
    _fl15(db, http, upstream)
    by_id = {a['id']: a for a in _answers(http)}
    for (q, platform), want in f2t5.SUMMARIES.items():
        a = by_id[f"run-{f2t5.run_id(q, platform)}"]
        if want.startswith('Another brand first') and a['severity'] != sev.HIGH:
            continue   # the answer that ranked no brand: not flagged (below)
        assert (a['severity'], a['severity_rule'], a['summary']) == (sev.HIGH, sev.BRAND_NOT_FIRST, want), a['id']


def test_no_flagged_answer_reads_not_scored(http, db, upstream):
    _fl15(db, http, upstream)
    answers = _answers(http)
    flagged = [a for a in answers if sev.is_flagged(a['severity'])]
    assert flagged and not [a['id'] for a in flagged if a['summary'] == 'Not scored']


def test_an_unanswered_or_unranked_comparison_is_not_left_out_where_first(http, db, upstream):
    """FL15's AI Mode returned nothing on the newborn comparison: no rival came first, so it is not High.
    Nor is an answer whose coding ranked no brand."""
    _fl15(db, http, upstream)
    by_id = {a['id']: a for a in _answers(http)}
    unanswered = by_id[f"run-{f2t5.run_id(0, 'aimode')}"]
    unranked = by_id[f"run-{f2t5.run_id(1, 'claude')}"]
    assert (unanswered['answer_status'], unanswered['severity']) == (None, sev.LOW)
    assert unranked['severity'] == sev.LOW
    # the brand first is not flagged
    assert by_id[f"run-{f2t5.run_id(0, 'perplexity')}"]['severity'] == sev.LOW


@pytest.mark.parametrize('mentions,line', [
    ([{'name': 'Huggies', 'position': 1}, {'name': 'Pampers', 'position': 2, 'role': 'primary'}],
     'Huggies first, Pampers second'),
    ([{'name': 'Huggies', 'position': 1}], 'Huggies first, Pampers not named'),
    ([{'name': 'Pampers', 'position': 3, 'role': 'primary'}, {'name': 'Kudos', 'position': 2}],
     'Another brand first, Pampers third'),
])
def test_the_ranking_line(mentions, line):
    assert rm.ranking_line(mentions, 'Pampers') == line


def test_a_flagged_answer_with_no_line_reads_its_rules_line():
    run = {'id': 9, 'platform': 'chatgpt', 'run_number': 1, 'answer_status': 'answered', 'raw_response': 'I could '
           'not find that product.'}
    query = {'tier': 'brand_direct', 'query_text': 'Is Pampers Pure Protection still sold?', 'source_ref': {}}
    outcome = {'outcome': 'acknowledged_unknown', 'outcome_reason': None, 'extraction': {}, 'flags': []}
    a = rm.build_answer(run, query, outcome, [], runs_per_query=1, cycle_code='c', ours='Pampers')
    assert (a['severity'], a['severity_rule'], a['summary']) == (sev.MEDIUM, sev.COULD_NOT_FIND,
                                                                 'said it could not find the product')


# ── A5b: could not find is Medium ─────────────────────────────────────────

def test_could_not_find_the_product_is_medium(http, db, upstream):
    _fl15(db, http, upstream)
    unknown = [a for a in _answers(http) if a.get('brand_verdict') == 'acknowledged_unknown']
    assert unknown and {(a['severity'], a['severity_rule']) for a in unknown} == {(sev.MEDIUM, sev.COULD_NOT_FIND)}


# ── A1, A2: flagged and the hero ──────────────────────────────────────────

def test_the_summarys_flagged_is_the_answers_lists(http, db, upstream):
    _fl15(db, http, upstream)
    answers, summary = _answers(http), _summary(http)
    tally = sev.tally(answers)
    assert summary['flagged'] == {'total': tally['flagged'], 'high': tally['high'], 'medium': tally['medium'],
                                  'right': tally['right'], 'of': len(answers)}
    assert summary['severity'] == tally


def test_the_hero_on_the_harness(http, db, upstream):
    _fl15(db, http, upstream)
    hero = _summary(http)['hero']
    high = sum(1 for a in _answers(http) if a['severity'] == sev.HIGH)
    assert hero['n'] == high and hero['sub'] == f"of {_summary(http)['flagged']['total']} flagged"
    assert hero['claim'] == (f"{high} answers give a wrong price, a wrong fact, or leave {BRAND} out where it should "
                             "be first")
    assert hero['text'] == f"{high} of {_summary(http)['flagged']['total']} flagged · {hero['claim']}"


def test_the_hero_on_fl15s_counts():
    """FL15's live counts after 2T-4 (High 63, Medium 30, Right 195, 306 not flagged), DERIVED as rows."""
    lead = measure.answers_lead(f2t5.fl15_answers(), 'Pampers')
    assert lead['flagged'] == {'total': 93, 'high': 63, 'medium': 30, 'right': 195, 'of': 594}
    assert lead['hero']['text'] == ('63 of 93 flagged · 63 answers give a wrong price, the wrong product, a wrong '
                                    'fact, or leave Pampers out where it should be first')


@pytest.mark.parametrize('rules,claim', [
    (['wrong_price'], '1 answer gives a wrong price'),
    (['wrong_price', 'brand_not_first'], '2 answers give a wrong price or leave Pampers out where it should be first'),
    (['brand_not_first'], '1 answer leaves Pampers out where it should be first'),
    (['successor_not_named', 'retired_called_current', 'wrong_price'],
     '3 answers give a wrong price or the wrong product'),
])
def test_the_clauses_are_the_kinds_present(rules, claim):
    answers = [{'id': f'r{i}', 'severity': sev.HIGH, 'severity_rule': r} for i, r in enumerate(rules)]
    assert measure.high_claim(answers, 'Pampers') == claim


def test_with_no_high_the_hero_reads_the_medium_answers():
    answers = [{'id': 'a', 'severity': sev.MEDIUM, 'severity_rule': sev.MISSED_DEAL},
               {'id': 'b', 'severity': sev.MEDIUM, 'severity_rule': sev.COULD_NOT_FIND},
               {'id': 'c', 'severity': sev.OK, 'severity_rule': sev.RIGHT}]
    hero = measure.answers_lead(answers, 'Pampers')['hero']
    assert (hero['n'], hero['sub']) == (2, 'of 2 flagged')
    assert hero['claim'] == '2 answers leave out a live deal or say they could not find the product'


def test_the_worst_answer(http, db, upstream):
    _fl15(db, http, upstream)
    answers, summary = _answers(http), _summary(http)
    worst = next(a for a in answers if a['id'] == summary['worst_answer_id'])
    assert (worst['severity'], worst['severity_rule']) == (sev.HIGH, sev.WRONG_PRICE)
    assert measure.worst_answer([{'id': 'x', 'severity': sev.LOW}]) is None


# ── A3: the chips ─────────────────────────────────────────────────────────

def test_one_chip_per_flagged_answer_by_agent_then_severity(http, db, upstream):
    _fl15(db, http, upstream)
    answers, chips = _answers(http), _summary(http)['chips']
    flagged = {a['id']: a for a in answers if sev.is_flagged(a['severity'])}
    assert [c['id'] for c in chips if c['id'] not in flagged] == [] and len(chips) == len(flagged)
    order = [(measure.AGENT_ORDER.index(c['agent']), sev.ORDER[c['severity']]) for c in chips]
    assert order == sorted(order)
    c = chips[0]
    assert set(c) == {'id', 'agent', 'kind', 'severity', 'rule', 'query', 'summary'}
    assert (c['kind'], c['severity'], c['rule']) == (flagged[c['id']]['kind'], flagged[c['id']]['severity'],
                                                     flagged[c['id']]['severity_rule'])


def test_kinds_count_each_tab(http, db, upstream):
    _fl15(db, http, upstream)
    answers, kinds = _answers(http), _summary(http)['kinds']
    for k in rm.ANSWER_KINDS:
        mine = [a for a in answers if a['kind'] == k]
        assert kinds[k] == {'answers': len(mine), 'flagged': sum(1 for a in mine if sev.is_flagged(a['severity']))}


# ── A9: the evidence drawer ───────────────────────────────────────────────

def test_the_evidence_drawer_fields_are_served():
    """The drawer shows the answer's words, marked wrong, left out or right, beside the live page: each
    answer's `paragraphs` (segments with `mark` ok | wrong | miss, the console's "left out", and `ann` the
    check it belongs to) and `checks` (claim, what the agent said, `live`, its basis, the verdict). Served
    since 2C and 2L-1, read here on a stored-shape answer (the harness stores no claim spans)."""
    text_ = 'Walmart has it at $24.97.\n\nAmazon lists it at $27.97.'
    run = {'id': 7, 'platform': 'chatgpt', 'run_number': 1, 'answer_status': 'answered', 'raw_response': text_}
    query = {'tier': 'catalog_accuracy', 'query_text': 'What does the Swaddlers Newborn 84 ct cost at Amazon?',
             'source_ref': {'variant_id': 'feed_sku:v0'}}
    outcome = {'outcome': 'wrong', 'outcome_reason': 'stated 24.97, the page said 27.97',
               'expected_answer': {'type': 'price', 'amount': '27.97', 'attributed_to': 'amazon.com'},
               'claim_results': [{'stated': '24.97', 'outcome': 'wrong', 'target': 'asked',
                                  'reference': {'price': '27.97', 'method': 'json_ld'}},
                                 {'stated': '27.97', 'outcome': 'exact', 'target': 'asked',
                                  'reference': {'price': '27.97', 'method': 'json_ld'}}],
               'extraction': {'spans': [{'id': 1, 'text': 'Walmart has it at $24.97.'},
                                        {'id': 2, 'text': 'Amazon lists it at $27.97.'}]}, 'flags': []}
    a = rm.build_answer(run, query, outcome, [], runs_per_query=1, cycle_code='c')
    marks = [(seg.get('mark'), seg.get('ann')) for p in a['paragraphs'] for seg in p if seg.get('mark')]
    assert marks == [('wrong', 1), ('ok', 2)] and len(a['paragraphs']) == 2
    assert [(c['verdict'], c['live']) for c in a['checks']] == [('wrong', '$27.97'), ('right', '$27.97')]
    assert all(c.get('live_basis') for c in a['checks'])   # where the live price came from
    assert {'claim', 'agent', 'live', 'verdict', 'tone'} <= set(a['checks'][0])
    assert (a['severity'], a['kind'], a['summary']) == (sev.HIGH, rm.VALUE, 'stated 24.97, the page said 27.97')
