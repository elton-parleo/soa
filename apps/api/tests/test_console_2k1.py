"""
2K-1 §1 (E29): the brand-choice set, on FL12's six-agent shape with 12
comparison questions (console_fixture_2k1), sqlite and Postgres.

  17 unprompted + 12 comparison questions x 6 agents = 174 brand-choice answers.
  Lost (2I-9's share, every agent): 57 of the 102 unprompted answers put
    another brand first; of the 72 comparison answers, Pampers 30 and Huggies
    12 (ours 24, nobody 6). 99 of 174.
  Visibility's headline and the Overview's first-pick tiles read the same 174;
  share of mentions and the score's Visibility dimension stay on the 102
  unprompted answers, so the score is FL12's (2I-8) to the point.
"""
from fractions import Fraction

import pytest
from sqlalchemy import text

from app.services import console_score as score_svc
from soa_shared.models.soa_models import SoaMerchantRevenueInputs
from tests.score_2l4 import retailer_rows
from tests import console_fixture_2k1 as f2k1
from tests import console_fixture_229 as f229
from tests.test_console_2c3a import _get, _supply, db  # noqa: F401
from tests.test_console_2i8 import _fl12 as _fl12_2i8
from tests.test_console_read_models import _encode, as_, http, upstream  # noqa: F401  (pytest fixtures)

WS = 'wiggle-and-snug'
PARAMS = {'cycle': f2k1.CYCLE, 'org': 10}
LOST = Fraction(57 + 30 + 12, 102 + 72)


def _fl12_comparison(db):
    f2k1.load(db, _encode)
    kind = 'JSON' if db.dialect.name == 'postgresql' else 'TEXT'
    with db.begin() as c:
        c.exec_driver_sql(f"ALTER TABLE soa_cycles ADD COLUMN share_of_algorithm {kind}")
        c.exec_driver_sql("ALTER TABLE soa_cycles ADD COLUMN share_of_algorithm_version TEXT")
    SoaMerchantRevenueInputs.__table__.create(db, checkfirst=True)
    return f2k1.CYCLE


def _visibility(http):
    as_('op')
    r = http.get('/api/console/visibility', params=PARAMS)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_rows_say_brand_choice_and_174_are_counted(http, db, upstream):
    _fl12_comparison(db)
    rows = _visibility(http)['byQuestion']
    answered = [r for r in rows if r['answered']]
    comparison = [r for r in answered if r['tier'] == 'comparison']
    assert len(comparison) == 72 and all(r['brand_choice'] and not r['unprompted'] for r in comparison)
    assert all(r['type'] == 'Comparison' for r in comparison)
    assert sum(r['unprompted'] for r in answered) == 102
    assert sum(r['brand_choice'] for r in answered) == 174
    # a category-control question that names the brand is neither
    named = [r for r in answered if r['tier'] == 'category_control' and not r['unprompted']]
    assert named and not any(r['brand_choice'] for r in named)


def test_lost_is_over_the_174_brand_choice_answers_by_hand(http, db, upstream):
    cycle = _fl12_comparison(db)
    _supply(upstream)
    as_('alice')
    body = http.get('/api/console/revenue', params={'cycle': cycle, 'merchant': WS}).json()
    assert body['counts']['lost'] == {'n': 99, 'of': 174, 'you_first': 33 + 24}
    assert body['counts']['lost_set'] == 'brand-choice'
    assert body['counts']['lost_rivals'] == [['Pampers', 57], ['Huggies', 42]]
    assert body['shares']['lost'] == pytest.approx(float(LOST))
    lost = body['drivers'][0]
    assert lost['measured'] == ('99 of the 174 brand-choice answers put another brand first, 57%. '
                                'Pampers first in 57, Huggies in 42. Wiggle & Snug came first in 57.')
    assert '99 of 174 brand-choice answers put another brand first' in body['basis']
    assert body['heroBasis'].startswith('57% of brand-choice answers put another brand first')
    # Lost's denominator is the headline's
    assert body['counts']['lost']['of'] == _visibility(http)['headlines']['all']['denom']


def test_the_headline_reads_brand_choice_answers_when_the_cycle_asked_comparisons(http, db, upstream):
    _fl12_comparison(db)
    head = _visibility(http)['headlines']['all']
    assert (head['tier'], head['denom'], head['first'], head['named']) == ('brand_choice', 174, 57, 51 + 66)
    # ours first in 57, Pampers in 57 too: not ahead, so the gap sentence
    assert head['text'] == 'Named in 117 of 174 brand-choice answers. Pampers first in 57, Huggies in 42.'


def test_without_a_comparison_question_the_headline_is_2i8_s_unprompted_wording(http, db, upstream):
    _fl12_2i8(db)
    head = _visibility(http)['headlines']['all']
    assert (head['tier'], head['denom']) == ('unprompted', 102)
    assert 'unprompted answers' in head['text'] and 'brand-choice' not in head['text']


def test_the_first_pick_tiles_and_metric_counts_read_brand_choice_share_of_mentions_does_not(http, db, upstream):
    _fl12_comparison(db)
    _supply(upstream)
    body = _get(http, rescore=1).json()
    rows = {m['key']: m for m in retailer_rows(body)}
    assert (rows['first']['value'], rows['first']['denominator']) == (57, 174)
    assert (rows['share']['value'], rows['share']['denominator']) == (117, 174)
    assert rows['first']['surface_note'] == 'across every agent, brand-choice answers'
    assert body['metric_counts']['all']['tier'] == 'brand_choice'
    # share of mentions stays on the 102 unprompted answers
    som = next(d for p in body['pillars'] for d in p['dimensions'] if d['code'] == 'share_of_mentions')
    assert all(part['source'] == 'soa_coded_mentions, answered unprompted runs'
               for row in (som.get('by_surface') or {}).values() for part in row.get('parts') or [])
    as_('op')
    over = http.get('/api/console/overview', params={**PARAMS, 'merchant': WS}).json()
    totals = over['by_surface']['all']['totals']
    assert (over['by_surface']['all']['tier'], totals['first'], totals['named'], totals['named_of']) == \
        ('brand_choice', 57, 117, 174)
    assert over['coverage']['unprompted'] == 102 and over['coverage']['brand_choice'] == 174


def test_the_score_does_not_move_when_the_12_are_comparison_rather_than_branded_control(http, db, upstream):
    """The 12 questions were branded category control in 2I-8's FL12 (out of
    the unprompted set) and are comparison here (out of it too): retagged
    back, every dimension, pillar and the score are the same."""
    _fl12_comparison(db)
    _supply(upstream)
    keep = ('score', 'earned', 'applicable_max', 'verdict', 'pillars', 'surfaces', 'measured', 'biggest_gap')
    with_comparison = _get(http, rescore=1).json()
    assert with_comparison['scorer_version'] == '14'
    assert with_comparison['unprompted'] == {'questions': 17, 'named_the_brand': 33 - 12, 'category_control': 38}
    with db.begin() as c:
        c.execute(text("UPDATE soa_queries SET tier = 'category_control' WHERE tier = 'comparison'"))
    as_control = _get(http, rescore=1).json()
    assert as_control['unprompted'] == {'questions': 17, 'named_the_brand': 33, 'category_control': 50}
    assert {k: with_comparison[k] for k in keep} == {k: as_control[k] for k in keep}
    # and the first-pick rows fall back to the unprompted set
    assert {m['key']: m['denominator'] for m in retailer_rows(as_control)}['first'] == 102


def test_the_study_list_counts_the_comparison_tier(http, db, upstream):
    _fl12_comparison(db)
    as_('op')
    [study] = [s for s in http.get('/api/console/studio/studies', params={'org': 10}).json() if s['id'] == f229.STUDY]
    # 12 comparison questions name the brand: branded, and counted beside
    counts = study['prompt_counts']
    assert counts['comparison'] == 12 and counts['prompts'] == 87
    assert sum(1 for p in study['prompts'] if p['tier'] == 'comparison') == 12


def test_scorer_11_names_its_change_and_never_explains_a_moved_score():
    assert score_svc.SCORER_VERSION == '14'
    assert score_svc.SCORER_CHANGES['11'] == 'brand-choice set for Lost and the first-pick tiles'
    assert score_svc.SCORER_CHANGE_APPLIES['11']({}) is False


def test_the_preview_gives_the_comparison_stage_its_own_line():
    from app.services import console_studies as cs
    from soa_shared.catalog_snapshot import CatalogSnapshot
    snap = CatalogSnapshot(available=False, merchant_slug='pampers', read_at='2026-10-21T00:00:00+00:00', error='down')
    snap.brand = 'Pampers'
    stages = {'Awareness': 13, 'Research': 13, 'Comparison': 12, 'Ready to Buy': 12}
    out = cs.build_preview(snap, tiers={'category_control': True}, stage_total=50, stage_targets=stages)['tiers']
    assert out['comparison']['count'] == 12
    assert out['comparison']['line'] == '12 questions, each naming the brand and a rival'
    assert (out['category_control']['count'], out['category_control']['line']) == (38, '38 questions, none naming the brand')
    # no stage counts sent (an older console): 2I-7's preview, unchanged
    old = cs.build_preview(snap, tiers={'category_control': True}, stage_total=50)['tiers']
    assert 'comparison' not in old and old['category_control']['count'] == 50


def test_the_lead_headline_reads_first_in_n_of_m_brand_choice_answers():
    from app.services import console_parity as parity
    ours, rival = {'name': 'Pampers', 'you': True}, {'name': 'Huggies', 'you': False}
    row = lambda tier, first, unprompted: {'answered': True, 'surface': 'grounded_api', 'tier': tier,  # noqa: E731
                                           'unprompted': unprompted, 'brand_choice': True, 'named': [first],
                                           'first': first}
    rows = [row('category_control', ours, True)] * 3 + [row('comparison', ours, False)] * 2 + \
        [row('comparison', rival, False)]
    head = parity.visibility_headline(rows, 'all', 'Pampers')
    assert (head['tier'], head['text']) == ('brand_choice', 'First in 5 of 6 brand-choice answers.')
    # no comparison question: the unprompted wording, over the unprompted rows only
    head = parity.visibility_headline(rows[:3], 'all', 'Pampers')
    assert (head['tier'], head['text']) == ('unprompted', 'First in 3 of 3 unprompted answers.')
