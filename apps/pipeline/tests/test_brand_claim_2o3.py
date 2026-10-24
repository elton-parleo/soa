"""
2O-3 (B1): the brand-claim verdict is decided by code; the model only extracts.

The coder's calls (2O-1: two, a third on a disagreement) transcribe and label
the answer as before. Version 3 takes only the claim spans from them, checks
2A-5's evidence rule on each, makes the calls agree on their spans, and
decides the category by looking each span's facts up in the brand's fact
index for the cycle (scoring/brand_fact_index.py,
scoring/brand_claim_verdict.py).

No model is called: each call's record is built here from the answer with
the pipeline's own segmenter and labels (parser/extraction_postprocess.
apply_labels), as the labelling call leaves it.

2O-4: the scorer no longer makes these calls (the claims are selected by
rule, tests/test_brand_claim_selector_2o4.py). A stored version-3 record is
still decided over its calls, as rescore --classify-only decides it, and
that is what these tests keep pinning.
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from parser import extraction_postprocess as pp
from parser.expectation_client import ExtractionResult
from scoring import brand_claim_verdict as bcv
from scoring import brand_fact_index as bfi
from scoring import expectation_comparator as cmp
from scoring import expectation_scorer as scorer_module
from scripts import rescore_cycle
from soa_shared import expected_answers as ea
from tests.test_expectation_scorer import FakeFacts, db, outcomes  # noqa: F401  (db is a fixture)

BRAND, DOMAIN = 'Pampers', 'pampers.com'
EXPECTATION = ea.brand_mention(BRAND, DOMAIN)
QUESTION = 'What sizes do Pampers Swaddlers come in?'
FACTS = {
    'brand': BRAND, 'domain': DOMAIN, 'own_domains': [DOMAIN], 'retailer_list': ['walmart.com', 'amazon.com'],
    'tier_names': [], 'program_name': None,
    'product_titles': ['Pampers Swaddlers Diapers Size 1, 96 Count', 'Pampers Pure Protection Diapers Size 2, 74 Count'],
    'variants': [
        {'title': 'Pampers Swaddlers Diapers Size 1, 96 Count', 'size': '1', 'count': 96, 'list_price': '27.97',
         'weight_range': {'min': 8, 'max': 14}, 'attributes': {'wetness_indicator': True}},
        {'title': 'Pampers Pure Protection Diapers Size 2, 74 Count', 'size': '2', 'count': 74,
         'list_price': '31.97', 'weight_range': {'min': 12, 'max': 18}, 'attributes': {'fragrance_free': True}},
    ],
    'features': ['Wetness indicator lets you know when it is time to change', 'Hypoallergenic and fragrance free'],
}
BASE = {'prices': [], 'codes': [], 'pack_counts': [], 'sizes': [], 'gtins': [], 'member_prices': [], 'points': [],
        'brand_mentioned': True, 'brand_unknown_statement': None, 'other_brands_named': [],
        'loyalty_tiers_named': [], 'brand_claims': [], 'sources_cited': [], 'recommended_retailers': [],
        'postprocess': [], 'extraction_confident': True, 'extraction_note': None}


def record(answer, asserted=None, **fields):
    """One call's record: the answer segmented, the spans whose text is in
    `asserted` labelled asserted assertions (every span when None), the rest
    `none`, as apply_labels stores the labelling call's answer."""
    spans = pp.segment(answer)
    labels = {'spans': [{'span_id': s['id'],
                         'kind': 'assertion' if asserted is None or s['text'] in asserted else 'none',
                         'modality': 'asserted'} for s in spans],
              'other_brands': [{'name': o['name'], 'relation': 'comparison'}
                               for o in fields.get('other_brands_named') or []],
              'retailers': [{'name': n, 'role': 'recommendation'} for n in fields.get('recommended_retailers') or []]}
    return pp.apply_labels({**BASE, **fields}, labels, answer_text=answer, brand=BRAND)


def coded(calls, answer, question=QUESTION):
    calls = [{**c, 'evidence': bcv.evidence(c, answer)} for c in calls]
    return {**calls[0], 'coder': {'version': 3, 'question': question, 'calls': calls}}


def decide(calls, answer, question=QUESTION, facts=FACTS, index=None):
    return cmp.compare(EXPECTATION, coded(calls, answer, question), tier='brand_direct', brand_facts=facts,
                       brand_index=index)


# ── the verdict is the index's ────────────────────────────────────────────

# 2O-5: fabricated is contradicted: the record's Swaddlers Size 1 is 8-14 lbs
FABRICATED = "Pampers Swaddlers Size 1 fit babies 2-9 lbs. They come in a 96 count box."


def test_a_fact_not_on_the_index_is_fabricated_and_the_reason_names_it():
    v = decide([record(FABRICATED), record(FABRICATED)], FABRICATED)
    assert (v.outcome, v.reason_code) == ('fabricated', 'fact_contradicted')
    # the feed's range alone is the brand's record, not a page's chart
    assert v.reason == "fabricated: '2-9 lbs' for Swaddlers Size 1 — Pampers' record says 8 to 14 lb"
    span = v.brand_claim['spans'][v.brand_claim['decided_by']]
    assert span['facts_missing'] == [{'type': 'weight', 'text': '2-9 lbs', 'slot': 'ranges', 'claimed': '2-9 lbs',
                                      'published': '8 to 14 lb', 'line': 'Swaddlers', 'size': '1',
                                      'source': 'record',
                                      # 2P-1 (B4): the reason's half after the dash, for the drawer
                                      'evidence': "Pampers' record says 8 to 14 lb"}]
    # Swaddlers is the question's, so not a fact the span adds; it names the page
    assert span['facts_found'] == [{'type': 'size', 'text': 'Size 1'}] and span['line'] == 'Swaddlers'
    assert v.brand_claim['index']['version'] == bfi.INDEX_VERSION and v.brand_claim['index']['digest']


def test_a_fact_the_index_does_not_hold_is_unverified_not_fabricated():
    """2O-5: no size named, and the record's Swaddlers sizes are the feed's
    sample, not a chart: nothing contradicts 2-9 lbs. The 96 count box is
    on the record, so the answer is grounded on its second sentence."""
    answer = "Pampers Swaddlers fit babies 2-9 lbs. They come in a 96 count box."
    v = decide([record(answer), record(answer)], answer)
    assert (v.outcome, v.reason_code) == ('grounded', 'facts_published')
    first = v.brand_claim['spans'][0]
    assert first['verdict'] == 'unverified' and first['facts_unverified'] == [{'type': 'weight', 'text': '2-9 lbs'}]
    alone = "Pampers Swaddlers fit babies 2-9 lbs."
    v = decide([record(alone), record(alone)], alone)
    assert (v.outcome, v.reason_code) == ('unscoreable', ea.UNVERIFIED)
    assert v.reason == f"'Pampers Swaddlers fit babies 2-9 lbs.' — {ea.UNVERIFIED_NOTE}"


def test_every_fact_on_the_index_is_grounded():
    answer = "Pampers Swaddlers fit babies 8-14 lbs in Size 1 and have a wetness indicator."
    v = decide([record(answer), record(answer)], answer)
    assert (v.outcome, v.reason_code) == ('grounded', 'facts_published')
    assert [f['type'] for f in v.brand_claim['spans'][0]['facts_found']] == ['size', 'weight', 'attribute']


def test_a_span_with_no_checkable_fact_is_unscoreable_outside_the_counts():
    answer = "Pampers is a great choice for most families and parents love it."
    v = decide([record(answer), record(answer)], answer, question='Is Pampers a good diaper brand?')
    assert (v.outcome, v.reason_code, v.reason) == ('unscoreable', ea.NO_CHECKABLE_FACT, ea.NO_CHECKABLE_FACT_NOTE)


def test_the_label_wobble_that_moved_fl14_no_longer_moves_the_category():
    """Call 1 labels the praise an asserted claim, call 2 labels it none:
    under version 2 that was fabricated against echoed. Neither span set has a
    checkable fact, so both calls give the same verdict."""
    answer = "Pampers Swaddlers are widely considered the gold standard. Parents love them."
    one = record(answer)                    # both sentences asserted
    two = record(answer, asserted=[])       # nothing asserted
    q = 'Are Pampers Swaddlers good for newborns?'
    assert decide([one, one], answer, q).outcome == decide([two, two], answer, q).outcome == 'unscoreable'


# ── the calls agree on spans; 2A-5's evidence rule refuses a call ─────────

class Replay:
    def __init__(self, records):
        self.extract = AsyncMock(side_effect=[
            ExtractionResult(record=json.loads(json.dumps(r)), model='gpt-5.4-mini',
                             usage={'input_tokens': 2900, 'output_tokens': 240}) for r in records])


class NoHistory:
    def for_variant(self, *_a, **_k):
        return None


class NoTenant:
    def for_cycle(self, *_a, **_k):
        return []


class Pages:
    """The cycle's cached retailer-prices read (ReferenceCache.for_cycle)."""

    def __init__(self, payload=None):
        self.payload = payload

    def for_cycle(self, *_a, **_k):
        return SimpleNamespace(payload=self.payload) if self.payload else None


def seed(db, answer, question=QUESTION):
    with db.begin() as conn:
        conn.execute(text("""
            INSERT INTO soa_queries (id, query_text, tier, expected_answer, provenance, source_ref)
            VALUES (1, :q, 'brand_direct', :e, 'ai', :r)
        """), {'q': question, 'e': json.dumps(EXPECTATION), 'r': json.dumps({'merchant_slug': 'pampers'})})
        conn.execute(text("""
            INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number, raw_response, status)
            VALUES (7, 3, 1, 'perplexity', 1, :a, 'success')
        """), {'a': answer})


def test_a_stored_version_3_record_settles_on_its_spans_and_keeps_the_evidence():
    v = decide([record(FABRICATED), record(FABRICATED)], FABRICATED)
    assert v.coder == {'pair': [0, 1], 'refused': [False, False]}
    assert (v.outcome, v.reason_code) == ('fabricated', 'fact_contradicted')
    claim = v.brand_claim
    assert claim['version'] == 3
    assert claim['spans'][claim['decided_by']]['facts_missing'][0]['text'] == '2-9 lbs'


def test_a_span_not_in_the_answer_refuses_the_call_and_a_third_decides():
    """2A-5: a call whose claim is not the answer's words agrees with nothing."""
    invented = {**record(FABRICATED), 'brand_claims': [
        {'claim': 'Pampers Swaddlers are made in Ohio.', 'sentence': 'Pampers Swaddlers are made in Ohio.',
         'kind': 'assertion', 'modality': 'asserted', 'effective_modality': 'asserted'}]}
    v = decide([invented, record(FABRICATED), record(FABRICATED)], FABRICATED)
    assert v.coder == {'pair': [1, 2], 'refused': [True, False, False]}
    assert bcv.evidence(invented, FABRICATED)['missing'] == ['Pampers Swaddlers are made in Ohio.']
    assert v.outcome == 'fabricated'


def test_span_sets_that_do_not_overlap_are_a_disagreement():
    answer = "Pampers Swaddlers fit babies 2-9 lbs. Pampers Pure Protection is fragrance free."
    first = record(answer, asserted=['Pampers Swaddlers fit babies 2-9 lbs.'])
    second = record(answer, asserted=['Pampers Pure Protection is fragrance free.'])
    v = decide([first, second, second], answer)
    assert v.coder['pair'] == [1, 2] and v.outcome == 'grounded'
    assert decide([first, second], answer).reason_code == ea.CODER_DISAGREED


def test_a_classify_only_re_score_re_takes_the_verdict_from_the_stored_calls():
    stored = coded([record(FABRICATED), record(FABRICATED)], FABRICATED)
    run = SimpleNamespace(tier='brand_direct', source_ref={'merchant_slug': 'pampers'}, study_type=None, cycle_id=3,
                          answer_status=None, retrieved_sources=None, grounding=None)
    kwargs = dict(brand_facts=FakeFacts(FACTS), references=Pages())
    first = scorer_module.classify(run, EXPECTATION, stored, **kwargs)
    second = scorer_module.classify(run, EXPECTATION, stored, **kwargs)
    assert first.outcome == second.outcome == 'fabricated'
    assert first.brand_claim == second.brand_claim and first.brand_claim['version'] == 3
    assert rescore_cycle._signature(first) == rescore_cycle._signature(second)


def test_the_page_reads_cached_on_the_cycle_are_in_the_index(db):
    """A weight the record does not carry and the brand page's size chart does is grounded."""
    answer = "Pampers Swaddlers Size 3 fit babies 16-28 lbs."
    seed(db, answer)
    pages = Pages({'prices': [{'retailer_domain': DOMAIN, 'role': 'own', 'variant_label': 'Swaddlers S3',
                               'page_title': 'Pampers Swaddlers Diapers Size 3, 84 Count',
                               'size_chart': [{'size': '3', 'min': 16, 'max': 28}]}]})
    client = Replay([])
    scorer = scorer_module.ExpectationScorer(client, NoHistory(), FakeFacts(FACTS), labeler=False,
                                             references=pages, tenant_domains=NoTenant())
    asyncio.run(scorer.score_run(7))
    (row,) = outcomes(db)
    # 2O-4: selected by rule, so no call
    assert row['outcome'] == 'grounded' and client.extract.await_count == 0


def test_a_version_2_record_is_still_decided_by_the_version_2_rule():
    answer = "Pampers Swaddlers are widely considered the gold standard."
    calls = [record(answer), record(answer)]
    v2 = {**calls[0], 'coder': {'version': 2, 'calls': calls}}
    assert cmp.compare(EXPECTATION, v2, tier='brand_direct', brand_facts=FACTS).outcome == 'fabricated'
    assert decide(calls, answer).outcome == 'unscoreable'


def test_a_wall_is_stamped_with_the_coder_version_and_no_call(db):
    seed(db, '')
    with db.begin() as conn:
        conn.execute(text("UPDATE soa_runs SET answer_status = 'sign_in_wall'"))
    client = Replay([])
    scorer = scorer_module.ExpectationScorer(client, NoHistory(), FakeFacts(FACTS), labeler=False,
                                             references=Pages(), tenant_domains=NoTenant())
    asyncio.run(scorer.score_run(7))
    (row,) = outcomes(db)
    assert client.extract.await_count == 0 and row['outcome'] == 'absent'
    assert json.loads(row['extraction'])['coder'] == {'version': ea.BRAND_CODER_VERSION, 'calls': []}


# ── the rescore names the rules and reports the spans ─────────────────────

def test_the_new_reason_codes_are_named_rules():
    for code in ('fact_not_published', 'facts_published', 'no_checkable_fact', 'fact_type_not_read'):
        assert code in rescore_cycle.RULES


@pytest.mark.parametrize('copy', ['apps/api', 'packages/shared'])
def test_the_vocabulary_copies_agree(copy):
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root = os.path.dirname(os.path.dirname(here))
    with open(os.path.join(here, 'soa_shared', 'expected_answers.py')) as a, \
            open(os.path.join(root, copy, 'soa_shared', 'expected_answers.py')) as b:
        assert a.read() == b.read()
