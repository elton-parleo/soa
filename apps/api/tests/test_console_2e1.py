"""
2E-1: a re-run of the domain checks replaces the record and bumps its
revision; the score of record recomputes once on the next read and keeps
the previous value in its history. A Protocol & Feed the checks could not
measure (no product page) reads "not measured: no product page", never the
Audit's 'na'. On sqlite and a local Postgres (test_console_2c3a's db).
"""
import copy

from app.services import console_score as score_svc
from tests.test_console_2c3a import _cycle_229, _get, _stored, db  # noqa: F401  (db is a fixture)
from tests.test_console_2e import NONE, FULL, _dims, _set_domain_checks, _supply, _with_domain_checks, reference_2a3
from tests.test_console_read_models import http, upstream  # noqa: F401


def _revised(record, revision):
    out = copy.deepcopy(record)
    out['revision'] = revision
    return out


def test_a_replaced_record_recomputes_the_score_once_and_keeps_the_old_value(http, upstream, db, monkeypatch):
    _cycle_229(db)
    _with_domain_checks(db, _revised(NONE, 1))
    _supply(upstream, reference_2a3())
    computed = []
    real = score_svc.build_score
    monkeypatch.setattr(score_svc, 'build_score', lambda *a, **k: computed.append(1) or real(*a, **k))
    first = _get(http).json()
    assert first['inputs']['domain_checks']['revision'] == 1
    assert _get(http).json()['score'] == first['score'] and len(computed) == 1      # served from the row

    # run_domain_checks.py --replace: the same measured set, a new revision
    _set_domain_checks(db, _revised(FULL, 2))
    second = _get(http).json()
    assert len(computed) == 2
    assert second['measured'] == first['measured']
    assert second['score'] > first['score']
    assert second['inputs']['domain_checks']['revision'] == 2
    assert [h['score'] for h in second['history']] == [first['score']]
    assert second['history'][0]['replaced_because'] == 'domain checks revision changed'
    assert _get(http).json()['score'] == second['score'] and len(computed) == 2     # once
    raw, _ = _stored(db)
    assert raw is not None


def test_the_revision_trigger():
    stored = {'scorer_version': score_svc.SCORER_VERSION, 'adapter_revision': score_svc.ADAPTER_REVISION,
              'measured': ['agent_access', 'protocol_feed', 'value_protocols']}
    # a score stored before revisions were, on a record stored before them: revision 1 both
    assert score_svc.needs_recompute(stored, FULL) is None
    assert score_svc.needs_recompute({**stored, 'inputs': {'domain_checks': {'revision': 1}}}, _revised(FULL, 1)) is None
    assert score_svc.needs_recompute(stored, _revised(FULL, 2)) == 'domain checks revision changed'
    assert score_svc.needs_recompute({**stored, 'inputs': {'domain_checks': {'revision': 2}}},
                                     _revised(FULL, 3)) == 'domain checks revision changed'
    assert score_svc.record_revision(None) is None and score_svc.record_revision(FULL) == 1


def _no_pdp(record):
    out = copy.deepcopy(record)
    nm = {'score': None, 'max': 5, 'evidence': ['not measured: no product page'], 'fix': None, 'fix_human': None,
          'coverage': 'not_measured', 'deferred_items': [], 'cap_basis': []}
    out['protocol_feed'] = out['domains'][0]['protocol_feed'] = nm
    return out


def test_no_product_page_is_not_measured_with_the_reason_never_na(http, upstream, db):
    _cycle_229(db)
    _with_domain_checks(db, _no_pdp(FULL))
    _supply(upstream, reference_2a3())
    body = _get(http).json()
    pf = _dims(body)['protocol_feed']
    assert pf['state'] == 'not_measured' and pf['reason'] == 'not measured: no product page'
    assert 'protocol_feed' not in body['measured'] and 'value_protocols' in body['measured']
    assert body['verdict'] is None and body['verdict_note'].startswith('No readiness verdict while 5 of 100')
