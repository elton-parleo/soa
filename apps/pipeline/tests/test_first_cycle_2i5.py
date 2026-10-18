"""
2I-5: the full loop runs a study's first cycle (soa_shared.comparison_sets).

On production (Oct 16, 8:44 PM) Wiggle & Snug Brand's first full loop read
its pages and then failed with no cycle: the coordinator took the comparison
set only from the study's latest cycle, and a study that has never run has
none. Now: the latest cycle's set, else the study's merchant (M001) and its
comparison_domains from supply (M002 on), entities created where missing.

Production's schema (soa_pg_harness.model_schema), on sqlite and on a local
Postgres. Supply's reads go through the real TrueSyncCatalogClient with
httpx.get answering from the recorded payloads
(tests/fixtures/first_cycle/supply_ws_brand_2i5.json: the 2H /tenant and the
brand's /retailers with and without a competitor list). The full-loop POST
and PATCH are test_full_loop_coordinator.py's FakeSupply.
"""
import json
import os

import httpx
import pytest
from sqlalchemy import text

import clients.truesync_catalog as catalog_module
from clients.truesync_catalog import TrueSyncCatalogClient
from fullloop.coordinator import Coordinator
from soa_pg_harness import model_schema
from soa_shared.comparison_sets import comparison_set_for_study
from tests.test_full_loop_coordinator import NOW, FakeSupply

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, 'fixtures', 'first_cycle', 'supply_ws_brand_2i5.json')) as fh:
    SUPPLY = json.load(fh)
BRAND, STORE = 'wiggle-and-snug-brand', 'wiggle-and-snug'
STUDY, STORE_STUDY = 'ws_brand_smoke_test_1a2b3c', 'ws-2b-fixture'


@pytest.fixture
def db(any_engine):
    model_schema(any_engine)
    with any_engine.begin() as c:
        c.execute(text("INSERT INTO organizations (id, name) VALUES (1, 'Parleo'), (10, 'Wiggle & Snug')"))
        for st in (STUDY, STORE_STUDY):
            c.execute(text("INSERT INTO soa_queries (query_code, query_text, study_type, study_pattern, category, stage, "
                           "specificity, persona, status, organization_id) VALUES (:code, 'Best diapers?', :st, "
                           "'brand_at_retail', 'Baby Care', 'Awareness', 'Broad', 'Casual / Gift Buyer', 'Active', 1)"),
                      {'code': f'{st[:8]}-Q1', 'st': st})
        # the smoke test as #120 records it: no brand box, the merchant in tier_config
        c.execute(text("INSERT INTO soa_query_generation_jobs (study_type, study_name, target_count, created_count, status, organization_id, "
                       "customer_organization_id, tier_config) VALUES (:st, 'W&S Brand smoke test', 5, 5, 'complete', 1, 10, :t)"),
                  {'st': STUDY, 't': json.dumps({'merchant': {'slug': BRAND}})})
    return any_engine


@pytest.fixture
def reads(monkeypatch):
    """httpx.get as supply answers it; `listed` picks the /retailers payload."""
    state = {'listed': 'none', 'calls': []}

    def get(url, params=None, timeout=None, headers=None):
        path = httpx.URL(url).path
        state['calls'].append(path)
        if path == '/api/truesync/tenant':
            return httpx.Response(200, json=SUPPLY['tenant'])
        if path == f'/api/truesync/merchants/{BRAND}/retailers':
            return httpx.Response(200, json=SUPPLY[state['listed']])
        return httpx.Response(404, json={'detail': 'no fixture'})
    monkeypatch.setattr(catalog_module.httpx, 'get', get)
    return state


def coordinator(db, supply):
    return Coordinator(engine=db, client_for=supply.client, clock=lambda: NOW,
                       catalog_for=lambda _org: TrueSyncCatalogClient(base_url='https://supply.example', token='tst_org'))


def loop(db, study=STUDY, merchant=BRAND, run=33):
    with db.begin() as c:
        return c.execute(text("""INSERT INTO soa_full_loop_requests (organization_id, merchant_slug, study_type, platforms,
            runs_per_query, supply_run_id, supply_status, status, created_by)
            VALUES (10, :m, :st, :p, 1, :r, 'reference_done', 'reference_done', 'op') RETURNING id"""),
                         {'m': merchant, 'st': study, 'p': json.dumps(['chatgpt']), 'r': run}).scalar()


def cycle_set(db, cycle_id):
    with db.connect() as c:
        return [tuple(r) for r in c.execute(text(
            "SELECT e.slug, e.name, ce.comparison_code, ce.role FROM soa_cycle_entities ce "
            "JOIN soa_entities e ON e.id = ce.entity_id WHERE ce.cycle_id = :c ORDER BY ce.comparison_code"),
            {'c': cycle_id})]


def entity(db, slug):
    with db.connect() as c:
        row = dict(c.execute(text("SELECT name, slug, entity_type, website_url, aliases FROM soa_entities WHERE slug = :s"),
                             {'s': slug}).mappings().one())
    row['aliases'] = json.loads(row['aliases']) if isinstance(row['aliases'], str) else row['aliases']
    return row


# ═══ the Oct 16 case: a first cycle, no competitor list ══════════════════

def test_a_first_cycle_with_no_competitor_list_is_the_brand_alone(db, reads):
    co = coordinator(db, FakeSupply('reference_done'))
    rid = loop(db)
    co.tick()
    row = co.get(rid)
    assert (row['status'], row['error']) == ('cycle_planned', None)
    assert cycle_set(db, row['cycle_id']) == [(BRAND, 'Wiggle & Snug Brand', 'M001', 'primary')]
    # created from supply's /tenant record: its name, its own domain as alias and website
    assert entity(db, BRAND) == {'name': 'Wiggle & Snug Brand', 'slug': BRAND, 'entity_type': 'brand',
                                 'website_url': 'https://wiggleandsnug.com/', 'aliases': ['wiggleandsnug.com']}
    assert reads['calls'] == ['/api/truesync/tenant', f'/api/truesync/merchants/{BRAND}/retailers']


def test_a_competitor_list_is_tracked_in_its_order_an_existing_entity_matched_by_domain(db, reads):
    reads['listed'] = 'two'
    with db.begin() as c:   # Pampers is already in the registry, under its site
        c.execute(text("INSERT INTO soa_entities (name, slug, entity_type, website_url) "
                       "VALUES ('Pampers', 'pampers', 'brand', 'https://www.pampers.com/')"))
    co = coordinator(db, FakeSupply('reference_done'))
    rid = loop(db)
    co.tick()
    row = co.get(rid)
    assert row['status'] == 'cycle_planned'
    assert cycle_set(db, row['cycle_id']) == [(BRAND, 'Wiggle & Snug Brand', 'M001', 'primary'),
                                              ('pampers', 'Pampers', 'M002', 'competitor'),
                                              ('huggies-com', 'huggies.com', 'M003', 'competitor')]
    # a rival not in the registry is created named by its domain until the wizard (2I-6) names it
    assert entity(db, 'huggies-com') == {'name': 'huggies.com', 'slug': 'huggies-com', 'entity_type': 'brand',
                                         'website_url': 'https://huggies.com/', 'aliases': ['huggies.com']}


def test_the_second_cycle_copies_the_first_and_a_removed_domain_stays(db, reads):
    """2I-6: a later cycle reads the list to add to the copy; an emptied list removes nothing."""
    reads['listed'] = 'two'
    co = coordinator(db, FakeSupply('reference_done'))
    first = co.get((lambda r: (co.tick(), r)[1])(loop(db)))['cycle_id']
    with db.begin() as c:
        c.execute(text("UPDATE soa_full_loop_requests SET status = 'scored'"))
        c.execute(text("UPDATE soa_cycles SET status = 'complete', start_date = '2026-10-16'"))
    reads['listed'], reads['calls'] = 'none', []          # the list emptied on supply: the set keeps its rivals
    rid = loop(db, run=34)
    co.tick()
    second = co.get(rid)['cycle_id']
    assert second != first and cycle_set(db, second) == cycle_set(db, first)
    assert len(cycle_set(db, second)) == 3 and reads['calls'] == [f'/api/truesync/merchants/{BRAND}/retailers']


# ═══ a study with a cycle: today's set ═══════════════════════════════════

def test_a_study_with_a_prior_cycle_gets_todays_set_and_no_supply_read(db, reads):
    with db.begin() as c:
        for i, (name, slug) in enumerate((('Wiggle & Snug', STORE), ('Pampers', 'pampers'), ('Huggies', 'huggies')), start=7):
            c.execute(text("INSERT INTO soa_entities (id, name, slug, entity_type) VALUES (:i, :n, :s, 'brand')"),
                      {'i': i, 'n': name, 's': slug})
        c.execute(text("INSERT INTO soa_cycles (id, cycle_code, study_type, study_pattern, status, cycle_mode, start_date, "
                       "organization_id) VALUES (229, 'WS-2B-FIXTURE', :st, 'brand_at_retail', 'complete', 'query', "
                       "'2026-09-29', 1)"), {'st': STORE_STUDY})
        for eid, code, role in ((7, 'M001', 'primary'), (9, 'M003', 'competitor'), (8, 'M002', 'competitor')):
            c.execute(text("INSERT INTO soa_cycle_entities (cycle_id, entity_id, comparison_code, role) "
                           "VALUES (229, :e, :c, :r)"), {'e': eid, 'c': code, 'r': role})
    with db.begin() as c:
        got = comparison_set_for_study(c, STORE_STUDY, 10, supply=None)
    # exactly what the coordinator's _comparison_set returned before 2I-5: the rows by comparison code
    assert got == [{'entity_id': 7, 'comparison_code': 'M001', 'role': 'primary'},
                   {'entity_id': 8, 'comparison_code': 'M002', 'role': 'competitor'},
                   {'entity_id': 9, 'comparison_code': 'M003', 'role': 'competitor'}]
    co = coordinator(db, FakeSupply('reference_done'))
    rid = loop(db, study=STORE_STUDY, merchant=STORE)
    co.tick()
    assert [c[2:] for c in cycle_set(db, co.get(rid)['cycle_id'])] == [('M001', 'primary'), ('M002', 'competitor'),
                                                                       ('M003', 'competitor')]
    assert reads['calls'] == []


# ═══ the failures ════════════════════════════════════════════════════════

def test_a_study_with_no_merchant_fails_saying_so(db, reads):
    """The pre-#120 lost study: a job with no customer org, so not this org's study."""
    with db.begin() as c:
        c.execute(text("UPDATE soa_query_generation_jobs SET customer_organization_id = NULL, tier_config = NULL"))
    co = coordinator(db, FakeSupply('reference_done'))
    rid = loop(db)
    co.tick()
    assert (co.get(rid)['status'], co.get(rid)['error']) == (
        'failed', 'could not create the cycle: the study belongs to no merchant')
    assert reads['calls'] == []


def test_supply_unreadable_on_a_first_cycle_fails_with_the_read_and_creates_nothing_to_copy(db, reads, monkeypatch):
    monkeypatch.setattr(catalog_module.httpx, 'get', lambda *a, **k: httpx.Response(502, text='supply down'))
    co = coordinator(db, FakeSupply('reference_done'))
    rid = loop(db)
    co.tick()
    row = co.get(rid)
    assert row['status'] == 'failed' and row['cycle_id'] is None
    assert row['error'] == "could not create the cycle: could not read 'wiggle-and-snug-brand''s merchant record from TrueSync: supply down"
