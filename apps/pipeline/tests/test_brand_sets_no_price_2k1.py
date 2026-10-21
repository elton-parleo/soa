"""
2K-1 §2: the brand's own page carries no price, and a price attributed to it
is not an unverifiable answer.

Supply 2J-1 serves a brand's own-domain read as `none_by_design` (price null,
read_status ok, verifiable false, "brand site, no price set"). Before 2K-1 a
claim judged against that row scored `unverifiable` and counted in "N prices
could not be checked", which is a finding about a page we could not read. The
page was read; it sets no price by design. Now the claim is `unscoreable`
with reason code `brand_sets_no_price`, outside every accuracy and outside the
unverifiable count. Attribution to a retailer is unaffected.

Recorded payloads: packages/testing/fixtures/retailer_prices_fl12_2j4.json
(supply's rows for one FL12-shaped variant, before and after 2J-1's reparse).
"""
import json
import os

import pytest
import soa_pg_harness

from scoring import expectation_comparator as cmp
from scoring import retailer_reference as rr
from soa_shared import expected_answers as ea

with open(os.path.join(os.path.dirname(soa_pg_harness.__file__), 'fixtures', 'retailer_prices_fl12_2j4.json')) as _fh:
    PAYLOADS = json.load(_fh)

NB84 = {'merchant_slug': 'pampers', 'variant_id': '00037000863434', 'gtin': '00037000863434',
        'own_domain': 'pampers.com', 'merchant_kind': 'brand', 'retailer_list': ['walmart.com', 'amazon.com']}


def extraction(*amounts):
    return {'prices': [{'amount': a, 'currency': 'USD', 'attributed_product': 'Pampers Swaddlers NB 84'} for a in amounts],
            'codes': [], 'pack_counts': [], 'gtins': [], 'member_prices': [], 'points': [], 'brand_mentioned': True,
            'sources_cited': [], 'extraction_confident': True, 'extraction_note': None}


def compare(payload, retailer, *amounts):
    return cmp.compare(ea.price(None, attributed_to=retailer), extraction(*amounts), source_ref=NB84,
                       reference=rr.ReferenceSet(payload))


def test_a_price_attributed_to_the_brand_s_own_none_by_design_page_is_not_scored():
    result = compare(PAYLOADS['after'], 'pampers.com', '9.97')
    assert result.outcome == cmp.UNSCOREABLE
    assert result.reason_code == 'brand_sets_no_price'
    assert result.reason == "the brand's site sets no price; the agent priced it anyway"
    # the agent's quote is kept on the claim, for the drawer
    [claim] = result.claims
    assert (claim['stated'], claim['outcome'], claim['reason_code']) == ('9.97', 'unscoreable', 'brand_sets_no_price')
    assert claim['reference']['method'] == 'none_by_design'


def test_before_2k1_the_same_claim_scored_unverifiable_and_a_readable_own_page_still_scores():
    # the same row with the 2K-1 rule taken out reads as it did: unverifiable
    row = rr.ReferenceRow.from_payload(next(r for r in PAYLOADS['after']['prices'] if r['retailer_domain'] == 'pampers.com'))
    assert rr.brand_sets_no_price(row)
    row.method = 'regex'
    assert rr.judge_claim('9.97', row=row, prior=None, member=False)[0] == rr.UNVERIFIABLE
    # before 2J-1's reparse the page was read with a price: exact
    assert compare(PAYLOADS['before'], 'pampers.com', '9.97').outcome == cmp.EXACT


@pytest.mark.parametrize('retailer, stated, outcome', [
    ('amazon.com', '27.97', cmp.EXACT),
    ('amazon.com', '0.00', cmp.WRONG),
    ('target.com', '10.00', cmp.UNVERIFIABLE),    # a retailer page that states no price stays unverifiable
])
def test_attribution_to_a_retailer_is_unaffected(retailer, stated, outcome):
    result = compare(PAYLOADS['after'], retailer, stated)
    assert result.outcome == outcome and result.reason_code != 'brand_sets_no_price'


def test_a_none_by_design_row_on_a_retailer_role_is_not_the_brand_s_own():
    row = rr.ReferenceRow.from_payload({**next(r for r in PAYLOADS['after']['prices'] if r['retailer_domain'] == 'pampers.com'),
                                        'role': 'retailer'})
    assert not rr.brand_sets_no_price(row)
