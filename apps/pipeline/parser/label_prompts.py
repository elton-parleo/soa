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

# `none` is the fifth, and it is what makes the coverage check possible.
# Every span is offered to the labeller, including the ones that are not
# about the brand at all; a span it declines has to say so, because
# "labelled none" and "never came back" are different facts and only one
# of them is a finding.
from parser.span_segmenter import segment

BRAND_SENTENCE_KINDS = (
    'unknown_statement', 'assertion', 'disclaimer', 'instruction', 'none',
)
MODALITIES = ('asserted', 'hedged', 'conditional')
# Four of these were specified; `not_a_brand` is a fifth, added because
# two reviewed rows could not be expressed without it. One answer named
# "Wiggle", the UK sports retailer, as Wiggle & Snug's parent company —
# the review's ruling is that this is an assertion ABOUT the brand, not
# another brand. Another listed Amazon, Walmart, Target, Walmart.com and
# Target.com as other brands; they are shops, and two of them are the
# same shop twice.
#
# Without a value meaning "this name does not belong in this list", the
# labeller has to pick one of the four and the name stays — and a
# retailer sitting in other_brands is a misattribution waiting to be
# found.
OTHER_BRAND_RELATIONS = (
    'closest_match_described', 'spelling_guess', 'citation_only', 'comparison',
    'not_a_brand',
)
RETAILER_ROLES = ('recommendation', 'source', 'unavailable')

LABELING_PROMPT = """You are labelling spans that have already been taken out of an AI \
shopping assistant's answer. You are not transcribing, and you are not \
judging whether the answer was right. For each span you pick ONE value \
from a fixed list. There is no other allowed output.

You are given the answer for context and the spans to label.

You are given the answer, and then the answer cut into numbered SPANS.
The spans are ours. Label each one by its id. You cannot merge two spans,
extend one, quote a different piece of text, or return a span id that was
not given to you — the only thing coming back is an id and two words from
the lists below.

That is not a style preference. Choosing where a sentence stops used to
be part of this job, and it merged "It seems there might be a slight
misunderstanding." with the flat claim that followed, so the first
sentence's hedge suppressed the second sentence's claim; it ran a
cannot-find statement past a "but" and swallowed a product claim with it;
and it dropped whole sentences, including one answer's entire headline.
The cutting is done before you see it now.

SPANS — two labels each, `kind` and `modality`.

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

  "none"  the span is not about the brand under discussion: a heading, \
a bare product name, a sentence about somebody else, a list item of \
general advice. Most spans in a long answer are this.

  Use "none" rather than forcing a span into one of the other four. It \
is a real answer, not a failure to decide — and a span you simply do not \
return at all is neither, which is why every span has to come back.

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
  "not_a_brand"   the name is not another brand at all: a shop ("Amazon", \
"Walmart.com"), the brand's own website, or the brand's own parent \
presented as its owner. A shop belongs in the retailer list and an \
owner is a statement about the brand; neither is a rival.

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

Return one entry for EVERY span id you were given, in order, and no \
others. Do not add spans, do not drop spans, and do not return any value \
that is not in the lists above."""


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
            "spans": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        # The id we gave it. Never the text: a labeller
                        # that hands back its own quotation is a labeller
                        # that can paraphrase, and a label on words
                        # nobody said cannot be checked against the
                        # stored answer.
                        "span_id": {"type": "integer"},
                        "kind": {"type": "string", "enum": list(BRAND_SENTENCE_KINDS)},
                        "modality": {"type": "string", "enum": list(MODALITIES)},
                    },
                    "required": ["span_id", "kind", "modality"],
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
        "required": ["spans", "other_brands", "retailers"],
        "additionalProperties": False,
    }


def spans_to_label(record: dict, answer_text=None) -> dict:
    """
    What to hand the labeller: the ANSWER, cut up by the segmenter, plus
    the names the transcription found.

    The spans no longer come from the transcription. They come from
    span_segmenter.segment, which means they are verbatim, they are in
    order, they cover the answer, and — the part that matters — a span
    that names the brand and comes back unlabelled is visible as a gap
    rather than as an absence nobody can see.

    `answer_text` is optional only so an older stored record can still be
    relabelled from the sentences it happens to carry. Every live caller
    passes the answer.
    """
    if answer_text:
        spans = segment(answer_text)
    else:
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
        spans = [{'id': i, 'text': t} for i, t in enumerate(unique, start=1)]

    return {
        'spans': spans,
        'other_brands': [
            e['name'] for e in record.get('other_brands_named') or []
            if isinstance(e, dict) and e.get('name')
        ],
        'retailers': [
            m['name'] for m in record.get('retailer_mentions') or []
            if isinstance(m, dict) and m.get('name')
        ] or list(record.get('recommended_retailers') or []),
    }
