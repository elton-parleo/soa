"""
2L-3, the worker's half: the full loop writes a scored cycle's console
narratives once (fullloop/coordinator.py _narratives), and
scripts/rescore_cycle.py --narratives rewrites them (--dry-run prints them and
stores nothing). The writer, the checks and the read are soa_shared/
narratives.py, tested end to end on the FL13-shaped fixture in
apps/api/tests/test_narratives_2l3.py. No model is called here.
"""
import argparse

import pytest
from sqlalchemy import create_engine, text

from scripts import rescore_cycle as rc
from soa_shared import narratives
from tests.test_full_loop_coordinator import NOW, FakeSupply, cycle_status, db, request  # noqa: F401  (fixture)
from fullloop.coordinator import Coordinator

NARRATIVES_TABLE = """CREATE TABLE soa_narratives (id INTEGER PRIMARY KEY, cycle_id INTEGER, subject TEXT,
    facts_digest TEXT, line TEXT, status TEXT, reason TEXT, model TEXT, calls TEXT, written_at TIMESTAMP)"""


class Writes:
    """write_cycle's stand-in: records each call, returns one accepted line."""

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, engine, cycle_id, writer, **kw):
        self.calls.append((cycle_id, writer, kw))
        if self.fail:
            raise RuntimeError('model down')
        return [{'subject': 'answer:run-1', 'status': 'accepted', 'line': 'ChatGPT said $1.00.', 'reason': None,
                 'calls': [{'usage': {'input_tokens': 700, 'output_tokens': 40}}] * 2}]


def _loop(db, monkeypatch, *, writer=object(), table=True, fail=False, cycle='complete'):
    if table:
        with db.begin() as c:
            c.exec_driver_sql(NARRATIVES_TABLE)
    writes = Writes(fail)
    monkeypatch.setattr(narratives, 'write_cycle', writes)
    supply = FakeSupply('reference_done')
    co = Coordinator(engine=db, client_for=supply.client, clock=lambda: NOW, writer_for=lambda: writer)
    rid = request(db, status='reference_done')
    co.tick()
    cycle_status(db, co.get(rid)['cycle_id'], cycle)
    co.tick()
    return co, rid, writes


def test_a_scored_cycle_gets_its_narratives_once(db, monkeypatch):
    writer = object()
    co, rid, writes = _loop(db, monkeypatch, writer=writer)
    row = co.get(rid)
    assert row['status'] == 'scored'
    assert writes.calls == [(row['cycle_id'], writer, {})]     # no force: current lines are skipped


def test_a_failed_cycle_gets_none(db, monkeypatch):
    co, rid, writes = _loop(db, monkeypatch, cycle='failed')
    assert co.get(rid)['status'] == 'failed'
    assert writes.calls == []


def test_with_the_flag_off_nothing_is_written(db, monkeypatch):
    co, rid, writes = _loop(db, monkeypatch, writer=None)
    assert co.get(rid)['status'] == 'scored'
    assert writes.calls == []


def test_without_the_table_nothing_is_written_and_the_cycle_is_scored(db, monkeypatch):
    co, rid, writes = _loop(db, monkeypatch, table=False)
    assert co.get(rid)['status'] == 'scored'
    assert writes.calls == []


def test_a_writer_that_fails_never_fails_the_loop(db, monkeypatch):
    co, rid, writes = _loop(db, monkeypatch, fail=True)
    assert co.get(rid)['status'] == 'scored'
    assert len(writes.calls) == 1


def test_the_default_writer_follows_the_flag(monkeypatch):
    from fullloop import coordinator
    monkeypatch.delenv(narratives.FLAG, raising=False)
    assert coordinator._default_writer() is None
    monkeypatch.setenv(narratives.FLAG, '1')
    assert isinstance(coordinator._default_writer(), narratives.LiveWriter)


@pytest.fixture
def rescore_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as c:
        c.exec_driver_sql("CREATE TABLE soa_cycles (id INTEGER PRIMARY KEY, cycle_code TEXT)")
        c.exec_driver_sql("INSERT INTO soa_cycles (id, cycle_code) VALUES (229, 'FL13-pampers-20261020')")
    monkeypatch.setattr(rc, 'engine', engine)
    return engine


def _args(**kw):
    return argparse.Namespace(**{'cycle': 'FL13-pampers-20261020', 'dry_run': False, **kw})


def test_rescore_narratives_dry_run_prints_the_lines_and_stores_nothing(rescore_db, monkeypatch):
    writes = Writes()
    monkeypatch.setattr(narratives, 'write_cycle', writes)
    out = []
    writer = type('W', (), {'model': 'gpt-test'})()
    assert rc._main_narratives(_args(dry_run=True), writer=writer, log=out.append) == 0
    assert writes.calls == [(229, writer, {'dry_run': True, 'force': True, 'log': out.append})]
    text_ = '\n'.join(out)
    assert 'dry run: the model is called, nothing is stored' in text_
    assert 'answer:run-1  [accepted]  ChatGPT said $1.00.' in text_
    assert 'accepted 1, dropped 0, null 0; 2 calls, 1400 input / 80 output tokens' in text_
    assert 'stored' not in out[-1]


def test_rescore_narratives_refuses_to_store_without_the_table(rescore_db, monkeypatch):
    monkeypatch.setattr(narratives, 'write_cycle', Writes())
    with pytest.raises(SystemExit, match='c8e2f4a6b1d3'):
        rc._main_narratives(_args(), writer=object(), log=lambda s: None)
    with rescore_db.begin() as c:
        c.exec_driver_sql(NARRATIVES_TABLE)
    out = []
    assert rc._main_narratives(_args(), writer=object(), log=out.append) == 0
    assert out[-2].endswith('; stored')
    # 2M-3: the cost-per-cycle estimate at the configured model's published price, said to be unverified
    assert out[-1].startswith('about $') and out[-1].endswith('unverified)')


def test_rescore_narratives_runs_on_its_own():
    with pytest.raises(SystemExit):
        rc.main(['--cycle', 'X', '--narratives', '--classify-only'])


def test_rescore_narratives_prints_each_call_of_a_dropped_line(rescore_db, monkeypatch):
    """2L-3a: a drop is read from what each call wrote (a line beside a null, or a failed check)."""
    def dropped(engine, cycle_id, writer, **kw):
        return [{'subject': 'answer:run-2', 'status': 'dropped', 'line': None, 'reason': 'calls_disagree:null',
                 'calls': [{'line': 'ChatGPT said $1.00.', 'check': None, 'usage': {}},
                           {'line': None, 'check': 'no_line', 'usage': {}}]}]
    monkeypatch.setattr(narratives, 'write_cycle', dropped)
    out = []
    rc._main_narratives(_args(dry_run=True), writer=type('W', (), {'model': 'm'})(), log=out.append)
    assert '      call 1 [pass]  ChatGPT said $1.00.' in out
    assert '      call 2 [no_line]  ' in out
