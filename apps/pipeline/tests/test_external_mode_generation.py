"""
2B §1: the generator's external/brand mode, from the merchant's record.

Three fictional records in the shapes supply serves (tests/fixtures/
merchant_records/): a brand with two retailers, an external seller, and a
brand whose feed names no retailer URL. No model call: the AI-written tiers
are patched, exactly as test_syndicated_study.py does.
"""
import json
import os
from unittest.mock import patch

import pytest

from clients.truesync_catalog import build_snapshot, merge_merchant_record
from generation import catalog_tiers as ct
from generation import syndicated_study as ss
from soa_shared import expected_answers as ea

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def record(name):
    with open(os.path.join(FIXTURES, 'merchant_records', name)) as fh:
        return json.load(fh)


def snapshot_of(name):
    payload = record(name)
    snap = build_snapshot(payload['catalog'], merchants=payload['merchants'])
    return merge_merchant_record(snap, merchant=payload['tenant_merchant'],
                                 retailers=payload['retailers'], feed=payload['feed'])


@pytest.fixture
def brand():
    return snapshot_of('brand_two_retailers.json')


@pytest.fixture
def seller():
    return snapshot_of('external_seller.json')


@pytest.fixture
def no_retailers():
    return snapshot_of('brand_no_retailer_urls.json')


def accuracy(snapshot):
    return ct.build_catalog_accuracy(snapshot, category='Baby Care', persona='Value-Conscious Parent',
                                     study_pattern='brand_at_retail')


# ── the record ────────────────────────────────────────────────────────────

def test_the_record_is_read_onto_the_snapshot(brand, seller):
    assert brand.is_external and brand.merchant_kind == 'brand'
    assert brand.retailer_list == ['target.com', 'walmart.com']
    assert brand.own_domain == 'acmebaby.example'
    assert seller.retailer_list == ['acme-pets.test']
    assert seller.study_brand == 'Acme Pets'      # the store, not the dog food brand
    assert brand.study_brand == 'Acme Baby'


# ── a brand with two retailers ────────────────────────────────────────────

def test_a_brand_price_is_always_asked_at_a_retailer_in_its_list(brand):
    rows, report = accuracy(brand)
    assert [r['query_text'] for r in rows] == [
        'What does the Acme Baby Swaddle Diapers Size 3 cost at Target?',
        'What does the Acme Baby Swaddle Diapers Size 3 value pack cost at Walmart?',
        'What does the Acme Baby Swaddle Diapers Size 4 cost at Walmart?',
    ]
    assert report['asked_at'] == {
        '00012345678905': 'target.com', '00012345678912': 'walmart.com',
        '00012345678929': 'walmart.com',
    }
    for row in rows:
        assert ct.retailers_outside_list(row['query_text'], brand) == []
        assert ea.names_brand(row['query_text'], 'Acme Baby')


def test_the_price_expectation_carries_attributed_to_and_the_record_facts(brand):
    rows, _ = accuracy(brand)
    first = rows[0]
    assert first['expected_answer']['attributed_to'] == 'target.com'
    assert first['expected_answer']['amount'] == '24.99'   # the record's, kept as reference
    ref = first['source_ref']
    assert ref['own_domain'] == 'acmebaby.example'
    assert ref['merchant_kind'] == 'brand'
    assert ref['retailer_list'] == ['target.com', 'walmart.com']
    assert ref['gtin'] == '00012345678905'
    assert ref['variant_id'] == '00012345678905'
    ea.validate(first['expected_answer'])


def test_a_variant_sold_at_one_retailer_is_asked_there(brand):
    rows, _ = accuracy(brand)
    size_4 = [r for r in rows if r['source_ref']['variant_id'] == '00012345678929'][0]
    assert size_4['expected_answer']['attributed_to'] == 'walmart.com'


def test_brand_direct_context_targets_the_brands_own_claims_and_lists_retailers(brand):
    context = ct.build_catalog_context(brand)
    assert "It is a brand, not a store." in context
    assert 'Target (target.com), Walmart (walmart.com)' in context
    assert 'may name only these retailers' in context


def test_brand_direct_rows_carry_the_record_for_fabricated_availability(brand):
    rows = ct.stamp_brand_direct([{'query_text': 'Where can I buy Acme Baby diapers?'}], brand)
    assert rows[0]['expected_answer'] == {'type': 'brand_mention', 'brand': 'Acme Baby',
                                          'domain': 'acmebaby.example'}
    assert rows[0]['source_ref']['retailer_list'] == ['target.com', 'walmart.com']


# ── an external seller ────────────────────────────────────────────────────

def test_an_external_seller_is_priced_at_its_own_page(seller):
    rows, _ = accuracy(seller)
    assert [r['query_text'] for r in rows] == [
        'What does the Trailmix Adult Dog Food Chicken & Rice 35 lb cost at Acme Pets?',
        'What does the Trailmix Adult Dog Food Lamb & Rice 35 lb cost at Acme Pets?',
    ]
    assert {r['expected_answer']['attributed_to'] for r in rows} == {'acme-pets.test'}
    for row in rows:
        assert ea.names_brand(row['query_text'], seller.study_brand)


def test_an_external_sellers_brand_direct_names_the_store(seller):
    rows = ct.stamp_brand_direct([{'query_text': 'Does Acme Pets price match?'}], seller)
    assert rows[0]['expected_answer']['brand'] == 'Acme Pets'


# ── a brand with no retailer URLs ─────────────────────────────────────────

def test_a_brand_with_no_retailer_urls_gets_no_price_tier_and_says_why(no_retailers):
    rows, report = accuracy(no_retailers)
    assert rows == []
    assert 'no retailer URLs' in report['unavailable']
    assert 'no page a price could be scored against' in ct.expected_nulls(no_retailers, 'catalog_accuracy')


# ── the study as a whole ──────────────────────────────────────────────────

ALL_ON = {'brand_direct': {'enabled': True, 'count': 3}, 'catalog_accuracy': {'enabled': True},
          'value_incentives': {'enabled': True}, 'category_control': {'enabled': False}}


def build(snapshot, brand_rows):
    with patch.object(ss, 'generate_and_review_study', return_value=([], {})), \
            patch.object(ss, 'generate_brand_direct', return_value=(brand_rows, {'requested': 3})):
        return ss.build_syndicated_study(
            snapshot=snapshot, study_name='Acme', description='', stage_targets={'Research': 3},
            allowed_categories=['Baby Care'], study_pattern='brand_at_retail', api_key='k',
            tier_config=ALL_ON, personas=['Value-Conscious Parent'])


def test_a_brand_direct_question_naming_an_unlisted_retailer_is_dropped(brand):
    rows, _prov, config = build(brand, [
        {'query_text': 'Is Acme Baby cheaper at Target?', 'stage': 'Research'},
        {'query_text': 'Does Amazon carry Acme Baby diapers?', 'stage': 'Research'},
        {'query_text': 'What is the Acme Baby rewards program?', 'stage': 'Research'},
    ])
    texts = [r['query_text'] for r in rows]
    assert 'Does Amazon carry Acme Baby diapers?' not in texts
    assert config['brand_direct']['retailer_not_in_list_drops'] == [
        {'query_text': 'Does Amazon carry Acme Baby diapers?', 'retailers': ['amazon.com']}]
    assert config['merchant']['kind'] == 'brand'
    assert config['merchant']['retailer_list'] == ['target.com', 'walmart.com']


def test_the_tier_config_records_why_a_brand_has_no_price_tier(no_retailers):
    _rows, _prov, config = build(no_retailers, [])
    assert config['catalog_accuracy']['count'] == 0
    assert 'no retailer URLs' in config['catalog_accuracy']['unavailable']


def test_the_hosted_seller_is_generated_exactly_as_before():
    """W&S, hosted: merging a 'parleo' record changes no row."""
    with open(os.path.join(FIXTURES, 'wiggle_and_snug_catalog.json')) as fh:
        payloads = json.load(fh)

    def snap():
        return build_snapshot(payloads['catalog'], merchants=payloads['merchants'],
                              incentives=payloads['incentives'], price_history=payloads['price_history'])

    plain = snap()
    merged = merge_merchant_record(snap(), merchant={'slug': 'wiggle-and-snug', 'kind': 'seller',
                                                     'hosting': 'parleo'})
    assert accuracy(plain) == accuracy(merged)
    assert ct.build_value_incentives(plain, category='Baby Care', persona='p', study_pattern='brand_at_retail') == \
        ct.build_value_incentives(merged, category='Baby Care', persona='p', study_pattern='brand_at_retail')
    assert ct.build_catalog_context(plain) == ct.build_catalog_context(merged)
