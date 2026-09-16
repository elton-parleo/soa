"""
The golden set, and the gate on it.

tests/fixtures/extraction_golden/ is every row of a hand-reviewed
validate_extractions sample, frozen with the field values the review
settled on. This file is what makes it a gate rather than a folder.

What the gate measures and what it does not, stated here because a green
gate is easy to over-read:

  * it runs the DETERMINISTIC pipeline — post-processing and the
    classifier — over the stored transcription, with the golden labels
    replayed. No model call, so it runs in CI and a field that regresses
    regressed because somebody changed the code.
  * it does NOT measure the extractor or the labeller. Those are measured
    by drawing a fresh sample and reading it, which is what produced this
    fixture. A green gate is not evidence that either model got better.
  * for the mechanical fields, the golden values were DERIVED by applying
    the review's numbered rulings. The current pipeline agreeing with
    them shows the rules were implemented as written — not that they are
    right. The rows the review explicitly ruled on are the part that is
    not circular, and the eval can be run over those alone.
"""
import json
import pathlib

import pytest

from scripts import eval_extraction_golden as ev

GOLDEN = sorted(ev.GOLDEN_DIR.glob('*.json'))


def test_the_golden_set_exists_and_is_a_whole_sample():
    assert len(GOLDEN) == 40


@pytest.mark.parametrize('path', GOLDEN, ids=lambda p: p.stem)
def test_every_golden_row_carries_the_answer_it_was_judged_from(path):
    """A frozen label with no answer beside it cannot be re-checked by
    the next person, which is the only reason to freeze it."""
    row = json.loads(path.read_text())
    assert row['answer']
    assert row['as_extracted']
    assert row['reviewed'] is True
    for field in ev.FIELDS:
        assert field in row['golden'], field


def test_the_rows_the_review_ruled_on_carry_its_note():
    rows = [json.loads(p.read_text()) for p in GOLDEN]
    flagged = [r for r in rows if r['flagged_by_review']]
    assert len(flagged) == 17
    assert all(r['review_note'] for r in flagged)


def test_the_gate_passes(capsys):
    """The gate itself. It fails if any field drops below its recorded
    level or overall agreement drops below 0.90."""
    assert ev.main(['--gate']) == 0
    assert 'every field at or above its floor' in capsys.readouterr().out


def test_the_gate_fails_when_a_field_regresses(monkeypatch, capsys):
    """A gate nobody has seen fail is a gate nobody should trust."""
    monkeypatch.setitem(ev.BASELINE, 'sizes', 1.5)
    assert ev.main(['--gate']) == 1
    assert 'REGRESSION' in capsys.readouterr().out


def test_the_stored_rows_do_not_clear_the_gate(capsys):
    """The before/after in one assertion. If the transcriptions as they
    were stored passed this, none of the corrections did anything."""
    assert ev.main(['--before']) == 0          # a measurement, never a gate
    out = capsys.readouterr().out
    assert 'FAILED' in out


def test_the_before_number_is_worse_on_the_fields_the_review_flagged():
    rows = [json.loads(p.read_text()) for p in GOLDEN]

    def score(produce, subset):
        good = total = 0
        for row in subset:
            for ok in ev.compare(row, produce(row)).values():
                total += 1
                good += 1 if ok else 0
        return good / total

    flagged = [r for r in rows if r['flagged_by_review']]
    assert score(ev.as_extracted, flagged) < score(ev.run_pipeline, flagged)
    assert score(ev.run_pipeline, rows) == 1.0


def test_sizes_are_where_the_before_number_is_worst():
    """Ten of forty rows recorded a baby's weight, a percentage, a
    duration or a size-chart range as a product size."""
    rows = [json.loads(p.read_text()) for p in GOLDEN]
    moved = [r for r in rows
             if len(r['golden']['sizes']) != len(r['as_extracted'].get('sizes') or [])]
    assert len(moved) == 10


def test_the_one_row_where_brand_mentioned_was_wrong():
    """Row 11: a price question, so the expectation carries no brand, so
    ea.names_brand was asked to find nothing and said yes."""
    rows = {json.loads(p.read_text())['row']: json.loads(p.read_text()) for p in GOLDEN}
    row = rows[11]
    assert row['as_extracted']['brand_mentioned'] is True
    assert row['golden']['brand_mentioned'] is False
    assert 'Wiggle & Snug' not in row['answer']
