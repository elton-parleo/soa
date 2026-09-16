"""
Cutting an answer into labellable spans, on the rows that made it
necessary.

Four hand-checks in, the last thing the model still chose was where a
sentence stopped. Seed 4 shows the four ways it got that wrong, and each
one is a test here, quoting the answer it came from.

The contract is verbatim: every span is a substring of the answer, so a
reader checking a label can find the words in the stored answer.
"""
import json
import pathlib

import pytest

from parser.span_segmenter import segment, covers
from soa_shared import expected_answers as ea

BRAND = 'Wiggle & Snug'


def texts(answer):
    return [s['text'] for s in segment(answer)]


def brand_spans(answer):
    return [s['text'] for s in segment(answer) if ea.names_brand(s['text'], BRAND)]


# ── the four failures, verbatim from seed 4 ───────────────────────────────

def test_row_25_a_hedge_in_one_sentence_does_not_reach_the_next():
    """The transcriber returned both of these as one span, marked hedged.
    The second sentence is not hedged; it is the false claim the tier
    exists to catch."""
    answer = ("It seems there might be a slight misunderstanding. "
              "**Wiggle & Snug is a private label brand sold exclusively at Kohl's.**")
    assert texts(answer) == [
        "It seems there might be a slight misunderstanding.",
        "**Wiggle & Snug is a private label brand sold exclusively at Kohl's.**",
    ]


def test_row_19_a_cannot_find_stops_at_the_but():
    """It ran past the clause break and took a product claim with it."""
    answer = ("I couldn’t verify a product specifically branded "
              "**“Wiggle & Snug Cloud Wipes”**, but the 3-pack "
              "“Cloud Moist” wipes are listed as **hypoallergenic**.")
    spans = texts(answer)
    assert len(spans) == 2
    assert spans[0].endswith('**“Wiggle & Snug Cloud Wipes”**,')
    assert spans[1].startswith('but the 3-pack')


def test_row_27_a_leading_subordinate_clause_is_its_own_span():
    """Same failure, the other way round — the cannot-find is the clause
    at the FRONT, and the comma closing it sits inside a quotation."""
    answer = ("While I don't find a product specifically named \"Wiggle & "
              "**Snug** Bum Balm,\" the **Wiggle & Giggle Organic Baby Bum "
              "Balm 4 oz** is a very popular and similarly named product.")
    spans = texts(answer)
    assert len(spans) == 2
    assert spans[0].startswith("While I don't find")
    assert spans[1].startswith('the **Wiggle & Giggle')


def test_row_9_a_sentence_ending_in_a_unit_still_ends():
    """"4 oz." was on the abbreviation list, so this sentence never
    ended — and the half of it that says no product page for this brand
    could be found reached nothing and was recorded nowhere."""
    answer = ("I **did not find a reliable current product page specifically "
              "for “Wiggle & Snug Bum Balm 4 oz.”** The closest "
              "matching listings I found are for Amallow.")
    spans = texts(answer)
    assert len(spans) == 2
    assert spans[0].startswith('I **did not find')
    assert spans[1].startswith('The closest')


def test_row_39_the_headline_is_its_own_span():
    answer = ("It appears that Wiggle & Snug Bum Balm 4 oz has been "
              "**discontinued**.\n\nMost retail listings show it as "
              "\"currently unavailable\".")
    assert texts(answer)[0] == (
        "It appears that Wiggle & Snug Bum Balm 4 oz has been **discontinued**."
    )


# ── what must not split ───────────────────────────────────────────────────

@pytest.mark.parametrize("answer", [
    "It costs $15.79 for the giant pack.",
    "Sizes run from 8 lb. to 14 lb. across the range.",
    "Look for a 4 oz. jar on the shelf.",
    "Brands e.g. Pampers and Huggies are widely stocked.",
    "The U.S. version differs from the E.U. one.",
])
def test_a_period_inside_a_sentence_does_not_end_it(answer):
    assert texts(answer) == [answer]


def test_a_mid_sentence_while_does_not_split_on_its_own_comma():
    answer = ("The diaper stays put while the baby crawls, rolls or sleeps, "
              "which is the whole point.")
    assert texts(answer) == [answer]


# ── the contract ──────────────────────────────────────────────────────────

SEED4 = pathlib.Path(__file__).resolve().parent / 'fixtures' / 'extraction_golden'


def _seed4_answers():
    return [json.loads(p.read_text())['answer']
            for p in sorted(SEED4.glob('seed4_*.json'))]


def test_every_span_of_every_reviewed_answer_is_verbatim():
    answers = _seed4_answers()
    assert answers, 'seed 4 is not in the golden set'
    for answer in answers:
        assert covers(answer, segment(answer))


def test_spans_are_numbered_from_one_and_in_order():
    answer = "One. Two. Three."
    assert [s['id'] for s in segment(answer)] == [1, 2, 3]


def test_an_empty_answer_has_no_spans():
    for answer in ('', '   ', None):
        assert segment(answer) == []


def test_bullet_lists_are_one_span_per_item():
    answer = "Popular alternatives:\n*   Desitin\n*   Aquaphor\n*   Weleda"
    assert len(segment(answer)) == 4


def test_a_span_that_names_the_brand_is_findable():
    """The coverage check runs on this, so it has to hold on real
    answers and not only on constructed ones."""
    for answer in _seed4_answers():
        for span in brand_spans(answer):
            assert span in answer
