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


def test_the_golden_set_is_five_whole_samples():
    assert len(GOLDEN) == 200
    rows = [json.loads(p.read_text()) for p in GOLDEN]
    assert sorted({r['seed'] for r in rows}) == [1, 2, 3, 4, 5]
    for seed in (1, 2, 3, 4, 5):
        assert len([r for r in rows if r['seed'] == seed]) == 40


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
    assert len(flagged) == 59
    assert all(r['review_note'] is not None for r in flagged)


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


def _score(produce, subset):
    good = total = 0
    for row in subset:
        for ok in ev.compare(row, produce(row)).values():
            total += 1
            good += 1 if ok else 0
    return good / total


def test_the_pipeline_beats_the_stored_transcription_on_every_earlier_sample():
    rows = [json.loads(p.read_text()) for p in GOLDEN]
    for seed in (1, 2, 3):
        subset = [r for r in rows if r['seed'] == seed]
        assert _score(ev.as_extracted, subset) < _score(ev.run_pipeline, subset), seed


def test_a_second_pass_changes_nothing_on_any_row():
    """The property a growing golden set can check that a fresh sample
    cannot: a re-score must not move an answer the first score settled.
    It has already caught one real bug — rebuilding retailer_mentions
    from recommended_retailers dropped every retailer an earlier pass had
    marked source or unavailable."""
    rows = [json.loads(p.read_text()) for p in GOLDEN]
    unstable = [r['row'] for r in rows if not ev.idempotent(r)]
    assert unstable == []


def test_the_latest_sample_is_not_made_worse_by_running_it_again():
    """Seed 4 came out of the current pipeline, so re-running it should
    change nothing. It did: rebuilding retailer_mentions from
    recommended_retailers dropped every retailer that was a source or
    showed the product unavailable, which is data the earlier pass had
    established on evidence this one cannot see."""
    rows = [json.loads(p.read_text()) for p in GOLDEN if json.loads(p.read_text())['seed'] == 4]
    assert _score(ev.as_extracted, rows) == 1.0
    assert _score(ev.run_pipeline, rows) == 1.0


def test_the_later_samples_are_clean_and_the_first_is_not():
    """Seed 1 came from the first extractor, which had no `sizes` field
    and no `recommended_retailers`. "4 oz" is in pack_counts and three
    recommended shops are in sources_cited, and nothing downstream can
    know that a bare 4 attributed to a balm means ounces. Those were
    fixed in the extractor, not here — which is exactly what the two
    later samples scoring 1.000 says."""
    rows = [json.loads(p.read_text()) for p in GOLDEN]
    for seed in (2, 3, 4, 5):
        assert _score(ev.run_pipeline, [r for r in rows if r['seed'] == seed]) == 1.0
    assert _score(ev.run_pipeline, [r for r in rows if r['seed'] == 1]) < 1.0


def test_sizes_are_where_the_before_number_is_worst():
    """A baby's weight, a percentage, a duration, a per-diaper price, a
    size-chart range and the digit out of "Size 6" were all landing in
    the sizes field."""
    before = ev.main(['--before'])
    assert before == 0
    rows = [json.loads(p.read_text()) for p in GOLDEN]
    moved = [r for r in rows
             if len(r['golden']['sizes']) != len(r['as_extracted'].get('sizes') or [])]
    assert len(moved) >= 20


def test_every_remaining_miss_is_in_the_first_sample():
    """Which is what says the residue is the extractor's and not the
    code's: seed 1 predates the fields those values belong in."""
    rows = [json.loads(p.read_text()) for p in GOLDEN]
    for row in rows:
        if row['seed'] == 1:
            continue
        assert all(ev.compare(row, ev.run_pipeline(row)).values()), (row['seed'], row['row'])


def test_every_row_where_brand_mentioned_was_wrong_is_now_right():
    """Four across three samples, in both directions — an answer reading
    "on eligible Wiggle & Snug products" recorded as no mention, and
    answers naming only "Wonder/The Wiggles" recorded as one."""
    rows = [json.loads(p.read_text()) for p in GOLDEN]
    wrong = [r for r in rows
             if r['as_extracted'].get('brand_mentioned') != r['golden']['brand_mentioned']]
    assert len(wrong) == 4
    for row in wrong:
        produced = ev.run_pipeline(row)
        assert produced['brand_mentioned'] == row['golden']['brand_mentioned'], row['row']


def test_a_retailer_that_was_a_source_keeps_its_name_and_gains_a_role():
    """It used to be deleted. A name that vanishes is a name the
    labelling pass never sees and nobody can check afterwards."""
    rows = {(r['seed'], r['row']): r for r in
            (json.loads(p.read_text()) for p in GOLDEN)}
    produced = ev.run_pipeline(rows[(2, 11)])
    assert [m['name'] for m in produced['retailer_mentions']] == ['Walmart', 'Target']
    assert all(m['role'] == 'source' for m in produced['retailer_mentions'])
    assert produced['recommended_retailers'] == []


def test_a_shop_listed_as_a_brand_is_labelled_out_of_the_list():
    """One answer listed Amazon, Walmart, Target, Walmart.com and
    Target.com as other brands — shops, two of them twice. None of the
    four relations the review named can say "this is not a brand", which
    is why there is a fifth."""
    rows = {(r['seed'], r['row']): r for r in
            (json.loads(p.read_text()) for p in GOLDEN)}
    produced = ev.run_pipeline(rows[(2, 29)])
    assert produced['other_brands_named'] == []
    assert any('not a brand' in note for note in produced['postprocess'])
