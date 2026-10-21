"""
2L-3 (B2): the console's one-line narratives end to end on the FL13-shaped
fixture (tests/narratives_fixture.py). No test calls a model: they replay
the responses scripts/record_narratives.py recorded, keyed by the facts
digest. A missing or stale recording fails with the command that records it.

  the fixture's lines written and stored, every line printed beside its
  facts, every stored line passing the checks (test_narratives_2l3_checks.py);
  served as `narrative` on /answers, /overview and /true-value while the flag
  is on and the facts' digest is current; null otherwise
"""
import json
import os

import pytest
from sqlalchemy import text

from soa_shared import narratives as n
from tests import console_fixture_2j2 as f2j2
from tests import narratives_fixture as fx
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import _encode, as_, http, upstream  # noqa: F401  (pytest fixtures)


# ═══ end to end on the FL13-shaped fixture ════════════════════════════════

def _facts(db):
    with db.connect() as c:
        return n.load_cycle_facts(c, fx.CYCLE_ID)


def _write(db):
    return n.write_cycle(db, fx.CYCLE_ID, n.RecordedWriter(fx.FIXTURES), max_workers=1)


def _load(db):
    f2j2.load(db, _encode)


def test_the_fixture_s_subjects(db):
    _load(db)
    facts = _facts(db)
    kinds = {k: sum(1 for s in facts if s.startswith(k + ':')) for k in ('answer', 'product')}
    assert kinds == {'answer': 122, 'product': 10}
    why = {}
    for f in facts.values():
        for w in f.get('why', []):
            why[w] = why.get(w, 0) + 1
    # the catalog tier's 30 wrong prices and 6 value-tier ones, Copilot's 20 other-brand answers,
    # and 2I-8's brand-direct and first-pick rows
    assert why == {'wrong_price': 36, 'other_brand_price': 20, 'brand_fabricated': 30, 'brand_misattributed': 6,
                   'rival_first_pick': 30}
    # the model is never handed the answer's text beyond the spans the scorer kept
    assert not any('raw_response' in json.dumps(f) for f in facts.values())


def test_every_line_beside_its_facts_and_every_stored_line_passes(db, capsys):
    _load(db)
    reports = _write(db)
    assert len(reports) == 132
    with capsys.disabled():
        print(f"\n2L-3 narratives on the FL13-shaped fixture ({len(reports)} subjects, 2 calls each)")
        for r in sorted(reports, key=lambda r: r['subject']):
            shown = {k: v for k, v in r['facts'].items() if k not in ('aliases', 'meaning', 'kind')}
            print(f"\n{r['subject']}  [{r['status']}{': ' + r['reason'] if r['reason'] else ''}]")
            print('  facts:', json.dumps(shown, ensure_ascii=False, sort_keys=True))
            print('  line: ', r['line'])
        counts = {s: sum(1 for r in reports if r['status'] == s) for s in ('accepted', 'dropped', 'null')}
        reasons = {}
        for r in reports:
            if r['status'] == 'dropped':
                key = r['reason'].split(':')[0]
                reasons[key] = reasons.get(key, 0) + 1
        totals = n.usage_totals(reports)
        print(f"\n{counts}  dropped by reason {reasons}  {totals}")
    with db.connect() as c:
        stored = n.stored(c, fx.CYCLE_ID)
    assert set(stored) == {r['subject'] for r in reports}
    facts = _facts(db)
    for subject, row in stored.items():
        assert row['facts_digest'] == n.facts_digest(facts[subject])
        if row['status'] == 'accepted':
            assert n.check(row['line'], facts[subject]) is None, (subject, row['line'])
            assert len(row['line']) <= n.MAX_CHARS
        else:
            assert row['line'] is None
    assert sum(1 for r in stored.values() if r['status'] == 'accepted') >= 60
    assert all(stored[f"product:{k}"]['status'] in ('accepted', 'dropped', 'null')
               for k in (s.split(':', 1)[1] for s in facts if s.startswith('product:')))


def test_a_second_write_skips_current_lines_and_force_rewrites(db):
    _load(db)
    _write(db)
    assert n.write_cycle(db, fx.CYCLE_ID, n.RecordedWriter(fx.FIXTURES)) == []
    assert len(n.write_cycle(db, fx.CYCLE_ID, n.RecordedWriter(fx.FIXTURES), force=True)) == 132


def test_a_dry_run_stores_nothing(db):
    _load(db)
    reports = n.write_cycle(db, fx.CYCLE_ID, n.RecordedWriter(fx.FIXTURES), dry_run=True)
    assert len(reports) == 132
    with db.connect() as c:
        assert n.stored(c, fx.CYCLE_ID) == {}


def test_a_missing_recording_says_how_to_record(db, tmp_path):
    _load(db)
    with pytest.raises(n.MissingRecording, match='record_narratives.py'):
        n.write_cycle(db, fx.CYCLE_ID, n.RecordedWriter(tmp_path), dry_run=True)


def _get(http, path, **params):
    as_('op')
    r = http.get(f'/api/console/{path}', params={'org': 10, 'cycle': f2j2.CYCLE, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _accepted(db):
    with db.connect() as c:
        return {s: r['line'] for s, r in n.stored(c, fx.CYCLE_ID).items() if r['status'] == 'accepted'}


#: SOA_2L3_SAMPLE_DUMP=<dir> writes the three responses below, the console's samples
#: (parleohq/truesync apps/console/src/data/fixtures/console-read-models/*-2l3.json)
DUMP = os.environ.get('SOA_2L3_SAMPLE_DUMP')


def _dump(name, body):
    if DUMP:
        os.makedirs(DUMP, exist_ok=True)
        with open(os.path.join(DUMP, f"{name}-2l3.json"), 'w') as fh:
            json.dump(body, fh, indent=1, ensure_ascii=False)
            fh.write('\n')


def test_served_on_answers_overview_and_true_value(http, db, monkeypatch):
    _load(db)
    _write(db)
    monkeypatch.setenv(n.FLAG, '1')
    lines = _accepted(db)
    answers = _get(http, 'answers')
    _dump('answers', answers)
    assert all('narrative' in a for a in answers)
    by_id = {a['id']: a['narrative'] for a in answers}
    for subject, line in lines.items():
        if subject.startswith('answer:'):
            assert by_id[subject.split(':', 1)[1]] == line
    assert sum(1 for v in by_id.values() if v) == sum(1 for s in lines if s.startswith('answer:'))
    # an answer that is not flagged keeps its template
    right = next(a for a in answers if a.get('verdict') == 'right')
    assert right['narrative'] is None

    over = _get(http, 'overview')
    _dump('overview', over)
    products = over['by_surface']['all']['products']
    product_lines = {s.split(':', 1)[1]: line for s, line in lines.items() if s.startswith('product:')}
    assert product_lines
    facts = _facts(db)
    for p in products:
        key = next((k for k, f in ((s.split(':', 1)[1], f) for s, f in facts.items() if s.startswith('product:'))
                    if p['sku'] in f['aliases']), None)
        assert p['narrative'] == product_lines.get(key), p['name']
    for surface, block in over['by_surface'].items():
        if surface != 'all':
            assert all(p['narrative'] is None for p in block['products'])
        for s in block['signals']:
            assert s['narrative'] == (by_id.get(s['answerId']) if s.get('answerId') else None)

    tv = _get(http, 'true-value', merchant=f2j2.MERCHANT)
    _dump('true-value', tv)
    captions = {r['product']: r['narrative'] for r in tv['rows']}
    assert sum(1 for v in captions.values() if v) == len(product_lines)
    tv_plain = _get(http, 'true-value')
    assert {r['product']: r['narrative'] for r in tv_plain['rows']} == captions


def test_with_the_flag_off_every_narrative_is_null(http, db, monkeypatch):
    _load(db)
    _write(db)
    monkeypatch.delenv(n.FLAG, raising=False)
    assert all(a['narrative'] is None for a in _get(http, 'answers'))
    assert all(p['narrative'] is None for p in _get(http, 'overview')['by_surface']['all']['products'])
    assert all(r['narrative'] is None for r in _get(http, 'true-value')['rows'])


def test_without_the_table_every_narrative_is_null(http, db, monkeypatch):
    _load(db)
    with db.begin() as c:
        c.exec_driver_sql('DROP TABLE soa_narratives')
    monkeypatch.setenv(n.FLAG, '1')
    assert all(a['narrative'] is None for a in _get(http, 'answers'))
    assert all(r['narrative'] is None for r in _get(http, 'true-value')['rows'])


def test_a_rescore_that_changes_the_facts_puts_the_template_back(http, db, monkeypatch):
    _load(db)
    _write(db)
    monkeypatch.setenv(n.FLAG, '1')
    lines = _accepted(db)
    subject = next(s for s in lines if s.startswith('answer:') and 'Walmart charged' in lines[s])
    run_id = int(subject.split('-')[-1])
    before = _facts(db)
    with db.begin() as c:   # the rescore moved this answer's quote
        row = c.execute(text("SELECT claim_results FROM soa_expectation_outcomes WHERE run_id = :r"),
                        {'r': run_id}).scalar()
        claims = json.loads(row) if isinstance(row, str) else row
        claims[0]['stated'] = '19.99'
        c.execute(text("UPDATE soa_expectation_outcomes SET claim_results = :c WHERE run_id = :r"),
                  {'c': _encode(claims), 'r': run_id})
    by_id = {a['id']: a['narrative'] for a in _get(http, 'answers')}
    assert by_id[subject.split(':', 1)[1]] is None
    # every other line is untouched
    assert sum(1 for v in by_id.values() if v) == sum(1 for s in lines if s.startswith('answer:')) - 1
    # and the one product the quote was in: its facts moved, so its line is gone; every other product keeps its own
    after = _facts(db)
    moved = {s for s in before if s.startswith('product:') and n.facts_digest(before[s]) != n.facts_digest(after[s])}
    assert len(moved) == 1
    with db.connect() as c:
        current = n.served(c, fx.CYCLE_ID)
    assert subject not in current
    assert {s for s in current if s in lines and s.startswith('product:')} == \
        {s for s in lines if s.startswith('product:')} - moved
