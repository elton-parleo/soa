"""
2P-2: a brand-claim narrative is written about the contradicted sentence only.

FL14's --narratives run after 2P-1 accepted 13 lines about a grounded sentence beside the one the scorer flagged,
joined with a "but" that contradicts nothing (run-15090: "Gemini said Target is a place to buy Pampers Baby-Dry but
Pampers' record includes target.com"). On the 2L-3 fixture with 2P-1's FL14 claims and the shapes of
narratives_fixture.fl14_beside():

  70331  a contradicted sentence with a grounded one beside it, both labelled: the facts carry the contradicted one
  70332  a grounded answer flagged for a store off the brand's list: no subject
  70334  an unverified answer with the same flag: no subject

No test calls a model, and no new subject is recorded: the checks are run on lines written here. The two 2P-1
subjects' facts are unchanged, so test_narratives_2p1 replays their recordings under the new checks.
"""
import json

import pytest

from soa_shared import narratives as n
from tests import console_fixture_2j2 as f2j2
from tests import narratives_fixture as fx
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import _encode
from tests.test_narratives_2p1 import CLAUDE_LINE, GEMINI_LINE

SAYS = "pampers.com's size list says Newborn to Size 7"

#: FL14's accepted lines the run named (fl14-narratives-3.txt), verbatim
FL14_LINES = {
    14982: 'Perplexity said "BJ’s Wholesale Club - listed for online shipping, with sizes Newborn through 8" '
           'but Pampers sizes Newborn through 8.',
    14991: 'Perplexity said "Amazon" has multiple sizes and pack counts available but the Pampers record lists '
           '"amazon.com".',
    15078: 'Gemini said "* **Target** (also offers a 164ct option)" but Pampers\' record/pages list "164ct" and '
           '"target.com".',
    15090: "Gemini said Target is a place to buy Pampers Baby-Dry but Pampers' record includes target.com.",
    15095: 'Gemini said "Target" as a place to buy Pampers Cruisers 360, Size 5, 128 ct, and Pampers\' record or '
           'pages list "target.com".',
    15220: 'Google AI Mode said "are widely available both online and in major retail stores." Pampers\' record '
           'pages list "Swaddlers Overnights".',
    15239: 'ChatGPT said “Costco” has Pampers Swaddlers Ultra listings, including “Sizes 1-2” and '
           '“Sizes 3-7”. Pampers’ record or pages list “Sizes 1-2” and “Sizes 3-7”.',
    15247: 'ChatGPT said “Pampers Official Store” includes “Pure Protection” and “Swaddlers '
           'Pure Protection” options. Pampers’ pages show “Swaddlers” only.',
    15299: 'ChatGPT says “Cheapest I found: Sam’s Club” for Pampers Swaddlers Ultra Day + Night but '
           'Pampers\' record or pages list “Size 5”.',
    15428: 'Claude said "Pampers Swaddlers Ultra Day + Night are also available on eBay" but Pampers\' record or '
           'pages list "Size 1".',
    15432: 'Claude said "**Walmart** -". Pampers\' record or pages list "walmart.com".',
    15437: 'Claude said "You can read reviews and buy Pampers Baby-Dry Diapers at Target." Target.com is on '
           'Pampers\' record or pages.',
    15439: "Claude said Pampers Cruisers 360, Size 5, 128 ct are sold on Amazon and Kroger. but Pampers' record "
           "cites amazon.com.",
}


def _facts(db):
    f2j2.load(db, _encode)
    fx.fl13_shapes(db)
    fx.fl14_claims(db)
    fx.fl14_beside(db)
    with db.connect() as c:
        return n.load_cycle_facts(c, fx.CYCLE_ID)


def test_the_facts_carry_the_contradicted_sentence_only(db):
    facts = _facts(db)
    beside = facts['answer:run-70331']
    # the grounded sentence beside it, and what it found, are not handed over
    assert beside['answer_spans'] == [fx.BABY_DRY_SIZES]
    assert beside['claim_facts'] == {'said': fx.BABY_DRY_SIZES, 'stated_otherwise': ['Newborn through Size 8']}
    assert beside['contradicted'] == {'claimed': 'Newborn through Size 8', 'for': 'Baby-Dry',
                                      'source': "pampers.com's size list", 'says': 'Newborn to Size 7'}
    assert fx.TARGET not in json.dumps(beside) and 'target.com' not in json.dumps(beside)
    assert 'scorer_note' not in beside and n.system_prompt(beside) == n.CONTRADICTED_PROMPT
    # flagged for a store, its sentences grounded or unverified: nothing to write about
    assert 'answer:run-70332' not in facts and 'answer:run-70334' not in facts
    assert 'answer:run-70304' not in facts


@pytest.mark.parametrize('line, failure', [
    # 2P-1 B4's pattern
    (f'ChatGPT said "Newborn through Size 8" for Baby-Dry. {SAYS}.', None),
    (f'ChatGPT said "Newborn through Size 8" for Baby-Dry but {SAYS}.', None),
    # FL14's: the grounded sentence beside it, quoted
    (f'ChatGPT said "{fx.TARGET}" {SAYS}.', 'quote_not_in_facts'),
    # the contradicted sentence quoted whole, not its value
    (f'ChatGPT said "{fx.BABY_DRY_SIZES}" {SAYS}.', 'claim_not_contradicted'),
    # the contradicted value never stated
    (f'ChatGPT said Baby-Dry is at Target. {SAYS}.', 'claim_not_contradicted'),
    # a "but" with no brand value after it
    (f'ChatGPT said "Newborn through Size 8" for Baby-Dry. {SAYS}, but Baby-Dry is sold at Target.',
     'but_without_brand_value'),
])
def test_a_brand_claim_line_is_about_the_contradicted_value(db, line, failure):
    assert n.check(line, _facts(db)['answer:run-70331']) == failure


def test_fl14_s_lines_fail_on_a_contradicted_claim(db):
    """Each of FL14's 13 lines, by its own agent, on a contradicted claim's facts: none is accepted."""
    beside = _facts(db)['answer:run-70331']
    for run, line in FL14_LINES.items():
        agent = next(a for a in n.AGENT_WORDS if line.startswith(a))
        assert n.check(line, {**beside, 'agent': agent}) is not None, run


def test_the_recorded_lines_pass_the_new_check(db):
    facts = _facts(db)
    assert n.contradicted_check(GEMINI_LINE, facts['answer:run-70302']) is None
    assert n.contradicted_check(CLAUDE_LINE, facts['answer:run-70306']) is None
