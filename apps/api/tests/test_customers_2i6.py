"""
2I-6 B1: competitors to track, entered once per merchant as name + domain.

One save (PUT /api/customers/{org}/merchants/{slug}/competitors) writes
supply's comparison_domains first (PUT /merchants/{slug}/comparison-domains,
2A-4), then one soa_entities row per competitor; the read-back joins supply's
list to soa's entity names. Then the comparison-set rule (soa_shared.
comparison_sets) tracks them: a first cycle as M002 onward, a later cycle
adding a newly saved one after the previous cycle's rivals.

Supply answers with the recorded payloads: the 2H /tenant and the brand's
/retailers (apps/pipeline/tests/fixtures/first_cycle/supply_ws_brand_2i5.json),
and supply's own answers to the PUT (its _retailers_view; 409 and 422 in its
words, truesync/tenancy.py set_comparison_domains on parleo-supply-app main
f240746). The fake keeps no state: after a PUT a test answers the next GET
with what supply would now serve. On sqlite and on a local Postgres.
"""
import pytest
from sqlalchemy import text

import app.routers.customers as customers_router
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2i5 import BRAND, STUDY, SUPPLY, first  # noqa: F401  (fixture)
from tests.test_console_read_models import TOKEN_A, as_, http, upstream  # noqa: F401  (fixtures)

PATH = f'/api/customers/10/merchants/{BRAND}/competitors'
SUPPLY_PUT = f'/api/truesync/merchants/{BRAND}/comparison-domains'
SUPPLY_GET = f'/api/truesync/merchants/{BRAND}/retailers'
PAMPERS, HUGGIES = {'name': 'Pampers', 'domain': 'pampers.com'}, {'name': 'Huggies', 'domain': 'huggies.com'}


@pytest.fixture
def saving(first, upstream, monkeypatch):
    monkeypatch.setattr(customers_router, 'engine', first)
    return first


def supply_holds(upstream, domains):
    """What supply serves after a PUT of `domains` (its _retailers_view)."""
    view = {**SUPPLY['none'], 'comparison_domains': list(domains)}
    upstream.answer('PUT', SUPPLY_PUT, body=view, token=TOKEN_A)
    upstream.answer('GET', SUPPLY_GET, body=view, token=TOKEN_A)
    return view


def entities(db):
    with db.connect() as c:
        return {r[0]: tuple(r[1:]) for r in c.execute(text("SELECT slug, name, website_url FROM soa_entities"))}


def save(http, rows):
    as_('op')
    return http.put(PATH, json={'competitors': rows})


# ═══ the validator ═══════════════════════════════════════════════════════

@pytest.mark.parametrize('domain', ['https://pampers.com', 'www.pampers.com', 'Pampers.com', 'pampers', 'pampers.com/diapers'])
def test_a_domain_that_is_not_a_bare_hostname_is_422_and_nothing_is_written(http, saving, upstream, domain):
    before = entities(saving)
    r = save(http, [{'name': 'Pampers', 'domain': domain}])
    assert r.status_code == 422 and r.json()['detail']['code'] == 'invalid'
    assert not any(c['method'] == 'PUT' for c in upstream.calls) and entities(saving) == before


def test_a_repeated_domain_is_422(http, saving, upstream):
    r = save(http, [PAMPERS, {'name': 'Pampers again', 'domain': 'pampers.com'}])
    assert r.status_code == 422 and "listed more than once: 'pampers.com'" in r.json()['detail']['message']


def test_supply_refusing_an_own_or_retailer_domain_is_its_409_and_leaves_the_entities(http, saving, upstream):
    upstream.answer('PUT', SUPPLY_PUT, status=409, token=TOKEN_A, body={
        'detail': "already one of this merchant's own or retailer domains: trueshopstore.com (retailer)"})
    before = entities(saving)
    r = save(http, [PAMPERS, {'name': 'Our store', 'domain': 'trueshopstore.com'}])
    assert r.status_code == 409
    detail = r.json()['detail']
    assert detail['code'] == 'supply_refused' and detail['message'].startswith('TrueSync refused the competitor list, so nothing was saved')
    assert 'trueshopstore.com (retailer)' in detail['message']
    assert entities(saving) == before


# ═══ the save: supply, then the entities ═════════════════════════════════

def test_a_save_writes_supply_then_matches_renames_and_creates_entities(http, saving, upstream):
    with saving.begin() as c:   # pampers.com as 2I-5 creates a rival (named by its domain); luvs.com under an alias
        c.execute(text("INSERT INTO soa_entities (name, slug, entity_type, website_url, aliases) VALUES "
                       "('pampers.com', 'pampers-com', 'brand', 'https://pampers.com/', '[\"pampers.com\"]'), "
                       "('Luvs Diapers', 'luvs', 'brand', NULL, '[\"luvs.com\"]')"))
    supply_holds(upstream, ['pampers.com', 'huggies.com', 'luvs.com', 'hellobello.com'])
    r = save(http, [PAMPERS, HUGGIES, {'name': 'Luvs', 'domain': 'luvs.com'}, {'name': 'Hello Bello', 'domain': 'hellobello.com'}])
    assert r.status_code == 200, r.text
    puts = [c for c in upstream.calls if c['method'] == 'PUT']
    assert [(c['path'], c['json'], c['token']) for c in puts] == [
        (SUPPLY_PUT, {'domains': ['pampers.com', 'huggies.com', 'luvs.com', 'hellobello.com']}, TOKEN_A)]
    assert [(s['domain'], s['action']) for s in r.json()['saved']] == [
        ('pampers.com', 'renamed'),    # named by its domain (2I-5): given the name
        ('huggies.com', 'matched'),    # the seeded Huggies, by its website
        ('luvs.com', 'matched'),       # by its alias; a real name is kept
        ('hellobello.com', 'created')]
    ents = entities(saving)
    assert ents['pampers-com'] == ('Pampers', 'https://pampers.com/')
    assert ents['luvs'][0] == 'Luvs Diapers'
    assert ents['hello-bello'] == ('Hello Bello', 'https://hellobello.com/')
    assert [(c['domain'], c['name']) for c in r.json()['competitors']] == [
        ('pampers.com', 'Pampers'), ('huggies.com', 'Huggies'), ('luvs.com', 'Luvs Diapers'), ('hellobello.com', 'Hello Bello')]


def test_removing_a_competitor_removes_the_domain_from_supply_and_keeps_the_entity(http, saving, upstream):
    supply_holds(upstream, ['pampers.com', 'huggies.com'])
    assert save(http, [PAMPERS, HUGGIES]).status_code == 200
    supply_holds(upstream, ['huggies.com'])
    r = save(http, [HUGGIES])
    assert [c['json'] for c in upstream.calls if c['method'] == 'PUT'][-1] == {'domains': ['huggies.com']}
    assert [c['domain'] for c in r.json()['competitors']] == ['huggies.com']
    assert entities(saving)['pampers'][0] == 'Pampers'


# ═══ the read-back ═══════════════════════════════════════════════════════

def test_the_read_back_is_supplys_list_joined_to_entity_names_no_entity_yet_shown(http, saving, upstream):
    supply_holds(upstream, ['huggies.com', 'kirkland.com'])   # kirkland.com entered on supply directly
    as_('op')
    r = http.get(PATH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['own_domains'] == ['wiggleandsnug.com'] and body['retailer_domains'] == ['trueshopstore.com']
    assert [(c['domain'], c['name']) for c in body['competitors']] == [('huggies.com', 'Huggies'), ('kirkland.com', None)]


def test_members_cannot_read_or_save_competitors(http, saving, upstream):
    as_('alice')
    assert http.get(PATH).status_code == 403
    assert http.put(PATH, json={'competitors': [PAMPERS]}).status_code == 403
    assert upstream.calls == []


# ═══ the comparison sets they make ═══════════════════════════════════════

def cycle_set(db, code):
    with db.connect() as c:
        return [tuple(x) for x in c.execute(text(
            "SELECT e.name, ce.comparison_code, ce.role FROM soa_cycle_entities ce JOIN soa_cycles cy ON cy.id = ce.cycle_id "
            "JOIN soa_entities e ON e.id = ce.entity_id WHERE cy.cycle_code = :c ORDER BY ce.comparison_code"), {'c': code})]


def test_after_saving_pampers_and_huggies_the_brands_first_cycle_tracks_them_and_a_later_one_adds_a_new_save(http, saving, upstream):
    supply_holds(upstream, ['pampers.com', 'huggies.com'])
    assert save(http, [PAMPERS, HUGGIES]).status_code == 200
    as_('op')
    assert http.post('/api/console/cycles', params={'org': 10}, json={
        'study_type': STUDY, 'platforms': ['chatgpt'], 'cycle_code': 'WSB-1'}).status_code == 201
    assert cycle_set(saving, 'WSB-1') == [('Wiggle & Snug Brand', 'M001', 'primary'), ('Pampers', 'M002', 'competitor'),
                                          ('Huggies', 'M003', 'competitor')]
    supply_holds(upstream, ['pampers.com', 'huggies.com', 'hellobello.com'])
    assert save(http, [PAMPERS, HUGGIES, {'name': 'Hello Bello', 'domain': 'hellobello.com'}]).status_code == 200
    as_('op')
    assert http.post('/api/console/cycles', params={'org': 10}, json={
        'study_type': STUDY, 'platforms': ['chatgpt'], 'cycle_code': 'WSB-2'}).status_code == 201
    assert cycle_set(saving, 'WSB-2') == cycle_set(saving, 'WSB-1') + [('Hello Bello', 'M004', 'competitor')]
