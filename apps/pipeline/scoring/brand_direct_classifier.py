"""
What a brand-direct answer actually did with the brand.

The tier used to be scored on presence: `exact` if the answer named the
brand, `absent` if not. Cycle 20260915-113207 is what that produces. Of
66 runs, 63 scored `exact` — a 95% success rate on a brand the
assistants, read in full, mostly could not find:

  * Gemini: "Wiggle & Snug Snug-Fit Diapers is not a real or widely
    recognized brand of diapers." Scored exact, because it said the name.
  * Gemini: "Wiggle & Snug is a private label brand sold exclusively at
    Kohl's", with loyalty tiers "Snuggle Friend, Snuggle Pal, Snuggle
    Bestie". Scored exact. None of it is in the record.
  * ChatGPT: "the closest match I found is Beezpro's Snug Fit Padded
    underwear Single Piece Trial Pack". Scored exact.
  * ChatGPT, twice: cited trueshopstore.com/loyalty and got Member and
    Member+ right. Also scored exact — indistinguishable, in the report,
    from the three above.

Two of 66 runs read the brand's own record. The measurement said 63.

So presence is not the measurement, and this module is the measurement
that replaces it. Five classifications, decided deterministically from a
transcription; see soa_shared.expected_answers.BRAND_ASSESSMENTS for what
each one means.

THE CLASSIFIER DOES NOT JUDGE EITHER. Every input is something the
extractor transcribed from the answer — a quoted sentence, a brand name
with the answer's own framing of it, a claim in the answer's own words —
or something read off the published record. Nothing here asks a model
whether an answer was good, for the same reason nothing else in Layer 2
does.
"""
import re
from typing import Optional

from soa_shared import expected_answers as ea

GROUNDED = 'grounded'
ECHOED = 'echoed'
MISATTRIBUTED = 'misattributed'
FABRICATED = 'fabricated'
ACKNOWLEDGED_UNKNOWN = 'acknowledged_unknown'
ABSENT = 'absent'
UNSCOREABLE = 'unscoreable'

_NOISE = re.compile(r'[^a-z0-9]+')


def _norm(text) -> str:
    return _NOISE.sub(' ', str(text or '').lower().replace('&', ' and ')).strip()


def _tokens(text) -> set:
    return {t for t in _norm(text).split() if t}


# `presented_as` is one of four words the extractor chooses from, and
# only one of them is a substitution: closest_match means the answer
# decided the asker must have meant somebody else. A `recommendation`
# ("popular alternatives include...") sits beside an answer about this
# brand rather than replacing it, and a `comparison` is the opposite of a
# substitution. Neither is misattribution on its own — but if the answer
# then hangs its numbers on that other brand's product, route one of
# misattributed_to catches it regardless of the label.
SUBSTITUTION = 'closest_match'

# Free text this field used to hold, before it was an enum. Kept so the
# classifier still reads extractions stored under the old prompt — a
# re-score over old records must not silently stop finding substitutions
# it used to find. New extractions cannot produce these: the schema
# enumerates the four words.
LEGACY_SUBSTITUTION_PHRASES = (
    'closest match', 'if you meant', 'did you mean', 'you might mean',
    'assuming you mean', 'looking for', 'similar', 'instead', 'alternative',
    'in place of', 'rather than', 'misremember',
)


def _is_substitution(presented_as) -> bool:
    text = str(presented_as or '').strip().lower()
    if not text:
        return False
    if text in ('comparison', 'recommendation', 'source'):
        return False
    if text == SUBSTITUTION:
        return True
    return any(phrase in text for phrase in LEGACY_SUBSTITUTION_PHRASES)


def _quantities(extraction) -> list:
    """Every extracted value that carries an attributed_product — the
    things the answer said ABOUT something."""
    out = []
    for key in ('prices', 'pack_counts', 'gtins', 'member_prices'):
        for item in extraction.get(key) or []:
            if isinstance(item, dict) and item.get('attributed_product'):
                out.append(item['attributed_product'])
    return out


def misattributed_to(extraction) -> Optional[str]:
    """
    The other brand this answer's specifics belong to, or None.

    Two routes, because the evidence shows two shapes. Either the answer
    attaches its numbers to a product that names somebody else — "Bc
    Babycare Cloud Moist Baby Wipes", "Beezpro's Snug Fit Padded
    underwear", "Amallow Baby Bum Balm" — or it names another brand in
    place of this one without quoting a number at all: "If you meant
    Huggies Little Snugglers", "you might be looking for Wiggle & Giggle".

    Both are the same result for the brand being measured. A shopper who
    asked about this brand walks away with a different one.
    """
    others = [
        entry for entry in extraction.get('other_brands_named') or []
        if isinstance(entry, dict) and entry.get('name')
    ]
    if not others:
        return None

    attributed = [_tokens(product) for product in _quantities(extraction)]
    for entry in others:
        name_tokens = _tokens(entry['name'])
        if not name_tokens:
            continue
        # Route one: a number of ours, attached to their product.
        if any(name_tokens <= product for product in attributed):
            return entry['name']
        # Route two: offered as the thing the asker must have meant.
        if _is_substitution(entry.get('presented_as')):
            return entry['name']
    return None


_DOMAIN = re.compile(r'\b((?:[a-z0-9-]+\.)+(?:com|net|org|io|co|shop|store|in|uk|ca))\b', re.I)


def _tier_contradictions(extraction, facts):
    """
    Loyalty tier names the answer stated that the record does not publish.

    Compared as a SET of transcribed names, not by looking for the real
    names in a sentence. That distinction is load-bearing: run 10833 said
    "the Member Rewards tiers are Wiggle, Snug, Cuddle", and a sentence
    search for the published tier "Member" finds it inside the programme's
    own name and concludes the answer got it right. The programme is not a
    tier. Only the list the answer actually gave is compared.
    """
    published = {_norm(t) for t in facts.get('tier_names') or [] if t}
    stated = [t for t in extraction.get('loyalty_tiers_named') or [] if t]
    if not published or not stated:
        return

    unknown = [t for t in stated if _norm(t) not in published]
    if len(unknown) == len(stated):
        yield {
            'claim': ', '.join(stated),
            'why': 'names tiers the record does not publish',
        }


def _recommended_without_source(extraction):
    """
    Sending a shopper somewhere to buy this brand, with nothing behind it.

    Telling a reader to "check Amazon, Walmart or Target" is a claim about
    where the brand is sold — which is why the extractor records it apart
    from the sources it cites, and why it is a finding rather than
    scenery.

    Two ways out of it, both deliberate:

      * the answer cited something. Then it is sourced, and the record
        does not carry retail presence, so it cannot be contradicted;
      * the answer also said it could not find the brand. "I could not
        find this brand — you could try Amazon" is a suggestion to go
        looking, not an assertion that it is there, and treating the two
        the same would punish the most honest answer in the set for
        trying to be useful.
    """
    retailers = [r for r in extraction.get('recommended_retailers') or [] if r]
    if not retailers:
        return None
    if extraction.get('sources_cited') or extraction.get('brand_unknown_statement'):
        return None
    return {
        'claim': f"told the reader to buy it at {', '.join(retailers)}",
        'why': 'where to buy, stated with no source',
    }


def contradicted_claims(extraction, brand_facts=None) -> list:
    """
    Brand-specific claims the published record contradicts, plus claims
    made with no source at all.

    The record is the authority and the limit. Where it states a fact —
    the loyalty tier names, the brand's own domain, which products exist
    — a claim that disagrees is contradicted, and that is a finding
    whether or not the answer cited anything. Where the record says
    nothing, an unsourced claim is the most that can be said: the answer
    asserted something specific about this brand and showed nothing.

    What is deliberately NOT done is calling a claim false because the
    record is silent on it. "Sold at Aldi" is not in the record, and the
    record does not carry retail presence, so it is reported as an
    unsourced assertion rather than as a proven invention.
    """
    facts = brand_facts or {}
    claims = [
        claim for claim in extraction.get('brand_claims') or []
        if isinstance(claim, dict) and claim.get('claim')
    ]

    sourced = bool(extraction.get('sources_cited'))
    titles = {_norm(t) for t in facts.get('product_titles') or [] if t}
    domain = _norm(facts.get('domain'))

    found = list(_tier_contradictions(extraction, facts))
    availability = _recommended_without_source(extraction)
    if availability:
        found.append(availability)
    for claim in claims:
        kind = (claim.get('kind') or 'other').lower()
        text = claim['claim']
        words = _tokens(text)

        if kind == 'ownership' and domain:
            # A claim that names a DIFFERENT domain as the brand's own.
            # Run 10663 called wiggleandsnug.com "their official website";
            # the record says trueshopstore.com. Matched on the domain in
            # the claim rather than on words like "official", because the
            # phrasing varies and the domain does not.
            claimed = _DOMAIN.findall(str(text))
            if claimed and not any(_norm(d) == domain for d in claimed):
                found.append({
                    'claim': text,
                    'why': f"the record's own domain is {facts.get('domain')}",
                })
                continue

        if kind == 'availability' and titles:
            # "Discontinued" about something the record is publishing now.
            if words & {'discontinued', 'unavailable', 'no', 'not'}:
                if any(set(title.split()) & words for title in titles if title):
                    found.append({'claim': text, 'why': 'the record publishes this product now'})
                    continue

        if not sourced:
            found.append({'claim': text, 'why': 'stated with no source'})

    return found


def classify(extraction, expectation, *, brand_facts=None) -> tuple:
    """
    (assessment, reason). The order the checks run in IS the ruling, so
    it is written out rather than implied:

      unscoreable          we could not read the answer. Ours, not theirs,
                           and never folded into anything else.
      absent               the brand never came up. Nothing further can be
                           said about how it was treated.
      misattributed        the specifics belong to another brand. This
                           outranks the honest "I could not find it" that
                           often accompanies it, because an answer that
                           says "I cannot verify this brand, but here is
                           Huggies" leaves the reader holding Huggies. The
                           admission is a mitigation, not the result.
      fabricated           it asserted brand-specific facts the record
                           contradicts, or asserted them with no source.
                           Outranks grounded on purpose: an invention with
                           a citation attached is worse than one without.
      acknowledged_unknown it said it could not find or verify the brand,
                           and did not answer about somebody else instead.
                           The honest failure, and the one that most needs
                           telling apart from the other two.
      grounded             it cited the brand's own domain.
      echoed               it named the brand. Nothing else is checkable —
                           which is exactly what the old `exact` meant.
    """
    extraction = extraction or {}

    if not extraction.get('extraction_confident', True):
        return UNSCOREABLE, extraction.get('extraction_note') or 'the answer could not be read'

    brand = (expectation or {}).get('brand')
    if not extraction.get('brand_mentioned'):
        return ABSENT, f"the answer did not name {brand}"

    other = misattributed_to(extraction)
    if other:
        return MISATTRIBUTED, f"named {brand} but described {other}"

    contradicted = contradicted_claims(extraction, brand_facts)
    if contradicted:
        first = contradicted[0]
        return FABRICATED, f"{first['claim']!r} — {first['why']}"

    unknown = extraction.get('brand_unknown_statement')
    if unknown:
        return ACKNOWLEDGED_UNKNOWN, f"said it could not find {brand}: {unknown!r}"

    domain = (expectation or {}).get('domain')
    if domain and _norm(domain) in {_norm(s) for s in extraction.get('sources_cited') or []}:
        return GROUNDED, f"cited {domain}"

    return ECHOED, f"named {brand}, with nothing checkable behind it"


def is_brand_direct(tier, expectation) -> bool:
    """The classifier runs for the brand-direct tier only. Everything else
    is compared against a published value and is not on this axis."""
    return tier == 'brand_direct' and (expectation or {}).get('type') == 'brand_mention'


assert set(ea.BRAND_OUTCOMES) == {
    GROUNDED, ECHOED, MISATTRIBUTED, FABRICATED, ACKNOWLEDGED_UNKNOWN,
    ABSENT, UNSCOREABLE,
}, "the classifier and the shared vocabulary must not drift"
