"""
2C-2: the console's demo blocks from stored data (app/services/console_parity.py),
and the two read-model bugs it starts with.

Over HTTP on the W&S fixture cycle with supply faked as the other console
tests fake it; the rules the fixture cannot show (thresholds, a previous
cycle, unprompted answers) on the pure builders with rows shaped like cycle
229's (FL3-wiggle-and-snug-20261014).
"""
import copy

from tests.test_console_read_models import (  # noqa: F401  (pytest fixtures)
    CYCLE, OWNED, TOKEN_A, as_, db, http, tenants, upstream,
)
from tests.test_console_truesync import WS_CATALOG
from tests.test_console_visibility_record import WS, WS_INCENTIVES, WS_PRICE_HISTORY, WS_REFERENCE, record, ws_supply
from tests.console_schema import check
from app.services import console_parity as parity
from app.services import console_read_models as rm


# ═══ §0.1 the record finds a GTIN-less variant's read ═════════════════════

def _supply_read(variant, n, **extra):
    """A reference row in supply's real shape (truesync/fullloop/views.py):
    variant_ref is `catalog_variant:<n>`, variant_label is the variant key,
    gtin is the record's (None here), the URL the family page's."""
    return {'variant_ref': f'catalog_variant:{n}', 'gtin': variant.get('gtin'), 'sku': None,
            'variant_label': variant['variant_id'], 'retailer_domain': 'trueshopstore.com',
            'url': 'https://trueshopstore.com/products/snug-fit-diapers', 'read_status': 'ok',
            'reference_source': 'honest_fetch', 'method': 'json_ld', 'observed_at': '2026-10-14T17:01:00+00:00',
            'price': variant['list_price'], 'member_price': None, 'list_price': None, 'currency': 'USD',
            'verifiable': True, 'findings': [], 'gap_count': 0, **extra}


def test_every_variant_of_a_family_page_finds_its_read(http, upstream):
    """Listing 90 has 12 variants and 4 GTINs. A GTIN-only join left 8 'Not
    read yet' although every page was read; the variant key joins all 12."""
    listing = next(l for l in WS_CATALOG['listings'] if l['listing_id'] == 90)
    rows = [_supply_read(v, 100 + i) for i, v in enumerate(listing['variants'])]
    ws_supply(upstream, reference={**WS_REFERENCE, 'rows': rows})
    as_('alice')
    body = record(http, str(listing['product_id']))
    assert [v['status'] for v in body['variants']] == ['Matches the page'] * 12
    assert sum(1 for v in listing['variants'] if not v.get('gtin')) == 8


def test_the_join_keys_in_order():
    v = {'variant_id': 'bum-balm-4oz', 'gtin': '884400896186'}
    one = {'listing_id': 93, 'product_url': 'https://trueshopstore.com/products/bum-balm-4-oz', 'variants': [v]}
    assert rm.reference_matches({'variant_ref': 'bum-balm-4oz'}, v)
    assert rm.reference_matches({'variant_ref': 'catalog_variant:9', 'variant_label': 'bum-balm-4oz'}, v)
    assert rm.reference_matches({'variant_ref': 'feed_sku:3', 'sku': 'bum-balm-4oz'}, v)
    # a one-variant listing: its page, or the listing's own ref
    assert rm.reference_matches({'url': 'https://www.trueshopstore.com/products/bum-balm-4-oz/?ref=x'}, v, one)
    assert rm.reference_matches({'variant_ref': 'listing:93'}, v, one)
    # GTIN is the second key, never needed
    assert rm.reference_matches({'variant_ref': 'catalog_variant:1', 'gtin': '00884400896186'}, v)
    assert not rm.reference_matches({'variant_ref': 'catalog_variant:2', 'variant_label': 'other'}, {'variant_id': 'x'})
    # a family page's URL alone never speaks for one of its variants
    family = {'listing_id': 90, 'product_url': 'https://trueshopstore.com/products/snug-fit-diapers',
              'variants': [{'variant_id': 'a'}, {'variant_id': 'b'}]}
    assert not rm.reference_matches({'url': family['product_url'], 'variant_label': 'b'}, {'variant_id': 'a'}, family)


# ═══ §0.2 a True Value cell follows its rule ══════════════════════════════

def q(outcome, stated=None, surface='grounded_api', agent='chatgpt', run='run-1'):
    return {'outcome': outcome, 'stated': stated, 'surface': surface, 'agent': agent, 'run': run}


def test_the_worst_quoting_run_decides_and_its_quote_is_shown():
    assert rm.aggregate_cell([q('exact', '12.99'), q('exact', '12.99'), q('wrong', '14.99')]) == ('wrong', '14.99')
    assert rm.aggregate_cell([q('partial', '12.49'), q('stale', '11.99'), q('exact', '12.99')]) == ('stale', '11.99')
    # a 'wrong' outcome that quoted nothing is not a quote: no WRONG with "not quoted"
    assert rm.aggregate_cell([q('wrong'), q('absent')]) == ('absent', None)
    # another brand's price is left out, even with a number stated
    assert rm.aggregate_cell([q('absent', '15.49'), q('exact', '12.99')]) == ('exact', '12.99')
    assert rm.aggregate_cell([q('absent', '15.49')]) == ('absent', None)
    assert rm.aggregate_cell([q('unverifiable', '12.99')]) == ('unverifiable', '12.99')
    assert rm.aggregate_cell([]) == (None, None)


def test_a_cell_never_reads_wrong_with_nothing_quoted():
    variants = [{'variant_id': 'v1', 'label': 'V1', 'list_price': '12.99', 'currency': 'USD'}]
    scored = [{**q('wrong'), 'variant_id': 'v1'}, {**q('absent', agent='gemini', run='run-2'), 'variant_id': 'v1'}]
    tv = rm.build_true_value(None, scored, own_domain='shop.test', record_variants=variants)
    cell = tv['rows'][0]['retailer_cells']['shop.test']
    assert (cell['status'], cell['quoted']) == ('missed', '—')
    assert tv['rows'][0]['cells']['chatgpt']['status'] == 'missed'
    check(tv, 'TrueValue')


def test_true_value_is_per_surface_with_the_agent_split(http):
    as_('alice')
    tv = http.get('/api/console/true-value', params={'cycle': CYCLE}).json()
    assert [s['surface'] for s in tv['surfaces']] == ['consumer_ui', 'grounded_api'] and tv['surface'] == 'grounded_api'
    assert tv['by_agent']['grounded_api'] == {
        'chatgpt': {'exact': 0, 'scored': 2, 'wrong': 2, 'stale': 0, 'partial': 0, 'unverifiable': 0, 'left_out': 0, 'other_brand': 0},
        'gemini': {'exact': 1, 'scored': 3, 'wrong': 2, 'stale': 0, 'partial': 0, 'unverifiable': 0, 'left_out': 0, 'other_brand': 0}}
    assert tv['by_agent']['consumer_ui']['aimode']['left_out'] == 1
    assert 'programs' in tv and 'ladder' not in tv          # no merchant: no supply read


def test_true_value_with_a_merchant_has_programs_and_the_ladder(http, upstream):
    incentives = copy.deepcopy(WS_INCENTIVES)
    upstream.answer('GET', f'{WS}/incentives/owned', body=OWNED, token=TOKEN_A)
    upstream.answer('GET', f'{WS}/incentives', body=incentives, token=TOKEN_A)
    upstream.answer('GET', f'{WS}/catalog', body=WS_CATALOG, token=TOKEN_A)
    upstream.answer('GET', f'{WS}/reference', body=WS_REFERENCE, token=TOKEN_A)
    upstream.answer('GET', f'{WS}/retailer-prices', body=WS_PRICE_HISTORY, token=TOKEN_A)
    as_('alice')
    tv = http.get('/api/console/true-value', params={'cycle': CYCLE, 'merchant': 'wiggle-and-snug'}).json()
    check(tv, 'TrueValue')
    # 2C-2a: the record's programs first; the owned Member Rewards (Member+) and SNUG3 are the same programs
    assert [p['name'] for p in tv['programs']] == ['Member Rewards Member+', 'WELCOME10', 'SNUG3', 'Member Rewards points']
    ladder = tv['ladder']
    # Bum Balm is the variant this cycle asked about most (3 runs).
    assert ladder['variant_id'] == 'bum-balm-4oz' and ladder['sub'] == 'The product this cycle asked about most, in 3 runs.'
    # the record states a $10.99 member price and Member+ at $7.34; its 10% first-order offer states no price
    assert [(s['label'], s['value']) for s in ladder['steps']] == [('List', '$12.99'), ('Member', '$10.99'), ('Member+', '$7.34')]
    assert ladder['unpriced'] == ['WELCOME10 10% off']
    assert tv['receipt']['rows'][-1] == {'k': 'The lowest stated price', 'v': '$7.34', 'kind': 'big'}
    assert tv['read_errors'] == {}


def test_supply_s_own_member_prices_are_read_when_listed():
    entry = {'listing_id': 93, 'incentives': [{'mechanic': 'member_price', 'variant_scope': ['b'], 'value': {'member_price': '10.99'}}],
             'variants': [{'variant_id': 'b', 'member_prices': [{'tier_name': 'Member+', 'price': '11.69', 'basis': 'effective_net_price'}]}]}
    stated, _ = parity.ladder_steps(entry, {'variant_id': 'b'}, [])
    assert stated == [(11.69, 'Member+', 'record', 'effective_net_price', None)]


def test_the_ladder_draws_only_stated_prices():
    listing = next(l for l in WS_CATALOG['listings'] if l['listing_id'] == 90)
    entry = next(l for l in WS_INCENTIVES['listings'] if l['listing_id'] == 90)
    variant = listing['variants'][0]
    stated, unpriced = parity.ladder_steps(entry, variant, [])
    # WELCOME10 states its first-order price; Member+ states 5% and no price,
    # and with no page read given there is no price to draw.
    assert stated == [(16.19, 'First order, WELCOME10', 'record', 'effective_net_price', None)]
    assert unpriced == ['Member+ 5% off']


# ═══ 1. Overview ══════════════════════════════════════════════════════════

def test_overview_on_the_fixture_cycle(http, upstream):
    upstream.answer('GET', f'{WS}/access', body=_access_with_a_problem(), token=TOKEN_A)
    as_('alice')
    body = http.get('/api/console/overview', params={'cycle': CYCLE, 'merchant': 'wiggle-and-snug'}).json()
    assert body['surface'] == 'grounded_api' and body['changes_note'] == 'First cycle. Changes appear from the next one.'
    g = body['by_surface']['grounded_api']
    assert g['changes'] == []
    for a in g['agents']:
        check(a, 'AgentWeek')
    agents = {a['agent']: a for a in g['agents']}
    assert agents['chatgpt']['pricesRight'] == '0 of 2' and agents['chatgpt']['note'] == 'Wrong on 2 prices.'
    assert agents['gemini']['pricesRight'] == '1 of 3' and agents['gemini']['note'] == 'Wrong on 2 prices.'
    assert agents['gemini']['named'] == 4 and agents['gemini']['first'] == 4
    for p in g['products']:
        check({k: v for k, v in p.items()}, 'ProductWeek')
    balm = next(p for p in g['products'] if p['sku'] == 'bum-balm-4oz')
    assert balm['status'] == 'wrong' and balm['quote'] == '$14.99'
    assert balm['quoted'] == '$12.99, 1 of 2 runs (Gemini 1). $14.99, 1 of 2 runs (ChatGPT 1)'
    assert balm['live'] == '$12.99 at trueshopstore.com, the record of Aug 28, no page read yet'
    assert balm['issue'] == 'Quoted a wrong price in 1 of 2 runs.'
    # the one access problem is a signal on every surface; Claude-User is not measured, not a problem
    assert [s['id'] for s in g['signals']] == ['access']
    assert g['signals'][0]['title'] == '1 agent identity could not read the pages.'
    assert g['signals'][0]['detail'] == 'PerplexityBot. From the last access run.'
    assert g['summary']['lines'] == ['First in 6 of 7 answers, ahead of every other brand.',
                                     "Prices right in 1 of 5 scored answers, 0 answered with another brand's price.",
                                     '1 agent identity could not read the pages.']


def _access_with_a_problem():
    from tests.test_console_read_models import _fixture
    body = copy.deepcopy(_fixture('supply_access_ws.json'))
    for r in body['accessibility']['requests']:
        if r['identity'] == 'PerplexityBot':
            r.update(ok=False, result='0 of 1 pages answered', code='403')
    return body


def _metric_rows():
    """Cycle 229-shaped rows on one surface: 300 unprompted, then priced."""
    rows, vis = [], []
    rid = 0

    def add(tier, platform, outcome=None, reason=None, named=(), first=None, variant=None, stage='Awareness'):
        nonlocal rid
        rid += 1
        rows.append({'run_id': rid, 'platform': platform, 'surface': 'grounded_api', 'answer_status': 'answered',
                     'tier': tier, 'stage': stage, 'query_code': f'Q{rid}', 'variant_id': variant,
                     'outcome': outcome, 'reason_code': reason})
        vis.append({'run': f'run-{rid}', 'surface': 'grounded_api', 'agent': 'chatgpt' if platform == 'chatgpt' else 'gemini',
                    'tier': tier or 'unprompted', 'answered': True, 'stage': stage, 'q': f'q{rid}', 'query_code': f'Q{rid}',
                    'named': [{'name': n, 'you': n == 'Wiggle & Snug'} for n in named],
                    'first': {'name': first, 'you': first == 'Wiggle & Snug'} if first else None})
    for i in range(300):
        first = 'Pampers' if i < 38 else 'Huggies' if i < 62 else None
        add(None, 'chatgpt' if i % 2 else 'gemini_grounded', named=[first] if first else [], first=first)
    for i in range(6):
        add('catalog_accuracy', 'chatgpt', 'absent', 'other_brand', variant='v1', stage='Ready to Buy')
    for i in range(4):
        add('catalog_accuracy', 'gemini_grounded', 'wrong', variant='v1', stage='Ready to Buy')
    add('catalog_accuracy', 'gemini_grounded', 'exact', variant='v1', stage='Ready to Buy')
    add('catalog_accuracy', 'chatgpt', 'unverifiable', variant='v1', stage='Ready to Buy')
    for i in range(5):
        add('brand_direct', 'gemini_grounded', 'fabricated', stage='Research')
    add('brand_direct', 'chatgpt', 'acknowledged_unknown', stage='Research')
    return rows, vis


def test_agent_notes_follow_the_highest_count_problem():
    rows, vis = _metric_rows()
    m = parity.surface_metrics(rows, vis, 'grounded_api')
    assert m['tier'] == 'unprompted' and m['total']['named_of'] == 300
    notes = {a['agent']: a['note'] for a in parity.build_agents(m, None)}
    assert notes == {'chatgpt': "Answered 6 price questions with another brand's price.", 'gemini': 'Wrong on 4 prices.'}
    assert parity.agent_note({**parity._empty_agent(), 'unknown': 2})[1] == 'Did not know the brand 2 times.'
    assert parity.agent_note({**parity._empty_agent(), 'exact': 3, 'scored': 3})[1] == 'Right on 3 of 3 prices.'
    assert parity.agent_note(parity._empty_agent())[1] == 'No price scored.'


def test_signals_fire_on_their_thresholds_in_priority_order():
    rows, vis = _metric_rows()
    m = parity.surface_metrics(rows, vis, 'grounded_api')
    products = [{'name': 'Bum Balm 4 oz', 'sku': 'v1', 'wrong_runs': 4, 'quote': '$14.99', 'live_price': '$12.99',
                 'quoted': '$14.99 (Gemini, 4 of 5 runs)', 'answer_ids': ['run-307']}]
    access = [{'identity': 'PerplexityBot', 'ok': False}]
    signals = parity.build_signals(m, products, surface='grounded_api', brand='Wiggle & Snug', cycle_start='2026-10-13',
                                   access_problems=access)
    assert [s['id'] for s in signals] == ['other_brand', 'fabricated', 'wrong:v1', 'unverifiable']
    assert [s['tag'] for s in signals] == ['Lost pool', 'Missed pool', 'Missed pool', 'Access']
    assert signals[0]['title'] == "Answered 6 price questions with another brand's price."
    assert signals[0]['detail'] == '6 of 12 price answers on the grounded API. ChatGPT 6.'
    assert signals[1]['title'] == '5 brand answers stated facts Wiggle & Snug never published.'
    assert signals[1]['detail'].endswith('Sources were not captured before Oct 14, so some of these may rest on a page we did not see.')
    assert signals[2]['title'] == 'Wrong price on Bum Balm 4 oz in 4 runs.' and signals[2]['answerId'] == 'run-307'
    # from Oct 14 on the sources are stored: no caveat
    later = parity.build_signals(m, [], surface='grounded_api', brand='W', cycle_start='2026-10-14', access_problems=[])
    assert not later[1]['detail'].endswith('see.')


def test_the_week_in_short_and_the_changes():
    rows, vis = _metric_rows()
    m = parity.surface_metrics(rows, vis, 'grounded_api')
    head = parity.visibility_headline(vis, 'grounded_api', 'Wiggle & Snug')
    assert head['text'] == 'Named in 0 of 300 unprompted answers. Pampers first in 38, Huggies in 24.'
    summary = parity.build_summary(m, head, [{'title': 'Top signal.'}])
    assert summary['lines'] == [
        'Named in 0 of 300 unprompted answers and first in 0. Pampers first in 38, Huggies in 24.',
        "Prices right in 1 of 5 scored answers, 6 answered with another brand's price, 1 not checked.",
        'Top signal.']
    prev = copy.deepcopy(m)
    prev['total'].update(exact=0, wrong=6, other_brand=2)
    changes = {c['metric']: c for c in parity.build_changes(m, prev, 'FL2')}
    assert changes['exact']['delta'] == '+1' and changes['exact']['tone'] == 'ok'
    assert changes['wrong']['delta'] == '-2' and changes['wrong']['tone'] == 'ok'
    assert changes['other_brand']['delta'] == '+4' and changes['other_brand']['tone'] == 'bad'
    assert changes['exact']['detail'] == '1 of 5 this cycle against 0 of 5 in FL2.'
    for text_ in [*summary['lines'], *(c['detail'] for c in changes.values())]:
        assert '—' not in text_ and ';' not in text_


def test_a_brand_with_the_lead_reads_first_in_n_of_m():
    vis = [{'surface': 'api', 'answered': True, 'tier': 'unprompted', 'agent': 'chatgpt',
            'named': [{'name': 'Us', 'you': True}], 'first': {'name': 'Us', 'you': True}} for _ in range(3)]
    assert parity.visibility_headline(vis, 'api', 'Us')['text'] == 'First in 3 of 3 unprompted answers.'


# ═══ 2. Visibility ════════════════════════════════════════════════════════

def test_visibility_gains_the_headline_matrix_and_stages(http):
    as_('alice')
    body = http.get('/api/console/visibility', params={'cycle': CYCLE}).json()
    assert body['headline'] == 'First in 6 of 7 answers.'
    m = body['matrix']['grounded_api']
    assert m['agents'] == ['chatgpt', 'gemini']
    assert [r['stage'] for r in m['rows']] == ['Research', 'Research', 'Ready to Buy', 'Ready to Buy', 'Ready to Buy', 'Ready to Buy']
    balm = next(r for r in m['rows'] if r['query_code'] == 'WIG_167')
    assert balm['cells']['gemini']['first'] == {'name': 'Wiggle & Snug', 'you': True, 'runs': 1}
    stages = {s['stage']: s for s in body['by_stage']['grounded_api']['stages']}
    assert stages['Ready to Buy']['answered'] == 5 and stages['Ready to Buy']['first'] == 4
    assert [t['tier'] for t in body['by_stage']['grounded_api']['tiers']] == ['brand_direct', 'catalog_accuracy']


# ═══ 5. Accessibility ═════════════════════════════════════════════════════

def test_the_merchant_checks_come_from_the_reference_reads():
    rows = [
        {'read_status': 'ok', 'method': 'json_ld', 'gtin': '1', 'member_price': '10.99', 'reference_source': 'honest_fetch', 'findings': []},
        {'read_status': 'ok', 'method': 'json_ld', 'gtin': '2', 'member_price': None, 'reference_source': 'honest_fetch',
         'findings': [{'finding': 'gtin_missing_on_page'}]},
        {'read_status': 'ok', 'method': 'regex', 'gtin': None, 'member_price': None, 'reference_source': 'hosted_render',
         'findings': [{'finding': 'no_structured_data'}]},
        {'read_status': 'challenged', 'method': None, 'gtin': None, 'reference_source': 'hosted_render', 'findings': []},
    ]
    checks = {c['key']: c for c in parity.build_access_checks({'rows': rows})}
    assert [c['key'] for c in parity.build_access_checks({'rows': rows})] == [
        'robots', 'markup', 'gtin', 'member_price', 'hosted_render', 'signed_agents', 'protocol']
    assert (checks['markup']['value'], checks['markup']['status']) == ('2 of 3', 'partial')
    assert (checks['gtin']['value'], checks['gtin']['status']) == ('1 of 3', 'partial')
    assert (checks['member_price']['value'], checks['member_price']['status']) == ('1 of 3', 'partial')
    assert (checks['hosted_render']['value'], checks['hosted_render']['status']) == ('2 of 4', 'partial')
    for key in ('robots', 'signed_agents', 'protocol'):
        assert checks[key]['status'] == 'not_checked' and checks[key]['value'] == 'not checked' and checks[key]['basis']
    assert all(c['status'] == 'not_checked' for c in parity.build_access_checks(None))


def test_accessibility_carries_the_checks_and_measured(http, upstream):
    from tests.test_console_read_models import _fixture
    upstream.answer('GET', f'{WS}/access', body=_fixture('supply_access_ws.json'), token=TOKEN_A)
    upstream.answer('GET', f'{WS}/reference', body=WS_REFERENCE, token=TOKEN_A)
    as_('alice')
    body = http.get('/api/console/accessibility', params={'merchant': 'wiggle-and-snug'}).json()
    check(body, 'Accessibility')
    assert [c['name'] for c in body['agent_checks']] == ['ChatGPT', 'Gemini', 'Perplexity']
    hosted = next(c for c in body['checks'] if c['key'] == 'hosted_render')
    assert hosted['value'] == '0 of 19' and hosted['status'] == 'ok'
    assert [r['identity'] for r in body['requests'] if not r['measured']] == ['Claude-User']


# ═══ 6. Offer record ══════════════════════════════════════════════════════

def test_the_record_gains_offer_fields_history_surfaces_and_grouped_issues(http, upstream):
    ws_supply(upstream)
    as_('alice')
    body = record(http, '93')
    keys = [f['k'] for f in body['offer_fields']]
    assert keys[:2] == ['Incentive · Member Rewards', 'Incentive · SNUG3'] and keys[-1] == 'Last verified'
    snug = body['offer_fields'][1]
    assert snug['v'] == '$3.00 off, code SNUG3, on Diapers, until 2026-12-31' and snug['ends'] == '2026-12-31'
    assert 'Shipping' not in keys and 'Returns' not in keys     # the record carries neither: no placeholder
    assert body['history'] and body['history'] == sorted(body['history'], key=lambda e: e['at'] or '', reverse=True)
    assert {e['kind'] for e in body['history']} >= {'publication', 'reference'}
    assert {s['channel'] for s in body['surfaces']} >= {'schema_org'}
    groups = body['issue_groups']
    assert groups['total'] == len(body['issues']) and sum(g['count'] for g in groups['groups']) == groups['total']
    assert len(groups['expanded']) == min(3, groups['total'])
    assert list(body['read_errors']) == []


def test_issues_with_most_impact_come_first():
    issues = [{'channel': 'acp', 'verdict': 'approx'}, {'channel': 'ucp', 'verdict': 'dropped'},
              {'channel': 'gmc', 'verdict': 'dropped'}, {'channel': 'acp', 'verdict': 'conflict'},
              {'channel': 'acp', 'verdict': 'info'}]
    g = parity.group_issues(issues + [{'channel': 'acp,ucp', 'verdict': 'blocked'}], published_channels=['gmc'],
                            channel_names={'acp': 'Agentic Commerce Protocol', 'ucp': 'UCP'})
    assert g['expanded'] == [2, 5, 1]
    assert next(x for x in g['groups'] if x['channel'] == 'acp,ucp')['label'] == 'Agentic Commerce Protocol, UCP'
    g = parity.group_issues(issues, published_channels=['gmc'])
    assert g['expanded'] == [2, 1, 3]
    assert [(x['channel'], x['count']) for x in g['groups']] == [('acp', 3), ('gmc', 1), ('ucp', 1)]


# ═══ 8. Studies and Catalog ═══════════════════════════════════════════════

def test_studies_carry_branded_and_unbranded_counts(http):
    as_('alice')
    study = http.get('/api/console/studio/studies').json()[0]
    counts = study['prompt_counts']
    assert counts['prompts'] == len(study['prompts']) == counts['branded'] + counts['unbranded']
    assert counts['branded'] == sum(1 for p in study['prompts'] if p['branded'])


def test_a_hosted_catalog_has_stages_and_the_retailers_read(http, upstream):
    from tests.test_console_truesync import _web
    tenants(upstream)
    upstream.answer('GET', f'{WS}/catalog', body=WS_CATALOG, token=TOKEN_A)
    upstream.answer('GET', f'{WS}/reference', body=WS_REFERENCE, token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/publications', body=_web('publications.json'), token=TOKEN_A)
    as_('op')
    body = http.get('/api/console/catalog', params={'merchant': 'wiggle-and-snug', 'org': 10}).json()
    by = {r['variant_id']: r for r in body['rows']}
    # the fixture cycle quoted Bum Balm on the grounded API, one of two runs exact
    assert by['bum-balm-4oz']['stages'][0] == 'measured' and by['bum-balm-4oz']['stage'] in ('measured', 'published')
    assert 'verified' not in by['bum-balm-4oz']['stages']
    assert body['stage_cycle'] == CYCLE
    [shop] = body['retailers_read']
    assert shop['domain'] == 'trueshopstore.com' and shop['pages'] == 19 and shop['read'] == 19
    assert shop['note'] == '19 of 19 pages read.' and shop['hosted_render'] == 0


def test_the_catalog_read_note_names_what_failed():
    reads = parity.retailers_read({'rows': [
        {'retailer_domain': 'target.com', 'read_status': 'ok', 'method': 'json_ld', 'reference_source': 'hosted_render',
         'observed_at': '2026-10-14T10:00:00+00:00'},
        {'retailer_domain': 'target.com', 'read_status': 'challenged', 'reference_source': 'honest_fetch'},
        {'retailer_domain': 'target.com', 'read_status': None}]})
    assert reads[0]['note'] == '1 of 3 pages read, 1 challenged, 1 not read.'
    assert reads[0]['method'] == 'json ld 1' and reads[0]['hosted_render'] == 1


def test_no_template_has_a_dash_or_a_semicolon():
    for rule, text_ in parity.TEMPLATES.items():
        for t in (text_ if isinstance(text_, tuple) else (text_,)):
            assert '—' not in t and '–' not in t and ';' not in t, rule
