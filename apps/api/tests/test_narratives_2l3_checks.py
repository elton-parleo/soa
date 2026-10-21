"""
2L-3 (B1): the narrative writer's checks (soa_shared/narratives.py). A line
is shown only when every dollar amount, number, retailer, agent and brand in
it is in the facts, who quoted what agrees with the facts, the agent is
named, no banned word is in it, and it is at most 220 characters; and only
when both calls write one and both pass. No model is called.
"""
import filecmp
import json
import os

import pytest

from soa_shared import narratives as n

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
ANSWER = {'kind': 'answer', 'why': ['wrong_price'], 'agent': 'Gemini', 'brand': 'Pampers',
          'question': 'What does the Pampers Swaddlers NB 84 cost at walmart.com?',
          'agent_quoted': [{'price_quoted': '27.97', 'verdict': 'wrong'}],
          'retailer_price_that_day': {'retailer': 'Walmart', 'price': '24.97', 'date': 'Oct 19'}}
PRODUCT = {'kind': 'product', 'product': 'Swaddlers NB 84', 'brand': 'Pampers',
           'retailer_prices_that_day': {'Walmart': {'price': '24.97', 'date': 'Oct 19'},
                                        'Amazon': {'price': '27.97', 'date': 'Oct 19'}},
           'wrong_quotes': [{'retailer': 'Amazon', 'quoted': '24.97', 'agents': ['ChatGPT'], 'retailer_charged': '27.97'},
                            {'retailer': 'Walmart', 'quoted': '27.97', 'agents': ['Gemini', 'Perplexity'],
                             'retailer_charged': '24.97'}],
           'right_quotes': [{'retailer': 'Walmart', 'quoted': '24.97', 'agents': ['ChatGPT', 'Google AI Mode']}]}


# ═══ the checks ═══════════════════════════════════════════════════════════

@pytest.mark.parametrize('line', [
    'Gemini said $27.97 for Pampers Swaddlers NB 84 at Walmart. Walmart charged $24.97 on Oct 19.',
    'Gemini quoted $27.97 when Walmart charged $24.97 on Oct 19.',
])
def test_a_true_line_passes(line):
    assert n.check(line, ANSWER) is None


@pytest.mark.parametrize('line, reason', [
    ('Gemini said $27.97. Walmart charged $24.99 on Oct 19.', 'amount_not_in_facts:$24.99'),
    ('Gemini said $27.97, $3.00 more than Walmart charged.', 'amount_not_in_facts:$3.00'),
    ('Gemini said $27.97 for 3 packs. Walmart charged $24.97.', 'number_not_in_facts:3'),
    ('Gemini said $27.97 at Target. Walmart charged $24.97.', 'name_not_in_facts:target'),
    ('Gemini said $27.97. Walmart charged $24.97, Huggies charged less.', 'name_not_in_facts:Huggies'),
    ('Gemini said $27.97. Walmart charged $24.97, Perplexity agreed.', 'name_not_in_facts:perplexity'),
    ('Walmart charged $27.97 on Oct 19. Gemini said $24.97.', 'unpaired_amount:$27.97'),
    ('Gemini said $27.97 at Walmart, but Walmart charged $27.97.', 'who_said_what:Walmart charged $27.97'),
    ('Walmart charged $24.97 on Oct 19, less than the answer said.', 'agent_not_named:Gemini'),
    ('Gemini said $27.97; Walmart charged $24.97.', 'banned:;'),
    ('Gemini said $27.97 — Walmart charged $24.97.', 'banned:—'),
    ('The AI said $27.97. Walmart charged $24.97 and Gemini was wrong.', 'banned:AI'),
    ('Gemini, a language model, said $27.97. Walmart charged $24.97.', 'banned:model'),
    ('Gemini said $27.97 for the merchant. Walmart charged $24.97.', 'banned:merchant'),
    ('Gemini said $27.97. The facts say Walmart charged $24.97.', 'banned:facts'),
    ('Gemini said $27.97 per retailer_price_that_day. Walmart charged $24.97.', 'banned:_'),
    ('Gemini said $27.97, a seamless miss. Walmart charged $24.97.', 'banned:seamless'),
    ('Gemini said $27.97. Walmart charged $24.97. ' + 'Pampers ' * 30, None),
])
def test_a_line_that_fails_says_why(line, reason):
    got = n.check(line, ANSWER)
    if reason is None:
        assert got.startswith('too_long:')
    else:
        assert got == reason


def test_google_ai_mode_is_a_name_not_a_banned_word():
    facts = {**ANSWER, 'agent': 'Google AI Mode'}
    assert n.check('Google AI Mode said $27.97. Walmart charged $24.97 on Oct 19.', facts) is None


def test_who_said_what_on_a_product():
    ok = ('ChatGPT quoted Amazon at $24.97 but Amazon charged $27.97. Gemini and Perplexity quoted Walmart at $27.97 '
          'but Walmart charged $24.97.')
    assert n.check(ok, PRODUCT) is None
    # the FL13 fixture's first recording: right numbers, wrong agent at the wrong retailer
    swapped = ('ChatGPT quoted Amazon at $24.97 and Walmart at $27.97, but Amazon charged $27.97. '
               'Gemini and Perplexity quoted Walmart at $27.97.')
    assert n.check(swapped, PRODUCT) == 'who_said_what:ChatGPT $27.97 at Walmart'
    assert n.check('Google AI Mode quoted Amazon at $24.97, but Amazon charged $27.97.', PRODUCT) == \
        'who_said_what:Google AI Mode $24.97 at Amazon'
    assert n.check('Amazon charged $24.97 on Oct 19. ChatGPT quoted it.', PRODUCT).startswith('who_said_what:Amazon')
    assert n.check('Amazon charged $27.97 on Oct 19, while Walmart charged $24.97.', PRODUCT) == 'agent_not_named'


def _answer(*lines):
    return n.Answer(raws=tuple(json.dumps({'line': x}) for x in lines), model='m')


def test_decide_takes_a_line_only_when_both_calls_pass():
    good = 'Gemini said $27.97. Walmart charged $24.97 on Oct 19.'
    other = 'Gemini quoted $27.97 for Pampers Swaddlers NB 84. Walmart charged $24.97.'
    d = n.decide(_answer(good, other), ANSWER)
    assert (d['status'], d['line']) == ('accepted', good)        # the first is kept
    d = n.decide(_answer(good, 'Gemini said $27.97. Walmart charged $25.00.'), ANSWER)
    assert (d['status'], d['line'], d['reason']) == ('dropped', None, 'amount_not_in_facts:$25.00')
    d = n.decide(_answer(None, None), ANSWER)
    assert (d['status'], d['line']) == ('null', None)
    d = n.decide(_answer(good, None), ANSWER)
    assert (d['status'], d['reason']) == ('dropped', 'calls_disagree:null')
    d = n.decide(n.Answer(raws=('not json', json.dumps({'line': good})), model='m'), ANSWER)
    assert (d['status'], d['reason']) == ('dropped', 'malformed')


def test_every_copy_of_the_module_is_identical():
    copies = [os.path.join(ROOT, d, 'narratives.py') for d in ('apps/api/soa_shared', 'apps/pipeline/soa_shared')]
    assert filecmp.cmp(*copies, shallow=False)


def test_the_flag_and_the_model_default():
    assert not n.enabled() or os.environ.get(n.FLAG) == '1'
    from soa_shared import config
    os.environ.pop(n.MODEL_ENV, None)
    assert n.model_name() == config.SOA_CODING_MODEL
