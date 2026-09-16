"""
The labelling pass: closed enums, and what happens when it fails.

The pass exists because two earlier arrangements failed the same way.
Asking the transcriber to judge modality inside its own call produced
different answers for the same shape of sentence within one run. Judging
it with a lexicon in Python fired on six rows of one sample and was right
on one. So the judgement is a second model call that does nothing else,
and it can only return words from a list.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from parser import label_prompts as lp
from parser import extraction_postprocess as pp
from parser.labeling_client import LabelingClient, EMPTY_LABELS


# ── the schema is closed ──────────────────────────────────────────────────

def test_every_label_is_one_of_a_fixed_list():
    """`presented_as` was free text for one round and came back holding
    "the", "like" and "unrelated products or"."""
    schema = lp.build_labeling_schema()
    span = schema['properties']['spans']['items']['properties']
    assert span['kind']['enum'] == [
        'unknown_statement', 'assertion', 'disclaimer', 'instruction', 'none',
    ]
    assert span['modality']['enum'] == ['asserted', 'hedged', 'conditional']
    # The id, never the text: a labeller that hands back its own
    # quotation is one that can paraphrase.
    assert span['span_id']['type'] == 'integer'
    assert 'sentence' not in span
    assert 'text' not in span
    # Five, not the four originally specified. The fifth exists because
    # two reviewed rows could not be expressed without it: a shop listed
    # as a brand, and the brand's own parent presented as its owner.
    assert schema['properties']['other_brands']['items']['properties'][
        'relation']['enum'] == [
        'closest_match_described', 'spelling_guess', 'citation_only',
        'comparison', 'not_a_brand',
    ]
    assert schema['properties']['retailers']['items']['properties'][
        'role']['enum'] == ['recommendation', 'source', 'unavailable']


def test_nothing_may_be_added_to_the_shape():
    schema = lp.build_labeling_schema()
    assert schema['additionalProperties'] is False
    for field in ('spans', 'other_brands', 'retailers'):
        assert schema['properties'][field]['items']['additionalProperties'] is False


def test_the_labeller_is_never_told_what_a_right_answer_looks_like():
    """It sees the answer and the spans. An expectation, a published
    price or a verdict in this prompt would have it labelling towards
    one."""
    prompt = lp.build_labeling_prompt()
    for leak in ('expected', 'published', 'trueshopstore', 'outcome',
                 'fabricated', 'exact', '22.99'):
        assert leak not in prompt.lower(), leak


# ── the examples are the reviews' own rows ────────────────────────────────

@pytest.mark.parametrize('sentence', [
    "I'm having trouble finding any information about a brand called Wiggle & Snug.",
    "Wiggle & Snug does not appear to be a real diaper brand.",
    "It doesn't sound like a widely recognized national brand.",
    "Wiggle & Snug does not currently offer a member rewards program.",
    "Wiggle & Snug is a Wiggle own-brand.",
    "I don't have real-time access to the absolute latest ingredient list.",
    "Without having the specific product in front of me, I cannot give a definitive yes or no.",
    "If it's a store brand, availability would be limited.",
    "Amazon listings show it currently unavailable.",
])
def test_the_prompt_carries_the_sentence_that_motivated_its_rule(sentence):
    assert sentence in lp.build_labeling_prompt()


def test_wording_strength_does_not_change_the_kind():
    """Two samples labelled "does not appear to be a real brand" and "is
    not a real or widely recognized brand" differently. They are the same
    sentence twice."""
    prompt = lp.build_labeling_prompt()
    assert 'Strength of wording does NOT change the kind' in prompt


def test_unavailable_is_never_a_recommendation():
    assert 'never "recommendation"' in lp.build_labeling_prompt()


# ── what gets sent ────────────────────────────────────────────────────────

def test_the_spans_come_from_the_answer_not_from_the_transcription():
    """The whole round. The transcriber used to choose where a sentence
    stopped, and it merged two, ran one past a clause break, and dropped
    others entirely."""
    answer = ("It seems there might be a slight misunderstanding. "
              "Wiggle & Snug is sold exclusively at Kohl's.")
    spans = lp.spans_to_label({'brand_claims': []}, answer)
    assert [s['text'] for s in spans['spans']] == [
        'It seems there might be a slight misunderstanding.',
        "Wiggle & Snug is sold exclusively at Kohl's.",
    ]
    assert [s['id'] for s in spans['spans']] == [1, 2]


def test_every_span_is_verbatim_in_the_answer():
    """A label attached to words nobody said cannot be checked against
    the stored answer."""
    from parser.span_segmenter import covers
    answer = ("I couldn't verify a product branded \"Wiggle & Snug Cloud Wipes\", "
              "but the 3-pack wipes are listed as hypoallergenic. "
              "Target's details also say they contain 99% purified water.")
    spans = lp.spans_to_label({}, answer)
    assert covers(answer, spans['spans'])


def test_nothing_to_label_makes_no_call():
    client = LabelingClient.__new__(LabelingClient)
    client.model = 'gpt-5.4-mini'
    client._client = MagicMock()
    client._client.responses.create = AsyncMock()

    result = asyncio.run(client.label({}, answer_text=''))
    client._client.responses.create.assert_not_awaited()
    assert result.labels == EMPTY_LABELS


def test_a_failed_call_returns_empty_labels_and_says_so():
    client = LabelingClient.__new__(LabelingClient)
    client.model = 'gpt-5.4-mini'
    client._client = MagicMock()
    client._client.responses.create = AsyncMock(side_effect=RuntimeError('boom'))

    result = asyncio.run(client.label(
        {'brand_claims': [{'claim': 'x', 'sentence': 'It is sold at Aldi.'}]},
        answer_text='hello',
    ))
    assert result.labels == EMPTY_LABELS
    assert 'boom' in result.error


def test_an_empty_label_set_leaves_a_claim_unasserted():
    """The whole reason a failed call is safe: an unlabelled span is not
    a claim, so a labelling outage cannot manufacture a fabrication."""
    record = pp.apply_labels(
        {}, EMPTY_LABELS,
        answer_text='Wiggle & Snug is sold at Aldi.', brand='Wiggle & Snug',
    )
    assert pp.asserted_claims(record) == []
    # And it says so, rather than reading as an answer with no claims.
    assert record['needs_review']


# ── the merge ─────────────────────────────────────────────────────────────

def test_a_label_for_a_span_that_was_never_sent_is_recorded_not_applied():
    """The id is the only handle. One that does not resolve is a label
    attached to nothing."""
    record = pp.apply_labels(
        {}, {'spans': [{'span_id': 99, 'kind': 'assertion', 'modality': 'asserted'}]},
        answer_text='Wiggle & Snug is sold at Aldi.', brand='Wiggle & Snug',
    )
    assert record['brand_claims'] == []
    assert any('unknown span ids' in n for n in record['postprocess'])


def test_a_name_labelled_not_a_brand_leaves_the_list():
    record = pp.apply_labels(
        {'other_brands_named': [{'name': 'Walmart.com'}, {'name': 'Huggies'}]},
        {'other_brands': [
            {'name': 'Walmart.com', 'relation': 'not_a_brand'},
            {'name': 'Huggies', 'relation': 'comparison'},
        ]},
    )
    assert [e['name'] for e in record['other_brands_named']] == ['Huggies']
    assert any('not a brand: Walmart.com' in n for n in record['postprocess'])


def test_a_retailer_labelled_unavailable_is_not_a_recommendation():
    """Row 7: "Amazon listings show it currently unavailable" drove a
    fabricated verdict reading "told the reader to buy it at Amazon"."""
    record = pp.apply_labels(
        {'recommended_retailers': ['Amazon']},
        {'retailers': [{'name': 'Amazon', 'role': 'unavailable'}]},
    )
    assert record['recommended_retailers'] == []
    assert record['retailer_mentions'] == [{'name': 'Amazon', 'role': 'unavailable'}]


def test_a_retailer_labelled_source_is_not_a_recommendation():
    record = pp.apply_labels(
        {'recommended_retailers': ['HEB']},
        {'retailers': [{'name': 'HEB', 'role': 'source'}]},
    )
    assert record['recommended_retailers'] == []


def test_a_retailer_labelled_recommendation_survives():
    record = pp.apply_labels(
        {'recommended_retailers': ['Amazon']},
        {'retailers': [{'name': 'Amazon', 'role': 'recommendation'}]},
    )
    assert record['recommended_retailers'] == ['Amazon']
