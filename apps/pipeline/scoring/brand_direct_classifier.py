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

from parser import extraction_postprocess as pp
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


# What the labelling pass calls a substitution. One value of four, and
# the only one that means "the answer decided the asker meant somebody
# else AND described them". A spelling guess describes nothing — three
# rows were scored misattributed for describing a brand they never
# described — and a comparison or a citation is not a substitution at
# all.
DESCRIBED = 'closest_match_described'


def _is_substitution(entry) -> bool:
    """`entry` is an other_brands_named row. The label decides."""
    if isinstance(entry, dict) and entry.get('relation') is not None:
        return entry['relation'] == DESCRIBED
    # No label: the labelling call failed or predates this. Fall back to
    # the old free-text field rather than guessing — and never to "yes".
    presented = str((entry or {}).get('presented_as') or '').strip().lower()
    if not presented or presented in ('comparison', 'recommendation', 'source'):
        return False
    if presented == SUBSTITUTION:
        return True
    return any(phrase in presented for phrase in LEGACY_SUBSTITUTION_PHRASES)


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
        # Route two: offered as the thing the asker must have meant, and
        # described.
        if _is_substitution(entry):
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

    For the same reason a stated "tier" that IS the programme's name is
    not a tier claim at all, and is left out before comparing: run 12972
    (cycle 229) said the brand has "a 'Member Rewards' program", the
    extractor listed Member Rewards as a tier, and the answer was scored
    fabricated for naming a tier the record does not publish.
    """
    published = {_norm(t) for t in facts.get('tier_names') or [] if t}
    stated = [t for t in extraction.get('loyalty_tiers_named') or []
              if t and not is_program_name(t, facts)]
    if not published or not stated:
        return

    unknown = [t for t in stated if _norm(t) not in published]
    if len(unknown) == len(stated):
        yield {
            'claim': ', '.join(stated),
            'why': 'names tiers the record does not publish',
        }


def is_program_name(name, facts) -> bool:
    """A stated tier name equal to the record's programme name."""
    program = _norm((facts or {}).get('program_name'))
    return bool(program) and _norm(name) == program


def own_domains(facts, expectation=None) -> list:
    """The merchant's own sites: the record's own_domains, else its one
    domain, else the expectation's."""
    facts = facts or {}
    listed = [d for d in facts.get('own_domains') or [] if d]
    if not listed and facts.get('domain'):
        listed = [facts['domain']]
    domain = (expectation or {}).get('domain')
    if domain and _norm(domain) not in {_norm(d) for d in listed}:
        listed.append(domain)
    return listed


def ours(facts, expectation=None) -> list:
    """
    2D: every site that is the brand's own for the grounded checks: the
    merchant's own (own_domains), then every own domain of every merchant
    in its tenant (`tenant_own_domains`, read once per cycle by
    expectation_scorer.TenantDomainsCache). A store and its brand site can
    be two merchants of one tenant (W&S: trueshopstore.com,
    wiggleandsnug.com); an answer grounded on either is grounded.

    Only the two grounded checks in classify_with_code read this. The
    ownership and no-source checks in contradicted_claims keep the
    merchant's own list, so this rule can move a row from echoed to
    grounded and nothing else.
    """
    listed = own_domains(facts, expectation)
    seen = {_norm(d) for d in listed}
    for domain in (facts or {}).get('tenant_own_domains') or []:
        if domain and _norm(domain) not in seen:
            listed.append(domain)
            seen.add(_norm(domain))
    return listed


def grounding_domains(facts, expectation=None) -> set:
    """Where a source grounds a brand claim: the merchant's own sites and
    its listed retailers."""
    return {_norm(d) for d in own_domains(facts, expectation)
            + list((facts or {}).get('retailer_list') or []) if d}


#: The shorter of a claim and a support segment must be at least this long
#: for one containing the other to count: "Yes" inside every segment is
#: not coverage.
_MIN_COVERAGE_CHARS = 12


def _covers(segment, claim) -> bool:
    a, b = _norm(segment), _norm(claim)
    if not a or not b or min(len(a), len(b)) < _MIN_COVERAGE_CHARS:
        return False
    return b in a or a in b


def support_domains(claim_text, grounding) -> list:
    """
    The source domains behind a claim, from the platform's grounding
    supports (runners/grounding.py): every support whose segment contains
    the claim, or is contained by it, and the domain of each source it
    names. Text, not offsets: Gemini counts offsets in UTF-8 bytes and the
    extractor quotes characters, and the quote is what both agree on.
    A source with no known domain (an unresolved redirect) grounds nothing.
    """
    grounding = grounding if isinstance(grounding, dict) else {}
    sources = grounding.get('sources') or []
    out = []
    for support in grounding.get('supports') or []:
        if not _covers(support.get('text'), claim_text):
            continue
        for index in support.get('sources') or []:
            if isinstance(index, int) and 0 <= index < len(sources):
                domain = (sources[index] or {}).get('domain')
                if domain and domain not in out:
                    out.append(domain)
    return out


def grounded_by(claim_text, grounding, allowed) -> Optional[str]:
    """The first merchant domain (own or listed retailer) a grounding
    support for this claim resolves to, or None."""
    for domain in support_domains(claim_text, grounding):
        if _norm(domain) in allowed:
            return domain
    return None


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
    # Only what the labeller called a recommendation. A retailer named
    # as where a price was found is a source, and one named as showing
    # the product unavailable is the opposite of a recommendation —
    # "Amazon listings show it currently unavailable" drove a fabricated
    # verdict reading "told the reader to buy it at Amazon".
    mentions = extraction.get('retailer_mentions')
    if mentions is not None:
        retailers = [
            m['name'] for m in mentions
            if isinstance(m, dict) and m.get('role') == 'recommendation' and m.get('name')
        ]
    else:
        retailers = [r for r in extraction.get('recommended_retailers') or [] if r]
    if not retailers:
        return None
    if extraction.get('sources_cited') or extraction.get('brand_unknown_statement'):
        return None
    return {
        'claim': f"told the reader to buy it at {', '.join(retailers)}",
        'why': 'where to buy, stated with no source',
    }


def contradicted_claims(extraction, brand_facts=None, *, grounding=None,
                        expectation=None) -> list:
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
    # Hedged claims are recorded and are not claims. The modality
    # decision is made once, deterministically, in
    # parser/extraction_postprocess — not here and not by the model.
    claims = [
        claim for claim in pp.asserted_claims(extraction)
        if claim.get('claim')
    ]

    # Sourced in the text (any citation, as before), or, claim by claim,
    # grounded by a platform support resolving to one of the merchant's
    # own sites or listed retailers.
    sourced = bool(extraction.get('sources_cited'))
    allowed = grounding_domains(facts, expectation)
    titles = {_norm(t) for t in facts.get('product_titles') or [] if t}
    own = {_norm(d) for d in own_domains(facts)}

    found = list(_tier_contradictions(extraction, facts))
    availability = _recommended_without_source(extraction)
    if availability:
        found.append(availability)
    for claim in claims:
        # claim_kind, not kind: the labelling pass owns `kind` (what sort
        # of sentence this is) and the transcription owns `claim_kind`
        # (what the claim is about). Reading the wrong one here would
        # check every assertion against the loyalty rule.
        kind = (claim.get('claim_kind') or claim.get('kind') or 'other').lower()
        text = claim['claim']
        words = _tokens(text)

        if kind == 'ownership' and own:
            # A claim that names a DIFFERENT domain as the brand's own.
            # Run 10663 called wiggleandsnug.com "their official website";
            # the record says trueshopstore.com. Matched on the domain in
            # the claim rather than on words like "official", because the
            # phrasing varies and the domain does not.
            claimed = _DOMAIN.findall(str(text))
            if claimed and not any(_norm(d) in own for d in claimed):
                found.append({
                    'claim': text,
                    'why': f"the record's own domains are {', '.join(own_domains(facts))}",
                })
                continue

        if kind == 'availability' and titles:
            # "Discontinued" about something the record is publishing now.
            if words & {'discontinued', 'unavailable', 'no', 'not'}:
                if any(set(title.split()) & words for title in titles if title):
                    found.append({'claim': text, 'why': 'the record publishes this product now'})
                    continue

        if not sourced and not grounded_by(text, grounding, allowed):
            found.append({'claim': text, 'why': 'stated with no source'})

    return found


#: Reason codes for the rules that decide a brand-direct outcome on what
#: they newly read (the rescore names them; see scripts/rescore_cycle.py).
CODE_GROUNDING_SUPPORT = 'grounding_support'
CODE_OWN_DOMAINS = 'own_domains'
CODE_TENANT_OWN_DOMAINS = 'tenant_own_domains'
CODE_PROGRAM_NAME = 'program_name_not_tier'


def classify(extraction, expectation, *, brand_facts=None, grounding=None) -> tuple:
    """(assessment, reason). See classify_with_code."""
    return classify_with_code(extraction, expectation, brand_facts=brand_facts,
                              grounding=grounding)[:2]


def classify_with_code(extraction, expectation, *, brand_facts=None, grounding=None) -> tuple:
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
      grounded             it cited one of the brand's own domains, or a
                           claim it asserted is backed by a grounding
                           support whose source is one of them or a
                           listed retailer. 2D: "own" is every own
                           domain of every merchant in the tenant (ours).
      echoed               it named the brand. Nothing else is checkable —
                           which is exactly what the old `exact` meant.
    """
    extraction = extraction or {}

    if not extraction.get('extraction_confident', True):
        return UNSCOREABLE, extraction.get('extraction_note') or 'the answer could not be read', None

    brand = (expectation or {}).get('brand')
    if not extraction.get('brand_mentioned'):
        return ABSENT, f"the answer did not name {brand}", None

    other = misattributed_to(extraction)
    if other:
        return MISATTRIBUTED, f"named {brand} but described {other}", None

    facts = brand_facts or {}
    contradicted = contradicted_claims(extraction, facts, grounding=grounding,
                                       expectation=expectation)
    if contradicted:
        first = contradicted[0]
        return FABRICATED, f"{first['claim']!r} — {first['why']}", None
    # Rule 4 decided it when the programme-name "tier" was the only
    # contradiction: with it counted, the answer would be fabricated.
    program_rule = bool(list(_tier_contradictions(
        extraction, {**facts, 'program_name': None}))) and \
        not list(_tier_contradictions(extraction, facts))
    program_code = CODE_PROGRAM_NAME if program_rule else None

    unknown = extraction.get('brand_unknown_statement')
    if unknown:
        return ACKNOWLEDGED_UNKNOWN, f"said it could not find {brand}: {unknown!r}", program_code

    own = {_norm(d) for d in own_domains(facts, expectation)}
    cited = {_norm(s) for s in extraction.get('sources_cited') or []}
    for domain in ours(facts, expectation):
        if _norm(domain) in cited:
            legacy = _norm((expectation or {}).get('domain') or facts.get('domain'))
            if _norm(domain) not in own:
                return GROUNDED, f"cited {domain}, an own domain of another merchant in the tenant", \
                    program_code or CODE_TENANT_OWN_DOMAINS
            return GROUNDED, f"cited {domain}", \
                program_code or (None if _norm(domain) == legacy else CODE_OWN_DOMAINS)

    # 2D: a support at any of the tenant's own sites grounds it too
    allowed = grounding_domains(facts, expectation) | {_norm(d) for d in ours(facts, expectation)}
    for claim in pp.asserted_claims(extraction):
        domain = grounded_by(claim.get('claim'), grounding, allowed)
        if domain:
            return GROUNDED, (f"{claim['claim']!r} — grounded by a source at {domain} "
                              f"(platform grounding support)"), CODE_GROUNDING_SUPPORT

    return ECHOED, f"named {brand}, with nothing checkable behind it", program_code


def is_brand_direct(tier, expectation) -> bool:
    """The classifier runs for the brand-direct tier only. Everything else
    is compared against a published value and is not on this axis."""
    return tier == 'brand_direct' and (expectation or {}).get('type') == 'brand_mention'


assert set(ea.BRAND_OUTCOMES) == {
    GROUNDED, ECHOED, MISATTRIBUTED, FABRICATED, ACKNOWLEDGED_UNKNOWN,
    ABSENT, UNSCOREABLE,
}, "the classifier and the shared vocabulary must not drift"
