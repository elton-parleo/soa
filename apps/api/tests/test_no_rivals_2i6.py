"""
2I-6 B2: no share-of-mentions score without a rival (console scorer 8).

Share of mentions is our mentions over every tracked entity's, so a cycle
whose comparison set is the brand alone scored it 1 of 1 whenever the brand
was named: the brand's first cycle, FL7 (2I-5's first-cycle rule, before any
competitor was entered), scored 54 on its grounded surface with the brand
named in 1 of 15 answers. Without a tracked competitor the dimension is not
measured: its points leave the applicable max and the verdict is withheld.

FL7 and FL4 are production cycles with no recorded sample here, so the
one-entity case is cycle 229 (the recorded W&S full loop, console_fixture_229)
with its rivals taken out of the comparison set: FL7's shape on 229's runs.
229 as recorded (two rivals) scores as before. On sqlite and a local Postgres.
"""
import pytest
from sqlalchemy import text

from app.services import console_score as score_svc
from soa_shared.scan_dimensions import DIMENSIONS_BY_CODE, FULL_CYCLE_SCORER_VERSION
from tests.test_console_2c3a import _cycle_229, _get, _supply as _supply_229, db  # noqa: F401
from tests.test_console_read_models import as_, http, upstream  # noqa: F401  (pytest fixtures)

SOM = float(DIMENSIONS_BY_CODE['share_of_mentions'].weight)


def _dims(body, code):
    return next(d for p in body['pillars'] for d in p['dimensions'] if d['code'] == code)


def _score(http, db, upstream, *, rivals=True, load=True):
    if load:
        _cycle_229(db)
        _supply_229(upstream)
    if not rivals:
        with db.begin() as c:
            c.execute(text("DELETE FROM soa_cycle_entities WHERE cycle_id = 229 AND role = 'competitor'"))
    r = _get(http, rescore=1)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_versions(http, db, upstream):
    assert score_svc.SCORER_VERSION == '10' and FULL_CYCLE_SCORER_VERSION == '7'
    assert score_svc.SCORER_CHANGES['8'] == 'share of mentions not measured without a tracked competitor'


def test_229_with_its_rivals_scores_as_before_but_for_the_version(http, db, upstream):
    """The body build_score made before 2I-6 (no rival count: every share-of-mentions measured) is the body now."""
    now = _score(http, db, upstream)
    som = _dims(now, 'share_of_mentions')
    assert som['state'] != 'not_measured' and score_svc.TEMPLATES['reason.no_rivals'] not in str(som)
    with db.connect() as c:
        row = dict(c.execute(text("SELECT * FROM soa_cycles WHERE id = 229")).mappings().one())
        runs, mentions = score_svc.load_score_runs(c, row), score_svc.load_score_mentions(c, row)
        assert score_svc.load_tracked_rivals(c, row) == 3
    kw = dict(runs=runs, mentions=mentions, vis_rows=[], access=None, reference_rows=None, inputs={})
    before = score_svc.build_score(row['cycle_code'], **kw)                       # rivals not read: the old path
    after = score_svc.build_score(row['cycle_code'], **kw, rivals=3)
    assert before == after


def test_a_cycle_tracking_the_brand_alone_does_not_measure_share_of_mentions(http, db, upstream):
    tracked = _score(http, db, upstream)
    alone = _score(http, db, upstream, rivals=False, load=False)
    som = _dims(alone, 'share_of_mentions')
    assert som['state'] == 'not_measured' and som['score'] is None
    assert som['reason'] == 'no competitor is tracked on this cycle: add competitors in the wizard'
    assert all(row['state'] == 'not_measured' and row['applicable_max'] == 0 for row in som['by_surface'].values())
    # its points leave the applicable max, and the verdict is withheld
    assert alone['applicable_max'] == pytest.approx(tracked['applicable_max'] - SOM, abs=0.1)
    assert alone['verdict'] is None and alone['verdict_note']
    # recommendation strength and the named counts do not depend on the set
    rec_t, rec_a = _dims(tracked, 'recommendation_strength'), _dims(alone, 'recommendation_strength')
    assert (rec_a['score'], rec_a['state']) == (rec_t['score'], rec_t['state'])
    assert 'share_of_mentions' not in alone['measured'] and 'share_of_mentions' in tracked['measured']


def test_the_recompute_line_names_the_change_when_it_applies(http, db, upstream):
    alone = _score(http, db, upstream, rivals=False)
    old = {'scorer_version': '7', 'score': (alone['score'] or 0) + 9}
    assert score_svc.recompute_line(old, alone, 'stale') == \
        'scorer 7 → 10: share of mentions not measured without a tracked competitor'
    tracked = {'scorer_version': '8', 'score': 31, 'pillars': [], 'coverage': {}}
    assert score_svc.recompute_line({'scorer_version': '7', 'score': 30}, tracked, 'stale') == 'scorer 7 → 8'
