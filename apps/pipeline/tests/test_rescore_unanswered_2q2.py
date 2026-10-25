"""
2Q-2 (B): `rescore_cycle.py --tier brand_direct` stamps the current coder on
a brand-direct row whose run has no answer, and says so.

FL15 (593 answers over 594 runs) printed "scored 257/258 (skipped 1)" and its
unanswered run's row kept coder 6, which held the cycle back on the console.
An unanswered run is absent on every coder version, so stamping it is
correct: the printout reads "skipped 1 (no answer), stamped", and every
brand-direct row of the cycle is on the current coder afterwards, whichever
path skipped it (stamp_unanswered).

NOTHING HERE IS RECORDED and there is no model call.
"""
import json

from sqlalchemy import text

from soa_shared import expected_answers as ea
from tests.test_expectation_scorer import db, outcomes  # noqa: F401  (db is a fixture)
from tests.test_retailer_coding_2q1 import _seed_fl14, make_scorer

CYCLE = 'FL14-pampers-20261023'


def _coders(db):
    return {r['run_id']: json.loads(r['extraction']).get('coder', {}).get('version') for r in outcomes(db)}


def _no_answer(db, run_id):
    with db.begin() as conn:
        conn.execute(text("UPDATE soa_runs SET status = 'error', raw_response = NULL WHERE id = :r"), {'r': run_id})


def _rescore(db, capsys, monkeypatch, *args):
    from scripts import rescore_cycle
    monkeypatch.setattr(rescore_cycle, 'engine', db)
    monkeypatch.setattr(rescore_cycle, '_brand_direct_scorer', lambda **_kw: make_scorer())
    monkeypatch.delenv('OPEN_AI_API_KEY', raising=False)
    code = rescore_cycle.main(['--cycle', CYCLE, '--tier', 'brand_direct', *args])
    return code, capsys.readouterr().out


def test_the_unanswered_run_is_stamped_and_the_printout_says_so(db, capsys, monkeypatch):
    _seed_fl14(db)
    _no_answer(db, 1)
    assert set(_coders(db).values()) == {6}

    code, dry = _rescore(db, capsys, monkeypatch, '--dry-run')
    assert code == 0 and "scored 59/60 (skipped 1 (no answer), to stamp, failed 0, retried 0)" in dry
    assert set(_coders(db).values()) == {6}

    code, out = _rescore(db, capsys, monkeypatch)
    assert code == 0 and "scored 59/60 (skipped 1 (no answer), stamped, failed 0, retried 0)" in out
    coders = _coders(db)
    assert len(coders) == 60 and set(coders.values()) == {ea.BRAND_CODER_VERSION}
    (row,) = [r for r in outcomes(db) if r['run_id'] == 1]
    assert json.loads(row['extraction'])['coder'] == {'version': ea.BRAND_CODER_VERSION, 'calls': []}


def test_a_cycle_with_every_run_answered_prints_as_before(db, capsys, monkeypatch):
    _seed_fl14(db)
    code, out = _rescore(db, capsys, monkeypatch)
    assert code == 0 and "scored 60/60 (skipped 0, failed 0, retried 0)" in out


def test_stamp_unanswered_stamps_only_unanswered_rows_off_the_current_coder(db):
    from scripts import rescore_cycle
    _seed_fl14(db)
    _no_answer(db, 1)
    with db.begin() as conn:
        conn.execute(text("UPDATE soa_runs SET answer_status = 'sign_in_wall' WHERE id = 2"))
    with db.connect() as conn:
        assert rescore_cycle.stamp_unanswered(conn, 3) == 2
    coders = _coders(db)
    assert coders[1] == coders[2] == ea.BRAND_CODER_VERSION
    # an answered row on an older coder is the rescore's to re-code, never stamped
    assert {v for k, v in coders.items() if k not in (1, 2)} == {6}
    with db.connect() as conn:
        assert rescore_cycle.stamp_unanswered(conn, 3) == 0
