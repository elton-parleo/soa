"""
2O-1 (H27): the brand-claim coder agrees with itself.

Rescoring FL14 on Oct 23 with no rule change for the tier moved 55 of its
258 brand-direct answers. The coder made one model call; now it makes two,
keeps a category only when they agree (the same category, and for
fabricated or grounded an overlapping claim), makes a third on a
disagreement, and with no two agreeing scores the answer `unscoreable` for
coder_disagreed.

2O-3: the live coder is version 3 (the verdict a lookup of the claim's facts,
tests/test_brand_claim_2o3.py). A stored version-2 record is still decided by
the rule below, so these tests pin the version to 2 (pin_v2) and keep
testing it.

No model is called. The pairs (fixtures/brand_coder/coder_pairs.json) are
hand-built records, not recordings: no key was present when this was
written. The FL14-shaped fixture is built from the rescore printout
(fixtures/build_brand_coder_fl14_2o1.py, which says what is and is not
recorded).
"""
import asyncio
import json
import os
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parser import expectation_client as ec
from parser import labeling_client as lc
from parser.expectation_client import CODER_SETTINGS, ExtractionResult
from scoring import brand_direct_classifier as bdc
from scoring import expectation_comparator as cmp
from scoring import expectation_scorer as scorer_module
from scripts import rescore_cycle
from soa_shared import expected_answers as ea
from tests.test_expectation_scorer import FakeFacts, db, outcomes  # noqa: F401  (db is a fixture)
from sqlalchemy import text

HERE = os.path.dirname(os.path.abspath(__file__))
PAIRS = json.load(open(os.path.join(HERE, 'fixtures', 'brand_coder', 'coder_pairs.json')))
FL14 = json.load(open(os.path.join(HERE, 'fixtures', 'brand_coder', 'fl14_shaped.json')))

@pytest.fixture(autouse=True)
def pin_v2(monkeypatch):
    """2O-3: the version-2 rule, which a record that version wrote is decided by."""
    monkeypatch.setattr(ea, 'BRAND_CODER_VERSION', 2)


BRAND, DOMAIN = PAIRS['brand'], PAIRS['domain']
EXPECTATION = ea.brand_mention(BRAND, DOMAIN)
FACTS = {'brand': BRAND, 'domain': DOMAIN, 'tier_names': [], 'product_titles': []}


def coded(calls):
    """A version-2 record over `calls`, as the scorer stores it before settling."""
    return {**calls[0], 'coder': {'version': ea.BRAND_CODER_VERSION, 'calls': calls}}


def decide(calls):
    return cmp.compare(EXPECTATION, coded(calls), tier='brand_direct', brand_facts=FACTS)


# ── the rule ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('case', PAIRS['cases'], ids=[c['name'] for c in PAIRS['cases']])
def test_each_pair_settles_as_its_case_says(case):
    verdict = decide(case['calls'])
    want = case['expect']
    assert verdict.outcome == want['outcome']
    assert verdict.coder['pair'] == want['pair']
    assert verdict.reason_code == want.get('reason_code', verdict.reason_code)
    if want['calls'] == 3:
        # the first two alone do not settle: that is what made the third call
        assert decide(case['calls'][:2]).coder['pair'] is None


def test_an_unsettled_answer_is_unscoreable_with_the_answers_line():
    case = next(c for c in PAIRS['cases'] if c['name'] == 'never_settles')
    verdict = decide(case['calls'])
    assert (verdict.outcome, verdict.reason_code, verdict.reason) == \
        ('unscoreable', 'coder_disagreed', 'the coder could not settle this answer')
    assert verdict.coder['outcomes'] == ['grounded', 'fabricated', 'echoed']


def test_the_same_category_with_claims_that_do_not_overlap_is_a_disagreement():
    a = {'outcome': 'fabricated', 'span': 'Pampers AMORE is made in France'}
    b = {'outcome': 'fabricated', 'span': 'has a blue wetness line that turns yellow'}
    assert not bdc.agree(a, b)
    assert bdc.agree(a, {'outcome': 'fabricated', 'span': 'AMORE is made in France'})
    # only fabricated and grounded compare a claim
    assert bdc.agree({'outcome': 'echoed', 'span': None}, {'outcome': 'echoed', 'span': None})
    # a cited domain is its own span: the same domain agrees, a sentence does not
    assert bdc.agree({'outcome': 'grounded', 'span': 'pampers.com'}, {'outcome': 'grounded', 'span': 'pampers.com'})
    assert not bdc.agree({'outcome': 'grounded', 'span': 'pampers.com'},
                         {'outcome': 'grounded', 'span': 'Swaddlers have a wetness indicator'})


def test_two_of_three_takes_the_earliest_agreeing_pair():
    e, f, g = ({'outcome': o, 'span': None} for o in ('echoed', 'absent', 'echoed'))
    assert bdc.settle([e, f, g]) == (0, 2)
    assert bdc.settle([f, e, g]) == (1, 2)
    assert bdc.settle([e, f]) is None


def test_a_record_one_call_wrote_is_classified_as_before():
    case = PAIRS['cases'][1]
    alone = cmp.compare(EXPECTATION, case['calls'][0], tier='brand_direct', brand_facts=FACTS)
    assert alone.outcome == 'fabricated' and alone.coder is None


# ── the scorer: two calls, a third on a disagreement ─────────────────────

class Replay:
    """The extraction client, replaying a case's calls in order."""

    def __init__(self, case):
        self.case = case
        self.extract = AsyncMock(side_effect=[
            ExtractionResult(record=json.loads(json.dumps(r)), model='gpt-5.4-mini', usage=u['extract'])
            for r, u in zip(case['calls'], case['usage'])])


class NoHistory:
    def for_variant(self, *_a, **_k):
        return None


class NoTenant:
    def for_cycle(self, *_a, **_k):
        return []


def seed_brand(db, answer):
    with db.begin() as conn:
        conn.execute(text("""
            INSERT INTO soa_queries (id, query_text, tier, expected_answer, provenance, source_ref)
            VALUES (1, 'Is Pampers AMORE good for newborns?', 'brand_direct', :e, 'ai', :r)
        """), {'e': json.dumps(EXPECTATION), 'r': json.dumps({'merchant_slug': 'pampers'})})
        conn.execute(text("""
            INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number, raw_response, status)
            VALUES (7, 3, 1, 'perplexity', 1, :a, 'success')
        """), {'a': answer})


def score_case(db, case):
    seed_brand(db, case['answer'])
    client = Replay(case)
    scorer = scorer_module.ExpectationScorer(client, NoHistory(), FakeFacts(FACTS), labeler=False,
                                             tenant_domains=NoTenant())
    result = asyncio.run(scorer.score_run(7))
    (row,) = outcomes(db)
    return client, result, row


@pytest.mark.parametrize('case', PAIRS['cases'], ids=[c['name'] for c in PAIRS['cases']])
def test_the_scorer_makes_two_calls_and_a_third_only_on_a_disagreement(db, case):
    client, result, row = score_case(db, case)
    want = case['expect']
    assert client.extract.await_count == want['calls']
    # the extractor's settings, on every coder call
    assert all(c.kwargs['settings'] == CODER_SETTINGS for c in client.extract.await_args_list)
    assert row['outcome'] == want['outcome'] == result.outcome
    stored = json.loads(row['extraction'])
    coder = stored['coder']
    assert coder['version'] == ea.BRAND_CODER_VERSION and len(coder['calls']) == want['calls']
    assert coder['pair'] == want['pair'] and coder['settings'] == CODER_SETTINGS
    assert [u['extract'] for u in coder['usage']] == [u['extract'] for u in case['usage']]
    if want['pair']:
        # the record is the settling call's
        assert stored['brand_claims'] == case['calls'][want['pair'][0]]['brand_claims']
    else:
        assert (row['reason_code'], row['outcome_reason']) == (ea.CODER_DISAGREED, ea.CODER_DISAGREED_NOTE)


def test_a_classify_only_re_score_re_takes_the_decision_from_the_stored_calls(db):
    """rescore --classify-only classifies the stored record: the same
    decision, twice, with no model call."""
    case = next(c for c in PAIRS['cases'] if c['name'] == 'disagree_claim_third_decides')
    _client, _result, row = score_case(db, case)
    stored = json.loads(row['extraction'])
    run = SimpleNamespace(tier='brand_direct', source_ref={'merchant_slug': 'pampers'}, study_type=None, cycle_id=3,
                          answer_status=None, retrieved_sources=None, grounding=None)
    first = scorer_module.classify(run, EXPECTATION, stored, brand_facts=FakeFacts(FACTS))
    second = scorer_module.classify(run, EXPECTATION, stored, brand_facts=FakeFacts(FACTS))
    assert first.outcome == second.outcome == row['outcome'] == 'fabricated'
    assert first.coder == second.coder == {'outcomes': ['fabricated', 'fabricated', 'fabricated'], 'pair': [0, 2]}


def test_a_wall_is_stamped_with_the_coder_version_and_no_call(db):
    seed_brand(db, '')
    with db.begin() as conn:
        conn.execute(text("UPDATE soa_runs SET answer_status = 'sign_in_wall'"))
    client = Replay(PAIRS['cases'][0])
    scorer = scorer_module.ExpectationScorer(client, NoHistory(), FakeFacts(FACTS), labeler=False,
                                             tenant_domains=NoTenant())
    asyncio.run(scorer.score_run(7))
    (row,) = outcomes(db)
    assert client.extract.await_count == 0
    assert json.loads(row['extraction'])['coder'] == {'version': ea.BRAND_CODER_VERSION, 'calls': []}


def test_another_tier_makes_one_call_with_no_settings(db):
    from tests.test_expectation_scorer import make_scorer, seed
    seed(db)
    scorer = make_scorer()
    asyncio.run(scorer.score_run(7))
    assert scorer.client.extract.await_count == 1
    assert 'settings' not in scorer.client.extract.await_args.kwargs
    assert 'coder' not in json.loads(outcomes(db)[0]['extraction'])


# ── the settings reach the request ────────────────────────────────────────

def _response(payload):
    return SimpleNamespace(output_text=json.dumps(payload),
                           usage=SimpleNamespace(input_tokens=10, output_tokens=2))


def test_the_coder_settings_are_the_extractors_and_only_the_coder_sends_them(monkeypatch):
    monkeypatch.setattr(ec.config, 'OPEN_AI_API_KEY', 'x')
    client = ec.ExpectationClient()
    create = AsyncMock(return_value=_response({**ec.EMPTY_EXTRACTION, 'extraction_confident': True}))
    client._client = MagicMock()
    client._client.responses.create = create
    asyncio.run(client.extract('Pampers is fine.', brand=BRAND, settings=CODER_SETTINGS))
    kwargs = create.await_args.kwargs
    assert kwargs['reasoning'] == {'effort': 'none'} and kwargs['text']['verbosity'] == 'low'
    asyncio.run(client.extract('Pampers is fine.', brand=BRAND))
    kwargs = create.await_args.kwargs
    assert 'reasoning' not in kwargs and 'verbosity' not in kwargs['text']


def test_the_labeller_sends_them_too(monkeypatch):
    monkeypatch.setattr(lc.config, 'OPEN_AI_API_KEY', 'x')
    labeler = lc.LabelingClient()
    create = AsyncMock(return_value=_response(lc.EMPTY_LABELS))
    labeler._client = MagicMock()
    labeler._client.responses.create = create
    record = {**PAIRS['cases'][1]['calls'][0]}
    asyncio.run(labeler.label(record, answer_text=PAIRS['cases'][1]['answer'], settings=CODER_SETTINGS))
    assert create.await_args.kwargs['reasoning'] == {'effort': 'none'}
    assert create.await_args.kwargs['text']['verbosity'] == 'low'


# ── FL14's shape: the counts before and after ─────────────────────────────

CLAIM = "Pampers Swaddlers are made with 100% organic cotton"
TEMPLATES = {
    'grounded': {'sources_cited': [DOMAIN]},
    'fabricated': {'brand_claims': [{'claim': CLAIM, 'sentence': CLAIM, 'claim_kind': 'product',
                                     'kind': 'assertion', 'modality': 'asserted'}]},
    'echoed': {},
    'acknowledged_unknown': {'brand_unknown_statement': "I couldn't find Pampers AMORE on the brand's site."},
    'misattributed': {'other_brands_named': [{'name': 'Huggies', 'relation': 'closest_match_described'}]},
    'absent': {'brand_mentioned': False},
    'unscoreable': {'extraction_confident': False, 'extraction_note': 'the answer could not be read'},
}


def record_for(category):
    return {**PAIRS['cases'][0]['calls'][0], **json.loads(json.dumps(TEMPLATES[category]))}


def test_each_template_classifies_as_its_category():
    for category in TEMPLATES:
        got = cmp.compare(EXPECTATION, record_for(category), tier='brand_direct', brand_facts=FACTS).outcome
        assert got == category


def fl14_counts():
    one_call, rescore, two_call, how = Counter(), Counter(), Counter(), Counter()
    for answer in FL14['answers']:
        calls = [record_for(c) for c in answer['calls']]
        one_call[cmp.compare(EXPECTATION, calls[0], tier='brand_direct', brand_facts=FACTS).outcome] += 1
        rescore[cmp.compare(EXPECTATION, calls[1], tier='brand_direct', brand_facts=FACTS).outcome] += 1
        verdict = decide(calls[:2])
        if verdict.coder['pair'] is None:
            verdict = decide(calls)
        two_call[verdict.outcome] += 1
        pair = verdict.coder['pair']
        how['first two' if pair == [0, 1] else 'third call' if pair else 'unsettled'] += 1
    return one_call, rescore, two_call, how


def test_fl14_shaped_counts_before_and_after():
    one_call, rescore, two_call, how = fl14_counts()
    # one call, as stored before Oct 23's rescore, and that rescore's one call
    assert one_call == Counter(FL14['before'])
    assert rescore == Counter(FL14['after_one_call_rescore'])
    # the two-call coder: 203 settle on the first two (78.7%), 37 on a third, 18 never
    assert how == Counter({'first two': 203, 'third call': 37, 'unsettled': 18})
    assert two_call == Counter({'absent': 6, 'acknowledged_unknown': 3, 'echoed': 49, 'fabricated': 112,
                                'grounded': 65, 'misattributed': 3, 'unscoreable': 20})
    # the 20 unscoreable: the 2 unreadable answers both calls agreed on, and the 18 the coder could not settle
    assert sum(two_call.values()) == 258


def test_the_moved_answers_are_the_printouts():
    moved = [a for a in FL14['answers'] if a['run_id']]
    assert len(moved) == 55
    assert all(a['calls'][0] != a['calls'][1] for a in moved)
    assert {a['run_id'] for a in moved} >= {14959, 15342, 15443}


# ── the rescore's report ──────────────────────────────────────────────────

def test_the_rescore_reports_the_coders_calls_agreement_and_tokens(db):
    stored = []
    for case in PAIRS['cases']:
        with db.begin() as conn:
            conn.execute(text("DELETE FROM soa_runs")); conn.execute(text("DELETE FROM soa_queries"))
            conn.execute(text("DELETE FROM soa_expectation_outcomes"))
        _c, _r, row = score_case(db, case)
        stored.append(json.loads(row['extraction']))
    stored.append({'brand_mentioned': True})            # a row one call wrote, before 2O-1
    report = rescore_cycle.coder_report(stored)
    assert {k: report[k] for k in ('answers', 'single_call', 'calls', 'agreed_first_two', 'third_calls',
                                   'settled_by_third', 'unsettled')} == \
        {'answers': 5, 'single_call': 1, 'calls': 13, 'agreed_first_two': 2, 'third_calls': 3,
         'settled_by_third': 2, 'unsettled': 1}
    assert report['agreement_rate'] == 0.4
    # the extraction's tokens only here: labeler=False makes no labelling call
    assert (report['input_tokens'], report['output_tokens']) == (13 * 2900, 13 * 240)
    # no stored price for the coder's model: no dollar figure, and the line says so
    assert rescore_cycle.coder_dollars(report, 'gpt-5.4-mini') is None
    assert 'no stored price for gpt-5.4-mini' in rescore_cycle._render_coder(report, 'gpt-5.4-mini')


def test_coder_disagreed_is_a_named_rule():
    assert 'coder_disagreed' in rescore_cycle.RULES
