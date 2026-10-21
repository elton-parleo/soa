"""
2K-1 §3 (A9): recommendations are not fabricated facts, without touching
Layer 2.

The frozen classifier calls "For a newborn, you should buy Pampers Swaddlers.
They are widely considered the gold standard" `fabricated` (an asserted claim,
no source). The outcome is not changed here. soa_shared/claim_kinds.py derives
`claim_kind` beside it from the stored extraction: `attribute` when any
structured value or labelled span names a price, size, weight, count, pack,
retailer, program, availability, ingredient, material or owner, else
`recommendation_only` (None when nothing is labelled).

The rule on 16 FL12-shaped fabricated answers
(packages/testing/fixtures/brand_direct_fl12_2k1.json, written, not recorded;
extractions made by the pipeline's own segmenter): it reclassifies 7 of the 16
to recommendation_only. A reader labels 5 of those 7 recommendations; the
other 2 state a checkable fact outside the brief's list (hospital use, a
wetness indicator), so recommendation_only's precision there is 5 of 7, and it
finds all 5 of the reader's recommendations. 14 of 16 agree.
"""
import filecmp
import json
import os

import pytest
import soa_pg_harness
from sqlalchemy import text

from soa_shared import claim_kinds as ck
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2i8 import _fl12
from tests.test_console_read_models import _encode, as_, http, upstream  # noqa: F401  (pytest fixtures)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
with open(os.path.join(os.path.dirname(soa_pg_harness.__file__), 'fixtures', 'brand_direct_fl12_2k1.json')) as _fh:
    FIXTURE = json.load(_fh)
ROWS = FIXTURE['rows']
#: the rows the rule reads as recommendation_only, by hand
RECOMMENDATION_ONLY = {'fl12-bd-01', 'fl12-bd-02', 'fl12-bd-03', 'fl12-bd-11', 'fl12-bd-12', 'fl12-bd-14', 'fl12-bd-16'}
#: where the rule and a reader disagree: a checkable claim the brief's list does not name
MISSES = {'fl12-bd-02', 'fl12-bd-11'}
#: 2K-3: what the console reads, with the endorsement words and no catalog features (soa's test fake
#: serves W&S no catalog): "most popular ... in US hospitals" (bd-02) is an attribute; bd-11's
#: wetness indicator needs the merchant's catalog (test_console_2k3.py)
CONSOLE_RECOMMENDATION_ONLY = RECOMMENDATION_ONLY - {'fl12-bd-02'}


def test_the_two_copies_are_identical():
    assert filecmp.cmp(os.path.join(ROOT, 'apps', 'api', 'soa_shared', 'claim_kinds.py'),
                       os.path.join(ROOT, 'apps', 'pipeline', 'soa_shared', 'claim_kinds.py'), shallow=False)


def test_every_fixture_row_is_fabricated_and_the_rule_reclassifies_7_of_16():
    assert len(ROWS) == 16 and {r['outcome'] for r in ROWS} == {'fabricated'}
    got = {r['id'] for r in ROWS if ck.claim_kind(r['extraction']) == ck.RECOMMENDATION_ONLY}
    assert got == RECOMMENDATION_ONLY
    assert ck.counts(r['extraction'] for r in ROWS) == {'attribute': 9, 'recommendation_only': 7, 'undecided': 0}


def test_precision_against_a_reader_s_labels():
    reader = {r['id'] for r in ROWS if r['reader_label'] == ck.RECOMMENDATION_ONLY}
    assert RECOMMENDATION_ONLY & reader == reader                      # every reader recommendation is found (5 of 5)
    assert RECOMMENDATION_ONLY - reader == MISSES                      # 2 of the 7 are facts the list misses
    assert len(RECOMMENDATION_ONLY & reader) == 5
    agree = sum(1 for r in ROWS if ck.claim_kind(r['extraction']) == r['reader_label'])
    assert agree == 14


def test_the_brief_s_example_is_recommendation_only():
    row = next(r for r in ROWS if r['id'] == 'fl12-bd-01')
    assert row['answer'].startswith('For a newborn, you should buy Pampers Swaddlers.')
    assert ck.claim_kind(row['extraction']) == ck.RECOMMENDATION_ONLY
    # "buy" is the transcription's `retail` word, which is why its claim_kind is not read
    assert any(c.get('claim_kind') == 'retail' for c in row['extraction']['brand_claims'])


@pytest.mark.parametrize('extraction, kind', [
    ({}, None),                                                    # nothing labelled: never guessed
    ({'span_labels': [{'text': 'Pampers is great.'}], 'prices': [{'amount': '9'}]}, 'attribute'),
    ({'span_labels': [{'text': 'Pampers is great.'}], 'retailer_mentions': [{'name': 'Target'}]}, 'attribute'),
    ({'brand_claims': [{'claim': 'Pampers comes in a jumbo pack.'}]}, 'attribute'),     # older record: its claims
    ({'span_labels': [{'text': 'I would pick Pampers, it is lovely.'}]}, 'recommendation_only'),
    ({'span_labels': [{'text': 'Buy it on amazon.com.'}]}, 'attribute'),               # a written domain
])
def test_the_rule_edges(extraction, kind):
    assert ck.claim_kind(extraction) == kind


# ═══ the console: the signal split and the Answers chip ══════════════════

def _with_fixture_extractions(db) -> dict:
    """FL12's six-agent shape (2I-8) with each fabricated brand-direct answer
    given a fixture row's extraction, in turn. {run_id: fixture row id}."""
    _fl12(db)
    assigned = {}
    with db.begin() as c:
        runs = [r[0] for r in c.execute(text(
            "SELECT run_id FROM soa_expectation_outcomes WHERE cycle_id = 229 AND tier = 'brand_direct' "
            "AND outcome = 'fabricated' ORDER BY run_id"))]
        for i, run in enumerate(runs):
            row = ROWS[i % len(ROWS)]
            assigned[run] = row['id']
            c.execute(text("UPDATE soa_expectation_outcomes SET extraction = :x WHERE run_id = :r"),
                      {'x': _encode(row['extraction']), 'r': run})
    return assigned


def test_the_signal_counts_attribute_answers_and_says_the_rest_on_a_second_line(http, db, upstream):
    assigned = _with_fixture_extractions(db)
    recommended = sum(1 for rid in assigned.values() if rid in CONSOLE_RECOMMENDATION_ONLY)
    stated = len(assigned) - recommended
    assert stated >= 5 and recommended > 0
    as_('op')
    over = http.get('/api/console/overview', params={'cycle': 'FL3-wiggle-and-snug-20261014', 'org': 10,
                                                     'merchant': 'wiggle-and-snug'}).json()
    every = over['by_surface']['all']
    assert (every['totals']['fabricated'], every['totals']['recommended']) == (stated, recommended)
    signal = next(s for s in every['signals'] if s['id'] == 'fabricated')
    assert signal['count'] == stated
    assert signal['title'] == f"{stated} brand answers stated facts Wiggle & Snug never published."
    assert signal['recommended'] == {'count': recommended,
                                     'line': f"{recommended} recommended Wiggle & Snug without stating a fact."}


def test_the_answers_list_carries_the_kind_as_a_chip(http, db, upstream):
    assigned = _with_fixture_extractions(db)
    as_('op')
    answers = {a['id']: a for a in http.get('/api/console/answers', params={'cycle': 'FL3-wiggle-and-snug-20261014',
                                                                             'org': 10}).json()}
    for run, row_id in assigned.items():
        a = answers[f'run-{run}']
        assert a['brand_verdict'] == 'fabricated'           # the outcome is not changed
        if row_id in CONSOLE_RECOMMENDATION_ONLY:
            assert (a['claim_kind'], a['claim_kind_label']) == ('recommendation_only', 'Recommendation only')
        else:
            assert (a['claim_kind'], a['claim_kind_label']) == ('attribute', 'Stated a fact')
    # a value-tier answer carries no kind
    assert not any('claim_kind' in a for a in answers.values() if a.get('tier') != 'brand_direct')
