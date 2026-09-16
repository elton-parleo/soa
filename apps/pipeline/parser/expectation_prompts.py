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
from soa_shared import expected_answers as ea

EXPECTATION_EXTRACTION_PROMPT = """You are transcribing what an AI shopping assistant's answer SAID. You are \
not judging whether it was right, and you are not being told what the right \
answer is.

Read the answer and write down every price, promotion code, pack count, \
size and member price it states, which sources it cited and which shops it \
pointed the reader to. Transcribe only. Do not correct, complete, round, convert or infer any \
value; do not add a value the answer does not state.

Every example value below is a made-up placeholder. None of them is the answer \
to anything you are being shown, and none of them tells you what any correct \
value is.

PRICES
Every plain price the answer states for a product, with the product it \
attributes that price to.
  amount: the number as written, e.g. "14.50". Do not round or convert.
  currency: the currency code the answer's own symbol or word implies. A \
bare "$" is "USD" — consistently, every time, including inside a range \
like "$10 to $15". "£" is "GBP", "€" is "EUR". Null ONLY when the answer \
states a number with no currency marker at all.
  attributed_product: the product or variant this price is stated FOR, as \
named in the answer — e.g. "Acme Widgets Large, 3-pack", "the 60 count \
box". Null only if the answer states a price attached to no product at all.

  Attribution matters more than the number. If the answer says a price for one \
size and a different price for another, those are two entries with two \
different attributed_product values. Never merge them, and never move a price \
onto a product the answer did not attach it to.

  If the answer gives a range ("$14-$17"), record the range's endpoints as two \
entries with the same attributed_product — and the same currency on both. \
The symbol at the front of a range governs the whole range.

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
Every unit COUNT the answer states for a product — how many items are in
the pack.
  value: the integer, e.g. 60.
  attributed_product: which product that count is stated for, as named.

  A count answers "how many". If the number answers "how big" or "how
  much is in it" — 4 oz, 3.4 fl oz, 100 ml, 250 g, 1 litre — it is a SIZE
  and goes in SIZES below, never here. "4 oz" is not a pack of four.

SIZES
Every weight, volume or physical measurement the answer states for a
product.
  value: the number as written, e.g. "4", "3.4".
  unit: the unit as written, e.g. "oz", "fl oz", "ml", "g".
  attributed_product: which product, as named.

  This list exists because a size read as a count is a wrong number
  attached to a real product, which is worse than a missing one: it
  scores an assistant against a quantity nobody asked about. A pack of
  four and a four-ounce jar are different facts.

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

CANNOT-FIND STATEMENT
brand_unknown_statement: the answer's own words, quoted, where it says it \
cannot find, cannot verify, does not recognise or has no information about \
the brand or the product — e.g. "I could not find any information about that \
brand". Null if the answer makes no such statement.

  Quote it; do not paraphrase and do not summarise. It has to be a \
statement that the BRAND OR THE PRODUCT is unfindable, unverifiable or \
unknown to you — "I could not find", "I cannot verify", "I have never \
heard of it", "it does not appear to exist", "not a real brand".

  These are NOT that statement, and this field is null for every one of \
them:

    * a freshness disclaimer — "I don't have real-time access to the \
latest ingredient list", "my information may be out of date". That says \
your knowledge has a date on it, not that the brand is unknown; an answer \
that then describes the brand as real has plainly found it.
    * hedging about one detail — "I am not sure of the current price".
    * simply not mentioning the brand. Saying nothing is not saying you \
could not find it.

OTHER BRANDS NAMED
other_brands_named: every brand OTHER than the one under discussion that the \
answer names, with the words the answer used to relate it.
  name: the other brand, as written, e.g. "Some Other Label".
  presented_as: exactly one of these four words, and nothing else:

    "closest_match"  offered as what the asker must have meant — "if you \
meant", "did you mean", "you might be looking for", "the closest match I \
found", "assuming you mean".
    "comparison"     weighed against the brand under discussion — "unlike \
X", "compared with X", "X also does this".
    "recommendation" suggested as something to try or buy as well as, or \
after failing to find, the brand — "popular alternatives include".
    "source"         named only as where the information came from.

  Null when none of the four fits. NEVER a fragment of the answer's own \
sentence: "the", "like", "such as" are not values for this field.

  Transcribe the relationship the answer states. Do not decide whether a \
substitution was reasonable; that is not being asked.

BRAND-SPECIFIC CLAIMS
brand_claims: every specific factual claim the answer makes ABOUT the brand \
under discussion that is not one of the quantities above — where it is sold, \
who owns it, whether it is exclusive to a retailer, what its loyalty tiers are \
called, when it launched.
  claim: the claim in the answer's own words.
  kind: "retail" for where it is sold or who sells it, "ownership" for who \
owns or manufactures it, "loyalty" for programme or tier names, "other" for \
anything else.

  A claim is an ASSERTION of fact about the brand. A possibility is not.

    a claim:     "It is a private label sold at a discount grocer."
    a claim:     "The tiers are called Bronze and Silver."
    NOT a claim: "It's possible this is a very new, small, or regional brand."
    NOT a claim: "They likely emphasise a closer fit."
    NOT a claim: "It might be a store brand."
    NOT a claim: "It should be suitable for sensitive skin."

  If the sentence is hedged — possible, possibly, likely, probably, may, \
might, could, perhaps, presumably, I would guess, I suspect, seems, \
appears to be — it is speculation and it does not belong in this list, \
however specific the thing being speculated about. Record what the answer \
asserts, not what it wonders.

LOYALTY TIERS NAMED
loyalty_tiers_named: every loyalty programme tier or level the answer \
names for the brand under discussion, as written — e.g. ["Bronze", \
"Silver"]. Empty when the answer names none.

  The tiers, not the programme. "Acme Rewards has two tiers, Bronze and \
Silver" gives ["Bronze", "Silver"] and not "Acme Rewards". A tier \
belonging to some other company's programme is not this brand's tier and \
does not go here.

SOURCES CITED
sources_cited: the bare domains of every source the answer cites AS WHERE \
IT GOT SOMETHING — a link, a parenthetical attribution, "according to". \
Only domains actually written out in the answer. Do not construct, guess \
or complete a partial URL, and do not add a domain because you recognise a \
retailer the answer named without linking.

  A recommendation is not a citation. "You could check Amazon, Walmart or \
Target" tells the reader where to go; it does not say where the answer's \
information came from. Those go in RECOMMENDED RETAILERS and this list \
stays empty. An answer that names three retailers to check and links to \
none of them has cited nothing.

RECOMMENDED RETAILERS
recommended_retailers: every shop, marketplace or site the answer tells \
the reader to go to, look at, or buy from, as written — e.g. ["Amazon", \
"Walmart"]. Empty when the answer sends the reader nowhere.

  Recorded separately because it is its own signal: telling a shopper to \
go and buy a brand somewhere is a claim about where that brand is sold.

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
    never a code. It is needed to tell "the brand under discussion" apart
    from every other brand in the answer, which several fields turn on:
    which brands are OTHER brands, whose loyalty tiers are being named,
    who a claim is about. Handing over the domain too would tell a model
    which citation we are hoping to find.

    It is NOT used for brand_mentioned any more. That field is computed
    from the answer text by ea.names_brand after this call returns — see
    stamp_brand_mentioned.
    """
    if not brand:
        return EXPECTATION_EXTRACTION_PROMPT
    return (
        f"{EXPECTATION_EXTRACTION_PROMPT}\n\n"
        f"The brand under discussion is: {brand}. Use it only to tell that "
        f"brand apart from the others the answer may name. It tells you "
        f"nothing about what any correct value is, and you are not being "
        f"asked."
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
            "sizes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "value": {"type": ["string", "null"]},
                        "unit": {"type": ["string", "null"]},
                        "attributed_product": {"type": ["string", "null"]},
                    },
                    "required": ["value", "unit", "attributed_product"],
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
            "brand_unknown_statement": {"type": ["string", "null"]},
            "other_brands_named": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "presented_as": {
                            "type": ["string", "null"],
                            "enum": [
                                "closest_match", "comparison",
                                "recommendation", "source", None,
                            ],
                        },
                    },
                    "required": ["name", "presented_as"],
                    "additionalProperties": False,
                },
            },
            "loyalty_tiers_named": {"type": "array", "items": {"type": "string"}},
            "brand_claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "kind": {"type": ["string", "null"]},
                    },
                    "required": ["claim", "kind"],
                    "additionalProperties": False,
                },
            },
            "sources_cited": {"type": "array", "items": {"type": "string"}},
            "recommended_retailers": {"type": "array", "items": {"type": "string"}},
            "extraction_confident": {"type": "boolean"},
            "extraction_note": {"type": ["string", "null"]},
        },
        "required": [
            "prices", "codes", "pack_counts", "sizes", "gtins",
            "member_prices", "points", "brand_unknown_statement",
            "other_brands_named", "loyalty_tiers_named", "brand_claims",
            "sources_cited", "recommended_retailers",
            "extraction_confident", "extraction_note",
        ],
        "additionalProperties": False,
    }


PRESENTED_AS = ('closest_match', 'comparison', 'recommendation', 'source')


def stamp_brand_mentioned(record: dict, answer_text, brand) -> dict:
    """
    Whether the answer named the brand, decided here rather than asked of
    the model.

    It was a model field, and on one cycle it was wrong in both
    directions: false on an answer reading "on eligible Wiggle & Snug
    products", true on an answer that only ever said "Wonder" and "The
    Wiggles". Both errors changed an outcome — the first to `absent`, the
    second to a brand assessment of an answer about somebody else.

    Nothing about this needs a model. It is a string in a string, and a
    deterministic check is both right every time and re-checkable by hand
    from the stored answer, which the rest of Layer 2 already promises.

    Mutates and returns `record`, so the client can apply it to whatever
    the call produced — including a failed call, whose record names
    nobody.
    """
    record['brand_mentioned'] = bool(
        answer_text and ea.names_brand(answer_text, brand)
    )
    return record


# The empty extraction: what a run with no usable answer records, so an
# outcome row exists for every run rather than silently missing.
EMPTY_EXTRACTION = {
    "prices": [],
    "codes": [],
    "pack_counts": [],
    "sizes": [],
    "gtins": [],
    "member_prices": [],
    "points": [],
    # Computed, never extracted — see stamp_brand_mentioned. False here
    # because an answer we could not read named nobody.
    "brand_mentioned": False,
    "brand_unknown_statement": None,
    "other_brands_named": [],
    "loyalty_tiers_named": [],
    "brand_claims": [],
    "sources_cited": [],
    "recommended_retailers": [],
    "extraction_confident": False,
    "extraction_note": "no answer text to read",
}
