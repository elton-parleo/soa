"""
Layer 2's extraction pass, with the model mocked.

Two things are being held to: the prompt asks for a transcription and
nothing else, and a failed call becomes `unscoreable` rather than an
assistant error. The second matters most — a model outage recorded as
`wrong` would inflate the error rate with our own downtime, and it would
do it silently.
"""
import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from parser import expectation_prompts as prompts
from soa_shared import expected_answers as ea

FIXTURE_EXTRACTION = {
    "prices": [
        {"amount": "22.99", "currency": "USD",
         "attributed_product": "Snug-Fit Diapers Size 3 Small Pack"},
    ],
    "codes": [{"code": "SNUG3", "value_kind": "amount_off", "value": "3.00"}],
    "pack_counts": [{"value": 84, "attributed_product": "Size 3 Small Pack"}],
    "gtins": [],
    "member_prices": [
        {"amount": "16.84", "tier": "Member+", "attributed_product": "Size 3 Small Pack"},
    ],
    "points": [{"value": "1", "per_dollar": True, "program": "Member Rewards"}],
    "brand_mentioned": True,
    "sources_cited": ["trueshopstore.com"],
    "extraction_confident": True,
    "extraction_note": None,
}


class _Usage:
    input_tokens = 900
    output_tokens = 120


class _Response:
    def __init__(self, payload):
        self.output_text = json.dumps(payload)
        self.usage = _Usage()


@pytest.fixture
def client(monkeypatch):
    import soa_shared.config as config
    from parser.expectation_client import ExpectationClient

    monkeypatch.setattr(config, "OPEN_AI_API_KEY", "test-key", raising=False)
    with patch("parser.expectation_client.AsyncOpenAI"):
        yield ExpectationClient()


def _stub(client, payload=None, exc=None):
    create = AsyncMock()
    if exc is not None:
        create.side_effect = exc
    else:
        create.return_value = _Response(payload)
    client._client.responses.create = create
    return create


# ── the schema ────────────────────────────────────────────────────────────

def test_the_schema_is_strict_and_every_field_required():
    """A model that omits a field should fail the call rather than hand
    back a partial record that reads as an absent quantity."""
    schema = prompts.build_extraction_schema()
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == sorted(schema["properties"])


def test_the_schema_contains_no_verdict_field():
    """The extraction transcribes; it never judges. A `correct` or
    `matches_expectation` field here would make the scorer a second
    opinion rather than a comparison."""
    rendered = json.dumps(prompts.build_extraction_schema())
    for forbidden in ("correct", "matches", "expected", "verdict", "accurate"):
        assert forbidden not in rendered, forbidden


def test_confidence_is_about_the_transcription_not_the_answer():
    schema = prompts.build_extraction_schema()
    assert schema["properties"]["extraction_confident"]["type"] == "boolean"
    assert "answer_confident" not in schema["properties"]


def test_the_prompt_never_carries_the_expected_value():
    """An extractor that knows the target price will find it. Only the
    brand NAME is passed, because brand_mentioned is unanswerable
    without it; the domain, the price and the code are not."""
    rendered = prompts.build_extraction_prompt("Wiggle & Snug")
    assert "Wiggle & Snug" in rendered
    # Not only the expectation itself: the prompt's own illustrative
    # values must not be any real study's values either. A prompt that
    # said 'e.g. "22.99"' while transcribing a Wiggle & Snug answer is
    # putting the right answer in front of the extractor as an example.
    for leaked in (
        "22.99", "SNUG3", "trueshopstore.com", "884400137609",
        "Snug-Fit", "Member+", "84",
    ):
        assert leaked not in rendered, leaked


def test_the_prompt_separates_did_not_say_from_could_not_read():
    rendered = prompts.build_extraction_prompt()
    assert "does not address any of the quantities above" in rendered
    assert "confident reading" in rendered


# ── the call ──────────────────────────────────────────────────────────────

def test_a_successful_call_returns_the_fixture_record(client):
    _stub(client, FIXTURE_EXTRACTION)
    result = asyncio.run(client.extract("...", brand="Wiggle & Snug"))

    # Everything the model returned, plus the one field the model is not
    # asked for: brand_mentioned is computed from the answer text.
    assert {k: v for k, v in result.record.items() if k != "brand_mentioned"} == {
        k: v for k, v in FIXTURE_EXTRACTION.items() if k != "brand_mentioned"
    }
    assert result.record["brand_mentioned"] is False  # the stub answer is "..."
    assert result.error is None
    assert result.latency_ms is not None
    assert result.usage["input_tokens"] == 900


def test_the_call_uses_a_strict_json_schema(client):
    create = _stub(client, FIXTURE_EXTRACTION)
    asyncio.run(client.extract("...", brand="Wiggle & Snug"))

    kwargs = create.call_args.kwargs
    fmt = kwargs["text"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["strict"] is True
    assert fmt["schema"] == prompts.build_extraction_schema()


def test_the_answer_text_is_what_is_sent(client):
    create = _stub(client, FIXTURE_EXTRACTION)
    asyncio.run(client.extract("The Size 3 pack is $22.99.", brand="Wiggle & Snug"))
    assert "The Size 3 pack is $22.99." in create.call_args.kwargs["input"][0]["content"]


def test_the_brand_reaches_the_instructions_and_nothing_else_does(client):
    create = _stub(client, FIXTURE_EXTRACTION)
    asyncio.run(client.extract("...", brand="Wiggle & Snug"))
    assert "Wiggle & Snug" in create.call_args.kwargs["instructions"]


# ── failure ───────────────────────────────────────────────────────────────

def test_a_failed_call_is_unscoreable_not_an_assistant_error(client):
    """A model outage recorded as `wrong` would inflate the error rate
    with our own downtime."""
    _stub(client, exc=RuntimeError("502 from OpenAI"))
    result = asyncio.run(client.extract("...", brand="Wiggle & Snug"))

    assert result.record["extraction_confident"] is False
    assert "502 from OpenAI" in result.record["extraction_note"]
    assert result.error is not None


def test_a_failed_call_is_retried_once(client):
    create = _stub(client, exc=RuntimeError("timeout"))
    asyncio.run(client.extract("...", brand="Wiggle & Snug"))
    assert create.await_count == 2


def test_an_empty_answer_never_reaches_the_model(client):
    create = _stub(client, FIXTURE_EXTRACTION)
    result = asyncio.run(client.extract("   ", brand="Wiggle & Snug"))

    create.assert_not_awaited()
    assert result.record["extraction_confident"] is False


def test_the_empty_extraction_has_every_schema_field():
    """It is stored as a real extraction record, so a reader of the row
    cannot tell it apart by shape — only by extraction_confident.

    Plus brand_mentioned, which is stamped on afterwards and so is in
    every stored record without ever being in the schema."""
    assert sorted(prompts.EMPTY_EXTRACTION) == sorted(
        list(prompts.build_extraction_schema()["properties"]) + ["brand_mentioned"]
    )


def test_the_model_is_never_asked_whether_the_brand_was_named():
    """It answered wrong in both directions on one cycle — false on "on
    eligible Wiggle & Snug products", true on an answer that only said
    "Wonder" and "The Wiggles". A string is in a string or it is not."""
    schema = prompts.build_extraction_schema()
    assert "brand_mentioned" not in schema["properties"]
    assert "brand_mentioned" not in schema["required"]
    assert "brand_mentioned" not in prompts.EXPECTATION_EXTRACTION_PROMPT


# ── the fixture record scores as expected end to end ──────────────────────

def test_the_fixture_extraction_scores_exact_against_the_published_record():
    """The whole point of the mocked extraction: a known transcription
    plus a known expectation gives a known outcome, with no model in the
    loop at scoring time at all."""
    from scoring import expectation_comparator as cmp

    source_ref = {
        'attribution': ['Size 3', 'Small Pack', '84'],
        'attribution_rivals': ['Size 1', 'Big Pack', '96'],
    }
    for expectation, expected in (
        (ea.price('22.99'), cmp.EXACT),
        (ea.pack_count(84), cmp.EXACT),
        (ea.code('SNUG3', 'amount_off', '3.00'), cmp.EXACT),
        (ea.member_price('16.84', 'Member+'), cmp.EXACT),
        (ea.points('per_dollar', rate='1.0'), cmp.EXACT),
        (ea.brand_mention('Wiggle & Snug', 'trueshopstore.com'), cmp.EXACT),
        (ea.gtin('884400137609'), cmp.ABSENT),
    ):
        verdict = cmp.compare(
            expectation, FIXTURE_EXTRACTION,
            source_ref=source_ref, brand_domain='trueshopstore.com',
        )
        assert verdict.outcome == expected, f"{expectation['type']}: {verdict.reason}"
