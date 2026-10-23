"""2O-1 (H27): builds tests/fixtures/brand_coder/fl14_shaped.json, the
FL14-shaped fixture for the two-call brand-claim coder. No model call, and
nothing read from production.

FL14-pampers-20261023's brand-direct tier is 258 answers. Its rescore of
Oct 23 (the printout Elton attached, fl14-rescore.txt) changed no rule for
the tier and moved 55 of them. Each answer here is the calls the coder would
have made, as categories:

  call 1  the outcome stored before the rescore (the printout's "before")
  call 2  the outcome after it ("after"), for the 55 moved answers; the
          same category as call 1 for the 203 that did not move
  call 3  only for the 55, which disagree. NOT RECORDED: the printout has
          two calls per answer, not three, so the deciding call is written
          here to reach every branch, in the printout's order: the first of
          every three agrees with call 1, the second with call 2, the third
          with neither (a category of its own). The counts it gives are a
          test of the rule, not a prediction of FL14's.

The 203 unmoved answers are placed so the before counts are the printout's:
absent 6, acknowledged_unknown 7, echoed 47, fabricated 123, grounded 72,
unscoreable 3. Replace with an export of FL14's stored outcomes (two calls
each) to make it a recording.

    cd apps/pipeline && python3 tests/fixtures/build_brand_coder_fl14_2o1.py
"""
import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'brand_coder', 'fl14_shaped.json')

BEFORE = {'absent': 6, 'acknowledged_unknown': 7, 'echoed': 47, 'fabricated': 123, 'grounded': 72,
          'unscoreable': 3}
AFTER = {'absent': 6, 'acknowledged_unknown': 10, 'echoed': 59, 'fabricated': 106, 'grounded': 71,
         'misattributed': 4, 'unscoreable': 2}

#: the printout's brand-direct moves, verbatim: (query_code, platform, before, after, run_id)
MOVES = [
    ('PAM_210', 'perplexity', 'fabricated', 'acknowledged_unknown', 14959),
    ('PAM_209', 'perplexity', 'fabricated', 'grounded', 14962),
    ('PAM_216', 'perplexity', 'fabricated', 'grounded', 14975),
    ('PAM_219', 'perplexity', 'grounded', 'fabricated', 14980),
    ('PAM_217', 'perplexity', 'fabricated', 'echoed', 14982),
    ('PAM_225', 'perplexity', 'echoed', 'fabricated', 14992),
    ('PAM_230', 'perplexity', 'fabricated', 'echoed', 15008),
    ('PAM_240', 'perplexity', 'fabricated', 'echoed', 15021),
    ('PAM_241', 'perplexity', 'fabricated', 'echoed', 15023),
    ('PAM_242', 'perplexity', 'fabricated', 'grounded', 15024),
    ('PAM_239', 'perplexity', 'grounded', 'echoed', 15025),
    ('PAM_245', 'perplexity', 'grounded', 'fabricated', 15033),
    ('PAM_248', 'perplexity', 'fabricated', 'grounded', 15035),
    ('PAM_213', 'gemini_grounded', 'echoed', 'fabricated', 15051),
    ('PAM_221', 'gemini_grounded', 'fabricated', 'echoed', 15078),
    ('PAM_230', 'gemini_grounded', 'fabricated', 'echoed', 15111),
    ('PAM_243', 'gemini_grounded', 'grounded', 'echoed', 15126),
    ('PAM_248', 'gemini_grounded', 'grounded', 'echoed', 15133),
    ('PAM_246', 'gemini_grounded', 'echoed', 'grounded', 15138),
    ('PAM_223', 'aimode', 'fabricated', 'misattributed', 15202),
    ('PAM_231', 'aimode', 'fabricated', 'echoed', 15221),
    ('PAM_232', 'aimode', 'fabricated', 'echoed', 15232),
    ('PAM_208', 'copilot', 'fabricated', 'grounded', 15237),
    ('PAM_234', 'aimode', 'acknowledged_unknown', 'echoed', 15238),
    ('PAM_209', 'copilot', 'grounded', 'fabricated', 15241),
    ('PAM_219', 'chatgpt', 'grounded', 'misattributed', 15244),
    ('PAM_210', 'copilot', 'fabricated', 'acknowledged_unknown', 15245),
    ('PAM_237', 'aimode', 'echoed', 'fabricated', 15249),
    ('PAM_236', 'aimode', 'echoed', 'fabricated', 15250),
    ('PAM_214', 'copilot', 'grounded', 'acknowledged_unknown', 15260),
    ('PAM_228', 'chatgpt', 'echoed', 'grounded', 15265),
    ('PAM_215', 'copilot', 'fabricated', 'grounded', 15266),
    ('PAM_216', 'copilot', 'grounded', 'acknowledged_unknown', 15268),
    ('PAM_246', 'aimode', 'fabricated', 'grounded', 15274),
    ('PAM_232', 'chatgpt', 'grounded', 'echoed', 15281),
    ('PAM_221', 'copilot', 'grounded', 'acknowledged_unknown', 15287),
    ('PAM_225', 'copilot', 'fabricated', 'acknowledged_unknown', 15303),
    ('PAM_235', 'chatgpt', 'acknowledged_unknown', 'misattributed', 15306),
    ('PAM_227', 'copilot', 'fabricated', 'echoed', 15309),
    ('PAM_228', 'copilot', 'fabricated', 'grounded', 15310),
    ('PAM_238', 'chatgpt', 'acknowledged_unknown', 'grounded', 15315),
    ('PAM_245', 'chatgpt', 'echoed', 'grounded', 15332),
    ('PAM_233', 'copilot', 'grounded', 'acknowledged_unknown', 15334),
    ('PAM_234', 'copilot', 'acknowledged_unknown', 'grounded', 15341),
    ('PAM_235', 'copilot', 'fabricated', 'grounded', 15342),
    ('PAM_236', 'copilot', 'fabricated', 'grounded', 15350),
    ('PAM_239', 'copilot', 'grounded', 'acknowledged_unknown', 15359),
    ('PAM_241', 'copilot', 'fabricated', 'echoed', 15364),
    ('PAM_242', 'copilot', 'grounded', 'fabricated', 15368),
    ('PAM_245', 'copilot', 'grounded', 'echoed', 15377),
    ('PAM_246', 'copilot', 'grounded', 'echoed', 15384),
    ('PAM_211', 'claude', 'fabricated', 'echoed', 15410),
    ('PAM_212', 'claude', 'unscoreable', 'fabricated', 15414),
    ('PAM_216', 'claude', 'acknowledged_unknown', 'echoed', 15425),
    ('PAM_232', 'claude', 'fabricated', 'misattributed', 15443),
]

#: a category neither call 1 nor call 2 wrote, for a third call that settles nothing
_OTHER = ['echoed', 'grounded', 'fabricated', 'acknowledged_unknown', 'misattributed', 'absent']


def third(i: int, first: str, second: str) -> str:
    if i % 3 == 0:
        return first
    if i % 3 == 1:
        return second
    return next(c for c in _OTHER if c not in (first, second))


def build() -> dict:
    moved_from = Counter(m[2] for m in MOVES)
    answers = []
    for i, (code, platform, was, now, run_id) in enumerate(MOVES):
        answers.append({'run_id': run_id, 'query_code': code, 'platform': platform,
                        'calls': [was, now, third(i, was, now)]})
    for category in sorted(BEFORE):
        for _ in range(BEFORE[category] - moved_from[category]):
            answers.append({'run_id': None, 'calls': [category, category]})
    assert len(answers) == 258
    assert Counter(a['calls'][0] for a in answers) == Counter(BEFORE)
    assert Counter(a['calls'][1] for a in answers) == Counter(AFTER)
    return {
        '_note': ("FL14-SHAPED, NOT RECORDED. Built by tests/fixtures/build_brand_coder_fl14_2o1.py from "
                  "the FL14 rescore printout of Oct 23 (258 brand-direct answers, 55 moved). Calls 1 and 2 are "
                  "the printout's before and after; call 3, for the 55, is written to reach every branch of the "
                  "rule (see the builder). Nothing was read from production."),
        'cycle_code': 'FL14-pampers-20261023',
        'before': BEFORE,
        'after_one_call_rescore': AFTER,
        'answers': answers,
    }


if __name__ == '__main__':
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as fh:
        json.dump(build(), fh, indent=1)
        fh.write('\n')
    print(f"wrote {OUT}")
