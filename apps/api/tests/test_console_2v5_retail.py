"""
2V-5: the retail read-outs that still read wrong after 2V-4, on Petco's
second cycle (org 11, 82 questions x 6 agents, 492 answers, feed v4).

On 2V-4's recording (tests/fixtures/console/supply_2v4/PROVENANCE.md: supply
`main` at 13c9c80, four SKUs) served through 2V-2's harness, plus answers
and feed fields written here, said so where they are: the pair's answers are
about diapers, and the recording's feed has no GTIN on any SKU while the live
v4 feed has one on nine of ten.
"""
import copy
import json
import os

from app.services import console_brand_overview as bo
from app.services import console_parity as parity
from app.services import console_read_models as rm
from app.services import console_retail as rt
from app.services import console_seller as cs
from tests import test_console_2v2_seller as t2v2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import WS, _get, _pair, f2p1
from tests.test_console_read_models import TOKEN_A, as_, http, upstream  # noqa: F401  (pytest fixtures)

SLUG = t2v2.SLUG
PRO_PLAN = '2579466'
#: written here: the live v4 feed's GTIN for Pro Plan 30 lb, as supply's reference read states it (12 digits)
PRO_PLAN_GTIN = '038100175526'


def _dump(name, body):
    """SOA_2V5_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2V5_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


def _paths():
    return cs.paths_by_sku(t2v2.recorded('price-paths'))


def _row(sku):
    return next(r for r in _paths() if r['sku'] == sku)


# ─── W1: Products this week, named ────────────────────────────────────────

def test_w1_a_gtin_row_is_named_as_the_record_names_it():
    """The Overview's product rows key a GTIN row by the GTIN supply's reference read states (12 or 13 digits,
    build_true_value), name_products keyed the feed by GTIN-14: only the GTIN-less row was named."""
    feed = copy.deepcopy(t2v2.recorded('feed')['rows'])
    feed[0]['gtin'], feed[0]['gtin14'] = PRO_PLAN_GTIN, '00' + PRO_PLAN_GTIN   # written here: v4 carries a GTIN
    products = [{'sku': PRO_PLAN_GTIN, 'name': '30 lb'}, {'sku': '3879911', 'name': '6 chews'},
                {'sku': '00' + PRO_PLAN_GTIN, 'name': '30 lb'}]
    named = bo.name_products(products, feed)
    assert [p['name'] for p in named] == ['Purina Pro Plan Sensitive Skin & Stomach Salmon & Rice, 30 lb',
                                          'NexGard PLUS Chewables for Dogs 33.1-66 lb, 6 chews',
                                          'Purina Pro Plan Sensitive Skin & Stomach Salmon & Rice, 30 lb']
    # a row the feed does not hold keeps its label
    assert bo.name_products([{'sku': 'v1', 'name': 'Size 1, 96 ct'}], feed)[0]['name'] == 'Size 1, 96 ct'


# ─── W2: one count of the tiers ───────────────────────────────────────────

#: written here: Petco's cycle 2 in shape, 82 questions x 6 agents (four API agents, two consumer surfaces)
AGENTS = (('chatgpt', 'grounded_api'), ('claude', 'grounded_api'), ('gemini', 'grounded_api'),
          ('perplexity', 'grounded_api'), ('aimode', 'consumer_ui'), ('copilot', 'consumer_ui'))
QUESTIONS = (('category_control', None, 18), ('brand_direct', None, 12), ('catalog_accuracy', None, 12),
             ('value_incentives', None, 10), ('comparison', None, 10), ('brand_direct', 'where_to_buy', 10),
             ('brand_direct', 'cheapest_place', 10))


def _cycle_rows():
    rows = []
    for tier, intent, n in QUESTIONS:
        for _q in range(n):
            for platform, surface in AGENTS:
                rows.append({'tier': tier, 'intent': intent, 'platform': platform, 'surface': surface,
                             'answer_status': 'answered', 'outcome': 'grounded' if tier == 'brand_direct' else 'exact',
                             'reason_code': None, 'flags': None})
    return rows


def _all(tier):
    return next(c for c in tier['surfaces'] if c['surface'] == 'all')


def test_w2_the_tiers_sum_to_the_cycles_answers():
    rows = _cycle_rows()
    assert len(rows) == 492
    body = rm.build_answers_summary(rows, cycle_code='C2', catalog_in_tier=True)
    tiers = {t['tier']: _all(t) for t in body['tiers']}
    assert [t['tier'] for t in body['tiers']] == ['brand_direct', 'catalog_accuracy', 'value_incentives',
                                                  'category_control', 'comparison']
    assert {k: c['answered'] for k, c in tiers.items()} == {
        'brand_direct': 192, 'catalog_accuracy': 72, 'value_incentives': 60, 'category_control': 108, 'comparison': 60}
    assert sum(c['answered'] for c in tiers.values()) == 492 == body['all_tiers'][0]['answered']
    # Visibility's "By tier" counts a run by its tier: brand-direct 192, the same count
    assert tiers['brand_direct']['answered'] == sum(1 for r in rows if r['tier'] == 'brand_direct')
    # the verdicts stay the AI-written questions' (2N-1); the catalog-built ones are named
    assert tiers['brand_direct']['counts'] == {'grounded': 72} and tiers['brand_direct']['catalog_built'] == 120
    # each surface's row sums too
    api = next(c for c in body['tiers'][0]['surfaces'] if c['surface'] == 'grounded_api')
    assert api['answered'] == 128 and api['catalog_built'] == 80


def test_w2_a_brands_summary_is_unchanged():
    body = rm.build_answers_summary(_cycle_rows(), cycle_code='C2')
    assert _all(next(t for t in body['tiers'] if t['tier'] == 'brand_direct'))['answered'] == 72


def test_w2_the_route_counts_a_sellers_catalog_built_answers(http, db, upstream):
    t2v2._shape(db, http, upstream)
    as_('op')
    seller = http.get('/api/console/answers/summary', params={'org': 10, 'cycle': f2p1.CYCLE_2, 'merchant': SLUG}).json()
    _dump('answers-summary-2v5.json', seller)
    total = seller['all_tiers'][0]['answered']
    assert sum(_all(t)['answered'] for t in seller['tiers']) == total


# ─── W3: the workspace's counts are the compiler's lines ──────────────────

def test_w3_the_workspace_counts_the_lines_the_compiler_block_renders(http, db, upstream):
    t2v2._shape(db, http, upstream)
    body = t2v2._read(http, 'truesync')
    _dump('truesync-2v5.json', body)
    held = {c['channel'] for c in body['channels'] if c['state'] == 'held'}
    marks = [l['mark'] for r in body['products'] for c in r['compiler'] if c['channel'] in held for l in c['lines']]
    w = body['workspace']
    assert w['fields'] == {k: marks.count(k) for k in ('carried', 'approximated', 'dropped')}
    # GMC's later steps and ongoing are dropped lines on screen, so the tile is not 0
    assert w['fields']['dropped'] > 0
    gmc = next(c for c in next(r for r in body['products'] if r['sku'] == PRO_PLAN)['compiler']
               if c['channel'] == 'merchant_center')
    assert {l['field']: l['mark'] for l in gmc['lines']}['price_path.later_steps'] == 'dropped'
    # what the compiled tile counts: one file per SKU per surface in the pass (6 held, MCP live)
    assert w['compiled'] == {'n': 28, 'of': 28}
    assert w['compiled_label'] == 'SKU files compiled (4 SKUs × 7 surfaces)'
    assert w['fields_label']['dropped'] == 'dropped by spec'


# ─── W4: drift reads the answers coded to the SKU ─────────────────────────

#: written here: price answers as Petco's cycle 2 had them, each with the product its question is coded to
PRICE_ANSWERS = [
    {'run_id': 1, 'agent': 'chatgpt', 'keys': ['sku:2579466'],
     'text': 'Purina Pro Plan Sensitive Skin & Stomach Salmon & Rice 30 lb is $77.99, or $46.79 on a first Autoship order.'},
    {'run_id': 2, 'agent': 'claude', 'keys': ['sku:2579466'],
     'text': 'Petco sells Purina Pro Plan Sensitive Skin & Stomach 30 lb for $77.99.'},
    {'run_id': 3, 'agent': 'perplexity', 'keys': ['sku:2579470'],
     'text': 'Purina Pro Plan Sensitive Skin & Stomach 47 lb: $96.48 at Amazon, $96.48 at Chewy, $96.48 at Walmart.'},
    {'run_id': 4, 'agent': 'gemini', 'keys': [],
     'text': 'Purina Pro Plan runs $96.48 for the large bag; Tidy Cats LightWeight is $25 and Greenies $71.48.'},
    {'run_id': 5, 'agent': 'copilot', 'keys': ['sku:3089211'],
     'text': 'Tidy Cats LightWeight 24/7 Performance 17 lb is $28.98, or $17.39 for a first Autoship.'},
    {'run_id': 6, 'agent': 'aimode', 'keys': ['sku:3089211'], 'text': 'Tidy Cats LightWeight is $25 at Walmart.'},
]


def test_w4_drift_rows_are_the_answers_coded_to_the_sku():
    pro = rt.drift_lines(_row(PRO_PLAN), PRICE_ANSWERS, 'Autoship')
    assert [(l['agent'], l['said'], l['verdict']) for l in pro] == [('claude', '$77.99', 'partial'),
                                                                     ('chatgpt', '$77.99, $46.79', 'right')]
    tidy = rt.drift_lines(_row('3089211'), PRICE_ANSWERS, 'Autoship')
    assert [(l['agent'], l['verdict']) for l in tidy] == [('aimode', 'wrong'), ('copilot', 'right')]
    # before: the product name's first words joined the 47 lb bag's and a comparison's prices to the 30 lb row
    assert sum(1 for a in PRICE_ANSWERS if cs.mentions(a, _row(PRO_PLAN))) == 4
    assert sum(1 for a in PRICE_ANSWERS if cs.mentions(a, _row('3089211'))) == 3


def test_w4_the_readback_denominator_is_the_drift_rows():
    lines = rt.drift_lines(_row(PRO_PLAN), PRICE_ANSWERS, 'Autoship')
    (readback,) = [e for e in rt.sku_timeline({}, name='Petco', held=None, lines=lines,
                                              cycle={'start_date': '2026-10-30', 'cycle_code': 'C2'}, pubs=[])]
    assert readback['what'] == 'Read back: prices right 1 of 2'


def test_w4_a_questions_subject_is_its_source():
    assert cs.subject_keys({'variant_id': 'sku:2579466', 'sku': '2579466', 'intent': 'where_to_buy'}) == \
        ['2579466', 'sku:2579466']
    keys = cs.subject_keys({'gtin': PRO_PLAN_GTIN})
    assert cs.coded_to({'keys': keys}, {'sku': '9', 'variant_id': 'sku:9', 'gtin': '00' + PRO_PLAN_GTIN})
    assert not cs.coded_to({'keys': []}, _row(PRO_PLAN))


# ─── W5: who approved the release ─────────────────────────────────────────

def _rules(signed, by='elton@parleo.io'):
    rules = copy.deepcopy(t2v2.recorded('rules')['rules'])
    for r in rules:
        on = r['code'] in signed
        r.update(approval='approved' if on else 'needs_approval', approved_by=(by(r['code']) if callable(by) else by)
                 if on else None)
    return rules


def test_w5_the_release_names_its_signer_or_how_many_signed(http, db, upstream):
    assert rt.approved_by(_rules(rt.SELLER_RULES)) == 'elton@parleo.io'
    assert rt.approved_by(_rules(('s1', 's2'))) == '2 of 6 signed'
    assert rt.approved_by(_rules(rt.SELLER_RULES, by=lambda c: 'gabe@petco.com' if c == 's6' else 'elton@parleo.io')) \
        == '6 of 6 signed'
    assert rt.approved_by(_rules(())) is None
    t2v2._shape(db, http, upstream)
    release = t2v2._read(http, 'truesync')['release']
    assert release['approved_by'] == '5 of 6 signed' and release['requested'] == 'parleo'


# ─── V1 to V4: the programs block and the ladder ──────────────────────────

def test_v_one_line_per_program_entry_from_the_2v1_shape():
    owned = t2v2.recorded('incentives-owned')['incentives']
    progs = cs.build_programs(owned=owned, paths=_paths(), answers=[], merchant='Petco')
    assert [(p['name'], p['text']) for p in progs] == [
        ('Petco Perks', 'All SKUs. Tier Premier. Formerly Vital Care and Repeat Delivery. Funder not stated. '
                        'Not combinable with other offers. No end date.'),
        ('Petco Autoship', 'All SKUs. 1st order 35% off, capped at $20; ongoing 5% off. Rx excluded on the 1st order. '
                           'Funder not stated. Not combinable with other offers. No end date.'),
        ('Petco Autoship', '2 SKUs. 1st order 40% off; 2nd order 20% off; 3rd order 10% off; ongoing 5% off. '
                           'Funded by Purina. Not combinable with other offers. Ends Oct 31.'),
        ('Perks Premier', 'Dog > Food, Cat > Food. Premier members 10% off. Funder not stated. '
                          'Not combinable with other offers. No end date.')]
    assert [p['valid_until'] for p in progs] == [None, None, '2026-10-31', None]
    assert [p['scope'] for p in progs] == ['all SKUs', 'all SKUs', '2 SKUs', 'Dog > Food, Cat > Food']


def test_v_a_loyalty_program_lists_its_tiers_points_and_former_names():
    """Written here: v4's Petco Perks, three tiers, 10 points, formerly Vital Care. 2V-3 Q7: the tier joins the
    name only because the three entries share it."""
    base = next(e for e in t2v2.recorded('incentives-owned')['incentives'] if e['mechanic'] == 'loyalty_program')
    tiers = [{**base, 'id': i, 'tier_name': t, 'points': '10', 'former_names': ['Vital Care']}
             for i, t in enumerate(('Classic', 'Premier', 'Gold'))]
    progs = cs.build_programs(owned=tiers, paths=[], answers=[], merchant='Petco')
    assert [p['name'] for p in progs] == ['Petco Perks · Classic', 'Petco Perks · Premier', 'Petco Perks · Gold']
    assert progs[1]['text'] == ('All SKUs. Tier Premier. 10 points. Formerly Vital Care. Funder not stated. '
                                'Not combinable with other offers. No end date.')


def test_v3_the_ladder_reads_the_price_path_with_no_funder():
    """v4 has no `funded_by` anywhere (by decision): the ladder still reads the path, list to member."""
    paths = _paths()
    for r in paths:
        for s in (r['price_path'].get('steps') or []) + [r['price_path'].get('ongoing') or {}]:
            s.pop('funded_by', None)
    assert cs.build_ladder(paths=[{**r, 'price_path': {**r['price_path'], 'steps': []}} for r in paths[:0]],
                           answers=[], name='Petco') is None
    ladder = cs.build_ladder(paths=paths, answers=[], name='Petco')
    assert ladder['title'] == 'Autoship prices at Petco' and ladder['sku'] == PRO_PLAN
    assert [f"{s['label']} {s['value']}" for s in ladder['steps']] == [
        'List $77.99', '1st order, 40% $46.79', '2nd order, 20% $62.39', '3rd order, 10% $70.19', 'Ongoing, 5% $74.09',
        'Perks Premier, 10% off, Premier members only $70.19']
    # the receipt beneath it is the same SKU
    assert cs.build_receipt(paths=paths, merchant='Petco')['sku'] == ladder['sku']
    greenies = cs.build_ladder(paths=paths, answers=[], name='Petco', sku='2174511')
    assert [s['value'] for s in greenies['steps']] == ['$39.99', '$25.99', '$37.99']
    flat = [{**r, 'price_path': {'list_price': r['price_path']['list_price'], 'steps': []}} for r in paths]
    assert cs.build_ladder(paths=flat, answers=[], name='Petco') is None


def test_v_true_value_serves_the_lines(http, db, upstream):
    t2v2._shape(db, http, upstream)
    body = t2v2._read(http, 'true-value', cycle=f2p1.CYCLE_2)
    _dump('true-value-2v5.json', body)
    assert [p['scope'] for p in body['programs']] == ['all SKUs', 'all SKUs', '2 SKUs', 'Dog > Food, Cat > Food']
    assert body['ladder']['sku'] == PRO_PLAN and sorted(body['ladders']) == sorted(r['sku'] for r in _paths())


def test_v_wiggle_and_snugs_member_rewards_line_is_pinned(http, db, upstream):
    _pair(db, http, upstream)
    progs = _get(http, 'true-value', merchant=WS)['programs']
    member = [(p['name'], p['terms'], p['agentsRight'], p.get('text')) for p in progs
              if p['name'].startswith('Member Rewards')]
    # as main serves them (read on main at 5f2a6dc); the console renders `terms` when soa sends no `text`
    assert member == [('Member Rewards Member+', 'Member+ discount, stated without a price', 'not asked this cycle', None),
                      ('Member Rewards points', 'points on 19 offers', 'not asked this cycle', None)]


# ─── W6: the live price says when it was read ─────────────────────────────

def test_w6_a_sellers_live_price_says_last_read():
    cell = {'live': '$77.21', 'reference_source': 'hosted_render', 'observed_at': '2026-10-29T12:00:00+00:00'}
    assert parity._live_text(cell, 'petco.com', last_read=True) == '$77.21 at petco.com, last read Oct 29 (hosted render)'
    # a brand's, and a hosted seller's, as before
    assert parity._live_text(cell, 'petco.com') == '$77.21 at petco.com, a hosted render, Oct 29'


def test_w6_the_retail_overview_words_its_live_prices(http, db, upstream):
    t2v2._shape(db, http, upstream)
    as_('op')
    body = http.get('/api/console/overview', params={'merchant': SLUG, 'org': 10, 'cycle': f2p1.CYCLE_2}).json()
    lives = [p['live'] for p in body['by_surface']['all']['products'] if p.get('live')]
    assert lives and all('last read' in v for v in lives if ' at ' in v)
    assert not any(', our own fetch, ' in v or ', a hosted render, ' in v for v in lives)
