"""
2B §2 and §3: retailer_price against the attributed page, the grounded-by-
source split, fabricated_availability, and the four rules ported from the
console-demo engine's checks.ts.

No network and no model: the W&S record is the repo's own catalog fixture,
the retailer-prices payloads are recorded fixtures (tests/fixtures/
retailer_prices/, a fictional brand), and every comparison is the
deterministic comparator.

Where a test names "the engine's example", the case is taken from the
comment or doc string in parleohq/truesync console-demo services/engine/
src/checks.ts that states the rule.
"""
import json
import os

import pytest

from clients.truesync_catalog import build_snapshot
from scoring import answer_flags as af
from scoring import expectation_comparator as cmp
from scoring import record_variants as rv
from scoring import variant_rules as vr
from scoring.retailer_reference import ReferenceSet, judge_claim, ReferenceRow
from soa_shared import expected_answers as ea

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def _json(*parts):
    with open(os.path.join(FIXTURES, *parts)) as fh:
        return json.load(fh)


@pytest.fixture(scope='module')
def ws_variants():
    payloads = _json('wiggle_and_snug_catalog.json')
    snapshot = build_snapshot(payloads['catalog'], merchants=payloads['merchants'],
                              incentives=payloads['incentives'],
                              price_history=payloads['price_history'])
    return rv.from_snapshot(snapshot)


SIZE_3_SMALL = {
    'merchant_slug': 'wiggle-and-snug', 'listing_id': 90,
    'variant_id': 'snug-fit-diapers-s3-small',
    'attribution': ['Size 3', 'small pack'],
    'attribution_rivals': ['big pack', 'Size 1', 'Size 2', 'Size 4', 'Size 5', 'Size 6'],
}
PRICE = ea.price('22.99')


def extraction(**overrides):
    base = {'prices': [], 'codes': [], 'pack_counts': [], 'gtins': [], 'member_prices': [],
            'points': [], 'brand_mentioned': True, 'sources_cited': [],
            'extraction_confident': True, 'extraction_note': None}
    base.update(overrides)
    return base


def price(amount, product):
    return {'amount': amount, 'currency': None, 'attributed_product': product}


def ws(expectation, extracted, variants, **kwargs):
    kwargs.setdefault('source_ref', SIZE_3_SMALL)
    return cmp.compare(expectation, extracted, record_variants=variants, **kwargs)


# ═══ Rule 1 and rule 4: whole-dollar partial ═════════════════════════════

def test_rule1_engine_example_241_for_240_99_is_partial():
    """checks.ts compareQuote: 'A whole-dollar quote within fifty cents of
    the shelf ("$241" for $240.99) is a rounding, not a miss.'"""
    assert vr.rounds_to('241', '240.99')
    assert vr.rounds_to('241.00', '240.99')
    assert not vr.rounds_to('241.50', '240.99')  # not whole-dollar
    assert not vr.rounds_to('242', '240.99')     # not within 50 cents


def test_rule1_about_18_for_17_99_is_partial_never_exact(ws_variants):
    result = ws(ea.price('17.99'), extraction(prices=[price('18', 'Snug-Fit Size 3 small pack')]),
                ws_variants)
    assert result.outcome == cmp.PARTIAL
    assert result.outcome != cmp.EXACT


def test_rule1_is_strict_at_fifty_cents():
    assert vr.rounds_to('18', '17.51')
    assert not vr.rounds_to('18', '17.50')


def test_rule4_whole_dollar_applies_to_member_prices(ws_variants):
    member = ea.member_price('16.84', 'Member+')
    result = ws(member, extraction(member_prices=[
        {'amount': '17', 'tier': 'Member+', 'attributed_product': 'Size 3 small pack'},
    ]), ws_variants)
    assert result.outcome == cmp.PARTIAL


def test_a_whole_dollar_miss_by_more_than_fifty_cents_is_still_wrong(ws_variants):
    result = ws(PRICE, extraction(prices=[price('18.00', 'Snug-Fit Size 3, 84 ct')]), ws_variants)
    assert result.outcome == cmp.WRONG


# ═══ Rule 2: clashes ══════════════════════════════════════════════════════

def test_engine_pack_numbers_examples():
    """checks.ts packNumbers: "24 Mega Rolls", "160 count", "198 Ct",
    "12 boxes", "32 oz", "3 Month Supply"; weight bands are left out."""
    assert vr.pack_numbers('24 Mega Rolls') == {24}
    assert vr.pack_numbers('160 count') == {160}
    assert vr.pack_numbers('198 Ct') == {198}
    assert vr.pack_numbers('12 boxes') == {12}
    assert vr.pack_numbers('32 oz') == {32}
    assert vr.pack_numbers('3 Month Supply') == {3}
    assert vr.pack_numbers('for dogs 33.1-66 lbs') == set()


def test_engine_model_number_examples():
    """checks.ts modelNumberClash: 'Speedgoat 6' against 'Speedgoat 7',
    'iO Series 9' against 'iO Series 6', 'Size 1' against 'Size 3'; 'iO9'
    reads as 'io 9' and meets 'iO Series 9'."""
    assert vr.model_number_clash('HOKA Speedgoat 6', 'HOKA Speedgoat 7')
    assert vr.model_number_clash('Oral-B iO Series 9', 'Oral-B iO Series 6')
    assert vr.model_number_clash('Size 1', 'Size 3')
    assert not vr.model_number_clash('Oral-B iO9', 'Oral-B iO Series 9')
    assert vr.model_number_clash('Oral-B iO9', 'Oral-B iO Series 7')


def test_engine_variant_marker_examples():
    """checks.ts VARIANT_MARKERS: GTX, the women's cut, used stock, Worn
    Wear; plus 2B's overnight and sensitive."""
    assert vr.variant_markers("Women's Speedgoat 6 GTX") == {'women', 'gtx'}
    assert vr.variant_markers('Patagonia Worn Wear jacket') == {'used'}
    assert vr.variant_markers('pre-owned') == {'preowned'}
    assert vr.marker_clash('Snug-Fit Overnight Size 3', 'Snug-Fit Diapers Size 3 day') == {'overnight'}
    # One-sided: an answer omitting "overnight" has not named a different product.
    assert vr.marker_clash('Snug-Fit Size 3', 'Snug-Fit Overnight Diapers Size 3') == set()


def test_rule2_pack_clash_names_the_sibling_and_is_scored_against_it(ws_variants):
    """'168 ct' is the Size 3 Big Pack. The claim is scored against the Big
    Pack ($39.99) — right for an adjacent variant of the same item group,
    so partial — and flagged variant_swap."""
    result = ws(PRICE, extraction(prices=[price('39.99', 'Snug-Fit Diapers 168 ct')]), ws_variants)
    assert result.outcome == cmp.PARTIAL
    assert result.reason_code == cmp.REASON_VARIANT_SWAP
    assert 'variant_swap' in result.flag_names
    (claim,) = result.claims
    assert claim['variant_id'] == 'snug-fit-diapers-s3-big'
    # Never exact: the Big Pack's price, said for the Small Pack question.
    assert claim['outcome'] == cmp.PARTIAL
    assert claim['priced_as_named'] is True


def test_rule2_model_number_clash_size_1_against_size_3(ws_variants):
    result = ws(PRICE, extraction(prices=[price('17.99', 'Size 1 small pack')]), ws_variants)
    assert result.outcome == cmp.PARTIAL
    assert result.claims[0]['variant_id'] == 'snug-fit-diapers-s1-small'


def test_rule2_variant_marker_names_another_product_and_is_wrong(ws_variants):
    """'Overnight' names the Overnight Size 3, a different product. Its
    price is right for that product, which has still not priced the one
    asked about: wrong, variant_swap."""
    result = ws(PRICE, extraction(prices=[price('23.99', 'Snug-Fit Overnight Diapers Size 3')]),
                ws_variants)
    assert result.outcome == cmp.WRONG
    assert result.reason_code == cmp.REASON_VARIANT_SWAP
    assert result.claims[0]['variant_id'] == 'snug-fit-overnight-s3'
    assert result.claims[0]['same_group'] is False


def test_rule2_trial_pack_price_on_a_size_question_is_wrong_never_exact(ws_variants):
    """Cycle 229 (FL3-wiggle-and-snug-20261014), runs 12985 and others:
    asked the Size 3 small pack, Gemini answered "Snug-Fit Trial Pack,
    $6.99". The Trial Pack is a different product (its own listing), and
    $6.99 is its price: wrong, variant_swap — and the claim itself is wrong
    too, so no check marks it right."""
    result = ws(PRICE, extraction(prices=[price('6.99', 'Wiggle & Snug Snug-Fit Trial Pack')]),
                ws_variants)
    assert result.outcome == cmp.WRONG
    assert result.reason_code == cmp.REASON_VARIANT_SWAP
    assert 'variant_swap' in result.flag_names
    (claim,) = result.claims
    assert claim['variant_id'] == 'snug-fit-trial-pack'
    assert claim['same_group'] is False
    assert claim['priced_as_named'] is True
    assert claim['outcome'] == cmp.WRONG
    assert 'a different product' in result.reason


def test_rule2_a_swapped_claim_is_never_exact(ws_variants):
    """Whatever variant a swapped claim names and however well it prices
    it, neither the question nor the claim is exact."""
    for stated, product in (('39.99', 'Snug-Fit Diapers 168 ct'), ('17.99', 'Size 1 small pack'),
                            ('23.99', 'Snug-Fit Overnight Diapers Size 3'),
                            ('6.99', 'Snug-Fit Trial Pack')):
        result = ws(PRICE, extraction(prices=[price(stated, product)]), ws_variants)
        assert result.reason_code == cmp.REASON_VARIANT_SWAP, product
        assert result.outcome != cmp.EXACT, product
        assert all(c['outcome'] != cmp.EXACT for c in result.claims), product


def test_rule2_a_clash_naming_no_record_variant_is_variant_clash(ws_variants):
    result = ws(PRICE, extraction(prices=[price('22.99', 'Snug-Fit Diapers 300 ct')]), ws_variants)
    assert result.outcome == cmp.WRONG
    assert result.reason_code == cmp.REASON_VARIANT_CLASH
    assert 'variant_swap' not in result.flag_names


def test_rule2_keeps_the_volunteered_wrong_count_rule(ws_variants):
    """catalog_tiers._discriminators: an answer naming the right variant
    and volunteering the WRONG count must not lose its price measurement
    to that count. 'Size 3 small pack, 92 ct' at $22.99 is exact."""
    result = ws(PRICE, extraction(prices=[price('22.99', 'Size 3 small pack (92 ct)')]), ws_variants)
    assert result.outcome == cmp.EXACT


def test_rule2_without_the_record_the_legacy_filter_stands():
    """No record variants (catalog unavailable): a claim attributed to a
    sibling is ignored exactly as before 2B, never guessed at."""
    result = cmp.compare(PRICE, extraction(prices=[price('39.99', 'Size 3 Big Pack, 168 ct')]),
                         source_ref=SIZE_3_SMALL)
    assert result.outcome == cmp.ABSENT


def test_asked_claims_decide_even_when_a_sibling_is_also_priced(ws_variants):
    result = ws(PRICE, extraction(prices=[
        price('39.99', 'Size 3 Big Pack, 168 ct'), price('22.99', 'Size 3 Small Pack, 84 ct'),
    ]), ws_variants)
    assert result.outcome == cmp.EXACT
    assert 'variant_swap' in result.flag_names  # the sibling claim is still recorded


# ═══ Rule 3: product_inferred ═════════════════════════════════════════════

def test_rule3_engine_example_unnamed_product_mismatch_is_unscoreable(ws_variants):
    """checks.ts canBeWrong: "'Wrong' is the readout's strongest claim, so
    it needs the agent to have named the item." A price attached to no
    product that misses is unscoreable, reason product_inferred."""
    result = ws(PRICE, extraction(prices=[price('19.49', None)]), ws_variants)
    assert result.outcome == cmp.UNSCOREABLE
    assert result.reason_code == cmp.REASON_PRODUCT_INFERRED


def test_rule3_an_unnamed_exact_match_is_still_exact(ws_variants):
    assert ws(PRICE, extraction(prices=[price('22.99', None)]), ws_variants).outcome == cmp.EXACT


def test_rule3_a_named_wrong_claim_outranks_an_inferred_one(ws_variants):
    result = ws(PRICE, extraction(prices=[price('19.49', None),
                                          price('11.00', 'Size 3 small pack')]), ws_variants)
    assert result.outcome == cmp.WRONG


# ═══ §2: retailer_price against the attributed page ══════════════════════

ACME_REF = {
    'merchant_slug': 'acme-baby', 'variant_id': '00012345678905', 'gtin': '00012345678905',
    'own_domain': 'acmebaby.example', 'merchant_kind': 'brand',
    'retailer_list': ['target.com', 'walmart.com'],
}
ACME_120 = {**ACME_REF, 'variant_id': '00012345678912', 'gtin': '00012345678912'}


@pytest.fixture(scope='module')
def reference():
    return ReferenceSet(_json('retailer_prices', 'acme_baby_as_of_cycle2.json'),
                        prior_payload=_json('retailer_prices', 'acme_baby_as_of_cycle1.json'),
                        prior_cycle_code='ACME-C1')


def at(retailer, amount='24.99'):
    return ea.price(amount, attributed_to=retailer)


@pytest.mark.parametrize('stated, outcome', [
    ('21.49', cmp.EXACT),
    ('22.99', cmp.STALE),        # the previous cycle's page price
    ('21', cmp.PARTIAL),         # whole-dollar within 50 cents
    ('24.99', cmp.WRONG),        # the list price / record MSRP is not the page price
])
def test_retailer_price_outcomes_at_target(reference, stated, outcome):
    result = cmp.compare(at('target.com'), extraction(prices=[price(stated, 'Acme Swaddle Size 3')]),
                         source_ref=ACME_REF, reference=reference)
    assert result.outcome == outcome, result.reason


def test_retailer_price_reads_the_attributed_page_not_another(reference):
    """$17.99 is Walmart's page price. Attributed to Target it is wrong."""
    stated = extraction(prices=[price('17.99', 'Acme Swaddle Size 3')])
    assert cmp.compare(at('walmart.com'), stated, source_ref=ACME_REF,
                       reference=reference).outcome == cmp.EXACT
    assert cmp.compare(at('target.com'), stated, source_ref=ACME_REF,
                       reference=reference).outcome == cmp.WRONG


def test_unverifiable_is_never_wrong(reference):
    """Target blocked both reference sources for the 120 ct page."""
    result = cmp.compare(at('target.com'), extraction(prices=[price('99.00', 'Acme Swaddle 120 ct')]),
                         source_ref=ACME_120, reference=reference)
    assert result.outcome == cmp.UNVERIFIABLE
    assert 'challenged' in result.reason


def test_absent_and_unscoreable_on_the_retailer_path(reference):
    assert cmp.compare(at('target.com'), extraction(), source_ref=ACME_REF,
                       reference=reference).outcome == cmp.ABSENT
    garbled = extraction(prices=[price('call for price', 'Acme Swaddle')])
    assert cmp.compare(at('target.com'), garbled, source_ref=ACME_REF,
                       reference=reference).outcome == cmp.UNSCOREABLE


def test_no_reference_read_is_unverifiable_not_wrong():
    result = cmp.compare(at('target.com'), extraction(prices=[price('1.00', 'Acme')]),
                         source_ref=ACME_REF, reference=None)
    assert result.outcome == cmp.UNVERIFIABLE


def test_member_price_attributed_to_a_page_reads_its_member_price(reference):
    member = ea.member_price('20.00', 'Target Circle', attributed_to='target.com')
    result = cmp.compare(member, extraction(member_prices=[
        {'amount': '19.34', 'tier': None, 'attributed_product': 'Acme Swaddle Size 3'},
    ]), source_ref=ACME_REF, reference=reference)
    assert result.outcome == cmp.EXACT


def test_stale_needs_a_previous_cycle(reference):
    without_prior = ReferenceSet(_json('retailer_prices', 'acme_baby_as_of_cycle2.json'))
    stated = extraction(prices=[price('22.99', 'Acme Swaddle Size 3')])
    assert cmp.compare(at('target.com'), stated, source_ref=ACME_REF,
                       reference=without_prior).outcome == cmp.WRONG
    assert 'nothing is stale' in without_prior.stale_basis
    assert 'ACME-C1' in reference.stale_basis


def test_judge_claim_tolerance_is_half_a_cent():
    row = ReferenceRow.from_payload({'retailer_domain': 'target.com', 'price': '21.49',
                                     'verifiable': True})
    assert judge_claim('21.494', row=row, prior=None, member=False)[0] == cmp.EXACT
    assert judge_claim('21.50', row=row, prior=None, member=False)[0] == cmp.WRONG


def test_attributed_to_must_be_a_bare_domain():
    assert ea.price('1.00', attributed_to='https://www.Target.com/p/1')['attributed_to'] == 'target.com'
    with pytest.raises(ea.ExpectedAnswerError):
        ea.validate({'type': 'price', 'amount': '1.00', 'currency': 'USD',
                     'attributed_to': 'https://target.com'})
    with pytest.raises(ea.ExpectedAnswerError):
        ea.validate({'type': 'gtin', 'value': '1', 'attributed_to': 'target.com'})


# ═══ fabricated_availability ══════════════════════════════════════════════

def availability(mentions, **ref):
    source_ref = {**ACME_REF, **ref}
    return cmp.compare(ea.brand_mention('Acme Baby'), extraction(retailer_mentions=mentions),
                       source_ref=source_ref)


def test_a_retailer_not_in_the_list_is_fabricated_availability():
    result = availability([{'name': 'Amazon', 'role': 'recommendation'},
                           {'name': 'Target', 'role': 'recommendation'}])
    (flag,) = [f for f in result.flags if f['flag'] == 'fabricated_availability']
    assert [r['domain'] for r in flag['retailers']] == ['amazon.com']


def test_online_counts_for_a_brand_without_its_own_site_listed():
    result = availability([{'name': 'online retailers', 'role': 'recommendation'}])
    assert 'fabricated_availability' in result.flag_names


def test_online_is_fine_for_a_seller():
    result = availability([{'name': 'online', 'role': 'recommendation'}],
                          merchant_kind='seller', retailer_list=[])
    assert 'fabricated_availability' not in result.flag_names


def test_unavailable_is_not_a_placement_and_unknown_names_are_not_flagged():
    result = availability([{'name': 'Amazon', 'role': 'unavailable'},
                           {'name': "Bob's Baby Barn", 'role': 'recommendation'}])
    assert 'fabricated_availability' not in result.flag_names


def test_the_hosted_seller_is_unchanged_no_retailer_list_no_flag():
    result = cmp.compare(ea.brand_mention('Wiggle & Snug'), extraction(
        retailer_mentions=[{'name': 'Amazon', 'role': 'recommendation'}]), source_ref=SIZE_3_SMALL)
    assert result.flags == []


# ═══ grounded by source ═══════════════════════════════════════════════════

def test_source_split_own_listed_other():
    result = cmp.compare(ea.brand_mention('Acme Baby', 'acmebaby.example'), extraction(
        sources_cited=['acmebaby.example', 'www.target.com', 'babylist.com']),
        source_ref=ACME_REF, retrieved_sources=['https://shop.acmebaby.example/p/1'])
    assert result.source_split == {
        'own_domain': ['acmebaby.example', 'shop.acmebaby.example'],
        'listed_retailer': ['target.com'],
        'other': ['babylist.com'],
    }


def test_the_existing_grounded_bucket_is_unchanged_by_the_split():
    assert af.source_split([], own_domain='a.com', retailer_list=[]) == {
        'own_domain': [], 'listed_retailer': [], 'other': []}
