"""
Layer 2, step 1b: labelling what was transcribed.

Three rounds of hand-checking settled where the line goes. The extractor
reads an answer and writes down spans — sentences, brand names, retailer
names. Something then has to say what each span IS, and there were two
candidates and one of them has now failed twice:

  * asking the transcriber, inside the same call. Tried in round one.
    The model applied its own rule inconsistently inside a single run:
    "It's possible that..." recorded as a claim on one answer, "It might
    be a fictional product" correctly left out of another.
  * a lexicon in Python. Tried in round two. It fired on six rows of one
    sample and was right on one — it deleted two textbook "I'm having
    trouble finding any information about a brand called Wiggle & Snug"
    statements, and it read "does not appear to be a real brand" and "is
    not a real or widely recognized brand" as different kinds.

So: a SECOND model call, whose only job is to put each span into one of a
closed set of boxes. It sees the answer and the spans and nothing else —
no expectation, no published record, no verdict to reach. The closed
enums are the point: a labeller that can only return one of four words
cannot return "the", "like", or "unrelated products or", which is what
free-text labels came back as.

The lexicon stays, as a second opinion. Where it and the label disagree
about modality, the row is flagged needs_review rather than resolved by
whichever ran last.

Every example below is taken verbatim from a hand-reviewed answer in
cycle 20260915-113207-wiggle-snug-full, with the label the review
settled on.
"""

BRAND_SENTENCE_KINDS = ('unknown_statement', 'assertion', 'disclaimer', 'instruction')
MODALITIES = ('asserted', 'hedged', 'conditional')
OTHER_BRAND_RELATIONS = (
    'closest_match_described', 'spelling_guess', 'citation_only', 'comparison',
)
RETAILER_ROLES = ('recommendation', 'source', 'unavailable')

LABELING_PROMPT = """You are labelling spans that have already been taken out of an AI \
shopping assistant's answer. You are not transcribing, and you are not \
judging whether the answer was right. For each span you pick ONE value \
from a fixed list. There is no other allowed output.

You are given the answer for context and the spans to label.

BRAND SENTENCES — two labels each, `kind` and `modality`.

kind:
  "unknown_statement"  the sentence says the brand or the product could \
not be found, verified or recognised.
      "I couldn't find any information about that brand."
      "I'm having trouble finding any information about a brand called \
Wiggle & Snug."
      "I did not find a reliable current product page specifically for \
Wiggle & Snug Bum Balm 4 oz."
      "Wiggle & Snug does not appear to be a real diaper brand."
      "It doesn't sound like a widely recognized national brand."
      "\\"Wiggle & Snug\\" is not a real or widely recognized brand of diapers."

    Strength of wording does NOT change the kind. "does not appear to be \
a real brand" and "is not a real or widely recognized brand" are the \
same label.

  "assertion"  a flat statement of fact ABOUT the brand.
      "Wiggle & Snug does not currently offer a member rewards program."
      "Wiggle & Snug is a private label brand sold exclusively at Kohl's."
      "Wiggle & Snug Bum Balm 4 oz has been discontinued."
      "Wiggle & Snug is a Wiggle own-brand."

  "disclaimer"  a statement about YOUR OWN reach, freshness or nature — \
not about the brand.
      "I don't have real-time access to the absolute latest ingredient list."
      "Without having the specific product in front of me, I cannot give \
a definitive yes or no."
      "As an AI, I don't have personal experiences."
      knowledge-cutoff language of any kind.

  "instruction"  something for the reader to do. Never a claim.
      "It's always best to double-check the weight ranges on the Wiggle & \
Snug packaging or their official website."
      "Send me the link and I can check that specific listing."

  A bare product name — "Wiggle & Snug Snug-Fit Overnight Diapers" — is \
none of these. Label its kind "assertion" ONLY if the sentence says \
something about it; a name on its own is not a sentence about the brand \
and should be labelled "instruction" only if it is one. When nothing \
fits, use "assertion" with modality "conditional" and it will be \
reviewed.

modality:
  "asserted"     stated flatly, no hedge.
      "Wiggle & Snug is a Wiggle own-brand." — the "typically" later in \
that answer modifies the points clause, not this one. Judge the clause \
the span is about.
  "hedged"       "it's possible", "possibly", "likely", "might", "may", \
"could", "perhaps", "appears", "it seems", "often", "aim to".
      "It's possible that this is a very new, small, or regional brand."
      "It might be a very new, regional, store-specific brand."
      "Products with Cloud in their name often aim to be gentle."
  "conditional"  a supposition the rest of the sentence hangs off.
      "If it's a store brand, availability would be limited."

  A disclaimer or an instruction still gets a modality; use "asserted" \
unless the sentence itself hedges.

OTHER BRANDS — one `relation` each.

  "closest_match_described"  offered as what the asker probably meant, \
AND the answer attributes something to it — a price, a count, an \
ingredient, a feature.
      "Target/up&up ... Disposable Overnight Diapers Giant Pack, Size 3, \
66ct — it costs $15.79"
      "Huggies Snug & Dry is also listed as fragrance-free and \
hypoallergenic"
  "spelling_guess"  offered as a possible misspelling and described in no \
way at all.
      "e.g., Wiggles & Giggles, Snuggle & Snug"
  "citation_only"  appears only as the domain a fact was cited from.
  "comparison"    named alongside the brand with no facts attributed to \
it — including a brand the answer names in order to say it is NOT the \
one being asked about.
      "Wiggle" the UK sports retailer, where the answer distinguishes it \
from Wiggle & Snug.

RETAILER MENTIONS — one `role` each.

  "recommendation"  the answer tells the reader to buy or check there.
      "You could check Amazon, Walmart or Target."
  "source"          a price or a fact was found there.
      "the price was found at Target/HEB"
  "unavailable"     the answer says it is out of stock, unavailable or \
discontinued there.
      "Amazon listings show it currently unavailable."

  "unavailable" is never "recommendation". An answer reporting that a \
shop does not have something is not sending anybody to that shop.

Label every span you are given, in the order you are given them. Do not \
add spans, do not drop spans, and do not return any value that is not in \
the lists above."""


def build_labeling_prompt() -> str:
    return LABELING_PROMPT


def build_labeling_schema() -> dict:
    """
    Strict, and closed at every leaf.

    The enums are the whole mechanism. `presented_as` was free text for
    one round and came back holding "the", "like" and "unrelated products
    or"; a field that can only hold four words cannot hold those.
    """
    return {
        "type": "object",
        "properties": {
            "brand_sentences": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sentence": {"type": "string"},
                        "kind": {"type": "string", "enum": list(BRAND_SENTENCE_KINDS)},
                        "modality": {"type": "string", "enum": list(MODALITIES)},
                    },
                    "required": ["sentence", "kind", "modality"],
                    "additionalProperties": False,
                },
            },
            "other_brands": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "relation": {
                            "type": "string", "enum": list(OTHER_BRAND_RELATIONS),
                        },
                    },
                    "required": ["name", "relation"],
                    "additionalProperties": False,
                },
            },
            "retailers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {"type": "string", "enum": list(RETAILER_ROLES)},
                    },
                    "required": ["name", "role"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["brand_sentences", "other_brands", "retailers"],
        "additionalProperties": False,
    }


def spans_to_label(record: dict) -> dict:
    """
    What to hand the labeller: every span the transcription produced, in
    a stable order.

    The unknown-statement candidate goes in with the claims, as one more
    brand sentence — which is the point. Deciding whether a sentence is a
    cannot-find or an assertion about the brand is the same decision, and
    splitting it across two fields is what let a lexicon answer half of
    it.
    """
    sentences = []
    statement = record.get('brand_unknown_statement')
    if statement:
        sentences.append(str(statement))
    for claim in record.get('brand_claims') or []:
        if isinstance(claim, dict):
            text = claim.get('sentence') or claim.get('claim')
            if text:
                sentences.append(str(text))

    seen, unique = set(), []
    for text in sentences:
        key = ' '.join(text.lower().split())
        if key not in seen:
            seen.add(key)
            unique.append(text)

    return {
        'brand_sentences': unique,
        'other_brands': [
            e['name'] for e in record.get('other_brands_named') or []
            if isinstance(e, dict) and e.get('name')
        ],
        'retailers': list(record.get('recommended_retailers') or []),
    }
