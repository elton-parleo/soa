"""
2P-1 (B3): a second cycle's narratives under the digest rule.

On the 2L-3 FL13-shaped fixture (tests/narratives_fixture.py), cycle 229's
lines written from the recordings, then 229 copied seven days on as cycle
230 (console_fixture_2p1.clone) and two of its flagged answers' facts
changed: the quotes on two wrong-price answers. Writing 230:

  every answer whose facts are unchanged keeps cycle 229's line, with no
  call ('carried:<cycle>'); every product row, and every price answer, is
  written again, their facts carrying the day of the new read (a line that
  kept "Oct 19" fails the checks: the number is not in the facts); the two
  changed answers are written again. Served on 230: the carried lines, the rewritten ones, and nothing
  for a subject whose line was not accepted.

No test calls a model: 229 replays the recordings, and 230's writer is a
stub that records what it is asked and answers from the lines below.
"""
import json

from sqlalchemy import text

from soa_shared import narratives as n
from tests import console_fixture_229 as f229
from tests import console_fixture_2j2 as f2j2
from tests import console_fixture_2p1 as f2p1
from tests import narratives_fixture as fx
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import _encode, http, upstream  # noqa: F401  (pytest fixtures)


class Stub:
    """The second cycle's writer: records each request; a line for the subjects in `lines`, null for the rest."""

    model = 'stub'

    def __init__(self, lines):
        self.lines, self.asked = lines, []

    def __call__(self, facts):
        self.asked.append(n.facts_digest(facts))
        line = self.lines.get(n.facts_digest(facts))
        raw = json.dumps({'line': line})
        return n.Answer(raws=(raw, raw), model=self.model)


def _stored(db, cycle_id):
    with db.connect() as c:
        return n.stored(c, cycle_id)


def _facts(db, cycle_id):
    with db.connect() as c:
        return n.load_cycle_facts(c, cycle_id)


def _requote(db, run_id, price):
    """The answer quoted another price: its claim and its extraction."""
    with db.begin() as c:
        claims, x = c.execute(text("SELECT claim_results, extraction FROM soa_expectation_outcomes WHERE run_id = :r"),
                              {'r': run_id}).one()
        claims = json.loads(claims) if isinstance(claims, str) else list(claims or [])
        x = json.loads(x) if isinstance(x, str) else dict(x or {})
        for claim in claims:
            claim['stated'] = price
        x['prices'] = [{'amount': price, 'currency': 'USD'}]
        c.execute(text("UPDATE soa_expectation_outcomes SET claim_results = :c, extraction = :x WHERE run_id = :r"),
                  {'c': _encode(claims), 'x': _encode(x), 'r': run_id})


def test_a_second_cycle_keeps_the_lines_whose_facts_did_not_change(db, monkeypatch):
    monkeypatch.setenv('SOA_NARRATIVES_ENABLED', '1')
    f2j2.load(db, _encode)
    fx.fl13_shapes(db)
    first = n.write_cycle(db, fx.CYCLE_ID, n.RecordedWriter(fx.FIXTURES), max_workers=1)
    accepted = {r['digest']: r['line'] for r in first if r['status'] == 'accepted'}
    assert accepted
    f2p1.clone(db, _encode)
    facts_1 = _facts(db, f2p1.ID_1)

    # two wrong-price answers whose quote is an accepted line's, quoted otherwise in cycle 2
    changed = []
    for subject, f in sorted(facts_1.items()):
        if subject.startswith('answer:') and 'wrong_price' in f.get('why', []) and n.facts_digest(f) in accepted \
                and f.get('agent_quoted'):
            changed.append(int(subject.split('-')[1]) + f2p1.RUN_OFFSET)
        if len(changed) == 2:
            break
    assert len(changed) == 2, 'the fixture has two accepted wrong-price lines with a quote'
    for run_id in changed:
        _requote(db, run_id, '19.99')
    facts_2 = _facts(db, f2p1.ID_2)
    changed_subjects = {f'answer:run-{r}' for r in changed}
    for s in changed_subjects:
        assert n.facts_digest(facts_2[s]) != n.facts_digest(facts_1[s.replace(str(int(s.split('-')[1])),
                                                                                 str(int(s.split('-')[1]) - f2p1.RUN_OFFSET))])
    # the rewritten lines: cycle 1's, with the new quote in place of the old one
    rewrites = {}
    for s in changed_subjects:
        old = facts_1[f"answer:run-{int(s.split('-')[1]) - f2p1.RUN_OFFSET}"]
        old_price = old['agent_quoted'][0]['price_quoted']
        rewrites[n.facts_digest(facts_2[s])] = accepted[n.facts_digest(old)].replace(f'${old_price}', '$19.99').replace('Oct 19', 'Oct 26')

    stub = Stub(rewrites)
    second = n.write_cycle(db, f2p1.ID_2, stub, max_workers=1)
    by = {r['subject']: r for r in second}
    carried = {s for s, r in by.items() if (r['reason'] or '').startswith('carried:')}
    # nothing carried was asked for, and nothing asked for was carried
    assert not carried & {s for s, f in facts_2.items() if n.facts_digest(f) in stub.asked}
    unchanged = {s for s, f in facts_2.items() if s.startswith('answer:') and s not in changed_subjects
                 and n.facts_digest(f) in accepted}
    assert carried == unchanged and unchanged
    print(f"\ncycle 2: {len(facts_2)} subjects, {len(carried)} carried, {len(stub.asked)} written")
    assert all(by[s]['reason'] == f'carried:{f229.CYCLE_229}' and by[s]['calls'] == [] for s in carried)
    # every product row is written again: its facts carry the new read's day
    products = {s for s in facts_2 if s.startswith('product:')}
    assert products and not products & carried
    assert all(any(p['date'] == 'Oct 26' for p in facts_2[s]['retailer_prices_that_day']) for s in products)
    # the two changed answers are rewritten, and pass the checks
    for s in changed_subjects:
        assert by[s]['status'] == 'accepted' and '$19.99' in by[s]['line'], by[s]
    # served on cycle 2: the carried lines word for word, the rewritten ones
    with db.connect() as c:
        served = n.served(c, f2p1.ID_2)
    assert {s: served.get(s) for s in carried} == {s: accepted[n.facts_digest(facts_2[s])] for s in carried}
    assert all(served[s] == by[s]['line'] for s in changed_subjects)
    # and a second write of cycle 2 has nothing left to do
    assert [r for r in n.write_cycle(db, f2p1.ID_2, Stub({}), max_workers=1) if r['status'] == 'accepted'] == []


# ═══ 2P-1 (B4): the new brand-claim verdicts, replayed ═══════════════════
#
# On the same fixture with FL14's claims (narratives_fixture.fl14_claims, 2O-5's verdicts, coder 6):
# Gemini's '2 to 9 lbs' for Swaddlers Newborn, which pampers.com's chart contradicts; Claude's '6 to 12
# lbs' for Swaddlers Size 1, which Pampers' record contradicts; Perplexity's "They are hypoallergenic."
# (unverified: no page states it, nothing contradicts it). Recorded with
# `scripts/record_narratives.py --cycle fl14`; replayed here.

GEMINI_LINE = 'Gemini said "2 to 9 lbs" for Swaddlers Newborn. pampers.com\'s chart says under 10 lb.'
CLAUDE_LINE = 'Claude said "6 to 12 lbs" for Swaddlers Size 1. Pampers\' record says "8 to 14 lb".'


def _fl14(db):
    f2j2.load(db, _encode)
    fx.fl13_shapes(db)
    fx.fl14_claims(db)


def test_a_contradicted_claim_s_facts_carry_the_contradiction(db):
    _fl14(db)
    facts = _facts(db, fx.CYCLE_ID)
    gemini = facts['answer:run-70302']
    assert gemini['contradicted'] == {'claimed': '2 to 9 lbs', 'for': 'Swaddlers Newborn',
                                      'source': "pampers.com's chart", 'says': 'under 10 lb'}
    assert gemini['meaning'] == ["The answer stated something about the brand that the brand's own pages or record "
                                 "state otherwise."]
    # the claim is contradicted, never "unpublished"; the scorer's dash sentence is not handed over as a note
    assert gemini['claim_facts'] == {'said': fx.NEWBORN, 'stated_otherwise': ['2 to 9 lbs']}
    assert 'scorer_note' not in gemini and 'never published' not in json.dumps(gemini)
    assert n.system_prompt(gemini) == n.CONTRADICTED_PROMPT
    assert facts['answer:run-70306']['contradicted']['source'] == "Pampers' record"
    # unverified: no narrative at all
    assert 'answer:run-70304' not in facts


def test_the_line_reads_the_contradiction(db, monkeypatch):
    monkeypatch.setenv('SOA_NARRATIVES_ENABLED', '1')
    _fl14(db)
    reports = {r['subject']: r for r in n.write_cycle(db, fx.CYCLE_ID, n.RecordedWriter(fx.FIXTURES), max_workers=1)}
    assert (reports['answer:run-70302']['status'], reports['answer:run-70302']['line']) == ('accepted', GEMINI_LINE)
    assert (reports['answer:run-70306']['status'], reports['answer:run-70306']['line']) == ('accepted', CLAUDE_LINE)
    gemini = _facts(db, fx.CYCLE_ID)['answer:run-70302']
    # the checks a contradicted line answers to
    assert n.check(GEMINI_LINE, gemini) is None
    assert n.check('Gemini said "2 to 9 lbs" for Swaddlers Newborn. Pampers never published it and no source backs '
                   'it.', gemini) == 'contradicted_never_published'
    assert n.check('Gemini said "2 to 9 lbs" for Swaddlers Newborn.', gemini) == 'contradiction_not_said'
    assert n.check('Gemini said "2 to 9 pounds" for Swaddlers Newborn. pampers.com\'s chart says under 10 lb.',
                   gemini) == 'quote_not_in_facts'


def test_the_drawer_lists_every_judged_sentence(http, db, upstream, monkeypatch):
    monkeypatch.setenv('SOA_NARRATIVES_ENABLED', '1')
    _fl14(db)
    n.write_cycle(db, fx.CYCLE_ID, n.RecordedWriter(fx.FIXTURES), max_workers=1)
    from tests.test_console_read_models import as_
    as_('op')
    answers = {a['id']: a for a in http.get('/api/console/answers', params={'cycle': f229.CYCLE_229, 'org': 10}).json()}
    gemini = answers['run-70302']
    assert (gemini['brand_verdict'], gemini['narrative']) == ('fabricated', GEMINI_LINE)
    assert gemini['summary'] == "fabricated: '2 to 9 lbs' for Swaddlers Newborn — pampers.com's chart says under 10 lb"
    sentences = gemini['brand_claim']['sentences']
    assert [(s['text'], s['verdict'], s['decided'], s['evidence']) for s in sentences] == [
        (fx.SIZES, 'grounded', False, []),
        (fx.NEWBORN, 'fabricated', True, ["pampers.com's chart says under 10 lb"]),
        (fx.SOFT, 'unverified', False, [])]
    assert [f['text'] for f in sentences[0]['facts_found']] == ['Newborn']
    assert [f['text'] for f in sentences[2]['facts_unverified']] == ['softer']
    claude = answers['run-70306']
    assert claude['brand_claim']['sentences'][0]['evidence'] == ["Pampers' record says 8 to 14 lb"]
    # unverified: no narrative; the template is the scorer's note
    hypo = answers['run-70304']
    assert (hypo['brand_verdict'], hypo['narrative']) == ('unverified', None)
    assert hypo['summary'] == f"'{fx.HYPO}' — not on the pages read; nothing contradicts it"
    assert [s['verdict'] for s in hypo['brand_claim']['sentences']] == ['unverified']
