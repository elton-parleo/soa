"""
2G: seven demo-parity leftovers, soa's half, on the 229-shaped fixture
(console_fixture_229.py with the 2G layer, console_fixture_229_2g.py) on
sqlite and on a local Postgres (test_console_2c3a's db fixture). Supply
answers with recorded payloads (tests/fixtures/console/README.md).
"""
from collections import Counter

import pytest

from app.services import console_parity as parity
from tests import console_fixture_229 as f229
from tests import console_fixture_229_2g as g
from tests.test_console_2c3a import _cycle_229, db  # noqa: F401  (db is a fixture)
from tests.test_console_read_models import TOKEN_A, _fixture, as_, http, tenants, upstream  # noqa: F401
from tests.test_console_truesync import WS_CATALOG, _web
from tests.test_console_visibility_record import WS, record, ws_supply

PRICES_AVAILABILITY = _fixture('supply_retailer_prices_ws_availability.json')


@pytest.fixture
def cycle(db, upstream):
    _cycle_229(db)
    g.apply(db)
    ws_supply(upstream)
    upstream.answer('GET', f'{WS}/access', body=_fixture('supply_access_ws.json'), token=TOKEN_A)
    as_('op')
    return db


def _get(http, path, **params):
    r = http.get(path, params={'cycle': f229.CYCLE_229, 'org': 10, **params})
    assert r.status_code == 200, r.text
    return r.json()


# ═══ 1. Answers: the header takes the answered count ═════════════════════

def test_the_run_count_rule_516_runs_514_answered(http, cycle):
    """The demo's header counts answers; under 2C-2b's rule an answer is a run
    that says answered. soa serves both per surface in all_tiers."""
    summary = _get(http, '/api/console/answers/summary')
    every = {c['surface']: (c['runs'], c['answered']) for c in summary['all_tiers']}
    assert sum(r for r, _ in every.values()) == 516 and sum(a for _, a in every.values()) == 514
    assert every['grounded_api'] == (514, 514) and every['consumer_ui'] == (2, 0)
    answers = _get(http, '/api/console/answers')
    assert len(answers) == 516 and sum(a['answer_status'] == 'answered' for a in answers) == 514


# ═══ 2. Answers carry what their question expected ═══════════════════════

def test_each_answer_says_what_its_question_expected(http, cycle):
    answers = _get(http, '/api/console/answers')
    by = Counter(a.get('expected_type') for a in answers)
    # catalog 19 x 6, member 3 x 6, code 1 x 6, points 2 x 6, brand-direct 11 x 6, unprompted none
    assert by == {'price': 114, 'member_price': 18, 'code': 6, 'points': 12, 'brand_mention': 66, None: 300}
    # Snug-Fit Diapers (listing 90): its price questions, and the code and points ones asked on it
    diapers = {v['variant_id'] for v in WS_CATALOG['listings'][0]['variants']}
    mine = Counter(a.get('expected_type') for a in answers if a.get('variant_id') in diapers)
    assert mine == {'price': 72, 'code': 6, 'points': 12}


# ═══ 4. Visibility: the brands named outside the comparison set ═════════

def test_the_untracked_brands_with_their_counts(http, cycle):
    body = _get(http, '/api/console/visibility')
    top = body['ranking']['untracked']['grounded_api']
    assert top[:3] == [{'name': 'Target', 'named': 34}, {'name': 'Costco', 'named': 17}, {'name': 'Hello Bello', 'named': 9}]
    assert not {'Pampers', 'Huggies', 'Pull-Ups', 'Wiggle & Snug'} & {b['name'] for b in top}
    assert body['ranking']['denoms']['grounded_api'] == 514                   # "(all 514 answers)"
    assert body['sources_left_out'] == 43                                      # the existing line stays
    assert body['ranking']['untracked']['consumer_ui'] == []


# ═══ 5. True Value: the caption under each product ═══════════════════════

def test_each_member_price_variant_carries_its_program_line(http, cycle):
    body = _get(http, '/api/console/true-value', merchant='wiggle-and-snug')
    lines = body['program_lines']
    assert set(g.MEMBER_VARIANTS) <= set(lines)
    # a variant with a program price on its page and no Member+ question says so; one with neither has no line
    for vid, line in lines.items():
        if vid not in g.MEMBER_VARIANTS:
            assert line['by_surface'] == {} and line['line'].endswith('Not asked this cycle.') and line['price'] is not None
    assert 'bum-balm-4oz' not in lines
    gr = {vid: lines[vid]['by_surface']['grounded_api'] for vid in g.MEMBER_VARIANTS}
    # member outcomes in run order: 9 exact, 9 wrong; ChatGPT's three runs then Gemini's
    assert (gr['snug-fit-overnight-s3']['asked'], gr['snug-fit-overnight-s3']['quoted']) == (['chatgpt', 'gemini'], ['chatgpt', 'gemini'])
    assert gr['cloud-wipes-3pack']['quoted'] == ['chatgpt']
    assert gr['snug-fit-trial-pack']['quoted'] == []
    assert gr['snug-fit-trial-pack']['line'].endswith('Quoted by 0 of 2 agents.')
    assert gr['cloud-wipes-3pack']['line'].endswith('Quoted by 1 of 2 agents.')
    # every row names its variant, so the console can put the line under it
    assert {r['variant_id'] for r in body['rows']} >= set(g.MEMBER_VARIANTS)


def test_the_program_price_follows_the_ladders_source_rule():
    """The record's member price first, else the newest page read with one."""
    listing = WS_CATALOG['listings'][1]
    v = listing['variants'][0]
    outcomes = [{'expected_answer': {'type': 'member_price', 'tier_name': 'Member+'}, 'source_ref': {'variant_id': v['variant_id']},
                 'platform': 'chatgpt', 'surface': 'grounded_api', 'outcome': 'exact'}]
    read = {'variant_ref': v['variant_id'], 'read_status': 'ok', 'member_price': '11.49', 'observed_at': '2026-10-14T17:00:00+00:00'}
    from_read = parity.program_lines({'listings': [listing]}, None, outcomes, reads=[read])[v['variant_id']]
    assert from_read['by_surface']['grounded_api']['line'] == 'Member $11.49 (from the page read Oct 14). Quoted by 1 of 1 agent.'
    record = {'listings': [{'listing_id': listing['listing_id'], 'variants': [
        {'variant_id': v['variant_id'], 'member_prices': [{'price': '10.99', 'tier_name': 'Member+'}]}]}]}
    from_record = parity.program_lines({'listings': [listing]}, record, outcomes, reads=[read])[v['variant_id']]
    assert from_record['by_surface']['grounded_api']['line'].startswith('Member+ $10.99 (from the record).')
    nothing = parity.program_lines({'listings': [listing]}, None, [], reads=[])
    assert nothing == {}


# ═══ 6. Offer record: availability; shipping and returns only if supply has them ══

def test_availability_from_the_newest_read_and_no_shipping_or_returns(http, cycle, upstream):
    upstream.answer('GET', f'{WS}/retailer-prices', body=PRICES_AVAILABILITY, token=TOKEN_A)
    body = record(http, 91, org=10)
    fields = {f['k']: f for f in body['offer_fields']}
    assert fields['Availability']['v'] == 'In stock' and fields['Availability']['prov'] == 'parleo'
    assert fields['Availability']['note'].startswith('as the newest page read found it')
    # supply's record carries neither: its store config has a free-shipping deal, not a policy, and no returns
    assert 'Shipping' not in fields and 'Returns' not in fields


def test_no_availability_anywhere_renders_none(http, cycle):
    body = record(http, 91, org=10)                       # the Oct 14 recording: no availability on any read
    assert 'Availability' not in {f['k'] for f in body['offer_fields']}


def test_a_record_that_carries_shipping_and_returns_shows_them():
    listing = {'listing_id': 1, 'variants': [{'variant_id': 'a', 'availability': 'in_stock'}],
               'shipping': 'Free over $39', 'returns': '60 days'}
    fields = parity.offer_fields({'fields': [{'k': 'Name', 'prov': 'retail'}]}, owned=None, reference_rows=[],
                                 verifications=[], listing=listing)
    assert [(f['k'], f['v'], f['prov']) for f in fields] == [
        ('Availability', 'In stock', 'retail'), ('Shipping', 'Free over $39', 'retail'), ('Returns', '60 days', 'retail')]


# ═══ 7. Catalog: the stage ladder ════════════════════════════════════════

def test_the_stage_ladder_19_published_13_measured_0_verified(http, cycle, upstream):
    tenants(upstream)
    upstream.answer('GET', '/api/truesync/publications', body=_web('publications.json'), token=TOKEN_A)
    body = http.get('/api/console/catalog', params={'merchant': 'wiggle-and-snug', 'org': 10}).json()
    ladder = body['stage_ladder']
    by = {s['key']: s['products'] for s in ladder['stages']}
    assert by == {'not_measured': 6, 'measured': 13, 'published': 19, 'verified': 0}
    assert ladder['here'] == 2 and ladder['total'] == 19
    assert [s['name'] for s in ladder['stages']] == ['Not measured', 'Measured', 'Published', 'Verified']
    assert ladder['stages'][1]['line'] == 'Weekly check runs, record compiled'


def test_here_is_the_highest_stage_reached():
    assert parity.stage_ladder([{'stages': []}])['here'] == 0
    assert parity.stage_ladder([{'stages': ['measured']}, {'stages': []}])['here'] == 1
    assert parity.stage_ladder([{'stages': ['measured', 'published', 'verified']}])['here'] == 3
