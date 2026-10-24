"""
2O-3 (B2): the brand-claim verdict is stable wherever the spans are.

Two consecutive re-scores of FL14 under the two-call coder moved 66 of its
258 brand-direct answers (fl14-coder-run2.txt). Version 3 decides the
category from the claim spans' facts against the brand's fact index, so the
only variance left is in the spans the model extracts. These tests pin that:

  * the fact index built from the FL13-shaped record and brand pages
    (fixtures/brand_claim/fl13_record_pages.json);
  * one span per verdict;
  * the echo threshold on the demo's question/answer pairs
    (fixtures/brand_claim/echo_pairs.json);
  * two "recordings" of FL14's 258 answers (fixtures/brand_claim/
    fl14_shaped_runs.json): wherever the two runs' span sets agree, the
    verdict is the same; the split from each run's spans, and how many
    answers' verdicts differ between them, beside the printout's 66.

NOTHING HERE IS RECORDED. No OPEN_AI_API_KEY was present in the session that
wrote 2O-3, so no call was made. The FL14-shaped runs reproduce the
printout's 66 moves under the version-2 rule, each built as one sentence the
labeller asserted in one run and not the other; which sentence is the
builder's choice (fixtures/build_brand_claim_2o3.py says how). The figures
below are this fixture's, not FL14's: Elton's two rescores measure FL14.
"""
import json
import os
from collections import Counter

import pytest

from scoring import brand_claim_verdict as bcv
from scoring import brand_direct_classifier as bdc
from scoring import brand_fact_index as bfi
from soa_shared import expected_answers as ea

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, 'fixtures', 'brand_claim')
FL13 = json.load(open(os.path.join(FIXTURES, 'fl13_record_pages.json')))
FL14 = json.load(open(os.path.join(FIXTURES, 'fl14_shaped_runs.json')))
PAIRS = json.load(open(os.path.join(FIXTURES, 'echo_pairs.json')))['pairs']
EXPECTATION = ea.brand_mention('Pampers', 'pampers.com')
OWN = ['pampers.com']


@pytest.fixture(scope='module')
def index():
    return bfi.build(FL13['facts'], FL13['reference'])


# ── the index ─────────────────────────────────────────────────────────────

def test_the_index_from_the_fl13_shaped_record_and_brand_pages(index):
    stamp = index.stamp()
    # 2O-5: version 2, the line slots on top of version 1's 83 facts
    assert (stamp['version'], stamp['size']) == (2, 191)
    assert stamp['types_read'] == list(bfi.FACT_TYPES)
    d = index.as_dict()
    # the retailer rows' prices (Walmart, and Amazon $3.00 above), the titles' counts and sizes
    assert '24.97' in d['prices'] and '27.97' in d['prices'] and len(d['prices']) == 14
    assert d['counts'] == ['66', '84', '96', '104', '136']
    assert d['sizes'] == ['0', '1', '2', '3', '4', '5', '6']
    # the size chart, from the record's weight ranges and the own pages' charts
    assert {'min': 8.0, 'max': 14.0} in d['weights'] and {'min': 27.0, 'max': None} in d['weights']
    assert d['retailers'] == ['amazon.com', 'pampers.com', 'walmart.com']
    # the own pages' bullets
    assert {'wetness indicator', 'fragrance free', 'hypoallergenic', 'umbilical cord notch'} <= set(d['attributes'])
    assert 'pampers pure protection diapers' in d['titles']


def test_the_index_is_the_same_twice(index):
    again = bfi.build(json.loads(json.dumps(FL13['facts'])), json.loads(json.dumps(FL13['reference'])))
    assert again.digest() == index.digest() and again.as_dict() == index.as_dict()


@pytest.mark.parametrize('text,kind,status', [
    ('Size 1 fits 8-14 lbs', 'weight', 'found'),
    ('Size 1 fits 6-12 lbs', 'weight', 'missing'),
    ('$24.97', 'price', 'found'),
    ('$25', 'price', 'found'),          # whole-dollar within fifty cents (rule 1)
    ('$45', 'price', 'missing'),
    ('a 96 count box', 'count', 'found'),
    ('a 120 count box', 'count', 'missing'),
    ('at Walmart', 'retailer', 'found'),
    ('at Target', 'retailer', 'missing'),
    ('fragrance-free', 'attribute', 'found'),
    # 2O-5: the Swaddlers page's "free of parabens and latex" states it
    ('latex free', 'attribute', 'found'),
    ('chlorine free', 'attribute', 'missing'),
    ('Pampers Pure Protection', 'name', 'found'),
    ('Pampers Swaddlers Overnights', 'name', 'missing'),
])
def test_a_fact_is_looked_up_by_its_type(index, text, kind, status):
    (fact,) = [f for f in bfi.facts_in(text, 'Pampers', own_domains=OWN) if f['type'] == kind]
    assert bfi.lookup(fact, index) == status


def test_a_type_the_cycle_read_nothing_of_is_unchecked_not_missing():
    titles_only = bfi.build({'brand': 'Pampers', 'domain': 'pampers.com', 'product_titles': ['Pampers Swaddlers']})
    (fact,) = bfi.facts_in('it is latex free', 'Pampers')
    assert 'attribute' not in titles_only.types_read() and bfi.lookup(fact, titles_only) == 'unchecked'
    one = {'brand_mentioned': True, 'extraction_confident': True, 'spans': [{'text': 'Pampers is latex free.'}],
           'brand_claims': [{'claim': 'Pampers is latex free.', 'kind': 'assertion', 'modality': 'asserted'}]}
    v = bcv.decide(one, EXPECTATION, question='Is Pampers safe?', index=titles_only)
    # 2O-5: not on the index and nothing contradicts it: unverified (unchecked was its special case)
    assert (v['outcome'], v['reason_code']) == ('unscoreable', ea.UNVERIFIED)


# ── one span per verdict ──────────────────────────────────────────────────

def _one(span, *, unknown=None, others=()):
    spans = [{'text': t} for t in ([unknown] if unknown else []) + [span]]
    return {'brand_mentioned': True, 'extraction_confident': True, 'spans': spans,
            'other_brands_named': [{'name': o} for o in others],
            'brand_claims': [{'claim': span, 'kind': 'assertion', 'modality': 'asserted'}] if span else []}


@pytest.mark.parametrize('question,record,outcome,code', [
    ('Are Pampers Swaddlers good for newborns?', _one('Pampers Swaddlers are good for newborns.'), 'echoed', None),
    ('What weight does Size 1 fit?', _one('Pampers Swaddlers Size 1 fit babies 8-14 lbs.'), 'grounded',
     'facts_published'),
    # 2O-5: Swaddlers Size 1 is 8-14 on the record and the page's chart: contradicted
    ('What weight does Size 1 fit?', _one('Pampers Swaddlers Size 1 fit babies 6-12 lbs.'), 'fabricated',
     'fact_contradicted'),
    ('Where can I buy Pampers Swaddlers?', _one('You can buy Pampers Swaddlers at Target.'), 'unscoreable',
     ea.UNVERIFIED),
    ('Do Pampers make a newborn diaper?', _one('Pampers Little Snugglers fit babies up to 14 lbs.',
                                               others=['Huggies Little Snugglers']), 'misattributed', None),
    ('Is Pampers AMORE good?', _one(None, unknown="I couldn't find information about Pampers AMORE."),
     'acknowledged_unknown', None),
    ('Is Pampers a good brand?', _one('Pampers is a great choice for most families.'), 'unscoreable',
     ea.NO_CHECKABLE_FACT),
])
def test_one_span_per_verdict(index, question, record, outcome, code):
    v = bcv.decide(record, EXPECTATION, question=question, index=index, own_domains=OWN)
    assert (v['outcome'], v['reason_code']) == (outcome, code)


def test_the_fabricated_reason_names_the_fact_and_the_page(index):
    v = bcv.decide(_one('Pampers Swaddlers Size 1 fit babies 6-12 lbs.'), EXPECTATION,
                   question='What weight does Size 1 fit?', index=index, own_domains=OWN)
    # 2O-5: the drawer line names the slot, the claim's value and the index's
    assert v['reason'] == "fabricated: '6-12 lbs' for Swaddlers Size 1 — pampers.com's chart says 8 to 14 lb"
    span = v['brand_claim']['spans'][v['brand_claim']['decided_by']]
    assert span['facts_missing'] == [{'type': 'weight', 'text': '6-12 lbs', 'slot': 'ranges', 'claimed': '6-12 lbs',
                                      'published': '8 to 14 lb', 'line': 'Swaddlers', 'size': '1'}]
    v = bcv.decide(_one('You can buy Pampers Swaddlers at Target.'), EXPECTATION,
                   question='Where can I buy Pampers Swaddlers?', index=index, own_domains=OWN)
    assert v['reason'] == "'You can buy Pampers Swaddlers at Target.' — " + ea.UNVERIFIED_NOTE


@pytest.mark.parametrize('span,kind', [
    ('You can buy Pampers Swaddlers at Walmart.', 'where_to_buy'),
    ('Pampers Swaddlers cost $24.97 at Walmart.', 'price'),
    ('Pampers Swaddlers cost $24.97.', 'price'),
    ('Pampers Baby Dry has been discontinued.', 'availability'),
    ('Pampers Pure Protection is fragrance free.', 'attribute'),
    ('I would recommend Pampers for most families.', 'recommendation'),
    ('Pampers has been around a long time.', 'general'),
])
def test_the_span_kind_is_decided_from_its_words(span, kind):
    assert bcv.span_kind(span, bfi.facts_in(span, 'Pampers', own_domains=OWN)) == kind


# ── the echo threshold ────────────────────────────────────────────────────

@pytest.mark.parametrize('pair', PAIRS, ids=[p['span'][:40] for p in PAIRS])
def test_the_echo_threshold_on_the_demos_pairs(index, pair):
    span = bcv.judge_span(pair['span'], question=pair['question'], brand='Pampers', index=index, own_domains=OWN)
    assert span['verdict'] == pair['verdict']


def test_the_threshold_sits_between_the_restatements_and_the_rest(index):
    def overlap(p):
        return bcv.judge_span(p['span'], question=p['question'], brand='Pampers', index=index,
                              own_domains=OWN).get('overlap')
    echoes = [overlap(p) for p in PAIRS if p['verdict'] == 'echoed']
    others = [overlap(p) for p in PAIRS if p['verdict'] == 'no_fact']
    assert min(echoes) >= bcv.ECHO_THRESHOLD > max(others)
    assert (min(echoes), max(others)) == (0.667, 0.5)


# ── two recordings: the verdict moves only where the spans do ─────────────

def verdicts(index):
    out = []
    for a in FL14['answers']:
        out.append([bcv.decide(r, EXPECTATION, question=a['question'], index=index, own_domains=OWN)
                    for r in a['runs']])
    return out


def test_the_fixture_reproduces_the_printouts_66_moves_under_version_2():
    facts = {'domain': 'pampers.com', 'own_domains': OWN}
    v2 = [[bdc.classify(r, EXPECTATION, brand_facts=facts)[0] for r in a['runs']] for a in FL14['answers']]
    assert Counter(a for a, _b in v2) == Counter(FL14['run1'])
    assert Counter(b for _a, b in v2) == Counter(FL14['run2'])
    assert sum(1 for a, b in v2 if a != b) == 66


def test_identical_spans_give_identical_verdicts(index):
    for a, (one, two) in zip(FL14['answers'], verdicts(index)):
        if bcv.spans_agree(bcv.claim_spans(a['runs'][0]), bcv.claim_spans(a['runs'][1])):
            assert one['outcome'] == two['outcome'], (a['query_code'], a['agent'])
    # and the same record, decided twice, is the same verdict
    a = FL14['answers'][0]
    assert bcv.decide(a['runs'][0], EXPECTATION, question=a['question'], index=index) == \
        bcv.decide(a['runs'][0], EXPECTATION, question=a['question'], index=index)


def test_fl14_shaped_split_per_run_and_the_variance_left(index):
    vs = verdicts(index)
    run1 = Counter(v[0]['outcome'] for v in vs)
    run2 = Counter(v[1]['outcome'] for v in vs)
    # 2O-5: fabricated is contradicted, so the 52 a fact merely absent from the
    # index made fabricated are unverified or grounded on another sentence
    assert run1 == Counter({'unscoreable': 142, 'grounded': 87, 'fabricated': 12, 'absent': 6,
                            'acknowledged_unknown': 7, 'misattributed': 4})
    assert run2 == Counter({'unscoreable': 150, 'grounded': 80, 'fabricated': 14, 'absent': 6,
                            'acknowledged_unknown': 8})
    # of run 1's 142 unscoreable, 112 state no checkable fact, 26 are unverified and 4 could not be read
    codes = Counter(v[0]['reason_code'] for v in vs if v[0]['outcome'] == 'unscoreable')
    assert codes == Counter({ea.NO_CHECKABLE_FACT: 112, ea.UNVERIFIED: 26, None: 4})
    # every fabricated answer left is the one sentence the record contradicts
    assert {s['text'] for v in vs for s in v[0]['brand_claim']['spans'] if s['verdict'] == 'fabricated'} == \
        {'Pampers Swaddlers Size 1 fit babies 6-12 lbs.'}
    # the span sets that differ between the two recordings: the only variance left
    differ = sum(1 for a in FL14['answers']
                 if not bcv.spans_agree(bcv.claim_spans(a['runs'][0]), bcv.claim_spans(a['runs'][1])))
    assert differ == 50
    # and the answers whose verdict differs, beside the printout's 66
    moved = [(a['query_code'], a['agent']) for a, v in zip(FL14['answers'], vs) if v[0]['outcome'] != v[1]['outcome']]
    assert len(moved) == 26      # 2O-5: 31 under 2O-3's absent-is-fabricated
    # every one of them is an answer whose spans differ (the fixture's moves are span wobble)
    assert all(not bcv.spans_agree(bcv.claim_spans(a['runs'][0]), bcv.claim_spans(a['runs'][1]))
               for a, v in zip(FL14['answers'], vs) if v[0]['outcome'] != v[1]['outcome'])


def test_the_rescore_counts_the_claim_sets_that_changed():
    """2O-4: the rescore compares claim sets sentence for sentence (no
    overlap allowance: a rule-selected set either is the same or is not)."""
    from scripts import rescore_cycle
    before = {i: bcv.claim_spans(a['runs'][0]) for i, a in enumerate(FL14['answers'])}
    after = {i: bcv.claim_spans(a['runs'][1]) for i, a in enumerate(FL14['answers'])}
    changed = rescore_cycle.claim_sets_changed(before, after)
    assert changed == {'compared': 258, 'changed': 50}
    assert rescore_cycle.claim_sets_changed(before, before) == {'compared': 258, 'changed': 0}
