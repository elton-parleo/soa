"""
2D: the brand's own domains are one set across the tenant.

soa #104 grounds a brand-direct answer on the merchant's own domains, read
from supply's /merchants/{slug}/retailers. Wiggle & Snug's store
(trueshopstore.com) and its brand site (wiggleandsnug.com) are two supply
merchants, so the store's list holds only the store, and cycle 229 run
12979, which cited wiggleandsnug.com, scored `echoed` on the store's cycle.
The grounded checks now read every own domain of every merchant in the
tenant (TrueSyncCatalogClient.tenant_own_domains, once per cycle).

Every ownership check reads the tenant set: the ownership claim, the
no-source check, and the two grounded checks.

The last tests are `rescore_cycle.py --classify-only --dry-run` on a
229-shaped brand-direct fixture: the six golden rows r40-r45 (229's Gemini
answers, as stored, with their grounding) and two ChatGPT rows, under the
store's record as supply serves it today. Exactly two rows move: 12979
echoed -> grounded (it cited wiggleandsnug.com) and 12975 fabricated ->
grounded (its claim's support is at wiggleandsnug.com). sqlite and Postgres.
"""
import json
import os
from datetime import date

import pytest
from sqlalchemy import text

from clients.truesync_catalog import TrueSyncCatalogClient
from scoring import brand_direct_classifier as bdc
from scoring import expectation_scorer as scorer_module
from scripts import rescore_cycle as rc
from soa_pg_harness import model_schema
from soa_shared import expected_answers as ea
from soa_shared.models.soa_models import Base

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')
CYCLE = 'FL3-wiggle-and-snug-20261014'
WS_BRAND = ea.brand_mention('Wiggle & Snug', 'trueshopstore.com')

#: GET /tenant: the store and the brand, two merchants of one tenant
TENANT = {'merchants': [
    {'slug': 'wiggle-and-snug', 'name': 'Wiggle & Snug', 'domain': 'trueshopstore.com',
     'kind': 'seller', 'hosting': 'hosted', 'has_record': True},
    {'slug': 'wiggle-and-snug-brand', 'name': 'Wiggle & Snug (brand site)', 'domain': 'wiggleandsnug.com',
     'kind': 'brand', 'hosting': 'hosted', 'has_record': False}]}
#: GET /merchants/{slug}/retailers: the store answers with the deprecated
#: single field, the brand with the supply #20 list
RETAILERS = {
    'wiggle-and-snug': {'merchant': 'wiggle-and-snug', 'own_domain': 'trueshopstore.com', 'domains': []},
    'wiggle-and-snug-brand': {'merchant': 'wiggle-and-snug-brand', 'own_domain': 'wiggleandsnug.com',
                              'own_domains': ['https://www.WiggleAndSnug.com/', 'wiggleandsnug.com'],
                              'domains': []},
}


def _json(*parts):
    with open(os.path.join(FIXTURES, *parts)) as fh:
        return json.load(fh)


class Supply(TrueSyncCatalogClient):
    """The real client over recorded payloads: no network. `down` makes a
    path's read fail the way an outage does."""

    def __init__(self, down=()):
        super().__init__(base_url='https://supply.example', token='t')
        self.down = set(down)
        self.calls = []
        ws = _json('wiggle_and_snug_catalog.json')
        self.paths = {
            '/api/truesync/tenant': TENANT,
            '/api/truesync/merchants': ws['merchants'],
            '/api/truesync/merchants/wiggle-and-snug/catalog': ws['catalog'],
            '/api/truesync/merchants/wiggle-and-snug/incentives': ws['incentives'],
            '/api/truesync/merchants/wiggle-and-snug/price-history': ws['price_history'],
            **{f'/api/truesync/merchants/{slug}/retailers': body for slug, body in RETAILERS.items()},
        }

    def _get(self, path, params=None):
        self.calls.append(path)
        if path in self.down:
            return None, 'upstream returned 503'
        if path not in self.paths:
            return None, f'no TrueSync merchant at {path}'
        return self.paths[path], None


# ═══ the read ═════════════════════════════════════════════════════════════

def test_the_tenant_s_own_domains_are_every_merchant_s_list_or_its_single_field():
    domains, error = Supply().tenant_own_domains()
    assert (domains, error) == (['trueshopstore.com', 'wiggleandsnug.com'], None)


def test_a_merchant_whose_read_fails_is_left_out_and_named():
    domains, error = Supply(down={'/api/truesync/merchants/wiggle-and-snug-brand/retailers'}).tenant_own_domains()
    assert domains == ['trueshopstore.com'] and error == 'wiggle-and-snug-brand: upstream returned 503'


def test_read_once_per_cycle_and_degraded_to_the_merchant_s_own_on_an_outage():
    supply = Supply()
    cache = scorer_module.TenantDomainsCache(supply)
    assert cache.for_cycle(229) == cache.for_cycle(229) == ['trueshopstore.com', 'wiggleandsnug.com']
    assert supply.calls.count('/api/truesync/tenant') == 1
    assert scorer_module.TenantDomainsCache(Supply(down={'/api/truesync/tenant'})).for_cycle(229) == []


# ═══ the rule ═════════════════════════════════════════════════════════════

STORE_FACTS = {'brand': 'Wiggle & Snug', 'domain': 'trueshopstore.com', 'own_domains': ['trueshopstore.com'],
               'retailer_list': [], 'tier_names': ['Member', 'Member+'], 'program_name': 'Member Rewards'}
TENANT_FACTS = {**STORE_FACTS, 'tenant_own_domains': ['trueshopstore.com', 'wiggleandsnug.com']}


def _golden(rid):
    return _json('verdict_golden', f'{rid}.json')


def test_run_12979_cited_the_brand_site_and_is_grounded_on_the_tenant_s_domains():
    row = _golden('r43')
    assert bdc.classify_with_code(row['extraction'], WS_BRAND, brand_facts=STORE_FACTS)[0] == 'echoed'
    assert bdc.classify_with_code(row['extraction'], WS_BRAND, brand_facts=TENANT_FACTS) == (
        'grounded', 'cited wiggleandsnug.com, an own domain of another merchant in the tenant', 'tenant_own_domains')


def test_a_merchant_whose_own_record_lists_the_site_keeps_its_own_domains_code():
    """Golden r43's record facts list both domains on the store's own record:
    the merchant's rule decides, and the tenant set changes nothing."""
    row = _golden('r43')
    facts = {**row['record_facts'], 'tenant_own_domains': ['trueshopstore.com', 'wiggleandsnug.com']}
    assert bdc.classify_with_code(row['extraction'], WS_BRAND, brand_facts=facts)[::2] == ('grounded', 'own_domains')


def test_run_12975_s_claim_is_sourced_by_a_support_at_the_tenant_s_other_site():
    """Its only backing is a Gemini support at wiggleandsnug.com and it
    cites nothing. On the store's own list the no-source check called that
    fabricated; on the tenant's it is sourced, and the support grounds it."""
    r40 = _golden('r40')
    assert bdc.classify(r40['extraction'], WS_BRAND, brand_facts=STORE_FACTS, grounding=r40['grounding'])[0] == 'fabricated'
    assert bdc.classify_with_code(r40['extraction'], WS_BRAND, brand_facts=TENANT_FACTS, grounding=r40['grounding'])[::2] == (
        'grounded', 'tenant_own_domains')


def test_an_ownership_claim_naming_the_tenant_s_other_site_is_not_contradicted():
    r40 = _golden('r40')
    claim = {'claim': 'Their official website is wiggleandsnug.com.', 'claim_kind': 'ownership', 'kind': 'assertion',
             'modality': 'asserted', 'effective_modality': 'asserted'}
    ownership = {**r40['extraction'], 'brand_claims': [claim], 'sources_cited': ['trueshopstore.com']}
    assert bdc.classify(ownership, WS_BRAND, brand_facts=STORE_FACTS)[0] == 'fabricated'
    assert bdc.classify(ownership, WS_BRAND, brand_facts=TENANT_FACTS)[0] == 'grounded'
    elsewhere = {**ownership, 'brand_claims': [{**claim, 'claim': 'Their official website is snugbrand.com.'}]}
    assert bdc.classify(elsewhere, WS_BRAND, brand_facts=TENANT_FACTS)[0] == 'fabricated'


def test_a_support_at_the_tenant_s_other_site_grounds_a_cited_answer():
    """Cited something that is not ours, and a claim backed by a support at
    the brand site: grounded by the support, which the tenant set allows."""
    r40 = _golden('r40')
    extraction = {**r40['extraction'], 'sources_cited': ['reddit.com']}
    assert bdc.classify_with_code(extraction, WS_BRAND, brand_facts=STORE_FACTS, grounding=r40['grounding'])[0] == 'echoed'
    assert bdc.classify_with_code(extraction, WS_BRAND, brand_facts=TENANT_FACTS, grounding=r40['grounding'])[::2] == (
        'grounded', 'tenant_own_domains')
    retailer = {**r40['grounding'], 'sources': [{**r40['grounding']['sources'][0], 'domain': 'trueshopstore.com',
                                                 'title': 'trueshopstore.com'}]}
    assert bdc.classify_with_code(extraction, WS_BRAND, brand_facts=TENANT_FACTS, grounding=retailer)[::2] == (
        'grounded', 'grounding_support')            # the merchant's own site: #104's code, as before


# ═══ the rescore, on the 229-shaped fixture ═══════════════════════════════

# (run id, golden row or None, platform, run number, extraction override, the
#  outcome production stores under the store-only record)
FIXTURE_ROWS = [
    (12975, 'r40', 'gemini_grounded', 1, None, 'fabricated'),
    (12976, 'r41', 'gemini_grounded', 2, None, 'fabricated'),
    (12977, 'r42', 'gemini_grounded', 3, None, 'fabricated'),
    (12979, 'r43', 'gemini_grounded', 1, None, 'echoed'),
    (12972, 'r44', 'gemini_grounded', 2, None, 'grounded'),
    (12973, 'r45', 'gemini_grounded', 3, None, 'fabricated'),
    (12980, None, 'chatgpt', 1, {'sources_cited': ['trueshopstore.com']}, 'grounded'),
    (12981, None, 'chatgpt', 2, {'brand_unknown_statement': 'I could not find a brand called Wiggle & Snug.'},
     'acknowledged_unknown'),
]


def _row(golden, override):
    if golden:
        g = _golden(golden)
        return g['extraction'], g.get('grounding')
    base = {**_golden('r43')['extraction'], 'sources_cited': [], 'brand_claims': [], **override}
    return base, None


@pytest.fixture
def cycle_229(any_engine, monkeypatch):
    model_schema(any_engine)
    t = Base.metadata.tables
    with any_engine.begin() as c:
        c.execute(t['organizations'].insert(), [{'id': 10, 'name': 'Wiggle & Snug'}])
        c.execute(t['soa_cycles'].insert(), [{
            'id': 229, 'cycle_code': CYCLE, 'start_date': date(2026, 10, 14), 'status': 'complete',
            'study_type': 'ws', 'study_pattern': 'retailer', 'cycle_mode': 'query', 'organization_id': 10,
            'platforms': ['chatgpt', 'gemini']}])
        for n, (run_id, golden, platform, number, override, outcome) in enumerate(FIXTURE_ROWS, start=1):
            extraction, grounding = _row(golden, override)
            c.execute(t['soa_queries'].insert(), [{
                'id': n, 'query_code': f'WIG_{140 + n}', 'query_text': 'Is Wiggle & Snug Bum Balm still sold?',
                'category': 'Cross-Category', 'stage': 'Research', 'specificity': 'Narrow',
                'persona': 'New / First-Time Parent', 'status': 'Active', 'study_type': 'ws',
                'study_pattern': 'retailer', 'organization_id': 10, 'tier': 'brand_direct',
                'expected_answer': WS_BRAND, 'source_ref': {'merchant_slug': 'wiggle-and-snug'}}])
            c.execute(t['soa_runs'].insert(), [{
                'id': run_id, 'cycle_id': 229, 'query_id': n, 'platform': platform, 'run_number': number,
                'raw_response': 'answer', 'status': 'success', 'surface': 'grounded_api',
                'answer_status': 'answered', 'grounding': grounding}])
            c.execute(t['soa_expectation_outcomes'].insert(), [{
                'run_id': run_id, 'query_id': n, 'cycle_id': 229, 'platform': platform, 'tier': 'brand_direct',
                'expected_answer': WS_BRAND, 'extraction': extraction, 'outcome': outcome,
                'extraction_model': 'gpt-x', 'surface': 'grounded_api'}])
    monkeypatch.setattr(rc, 'engine', any_engine)
    monkeypatch.setattr(scorer_module, 'engine', any_engine)
    monkeypatch.setattr(TrueSyncCatalogClient, 'for_study', classmethod(lambda cls, study_type, **kw: Supply()))
    return any_engine


def _outcomes(db):
    with db.connect() as c:
        return dict(c.execute(text("SELECT run_id, outcome FROM soa_expectation_outcomes ORDER BY run_id")).all())


def test_the_fixture_s_stored_outcomes_are_what_the_store_only_record_gives(cycle_229):
    """So the dry run starts from what production holds, not from a guess."""
    for run_id, golden, _p, _n, override, outcome in FIXTURE_ROWS:
        extraction, grounding = _row(golden, override)
        assert bdc.classify(extraction, WS_BRAND, brand_facts=STORE_FACTS, grounding=grounding)[0] == outcome, run_id


def test_the_dry_run_moves_12979_and_12975_to_grounded_and_writes_nothing(cycle_229, capsys):
    before = _outcomes(cycle_229)
    assert rc.main(['--cycle', CYCLE, '--classify-only', '--dry-run']) == 0
    out = capsys.readouterr().out
    rule = 'brand-direct: every own domain of every merchant in the tenant is ours (2D)'
    assert 'rows whose outcome moved: 2 of 8' in out
    assert f'WIG_141 · gemini_grounded · run 1: fabricated -> grounded   [{rule}]   [run 12975]' in out
    assert f'WIG_144 · gemini_grounded · run 1: echoed -> grounded   [{rule}]   [run 12979]' in out
    assert 'unattributed moves: 0' in out and 'dry run — nothing written.' in out
    assert _outcomes(cycle_229) == before


def test_the_write_moves_only_12979_and_12975(cycle_229, capsys):
    before = _outcomes(cycle_229)
    assert rc.main(['--cycle', CYCLE, '--classify-only']) == 0
    after = _outcomes(cycle_229)
    assert {r: (before[r], after[r]) for r in before if before[r] != after[r]} == {
        12975: ('fabricated', 'grounded'), 12979: ('echoed', 'grounded')}
    fabricated = lambda o: sum(v == 'fabricated' for v in o.values())
    assert (fabricated(before), fabricated(after)) == (4, 3)      # r41 huggies.com, r42 unresolved, r45 invented tiers
    with cycle_229.connect() as c:
        codes = dict(c.execute(text("SELECT run_id, reason_code FROM soa_expectation_outcomes "
                                    "WHERE run_id IN (12975, 12979)")).all())
    assert codes == {12975: 'tenant_own_domains', 12979: 'tenant_own_domains'}
