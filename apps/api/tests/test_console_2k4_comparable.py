"""
2K-4 §B1: one comparability rule (soa_shared/cycle_compare), sqlite and Postgres.

On FL13 the Share of Algorithm tile read "-6 vs FL12-pampers-20261020" and the
metric tiles showed deltas while the Changes block said "Not comparable": the
score never checked the question set, and FL12 and FL13 were different
studies. The score tile, the metric tiles, the Changes block and the revenue
history now ask cycles_comparable, which checks the scorer version, the study
(or identical question codes and tiers), the surfaces, the agents and the
measured set, in that order, and names the first that fails.
"""
import filecmp
import os

import pytest
from sqlalchemy import text

from soa_shared import cycle_compare as cc
from tests import console_fixture_229 as f229
from tests.test_console_2c3a import _supply, db  # noqa: F401  (fixture)
from tests.test_console_2i9 import WS, _fl12_money, _inputs
from tests.test_console_read_models import _encode, as_, http, upstream  # noqa: F401  (pytest fixtures)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
OTHER_STUDY = 'pampers-fl12'
DIFFERENT = f'Not comparable: {f229.PREVIOUS} ran a different study ({OTHER_STUDY}).'


def test_the_two_copies_are_identical():
    assert filecmp.cmp(os.path.join(ROOT, 'apps', 'api', 'soa_shared', 'cycle_compare.py'),
                       os.path.join(ROOT, 'apps', 'pipeline', 'soa_shared', 'cycle_compare.py'), shallow=False)


# ═══ the rule ════════════════════════════════════════════════════════════

def _f(code='PREV', **kw):
    base = dict(study='s', questions={'Q1': 'brand_direct'}, agents={'all': ['chatgpt', 'claude']}, scorer_version='11',
                reads=cc.UNPROMPTED, measured={cc.UNPROMPTED: 10, 'comparison': 4})
    return cc.facts(code, **{**base, **kw})


def test_same_study_same_agents_is_comparable():
    assert cc.cycles_comparable(_f('now'), _f()) == (True, None, None)


def test_the_first_failing_condition_is_named():
    assert cc.cycles_comparable(_f('now', scorer_version='12'), _f(study='t')) == \
        (False, 'version', 'Scored under v11, re-score to compare.')
    assert cc.cycles_comparable(_f('now'), _f(study='t', questions={}, agents={'all': ['chatgpt']})) == \
        (False, 'study', 'Not comparable: PREV ran a different study (t).')
    assert cc.cycles_comparable(_f('now'), _f(agents={'all': ['claude']}), agent_name=str.title) == \
        (False, 'agents', 'Not comparable: PREV ran Claude only.')
    assert cc.cycles_comparable(_f('now', reads=cc.BRAND_CHOICE), _f(measured={cc.UNPROMPTED: 10})) == \
        (False, 'measured', 'Not comparable: PREV asked no comparison questions.')


def test_another_study_with_identical_questions_is_comparable():
    assert cc.cycles_comparable(_f('now'), _f(study='renamed'))[0] is True


def test_the_score_names_the_surface_the_changes_block_says_this_surface():
    now, prev = _f('now', agents={'grounded_api': ['chatgpt', 'claude']}), _f(agents={'grounded_api': ['claude']})
    assert cc.cycles_comparable(now, prev, on=None, surface_name=lambda s: 'the grounded API')[2] == \
        'Not comparable: PREV ran claude only on the grounded API.'
    assert cc.cycles_comparable(now, prev, on=' on this surface')[2] == 'Not comparable: PREV ran claude only on this surface.'


# ═══ FL12 -> FL13: another study, not comparable everywhere, one reason ═══

def _fl13_shape(db, http, upstream):
    """The FL12-shaped fixture's previous cycle as another study, its score stored first."""
    cycle = _fl12_money(db)
    with db.begin() as c:
        job = dict(c.execute(text("SELECT * FROM soa_query_generation_jobs WHERE study_type = "
                                  "(SELECT study_type FROM soa_cycles WHERE id = 178)")).mappings().one())
        job = {k: _encode(v) if isinstance(v, (dict, list)) else v for k, v in job.items()}
        # the fixtures write their ids, so Postgres's sequence has not moved: name one
        job['id'] = c.execute(text("SELECT MAX(id) + 1 FROM soa_query_generation_jobs")).scalar()
        job['study_type'] = OTHER_STUDY
        c.execute(text(f"INSERT INTO soa_query_generation_jobs ({', '.join(job)}) VALUES ({', '.join(':' + k for k in job)})"),
                  job)
        c.execute(text("UPDATE soa_cycles SET study_type = :st WHERE id = 178"), {'st': OTHER_STUDY})
    _supply(upstream)
    as_('op')
    r = http.get('/api/console/score', params={'cycle': f229.PREVIOUS, 'merchant': WS, 'org': 10})
    assert r.status_code == 200 and r.json()['stored'] is True, r.text
    return cycle


def test_fl12_to_fl13_is_not_comparable_on_every_reader_with_the_same_reason(http, db, upstream):
    cycle = _fl13_shape(db, http, upstream)
    score = http.get('/api/console/score', params={'cycle': cycle, 'merchant': WS, 'org': 10}).json()
    assert score['previous']['comparable'] is False and score['previous']['condition'] == 'study'
    assert score['previous']['reason'] == DIFFERENT and 'delta' not in score['previous']
    assert all(m['delta'] is None and m['delta_reason'] == DIFFERENT for m in score['metrics'])
    over = http.get('/api/console/overview', params={'cycle': cycle, 'org': 10}).json()
    for s, block in over['by_surface'].items():
        assert (block['changes_status'], block['changes_note'], block['changes']) == ('not_comparable', DIFFERENT, []), s
    as_('alice')
    _inputs(http, 'PUT', json={'scope_value': 4e9})
    h = http.get('/api/console/revenue/history', params={'merchant': WS}).json()
    first, now = h['cycles']
    assert first['vs_previous'] is None
    assert now['vs_previous'] == {'cycle': f229.PREVIOUS, 'comparable': False, 'condition': 'study', 'reason': DIFFERENT}


def test_the_same_study_reads_the_agents_next(http, db, upstream):
    """The fixture's previous cycle, in its own study, ran ChatGPT only: the next condition."""
    cycle = _fl12_money(db)
    _supply(upstream)
    as_('op')
    over = http.get('/api/console/overview', params={'cycle': cycle, 'org': 10}).json()
    assert over['by_surface']['all']['changes_note'] == f'Not comparable: {f229.PREVIOUS} ran ChatGPT only.'
