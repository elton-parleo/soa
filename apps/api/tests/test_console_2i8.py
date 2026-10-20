"""
2I-8: every agent counted together, as the console demo counts them; a
surface is a filter.

The read models carry a pseudo-surface `all` ("All agents") computed over
every run in the cycle, listed first and chosen as the default. Each
surface's own entry is unchanged: the snapshot below was taken on main
(54c3416) before anything changed, and pins every per-surface value on four
fixtures, byte for byte, with `all` taken out. On sqlite and a local Postgres.
"""
import copy
import hashlib
import json
import os

import pytest
from sqlalchemy import text

from app.routers import console as console_router
from app.services import console_parity as parity
from app.services import console_read_models as rm
from soa_shared import surfaces
from tests import console_fixture_2i8 as f2i8
from tests import console_fixture_229 as f229
from tests.test_console_2c3 import _two_surfaces, _with_store
from tests.test_console_2c3a import _cycle_229, _supply, db  # noqa: F401
from tests.test_console_2i5 import STUDY as BRAND_STUDY, first  # noqa: F401  (fixture)
from tests.test_console_read_models import CYCLE, _encode, as_, http, upstream  # noqa: F401  (pytest fixtures)

SNAPSHOT = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'per_surface_2i8.json')
#: where the snapshot test writes the full per-surface views, when set
DUMP = os.getenv('SOA_2I8_SNAPSHOT_DUMP')
REAL = ('api', 'grounded_api', 'consumer_ui', 'unlabelled')
ALL = 'all'


# ═══ the four fixtures ══════════════════════════════════════════════════

def _ws(db):
    _with_store(db)
    return CYCLE


def _ws_two(db):
    _with_store(db)
    _two_surfaces(db)
    return CYCLE


def _229(db):
    _cycle_229(db)
    return f229.CYCLE_229


def _fl12(db):
    f2i8.load(db, _encode)
    kind = 'JSON' if db.dialect.name == 'postgresql' else 'TEXT'
    with db.begin() as c:
        c.exec_driver_sql(f"ALTER TABLE soa_cycles ADD COLUMN share_of_algorithm {kind}")
        c.exec_driver_sql("ALTER TABLE soa_cycles ADD COLUMN share_of_algorithm_version TEXT")
    return f2i8.CYCLE


FIXTURES = {'ws': _ws, 'ws_two': _ws_two, '229': _229, 'fl12': _fl12}
ENDPOINTS = ('visibility', 'overview', 'answers/summary', 'true-value', 'answers', 'score')


def _read(http, cycle, endpoint):
    as_('op')
    params = {'cycle': cycle, 'org': 10}
    if endpoint in ('overview', 'true-value', 'score'):
        params['merchant'] = 'wiggle-and-snug'
    if endpoint == 'score':
        params['rescore'] = 1
    r = http.get(f'/api/console/{endpoint}', params=params)
    assert r.status_code == 200, (endpoint, r.text)
    return r.json()


# ═══ the per-surface view ═══════════════════════════════════════════════

#: Fields that read the default surface (or say how counts are kept), which
#: 2I-8 moves to `all` on purpose. Everything else must not change.
DEFAULT_READERS = {
    'visibility': ('headline', 'lede', 'divergences'),
    'overview': ('surface', 'rules'),
    'true-value': ('surface', 'columns', 'divergences'),
    # 2I-8a: the five metric rows count every agent, under scorer 10
    'score': ('metric_surface', 'metrics', 'scorer_version', 'rules'),
}
#: a True Value cell's typed fields, read on the default surface
CELL_TYPED = ('quoted', 'status', 'outcome', 'runs', 'surface')
PROGRAM_TYPED = ('agentsRight', 'tone', 'surface')


def _strip_all(x):
    """`all` out: a key of a dict keyed by surface, an entry of a list of
    per-surface entries (each carries its surface's label)."""
    if isinstance(x, dict):
        keyed = any(k in REAL for k in x)
        return {k: _strip_all(v) for k, v in x.items() if not (keyed and k == ALL)}
    if isinstance(x, list):
        return [_strip_all(v) for v in x if not (isinstance(v, dict) and v.get('surface') == ALL and 'label' in v)]
    return x


def _strip_volatile(x):
    if isinstance(x, dict):
        return {k: _strip_volatile(v) for k, v in x.items() if k not in ('scored_at', 'stored', 'history')}
    if isinstance(x, list):
        return [_strip_volatile(v) for v in x]
    return x


def _ranking(r):
    r = {k: v for k, v in (r or {}).items() if k not in ('surface', 'denom')}
    rows = [{k: v for k, v in row.items() if k not in ('named', 'first')} for row in r.get('rows') or []]
    r['rows'] = sorted(rows, key=lambda row: row['name'])
    return r


def per_surface_view(endpoint, body):
    body = _strip_volatile(_strip_all(copy.deepcopy(body)))
    for k in DEFAULT_READERS.get(endpoint, ()):
        body.pop(k, None)
    if endpoint in ('visibility', 'overview') and body.get('ranking'):
        body['ranking'] = _ranking(body['ranking'])
    if endpoint == 'true-value':
        for row in body.get('rows') or []:
            for cells in (row.get('cells') or {}, row.get('retailer_cells') or {}):
                for cell in cells.values():
                    for k in CELL_TYPED:
                        cell.pop(k, None)
        for p in body.get('programs') or []:
            for k in PROGRAM_TYPED:
                p.pop(k, None)
    return body


def _digest(view) -> str:
    return hashlib.sha256(json.dumps(view, sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize('name', list(FIXTURES))
def test_every_per_surface_value_is_what_main_served(name, http, db, upstream):
    """Each endpoint's per-surface view on main (54c3416), before 2I-8, as
    sha256 of its sorted JSON. SOA_2I8_SNAPSHOT_DUMP=<dir> writes the views."""
    cycle = FIXTURES[name](db)
    _supply(upstream)
    got = {}
    for endpoint in ENDPOINTS:
        view = per_surface_view(endpoint, _read(http, cycle, endpoint))
        got[endpoint] = _digest(view)
        if DUMP:
            os.makedirs(DUMP, exist_ok=True)
            with open(os.path.join(DUMP, f"{name}-{endpoint.replace('/', '_')}-{db.dialect.name}.json"), 'w') as fh:
                json.dump(view, fh, indent=1, sort_keys=True)
    # keyed by dialect: /answers' runAt carries its offset on sqlite only, as on main
    with open(SNAPSHOT) as fh:
        assert got == json.load(fh)[db.dialect.name][name]


# ═══ FL12's shape: every agent together ══════════════════════════════════

DEMO_ORDER = ['chatgpt', 'gemini', 'aimode', 'perplexity', 'copilot', 'claude']


@pytest.fixture
def fl12(http, db, upstream):
    cycle = _fl12(db)
    _supply(upstream)
    as_('op')
    return {k: _read(http, cycle, k) for k in ('visibility', 'overview', 'answers/summary', 'true-value')}


def test_the_headline_counts_every_agent_first(fl12):
    """33 of 102: 22 of the 68 grounded answers and 11 of the 34 consumer ones."""
    vis = fl12['visibility']
    heads = vis['headlines']
    assert [s['surface'] for s in vis['surfaces']] == ['all', 'grounded_api', 'consumer_ui']
    assert vis['surfaces'][0] == {'surface': 'all', 'label': 'All agents', 'answered': 515, 'runs': 516}
    assert (heads['grounded_api']['first'], heads['grounded_api']['denom']) == (22, 68)
    assert (heads['consumer_ui']['first'], heads['consumer_ui']['denom']) == (11, 34)
    assert (heads['all']['first'], heads['all']['denom']) == (22 + 11, 68 + 34)
    assert heads['all']['named'] == heads['grounded_api']['named'] + heads['consumer_ui']['named']
    assert heads['all']['text'] == vis['headline'] == 'First in 33 of 102 unprompted answers.'
    assert vis['ranking']['surface'] == 'all' and vis['ranking']['denom'] == 515


def test_the_ranking_on_all_is_the_sum_of_the_surfaces(fl12):
    ranking = fl12['visibility']['ranking']
    assert ranking['denoms']['all'] == ranking['denoms']['grounded_api'] + ranking['denoms']['consumer_ui']
    assert list(ranking['agent_denoms']['all']) == DEMO_ORDER
    for row in ranking['rows']:
        per = row['surfaces']
        for k in ('named', 'first'):
            assert per['all'][k] == per['grounded_api'][k] + per['consumer_ui'][k] == row[k], (row['name'], k)
        assert per['all']['agents'] == {**per['grounded_api']['agents'], **per['consumer_ui']['agents']}
        assert list(per['all']['agents']) == DEMO_ORDER
    assert ranking['untracked']['all'] == []


def test_the_matrix_on_all_has_six_columns_in_the_demo_s_order(fl12):
    matrix = fl12['visibility']['matrix']
    assert matrix['all']['agents'] == DEMO_ORDER
    assert matrix['grounded_api']['agents'] == ['chatgpt', 'claude', 'gemini', 'perplexity']   # as before
    rows = {r['query_code']: r for r in matrix['all']['rows']}
    errored = rows[f2i8.ERRORED]['cells']['aimode']
    assert (errored['answered'], errored['first']) == (0, None)     # ran, no answer: no pick to show
    assert rows[f2i8.ERRORED]['cells']['copilot']['answered'] == 1
    # every per-surface cell is the same cell on `all`
    for s in ('grounded_api', 'consumer_ui'):
        for r in matrix[s]['rows']:
            for agent, cell in r['cells'].items():
                assert rows[r['query_code']]['cells'][agent] == cell


def test_a_question_an_agent_did_not_run_has_no_cell_on_all():
    rows = [{'q': 'q1', 'query_code': 'Q1', 'stage': 'Awareness', 'tier': 'unprompted', 'surface': s, 'agent': a,
             'answered': True, 'first': {'name': 'Pampers', 'you': False}}
            for s, a in (('grounded_api', 'chatgpt'), ('consumer_ui', 'aimode'))]
    rows.append({**rows[0], 'query_code': 'Q2', 'q': 'q2'})            # ChatGPT only
    m = parity.visibility_matrix(rows, surfaces.ALL)
    assert m['agents'] == ['chatgpt', 'aimode']
    q2 = next(r for r in m['rows'] if r['query_code'] == 'Q2')
    assert set(q2['cells']) == {'chatgpt'}


def test_the_overview_reads_all_by_default_with_six_agents(fl12):
    over = fl12['overview']
    assert over['surface'] == 'all'
    assert [s['surface'] for s in over['surfaces']] == ['all', 'consumer_ui', 'grounded_api']   # then by fidelity, as before
    assert over['surfaces'][0]['label'] == 'All agents'
    every, g, c = (over['by_surface'][k] for k in ('all', 'grounded_api', 'consumer_ui'))
    assert [a['agent'] for a in every['agents']] == DEMO_ORDER
    assert {a['agent']: a for a in every['agents']} == {a['agent']: a for a in g['agents'] + c['agents']}
    for k in ('answers', 'named', 'first', 'named_of', 'exact', 'scored', 'wrong', 'other_brand', 'fabricated'):
        assert every['totals'][k] == g['totals'][k] + c['totals'][k], k
    assert every['totals']['first'] == 33 and every['totals']['named_of'] == 102
    assert every['summary']['lines'][0] == 'First in 33 of 102 unprompted answers, ahead of every other brand.'
    assert over['coverage']['unprompted'] == 102


def test_signals_on_all_say_across_every_agent(fl12):
    every = fl12['overview']['by_surface']['all']
    other = next(s for s in every['signals'] if s['id'] == 'other_brand')
    assert other['detail'].startswith(f"{other['count']} of ") and ' price answers across every agent. ' in other['detail']
    grounded = next(s for s in fl12['overview']['by_surface']['grounded_api']['signals'] if s['id'] == 'other_brand')
    assert ' price answers on the grounded API. ' in grounded['detail']


def test_answers_summary_pools_counts_and_takes_accuracy_over_the_sums(fl12):
    body = fl12['answers/summary']
    catalog = {s['surface']: s for t in body['tiers'] if t['tier'] == 'catalog_accuracy' for s in t['surfaces']}
    assert list(catalog) == ['all', 'grounded_api', 'consumer_ui']
    g, c, a = catalog['grounded_api'], catalog['consumer_ui'], catalog['all']
    assert (g['counts']['exact'], g['scored'], c['counts']['exact'], c['scored']) == (8, 28, 14, 14)
    assert a['counts'] == {k: g['counts'].get(k, 0) + c['counts'].get(k, 0) for k in set(g['counts']) | set(c['counts'])}
    assert (a['counts']['exact'], a['scored']) == (22, 42) and a['accuracy'] == round(22 / 42, 4)
    assert a['accuracy'] != round((g['accuracy'] + c['accuracy']) / 2, 4)          # pooled, not a mean of surfaces
    assert a['unverifiable'] == g['unverifiable'] + c['unverifiable']
    every = {s['surface']: (s['runs'], s['answered']) for s in body['all_tiers']}
    assert every == {'all': (516, 515), 'grounded_api': (344, 344), 'consumer_ui': (172, 171)}


def test_the_true_value_cell_is_typed_from_every_agent_s_quotes():
    """TV_CELL_RULE over the pooled quotes: the grounded API right, the
    consumer UI wrong, so the typed cell is wrong; each surface's cell as before."""
    q = lambda agent, surface, outcome, stated, run: {  # noqa: E731
        'variant_id': 'v1', 'retailer': 'shop.test', 'outcome': outcome, 'stated': stated, 'surface': surface,
        'agent': agent, 'run': run}
    scored = [q('chatgpt', 'grounded_api', 'exact', '12.99', 'run-1'), q('gemini', 'grounded_api', 'exact', '12.99', 'run-2'),
              q('aimode', 'consumer_ui', 'wrong', '14.99', 'run-3'), q('copilot', 'consumer_ui', 'absent', None, 'run-4')]
    variants = [{'variant_id': 'v1', 'label': 'V1', 'list_price': '12.99', 'currency': 'USD'}]
    tv = rm.build_true_value(None, scored, own_domain='shop.test', record_variants=variants)
    cell = tv['rows'][0]['retailer_cells']['shop.test']
    assert (cell['status'], cell['quoted'], cell['runs'], cell['surface']) == ('wrong', '$14.99', 4, 'all')
    assert cell['by_surface']['grounded_api'] == {'quoted': '$12.99', 'status': 'exact', 'outcome': 'exact', 'runs': 2}
    assert cell['by_surface']['consumer_ui'] == {'quoted': '$14.99', 'status': 'wrong', 'outcome': 'wrong', 'runs': 2}
    assert cell['by_surface']['all'] == {'quoted': '$14.99', 'status': 'wrong', 'outcome': 'wrong', 'runs': 4}
    assert [c['id'] for c in tv['columns_by_surface']['all']] == ['chatgpt', 'gemini', 'aimode', 'copilot']


def test_the_untracked_footer_has_an_all_entry():
    def run(rid, platform, surface):
        return {'id': rid, 'platform': platform, 'run_number': 1, 'surface': surface, 'answer_status': 'answered',
                'query_code': f'Q{rid}', 'query_text': 'q', 'tier': None, 'stage': 'Awareness'}
    runs = [run(1, 'chatgpt', 'grounded_api'), run(2, 'aimode', 'consumer_ui'), run(3, 'copilot', 'consumer_ui')]
    other = lambda *names: {'other_brands_named': [{'name': n, 'presented_as': 'recommendation'} for n in names]}  # noqa: E731
    body = rm.build_visibility('C', runs=runs, entities=[{'name': 'Wiggle & Snug', 'role': 'primary'}], mentions=[],
                               extractions={1: other('Millie Moon'), 2: other('Millie Moon', 'Coterie'), 3: other('Coterie')})
    u = body['ranking']['untracked']
    assert u['grounded_api'] == [{'name': 'Millie Moon', 'named': 1}]
    assert u['consumer_ui'] == [{'name': 'Coterie', 'named': 2}, {'name': 'Millie Moon', 'named': 1}]
    assert u['all'] == [{'name': 'Coterie', 'named': 2}, {'name': 'Millie Moon', 'named': 2}]


def test_the_program_caption_has_an_all_line():
    catalog = {'listings': [{'listing_id': 'L1', 'variants': [{'variant_id': 'v1', 'member_price': '9.99',
                                                               'member_tier_name': 'Member+'}]}]}
    asked = lambda platform, surface, outcome: {  # noqa: E731
        'outcome': outcome, 'platform': platform, 'surface': surface,
        'expected_answer': {'type': 'member_price', 'tier_name': 'Member+'}, 'source_ref': {'variant_id': 'v1'}}
    lines = parity.program_lines(catalog, None, [asked('chatgpt', 'grounded_api', 'exact'),
                                                 asked('aimode', 'consumer_ui', 'wrong')])
    by = lines['v1']['by_surface']
    assert list(by) == ['all', 'consumer_ui', 'grounded_api']
    assert by['all']['line'].endswith('Quoted by 1 of 2 agents.')
    assert by['grounded_api']['line'].endswith('Quoted by 1 of 1 agent.')


# ═══ one surface: `all` is that surface ═════════════════════════════════

def _one_surface_229(db):
    """229 without its two errored consumer-UI runs: one surface, FL8's shape."""
    cycle = _229(db)
    with db.begin() as c:
        c.execute(text("DELETE FROM soa_runs WHERE cycle_id = 229 AND surface = 'consumer_ui'"))
    return cycle


@pytest.mark.parametrize('build', [_one_surface_229, _ws], ids=['229', 'ws_one_surface'])
def test_on_one_surface_all_is_that_surface(build, http, db, upstream):
    cycle = build(db)
    if build is _ws:
        with db.begin() as c:   # W&S has one AI Mode run: take it out
            c.execute(text("DELETE FROM soa_runs WHERE surface = 'consumer_ui'"))
    _supply(upstream)
    vis = _read(http, cycle, 'visibility')
    [only] = [s['surface'] for s in vis['surfaces'] if s['surface'] != 'all']
    same = lambda a, b, drop=('surface',): (  # noqa: E731
        {k: v for k, v in a.items() if k not in drop} == {k: v for k, v in b.items() if k not in drop})
    assert vis['headlines']['all'] == vis['headlines'][only]
    assert same(vis['matrix']['all'], vis['matrix'][only]) and same(vis['by_stage']['all'], vis['by_stage'][only])
    for k in ('denoms', 'agent_denoms', 'first_uncoded', 'agent_first_uncoded', 'untracked'):
        assert vis['ranking'][k]['all'] == vis['ranking'][k][only], k
    assert all(r['surfaces']['all'] == r['surfaces'][only] for r in vis['ranking']['rows'])
    over = _read(http, cycle, 'overview')
    a, o = over['by_surface']['all'], over['by_surface'][only]
    for k in ('agents', 'products', 'totals', 'tier', 'changes', 'changes_status', 'summary'):
        assert a[k] == o[k], k
    assert [{**s, 'detail': None} for s in a['signals']] == [{**s, 'detail': None} for s in o['signals']]
    summary = _read(http, cycle, 'answers/summary')
    pick = lambda xs, s: {k: v for x in xs if x['surface'] == s for k, v in x.items() if k not in ('surface', 'label')}  # noqa: E731
    assert pick(summary['all_tiers'], 'all') == pick(summary['all_tiers'], only)
    assert pick(summary['surfaces'], 'all') == pick(summary['surfaces'], only)
    for t in summary['tiers']:
        assert pick(t['surfaces'], 'all') == pick(t['surfaces'], only)
    tv = _read(http, cycle, 'true-value')
    if not tv['surfaces']:     # 229's catalog questions name no variant: nothing priced, no surface
        assert tv['surface'] is None and tv['by_agent'] == {}
        return
    assert tv['surface'] == 'all'
    assert tv['by_agent']['all'] == tv['by_agent'][only]
    assert tv['columns_by_surface']['all'] == tv['columns_by_surface'][only]
    for row in tv['rows']:
        for cell in [*row['cells'].values(), *(row.get('retailer_cells') or {}).values()]:
            if cell['by_surface']:
                assert cell['by_surface']['all'] == cell['by_surface'][only]


# ═══ Changes on `all` ═══════════════════════════════════════════════════

def _overview_inputs(db):
    with db.connect() as c:
        row = dict(c.execute(text("SELECT * FROM soa_cycles WHERE id = 229")).mappings().one())
        rows = parity.load_overview_rows(c, row)
        vis = console_router._visibility(c, row)
    return row, rows, vis


def test_changes_on_all_compare_two_cycles_with_the_same_agents(http, db, upstream):
    _fl12(db)
    row, rows, vis = _overview_inputs(db)
    tv = {'rows': []}
    body = parity.build_overview(row, rows=rows, visibility=vis, true_value=tv, brand='Wiggle & Snug',
                                 previous={'code': 'PREV', 'rows': rows, 'visibility': vis})
    every = body['by_surface']['all']
    assert every['changes_status'] == 'compared' and every['changes_note'] is None
    assert {c['metric']: (c['now'], c['prev'], c['delta']) for c in every['changes']}['first'] == (33, 33, '0')
    assert {a['agent']: a['delta_status'] for a in every['agents']} == {a: 'compared' for a in DEMO_ORDER}


def test_changes_on_all_are_not_comparable_when_an_agent_is_missing_from_one(http, db, upstream):
    _fl12(db)
    row, rows, vis = _overview_inputs(db)
    prev_rows = [r for r in rows if r['platform'] != 'claude']
    prev_vis = {**vis, 'byQuestion': [v for v in vis['byQuestion'] if v['agent'] != 'claude']}
    body = parity.build_overview(row, rows=rows, visibility=vis, true_value={'rows': []}, brand='Wiggle & Snug',
                                 previous={'code': 'PREV', 'rows': prev_rows, 'visibility': prev_vis})
    every = body['by_surface']['all']
    assert every['changes_status'] == 'not_comparable' and every['changes'] == []
    assert every['changes_note'] == 'Not comparable: PREV ran ChatGPT, Copilot, Gemini, Google AI Mode and Perplexity only.'
    # the consumer UI ran the same agents in both: compared there, as before
    assert body['by_surface']['consumer_ui']['changes_status'] == 'compared'


def test_fl12_against_its_chatgpt_only_previous_cycle_says_so_on_all(fl12):
    every = fl12['overview']['by_surface']['all']
    assert every['changes_status'] == 'not_comparable'
    assert every['changes_note'] == f'Not comparable: {f229.PREVIOUS} ran ChatGPT only.'
    assert fl12['overview']['by_surface']['grounded_api']['changes_note'] == \
        f'Not comparable: {f229.PREVIOUS} ran ChatGPT only on this surface.'


# ═══ `all` is never a run's surface ═════════════════════════════════════

def test_all_is_a_read_model_key_and_never_a_surface():
    assert surfaces.ALL == 'all' and surfaces.SURFACE_LABELS['all'] == 'All agents'
    assert surfaces.ALL not in surfaces.SURFACE_KINDS
    assert all(s.surface != surfaces.ALL and s.id != surfaces.ALL for s in surfaces.SURFACES)
    assert surfaces.surface_of('all') is None and surfaces.get('all') is None
    with pytest.raises(surfaces.UnknownSurface):
        surfaces.resolve('all')
    with pytest.raises(surfaces.UnknownSurface):
        surfaces.resolve_platforms(['chatgpt', 'all'])
    assert surfaces.with_all(['grounded_api', 'consumer_ui']) == ['all', 'grounded_api', 'consumer_ui']
    assert surfaces.with_all([]) == []


def test_a_cycle_naming_all_is_refused_and_nothing_is_written(http, first):
    as_('op')
    with first.connect() as c:
        before = c.execute(text("SELECT COUNT(*) FROM soa_cycles")).scalar()
    r = http.post('/api/console/cycles', params={'org': 10}, json={
        'study_type': BRAND_STUDY, 'platforms': ['all'], 'cycle_code': 'WSB-ALL'})
    assert r.status_code == 422, r.text
    with first.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM soa_cycles")).scalar() == before


def test_a_full_loop_naming_all_is_refused(http, db):
    as_('alice')
    r = http.post('/api/full-loop', json={'merchant_slug': 'wiggle-and-snug', 'study_type': 'ws-2b-fixture',
                                          'platforms': ['all']})
    assert r.status_code == 422, r.text
    with db.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM soa_full_loop_requests")).scalar() == 0


# ═══ B2: `?surface=all` is no parameter ═════════════════════════════════

@pytest.mark.parametrize('endpoint', ['answers', 'answers/summary', 'true-value', 'visibility', 'overview'])
def test_surface_all_and_no_surface_are_the_same_response(endpoint, http, db, upstream):
    """No console endpoint takes `surface`: each returns every surface keyed,
    `all` first, and the console picks. `?surface=all` is the same response."""
    cycle = _fl12(db)
    _supply(upstream)
    as_('op')
    params = {'cycle': cycle, 'org': 10, **({'merchant': 'wiggle-and-snug'} if endpoint in ('overview', 'true-value') else {})}
    plain = http.get(f'/api/console/{endpoint}', params=params)
    pooled = http.get(f'/api/console/{endpoint}', params={**params, 'surface': 'all'})
    assert plain.status_code == pooled.status_code == 200
    assert plain.json() == pooled.json()
