"""
2L-3 (B1): the narrative writer's checks (soa_shared/narratives.py). A line
is shown only when every dollar amount, number, retailer, agent and brand in
it is in the facts, who quoted what agrees with the facts, the agent is
named, no banned word is in it, and it is at most 220 characters; and only
when both calls write one and both pass. No model is called.

2L-3a: the rules the FL13 dry run (Oct 22) asked for, on hand-written lines
and facts: a judgment only on a verdict that holds it, the agent first and
nobody addressed, a direction only the facts give, a brand-choice line in
one sentence, "no source" once, the retry on a null, the product shape.
"""
import filecmp
import json
import os

import pytest

from soa_shared import narratives as n

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
ANSWER = {'kind': 'answer', 'why': ['wrong_price'], 'agent': 'Gemini', 'brand': 'Pampers',
          'question': 'What does the Pampers Swaddlers NB 84 cost at walmart.com?',
          'agent_quoted': [{'price_quoted': '27.97', 'verdict': 'wrong', 'direction': "quoted above the retailer's price"}],
          'retailer_price_that_day': {'retailer': 'Walmart', 'price': '24.97', 'date': 'Oct 19'},
          'price_direction': "quoted above the retailer's price", 'verdict': 'wrong'}
PRODUCT = {'kind': 'product', 'product': 'Swaddlers NB 84', 'brand': 'Pampers', 'agents_asked': 6,
           'retailer_prices_that_day': [{'retailer': 'Amazon', 'price': '27.97', 'date': 'Oct 19'},
                                        {'retailer': 'Walmart', 'price': '24.97', 'date': 'Oct 19'}],
           'quotes': [{'agent': 'ChatGPT', 'retailer': 'Amazon', 'price': '24.97', 'verdict': 'wrong'},
                      {'agent': 'ChatGPT', 'retailer': 'Walmart', 'price': '24.97', 'verdict': 'right'},
                      {'agent': 'Gemini', 'retailer': 'Walmart', 'price': '27.97', 'verdict': 'wrong'},
                      {'agent': 'Google AI Mode', 'retailer': 'Walmart', 'price': '24.97', 'verdict': 'right'},
                      {'agent': 'Perplexity', 'retailer': 'Walmart', 'price': '27.97', 'verdict': 'wrong'}],
           'issue': '2 of 6 agents quoted Walmart above its price',
           'price_direction': "quoted above the retailer's price"}


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
    ('Gemini said $27.97. On Oct 19 the price was $24.97.', 'unpaired_amount:$24.97'),
    ('Gemini said $27.97 at Walmart, but Walmart charged $27.97.', 'who_said_what:Walmart charged $27.97'),
    ('Walmart charged $24.97 on Oct 19, less than the answer said.', 'not_agent_first'),
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
    assert n.check('ChatGPT quoted it. Amazon charged $24.97 on Oct 19.', PRODUCT).startswith('who_said_what:Amazon')
    assert n.check('Amazon charged $27.97 on Oct 19, while Walmart charged $24.97.', PRODUCT) == 'not_agent_first'


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


# ═══ 2L-3a: the rules from the FL13 dry run (lines quoted from it, facts hand-written) ═══

UNREAD = {'kind': 'answer', 'why': ['wrong_price'], 'agent': 'ChatGPT', 'brand': 'Pampers', 'verdict': 'wrong',
          'agent_quoted': [{'price_quoted': '27.99', 'verdict': 'wrong'}],
          'retailer_price_that_day': {'retailer': 'Target', 'note': 'could not be read', 'date': 'Oct 21'}}
FIRST_PICK = {'kind': 'answer', 'why': ['rival_first_pick'], 'agent': 'ChatGPT', 'brand': 'Pampers',
              'question': 'Pampers vs Huggies for a newborn, which is better?',
              'first pick': 'Huggies', 'named in order': ['Huggies', 'Pampers', 'The Honest Company']}
FABRICATED = {'kind': 'answer', 'why': ['brand_fabricated'], 'agent': 'Claude', 'brand': 'Pampers',
              'brand_verdict': 'fabricated',
              'answer_spans': ['Pampers is widely considered one of the best diaper brands for newborns']}


def _priced(direction, *quotes, verdict='wrong', reference='49.77'):
    return {'kind': 'answer', 'why': ['wrong_price'], 'agent': 'Claude', 'brand': 'Pampers', 'verdict': verdict,
            'agent_quoted': [{'price_quoted': q} for q in quotes],
            'retailer_price_that_day': {'retailer': 'Amazon', 'price': reference, 'date': 'Oct 21'},
            'price_direction': n.DIRECTION_WORDS[direction] if direction else None}


@pytest.mark.parametrize('line', [
    # run-14727
    "ChatGPT says Target has Pampers for $27.99. Target's price that day could not be read. The quoted price was wrong.",
    'ChatGPT said $27.99 at Target, which is incorrect. Target could not be read on Oct 21.',
    'ChatGPT said $27.99 at Target. That is not what Target charged on Oct 21.',
    'ChatGPT said $27.99 at Target, which does not match Target on Oct 21.',
])
def test_rule_1_no_judgment_on_an_unverifiable_reference(line):
    assert n.check(line, UNREAD).startswith('judgment_without_verdict:')


def test_rule_1_the_unverifiable_line_that_passes():
    assert n.check("ChatGPT quoted $27.99 at Target. Target's price could not be read on Oct 21.", UNREAD) is None


def test_rule_1_judgment_holds_on_wrong_and_stale_only():
    line = 'Claude quoted $42.30. Amazon charged $49.77 on Oct 21, so the quote was wrong.'
    assert n.check(line, _priced(n.BELOW, '42.30')) is None
    assert n.check(line, _priced(n.BELOW, '42.30', verdict='stale')) is None
    assert n.check(line, _priced(n.BELOW, '42.30', verdict='partial')) == 'judgment_without_verdict:wrong'


@pytest.mark.parametrize('line, reason', [
    # run-14677, 14680, 14685, 14834, 14678, 14817, 14854
    ("Pampers puts ChatGPT's first pick as Huggies.", 'narrator:Pampers puts'),
    ('Pampers shows ChatGPT first picked Huggies.', 'narrator:Pampers shows'),
    ("Pampers is second on ChatGPT's list.", 'not_agent_first'),
    ('ChatGPT said it. Pampers says it is fabricated.', 'narrator:Pampers says'),
    ('ChatGPT first picked Huggies for your Pampers diaper question.', 'banned:your'),
    ('ChatGPT first picked Huggies. The shopper was told Huggies.', 'banned:The shopper was'),
    ('ChatGPT first picked Huggies, so the shopper got Huggies.', 'banned:the shopper got'),
    ('ChatGPT, the assistant, first picked Huggies.', 'banned:assistant'),
    ('You would see ChatGPT pick Huggies.', 'banned:You'),
])
def test_rule_2_the_agent_is_the_subject(line, reason):
    assert n.check(line, FIRST_PICK) == reason


@pytest.mark.parametrize('line', [
    'ChatGPT first picked Huggies, then Pampers, on "Pampers vs Huggies for a newborn, which is better?".',
    "ChatGPT's first pick was Huggies, then Pampers, on “Pampers vs Huggies for a newborn, which is better?”.",
])
def test_rule_2_and_4_the_agent_first_in_one_sentence(line):
    assert n.check(line, FIRST_PICK) is None


def test_rule_2_possessive_with_a_curly_apostrophe_and_a_two_word_name():
    facts = {**FIRST_PICK, 'agent': 'Google AI Mode'}
    assert n.check('Google AI Mode’s first pick was Huggies, then Pampers.', facts) is None
    assert n.check('AI Mode first picked Huggies, then Pampers.', facts) == 'not_agent_first'


@pytest.mark.parametrize('line, facts, reason', [
    # run-14858: quotes on both sides of $49.77, "lower" has no direction to state
    ('Claude quotes $42.30, $54.99, and $38.81 at Amazon. Amazon charged $49.77 on Oct 21, lower than they suggest.',
     _priced(n.RANGE, '42.30', '54.99', '38.81'), 'direction_without_fact:lower'),
    # run-14539: a range that includes the price gets no judgment
    ('Claude says Amazon ranges $9.97 to $82.70. Amazon charged $49.77 on Oct 21, so the quoted $9.97 was wrong.',
     _priced(n.RANGE, '9.97', '82.70'), 'judgment_without_verdict:wrong'),
    # run-14815: per-diaper prices against a pack price
    ('Claude quotes $0.30 and $0.45 per diaper, but Amazon charged $44.99 on Oct 21. The price was wrong.',
     _priced(n.PER_UNIT, '0.30', '0.45', reference='44.99'), 'judgment_without_verdict:wrong'),
    ('Claude quotes $0.30 per diaper, cheaper than Amazon, which charged $44.99 on Oct 21.',
     _priced(n.PER_UNIT, '0.30', reference='44.99'), 'direction_without_fact:cheaper'),
    # run-14817's word, against the direction the facts give
    ('Claude quoted $54.99. Amazon charged $49.77 on Oct 21, so it underquoted.',
     _priced(n.ABOVE, '54.99'), 'direction_without_fact:underquoted'),
])
def test_rule_3_a_direction_only_from_the_facts(line, facts, reason):
    assert n.check(line, facts) == reason


@pytest.mark.parametrize('line, facts', [
    ('Claude quoted $42.30, below what Amazon charged. Amazon charged $49.77 on Oct 21.', _priced(n.BELOW, '42.30')),
    ('Claude quoted $42.30, so it underquoted Amazon. Amazon charged $49.77 on Oct 21.', _priced(n.BELOW, '42.30')),
    ('Claude quoted $54.99, higher than Amazon. Amazon charged $49.77 on Oct 21.', _priced(n.ABOVE, '54.99')),
    ('Claude quotes $42.30 and $54.99 at Amazon. Amazon charged $49.77 on Oct 21.', _priced(n.RANGE, '42.30', '54.99')),
])
def test_rule_3_the_direction_the_facts_give_passes(line, facts):
    assert n.check(line, facts) is None


def test_rule_3_direction_computed_in_the_input_builder():
    assert n._direction('42.30', '49.77', []) == n.BELOW
    assert n._direction('54.99', '49.77', []) == n.ABOVE
    assert n._direction('49.77', '49.77', []) == n.SAME
    assert n._direction('42.30', None, []) is None
    assert n._direction('0.30', '44.99', []) == n.PER_UNIT
    assert n._direction('2.10', '44.99', ['about $2.10 per diaper at Amazon']) == n.PER_UNIT
    assert n._direction('2.10', '44.99', ['$2.10/ct']) == n.PER_UNIT
    assert n._direction('27.97', '44.99', ['$27.97 per pack']) == n.BELOW
    assert n.overall_direction([n.BELOW, n.BELOW]) == n.BELOW
    assert n.overall_direction([n.BELOW, n.ABOVE, n.BELOW]) == n.RANGE      # run-14858
    assert n.overall_direction([n.BELOW, n.SAME]) == n.RANGE
    assert n.overall_direction([n.PER_UNIT, n.PER_UNIT]) == n.PER_UNIT      # run-14815
    assert n.overall_direction([n.PER_UNIT, n.BELOW]) == n.BELOW            # run-14554: the pack quote's
    assert n.overall_direction([None]) is None


@pytest.mark.parametrize('line', [
    # the restatements of 30-odd dry-run lines
    'ChatGPT first picked Huggies, then Pampers. Its first pick was another brand.',
    'ChatGPT first picked Huggies over Pampers. The first pick was a rival brand to Pampers.',
])
def test_rule_4_a_brand_choice_line_is_one_sentence(line):
    assert n.check(line, FIRST_PICK) == 'brand_choice_sentences:2'


def test_rule_4_price_lines_may_run_to_two():
    assert n.check('Gemini said $27.97. Walmart charged $24.97 on Oct 19.', ANSWER) is None


def test_rule_5_no_source_once():
    # run-14831
    twice = ('Claude says "Pampers is widely considered one of the best diaper brands for newborns" with no source. '
             'Pampers never published this and no source backs it.')
    assert n.check(twice, FABRICATED) == 'repeats:no source'
    once = ('Claude said "Pampers is widely considered one of the best diaper brands for newborns". '
            'Pampers never published it and no source backs it.')
    assert n.check(once, FABRICATED) is None


def test_product_rows_have_their_own_limit():
    line = ('Gemini and Perplexity quoted Walmart at $27.97. Walmart charged $24.97 on Oct 19. '
            '2 of 6 agents quoted Walmart above its price. ChatGPT quoted Amazon at $24.97 for the Swaddlers NB 84 '
            'pack, and Amazon charged $27.97 on Oct 19.')
    assert n.MAX_CHARS < len(line) <= n.MAX_CHARS_PRODUCT
    assert n.check(line, PRODUCT) is None
    assert n.check(line, {**ANSWER, 'kind': 'answer'}).startswith('too_long:')


def test_product_judgment_and_direction():
    line = 'Gemini and Perplexity quoted Walmart at $27.97, above its price. Walmart charged $24.97 on Oct 19.'
    assert n.check(line, PRODUCT) is None
    assert n.check(line, {**PRODUCT, 'price_direction': None}) == 'direction_without_fact:above'
    # a wrong quote comparable on its own holds a judgment; a per-unit one does not
    wrong = 'Gemini quoted Walmart at $27.97, a wrong price. Walmart charged $24.97 on Oct 19.'
    assert n.check(wrong, PRODUCT) is None
    per_unit = {**PRODUCT, 'quotes': [{**q, 'note': n.DIRECTION_WORDS[n.PER_UNIT]} for q in PRODUCT['quotes']]}
    assert n.check(wrong, per_unit) == 'judgment_without_verdict:wrong'


def test_a_line_break_inside_a_line_is_a_space():
    assert n.parse(json.dumps({'line': 'Gemini said $27.97.\nWalmart charged $24.97.'}))[0] == \
        'Gemini said $27.97. Walmart charged $24.97.'


# ═══ rule 7: one retry on a null ═══════════════════════════════════════════

def test_needs_retry_only_on_a_line_beside_a_null():
    line, null = json.dumps({'line': 'x'}), json.dumps({'line': None})
    assert n.needs_retry([line, null]) and n.needs_retry([null, line])
    assert not n.needs_retry([line, line]) and not n.needs_retry([null, null])
    assert not n.needs_retry(['not json', line])


def test_decide_with_a_retry():
    good = 'Gemini said $27.97. Walmart charged $24.97 on Oct 19.'
    other = 'Gemini quoted $27.97 for Pampers Swaddlers NB 84. Walmart charged $24.97.'
    d = n.decide(_answer(None, good, other), ANSWER)            # the retry stands in for the null
    assert (d['status'], d['line'], len(d['calls'])) == ('accepted', good, 3)
    d = n.decide(_answer(good, None, None), ANSWER)             # two nulls is null
    assert (d['status'], d['reason']) == ('null', 'no_line')
    d = n.decide(_answer(good, None, 'Gemini said $27.97. Walmart charged $25.00.'), ANSWER)
    assert (d['status'], d['reason']) == ('dropped', 'amount_not_in_facts:$25.00')
    d = n.decide(_answer('Gemini said $9.99.', None, good), ANSWER)   # the first line still has to pass
    assert (d['status'], d['reason']) == ('dropped', 'amount_not_in_facts:$9.99')


class _Responses:
    def __init__(self, lines):
        self.lines, self.calls = list(lines), 0

    def create(self, **kw):
        self.calls += 1
        body = json.dumps({'line': self.lines.pop(0)})
        return type('R', (), {'output_text': body, 'usage': None})()


def test_the_live_writer_retries_once_and_only_on_a_line_beside_a_null():
    good = 'Gemini said $27.97. Walmart charged $24.97 on Oct 19.'
    for lines, calls in (([good, good], 2), ([None, None], 2), ([good, None, good], 3), ([None, good, None], 3)):
        responses = _Responses(lines)
        client = type('C', (), {'responses': responses})()
        answer = n.LiveWriter(model='m', client=client)(ANSWER)
        assert (responses.calls, len(answer.raws)) == (calls, calls)


def test_a_quote_handed_on_is_refused():
    # the FL13 fixture's first product recording: Perplexity quoted $27.97 at Walmart, not $24.97
    line = 'ChatGPT quoted $24.97 at Amazon, and so did Perplexity. Amazon charged $27.97 on Oct 19.'
    assert n.check(line, PRODUCT) == 'who_said_what:borrowed:so did'
    assert n.check('Gemini and Perplexity quoted $27.97 at Walmart. Walmart charged $24.97 on Oct 19.', PRODUCT) is None
    assert n.check('Gemini and ChatGPT quoted $27.97 at Walmart. Walmart charged $24.97 on Oct 19.', PRODUCT) == \
        'who_said_what:ChatGPT $27.97'


def test_a_product_row_leads_with_its_issue():
    # the FL13 fixture's recording: true, but about the agents who got the price right
    right = 'Google AI Mode quoted $24.97 at Walmart. Walmart charged $24.97 on Oct 19.'
    assert n.check(right, PRODUCT) == 'off_issue'
    assert n.check('Gemini quoted $27.97 at Walmart. Walmart charged $24.97 on Oct 19.', PRODUCT) is None
    no_wrong = {**PRODUCT, 'quotes': [q for q in PRODUCT['quotes'] if q['verdict'] == 'right']}
    assert n.check(right, {**no_wrong, 'price_direction': None}) is None


def test_a_fabricated_claim_line_needs_the_claim_in_the_facts():
    line = 'Claude said something about Pampers. Pampers never published it and no source backs it.'
    assert n.check(line, {**FABRICATED, 'answer_spans': []}) == 'no_claim_in_facts'
