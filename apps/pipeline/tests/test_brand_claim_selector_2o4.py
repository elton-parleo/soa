"""
2O-4: brand-direct claims are selected by rule, not by the model.

Two consecutive re-scores of FL14 under scorer 13 moved 51 of 258 brand-
direct answers (fl14-v13-run1.txt, fl14-v13-run2.txt): the verdict was a
lookup, and the sentences it looked up were the model's pick, which changed
between runs. Now the sentences are chosen from the answer text by rule
(scoring/brand_claim_selector.py) and the tier makes no model call.

  * the segmenter: "…Target and CVS. Pampers…" splits, "vs." does not;
  * the vocabulary: the line names a title gives, a line written alone;
  * the selector on the FL13-shaped answers (fixtures/brand_claim/
    fl13_brand_direct_answers.json): the claim sentences hand-counted for
    ten of them, before the selector was run;
  * no model call, through the scorer;
  * two runs give identical outcomes: the FL13-shaped answers through the
    scorer on sqlite, and FL14-shaped fixture's 258 in memory;
  * the FL14-shaped fixture's verdict split;
  * the printout: rescore_cycle --tier brand_direct end to end on sqlite,
    twice (the second moves nothing) and as a dry run (the same lines).

NOTHING HERE IS RECORDED: the answers are hand-written (the fixture says
how), and there is no model call to record.
"""
import asyncio
import json
import os
from collections import Counter
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from parser import span_segmenter
from scoring import brand_claim_selector as sel
from scoring import brand_fact_index as bfi
from scoring import expectation_scorer as scorer_module
from scripts import rescore_cycle
from soa_shared import expected_answers as ea
from tests.test_expectation_scorer import FakeFacts, db, outcomes  # noqa: F401  (db is a fixture)

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, 'fixtures', 'brand_claim')
FL13 = json.load(open(os.path.join(FIXTURES, 'fl13_record_pages.json')))
ANSWERS = json.load(open(os.path.join(FIXTURES, 'fl13_brand_direct_answers.json')))
FL14 = json.load(open(os.path.join(FIXTURES, 'fl14_shaped_runs.json')))
EXPECTATION = ea.brand_mention('Pampers', 'pampers.com')
OWN = ['pampers.com']
STUDY = {'terms': ['Pampers'], 'product_names': [], 'rivals': ANSWERS['rivals']}
HAND = [a for a in ANSWERS['answers'] if a.get('hand')]
#: 2O-5: the hand counts' outcomes under "fabricated means contradicted". Each
#: was fabricated for a fact the index did not hold, and nothing contradicts:
#: 3 Target off the retailer list (Walmart and Amazon on it), 6 a 120 count
#: box (the stretchy waistband on the page), 7 "#1 pediatrician recommended"
#: (Swaddlers and Cruisers named), 8 Size 7 (Newborn to 6 on the chart). The
#: sentences counted are unchanged.
HAND_2O5 = {3: 'grounded', 6: 'grounded', 7: 'grounded', 8: 'grounded'}


def vocab():
    return sel.vocabulary('Pampers', facts=FL13['facts'], study=STUDY)


def index():
    return bfi.build(json.loads(json.dumps(FL13['facts'])), json.loads(json.dumps(FL13['reference'])))


def judge(answer, question):
    record = sel.select(answer, question=question, vocab=vocab(), own_domains=OWN)
    return record, sel.decide(record, EXPECTATION, index=index(), own_domains=OWN)


# ── the segmenter ─────────────────────────────────────────────────────────

def test_a_store_whose_name_ends_like_an_abbreviation_ends_its_sentence():
    spans = span_segmenter.segment("You can buy them at Target and CVS. Pampers Swaddlers cost $24.97.")
    assert [s['text'] for s in spans] == ['You can buy them at Target and CVS.', 'Pampers Swaddlers cost $24.97.']


@pytest.mark.parametrize('text', [
    'Pampers vs. Huggies is a close call on price.',
    'Pampers is the No. 1 brand hospitals use.',
    'Some lines, e.g. Swaddlers, have a wetness indicator.',
    'Ask Dr. Brown about sizing.',
])
def test_an_abbreviation_does_not_end_a_sentence(text):
    assert [s['text'] for s in span_segmenter.segment(text)] == [text]


def test_a_unit_carries_its_sentence_and_its_lists_lead_in():
    units = span_segmenter.units("Pampers Swaddlers are soft, but they cost $45.\n**Pampers Pure:**\n- Fragrance free")
    assert [u['text'] for u in units] == ['Pampers Swaddlers are soft,', 'but they cost $45.', '**Pampers Pure:**',
                                          '- Fragrance free']
    assert units[1]['sentence'] == 'Pampers Swaddlers are soft, but they cost $45.'
    assert (units[3]['item'], units[3]['lead_in']) == (True, '**Pampers Pure:**')
    assert [u['text'] for u in units] == [s['text'] for s in span_segmenter.segment(
        "Pampers Swaddlers are soft, but they cost $45.\n**Pampers Pure:**\n- Fragrance free")]


# ── the vocabulary ────────────────────────────────────────────────────────

@pytest.mark.parametrize('title,line', [
    ('Pampers Swaddlers Diapers Size 1, 96 Count', 'Swaddlers'),
    ('Pampers Swaddlers NB 84', 'Swaddlers'),
    ('Pampers Baby Dry S3 136', 'Baby Dry'),
    ('Pampers Cruisers 360 S4 104', 'Cruisers 360'),
    ('Pampers Pure Protection Diapers Size 2, 74 Count', 'Pure Protection'),
    ('Pampers® Easy Ups™ Training Underwear', 'Easy Ups Training Underwear'),
    ('Pampers Diapers Size 3', None),
])
def test_the_line_a_title_names(title, line):
    assert sel.line_name(title, 'Pampers') == line


def test_the_fl13_vocabulary():
    v = vocab()
    assert v.lines == ['Swaddlers', 'Baby Dry', 'Cruisers 360', 'Easy Ups', 'Ultra', 'Pure', 'AMORE', 'Cruisers']
    assert v.rivals == ['Huggies', 'Luvs'] and v.terms == ['Pampers']
    # a line written alone: capitalised, and a one-word line not as the sentence's first word
    assert v.names_brand('Parents like Swaddlers for newborns.') == ['Swaddlers']
    assert v.names_brand('Swaddlers fit small.') == []          # one word, first in its sentence
    assert v.names_brand('Ultra soft liners help.') == []
    assert v.names_brand('Try the Ultra line.') == ['Ultra']
    assert v.names_brand('It is made of pure cotton.') == []
    assert v.stamp()['digest'] == vocab().stamp()['digest']


def test_the_brand_terms_are_read_once_per_cycle_from_the_entities_and_the_study():
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as c:
        c.exec_driver_sql("CREATE TABLE soa_entities (id INTEGER PRIMARY KEY, name TEXT, aliases TEXT)")
        c.exec_driver_sql("CREATE TABLE soa_cycle_entities (cycle_id INTEGER, entity_id INTEGER, "
                          "comparison_code TEXT, role TEXT)")
        c.exec_driver_sql("CREATE TABLE soa_query_generation_jobs (study_type TEXT, tier_config TEXT)")
        c.exec_driver_sql("""INSERT INTO soa_entities VALUES (1, 'Pampers', '["pampers.com"]'),
                             (2, 'Huggies', '["huggies.com"]'), (3, 'Luvs', NULL)""")
        c.exec_driver_sql("INSERT INTO soa_cycle_entities VALUES (236, 1, 'M001', 'primary'), "
                          "(236, 2, 'M002', 'competitor'), (236, 3, 'M003', 'competitor')")
        c.exec_driver_sql("""INSERT INTO soa_query_generation_jobs VALUES
                             ('pampers', '{"merchant": {"product_names": ["Pampers Swaddlers Diapers"]}}')""")
    original = scorer_module.engine
    scorer_module.engine = engine
    try:
        cache = scorer_module.BrandTermsCache()
        terms = cache.for_cycle(236, 'pampers')
        assert terms == {'terms': ['Pampers', 'pampers.com'], 'product_names': ['Pampers Swaddlers Diapers'],
                         'rivals': ['Huggies', 'huggies.com', 'Luvs']}
        assert cache.for_cycle(236, 'pampers') is terms
        # a database without the tables: nothing, and the selector still has the brand and the catalog
        scorer_module.engine = create_engine('sqlite:///:memory:')
        assert scorer_module.BrandTermsCache().for_cycle(236, 'pampers') == \
            {'terms': [], 'product_names': [], 'rivals': []}
    finally:
        scorer_module.engine = original


# ── the selector: ten answers counted by hand ─────────────────────────────

@pytest.mark.parametrize('answer', HAND, ids=[f"{a['id']}-{a['query_code']}-{a['agent']}" for a in HAND])
def test_the_claim_sentences_counted_by_hand(answer):
    record, decided = judge(answer['answer'], answer['question'])
    assert [c['text'] for c in record['selector']['claims']] == answer['hand']['claims']
    assert decided['outcome'] == HAND_2O5.get(answer['id'], answer['hand']['outcome'])


def test_ten_answers_are_counted_by_hand_and_eighteen_claims_between_them():
    assert len(HAND) == 10 and sum(len(a['hand']['claims']) for a in HAND) == 18


def test_every_claim_is_judged_and_the_worst_decides():
    one = next(a for a in ANSWERS['answers'] if a['id'] == 7)
    _record, decided = judge(one['answer'], one['question'])
    spans = decided['brand_claim']['spans']
    # 2O-5: "#1 pediatrician recommended" is not on the pages read, and nothing contradicts it
    assert [s['verdict'] for s in spans] == ['echoed', 'unverified', 'grounded']
    assert decided['brand_claim']['decided_by'] == 2
    assert {f['text'] for f in spans[1]['facts_unverified']} == {'#1', 'pediatrician recommended'}
    assert [(s['via'], s['qualifier']) for s in spans] == [('named', None), ('named', None), ('named', 'Swaddlers')]
    # misattributed beats fabricated, fabricated beats grounded
    answer = ("Huggies Little Snugglers are popular. Pampers Swaddlers come in a 120 count box. "
              "Pampers Little Snugglers fit babies 8-14 lbs. Pampers Swaddlers Size 1 fit 8-14 lbs.")
    _record, decided = judge(answer, 'What weight do Pampers Swaddlers Size 1 fit?')
    assert [s['verdict'] for s in decided['brand_claim']['spans']] == ['unverified', 'misattributed', 'grounded']
    assert decided['outcome'] == 'misattributed'
    # contradicted beats grounded: Swaddlers Size 1 is 8-14 on the record and the page's chart
    answer = "Pampers Swaddlers Size 1 fit 8-14 lbs. Pampers Swaddlers Size 1 fit 2-9 lbs."
    _record, decided = judge(answer, 'What weight do Pampers Swaddlers Size 1 fit?')
    assert [s['verdict'] for s in decided['brand_claim']['spans']] == ['grounded', 'fabricated']
    assert decided['outcome'] == 'fabricated'


@pytest.mark.parametrize('answer,question,outcome,code', [
    # the question's facts are not the answer's: restated, echoed
    ('Pampers Pure Protection is fragrance free.', 'Is Pampers Pure Protection fragrance free?', 'echoed', None),
    # a sentence that only restates the question, with no fact at all
    ('Pampers Cruisers 360 are good for active babies.', 'Are Pampers Cruisers 360 good for active babies?',
     'echoed', None),
    # praise: about the brand, no fact, not the question's words
    ('Pampers is a great choice for most families.', 'Is Pampers a good diaper brand?', 'unscoreable',
     ea.NO_CHECKABLE_FACT),
    # hedged, by the lexicon and by the answer's own attribution
    ('Pampers Swaddlers may fit babies 6-12 lbs.', 'What weight do Pampers Swaddlers Size 1 fit?', 'unscoreable',
     ea.NO_CHECKABLE_FACT),
    ('Some parents say Pampers Swaddlers fit babies 6-12 lbs.', 'What weight do Pampers Swaddlers Size 1 fit?',
     'unscoreable', ea.NO_CHECKABLE_FACT),
    # a line the brand never made, as the line that qualifies the sentence, is still looked up;
    # 2O-5: and with no line list served, not on the index is unverified, never fabricated
    ('Pampers Swaddlers Overnights fit babies 8-14 lbs.', 'What weight do Pampers Swaddlers Size 1 fit?',
     'unscoreable', ea.UNVERIFIED),
    # a clause that names a rival and not the brand is the rival's
    ('Pampers Swaddlers fit 8-14 lbs, while Huggies fits 6-12 lbs.', 'What weight do Pampers Swaddlers fit?',
     'grounded', 'facts_published'),
    ('Most parents find disposable diapers comfortable.', 'Are Pampers Swaddlers good for newborns?', 'absent',
     None),
])
def test_what_is_a_claim(answer, question, outcome, code):
    _record, decided = judge(answer, question)
    assert (decided['outcome'], decided['reason_code']) == (outcome, code)


def test_the_record_stores_every_judged_sentence_and_how_it_was_chosen():
    one = next(a for a in ANSWERS['answers'] if a['id'] == 8)
    record, decided = judge(one['answer'], one['question'])
    assert record['coder'] == {'version': 8, 'question': one['question'], 'calls': []}
    assert record['selector']['units'] == 5 and record['selector']['about_brand'] == 4
    assert [c['via'] for c in record['selector']['claims']] == ['named', 'lead_in', 'lead_in', 'lead_in']
    assert record['selector']['vocabulary']['lines'][:2] == ['Swaddlers', 'Baby Dry']
    claim = decided['brand_claim']
    assert claim['version'] == 8 and len(claim['spans']) == 4
    # 2O-5: under a lead-in naming no line, Size 7 is unverified (the chart is Swaddlers', Baby Dry's ...)
    assert claim['spans'][3]['facts_unverified'][0] == {'type': 'size', 'text': 'Size 7'}
    assert claim['index']['by_source'] == {'record': 3, 'catalog': 34, 'brand_pages': 154}
    assert claim['selector'] == {'units': 5, 'about_brand': 4, 'hedged': 0, 'no_fact': 0}
    # span_labels: the units about the brand, by rule, for the claim-kind chip
    assert [lab['kind'] for lab in record['span_labels']] == ['assertion'] * 4
    # the stores a unit sends the reader to, for the fabricated-availability flag
    three = next(a for a in ANSWERS['answers'] if a['id'] == 3)
    record, _decided = judge(three['answer'], three['question'])
    assert [m['name'] for m in record['retailer_mentions']] == ['Walmart', 'Amazon', 'Target']


# ── no model call ─────────────────────────────────────────────────────────

class Explodes:
    """A model client or labeller: calling either is a bug."""

    async def extract(self, *_a, **_k):
        raise AssertionError('brand-direct must not call the extraction model')

    async def label(self, *_a, **_k):
        raise AssertionError('brand-direct must not call the labeller')


class NoHistory:
    def for_variant(self, *_a, **_k):
        return None


class NoTenant:
    def for_cycle(self, *_a, **_k):
        return []


class Pages:
    def for_cycle(self, *_a, **_k):
        return SimpleNamespace(payload=FL13['reference'])


class Terms:
    def for_cycle(self, *_a, **_k):
        return STUDY


def make_scorer():
    return scorer_module.ExpectationScorer(Explodes(), NoHistory(), FakeFacts(FL13['facts']), labeler=Explodes(),
                                           references=Pages(), tenant_domains=NoTenant(), brand_terms=Terms())


def seed(db):
    with db.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS soa_cycles (id INTEGER PRIMARY KEY, cycle_code TEXT)")
        conn.exec_driver_sql("INSERT INTO soa_cycles (id, cycle_code) VALUES (3, 'FL13-pampers-20261022')")
        conn.exec_driver_sql("ALTER TABLE soa_queries ADD COLUMN query_code TEXT")
        for a in ANSWERS['answers']:
            conn.execute(text("""
                INSERT INTO soa_queries (id, query_text, tier, expected_answer, provenance, source_ref, query_code)
                VALUES (:id, :q, 'brand_direct', :e, 'ai', :r, :code)
            """), {'id': a['id'], 'q': a['question'], 'e': json.dumps(EXPECTATION),
                   'r': json.dumps({'merchant_slug': 'pampers'}), 'code': a['query_code']})
            conn.execute(text("""
                INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number, raw_response, status)
                VALUES (:id, 3, :q, :agent, 1, :a, 'success')
            """), {'id': 100 + a['id'], 'q': a['id'], 'agent': a['agent'], 'a': a['answer']})


def stored(db):
    return {r['run_id']: (r['outcome'], r['reason_code'], r['outcome_reason'], r['extraction'])
            for r in outcomes(db)}


def test_the_scorer_makes_no_model_call_and_stores_the_selection(db):
    seed(db)
    scorer = make_scorer()
    results = [asyncio.run(scorer.score_run(100 + a['id'])) for a in ANSWERS['answers']]
    assert {r.status for r in results} == {'success'}
    row = next(r for r in outcomes(db) if r['run_id'] == 107)
    extraction = json.loads(row['extraction'])
    assert row['extraction_model'] is None and extraction['coder']['calls'] == []
    assert [s['verdict'] for s in extraction['brand_claim']['spans']] == ['echoed', 'unverified', 'grounded']


def test_two_runs_over_the_fixture_give_identical_outcomes(db):
    seed(db)
    for _ in range(2):
        scorer = make_scorer()
        for a in ANSWERS['answers']:
            asyncio.run(scorer.score_run(100 + a['id']))
        if _ == 0:
            first = stored(db)
    assert stored(db) == first
    assert sum(1 for run_id in first if first[run_id][0] != stored(db)[run_id][0]) == 0


def test_the_fl13_shaped_split():
    outcomes_ = Counter(judge(a['answer'], a['question'])[1]['outcome'] for a in ANSWERS['answers'])
    # 2O-5: the four fabricated for a fact absent from the index are grounded on another sentence
    assert outcomes_ == Counter({'grounded': 10, 'echoed': 2, 'misattributed': 1, 'unscoreable': 1, 'absent': 1})


# ── the FL14-shaped fixture ───────────────────────────────────────────────

def fl14_verdicts():
    v, idx = vocab(), index()
    out = []
    for a in FL14['answers']:
        record = sel.select(a['answer'], question=a['question'], vocab=v, own_domains=OWN)
        out.append((record, sel.decide(record, EXPECTATION, index=idx, own_domains=OWN)))
    return out


def test_fl14_shaped_two_runs_move_nothing():
    one, two = fl14_verdicts(), fl14_verdicts()
    assert sum(1 for a, b in zip(one, two) if a[1]['outcome'] != b[1]['outcome']) == 0
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)


def test_fl14_shaped_verdict_split():
    """The 2O-3 fixture's 258 answers (one sentence or two each, from its
    bank), decided by rule. Its records' model picks no longer matter."""
    verdicts = fl14_verdicts()
    # 2O-5: of 2O-4's 64 fabricated, 15 are contradicted (Swaddlers Size 1 at 6-12 lbs), the rest
    # unverified (31), grounded on another sentence (16) or acknowledged_unknown (2)
    assert Counter((d['outcome'], d['reason_code']) for _r, d in verdicts) == Counter({
        ('unscoreable', ea.NO_CHECKABLE_FACT): 92, ('grounded', 'facts_published'): 94,
        ('fabricated', 'fact_contradicted'): 15, ('unscoreable', ea.UNVERIFIED): 31, ('absent', None): 22,
        ('acknowledged_unknown', None): 4})
    claims = sorted(len(r['selector']['claims']) for r, _d in verdicts)
    assert (sum(claims), claims[0], claims[len(claims) // 2], claims[-1]) == (145, 0, 1, 2)


# ── the printout ──────────────────────────────────────────────────────────

def test_the_selection_report():
    rows = [(None, json.loads(json.dumps(sel_row)), outcome, code) for sel_row, outcome, code in [
        ({'selector': {}, 'brand_claim': {'spans': [{'kind': 'attribute'}] * 2, 'decided_by': 0,
                                          'index': {'version': 1, 'digest': 'abc', 'size': 83,
                                                    'by_source': {'record': 3, 'catalog': 27, 'brand_pages': 53}}}},
         'grounded', 'facts_published'),
        ({'selector': {}, 'brand_claim': {'spans': [], 'index': {'version': 1, 'digest': 'abc', 'size': 83,
                                                                 'by_source': {'record': 3, 'catalog': 27,
                                                                               'brand_pages': 53}}}},
         'unscoreable', 'no_checkable_fact'),
        ({'coder': {'version': 3}}, 'echoed', None),   # a version-3 row is not counted
    ]]
    report = rescore_cycle.selection_report([r[1:] for r in rows])
    assert (report['answers'], report['claims'], report['min'], report['median'], report['max']) == (2, 2, 0, 1, 2)
    text_ = rescore_cycle._render_selection(report, {'compared': 2, 'changed': 0})
    assert '    fact index           83 facts (record 3, catalog 27, brand pages 53); v1 abc' in text_
    assert '    claim sentences      2  (per answer: min 0, median 1, max 2; attribute 2)' in text_
    assert '    no_checkable_fact    1  (50.0% of answers; unscoreable, outside the counts)' in text_
    assert '    claim sets changed since the stored scoring: 0 of 2' in text_


def test_a_version_3_rows_claim_set_is_its_settling_calls_spans():
    call = {'brand_claims': [{'claim': 'Pampers Swaddlers fit 2-9 lbs.', 'kind': 'assertion',
                              'modality': 'asserted'}], 'spans': [{'text': 'Pampers Swaddlers fit 2-9 lbs.'}]}
    assert sel.claim_set({'coder': {'version': 3, 'pair': [0, 1], 'calls': [call, call]}}) == \
        ['Pampers Swaddlers fit 2-9 lbs.']
    assert sel.claim_set({'coder': {'version': 3, 'pair': None, 'calls': [call]}}) is None
    assert sel.claim_set({'coder': {'version': 2}}) is None


def _main(monkeypatch, capsys, *args):
    monkeypatch.setattr(rescore_cycle, '_brand_direct_scorer', lambda **_kw: make_scorer())
    code = rescore_cycle.main(['--cycle', 'FL13-pampers-20261022', '--tier', 'brand_direct', *args])
    return code, capsys.readouterr().out


def test_the_rescore_twice_and_dry_run_print_the_same_brand_direct_lines(db, capsys, monkeypatch):
    """rescore_cycle --tier brand_direct end to end on sqlite, with no
    OPEN_AI_API_KEY: the first run scores the 15 answers, the second moves
    none of them and says the claim sets are the stored ones, and a dry run
    prints exactly the second run's lines and writes nothing."""
    seed(db)
    monkeypatch.setattr(rescore_cycle, 'engine', db)
    monkeypatch.delenv('OPEN_AI_API_KEY', raising=False)

    code, first = _main(monkeypatch, capsys)
    assert code == 0 and 'rows whose outcome moved: 15 of 15' in first
    assert 'claim sets changed since the stored scoring: 0 of 0' in first

    code, second = _main(monkeypatch, capsys)
    assert code == 0
    assert 'rows whose outcome moved: 0 of 15' in second and 'primary outcomes changed in: nothing' in second
    assert ('brand-direct claims (2O-4: selected by rule, no model call; 2O-5: fabricated is contradicted by the '
            'fact index, absent is unverified):') in second
    digest = index().digest()
    assert f'    fact index           191 facts (record 3, catalog 34, brand pages 154); v3 {digest}' in second
    # 2O-5: the slots, and the split with unverified apart from unscoreable
    assert "    index slots          lines 10 (status known 6, retired: none; the brand's line list not served)" in second
    assert '      ranges per size    Newborn 6, Size 1 6, Size 2 6, Size 3 6, Size 4 6, Size 5 8, Size 6 6' in second
    assert '    split                grounded 10, misattributed 1, echoed 2, absent 1, unscoreable 1  (' in second
    assert '    fabricated, by the slot contradicted: none' in second
    assert '    answers              15' in second
    assert '    claim sentences      22  (per answer: min 0, median 1, max 4;' in second
    assert '    no_checkable_fact    1  (6.7% of answers; unscoreable, outside the counts)' in second
    assert '    claim sets changed since the stored scoring: 0 of 15' in second

    before = stored(db)
    code, dry = _main(monkeypatch, capsys, '--dry-run')
    assert code == 0 and stored(db) == before
    assert 'dry run — nothing written.' in dry

    def after_scoring(out):
        lines = out.split('\nscored ', 1)[1].split('\n')
        return [line for line in lines if not line.startswith('unchanged, not re-scored')]
    assert after_scoring(dry) == after_scoring(second)


def test_a_stored_version_3_row_counts_as_a_changed_claim_set(db, capsys, monkeypatch):
    """The first v14 run over FL14's v13 rows: the line prints, and counts
    the rows whose model-picked spans are not the rule's sentences."""
    seed(db)
    monkeypatch.setattr(rescore_cycle, 'engine', db)
    monkeypatch.delenv('OPEN_AI_API_KEY', raising=False)
    call = {'brand_claims': [{'claim': 'Pampers Swaddlers are widely considered the gold standard for newborns.',
                              'kind': 'assertion', 'modality': 'asserted'}], 'spans': []}
    with db.begin() as conn:
        conn.execute(text("""
            INSERT INTO soa_expectation_outcomes (run_id, cycle_id, tier, outcome, extraction, platform)
            VALUES (101, 3, 'brand_direct', 'fabricated', :x, 'perplexity')
        """), {'x': json.dumps({'coder': {'version': 3, 'pair': [0, 1], 'calls': [call, call]}})})
    _code, out = _main(monkeypatch, capsys)
    assert 'claim sets changed since the stored scoring: 1 of 1' in out
