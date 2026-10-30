"""
2V-6: retail leftovers after 2V-5, and the full loop's study.

On 2V-4's recording (tests/fixtures/console/supply_2v4/PROVENANCE.md: supply
`main` at 13c9c80, five owned entries) served through 2V-2's harness. Live
Petco has eight owned entries; the two the recording lacks that this pass is
about are written here, said so where they are: a second Perks tier
("Premier Small Pet", no former names) and the per-dollar points entry
(`points_multiplier` 10, every SKU). The value-tier rows of cycle 3's one
per-dollar question are written here too, six agents, in the scorer's shape
(soa_expectation_outcomes: outcome, expected_answer, platform, surface).
"""
import copy
import json
import os

from sqlalchemy import text

from app.routers import console as console_router
from app.services import console_seller as cs
from tests import test_console_2v2_seller as t2v2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import f2p1
from tests.test_console_read_models import TOKEN_A, as_, http, start, upstream  # noqa: F401  (pytest fixtures)

PRO_PLAN = '2579466'
#: written here: live's two entries the recording lacks
SMALL_PET = {'tier_name': 'Premier Small Pet', 'former_names': [], 'id': 6}
POINTS = {'applies_to': 'all', 'applies_to_category': None, 'applies_to_gtins': [], 'applies_to_skus': [],
          'code': None, 'currency': None, 'discount_amount': None, 'discount_percent': None, 'exclusions': [],
          'former_names': [], 'funded_by': None, 'id': 7, 'mechanic': 'points', 'member_price': None,
          'name': 'Petco Perks', 'points': None, 'points_multiplier': '10.000', 'program_id': 'petco_perks',
          'set_at': '2026-10-30T15:10:37.583777', 'stacks_with': [], 'steps': None, 'tier_name': None,
          'valid_from': None, 'valid_until': None}
#: written here: cycle 3's one per-dollar Perks question, six agents; four exact, one wrong, one unverifiable
PER_DOLLAR = {'type': 'points', 'rule': {'kind': 'per_dollar', 'rate': '10.00', 'program_name': 'Petco Perks'}}
VALUE_ROWS = [{'outcome': o, 'expected_answer': json.dumps(PER_DOLLAR), 'platform': p, 'surface': s,
               'source_ref': json.dumps({'merchant_slug': t2v2.SLUG})}
              for o, p, s in (('exact', 'chatgpt', 'grounded_api'), ('exact', 'claude', 'grounded_api'),
                              ('exact', 'gemini', 'grounded_api'), ('wrong', 'perplexity', 'grounded_api'),
                              ('exact', 'aimode', 'consumer_ui'), ('unverifiable', 'copilot', 'consumer_ui'))]


def _dump(name, body):
    """SOA_2V6_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2V6_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


def _paths():
    return cs.paths_by_sku(t2v2.recorded('price-paths'))


def _owned():
    """The recording's five entries, then live's second tier and points entry (written here)."""
    owned = copy.deepcopy(t2v2.recorded('incentives-owned')['incentives'])
    perks = next(e for e in owned if e['mechanic'] == 'loyalty_program')
    return owned + [{**copy.deepcopy(perks), **SMALL_PET}, copy.deepcopy(POINTS)]


def _live_shape(db, http, upstream):
    t2v2._shape(db, http, upstream)
    upstream.answer('GET', f'{t2v2.f2r2.BASE}/incentives/owned', body={'incentives': _owned()}, token=TOKEN_A)


# ─── P6: the full loop never runs an archived study ───────────────────────

def test_p6_a_full_loop_on_an_archived_study_is_refused(http, db):
    """Oct 30: the console defaulted to the last loop's study after it was archived, and POST /full-loop took it."""
    as_('alice')
    with db.begin() as c:
        c.execute(text("UPDATE soa_query_generation_jobs SET archived_at = :at WHERE study_type = 'ws-2b-fixture'"),
                  {'at': '2026-10-29 12:00:00'})
    refused = start(http)
    assert refused.status_code == 422 and refused.json()['detail'] == 'study is archived'
    with db.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM soa_full_loop_requests")).scalar() == 0
    # unarchived, it runs as before
    with db.begin() as c:
        c.execute(text("UPDATE soa_query_generation_jobs SET archived_at = NULL WHERE study_type = 'ws-2b-fixture'"))
    assert start(http).status_code == 202


def test_p6_a_study_of_another_org_is_still_not_found(http, db):
    as_('alice')
    assert start(http, study_type='no-such-study').status_code == 404


# ─── X1, X2: one line per entry, soa's words, every entry on it ───────────

def test_x1_terms_is_the_line_on_every_card():
    """soa's line ends "No end date." and is the card's whole text: `terms` is it too, so a console that reads
    `terms` shows the line and never a tier's former names alone, or nothing."""
    progs = cs.build_programs(owned=_owned(), paths=_paths(), answers=[], merchant='Petco')
    assert all(p['terms'] == p['text'] and p['terms'] for p in progs)
    assert all(p['text'].count('No end date') + p['text'].count('Ends ') == 1 for p in progs)
    assert all(p['text'].count('Funder not stated') + p['text'].count('Funded by') == 1 for p in progs)


def test_x2_the_points_entry_and_every_tier_have_a_line():
    progs = cs.build_programs(owned=_owned(), paths=_paths(), answers=[], merchant='Petco')
    assert [(p['name'], p['text']) for p in progs] == [
        ('Petco Perks · Premier',
         'All SKUs. Tier Premier. 10 points per $1. Premier members get 10% off on Dog > Food, Cat > Food '
         '(Perks Premier). Formerly Vital Care and Repeat Delivery. Funder not stated. Not combinable with other '
         'offers. No end date.'),
        ('Petco Autoship', 'All SKUs. 1st order 35% off, capped at $20; ongoing 5% off. Rx excluded on the 1st order. '
                           'Funder not stated. Not combinable with other offers. No end date.'),
        ('Petco Autoship', '2 SKUs. 1st order 40% off; 2nd order 20% off; 3rd order 10% off; ongoing 5% off. '
                           'Funded by Purina. Not combinable with other offers. Ends Oct 31.'),
        ('Perks Premier', 'Dog > Food, Cat > Food. Premier members 10% off. Funder not stated. '
                          'Not combinable with other offers. No end date.'),
        ('Petco Perks · Premier Small Pet',
         'All SKUs. Tier Premier Small Pet. 10 points per $1. Funder not stated. Not combinable with other offers. '
         'No end date.'),
        ('Petco Perks points', '10 points per $1, all SKUs. Funder not stated. Not combinable with other offers. '
                               'No end date.')]
    # a fixed total reads as one
    fixed = cs.build_programs(owned=[{**POINTS, 'points_multiplier': None, 'points': 120}], paths=[], answers=[],
                              merchant='Petco')
    assert fixed[0]['text'].startswith('120 points, all SKUs.')


# ─── X3: asked this cycle, keyed on the value-tier rows ───────────────────

def test_x3_one_per_dollar_question_reads_on_the_perks_lines():
    progs = cs.build_programs(owned=_owned(), paths=_paths(), answers=[], merchant='Petco', value_outcomes=VALUE_ROWS)
    read = {p['name']: (p['agentsRight'], p['tone'], p['asked'], p['scored'], p['right']) for p in progs}
    assert read['Petco Perks · Premier'] == ('asked this cycle, 4 of 5 right', 'warn', 6, 5, 4)
    assert read['Petco Perks · Premier Small Pet'] == ('asked this cycle, 4 of 5 right', 'warn', 6, 5, 4)
    assert read['Petco Perks points'] == ('asked this cycle, 4 of 5 right', 'warn', 6, 5, 4)
    # nothing asked about the member price or Autoship
    assert read['Perks Premier'][0] == 'not asked this cycle' and read['Petco Autoship'][0] == 'not asked this cycle'
    perks = next(p for p in progs if p['name'] == 'Petco Perks · Premier')
    assert perks['by_surface']['all']['scored'] == 5 and perks['by_surface']['all']['exact'] == 4
    # a fixed-total question is not about the per-dollar entry, but is about the program
    fixed = [{**o, 'expected_answer': json.dumps({'type': 'points', 'rule': {
        'kind': 'fixed', 'total': 780, 'program_name': 'Perks'}})} for o in VALUE_ROWS]
    progs = cs.build_programs(owned=_owned(), paths=_paths(), answers=[], merchant='Petco', value_outcomes=fixed)
    read = {p['name']: p['agentsRight'] for p in progs}
    assert read['Petco Perks points'] == 'not asked this cycle'
    assert read['Petco Perks · Premier'] == 'asked this cycle, 4 of 5 right'


def test_x3_true_value_keys_the_cards_on_the_cycles_value_rows(http, db, upstream, monkeypatch):
    _live_shape(db, http, upstream)
    monkeypatch.setattr(console_router, '_value_outcomes', lambda conn, row: VALUE_ROWS)
    body = t2v2._read(http, 'true-value', cycle=f2p1.CYCLE_2)
    _dump('true-value-2v6.json', body)
    read = {p['name']: p['agentsRight'] for p in body['programs']}
    assert read['Petco Perks · Premier'] == 'asked this cycle, 4 of 5 right'
    assert len(body['programs']) == 6 and all(p['terms'] == p['text'] for p in body['programs'])


# ─── X4: the points line on the record ────────────────────────────────────

POINTS_LINE = '10 per $1 (780 on this bag at list, 468 on the first Autoship order)'


def test_x4_the_offer_record_states_the_points():
    row = next(r for r in _paths() if r['sku'] == PRO_PLAN)
    record = cs.build_record(row=row, feed_row=None, name='Petco', merchant='Petco', sent=None, held_any=False,
                             owned=_owned())
    fields = {f['k']: f['v'] for f in record['fields']}
    assert fields['Perks points'] == POINTS_LINE
    keys = [f['k'] for f in record['fields']]
    assert keys.index('Perks points') == keys.index('Member price (Perks Premier)') + 1
    # a SKU with no program step: the list price alone; a chew pack is an item
    nexgard = next(r for r in _paths() if r['sku'] == '3879911')
    got = {f['k']: f['v'] for f in cs.build_record(row=nexgard, feed_row=None, name='Petco', merchant='Petco',
                                                   sent=None, held_any=False, owned=_owned())['fields']}
    assert got['Perks points'].startswith('10 per $1 (') and 'on this item at list' in got['Perks points']
    # no points entry: no line, as before
    bare = cs.build_record(row=row, feed_row=None, name='Petco', merchant='Petco', sent=None, held_any=False)
    assert 'Perks points' not in {f['k'] for f in bare['fields']}


def test_x4_the_record_and_the_master_record_serve_it(http, db, upstream):
    _live_shape(db, http, upstream)
    record = t2v2._read(http, 'record', product=PRO_PLAN)
    assert {f['k']: f['v'] for f in record['fields']}['Perks points'] == POINTS_LINE
    truesync = t2v2._read(http, 'truesync')
    _dump('truesync-2v6.json', truesync)
    master = next(r for r in truesync['products'] if r['sku'] == PRO_PLAN)['record']
    assert {f['k']: f['v'] for f in master}['Perks points'] == POINTS_LINE
