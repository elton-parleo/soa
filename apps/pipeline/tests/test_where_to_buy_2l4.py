"""
2L-4 (B1): where-to-buy and cheapest-place questions on the brand-direct tier.

One of each per sampled variant, template-built (no model), naming the
product and no store, stage Ready to Buy, `source_ref.intent` saying which.
The stage counts absorb them: Ready to Buy first, then the other stages,
never Comparison. On the Wiggle & Snug fixture (19 sampled variants) that is
38 questions taken out of a 50-question brief, so the study stays 87.
"""
import filecmp
import os

from generation import catalog_tiers as ct
from soa_shared import retailers as af
from tests.test_syndicated_study import ALL_ON, STAGE_TARGETS, _build, payloads, snapshot  # noqa: F401  (fixtures)


def test_one_of_each_per_sampled_variant_naming_no_store(snapshot):  # noqa: F811
    rows, report = ct.build_intent_questions(snapshot, category='Baby Care', persona='Value-Conscious Parent',
                                             study_pattern='brand_at_retail')
    sampled = [v.variant_id for _p, v in ct.sample_variants(snapshot)]
    # 2M-1: plus ATTRIBUTE_CAP (10) attribute questions, which test_attribute_2m1.py covers
    assert (report['where_to_buy'], report['cheapest_place'], report['attribute'], report['count']) == (19, 19, 10, 48)
    assert report['sampled_variants'] == sampled
    by = {i: [r for r in rows if r['source_ref']['intent'] == i] for i in ct.INTENTS}
    assert [r['source_ref']['variant_id'] for r in by['where_to_buy']] == sampled
    assert [r['source_ref']['variant_id'] for r in by['cheapest_place']] == sampled
    assert by['where_to_buy'][0]['query_text'] == 'Where can I buy Wiggle & Snug Snug-Fit Diapers Size 1 small pack?'
    assert by['cheapest_place'][0]['query_text'] == 'Cheapest place to buy Wiggle & Snug Snug-Fit Diapers Size 1 small pack?'
    for r in rows:
        assert (r['tier'], r['stage'], r['provenance']) == ('brand_direct', 'Ready to Buy', 'catalog')
        assert r['expected_answer']['type'] == 'brand_mention'
        assert af.retailers_named(r['query_text']) == []


def test_the_demo_wording():
    assert ct.intent_question_text('where_to_buy', 'Pampers Swaddlers Size 1, 96 count') == \
        'Where can I buy Pampers Swaddlers Size 1, 96 count?'
    assert ct.intent_question_text('cheapest_place', 'Pampers AMORE Size 1, 132 count') == \
        'Cheapest place to buy Pampers AMORE Size 1, 132 count?'


def test_the_stage_counts_absorb_them_ready_to_buy_first():
    # the console's default brief, Balanced over four stages
    targets, taken, left = ct.absorb_intents({'Awareness': 13, 'Research': 13, 'Comparison': 12, 'Ready to Buy': 12}, 20)
    assert targets == {'Awareness': 9, 'Research': 9, 'Comparison': 12, 'Ready to Buy': 0}
    assert (taken, left) == ({'Ready to Buy': 12, 'Research': 4, 'Awareness': 4}, 0)
    # never Comparison: what the other stages cannot hold is left over
    targets, taken, left = ct.absorb_intents({'Awareness': 2, 'Comparison': 12, 'Ready to Buy': 3}, 20)
    assert (targets['Comparison'], sum(taken.values()), left) == (12, 5, 15)


def test_the_study_stays_the_size_of_its_brief(snapshot):  # noqa: F811
    rows, _prov, config, stage_call, _b = _build(snapshot, ALL_ON)
    asked = stage_call.call_args.kwargs['stage_targets']
    # Ready to Buy's 16, then Research's 12 and Awareness's 10; Comparison kept
    assert asked == {'Comparison': 12}
    # 2M-1: the 10 attribute questions add to the study (87 + 10)
    assert len(rows) == sum(STAGE_TARGETS.values()) + 12 + 19 + 6 + 10
    intents = config['brand_direct']['intents']
    assert (intents['count'], intents['not_absorbed'], intents['stage']) == (48, 0, 'Ready to Buy')
    assert intents['absorbed'] == {'Ready to Buy': 16, 'Research': 12, 'Awareness': 10}
    assert intents['stage_targets'] == STAGE_TARGETS


def test_nothing_moves_with_brand_direct_off(snapshot):  # noqa: F811
    rows, _prov, config, stage_call, _b = _build(snapshot, {**ALL_ON, 'brand_direct': {'enabled': False}})
    assert stage_call.call_args.kwargs['stage_targets'] == STAGE_TARGETS
    assert not any((r.get('source_ref') or {}).get('intent') for r in rows)
    assert 'intents' not in config['brand_direct']


def test_the_api_copy_is_identical():
    here = os.path.dirname(os.path.abspath(__file__))
    pipeline = os.path.join(here, '..', 'soa_shared', 'catalog_tiers.py')
    api = os.path.join(here, '..', '..', 'api', 'soa_shared', 'catalog_tiers.py')
    assert filecmp.cmp(pipeline, api, shallow=False)
