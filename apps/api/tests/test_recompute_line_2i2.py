"""
2I-2: the recompute line names the input that changed. "scorer 6 → 7:
ungrounded surfaces excluded from pooling" only when the new score in fact
dropped an ungrounded surface; otherwise "scorer 6 → 7" with " · <input>
changed" for each input the two stored bodies show differs, and nothing
guessed when the old body does not carry it. The history entry keeps the
old per-pillar scores. HTTP tests run on sqlite and on a local Postgres.
"""
import json

from sqlalchemy import text

from app.services import console_score as score_svc
from tests.test_console_2c3 import _score, _two_surfaces, _with_store
from tests.test_console_2c3a import _cycle_229, _get, _stored, _supply as _supply_229, db  # noqa: F401
from tests.test_console_read_models import as_, http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_grounded_2i import _second_surface_ungrounded


def _as_v6(db, body, cycle_id, **changes):
    old = {**json.loads(json.dumps(body)), 'scorer_version': '6', **changes}
    old.pop('stored', None)
    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET share_of_algorithm = :b, share_of_algorithm_version = '6' WHERE id = :i"),
                  {'b': json.dumps(old), 'i': cycle_id})
    return old


def _229_now(http, db, upstream):
    _cycle_229(db)
    _supply_229(upstream)
    body = _get(http, rescore=1).json()
    assert body['score'] is not None and 'ungrounded' not in body['coverage']
    return body


# ═══ an all-grounded cycle (229's shape) ═════════════════════════════════
def test_229_with_a_moved_score_and_the_same_inputs_reads_the_plain_line(http, db, upstream):
    now = _229_now(http, db, upstream)
    _as_v6(db, now, 229, score=now['score'] + 4)
    body = _get(http).json()
    assert body['scorer_version'] == '7'
    assert body['history'][-1]['replaced_because'] == 'scorer 6 → 7'


def test_229_with_an_older_reference_read_names_it(http, db, upstream):
    now = _229_now(http, db, upstream)
    inputs = {**now['inputs'], 'reference_run': {**now['inputs']['reference_run'], 'finished_at': '2026-09-20T10:00:00+00:00'}}
    _as_v6(db, now, 229, score=now['score'] + 4, inputs=inputs)
    line = _get(http).json()['history'][-1]['replaced_because']
    assert line == 'scorer 6 → 7 · reference read changed' and 'ungrounded' not in line


def test_229_with_other_incentive_flags_names_them(http, db, upstream):
    now = _229_now(http, db, upstream)
    old = json.loads(json.dumps(now))
    for p in old['pillars']:
        for d in p['dimensions']:
            for row in (d.get('by_surface') or {}).values():
                for part in row['parts'] or []:
                    if d['code'] == 'deal_citability' and part['half'] == 'seen':
                        part['numerator'] = (part['numerator'] or 0) + 1   # supply before #24 flagged one more page
    _as_v6(db, old, 229, score=now['score'] + 4)
    assert _get(http).json()['history'][-1]['replaced_because'] == 'scorer 6 → 7 · incentive flags changed'


def test_a_v6_score_that_carries_no_inputs_reads_the_plain_line(http, db, upstream):
    now = _229_now(http, db, upstream)
    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET share_of_algorithm = :b, share_of_algorithm_version = '6' WHERE id = 229"),
                  {'b': json.dumps({'scorer_version': '6', 'adapter_revision': score_svc.ADAPTER_REVISION,
                                    'score': now['score'] + 4})})
    entry = _get(http).json()['history'][-1]
    assert entry['replaced_because'] == 'scorer 6 → 7'
    assert entry['pillars'] == []


def test_the_history_entry_keeps_the_old_pillar_scores(http, db, upstream):
    now = _229_now(http, db, upstream)
    old = _as_v6(db, now, 229, score=now['score'] + 4)
    entry = _get(http).json()['history'][-1]
    assert (entry['score'], entry['earned'], entry['applicable_max']) == (old['score'], old['earned'], old['applicable_max'])
    assert entry['pillars'] == [{'code': p['code'], 'score': p['score'], 'applicable_max': p['applicable_max']}
                                for p in old['pillars']]
    assert entry['pillars'] and all(set(p) == {'code', 'score', 'applicable_max'} for p in entry['pillars'])


# ═══ a two-surface cycle with one ungrounded ═════════════════════════════
def test_a_two_surface_cycle_with_one_ungrounded_reads_the_ungrounded_line(http, upstream, db):
    from tests.test_console_2c3 import _supply
    _with_store(db)
    _two_surfaces(db)
    _second_surface_ungrounded(db)
    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET share_of_algorithm = :b, share_of_algorithm_version = '6' WHERE id = 1"),
                  {'b': json.dumps({'scorer_version': '6', 'adapter_revision': score_svc.ADAPTER_REVISION, 'score': 68})})
    _supply(upstream)
    as_('alice')
    body = _score(http)
    assert body['coverage']['ungrounded'] == ['api']
    assert body['history'][-1]['replaced_because'] == 'scorer 6 → 7: ungrounded surfaces excluded from pooling'


# ═══ the line itself ═════════════════════════════════════════════════════
def test_a_changed_domain_checks_revision_names_it():
    old = {'scorer_version': '6', 'score': 30, 'inputs': {'domain_checks': {'revision': 1}}}
    new = {'scorer_version': '7', 'score': 33, 'inputs': {'domain_checks': {'revision': 2}}, 'coverage': {}}
    assert score_svc.recompute_line(old, new, 'stale') == 'scorer 6 → 7 · domain checks changed'
    # a record that arrived after the old score was stored is a change too
    assert score_svc.recompute_line({**old, 'inputs': {'domain_checks': None}}, new, 'stale') \
        == 'scorer 6 → 7 · domain checks changed'
    # an old score that never recorded it: nothing guessed
    assert score_svc.recompute_line({**old, 'inputs': {}}, new, 'stale') == 'scorer 6 → 7'


def test_every_changed_input_is_named_in_order():
    run = lambda at: {'id': 7, 'finished_at': at}
    old = {'scorer_version': '6', 'score': 30,
           'inputs': {'domain_checks': {'revision': 1}, 'reference_run': run('2026-10-01T00:00:00+00:00')}}
    new = {'scorer_version': '7', 'score': 33, 'coverage': {},
           'inputs': {'domain_checks': {'revision': 2}, 'reference_run': run('2026-10-14T17:02:00+00:00')}}
    assert score_svc.recompute_line(old, new, 'stale') == \
        'scorer 6 → 7 · domain checks changed · reference read changed'
    # a failed reference read on the new score carries no read: not compared
    assert score_svc.recompute_line(old, {**new, 'inputs': {**new['inputs'], 'reference_run': None}}, 'stale') == \
        'scorer 6 → 7 · domain checks changed'


def test_the_ungrounded_line_needs_an_ungrounded_surface_dropped():
    old = {'scorer_version': '6', 'score': 24}
    assert score_svc.recompute_line(old, {'scorer_version': '7', 'score': 20}, 'stale') == 'scorer 6 → 7'
    assert score_svc.recompute_line(old, {'scorer_version': '7', 'score': 20, 'coverage': {'ungrounded': ['api']}},
                                    'stale') == 'scorer 6 → 7: ungrounded surfaces excluded from pooling'
