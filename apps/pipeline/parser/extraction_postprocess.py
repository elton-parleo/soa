"""
The deterministic half of Layer 2 extraction.

The division of labour, arrived at by two hand-checks:

    THE MODEL TRANSCRIBES SPANS. THIS CODE CLASSIFIES THEM.

Round one moved `brand_mentioned` out of the model because it got it
wrong in both directions. Round two found the same failure in every other
field where the prompt asked for a judgement rather than a quotation:

  * hedging. The prompt told the model not to record a possibility as a
    claim. It recorded "It's possible that..." as a claim on one run and
    correctly left "It might be a fictional product" out on another — the
    same model, the same kind of answer, within a single run of the
    study. Two rows flipped to `fabricated` on hedges alone.
  * cannot-find. The prompt listed what does and does not count. The
    model filed "Wiggle & Snug does not currently offer a member rewards
    program" — an assertion ABOUT the brand — as a statement that the
    brand was unknown, which turned a false claim into the honest answer.
  * substitution. Asked which other brands the answer offered in place of
    this one, it returned two guesses at alternate spellings the answer
    described nothing about, and a plain acknowledged-unknown was scored
    `misattributed`.
  * currency. Told to use the code, it returned "Rs." on one run and
    "INR" on another for the same answer.

None of those is a transcription failure. Each is the model being asked
to apply a rule, applying it inconsistently, and the inconsistency
landing directly on an outcome. A rule applied in Python is applied the
same way every time, is readable by the person doing the next
hand-check, and can be tested against the rows that motivated it — which
is what the rest of this file is.

What the model is still asked for is spans: the sentence a claim came
from, the sentence that sounds like a cannot-find, the name of a brand it
mentioned. Those it gets right.

Every decision this module makes is recorded in `postprocess` on the
record, so the next hand-check can see what the code did and disagree
with it.
"""
import re
from typing import Optional

from parser.span_segmenter import segment
from soa_shared import expected_answers as ea

# ─── Modality ──────────────────────────────────────────────────────────────
#
# A claim the answer hedged is not a claim the answer made. Matched on the
# verbatim sentence the extractor quotes, so the decision is re-checkable
# against the stored answer by anyone who can read.

HEDGE_MARKERS = (
    'possible', 'possibly', 'likely', 'probably', 'perhaps', 'presumably',
    'might', 'could', 'appears', 'appear to',
    'seems', 'seem to', 'if it', "i'd guess", 'i would guess',
    'i suspect', 'suggests', 'typically', 'usually', 'generally',
)

# 'may' is a hedge and also a month. Required not to be followed by a
# number, so "It may be a store brand" hedges and "The line launched in
# May 2024" is the claim it is. This is the only marker that needs a
# rule rather than a word, which is why it is the only one written as
# one.
_MAY = re.compile(r'\bmay\b(?!\s+\d)')

_WORD = re.compile(r'[^a-z0-9]+')


def _flat(text) -> str:
    """Lowercased with punctuation flattened to spaces, padded, so a
    marker matches on word boundaries rather than inside a longer word.

    Applied to the MARKERS as well as to the text — otherwise "couldn't
    find" never matches a sentence whose apostrophe has been flattened,
    which is a lexicon that silently matches nothing.
    """
    return f" {_WORD.sub(' ', str(text or '').lower()).strip()} "


def _contains(text, markers) -> bool:
    flat = _flat(text)
    return any(_flat(marker).strip() and _flat(marker) in flat for marker in markers)


def is_hedged(sentence) -> bool:
    """Whether this sentence states a possibility rather than a fact."""
    if _contains(sentence, HEDGE_MARKERS):
        return True
    return bool(_MAY.search(str(sentence or '').lower()))


# ─── Cannot-find ───────────────────────────────────────────────────────────
#
# Two lexicons, and the disclaimer one wins. "I don't have real-time
# access to the latest ingredient list" and "without the product in front
# of me" are statements about the shape of our knowledge, not about
# whether this brand exists — and both answers that carried them went on
# to treat the brand as real.

CANNOT_FIND_MARKERS = (
    "couldn't find", 'could not find', "can't find", 'cannot find',
    "haven't been able to find", 'have not been able to find',
    "couldn't verify", 'could not verify', "can't verify", 'cannot verify',
    "couldn't locate", 'could not locate',
    'not familiar', 'no information', 'not a real', 'not a recognized',
    'not a widely recognized', 'not a widely known', 'not widely recognized',
    'does not appear to exist', "doesn't appear to exist",
    'no results', 'turned up nothing', 'unable to find', 'unable to verify',
    'never heard of', 'not aware of',
)

DISCLAIMER_MARKERS = (
    'real time', 'realtime', 'in front of me', 'knowledge cutoff',
    'cut off date', 'cutoff date', 'training data', 'up to date',
    'most recent information', 'browse the web', 'access the internet',
    'live data',
)

# When a sentence filed as a cannot-find turns out to be an assertion, it
# is one — and this is what kind. Keyword order matters: a sentence about
# a rewards programme is a loyalty claim even though it also says where
# something is sold.
_CLAIM_KINDS = (
    ('loyalty', ('reward', 'rewards', 'loyalty', 'tier', 'tiers', 'points',
                 'membership', 'member')),
    ('retail', ('sold', 'sells', 'available', 'stock', 'stocked', 'retailer',
                'store', 'stores', 'exclusive', 'buy')),
    ('ownership', ('owned', 'owns', 'manufactured', 'made by', 'parent',
                   'private label', 'subsidiary')),
)


def looks_unknown(sentence) -> bool:
    """A sentence that says the brand cannot be found, and is not a
    disclaimer about our own reach."""
    if is_disclaimer(sentence):
        return False
    return _contains(sentence, CANNOT_FIND_MARKERS)


def is_disclaimer(sentence) -> bool:
    return _contains(sentence, DISCLAIMER_MARKERS)


def claim_kind(sentence) -> str:
    flat = _flat(sentence)
    for kind, words in _CLAIM_KINDS:
        if any(f' {word} ' in flat for word in words):
            return kind
    return 'other'


# ─── Sizes ─────────────────────────────────────────────────────────────────
#
# A size is how much product is in the pack. The field was catching every
# number with a unit next to it: a baby's weight ("15 lb", attributed to
# "a baby"), a diaper's weight RANGE ("12–18 lb" for Size 2), a
# percentage ("25%"), a duration ("12 hours"), a per-unit price ("30.3 ¢
# per diaper"), and the digit out of "Size 6".
#
# An allowlist rather than a denylist, because the failure is the field
# accepting things nobody enumerated. Weight in pounds is deliberately
# NOT here: every lb value across three samples was a baby's weight or a
# size chart's range, and a product sold by the pound would be better
# missed than a size chart read as a product.
SIZE_UNITS = {
    'oz', 'ounce', 'ounces', 'fl oz', 'floz', 'fluid ounce', 'fluid ounces',
    'ml', 'millilitre', 'millilitres', 'milliliter', 'milliliters',
    'l', 'litre', 'litres', 'liter', 'liters',
    'g', 'gram', 'grams', 'kg', 'kilogram', 'kilograms',
}


# Who a measurement can be ABOUT and still not be a product size. A
# weight in kilograms is a product size when it is a tub and a baby's
# when it is a baby, and the unit cannot tell them apart — "4.5 kg"
# attributed to "newborn sizes" is a size chart.
#
# Matched as "what is left after removing these words", never as "does
# the attribution contain one": "Baby Bum Balm" is a product whose name
# starts with the word baby, and a rule that dropped it would lose a real
# size to catch a fake one.
NON_PRODUCT_WORDS = {
    'a', 'an', 'the', 'your', 'my', 'for', 'of', 'up', 'to', 'and', 'or',
    'baby', 'babies', 'newborn', 'newborns', 'infant', 'infants',
    'toddler', 'toddlers', 'child', 'children', 'kid', 'kids',
    'size', 'sizes', 'range', 'ranges', 'weight', 'weights', 'chart',
}


def names_a_product(attributed) -> bool:
    """Whether the attribution names a thing that is sold, rather than a
    person or a size chart. An empty attribution counts: an answer about
    one product that says "it is 4 oz" has attributed that by context."""
    words = set(_flat(attributed).split())
    if not words:
        return True
    # A bare number is not a product noun either: "weight range for Size
    # 3" leaves nothing but the 3, and a size chart is not a product.
    return any(
        word not in NON_PRODUCT_WORDS and not word.isdigit()
        for word in words
    )


def is_product_size(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    unit = _flat(entry.get('unit')).strip()
    if not unit or unit not in SIZE_UNITS:
        return False
    return names_a_product(entry.get('attributed_product'))


# ─── Codes ─────────────────────────────────────────────────────────────────
#
# A promotion code is a token you type into a box. "10% off" is a
# description of what a code does, and one answer had it in the codes
# list — where it was compared against a published code, could never
# match one, and produced a wrong verdict about a code the answer never
# actually named.
#
# The shape is the whole test: one alphanumeric run, no spaces, no
# percent sign. Codes in the record look like SAVE5 and WELCOME10, and
# nothing that describes a discount looks like that.
_CODE_SHAPE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{1,31}$')


def is_code_shaped(code) -> bool:
    return bool(_CODE_SHAPE.match(str(code or '').strip()))


# ─── Hygiene ───────────────────────────────────────────────────────────────

def _dedupe(items, key):
    seen, out = set(), []
    for item in items or []:
        k = key(item)
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out


def _domain_root(text) -> str:
    """'www.trueshopstore.com/loyalty' -> 'trueshopstore'. Enough to spot
    the brand's own site written as a brand name, and nothing more."""
    bare = str(text or '').strip().lower().lstrip('.')
    bare = bare[4:] if bare.startswith('www.') else bare
    return bare.split('/')[0].split('.')[0]


def _attributed_names(record) -> str:
    """Everything the answer hung a value or a claim on, as one flat
    string to look for a brand name in."""
    parts = []
    for key in ('prices', 'pack_counts', 'gtins', 'member_prices', 'sizes'):
        for item in record.get(key) or []:
            if isinstance(item, dict):
                parts.append(item.get('attributed_product') or '')
    for claim in record.get('brand_claims') or []:
        if isinstance(claim, dict):
            parts.append(claim.get('claim') or '')
            parts.append(claim.get('sentence') or '')
    parts.extend(str(d) for d in record.get('sources_cited') or [])
    return _flat(' '.join(parts))


def attributes_something_to(name, record) -> bool:
    """
    Whether the answer said anything ABOUT this other brand.

    A `closest_match` that describes nothing is not a substitution, it is
    a spelling guess — "e.g. Wiggles & Giggles, Snuggle & Snug". One
    answer offered two of those and was scored `misattributed` for
    describing a brand it never described. A substitution has to carry
    something: a number, a claim, or a citation.
    """
    tokens = set(_flat(name).split())
    if not tokens:
        return False
    haystack = set(_attributed_names(record).split())
    return tokens <= haystack


# ─── The pass ──────────────────────────────────────────────────────────────

def normalize(record: dict, *, answer_text, brand, brand_domain=None) -> dict:
    """
    One raw extraction -> the record that gets stored and compared.

    Mutates and returns `record`. Every step appends to `postprocess`,
    which is stored with the row: the next hand-check reads what the code
    decided, not just what it produced.
    """
    record = dict(record or {})
    notes = []

    # ── brand_mentioned, decided here and never asked ────────────────
    #
    # `brand` empty means FALSE, not true. ea.names_brand answers True
    # with nothing to look for — right for the generator's guard, where a
    # brand is always in hand, and catastrophic here: the value tiers
    # carry a price expectation with no brand on it, so every catalog row
    # in the study recorded brand_mentioned true whatever the answer
    # said. One sample row made it visible; the rest were true by
    # accident.
    record['brand_mentioned'] = bool(
        answer_text and brand and ea.names_brand(answer_text, brand)
    )

    # ── currency ──────────────────────────────────────────────────────
    unknown_currencies = []
    for key in ('prices', 'member_prices'):
        for item in record.get(key) or []:
            if not isinstance(item, dict):
                continue
            if 'currency' not in item:
                # A record from before the field existed. Leaving the key
                # absent is not the same as setting it to None, and
                # inventing it here would rewrite a stored record to say
                # something it never said.
                continue
            code = ea.normalize_currency(item.get('currency'))
            if code and not ea.is_currency_code(code):
                unknown_currencies.append(str(item.get('currency')))
            item['currency'] = code
    if unknown_currencies:
        # Never left as a raw string. A currency nothing can read makes
        # the price comparison meaningless, and calling it a match or a
        # mismatch would both be claims about the assistant made out of
        # our own confusion.
        record['extraction_confident'] = False
        record['extraction_note'] = (
            f"unreadable currency: {', '.join(sorted(set(unknown_currencies)))}"
        )
        notes.append('unscoreable: unreadable currency')

    # ── claims: hedged or asserted ────────────────────────────────────
    claims = []
    for claim in record.get('brand_claims') or []:
        if not isinstance(claim, dict) or not claim.get('claim'):
            continue
        sentence = claim.get('sentence') or claim.get('claim')
        claim['sentence'] = sentence
        # Recorded as what the lexicon thinks, under a name that says so.
        # The labelling pass supplies `modality`, and the classifier
        # reads that; this is the second opinion the two are compared
        # against — see reconcile_modality.
        claim['lexicon_hedged'] = is_hedged(sentence)
        claims.append(claim)
    claims = _dedupe(claims, lambda c: (_flat(c['claim']), _flat(c['sentence'])))
    record['brand_claims'] = claims

    # ── cannot-find: a cross-check, never a rewrite ───────────────────
    #
    # This used to move a statement that failed the lexicon into
    # brand_claims. It fired on six rows of one sample and was right on
    # one: it removed two textbook unknown statements ("I'm having
    # trouble finding any information about a brand called Wiggle &
    # Snug"), it turned a hedged sentence into an asserted claim, and it
    # treated "does not appear to be a real brand" differently from "is
    # not a real or widely recognized brand", which are the same
    # sentence twice.
    #
    # A lexicon is a good signal and a bad adjudicator. It now records
    # what it thinks and changes nothing; the labelling pass decides.
    statement = record.get('brand_unknown_statement')
    if statement:
        record['lexicon_unknown'] = looks_unknown(statement)
        record['lexicon_disclaimer'] = is_disclaimer(statement)

    # ── other brands ──────────────────────────────────────────────────
    others, dropped = [], []
    # ea.normalize_brand_text, not _flat: it expands '&' to 'and', so
    # "Wiggle & Snug" and "wiggle and snug" are one name. _flat drops the
    # ampersand entirely and the two stop matching.
    brand_tokens = set(ea.normalize_brand_text(brand).split())
    own_root = _domain_root(brand_domain)
    for entry in record.get('other_brands_named') or []:
        if not isinstance(entry, dict) or not entry.get('name'):
            continue
        name = entry['name']
        tokens = set(ea.normalize_brand_text(name).split())
        # The WHOLE brand, not a token of it. "Wiggle" is a UK sports
        # retailer that one answer explicitly distinguishes from Wiggle &
        # Snug, and dropping it as "is the brand" deleted the one thing
        # that answer was doing.
        if tokens and tokens == brand_tokens:
            dropped.append(f'{name} (is the brand)')
            continue
        if own_root and own_root in _flat(name):
            dropped.append(f'{name} (is the brand\'s own site)')
            continue
        others.append(entry)
    record['other_brands_named'] = _dedupe(others, lambda e: _flat(e['name']))
    if dropped:
        notes.append('dropped other brands: ' + '; '.join(dropped))

    # ── retailers ─────────────────────────────────────────────────────
    #
    # A retailer the answer got a price FROM is a source, not a
    # suggestion, and counting it twice would turn a cited answer into an
    # unsourced availability claim.
    sources = {_domain_root(d) for d in record.get('sources_cited') or []}

    # Seed from retailer_mentions when the record already has them.
    # recommended_retailers holds only the ones a previous pass called a
    # recommendation, so rebuilding from it drops every retailer that was
    # a source or showed the product unavailable — which made running
    # this over its own output lose data, and made the golden set of an
    # already-processed sample unreachable.
    existing = record.get('retailer_mentions')
    if existing:
        incoming = [(m.get('name'), m.get('role')) for m in existing
                    if isinstance(m, dict) and m.get('name')]
    else:
        incoming = [(name, None) for name in record.get('recommended_retailers') or []]

    mentioned, demoted = [], []
    for retailer, role in incoming:
        if not retailer:
            continue
        if role and role != 'recommendation':
            # A role an earlier pass established on evidence this pass
            # cannot see. Kept.
            mentioned.append({'name': retailer, 'role': role})
            continue
        if _domain_root(retailer) in sources or _flat(retailer).strip() in sources:
            # A retailer a price came FROM is a source. Recorded with
            # that role rather than deleted: the row should say what
            # every retailer the answer named was, and a name that
            # vanishes here is a name the labelling pass never sees and
            # nobody can check afterwards.
            demoted.append(str(retailer))
            mentioned.append({'name': retailer, 'role': 'source'})
            continue
        mentioned.append({'name': retailer, 'role': role})
    record['retailer_mentions'] = _dedupe(mentioned, lambda m: _flat(m['name']))
    record['recommended_retailers'] = [
        m['name'] for m in record['retailer_mentions']
        if m['role'] in (None, 'recommendation')
    ]
    if demoted:
        notes.append('retailers that were sources: ' + ', '.join(demoted))

    # ── sizes ─────────────────────────────────────────────────────────
    sizes, not_sizes = [], []
    for entry in record.get('sizes') or []:
        (sizes if is_product_size(entry) else not_sizes).append(entry)
    record['sizes'] = _dedupe(
        sizes,
        lambda e: (_flat(e.get('value')), _flat(e.get('unit')),
                   _flat(e.get('attributed_product'))),
    )
    if not_sizes:
        notes.append(
            'not product sizes: '
            + ', '.join(
                f"{e.get('value')} {e.get('unit') or ''}".strip()
                for e in not_sizes if isinstance(e, dict)
            )
        )

    # ── the remaining lists ───────────────────────────────────────────
    for key in ('prices', 'member_prices', 'pack_counts', 'gtins'):
        record[key] = _dedupe(
            [e for e in record.get(key) or [] if isinstance(e, dict)],
            lambda e: tuple(sorted((k, _flat(v)) for k, v in e.items())),
        )
    # A member price with no amount is not a member price. "Member
    # pricing on selected products" says a programme exists, not what
    # anybody pays.
    record['member_prices'] = [
        e for e in record['member_prices']
        if ea.normalize_money(e.get('amount')) is not None
    ]
    record['pack_counts'] = [
        e for e in record['pack_counts'] if e.get('value') is not None
    ]

    # ── codes ─────────────────────────────────────────────────────────
    codes, not_codes = [], []
    for entry in record.get('codes') or []:
        if not isinstance(entry, dict):
            continue
        (codes if is_code_shaped(entry.get('code')) else not_codes).append(entry)
    record['codes'] = _dedupe(
        codes, lambda c: (_flat(c.get('code')), _flat(c.get('value_kind')),
                          _flat(c.get('value'))))
    if not_codes:
        notes.append(
            'not codes: '
            + ', '.join(str(c.get('code')) for c in not_codes))

    record['sources_cited'] = _dedupe(record.get('sources_cited') or [], _flat)
    # Cased and stripped, NOT punctuation-flattened: 'Member' and
    # 'Member+' are two tiers, and a key that drops the plus merges the
    # record's whole programme into one name.
    record['loyalty_tiers_named'] = _dedupe(
        [t for t in record.get('loyalty_tiers_named') or [] if t],
        lambda t: str(t).strip().lower(),
    )

    record['postprocess'] = notes
    return record


def apply_labels(record: dict, labels: dict, *, answer_text=None,
                 brand=None) -> dict:
    """
    The labeller's answer, merged onto the transcription.

    Matched on SPAN ID. The spans were cut by span_segmenter before the
    call, so the text a label is attached to is ours, verbatim, and the
    labeller could not have merged two of them or run one past a clause
    break — which is what the previous three arrangements each did.

    brand_claims and brand_unknown_statement are DERIVED here, from the
    spans, rather than taken from the transcription. The transcription's
    own versions of them are kept as a cross-check: where the two
    disagree, the row says so.
    """
    record = dict(record or {})
    labels = labels or {}
    notes = list(record.get('postprocess') or [])

    spans = segment(answer_text) if answer_text else []
    by_id = {span['id']: span for span in spans}
    labelled = {}
    unknown_ids = []
    for item in labels.get('spans') or []:
        if not isinstance(item, dict):
            continue
        span_id = item.get('span_id')
        if span_id not in by_id:
            # A label for a span we never sent. Recorded rather than
            # applied: the id is the only handle, and one that does not
            # resolve is a label attached to nothing.
            unknown_ids.append(span_id)
            continue
        labelled[span_id] = item
    if unknown_ids:
        notes.append(f'labels for unknown span ids: {unknown_ids}')

    if spans:
        claims, statement = [], None
        for span_id, span in sorted(by_id.items()):
            label = labelled.get(span_id)
            if not label:
                continue
            kind, modality = label.get('kind'), label.get('modality')
            if kind == 'unknown_statement' and statement is None:
                statement = span['text']
            elif kind == 'assertion':
                lexicon = is_hedged(span['text']) or span.get('inherits_hedge', False)
                claims.append({
                    'claim': span['text'], 'sentence': span['text'],
                    'span_id': span_id, 'kind': kind, 'modality': modality,
                    'claim_kind': claim_kind(span['text']),
                    'lexicon_hedged': lexicon,
                    'inherits_hedge': span.get('inherits_hedge', False),
                    'effective_modality': effective_modality(modality, lexicon),
                })
        # The transcription's own reading, kept beside the spans so a
        # disagreement is visible instead of being resolved by whichever
        # field is read first.
        record['transcribed_unknown_statement'] = record.get('brand_unknown_statement')
        record['brand_unknown_statement'] = statement
        record['brand_claims'] = claims

    record['spans'] = spans
    record['span_labels'] = [
        {'span_id': i, 'text': by_id[i]['text'],
         'kind': labelled[i].get('kind'), 'modality': labelled[i].get('modality')}
        for i in sorted(labelled) if i in by_id
    ]

    # ── other brands ──────────────────────────────────────────────────
    relations = {
        _flat(item['name']): item.get('relation')
        for item in labels.get('other_brands') or []
        if isinstance(item, dict) and item.get('name')
    }
    kept = []
    for entry in record.get('other_brands_named') or []:
        if not isinstance(entry, dict) or not entry.get('name'):
            continue
        entry['relation'] = relations.get(_flat(entry['name']))
        if entry['relation'] == 'not_a_brand':
            notes.append(f"not a brand: {entry['name']}")
            continue
        kept.append(entry)
    record['other_brands_named'] = kept

    # ── retailers ─────────────────────────────────────────────────────
    roles = {
        _flat(item['name']): item.get('role')
        for item in labels.get('retailers') or []
        if isinstance(item, dict) and item.get('name')
    }
    mentions = record.get('retailer_mentions')
    if mentions is None:
        mentions = [{'name': name, 'role': None}
                    for name in record.get('recommended_retailers') or []]
    record['retailer_mentions'] = [
        {'name': m['name'], 'role': m.get('role') or roles.get(_flat(m['name']))}
        for m in mentions
    ]
    record['recommended_retailers'] = [
        m['name'] for m in record['retailer_mentions']
        if m['role'] == 'recommendation'
    ]

    record['hedged_unsourced'] = hedged_unsourced(record)
    review = needs_review(record)
    review.extend(coverage_gaps(record, brand=brand))
    if review:
        notes.append(f'{len(review)} span(s) need review')
    record['needs_review'] = review
    record['postprocess'] = notes
    return record


def coverage_gaps(record, *, brand=None) -> list:
    """
    Every span naming the brand that came back without a label, plus the
    places the transcription and the spans disagree.

    A span the labeller declined says "none" and is fine. A span it never
    mentioned is the failure this exists for: one answer's entire
    headline — "It appears that Wiggle & Snug Bum Balm 4 oz has been
    discontinued" — reached neither the claims nor the unknown statement
    on the previous arrangement, and nothing anywhere recorded that it
    had gone missing.

    The transcription mismatch is here rather than in a note for the same
    reason. A cannot-find statement the transcriber read one way and the
    spans read another is a disagreement about what the answer said, and
    that belongs in front of a person.
    """
    gaps = []
    labelled = {item['span_id'] for item in record.get('span_labels') or []}
    for span in record.get('spans') or []:
        if span['id'] in labelled:
            continue
        if brand and not ea.names_brand(span['text'], brand):
            continue
        if not brand:
            continue
        gaps.append({
            'reason': 'a span naming the brand came back unlabelled',
            'span_id': span['id'], 'text': span['text'],
        })

    transcribed = record.get('transcribed_unknown_statement')
    derived = record.get('brand_unknown_statement')
    # One containing the other is the same statement read to a different
    # boundary, which is the segmenter's job and not a disagreement about
    # what the answer said. Only a genuinely different statement — or
    # none at all on one side — is a finding.
    a, b = _flat(transcribed).strip(), _flat(derived or '').strip()
    same = bool(a) and bool(b) and (a in b or b in a)
    if transcribed and not same:
        gaps.append({
            'reason': ('the transcription read a cannot-find statement the '
                       'spans did not'),
            'transcribed': transcribed, 'from_spans': derived,
        })
    return gaps


def effective_modality(label_modality, lexicon_hedged) -> str:
    """
    What the span counts as for scoring when the two readings differ.

    HEDGED. The same fail-safe as "an unlabelled span is not a claim":
    where the evidence is disputed, the pipeline takes the reading that
    cannot manufacture a finding. A hedge scored as an assertion invents
    a fabrication out of a sentence the answer did not commit to; an
    assertion scored as a hedge loses a finding that a human reading the
    needs_review queue will still see.

    Those are not symmetric costs. One of them puts a false accusation in
    a report; the other leaves a true one for a person to confirm.

    The disagreement is surfaced either way — this decides only what the
    classifier does while it waits.
    """
    if label_modality in ('hedged', 'conditional'):
        return label_modality
    if lexicon_hedged:
        return 'hedged'
    return label_modality or 'hedged'


def hedged_unsourced(record) -> list:
    """
    Claims this answer made, hedged, with nothing behind them.

    A disputed span lands here rather than in `fabricated`: the answer
    said something specific about the brand, did not commit to it, and
    cited nothing. That is a real finding and a different one from
    inventing a fact, and it is worth being able to count separately
    rather than folding into "named the brand and said nothing
    checkable".
    """
    if record.get('sources_cited'):
        return []
    return [
        claim for claim in record.get('brand_claims') or []
        if isinstance(claim, dict)
        and claim.get('kind') == 'assertion'
        and claim.get('effective_modality') in ('hedged', 'conditional')
    ]


def asserted_claims(record) -> list:
    """
    The claims the answer actually made, by the LABEL — never by the
    lexicon.

    A claim counts when its label says kind=assertion and its EFFECTIVE
    modality is asserted — which means the label said asserted and the
    lexicon did not disagree. An unlabelled record yields nothing rather
    than everything: a claim nobody has classified is not a claim we can
    act on, and falling back to "treat it as asserted" is how a hedge
    became a fabrication three samples running.
    """
    return [
        claim for claim in record.get('brand_claims') or []
        if isinstance(claim, dict)
        and claim.get('kind') == 'assertion'
        and claim.get('effective_modality', claim.get('modality')) == 'asserted'
    ]


def needs_review(record) -> list:
    """
    Where the lexicon and the label disagree about modality.

    Surfaced, never silently resolved. The lexicon is a regular
    expression and the labeller is a model, and when a sentence looks
    hedged to one and asserted to the other, the honest output is a flag
    for a human — not a pick made by whichever happens to be consulted
    first.
    """
    out = []
    for claim in record.get('brand_claims') or []:
        if not isinstance(claim, dict) or 'modality' not in claim:
            continue
        lexicon = claim.get('lexicon_hedged')
        if lexicon is None:
            continue
        label_hedged = claim.get('modality') in ('hedged', 'conditional')
        if bool(lexicon) != label_hedged:
            out.append({
                'sentence': claim.get('sentence'),
                'lexicon': 'hedged' if lexicon else 'asserted',
                'label': claim.get('modality'),
            })
    return out
