"""
2T-5 (Visibility): the demo's Visibility for a brand at retail (pg.ts
visibility and ranking, Leads.tsx VisibilityLead), from the Oct 26 findings.

  V1  `headline`: "<Brand> is named in N of M category answers and put first
      in F. <Rival> goes first in R, and A of B agents lead the <question>
      question with <rival product>."
  V2  `gap`: {behind_or_ahead, n, rival, sentence}, dollars the Lost pool's
  V3  `footnote` in the demo's wording; "named but not tracked" leaves out
      products outside the category, the brand's own named apart
  V4  each byQuestion row's coded `pick`: no_single_pick, never "no pick
      coded" where the coding names brands
  V5  routing: `named` per store, the where-to-buy and cheapest-place tables

Inputs: the 2T-1 harness (supply #33's answers RECORDED) and
console_fixture_2t5's FL15 shape, DERIVED and labelled. No production read,
no model call.
"""
from collections import Counter

import pytest

from app.services import console_measure as measure
from app.services import console_read_models as rm
from tests import console_fixture_2p1 as f2p1
from tests import console_fixture_2t5 as f2t5
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import _encode, http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_console_2t1_overview_truesync import _read, _shape

BRAND = f2t5.BRAND


def _vis(db, http, upstream):
    _shape(db, http, upstream)
    f2t5.comparison(db, _encode)
    return _read(http, 'visibility', cycle=f2p1.CYCLE_2)


def _choice(vis):
    return [v for v in vis['byQuestion'] if v['answered'] and v['brand_choice']]


# ── V1: the headline ──────────────────────────────────────────────────────

def test_the_headline_reads_the_brand_choice_ranking(http, db, upstream):
    vis = _vis(db, http, upstream)
    rows = vis['ranking']['brand_choice']['rows']
    you = next(r for r in rows if r['you'])
    rival = max((r for r in rows if not r['you']), key=lambda r: (r['first'], r['named']))
    assert rival['name'] == f2t5.RIVAL   # the comparison answers put Huggies past Pampers
    # the question the rival leads most, recounted from the rows
    led = Counter(v['q'] for v in _choice(vis) if (v['first'] or {}).get('name') == rival['name'])
    q, k = led.most_common(1)[0]
    agents = {v['agent'] for v in _choice(vis) if v['q'] == q}
    assert vis['headline'] == (f"{BRAND} is named in {you['named']} of {vis['ranking']['brand_choice']['denom']} "
                               f"category answers and put first in {you['first']}. Huggies goes first in "
                               f"{rival['first']}, and {k} of {len(agents)} agents lead the “{q}” question with "
                               f"Huggies.")
    detail = vis['headline_detail']
    assert (detail['question']['q'], detail['question']['product_source']) == (q, 'rival_name')
    assert detail['question_short'] is None and detail['question_short_reason']
    # the every-agent line the typed field carried stays in `headlines`
    assert vis['headlines']['all']['text'].startswith('First in ')


def test_the_rival_product_is_its_first_named_product():
    """On the comparison question the rival leads with "Huggies Little Snugglers" (named_products)."""
    rows = [{'q': 'A vs Huggies', 'agent': a, 'first': {'name': 'Huggies'},
             'named_products': [{'name': 'Huggies Little Snugglers', 'brand': 'Huggies'}]} for a in ('chatgpt', 'gemini')]
    rows += [{'q': 'A vs Huggies', 'agent': 'perplexity', 'first': {'name': 'A'}}]
    lead = measure.rival_question(rows, 'Huggies')
    assert (lead['k'], lead['n'], lead['product'], lead['product_source']) == (
        2, 3, 'Huggies Little Snugglers', 'named_products')


def test_named_products_are_coded_per_row(http, db, upstream):
    vis = _vis(db, http, upstream)
    row = next(v for v in vis['byQuestion'] if v['run'] == f"run-{f2t5.run_id(0, 'chatgpt')}")
    assert row['named_products'] == [{'name': 'Huggies Little Snugglers', 'brand': 'Huggies', 'you': False}]


# ── V2: the gap ───────────────────────────────────────────────────────────

@pytest.mark.parametrize('you,rival,side,sentence', [
    ((25, 5), (27, 9), 'behind', '4 first picks behind Huggies · Named almost as often as Huggies, picked first less '
                                  'often'),
    ((25, 3), (27, 9), 'behind', '6 first picks behind Huggies · Named almost as often as Huggies, picked first far '
                                  'less often'),
    ((10, 2), (27, 9), 'behind', '7 first picks behind Huggies · Huggies is picked first in 9, Pampers in 2'),
    ((25, 12), (27, 9), 'ahead', '3 first picks ahead of Huggies · Named almost as often as Huggies, picked first '
                                 'more often'),
    ((25, 9), (27, 9), 'level', 'Level with Huggies on first picks · Level with Huggies on first picks, named 25 to '
                                "Huggies's 27"),
])
def test_the_gap_by_the_demos_rule(you, rival, side, sentence):
    vis = {'ranking': {'rows': [{'name': 'Pampers', 'you': True, 'named': you[0], 'first': you[1]},
                                {'name': 'Huggies', 'you': False, 'named': rival[0], 'first': rival[1]},
                                {'name': 'Kudos', 'you': False, 'named': 7, 'first': 2}]}}
    gap = measure.visibility_gap(vis, 'Pampers', {'dollars': 41200, 'reason': None})
    assert (gap['behind_or_ahead'], gap['sentence'], gap['dollars'], gap['dollars_reason']) == (
        side, sentence, 41200, None)


def test_the_gaps_dollars_are_the_lost_pools_or_say_why(http, db, upstream):
    gap = _vis(db, http, upstream)['gap']
    assert gap['rival'] == f2t5.RIVAL and gap['behind_or_ahead'] in ('behind', 'ahead', 'level')
    # no sales in scope entered on the harness: no dollars, the model's own reason
    assert gap['dollars'] is None and gap['dollars_reason'] == 'enter sales in scope on Impact'


# ── V3: the footnote, and outside the category ────────────────────────────

def test_the_footnote_in_the_demos_wording(http, db, upstream):
    vis = _vis(db, http, upstream)
    foot = vis['footnote']
    firsts = Counter((v['first'] or {}).get('name') for v in _choice(vis) if v['first'])
    singles = sorted(n for n, c in firsts.items() if c == 1)
    none = sum(1 for v in _choice(vis) if v.get('pick') == 'no_single_pick')
    line = vis['retired_named']['lines'][0]['brand_choice']['all']
    parts = []
    if singles:
        parts.append(f"One first pick each for {singles}.")
    if none:
        parts.append(f"{none} answers named no single first pick.")
    parts.append(f"AMORE was named in {line['successor_named']} of {line['answers']}, Pure in {line['named']}.")
    parts.append(f"{BRAND} Training Pants was named too, outside the category.")
    assert foot['footnote'] == ' '.join(parts)


def test_named_but_not_tracked_leaves_out_products_outside_the_category(http, db, upstream):
    vis = _vis(db, http, upstream)
    untracked = {u['name'] for u in vis['ranking']['untracked']['all']}
    assert 'WaterWipes' not in untracked
    assert vis['ranking']['outside_category'] == {'others': [{'name': 'WaterWipes', 'named': 2}],
                                                  'own': [{'name': f'{BRAND} Training Pants', 'named': 1}]}


@pytest.mark.parametrize('name,out', [('WaterWipes', True), ('Huggies Pull-Ups', True), ('Pampers Easy Ups', True),
                                      ('Huggies Little Movers', False), ('Coterie', False)])
def test_outside_the_category(name, out):
    assert rm.is_outside_category(name) is out


# ── V4: the coded pick ────────────────────────────────────────────────────

def test_each_row_carries_its_coded_pick(http, db, upstream):
    vis = _vis(db, http, upstream)
    by_run = {v['run']: v for v in vis['byQuestion']}
    assert 'pick' not in by_run[f"run-{f2t5.run_id(0, 'aimode')}"]          # never answered
    assert by_run[f"run-{f2t5.run_id(0, 'chatgpt')}"]['pick'] == 'first'
    assert by_run[f"run-{f2t5.run_id(1, 'claude')}"]['pick'] == 'no_brand_named'
    for v in vis['byQuestion']:
        if v['answered'] and not v['first'] and v['named']:
            assert v['pick'] == 'no_single_pick'


def test_no_single_pick_and_no_pick_coded():
    brands = rm._Brands([{'name': 'Pampers', 'role': 'primary'}, {'name': 'Huggies', 'role': 'competitor'}], [])
    run = {'id': 1, 'platform': 'chatgpt', 'answer_status': 'answered', 'tier': 'category_control',
           'query_text': 'best diaper'}
    named = rm.build_visibility('c', runs=[run], entities=[{'name': 'Pampers', 'role': 'primary'},
                                                           {'name': 'Huggies', 'role': 'competitor'}],
                                mentions=[{'run_id': 1, 'name': 'Huggies', 'position': 2, 'role': 'competitor'}],
                                extractions={1: {'other_brands_named': []}})
    assert named['byQuestion'][0]['pick'] == 'no_single_pick'
    absent = rm.build_visibility('c', runs=[run], entities=[{'name': 'Pampers', 'role': 'primary'}], mentions=[],
                                 extractions={})
    assert absent['byQuestion'][0]['pick'] == 'no_pick_coded'
    assert brands.resolve('Huggies Little Movers') == ('Huggies', False)


# ── V5: routing ───────────────────────────────────────────────────────────

def test_routing_names_each_store_and_splits_by_intent(http, db, upstream):
    routing = _vis(db, http, upstream)['routing']
    for row in routing['rows']:
        assert row['named'] >= row['first']
        assert row['named_surfaces']['all'] == row['named']
    wtb, cheap = routing['intents']['where_to_buy'], routing['intents']['cheapest_place']
    assert routing['default_intent'] == 'where_to_buy'
    assert wtb['total'] + cheap['total'] == routing['total']
    by = {r['name']: r for r in routing['rows']}
    for r in wtb['rows']:
        other = next((c for c in cheap['rows'] if c['name'] == r['name']), {'first': 0, 'named': 0})
        assert r['first'] + other['first'] == by[r['name']]['first']
        assert r['named'] + other['named'] == by[r['name']]['named']
    assert wtb['sub'] == f"{wtb['total']} where-to-buy answers"
    assert wtb['title'] == f"Where agents send {BRAND} shoppers first"
