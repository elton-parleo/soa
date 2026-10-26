"""
2T-1: the Overview and TrueSync read models for a brand at retail, to the
console demo's shape, on 2P-1's pair (cycle 229 Oct 14, cycle 230 Oct 21)
with supply's answers RECORDED from parleo-supply-app#33 (console_fixture_2r2;
tests/fixtures/console/supply_2r1/PROVENANCE.md), its /deals included
(deals-20261020.json, deals-20261021.json: #33's merchant has no live deal,
its retailer rows were never read). sqlite and Postgres.

The pair's own supply answers (the /reference attributes, its /deals) are
served for #33's merchant too (console_fixture_2r2.alias), as 2R-2's tests
do. A state neither produced (a club-only line, another merchant's hold) is
derived from the recorded rows in the test that needs it, and says so.
"""
import copy
import json
import os

from app.services import console_brand_overview as bo
from app.services import console_cache
from app.services import console_release as rel
from tests import console_fixture_2p1 as f2p1
from tests import console_fixture_2r2 as f2r2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import _pair
from tests.test_console_read_models import TOKEN_A, as_, http, upstream  # noqa: F401  (pytest fixtures)

SLUG, BASE = f2r2.SLUG, f2r2.BASE


def _shape(db, http, upstream, sent=None):
    _pair(db, http, upstream)
    f2r2.retag(db)
    f2r2.alias(upstream)
    return f2r2.answer(upstream, sent=sent)


def _read(http, endpoint, merchant=SLUG, status=200, **params):
    as_('op')
    r = http.get(f'/api/console/{endpoint}', params={'merchant': merchant, 'org': 10, **params})
    assert r.status_code == status, r.text
    return r.json()


def _overview(http, **kw):
    return _read(http, 'overview', cycle=f2p1.CYCLE_2, **kw)


def _dump(name, body):
    """SOA_2T1_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2T1_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


def _held_rows():
    return f2r2.mine(f2r2.body('publications-held'))


# ── B1: the charter is the score's tiles ─────────────────────────────────

def test_the_charter_numbers_equal_the_score_tiles(http, db, upstream):
    _shape(db, http, upstream)
    overview = _overview(http)
    score = _read(http, 'score', cycle=f2p1.CYCLE_2)
    _dump('overview-2t1.json', overview)
    _dump('score-2t1.json', score)
    tiles = {m['key']: m for m in score['metrics_by_kind']['brand']}
    charter = {t['key']: t for t in overview['charter']}
    assert list(charter) == ['attribute', 'coverage', 'presence', 'promo']
    for key, tile in charter.items():
        assert (tile['value'], tile['of'], tile['delta'], tile['state']) == \
            (tiles[key]['value'], tiles[key]['denominator'], tiles[key]['delta'], tiles[key]['state']), key
    counts = score['metric_counts'][score['metric_surface']]
    a = counts['attribute']
    assert charter['attribute']['second_line'] == (f"Retailer pages got it right {a['pages']['k']} of {a['pages']['n']} "
                                                   f"times and agent answers {a['answers']['k']} of {a['answers']['n']}.")
    assert charter['attribute']['big'] == f"{round(a['value'] * 100 / a['of'])}%"
    p = counts['presence']
    assert (charter['presence']['big'], charter['presence']['first']) == (str(p['first']), p['first'])
    assert charter['presence']['second_line'] == f"{p['rival']['name']} came first in {p['rival']['first']} of the same answers."
    deal = counts['promo']['deal']
    assert charter['promo']['second_line'] == \
        f"Amazon ran a {deal['kind_label']} on 5 SKUs, and {deal['named']} of {deal['asked']} answers on them named it."
    # no club-only line in #33's feed: the coverage tile has no second line, never an invented one
    assert charter['coverage']['second_line'] is None


# ── B2: signals ranked by pool, the lead follows the top one ─────────────

def test_signals_are_ranked_by_pool_then_count_and_the_existing_keep_their_place(http, db, upstream):
    _shape(db, http, upstream)
    overview = _overview(http)
    ranked = overview['by_surface']['all']['signals']
    revenue = overview['revenue']
    values = {'lost': revenue['shares']['lost'], 'missed': revenue['shares']['missed'], 'root': 0.0}
    keys = [(-values[s['pool']], -s['count']) for s in ranked]
    assert keys == sorted(keys)
    assert [s['rank'] for s in ranked] == list(range(1, len(ranked) + 1))
    kinds = {s['id']: s['kind'] for s in ranked}
    # the existing three are all still there, beside the new generators the pair's data gives
    assert {'other_brand', 'fabricated', 'unverifiable'} <= set(kinds)
    assert {kinds['retired'], kinds['size_chart']} == {'retired', 'size_chart'}
    assert any(k == 'deal' for k in kinds.values())
    retired = next(s for s in ranked if s['kind'] == 'retired')
    line = overview['retired_named']['lines'][0]
    assert retired['title'] == (f"Agents named Pure {line['brand_choice']['all']['named']} times and AMORE "
                                f"{line['brand_choice']['all']['successor_named']} times.")
    size = next(s for s in ranked if s['kind'] == 'size_chart')
    assert size['title'] == 'pampers.com runs two Size 4 charts, and agents repeat both.'
    # the lead reads the same ranked list
    assert (overview['lead']['signal'], overview['lead']['kind']) == (ranked[0]['id'], ranked[0]['kind'])


def test_the_lead_headline_follows_the_top_signal(http, db, upstream):
    """Each kind the brief names, made top by its pool: the headline and the two tiles are that signal's."""
    _shape(db, http, upstream)
    overview = _overview(http)
    signals = overview['by_surface']['all']['signals']
    totals = overview['by_surface']['all']['totals']
    promo = overview['promo_pass_through']
    ws = _read(http, 'truesync')['workspace']
    for kind, headline in (
            ('size_chart', 'Agents read Pampers from sources that disagree, pampers.com included. One push of one '
                           'record fixes every surface.'),
            ('retired', 'Agents still send shoppers to Pure, which pampers.com retired, and seldom to AMORE. One push of '
                        'one record fixes every surface.'),
            ('deal', None), ('price', None)):
        top = next(s for s in signals if s['kind'] == kind)
        lead = bo.build_lead([top] + [s for s in signals if s is not top], brand='Pampers', name='Pampers 2R-1',
                             domain='pampers.com', totals=totals, promo=promo, workspace=ws)
        assert (lead['kind'], lead['signal']) == (kind, top['id'])
        if headline:
            assert lead['headline'] == headline
        assert len(lead['facts']) == 2 and lead['owner'] is None
        assert lead['do'] == ("Compile one Pampers record per SKU and hold it for Pampers 2R-1's team to send: Site "
                              "markup and Manufacturer Center.")
    size = next(s for s in signals if s['kind'] == 'size_chart')
    lead = bo.build_lead([size], brand='Pampers', name='Pampers 2R-1', domain='pampers.com', totals=totals, promo=promo,
                         workspace=ws)
    first, second = lead['facts']
    assert first['who'] == 'Swaddlers Size 4 weight range' and first['of'] == 'ranges'
    assert first['cap'].startswith('pampers.com says 15 to 34 lb, ')
    assert first['value'] == len(first['sources'])
    assert second['who'] == 'pampers.com markup' and second['value'] == len(second['lines'])
    assert second['cap'].startswith("where pampers.com's own markup contradicts its size chart: ")
    deal = next(s for s in signals if s['kind'] == 'deal')
    lead = bo.build_lead([deal], brand='Pampers', name='Pampers 2R-1', domain='pampers.com', totals=totals, promo=promo,
                         workspace=ws)
    f = deal['facts']
    assert lead['headline'] == (f"{f['deal']} ran on {f['skus']} SKUs and {f['named']} of {f['asked']} answers named it. "
                                "Deals stop at the retailer page until one record carries them.")
    assert (lead['facts'][1]['value'], lead['facts'][1]['of']) == (promo['k'], f"of {promo['n']}")


# ── B1: the TrueSync card is TrueSync's own workspace ────────────────────

def test_the_truesync_card_and_the_workspace_count_the_held_rows(http, db, upstream):
    _shape(db, http, upstream)
    card = _overview(http)['truesync_card']
    ts = _read(http, 'truesync')
    _dump('truesync-2t1.json', ts)
    ws = ts['workspace']
    rows = _held_rows()
    held = [r for r in rows if r['reason'] == 'held_for_merchant']
    blocked = [r for r in rows if r['reason'] == 'blocked']
    records = {r['record_ref'] for r in rows}
    channels = {r['channel_slug'] for r in rows}
    assert (ws['records'], ws['compiled'], ws['blocked'], ws['published']) == \
        (len(records), {'n': len(held), 'of': len(records) * len(channels)}, len(blocked), 0)
    # 2T-3 (7): distinct fields per record over its held channels (test_console_2t3's before and after)
    assert ws['fields'] == rel._fields(rel.hold(rows).values())
    assert (ws['next_check'], ws['walled']) == (None, {'n': 0, 'domains': []})
    # the Overview's card is the same count, never a second one
    assert (card['products'], card['cells'], card['drifting'], card['surfaces']) == \
        (ws['records'], ws['compiled'], ws['disagree'], ws['surfaces'])
    assert [s['line'] for s in card['surfaces']] == ['4 of 4 compiled', '4 of 4 compiled', '0 of 4 compiled']
    assert card['mode_note'] == ("Manufacturer records compiled from the feed and pampers.com. Nothing publishes until "
                                 "Pampers' team sends it.")


# ── B3: the release page ─────────────────────────────────────────────────

def test_the_matrix_is_one_row_per_held_record_on_this_pass_s_channels(http, db, upstream):
    _shape(db, http, upstream)
    ts = _read(http, 'truesync')
    rows = _held_rows()
    assert [p['record_ref'] for p in ts['products']] == list(dict.fromkeys(
        r['record_ref'] for r in sorted(rows, key=lambda r: r['id'])))
    assert len(ts['products']) == len({r['record_ref'] for r in rows})
    assert ts['pass_channels'] == ['schema_org', 'manufacturer_center', 'acp']
    assert [c['id'] for c in ts['channels']] == ts['pass_channels']   # no Merchant Center, no deal directory
    assert ts['cell_states'] == ['held', 'published', 'blocked', 'na']
    cells = {p['name']: {k: c['s'] for k, c in p['cells'].items()} for p in ts['products']}
    assert set(cells) == {'Pampers Swaddlers', 'Pampers Pure Protection', 'Pampers AMORE', 'Pampers Zzz'}
    assert {tuple(c.values()) for c in cells.values()} == {('held', 'held', 'blocked')}
    by = {p['name']: p for p in ts['products']}
    assert by['Pampers Zzz']['sub'] == 'Size 4, 104 ct, 22 to 37 lb'
    assert by['Pampers Swaddlers']['sub'] == 'Newborn, 84 ct, under 10 lb · Size 1, 96 ct, 8 to 14 lb · Size 4, 15 to 34 lb'
    assert (by['Pampers Pure Protection']['retired'], by['Pampers Pure Protection']['successor']) == (True, 'Pampers AMORE')
    # the blocked cell carries supply's clause
    assert by['Pampers Zzz']['cells']['acp']['note'] == f2r2.body('artifact-acp')['detail']['spec_clause']
    assert 'diff' not in ts   # it stays on /publishing
    assert _read(http, 'publishing')['diff']


def test_a_record_its_readback_timeline_and_compiler(http, db, upstream):
    _shape(db, http, upstream)
    zzz = next(p for p in _read(http, 'truesync')['products'] if p['name'] == 'Pampers Zzz')
    record = {f['k']: f for f in zzz['record']}
    assert record['GTIN']['v'] == '037000833970 (feed)'
    assert record['Size and weight']['v'] == 'Size 4, 22 to 37 lb'
    assert (record['Price']['v'], record['Price']['prov']) == ('Not set. Retailers price it', 'parleo')
    assert record['Claims']['note'] == 'pampers.com, Oct 20' and record['Claims']['prov'] == 'brand'
    # #33 never read the retailer pages: listed, not read, and never "not carried"
    assert record['Where to buy']['v'] == 'Amazon, Target and Walmart listed. Not read yet'
    assert record["Couldn't read"]['v'] == 'Amazon, Target and Walmart: not read yet'
    assert 'Not carried' not in record and record['Not in the feed']['v'] == "Sam's Club"
    # the readback: the cycle's weight answers on Zzz Size 4, against the chart's 22 to 37 lb
    weights = [l for l in zzz['drift_all'] if l['fact'] == 'weight']
    assert {l['truth'] for l in weights} == {'22 to 37 lb'}
    wrong = sorted(l['agent'] for l in weights if l['verdict'] == 'wrong')
    assert zzz['disagree'] == {'agents': len(wrong), 'of': 6, 'which': wrong}
    assert zzz['drift'][:len(wrong)] == [l for l in zzz['drift_all'] if l['verdict'] == 'wrong']
    assert [e['what'] for e in zzz['timeline']] == [
        'pampers.com read: the size chart, the claims and the markup',
        f"Read back: weight right {len(weights) - len(wrong)} of {len(weights)}",
        'Compiled in manufacturer mode. Held on Site markup and Manufacturer Center, blocked on ACP feed. '
        'Nothing published']
    compiler = {c['channel']: c for c in zzz['compiler']}
    assert compiler['manufacturer_center']['spec_version'] == 'manufacturers-v1-2026-10-05'
    # 2T-3 (6): r1 and r5 apply to Manufacturer Center; #33's rules are all off, so none is applied
    assert (compiler['manufacturer_center']['rules_relevant'], compiler['manufacturer_center']['rules_applied']) == \
        (['r1', 'r5'], [])
    assert compiler['manufacturer_center']['lines'][0]['mark'] == 'carried'
    assert {l['mark'] for l in compiler['acp']['lines']} <= {'carried', 'info', 'approximated', 'conflict', 'dropped'}
    assert compiler['acp']['state'] == 'blocked'


def test_the_release_releases_and_destinations(http, db, upstream):
    _shape(db, http, upstream)
    ts = _read(http, 'truesync')
    release = ts['release']
    assert (release['name'], release['status'], release['approved_by'], release['requested'], release['rules_on']) == \
        ('Four records, Manufacturer Center first', 'Compiled, held', None, 'parleo', {'on': 0, 'of': 6})
    assert [(s['channel'], s['status']) for s in release['surfaces']] == [
        ('schema_org', 'Compiled, held · Oct 25'), ('manufacturer_center', 'Compiled, held · Oct 25'),
        ('acp', 'Blocked · Oct 25'), ('ucp_uip', 'Not in this pass'), ('deals_api', 'Not in this pass'),
        ('mcp', 'Not in this pass')]
    assert {s['channel']: s['spec_version'] for s in release['surfaces']}['acp'] == 'acp-feed-stable-2026-08-18'
    assert ts['releases'] == [{'version': 'v1', 'compiled_at': '2026-10-25T22:02:33', 'day': 'Oct 25',
                               'what_changed': 'Feed version 1, first compile', 'status': 'Compiled, held',
                               'approvals': 'None needed yet', 'verification': 'Waits for the first live publish',
                               'requested': 'parleo', 'current': True, 'rows': 12}]
    # #33's tenant has one merchant: step 1 only
    assert [d['step'] for d in ts['destinations']] == [1]
    assert ts['destinations'][0]['status'] == {'label': 'Held for Pampers 2R-1', 'tone': 'blue'}


def test_a_second_step_only_when_another_merchant_holds_a_compile():
    """Derived: #33's tenant lists one merchant. Another merchant (the pair's W&S) given one of #33's held rows,
    re-keyed to it, is step 2; with none, there is no step 2."""
    rows = _held_rows()
    theirs = [{**rows[0], 'id': 99, 'record_ref': 'feed:wiggle-and-snug:sku:x'}]
    merchants = [{'slug': SLUG, 'name': 'Pampers 2R-1'}, {'slug': 'wiggle-and-snug', 'name': 'Wiggle & Snug'}]
    common = dict(pubs=rows, merchants=merchants, slug=SLUG, name='Pampers 2R-1', brand='Pampers', domain='pampers.com',
                  channels=f2r2.body('channels'))
    steps = rel.build_destinations(all_pubs=rows + theirs, **common)
    assert [d['step'] for d in steps] == [1, 2]
    assert (steps[1]['title'], steps[1]['planned_on'], steps[1]['status']['label']) == \
        ('Proof of push: Wiggle & Snug', None, 'Compiled, not sent')
    assert [d['step'] for d in rel.build_destinations(all_pubs=rows, **common)] == [1]


def test_a_stated_send_moves_the_release_and_the_timeline(http, db, upstream):
    _shape(db, http, upstream, sent='2026-10-23')
    ts = _read(http, 'truesync')
    assert ts['release']['status'] == 'Compiled, sent by P&G content team'
    swd = next(p for p in ts['products'] if p['name'] == 'Pampers Swaddlers')
    sent = [e for e in swd['timeline'] if e['what'] == 'P&G content team says it sent the Manufacturer Center file']
    # dated as stated: #33's recording states Oct 23 for a file compiled Oct 25 (2R-2b: soa refuses that now)
    assert [e['day'] for e in sent] == ['Oct 23']


# ── B2: the rest of the Overview ─────────────────────────────────────────

def test_revenue_missed_is_the_size_answers_wrong_with_prices_beside(http, db, upstream):
    _shape(db, http, upstream)
    overview = _overview(http)
    revenue = overview['revenue']
    answers = overview['attribute_accuracy']['answers']
    missed = answers['n'] - answers['k']
    assert revenue['shares']['missed_raw'] == missed / answers['n']
    assert revenue['shares']['missed'] == missed / answers['n'] * (1 - revenue['shares']['lost'])
    driver = next(d for d in revenue['drivers'] if d['id'] == 'missed')
    assert driver['title'] == 'Facts agents and retailers get wrong' and driver['basis'] == 'attribute'
    assert driver['measured'].startswith(f"{missed} of the {answers['n']} size answers gave a weight range that "
                                         "doesn't match pampers.com")
    assert 'Prices: ' in driver['measured'] and 'Prices, beside it and not added' in revenue['how_calculated']
    assert revenue['mode_note'] == ("Manufacturer mode: Pampers never sets a price. Revenue is modeled from these "
                                    "answers, not scored.")
    # the top signal is a price (another brand's): the first-pick headline
    lost = revenue['counts']['lost']
    assert revenue['headline'].startswith(f"Another brand gets the first pick in {lost['n']} of {lost['of']}")
    # Impact reads the same model
    impact = _read(http, 'revenue', cycle=f2p1.CYCLE_2)
    assert impact['shares'] == revenue['shares'] and impact['basis'] == revenue['how_calculated']


def test_strip_week_agents_and_labels(http, db, upstream):
    _shape(db, http, upstream)
    overview = _overview(http)
    score = _read(http, 'score', cycle=f2p1.CYCLE_2)
    strip = overview['strip']
    moved = [m['key'] for m in score['metrics_by_kind']['brand'] if m.get('delta')]
    assert (strip['score'], strip['delta'], strip['moved']['keys']) == (score['score'], score['previous']['delta'], moved)
    assert strip['moved_line'] == f"{len(moved)} of 5 numbers moved"
    deltas = {d['code']: d['delta'] for d in score['previous']['pillar_deltas']}
    assert {p['code']: p['delta'] for p in strip['pillars']} == deltas   # a field, never inside the fraction
    assert (strip['approvals'], strip['actions']) == (None, None)
    assert [w['key'] for w in overview['week_in_short']] == ['attribute', 'misses', 'retired', 'coverage', 'promo']
    assert overview['week_in_short'][1]['text'].startswith('The misses sit on Size 4, where pampers.com runs two charts')
    for a in overview['by_surface']['all']['agents']:
        f = a['facts_right']
        assert f['right'] == f['weight']['right'] + a['exact'] and f['of'] == f['weight']['of'] + a['scored']
    chatgpt = next(a for a in overview['by_surface']['all']['agents'] if a['agent'] == 'chatgpt')
    assert chatgpt['deals_line'] == f"Named {chatgpt['deals']['named']} of {chatgpt['deals']['of']} live deals"
    assert (overview['vs_label'], overview['vs_cycle']) == ('vs Oct 14', f2p1.CYCLE_1)
    assert overview['header'] == {'skus': 6, 'records': 4, 'retailers_checked': 2,
                                  'retailers': ['walmart.com', 'amazon.com'], 'brand_domain': 'pampers.com'}
    stages = [e['stage'] for e in overview['activity']]
    # the pair's runs share one stamp: complete still reads above started
    assert stages == ['compiled', 'complete', 'started', 'brand_page']
    foot = overview['first_pick']['footnote']
    assert foot.endswith('AMORE was named in 3 of 102, Pure in 7.')


def test_products_live_deals_check_weight_and_quotes(http, db, upstream):
    _shape(db, http, upstream)
    products = {p['sku']: p for p in _overview(http)['by_surface']['all']['products']}
    v1 = products['v1']
    # 2T-3 (3): the deal's one label (ppt.label)
    assert v1['live_deals'] == ['Amazon: save 40% on 1 when you buy 2']
    assert v1['live'].endswith('. Amazon: save 40% on 1 when you buy 2')
    assert v1['issue'].startswith('Weight right in 5 of 5.')
    assert v1['check'] == 'partly_right'
    assert v1['quoted_all'].count('$') == 3 and v1['quoted'] == v1['quoted_all']   # three amounts: nothing collapsed
    assert v1['signal'].startswith('deal:')
    long = 'Amazon $1.00, 1 of 9 runs. Walmart $2.00, 1 of 9 runs. Kroger $3.00, 1 of 9 runs. CVS $4.00, 1 of 9 runs. ' \
           'No price, 5 of 9 runs'
    assert bo.collapse_quoted(long) == ('Amazon $1.00, 1 of 9 runs. Walmart $2.00, 1 of 9 runs. Kroger $3.00, 1 of 9 '
                                        'runs. +1 more. No price, 5 of 9 runs', long)


def test_33_s_own_deals_recorded_name_no_deal(http, db, upstream):
    """#33's /deals as recorded (its merchant's retailer rows were never read): no deal signal, no promo line."""
    _shape(db, http, upstream)
    recorded = f2r2.body('deals-20261021')
    assert recorded['deals'] == [] and recorded['merchant'] == SLUG
    upstream.routes.by_date = [('', recorded)]
    console_cache.clear()
    overview = _overview(http)
    assert not any(s['kind'] == 'deal' for s in overview['by_surface']['all']['signals'])
    assert overview['promo_pass_through']['live_deals'] == 0
    promo = {t['key']: t for t in overview['charter']}['promo']
    assert promo['second_line'] is None
    assert all(p['live_deals'] == [] for p in overview['by_surface']['all']['products'])


def test_a_club_only_line_sent_elsewhere():
    """Derived: #33's feed has no club-only line. Its Pure row given only clubs (Sam's Club and Costco), and the
    store answers about it built in rm.stores_in_order's shape, read as the brief says."""
    feed = copy.deepcopy(f2r2.body('feed')['rows'])
    pure = next(r for r in feed if r.get('sku') == 'sku_pg_pure_s1')
    pure['retailers'] = [{'domain': 'pampers.com'}, {'domain': 'samsclub.com'}, {'domain': 'costco.com'}]
    lines = bo.club_lines(feed, ['pampers.com'])
    assert [l['label'] for l in lines] == ['Size 1']
    answers = [{'intent': 'where_to_buy', 'keys': ['sku:sku_pg_pure_s1'], 'stores': ["Sam's Club", 'Costco']},
               {'intent': 'where_to_buy', 'keys': ['sku:sku_pg_pure_s1'], 'stores': ['Walmart']},
               {'intent': 'cheapest_place', 'keys': ['sku_pg_pure_s1'], 'stores': ['Walmart', "Sam's Club"]}]
    counts = bo.club_counts(lines, answers)
    assert (counts['where'], counts['club_named'], counts['elsewhere'], counts['stores']) == (2, 1, 2, ['Walmart'])
    signal = bo.store_signal(counts, 'Pampers')
    assert signal['title'] == 'A club-only Pure Protection, sent to Walmart.'
    assert (signal['kind'], signal['pool'], signal['count']) == ('store', 'missed', 2)
    score = {'metric_surface': 'all', 'metrics_by_kind': {'brand': [
        {'key': 'coverage', 'state': 'measured', 'value': 40, 'denominator': 49, 'delta': None, 'reason': None}]},
        'metric_counts': {'all': {'coverage': {'names': ['Amazon', 'Walmart']}}}}
    coverage = bo.build_charter(score, domain='pampers.com', club=counts, promo=None)[0]
    assert coverage['second_line'] == '1 of 2 answers on the club-only Pampers Pure Protection also named a warehouse club.'


def test_a_merchant_not_in_manufacturer_mode_gets_none_of_it(http, db, upstream):
    from tests.test_console_read_models import WS_TENANT
    _shape(db, http, upstream)
    upstream.answer('GET', '/api/truesync/tenant', body=WS_TENANT, token=TOKEN_A)
    console_cache.clear()
    overview = _overview(http, merchant=f2r2.PAIR_SLUG)
    assert not {'lead', 'truesync_card', 'charter', 'strip', 'revenue', 'week_in_short', 'activity', 'header',
                'vs_label'} & set(overview)
    assert 'pool' not in overview['by_surface']['all']['signals'][0]
    ts = _read(http, 'truesync', merchant=f2r2.PAIR_SLUG)
    assert not {'workspace', 'release', 'releases', 'cell_states'} & set(ts)
