"""
2Q-2 (B): a run with no answer never holds a cycle back on the coder version.

FL15 has 593 answers over 594 runs. `rescore_cycle.py --tier brand_direct`
printed "scored 257/258 (skipped 1)": the unanswered run's row kept coder 6,
and the score card and every tile read "Scored under v16, re-score to
compare." while the Changes block on the same page compared FL14 and FL15.
An unanswered run is absent on every coder version, so brand_coder (2P-1's
helper, which the score, its tiles, Changes, Visibility, True Value, Trade
promotions and Impact all read through outcomes_version / comparable_version)
leaves it out. Held here, on 2P-1's pair (console_fixture_2p1.py):

  1. one unanswered run still on an older coder: comparable on every reader;
  2. one answered row genuinely on an older coder: "re-score to compare" on
     every reader, the Changes block included, never a delta;
  3. a score stored before 2Q-2, whose block counted the unanswered row,
     is recounted on the next read.
"""
import json

from sqlalchemy import text

from app.services import console_score as score_svc
from soa_shared import expected_answers as ea
from tests import console_fixture_2p1 as f2p1
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_comparable import _both_on, _history, _now, _scored_at_column
from tests.test_console_2p1_two_cycles import WS, _get, _pair
from tests.test_console_read_models import _encode, as_, http, upstream  # noqa: F401  (pytest fixtures)


def _brand_rows(db, cycle_id):
    with db.begin() as c:
        return c.execute(text("SELECT id, run_id, extraction FROM soa_expectation_outcomes WHERE cycle_id = :c AND "
                              "tier = 'brand_direct' ORDER BY id"), {'c': cycle_id}).fetchall()


def _on_coder(db, outcome_id, extraction, version, **row):
    x = extraction if isinstance(extraction, dict) else json.loads(extraction or '{}')
    x['coder'] = {'version': version, 'calls': []}
    sets = ''.join(f', {k} = :{k}' for k in row)
    with db.begin() as c:
        c.execute(text(f"UPDATE soa_expectation_outcomes SET extraction = :x, scored_at = :t{sets} WHERE id = :i"),
                  {'x': _encode(x), 't': _now(), 'i': outcome_id, **row})


def _unanswered(db, cycle_id, version=6):
    """The first brand-direct run of the cycle as FL15's: no answer arrived, its
    row absent and still on an older coder."""
    oid, run_id, extraction = _brand_rows(db, cycle_id)[0]
    with db.begin() as c:
        c.execute(text("UPDATE soa_runs SET status = 'error', raw_response = NULL WHERE id = :r"), {'r': run_id})
    _on_coder(db, oid, extraction, version, outcome='absent')


def _everywhere(http):
    score = _get(http, 'score', merchant=WS)
    over = _get(http, 'overview', merchant=WS)
    return score, over, _history(http)[f2p1.CYCLE_2]


def test_an_unanswered_run_on_an_older_coder_is_comparable_everywhere(http, db, upstream):
    _scored_at_column(db)
    _pair(db, http, upstream, changes=False)
    _both_on(db, http, ea.BRAND_CODER_VERSION)
    _unanswered(db, f2p1.ID_2)
    score, over, history = _everywhere(http)
    n = len(_brand_rows(db, f2p1.ID_2))
    assert score['brand_coder'] == {'version': ea.BRAND_CODER_VERSION, 'of': n - 1, 'coded': n - 1,
                                    'oldest': ea.BRAND_CODER_VERSION, 'unanswered': 1}
    assert score['previous']['comparable'] is True and score['previous']['cycle'] == f2p1.CYCLE_1
    assert all(m['delta'] is not None for m in score['metrics'] if m['state'] == 'measured')
    assert {s: b['changes_status'] for s, b in over['by_surface'].items()} == \
        {s: 'compared' for s in over['by_surface']}
    assert history['comparable'] is True
    # and on the previous cycle too (FL14 with an unanswered run of its own)
    _unanswered(db, f2p1.ID_1, version=5)
    _get(http, 'score', cycle=f2p1.CYCLE_1, merchant=WS)
    score, over, history = _everywhere(http)
    assert score['previous']['comparable'] is True
    assert {b['changes_status'] for b in over['by_surface'].values()} == {'compared'}
    assert history['comparable'] is True


def test_an_answered_row_on_an_older_coder_is_never_compared_anywhere(http, db, upstream):
    _scored_at_column(db)
    _pair(db, http, upstream, changes=False)
    _both_on(db, http, ea.BRAND_CODER_VERSION)
    _unanswered(db, f2p1.ID_2)
    # one answered brand-direct row of this cycle genuinely on coder 6
    oid, _run, extraction = _brand_rows(db, f2p1.ID_2)[1]
    _on_coder(db, oid, extraction, 6)
    score, over, history = _everywhere(http)
    assert score['brand_coder']['oldest'] == 6 and score['brand_coder']['unanswered'] == 1
    previous = score['previous']
    assert (previous['comparable'], previous['condition']) == (False, 'version')
    reason = previous['reason']
    assert reason.startswith('Scored under v') and reason.endswith(', re-score to compare.')
    assert all(m['delta'] is None for m in score['metrics'])
    for s, block in over['by_surface'].items():
        assert (block['changes_status'], block['changes_note'], block['changes']) == ('not_comparable', reason, []), s
        assert all(a.get('delta_status') != 'compared' for a in block['agents']), s
    assert history == {'cycle': f2p1.CYCLE_1, 'comparable': False, 'condition': 'version', 'reason': reason}


def test_a_score_stored_counting_the_unanswered_row_is_recounted(http, db, upstream):
    _scored_at_column(db)
    _pair(db, http, upstream, changes=False)
    _both_on(db, http, ea.BRAND_CODER_VERSION)
    _unanswered(db, f2p1.ID_2)
    stored = _get(http, 'score', merchant=WS)
    # the block as a score stored before 2Q-2 counted it: 257 of 258, oldest 6
    body = score_svc.stored_score(db, f2p1.ID_2)
    of = body['brand_coder']['of'] + 1
    body['brand_coder'] = {'version': ea.BRAND_CODER_VERSION, 'of': of, 'coded': of - 1, 'oldest': 6}
    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET share_of_algorithm = :b WHERE id = :i"),
                  {'b': _encode(body), 'i': f2p1.ID_2})
    assert score_svc.needs_recompute(body, None) == 'brand coder recounted'
    as_('op')
    again = _get(http, 'score', merchant=WS)
    assert again['history'][-1]['replaced_because'] == 'brand coder recounted'
    assert again['brand_coder'] == stored['brand_coder'] and again['brand_coder']['unanswered'] == 1
    assert again['previous']['comparable'] is True


def test_brand_coder_leaves_an_unanswered_row_out():
    rows = [{'tier': 'brand_direct', 'outcome': 'grounded', 'coder_version': 7, 'answered': True},
            {'tier': 'brand_direct', 'outcome': 'absent', 'coder_version': 6, 'answered': False}]
    assert score_svc.outcomes_version(rows) == score_svc.SCORER_VERSION
    assert score_svc.outcomes_version([{**rows[1], 'answered': True}, rows[0]]) == '16'
    assert score_svc.brand_coder(rows)['unanswered'] == 1
