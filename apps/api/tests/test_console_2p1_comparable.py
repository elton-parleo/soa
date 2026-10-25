"""
2P-1 (B2): the comparability audit, on a cycle that went through FL14's
sequence, sqlite and Postgres.

FL14 was rescored under scorer versions 12 -> 16 (2O-1 to 2O-6), and 17 (2Q-1), with
`--tier brand_direct` runs (which re-select the claims by rule and stamp the
current brand-claim coder on every brand-direct row) and `--classify-only`
refreshes (which re-classify the stored extraction and leave its coder
stamp as it was). Held here, on 2P-1's pair (console_fixture_2p1.py):

  1. a stored score from before the rescores recomputes on the read after a
     tier rescore ('outcomes re-scored', 2N-2) and after a classify-only
     refresh ('cycle reference refreshed', 2J-4), and then carries the
     current scorer version and the current coder on every brand-direct row;
  2. a new cycle of the same study, on the same versions, is comparable on
     every reader: the score and its tiles, the Changes block, the Impact
     history;
  3. a previous cycle whose oldest brand-direct outcome is an older coder's
     reads "Scored under v<n>, re-score to compare." on every one of them,
     never a delta. Before 2P-1 the Changes block and the Impact history
     passed no version to cycle_compare and compared it silently.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import text

from app.services import console_score as score_svc
from soa_shared import expected_answers as ea
from tests import console_fixture_2p1 as f2p1
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import WS, _get, _pair
from tests.test_console_read_models import _encode, as_, http, upstream  # noqa: F401  (pytest fixtures)


def _scored_at_column(db):
    kind = 'TIMESTAMP WITH TIME ZONE' if db.dialect.name == 'postgresql' else 'TEXT'
    with db.begin() as c:
        c.exec_driver_sql(f"ALTER TABLE soa_expectation_outcomes ADD COLUMN scored_at {kind}")
        c.execute(text("UPDATE soa_expectation_outcomes SET scored_at = '2026-10-14T16:00:00+00:00'"))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _coded(db, cycle_id, version, *, only=None):
    """rescore_cycle --tier brand_direct: every brand-direct row of the cycle
    stamped with `version` (the first `only` of them, when given), written now,
    after the score last stored."""
    at = _now()
    with db.begin() as c:
        rows = c.execute(text("SELECT id, extraction FROM soa_expectation_outcomes WHERE cycle_id = :c AND "
                              "tier = 'brand_direct' ORDER BY id"), {'c': cycle_id}).fetchall()
        for n, (oid, extraction) in enumerate(rows):
            if only is not None and n >= only:
                break
            x = extraction if isinstance(extraction, dict) else json.loads(extraction or '{}')
            x['coder'] = {'version': version, 'calls': []}
            c.execute(text("UPDATE soa_expectation_outcomes SET extraction = :x, scored_at = :t WHERE id = :i"),
                      {'x': _encode(x), 't': at, 'i': oid})
    return len(rows)


def _refreshed(db, cycle_id):
    """rescore_cycle --refresh-reference --classify-only: the envelope's refreshed_at, every row re-written."""
    at = _now()
    with db.begin() as c:
        ref = c.execute(text("SELECT reference_prices FROM soa_cycles WHERE id = :c"), {'c': cycle_id}).scalar()
        ref = ref if isinstance(ref, dict) else json.loads(ref)
        ref['refreshed_at'] = at
        c.execute(text("UPDATE soa_cycles SET reference_prices = :p WHERE id = :c"), {'p': _encode(ref), 'c': cycle_id})
        c.execute(text("UPDATE soa_expectation_outcomes SET scored_at = :t WHERE cycle_id = :c"), {'t': at, 'c': cycle_id})


def _stored(db, cycle_id):
    return score_svc.stored_score(db, cycle_id)


def test_fl14_s_sequence_leaves_the_score_on_the_current_versions(http, db, upstream):
    _scored_at_column(db)
    _pair(db, http, upstream, changes=False)
    # the score stored before the rescores: brand-direct rows on coder 5 (2O-5)
    n = _coded(db, f2p1.ID_1, 5)
    first = _get(http, 'score', cycle=f2p1.CYCLE_1, merchant=WS)
    assert first['brand_coder'] == {'version': ea.BRAND_CODER_VERSION, 'of': n, 'coded': 0, 'oldest': 5}
    assert score_svc.comparable_version(_stored(db, f2p1.ID_1)) == '15'

    # --refresh-reference --classify-only: re-classified, the coder stamp kept
    _refreshed(db, f2p1.ID_1)
    after_refresh = _get(http, 'score', cycle=f2p1.CYCLE_1, merchant=WS)
    assert after_refresh['history'][-1]['replaced_because'] == 'cycle reference refreshed'
    assert after_refresh['brand_coder']['oldest'] == 5

    # --tier brand_direct, twice: every brand-direct row on the current coder
    for _twice in range(2):
        _coded(db, f2p1.ID_1, ea.BRAND_CODER_VERSION)
        body = _get(http, 'score', cycle=f2p1.CYCLE_1, merchant=WS)
        assert body['history'][-1]['replaced_because'] == 'outcomes re-scored'
    stored = _stored(db, f2p1.ID_1)
    assert stored['scorer_version'] == score_svc.SCORER_VERSION == '17'
    assert stored['brand_coder'] == {'version': 7, 'of': n, 'coded': n, 'oldest': 7}
    assert score_svc.comparable_version(stored) == '17'
    # and it is served as stored from then on
    assert _get(http, 'score', cycle=f2p1.CYCLE_1, merchant=WS)['inputs']['scored_at'] == stored['inputs']['scored_at']


def _both_on(db, http, version_1):
    _coded(db, f2p1.ID_1, version_1)
    _coded(db, f2p1.ID_2, ea.BRAND_CODER_VERSION)
    _get(http, 'score', cycle=f2p1.CYCLE_1, merchant=WS)


def _history(http):
    as_('op')
    return {c['cycle']: c['vs_previous'] for c in
            http.get('/api/console/revenue/history', params={'merchant': WS, 'org': 10}).json()['cycles']}


def test_a_new_cycle_on_the_same_versions_is_comparable_everywhere(http, db, upstream):
    _scored_at_column(db)
    _pair(db, http, upstream, changes=False)
    _both_on(db, http, ea.BRAND_CODER_VERSION)
    score = _get(http, 'score', merchant=WS)
    assert score['previous']['comparable'] is True and score['previous']['cycle'] == f2p1.CYCLE_1
    assert all(m['delta'] is not None for m in score['metrics'] if m['state'] == 'measured')
    over = _get(http, 'overview', merchant=WS)
    assert {s: b['changes_status'] for s, b in over['by_surface'].items()} == \
        {s: 'compared' for s in over['by_surface']}
    assert _history(http)[f2p1.CYCLE_2]['comparable'] is True


def test_a_previous_cycle_on_an_older_coder_is_never_compared(http, db, upstream):
    _scored_at_column(db)
    _pair(db, http, upstream, changes=False)
    # cycle 1 rescored on all but its first ten brand-direct rows, which stay on coder 5
    _both_on(db, http, ea.BRAND_CODER_VERSION)
    _coded(db, f2p1.ID_1, 5, only=10)
    _get(http, 'score', cycle=f2p1.CYCLE_1, merchant=WS)
    reason = 'Scored under v15, re-score to compare.'
    score = _get(http, 'score', merchant=WS)
    assert (score['previous']['comparable'], score['previous']['condition'], score['previous']['reason']) == \
        (False, 'version', reason)
    assert 'delta' not in score['previous']
    assert all(m['delta'] is None for m in score['metrics'])
    over = _get(http, 'overview', merchant=WS)
    for s, block in over['by_surface'].items():
        assert (block['changes_status'], block['changes_note'], block['changes']) == ('not_comparable', reason, []), s
        assert all(a.get('delta_status') != 'compared' for a in block['agents']), s
    assert _history(http)[f2p1.CYCLE_2] == {'cycle': f2p1.CYCLE_1, 'comparable': False, 'condition': 'version',
                                            'reason': reason}
    # the cycle itself, once its last ten rows are rescored, compares again
    _coded(db, f2p1.ID_1, ea.BRAND_CODER_VERSION)
    _get(http, 'score', cycle=f2p1.CYCLE_1, merchant=WS)
    assert _get(http, 'score', merchant=WS)['previous']['comparable'] is True
    assert _get(http, 'overview', merchant=WS)['by_surface']['all']['changes_status'] == 'compared'


def test_the_outcomes_version_is_the_score_s_rule():
    rows = [{'tier': 'brand_direct', 'outcome': 'grounded', 'coder_version': v} for v in (7, 7, 5)]
    assert score_svc.outcomes_version(rows) == '15'
    assert score_svc.outcomes_version(rows[:2]) == '17'
    assert score_svc.outcomes_version([{'tier': 'catalog_accuracy', 'outcome': 'exact'}]) == '17'
    assert score_svc.outcomes_version([{'tier': 'brand_direct', 'outcome': 'grounded', 'coder_version': None}]) == '11'
