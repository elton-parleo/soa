"""
2C-2a: eight fixes from the first live walk of the 2C-2 screens (cycle 229),
each reproduced on the W&S fixture cycle. Where the fixture lacks a shape the
live cycle has (a value & incentives question, a sibling-variant quote, a
previous cycle), the test adds those rows to the fixture database itself.
"""
import copy
import json

from sqlalchemy import text

from tests.test_console_read_models import (  # noqa: F401  (pytest fixtures)
    CYCLE, TOKEN_A, _fixture, as_, db, http, upstream,
)
from tests.test_console_truesync import WS_CATALOG
from tests.test_console_visibility_record import WS, WS_INCENTIVES, WS_REFERENCE
from tests.test_console_parity import _metric_rows
from app.services import console_parity as parity
from app.services import console_read_models as rm


def _add(db, table, row):
    cols = list(row)
    with db.begin() as c:
        c.execute(text(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + k for k in cols)})"),
                  {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def _question(db, qid, tier, text_, expected, source_ref, stage='Ready to Buy'):
    _add(db, 'soa_queries', {'id': qid, 'query_code': f'WIG_{qid}', 'query_text': text_, 'stage': stage,
                             'study_type': 'ws-2b-fixture', 'tier': tier, 'expected_answer': expected,
                             'source_ref': source_ref, 'provenance': 'catalog'})


def _run(db, rid, qid, platform, tier, outcome, claims, *, surface='grounded_api', reason=None, expected=None):
    _add(db, 'soa_runs', {'id': rid, 'cycle_id': 1, 'query_id': qid, 'platform': platform, 'run_number': 1,
                          'run_at': '2026-10-09T15:00:00+00:00', 'raw_response': 'answer', 'status': 'success',
                          'surface': surface, 'answer_status': 'answered'})
    _add(db, 'soa_expectation_outcomes', {'run_id': rid, 'query_id': qid, 'cycle_id': 1, 'platform': platform,
                                          'tier': tier, 'outcome': outcome, 'claim_results': claims,
                                          'reason_code': reason, 'surface': surface, 'expected_answer': expected or {},
                                          'flags': [], 'outcome_reason': 'r'})


# ═══ 1. Changes: one surface, one agent set, one denominator per metric ═══

def test_changes_never_divide_by_the_wrong_denominator():
    """Live: "34 of 59 this cycle against 38 of 25". Another brand's price is
    over answered price questions (those runs are absent, never scored)."""
    rows, vis = _metric_rows()
    now = parity.surface_metrics(rows, vis, 'grounded_api')
    prev = parity.surface_metrics(rows, vis, 'grounded_api')
    changes = {c['metric']: c for c in parity.build_changes(now, prev, 'C178')}
    assert changes['other_brand']['detail'] == '6 of 12 this cycle against 6 of 12 in C178.'
    assert changes['wrong']['detail'] == '4 of 5 this cycle against 4 of 5 in C178.'
    assert changes['named']['detail'] == '0 of 300 this cycle against 0 of 300 in C178.'
    for c in changes.values():
        assert c['now'] <= c['of_now'] and c['prev'] <= c['of_prev']


def test_changes_are_not_comparable_when_the_agents_differ(db):
    """229 ran ChatGPT and Gemini on the grounded surface, 20260915 ChatGPT
    only: one line saying so, and no delta."""
    with db.connect() as c:
        cycle = dict(c.execute(text("SELECT * FROM soa_cycles WHERE id = 1")).mappings().one())
        rows = parity.load_overview_rows(c, cycle)
        vis = rm.load_visibility(c, cycle)['byQuestion']
    now = parity.surface_metrics(rows, vis, 'grounded_api')
    prev = parity.surface_metrics([r for r in rows if r['platform'] == 'chatgpt'],
                                  [v for v in vis if v['agent'] == 'chatgpt'], 'grounded_api', tier=now['tier'])
    assert parity.changes_status(now, prev, '20260915-113207-wiggle-snug-full') == (
        'not_comparable', 'Not comparable: 20260915-113207-wiggle-snug-full ran ChatGPT only on this surface.')
    assert parity.build_changes(now, prev, '20260915-113207-wiggle-snug-full') == []
    # the same agents: compared
    assert parity.changes_status(now, now, 'X')[0] == 'compared'
    overview = parity.build_overview({**cycle, 'cycle_code': CYCLE}, rows=rows, visibility=rm.load_visibility(db.connect(), cycle),
                                     true_value={'rows': []}, brand='Wiggle & Snug',
                                     previous={'code': 'C178', 'rows': [r for r in rows if r['platform'] == 'chatgpt'],
                                               'visibility': {'byQuestion': [v for v in vis if v['agent'] == 'chatgpt']}})
    g = overview['by_surface']['grounded_api']
    assert (g['changes_status'], g['changes'], g['changes_note']) == (
        'not_comparable', [], 'Not comparable: C178 ran ChatGPT only on this surface.')


# ═══ 2. True Value: a cell per agent when the merchant has one retailer ═══

def test_one_retailer_means_one_column_per_agent(http):
    """Live: "0 of 13 scored cells exact" while 9 runs were exact: both agents
    collapsed into one worst-wins cell."""
    as_('alice')
    tv = http.get('/api/console/true-value', params={'cycle': CYCLE}).json()
    assert tv['column_kind'] == 'agent'
    on = [c['id'] for c in tv['columns_by_surface']['grounded_api']]
    cells = [r['cells'][a] for r in tv['rows'] for a in on if a in r['cells']]
    scored = [c for c in cells for b in [c['by_surface'].get('grounded_api')] if b and b['status'] in ('exact', 'wrong', 'partial')]
    exact = sum(1 for c in scored if c['by_surface']['grounded_api']['status'] == 'exact')
    # one exact cell (Gemini on Bum Balm), no longer hidden under ChatGPT's wrong
    assert (exact, len(scored)) == (1, 5)
    assert tv['by_agent']['grounded_api']['gemini']['exact'] == 1


def test_two_retailers_keep_retailer_columns():
    reference = {'prices': [{'gtin': '00012345678905', 'retailer_domain': d, 'price': '21.49', 'verifiable': True}
                            for d in ('target.com', 'walmart.com')]}
    tv = rm.build_true_value(reference, [{'gtin': '00012345678905', 'retailer': 'target.com', 'outcome': 'exact',
                                          'stated': '21.49', 'agent': 'chatgpt', 'surface': 'api'}],
                             own_domain='brand.example', record_variants=[])
    assert tv['column_kind'] == 'retailer' and [c['id'] for c in tv['columns']] == ['target.com', 'walmart.com']


# ═══ 3. Programs join on the generator's identifiers ═════════════════════

def test_member_price_questions_join_the_record_s_tier(http, upstream, db):
    """Live: "Program price quoted 0 of 0" with 36 Member+ questions. The
    question's tier_name is the record's entitled tier name; the owned
    incentive's display name never matched it."""
    expected = {'type': 'member_price', 'amount': '10.99', 'currency': 'USD', 'tier_name': 'member+'}
    _question(db, 100, 'value_incentives', 'What do Member+ members pay for the Bum Balm?', expected,
              {'merchant_slug': 'wiggle-and-snug', 'listing_id': 93, 'variant_id': 'bum-balm-4oz'})
    _run(db, 2001, 100, 'chatgpt', 'value_incentives', 'exact', [], expected=expected)
    _run(db, 2002, 100, 'gemini_grounded', 'value_incentives', 'wrong', [], expected=expected)
    _run(db, 2003, 100, 'gemini_grounded', 'value_incentives', 'unverifiable', [], expected=expected)
    record = copy.deepcopy(WS_INCENTIVES)
    upstream.answer('GET', f'{WS}/incentives/owned', body={'merchant': 'wiggle-and-snug', 'incentives': [
        {'mechanic': 'member_price', 'name': 'Member Rewards', 'tier_name': None, 'member_price': '10.99'}]}, token=TOKEN_A)
    upstream.answer('GET', f'{WS}/incentives', body=record, token=TOKEN_A)
    as_('alice')
    programs = {p['name']: p for p in http.get('/api/console/programs', params={'merchant': 'wiggle-and-snug', 'cycle': CYCLE}).json()['programs']}
    member = programs['Member Rewards Member+']
    assert member['agentsRight'] == 'quoted right by 1 of 2 agents' and member['asked'] == 3
    assert member['by_surface']['grounded_api'] == {'asked': ['chatgpt', 'gemini'], 'right': ['chatgpt'], 'scored': 2, 'exact': 1}
    assert programs['Member Rewards']['agentsRight'] == 'not asked this cycle'      # the owned one, no tier to join


def test_codes_and_points_join_on_the_offer_id():
    prog = {'name': 'Member Rewards points', 'offer_ids': ['wiggle-and-snug:deal:1629:bum-balm-4oz']}
    assert rm._program_matches(prog, {'type': 'points'}, {'offer_id': 'wiggle-and-snug:deal:1629:bum-balm-4oz'})
    assert not rm._program_matches(prog, {'type': 'points'}, {'offer_id': 'other'})
    assert rm._program_matches({'code': 'snug3'}, {'code': ' SNUG3 '})
    assert rm._program_matches({'tier_name': 'Member+'}, {'tier_name': ' member+ '})


# ═══ 4. The ladder draws the variant's member price ══════════════════════

def test_the_ladder_reads_the_variant_s_member_price_first():
    """Live: "Member+ 5% off, stated without a price, not drawn" although the
    page read of Size 1 small carries $12.09. 2C-2b: the corrected fixture
    holds that price where production does, on the read, not the record."""
    listing = next(l for l in WS_CATALOG['listings'] if l['listing_id'] == 90)
    entry = copy.deepcopy(next(l for l in WS_INCENTIVES['listings'] if l['listing_id'] == 90))
    reads = WS_REFERENCE['rows']
    stated, unpriced = parity.ladder_steps(entry, listing['variants'][0], [], reads=reads)
    assert (12.09, 'Member+', 'reference_read', 'member_price') in [s_[:4] for s_ in stated]
    assert 'Member+ 5% off' not in unpriced
    ladder, receipt = parity.build_ladder({'listings': [listing]}, {'listings': [entry]}, [],
                                          [{'variant_id': 'snug-fit-diapers-s1-small'}], own_domain='trueshopstore.com',
                                          reads=reads)
    assert [(s['label'], s['value']) for s in ladder['steps']] == [('List', '$17.99'), ('First order, WELCOME10', '$16.19'), ('Member+', '$12.09')]
    assert receipt['rows'][-1] == {'k': 'The lowest stated price', 'v': '$12.09', 'kind': 'big'}


# ═══ 5. Accessibility denominators ═══════════════════════════════════════

def test_every_markup_check_is_over_the_pages_read():
    """Live: "GTIN in markup 6 of 6" with 19 pages read."""
    rows = [{'read_status': 'ok', 'method': 'json_ld', 'gtin': '1' if i < 6 else None, 'member_price': '9' if i < 4 else None,
             'reference_source': 'honest_fetch', 'findings': []} for i in range(19)]
    checks = {c['key']: c['value'] for c in parity.build_access_checks({'rows': rows})}
    assert (checks['gtin'], checks['member_price'], checks['markup']) == ('6 of 19', '4 of 19', '19 of 19')


# ═══ 6. By stage follows the tier filter ═════════════════════════════════

def test_by_stage_follows_the_tier():
    """Live: with Unprompted picked, the stage table still counted prompted
    rows (Research 34 of 34)."""
    _, vis = _metric_rows()
    for v in vis[300:]:
        v.update(named=[{'name': 'Wiggle & Snug', 'you': True}], first={'name': 'Wiggle & Snug', 'you': True})
    b = parity.visibility_by_stage(vis, 'grounded_api')
    assert [(r['stage'], r['first']) for r in b['stages_by_tier']['unprompted']] == [('Awareness', 0)]
    assert [(r['stage'], r['first']) for r in b['stages_by_tier']['all']] == [('Awareness', 0), ('Research', 6), ('Ready to Buy', 12)]
    assert [t['tier'] for t in b['tiers']] == ['unprompted', 'brand_direct', 'catalog_accuracy']


# ═══ 7. Products: the detail accounts for every run; the newest read ══════

def test_a_sibling_variant_s_quote_is_shown_and_the_page_read_is_the_reference(http, upstream, db):
    """Live: "Quoted a wrong price in 4 of 6 runs" beside one wrong quote and
    three "no price": the Trial Pack quotes were counted, not shown. And the
    reference said "the record, Sep 4" although an Oct 14 read existed."""
    # 2C-2b: exactly the entry scoring/expectation_comparator.py writes for a
    # sibling-variant claim on the record path (rescore_cycle stores
    # verdict.claims as claim_results unchanged), nothing more.
    swap = [{'stated': '6.99', 'amount': '6.99', 'product': 'Snug-Fit Trial Pack', 'tier': None,
             'conflict': 'names a sibling variant', 'target': 'swap', 'variant_id': 'snug-fit-trial-pack',
             'same_group': False, 'outcome': 'wrong', 'matched_at': None, 'against': '6.99',
             'priced_as_named': True}]
    for rid, platform in ((2101, 'chatgpt'), (2102, 'chatgpt'), (2103, 'gemini_grounded')):
        _run(db, rid, 1, platform, 'catalog_accuracy', 'wrong', swap, reason='variant_swap')
    reads = copy.deepcopy(WS_REFERENCE)
    balm_read = next(r for r in reads['rows'] if r['variant_label'] == 'bum-balm-4oz')
    reads['rows'].append({**balm_read, 'price': '12.49', 'observed_at': '2026-10-15T08:00:00+00:00'})
    upstream.answer('GET', f'{WS}/access', body=_fixture('supply_access_ws.json'), token=TOKEN_A)
    upstream.answer('GET', f'{WS}/reference', body=reads, token=TOKEN_A)
    as_('alice')
    body = http.get('/api/console/overview', params={'cycle': CYCLE, 'merchant': 'wiggle-and-snug'}).json()
    balm = next(p for p in body['by_surface']['grounded_api']['products'] if p['sku'] == 'bum-balm-4oz')
    assert balm['issue'] == 'Quoted a wrong price in 4 of 5 runs.'
    assert balm['quoted'] == ('$6.99 for Snug-Fit Trial Pack, 3 of 5 runs (ChatGPT 2, Gemini 1). '
                              '$12.99, 1 of 5 runs (Gemini 1). $14.99, 1 of 5 runs (ChatGPT 1)')
    assert balm['live'] == '$12.49 at trueshopstore.com, our own fetch, Oct 15'
    tv = http.get('/api/console/true-value', params={'cycle': CYCLE}).json()
    whole = next(r for r in tv['rows'] if r['sku'] == 'bum-balm-4oz')['retailer_cells']['trueshopstore.com']
    assert {q['swap_product'] for q in whole['quotes'] if q.get('swap_product')} == {'Snug-Fit Trial Pack'}


def test_with_no_page_read_the_record_is_the_reference_and_says_so():
    tv = rm.build_true_value(None, [], own_domain='shop.test', record_variants=[
        {'variant_id': 'v1', 'label': 'V1', 'list_price': '24.99', 'currency': 'USD', 'published_at': '2026-09-04T00:00:00'}],
        reads=[{'variant_ref': 'catalog_variant:9', 'variant_label': 'v2', 'price': '9.99', 'verifiable': True}])
    cell = tv['rows'][0]['cells']['shop.test']
    assert (cell['live'], cell['live_basis']) == ('$24.99', 'record')
    assert parity._live_text(cell, 'shop.test') == '$24.99 at shop.test, the record of Sep 4, no page read yet'


# ═══ 8. The week in short never repeats a count ══════════════════════════

def test_the_last_sentence_is_a_signal_not_already_stated():
    rows, vis = _metric_rows()
    m = parity.surface_metrics(rows, vis, 'grounded_api')
    head = parity.visibility_headline(vis, 'grounded_api', 'Wiggle & Snug')
    signals = parity.build_signals(m, [], surface='grounded_api', brand='Wiggle & Snug', cycle_start='2026-10-14', access_problems=[])
    assert [s['rule'] for s in signals] == ['other_brand', 'fabricated', 'unverifiable']
    lines = parity.build_summary(m, head, signals)['lines']
    assert lines[-1] == '5 brand answers stated facts Wiggle & Snug never published.'
    assert sum(1 for l in lines if '6' in l and "another brand's price" in l) == 1
    # every signal already stated: no last sentence
    only = [s for s in signals if s['rule'] in ('other_brand', 'unverifiable')]
    assert len(parity.build_summary(m, head, only)['lines']) == 2
