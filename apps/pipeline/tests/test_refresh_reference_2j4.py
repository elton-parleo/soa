"""
2J-4: rescore_cycle --refresh-reference, on an FL12-shaped cycle (Pampers,
a brand, scored Oct 20 against supply's reads before 2J-1 corrected them).

The recorded two-payload fixture (packages/testing/fixtures/
retailer_prices_fl12_2j4.json) is supply's retailer-prices for one variant
as of the cycle's stored as_of, before and after reparse_reads.py --apply:
Amazon $0.00 -> $27.97, Target $10.00 -> unverifiable (page read, no
price), pampers.com 9.97 -> none_by_design. Every agent quoted $27.97.

Held here, on sqlite and Postgres: the diff table; --dry-run writes
nothing; the write backs up, replaces the payload with the envelope and
moves exactly the expected rows; --restore puts the cycle back byte for
byte; the refusals; the stale basis and the next cycle are untouched.
"""
import json
import os
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

import soa_pg_harness
from clients.truesync_catalog import CatalogSnapshot, TrueSyncCatalogClient
from scoring import expectation_scorer as scorer_module
from scripts import rescore_cycle as rc
from soa_pg_harness import model_schema
from soa_shared import expected_answers as ea
from soa_shared.models.soa_models import Base

with open(os.path.join(os.path.dirname(soa_pg_harness.__file__), 'fixtures', 'retailer_prices_fl12_2j4.json')) as _fh:
    PAYLOADS = json.load(_fh)
BEFORE, AFTER = PAYLOADS['before'], PAYLOADS['after']
AS_OF = BEFORE['as_of']

PRIOR, CYCLE, NEXT = 'FL11-pampers-20261013', 'FL12-pampers-20261020', 'FL13-pampers-20261027'
GTIN = '00037000863434'
SOURCE_REF = {'merchant_slug': 'pampers', 'variant_id': GTIN, 'gtin': GTIN, 'own_domain': 'pampers.com',
              'merchant_kind': 'brand', 'retailer_list': ['amazon.com', 'target.com']}
#: (run id, query code, asked at, the amount the answer stated, the outcome stored against BEFORE)
RUNS = [
    (1201, 'PAM_CAT_1', 'amazon.com', '27.97', 'wrong'),
    (1202, 'PAM_CAT_2', 'target.com', '27.97', 'wrong'),
    (1203, 'PAM_CAT_3', 'pampers.com', '27.97', 'wrong'),
    (1204, 'PAM_CAT_4', 'amazon.com', '25.00', 'wrong'),     # wrong on both: does not move
]


def extraction(amount):
    return {'prices': [{'amount': amount, 'currency': 'USD', 'attributed_product': 'Pampers Swaddlers Newborn 84'}],
            'codes': [], 'pack_counts': [], 'gtins': [], 'member_prices': [], 'points': [],
            'brand_mentioned': True, 'sources_cited': [], 'extraction_confident': True, 'extraction_note': None}


class Supply(TrueSyncCatalogClient):
    """The real client over the recorded payload: no network. Records the
    as_of it was asked for."""

    def __init__(self, payload=AFTER, error=None):
        super().__init__(base_url='https://supply.example', token='t')
        self.payload, self.error, self.asked = payload, error, []

    def _get(self, path, params=None):
        self.asked.append((path, params))
        if path.endswith('/retailer-prices'):
            return (None, self.error) if self.error else (json.loads(json.dumps(self.payload)), None)
        return None, f'no fixture for {path}'

    def snapshot(self, slug, *, with_history=True):
        return CatalogSnapshot(available=False, merchant_slug=slug, read_at='2026-10-21T00:00:00+00:00',
                               error='fixture: no catalog')


def scorer():
    return scorer_module.ExpectationScorer(client=rc._NoModel(), history=scorer_module.HistoryCache(Supply()),
                                           brand_facts=NoFacts(), labeler=False,
                                           references=scorer_module.ReferenceCache(fetch=False),
                                           domain_checker=False)


class NoFacts:
    def for_merchant(self, _slug, study_type=None):
        return {}


@pytest.fixture
def fl12(any_engine, monkeypatch):
    model_schema(any_engine)
    t = Base.metadata.tables
    with any_engine.begin() as c:
        c.execute(t['organizations'].insert(), [{'id': 12, 'name': 'Pampers'}])
        for cid, code, day, payload in ((11, PRIOR, date(2026, 10, 13), {**BEFORE, 'as_of': '2026-10-13T13:05:00+00:00'}),
                                        (12, CYCLE, date(2026, 10, 20), BEFORE),
                                        (13, NEXT, date(2026, 10, 27), {**BEFORE, 'as_of': '2026-10-27T13:05:00+00:00'})):
            c.execute(t['soa_cycles'].insert(), [{
                'id': cid, 'cycle_code': code, 'start_date': day, 'status': 'complete', 'study_type': 'pampers',
                'study_pattern': 'brand_at_retail', 'cycle_mode': 'query', 'organization_id': 12,
                'platforms': ['chatgpt'], 'reference_prices': payload,
                'reference_as_of': datetime.fromisoformat(payload['as_of'])}])
        for n, (run_id, code, retailer, amount, outcome) in enumerate(RUNS, start=1):
            expected = ea.price('27.97', attributed_to=retailer)
            c.execute(t['soa_queries'].insert(), [{
                'id': n, 'query_code': code, 'query_text': f'How much are Pampers Swaddlers NB 84 at {retailer}?',
                'category': 'Baby Care', 'stage': 'Ready to Buy', 'specificity': 'Narrow',
                'persona': 'Value-Conscious Parent', 'status': 'Active', 'study_type': 'pampers',
                'study_pattern': 'brand_at_retail', 'organization_id': 12, 'tier': 'catalog_accuracy',
                'expected_answer': expected, 'source_ref': SOURCE_REF}])
            for cid, rid in ((12, run_id), (13, run_id + 100)):
                c.execute(t['soa_runs'].insert(), [{
                    'id': rid, 'cycle_id': cid, 'query_id': n, 'platform': 'chatgpt', 'run_number': 1,
                    'raw_response': 'answer', 'status': 'success', 'surface': 'grounded_api',
                    'answer_status': 'answered'}])
                c.execute(t['soa_expectation_outcomes'].insert(), [{
                    'run_id': rid, 'query_id': n, 'cycle_id': cid, 'platform': 'chatgpt', 'tier': 'catalog_accuracy',
                    'expected_answer': expected, 'extraction': extraction(amount), 'outcome': outcome,
                    'extraction_model': 'gpt-x', 'surface': 'grounded_api'}])
    monkeypatch.setattr(rc, 'engine', any_engine)
    monkeypatch.setattr(scorer_module, 'engine', any_engine)
    # as production holds them: written by the scorer, against the cached copy
    for code in (CYCLE, NEXT):
        assert rc.classify_only(code, scorer=scorer())['moved'] == []
    return any_engine


def _raw(db, code):
    with db.connect() as c:
        return c.execute(text("SELECT CAST(reference_prices AS TEXT) FROM soa_cycles WHERE cycle_code = :c"),
                         {'c': code}).scalar()


def _outcomes(db, cid=12):
    with db.connect() as c:
        return {r[0]: (r[1], r[2]) for r in c.execute(text(
            "SELECT run_id, outcome, outcome_reason FROM soa_expectation_outcomes WHERE cycle_id = :c ORDER BY run_id"),
            {'c': cid})}


def _refresh(backup=None, write=True, supply=None):
    return rc.refresh_reference(CYCLE, backup=backup, write=write, client=supply or Supply(),
                                scorer_factory=scorer, now=datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc))


def test_the_fixture_s_stored_outcomes_are_what_the_cached_reference_gives(fl12):
    """So the plan starts from what production holds: nothing moves on the
    cached copy."""
    assert rc.classify_only(CYCLE, scorer=scorer(), write=False)['moved'] == []


def test_the_diff_table_and_the_moves(fl12, capsys):
    supply = Supply()
    result = _refresh(write=False, supply=supply)
    # as of the cycle's stored as_of, never now
    assert supply.asked == [('/api/truesync/merchants/pampers/retailer-prices', {'as_of': AS_OF})]
    assert result['diff'] == [
        ('Swaddlers NB 84', 'amazon.com', 'price', '0.00', '27.97'),
        ('Swaddlers NB 84 (own)', 'pampers.com', 'price', '9.97', None),
        ('Swaddlers NB 84 (own)', 'pampers.com', 'method', 'regex', 'none_by_design'),
        ('Swaddlers NB 84 (own)', 'pampers.com', 'verifiable', True, False),
        ('Swaddlers NB 84', 'target.com', 'price', '10.00', None),
        ('Swaddlers NB 84', 'target.com', 'method', 'regex', 'regex_rendered'),
        ('Swaddlers NB 84', 'target.com', 'read_status', 'ok', 'empty'),
        ('Swaddlers NB 84', 'target.com', 'verifiable', True, False),
    ]
    out = capsys.readouterr().out
    assert 'reference cells that differ: 3' in out
    assert 'Swaddlers NB 84        amazon.com   price        0.00    27.97' in out
    assert 'Swaddlers NB 84 (own)  pampers.com  method       regex   none_by_design' in out
    assert {(code, was, now) for _r, code, _p, _n, was, now, _rule in result['moved']} == {
        ('PAM_CAT_1', 'wrong', 'exact'), ('PAM_CAT_2', 'wrong', 'unverifiable'),
        ('PAM_CAT_3', 'wrong', 'unverifiable')}
    assert dict(result['by_tier']['catalog_accuracy']) == {('wrong', 'exact'): 1, ('wrong', 'unverifiable'): 2}
    assert 'catalog_accuracy        4  (exact 1, unverifiable 2, wrong 1)' in out
    assert 'dry run — nothing written.' in out


def test_dry_run_writes_nothing_and_needs_no_backup(fl12, tmp_path):
    raw, outcomes = _raw(fl12, CYCLE), _outcomes(fl12)
    _refresh(write=False)
    assert (_raw(fl12, CYCLE), _outcomes(fl12)) == (raw, outcomes)
    assert list(tmp_path.iterdir()) == []


def test_apply_backs_up_replaces_with_the_envelope_and_moves_the_rows(fl12, tmp_path):
    backup = str(tmp_path / 'fl12-reference-2026-10-20.json')
    raw = _raw(fl12, CYCLE)
    result = _refresh(backup=backup)
    assert result['written'] is True
    saved = json.load(open(backup))
    assert saved['reference_prices_raw'] == raw and saved['cycle_code'] == CYCLE and saved['reference_as_of'] == AS_OF
    stored = json.loads(_raw(fl12, CYCLE))
    assert stored['prices'] == AFTER['prices'] and stored['as_of'] == AS_OF
    assert stored['refreshed_at'] == '2026-10-21T09:00:00+00:00'
    assert stored['previous_sha256'] == saved['sha256'] == rc._sha256(raw)
    assert saved['replaced_by_sha256'] == rc._sha256(_raw(fl12, CYCLE))
    after = _outcomes(fl12)
    assert after[1201][0] == 'exact'
    assert after[1202] == ('unverifiable', 'page read, but it states no price for this SKU')
    assert after[1203] == ('unverifiable', 'brand site, no price set')
    assert after[1204][0] == 'wrong'
    # the reference_as_of column is the cycle's, unchanged
    with fl12.connect() as c:
        as_of = c.execute(text("SELECT reference_as_of FROM soa_cycles WHERE id = 12")).scalar()
    assert rc._iso(as_of) == AS_OF


def test_restore_returns_the_cycle_byte_identical(fl12, tmp_path):
    backup = str(tmp_path / 'b.json')
    raw, outcomes = _raw(fl12, CYCLE), _outcomes(fl12)
    _refresh(backup=backup)
    assert _raw(fl12, CYCLE) != raw
    dry = rc.restore_reference(CYCLE, backup, write=False, scorer_factory=scorer)
    assert dry['written'] is False and len(dry['moved']) == 3 and _raw(fl12, CYCLE) != raw
    assert rc.restore_reference(CYCLE, backup, scorer_factory=scorer)['written'] is True
    assert _raw(fl12, CYCLE) == raw
    assert _outcomes(fl12) == outcomes


def test_refusals(fl12, tmp_path):
    raw = _raw(fl12, CYCLE)
    with pytest.raises(SystemExit, match='needs --backup'):
        _refresh(backup=None)
    existing = tmp_path / 'exists.json'
    existing.write_text('{}')
    with pytest.raises(SystemExit, match='exists; a backup is never overwritten'):
        _refresh(backup=str(existing))
    with pytest.raises(SystemExit, match="no cycle with code 'FL99'"):
        rc.refresh_reference('FL99', backup=None, write=False, client=Supply(), scorer_factory=scorer)
    with pytest.raises(SystemExit, match='failed'):
        _refresh(backup=str(tmp_path / 'x.json'), supply=Supply(error='upstream returned 503'))
    assert not (tmp_path / 'x.json').exists()
    with pytest.raises(SystemExit, match='no backup at'):
        rc.restore_reference(CYCLE, str(tmp_path / 'missing.json'), scorer_factory=scorer)
    # a backup of another cycle, and one whose refresh is no longer what the cycle holds
    backup = str(tmp_path / 'b.json')
    _refresh(backup=backup)
    with pytest.raises(SystemExit, match='is a backup of'):
        rc.restore_reference(NEXT, backup, scorer_factory=scorer)
    with fl12.begin() as c:
        c.execute(text("UPDATE soa_cycles SET reference_prices = :p WHERE id = 12"), {'p': raw})
    with pytest.raises(SystemExit, match='changed since'):
        rc.restore_reference(CYCLE, backup, scorer_factory=scorer)


def test_the_cli_refuses_without_classify_only_or_a_backup(fl12, capsys):
    with pytest.raises(SystemExit):
        rc.main(['--cycle', CYCLE, '--refresh-reference'])
    assert 'run with --classify-only' in capsys.readouterr().err
    with pytest.raises(SystemExit, match='needs --backup'):
        rc.main(['--cycle', CYCLE, '--refresh-reference', '--classify-only'])


def test_the_stale_basis_and_the_next_cycle_are_untouched(fl12, tmp_path):
    def basis():
        return scorer_module.ReferenceCache(fetch=False).for_cycle(12).stale_basis
    prior_raw, next_raw, next_outcomes, was = _raw(fl12, PRIOR), _raw(fl12, NEXT), _outcomes(fl12, 13), basis()
    _refresh(backup=str(tmp_path / 'b.json'))
    assert basis() == was and PRIOR in was
    assert (_raw(fl12, PRIOR), _raw(fl12, NEXT), _outcomes(fl12, 13)) == (prior_raw, next_raw, next_outcomes)
