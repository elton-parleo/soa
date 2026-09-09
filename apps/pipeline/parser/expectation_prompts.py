"""
Layer 2 extraction — the prompt and strict JSON schema for transcribing
what an answer SAID about the quantities a typed expectation names.

Deliberately separate from prompts.py (pass 1: mention coding) and
prompts_v2.py (pass 2: merchant attribution and citations). Layer 2 asks
for neither of those things, so there is nothing here for them to drift
from, by construction — the same separation, for the same reason, that
pass 2 already has from pass 1.

THE EXTRACTION TRANSCRIBES; IT NEVER JUDGES.

Nothing in the schema below is a verdict. There is no `correct`, no
`matches_expectation`, no confidence in the ANSWER — only whether the
transcription itself succeeded, which is what produces the `unscoreable`
outcome. The comparison that follows is ordinary deterministic Python
(scoring/expectation_comparator.py), which is what makes a stored
extraction re-checkable rather than merely re-runnable.

The reason this line is drawn so hard: a model asked "is this answer
right?" is a second opinion, and two models disagreeing about whether
$22.99 matches "about twenty-three dollars" is not a measurement. Worse,
it fails in the flattering direction — a generous judge scores a wrong
answer as right, and the whole point of this tier is to catch wrong
answers.

The expectation is NOT put in the prompt. The extractor is not told what
the right answer is, because an extractor that knows the target price
will find it: asked to transcribe prices from an answer that says "around
twenty-three dollars", a model holding "22.99" writes 22.99. Telling it
nothing makes the transcription independent of the thing it is checked
against, which is the only arrangement under which the check means
anything.

See docs/expected-answer-vocabulary.md.
"""

EXPECTATION_EXTRACTION_PROMPT = """You are transcribing what an AI shopping assistant's answer SAID. You are \
not judging whether it was right, and you are not being told what the right \
answer is.

Read the answer and write down every price, promotion code, pack count and \
member price it states, plus whether it named the brand and which sources it \
cited. Transcribe only. Do not correct, complete, round, convert or infer any \
value; do not add a value the answer does not state.

Every example value below is a made-up placeholder. None of them is the answer \
to anything you are being shown, and none of them tells you what any correct \
value is.

PRICES
Every plain price the answer states for a product, with the product it \
attributes that price to.
  amount: the number as written, e.g. "14.50". Do not round or convert.
  currency: the currency code if the answer makes it clear ("USD", "GBP"), \
otherwise null. Do not assume a currency from a bare "$".
  attributed_product: the product or variant this price is stated FOR, as \
named in the answer — e.g. "Acme Widgets Large, 3-pack", "the 60 count \
box". Null only if the answer states a price attached to no product at all.

  Attribution matters more than the number. If the answer says a price for one \
size and a different price for another, those are two entries with two \
different attributed_product values. Never merge them, and never move a price \
onto a product the answer did not attach it to.

  If the answer gives a range ("$14-$17"), record the range's endpoints as two \
entries with the same attributed_product.

CODES
Every promotion or coupon code the answer states.
  code: the code exactly as written, e.g. "SAVE5".
  value_kind: "amount_off" if the answer says a money amount off, \
"percent_off" if it says a percentage, "member_price" if the code sets a price \
rather than a discount, null if the answer states a code but not what it does.
  value: the number for that kind — dollars for amount_off and member_price, \
the percent for percent_off ("15" for 15% off, not "0.15"). Null if the answer \
does not say.

PACK COUNTS
Every unit count the answer states for a product.
  value: the integer, e.g. 60.
  attributed_product: which product that count is stated for, as named.

GTINS
Every barcode or GTIN/UPC/EAN the answer states, with the product it \
attributes it to.
  value: the digits as written.
  attributed_product: which product, as named.

  Nobody asks an assistant for a barcode, so this list is usually empty. \
Record one only when the answer volunteers it.

MEMBER PRICES
Every price the answer says a loyalty member or a named tier pays.
  amount: the number as written.
  tier: the tier or programme level named, e.g. "Gold". Null if the answer \
says "members" without naming a level.
  attributed_product: which product, as named.

  A price the answer presents as the ordinary price belongs in PRICES, not \
here. Only put a price here when the answer ties it to membership.

BRAND MENTIONED
brand_mentioned: true if the answer names the brand under discussion at all, \
false if it does not. This is presence, not endorsement — a passing, negative \
or dismissive mention is still true.

SOURCES CITED
sources_cited: the bare domains of every source the answer cites or links to, \
e.g. ["example-shop.com", "a-retailer.com"]. Only domains actually written out in \
the answer. Do not construct, guess or complete a partial URL, and do not add \
a domain because you recognise a retailer the answer named without linking.

CONFIDENCE
extraction_confident: false when you could not confidently read the answer — it \
is truncated mid-sentence, garbled, in a format you cannot parse, or an error \
message rather than an answer. true otherwise, INCLUDING when the answer simply \
does not address any of the quantities above. "The answer said nothing about \
price" is a confident reading; "I could not tell what the answer said" is not.

  This distinction is the one thing here that must not slip. An answer that \
does not address a quantity is a real result about the assistant. An answer we \
could not read is a result about us, and the two must never be counted \
together.

extraction_note: one short phrase saying why, when extraction_confident is \
false. Null otherwise.

Return every list empty rather than inventing an entry. An answer that states \
no price has no prices."""


def build_extraction_prompt(brand: str = None) -> str:
    """
    The system prompt, optionally naming the brand whose presence is being
    transcribed.

    The brand is the ONLY thing about the expectation the extractor is
    told, and it is told only the name — never the domain, never a price,
    never a code. `brand_mentioned` is unanswerable without knowing which
    brand is meant, whereas every other field is a transcription of what
    the answer says and needs no target at all. Handing over the domain
    too would tell a model which citation we are hoping to find.
    """
    if not brand:
        return EXPECTATION_EXTRACTION_PROMPT
    return (
        f"{EXPECTATION_EXTRACTION_PROMPT}\n\n"
        f"The brand under discussion is: {brand}. Use it only to decide "
        f"brand_mentioned. It tells you nothing about what any correct value "
        f"is, and you are not being asked."
    )


def build_extraction_schema() -> dict:
    """
    Strict JSON schema. Every field required and additionalProperties
    false, matching build_pass2_schema's conventions — a model that omits
    a field should fail the call rather than hand back a partial record
    that reads as an absent quantity.
    """
    return {
        "type": "object",
        "properties": {
            "prices": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": ["string", "null"]},
                        "currency": {"type": ["string", "null"]},
                        "attributed_product": {"type": ["string", "null"]},
                    },
                    "required": ["amount", "currency", "attributed_product"],
                    "additionalProperties": False,
                },
            },
            "codes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "value_kind": {"type": ["string", "null"]},
                        "value": {"type": ["string", "null"]},
                    },
                    "required": ["code", "value_kind", "value"],
                    "additionalProperties": False,
                },
            },
            "pack_counts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "value": {"type": ["integer", "null"]},
                        "attributed_product": {"type": ["string", "null"]},
                    },
                    "required": ["value", "attributed_product"],
                    "additionalProperties": False,
                },
            },
            "gtins": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "value": {"type": ["string", "null"]},
                        "attributed_product": {"type": ["string", "null"]},
                    },
                    "required": ["value", "attributed_product"],
                    "additionalProperties": False,
                },
            },
            "member_prices": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": ["string", "null"]},
                        "tier": {"type": ["string", "null"]},
                        "attributed_product": {"type": ["string", "null"]},
                    },
                    "required": ["amount", "tier", "attributed_product"],
                    "additionalProperties": False,
                },
            },
            "points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "value": {"type": ["string", "null"]},
                        "per_dollar": {"type": ["boolean", "null"]},
                        "program": {"type": ["string", "null"]},
                    },
                    "required": ["value", "per_dollar", "program"],
                    "additionalProperties": False,
                },
            },
            "brand_mentioned": {"type": "boolean"},
            "sources_cited": {"type": "array", "items": {"type": "string"}},
            "extraction_confident": {"type": "boolean"},
            "extraction_note": {"type": ["string", "null"]},
        },
        "required": [
            "prices", "codes", "pack_counts", "gtins", "member_prices", "points",
            "brand_mentioned", "sources_cited",
            "extraction_confident", "extraction_note",
        ],
        "additionalProperties": False,
    }


# The empty extraction: what a run with no usable answer records, so an
# outcome row exists for every run rather than silently missing.
EMPTY_EXTRACTION = {
    "prices": [],
    "codes": [],
    "pack_counts": [],
    "gtins": [],
    "member_prices": [],
    "points": [],
    "brand_mentioned": False,
    "sources_cited": [],
    "extraction_confident": False,
    "extraction_note": "no answer text to read",
}
