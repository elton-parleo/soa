"""
2C-2b: four fixes from the second live walk (cycle 229), on a W&S fixture
corrected to production's shape: the record's variants state no member
price (it is only on the page reads, supply_reference_ws.json, 7 of 19), and
swap rows are written as the scorer writes them, in both of the shapes cycle
229 can hold (before and after b3c5a29).
"""
import copy

from sqlalchemy import text

from tests.test_console_read_models import (  # noqa: F401  (pytest fixtures)
    CYCLE, TOKEN_A, _fixture, as_, db, http, upstream,
)
from tests.test_console_truesync import WS_CATALOG
from tests.test_console_visibility_record import WS, WS_INCENTIVES, WS_PRICE_HISTORY, WS_REFERENCE, record, ws_supply
from tests.test_console_2c2a import _run
from tests.test_console_parity import _metric_rows
from app.services import console_parity as parity
from app.services import console_read_models as rm

LISTING_90 = next(l for l in WS_CATALOG['listings'] if l['listing_id'] == 90)
ENTRY_90 = next(l for l in WS_INCENTIVES['listings'] if l['listing_id'] == 90)
S1_SMALL = LISTING_90['variants'][0]


# ═══ §0: the fixture is production's shape ═══════════════════════════════

def test_the_fixture_holds_member_prices_where_production_does():
    assert all(not v.get('member_prices') and v.get('entitled_member_price') is None
               for l in WS_INCENTIVES['listings'] for v in l.get('variants') or [])
    assert not any('member_price' in v for l in WS_CATALOG['listings'] for v in l['variants'])
    rows = WS_REFERENCE['rows']
    assert len(rows) == 19 and sum(1 for r in rows if r['member_price']) == 7
    assert next(r for r in rows if r['variant_label'] == 'snug-fit-diapers-s1-small')['member_price'] is None
    assert all(r['variant_ref'].startswith('catalog_variant:') and r['method'] == 'json_ld' for r in rows)


# ═══ 1. The member price: the record, else the newest page read ══════════

def test_the_ladder_draws_the_page_read_s_member_price_and_names_it():
    """Live: "Stated without a price, so not drawn: Member+ 5% off" although
    the Oct 14 read of Size 1 small carries $12.09."""
    ladder, receipt = parity.build_ladder({'listings': [LISTING_90]}, {'listings': [ENTRY_90]}, [],
                                          [{'variant_id': S1_SMALL['variant_id']}], own_domain='trueshopstore.com',
                                          reads=WS_REFERENCE['rows'], member_reads=WS_PRICE_HISTORY['prices'])
    # 2C-2c: the newest read (Oct 14) states none; the Oct 9 read in supply's history does
    assert [(s['label'], s['value'], s['note']) for s in ladder['steps']] == [
        ('List', '$17.99', 'from the record'), ('First order, WELCOME10', '$16.19', 'from the record'),
        ('Member+', '$12.09', 'from the page read Oct 9')]
    assert ladder['unpriced'] == []
    assert receipt['rows'][1] == {'k': 'Member+, from the page read Oct 9', 'v': '-$5.90', 'kind': 'minus', 'tag': 'On the page'}
    assert receipt['rows'][2] == {'k': 'The lowest stated price', 'v': '$12.09', 'kind': 'big'}


def test_with_neither_a_record_nor_a_page_price_it_is_stated_without_a_price():
    s5 = next(v for v in LISTING_90['variants'] if v['variant_id'] == 'snug-fit-diapers-s5-small')
    ladder, _ = parity.build_ladder({'listings': [LISTING_90]}, {'listings': [ENTRY_90]}, [],
                                    [{'variant_id': 'snug-fit-diapers-s5-small'}], own_domain='trueshopstore.com',
                                    reads=WS_REFERENCE['rows'])
    assert [s['label'] for s in ladder['steps']] == ['List', 'First order, WELCOME10']
    assert ladder['unpriced'] == ['Member+ 5% off'] and 'Stated without a price' in ladder['note']
    assert parity.member_price_source(ENTRY_90, s5, WS_REFERENCE['rows']) is None


def test_the_record_s_member_price_wins_over_the_page():
    entry = copy.deepcopy(ENTRY_90)
    entry['variants'][0].update(entitled_member_price='13.50', entitled_tier_name='Member+')
    src = parity.member_price_source(entry, S1_SMALL, WS_REFERENCE['rows'])
    assert (src['price'], src['source'], src['note']) == (13.5, 'record', 'from the record')


def test_the_record_s_variants_show_the_same_member_price_and_source(http, upstream):
    ws_supply(upstream)
    as_('alice')
    body = record(http, str(LISTING_90['product_id']))
    s1 = next(v for v in body['variants'] if v['id'] == S1_SMALL['variant_id'])
    assert s1['price'] == '$17.99 · member $12.09, from the page read Oct 9'
    assert (s1['member_source'], s1['member_note']) == ('reference_read', 'from the page read Oct 9')
    s5 = next(v for v in body['variants'] if v['id'] == 'snug-fit-diapers-s5-small')
    assert s5['price'] == '$26.99' and s5['member_price'] is None
    field = next(f for f in body['fields'] if f['k'] == 'Member price')
    assert field['v'] == '$12.09 to $30.49' and field['prov'] == 'parleo'
    assert field['note'] == 'from the page read Oct 14, on 8 of 12 variants. The record states none'


# ═══ 2. Swap quotes are listed on the row asked about ════════════════════

#: A swap row scored before b3c5a29 (cycle 229 was scored on Oct 14 before
#: it): the claim keeps the sibling's own verdict, the question's is
#: question_outcome, and there is no priced_as_named.
SWAP_BEFORE_B3C5A29 = [{'stated': '6.99', 'amount': '6.99', 'product': 'Snug-Fit Trial Pack', 'tier': None,
                        'conflict': 'names a sibling variant', 'target': 'swap', 'variant_id': 'snug-fit-trial-pack',
                        'same_group': False, 'outcome': 'exact', 'matched_at': None, 'against': '6.99',
                        'question_outcome': 'wrong'}]


def _overview(http, upstream):
    ws_supply(upstream)
    upstream.answer('GET', f'{WS}/access', body=_fixture('supply_access_ws.json'), token=TOKEN_A)
    as_('alice')
    return http.get('/api/console/overview', params={'cycle': CYCLE, 'merchant': 'wiggle-and-snug'}).json()


def test_swap_runs_are_listed_with_their_quote(http, upstream, db):
    """Live, Size 4 small: "wrong in 4 of 6 runs" beside "$9.99, 1 of 6. No
    price, 5 of 6": three Gemini variant_swap runs were counted, not shown."""
    for rid in (2201, 2202, 2203):
        _run(db, rid, 4, 'gemini_grounded', 'catalog_accuracy', 'wrong', SWAP_BEFORE_B3C5A29, reason='variant_swap')
    for rid in (2204, 2205):
        _run(db, rid, 4, 'chatgpt', 'catalog_accuracy', 'absent', [])
    body = _overview(http, upstream)
    s3 = next(p for p in body['by_surface']['grounded_api']['products'] if p['sku'] == 'snug-fit-diapers-s3-small')
    assert s3['issue'] == 'Quoted a wrong price in 4 of 6 runs, most often $6.99 against $22.99.'
    assert s3['quoted'] == ('$6.99 for Snug-Fit Trial Pack, 3 of 6 runs (Gemini 3). $9.99, 1 of 6 runs (ChatGPT 1). '
                            'No price, 2 of 6 runs (ChatGPT 2)')


def test_every_run_a_product_row_counts_is_in_its_detail(http, upstream, db):
    for rid in (2301, 2302):
        _run(db, rid, 4, 'gemini_grounded', 'catalog_accuracy', 'wrong', SWAP_BEFORE_B3C5A29, reason='variant_swap')
    _run(db, 2303, 1, 'chatgpt', 'catalog_accuracy', 'absent', [])
    body = _overview(http, upstream)
    for surface in body['by_surface'].values():
        for p in surface['products']:
            groups = p['quote_groups']
            assert sum(g['runs'] for g in groups) == p['runs'], p['sku']
            priced = sum(g['runs'] for g in groups if g['stated'])
            assert priced >= p['wrong_runs'], p['sku']        # every wrong run shows a value


# ═══ 3. The per-agent change follows the comparability rule ══════════════

def test_the_agent_table_says_not_comparable_when_the_block_does(db):
    with db.connect() as c:
        cycle = dict(c.execute(text("SELECT * FROM soa_cycles WHERE id = 1")).mappings().one())
        rows = parity.load_overview_rows(c, cycle)
        vis = rm.load_visibility(c, cycle)
    only_chatgpt = {'code': 'C178', 'rows': [r for r in rows if r['platform'] == 'chatgpt'],
                    'visibility': {'byQuestion': [v for v in vis['byQuestion'] if v['agent'] == 'chatgpt']}}
    o = parity.build_overview({**cycle, 'cycle_code': CYCLE}, rows=rows, visibility=vis, true_value={'rows': []},
                              brand='Wiggle & Snug', previous=only_chatgpt)
    g = o['by_surface']['grounded_api']
    assert g['changes_status'] == 'not_comparable'
    assert [(a['agent'], a['delta'], a['delta_status']) for a in g['agents']] == [
        ('chatgpt', '', 'not_comparable'), ('gemini', '', 'not_comparable')]


def test_a_compared_agent_change_uses_the_block_s_denominator():
    rows, vis = _metric_rows()
    now = parity.surface_metrics(rows, vis, 'grounded_api')
    prev = copy.deepcopy(now)
    prev['agents']['chatgpt']['first'] = 2
    prev['code'] = 'C178'
    agents = {a['agent']: a for a in parity.build_agents(now, prev, 'compared')}
    assert (agents['chatgpt']['delta'], agents['chatgpt']['delta_status']) == ('-2', 'compared')
    assert agents['chatgpt']['delta_detail'] == '0 of 150 this cycle against 2 of 150 in C178.'


# ═══ 4. One run count ════════════════════════════════════════════════════

def test_coverage_tiers_and_agents_agree_when_a_run_errored(http, upstream, db):
    """Live: coverage 514 answers, the tier table 516, the agent table 514:
    an errored run has no answer_status, and the tier table counted it."""
    with db.begin() as c:
        c.execute(text("UPDATE soa_runs SET status = 'error', answer_status = NULL, raw_response = NULL WHERE id = 1003"))
        c.execute(text("DELETE FROM soa_expectation_outcomes WHERE run_id = 1003"))
    body = _overview(http, upstream)
    summary = http.get('/api/console/answers/summary', params={'cycle': CYCLE}).json()
    # 2I-8: per surface, `all` aside (it is every surface's runs again)
    tier_answers = sum(c['answered'] for t in summary['tiers'] for c in t['surfaces'] if c['surface'] != 'all')
    agent_answers = sum(a['answers'] for k, s in body['by_surface'].items() if k != 'all' for a in s['agents'])
    assert body['coverage']['runs'] == 8
    assert (body['coverage']['answers'], tier_answers, agent_answers) == (6, 6, 6)
    # and on `all` alone, the same counts
    assert sum(c['answered'] for t in summary['tiers'] for c in t['surfaces'] if c['surface'] == 'all') == 6
    assert sum(a['answers'] for a in body['by_surface']['all']['agents']) == 6
