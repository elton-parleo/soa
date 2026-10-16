"""
2E: source_split (own domain / listed retailer / other, a report field on
every tier's outcome) reads the tenant-wide own-domain set 2D gave the
brand-direct classifier. Before, a catalog answer citing the tenant's other
site (W&S: wiggleandsnug.com on the store's trueshopstore.com cycle) split
it as `other`. No outcome moves: the split is not an input to any verdict.
"""
from types import SimpleNamespace

from scoring import expectation_comparator as cmp
from scoring import expectation_scorer as es
from soa_shared import expected_answers as ea

STORE_REF = {
    'merchant_slug': 'wiggle-and-snug', 'variant_id': '00850000000011', 'gtin': '00850000000011',
    'own_domain': 'trueshopstore.com', 'merchant_kind': 'seller', 'retailer_list': ['target.com'],
}
TENANT = ['trueshopstore.com', 'wiggleandsnug.com']


def extraction(**overrides):
    base = {'prices': [{'amount': '22.99', 'currency': None, 'attributed_product': None}], 'codes': [],
            'pack_counts': [], 'gtins': [], 'member_prices': [], 'points': [], 'brand_mentioned': True,
            'sources_cited': ['wiggleandsnug.com', 'target.com', 'babylist.com'],
            'extraction_confident': True, 'extraction_note': None}
    base.update(overrides)
    return base


def _compare(facts):
    return cmp.compare(ea.price('22.99'), extraction(), source_ref=STORE_REF, tier='catalog_accuracy',
                       brand_facts=facts)


def test_the_tenants_other_site_is_own_in_the_split():
    verdict = _compare({'tenant_own_domains': TENANT})
    assert verdict.source_split == {'own_domain': ['wiggleandsnug.com'], 'listed_retailer': ['target.com'],
                                    'other': ['babylist.com']}


def test_before_2e_it_was_other_and_no_outcome_moves():
    before, after = _compare({}), _compare({'tenant_own_domains': TENANT})
    assert before.source_split['other'] == ['wiggleandsnug.com', 'babylist.com']
    assert (before.outcome, before.reason, before.reason_code, before.flags) == \
        (after.outcome, after.reason, after.reason_code, after.flags)


class _Tenant:
    def __init__(self, domains=None, refuse=False):
        self.domains, self.refuse = domains or TENANT, refuse

    def for_cycle(self, cycle_id, study_type=None):
        if self.refuse:
            from clients.truesync_catalog import TrueSyncNotAuthorized
            raise TrueSyncNotAuthorized('refused')
        return list(self.domains)


def _run():
    return SimpleNamespace(source_ref={**STORE_REF}, study_type='ws', tier='catalog_accuracy', cycle_id=229,
                           answer_status='answered', retrieved_sources=None, grounding=None)


def test_classify_puts_the_tenant_set_on_every_tier():
    verdict = es.classify(_run(), ea.price('22.99'), extraction(), tenant_domains=_Tenant())
    assert verdict.source_split['own_domain'] == ['wiggleandsnug.com']


def test_off_the_brand_direct_tier_a_refused_tenant_read_degrades_to_the_merchants_own():
    verdict = es.classify(_run(), ea.price('22.99'), extraction(), tenant_domains=_Tenant(refuse=True))
    assert verdict.source_split['own_domain'] == []
    assert verdict.source_split['other'] == ['wiggleandsnug.com', 'babylist.com']
