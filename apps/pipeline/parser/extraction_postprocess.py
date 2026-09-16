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


def is_product_size(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    unit = _flat(entry.get('unit')).strip()
    return bool(unit) and unit in SIZE_UNITS


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
    retailers, demoted = [], []
    for retailer in record.get('recommended_retailers') or []:
        if not retailer:
            continue
        if _domain_root(retailer) in sources or _flat(retailer).strip() in sources:
            demoted.append(str(retailer))
            continue
        retailers.append(retailer)
    record['recommended_retailers'] = _dedupe(retailers, _flat)
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


def apply_labels(record: dict, labels: dict) -> dict:
    """
    The labeller's answer, merged onto the transcription.

    Matched on the sentence text, normalised, because that is the only
    key both sides share — the labeller is handed spans and returns them
    with labels attached, and a span it renamed is a span nobody can
    match. Anything it did not label keeps no label at all, which
    asserted_claims reads as "not a claim".

    A sentence labelled `unknown_statement` becomes the record's
    brand_unknown_statement and leaves brand_claims. A sentence labelled
    `disclaimer` or `instruction` leaves brand_claims too and becomes
    neither: an instruction to check the packaging is not a claim about
    the brand, and one sample scored `fabricated` on exactly that.
    """
    record = dict(record or {})
    labels = labels or {}
    notes = list(record.get('postprocess') or [])

    by_sentence = {}
    for item in labels.get('brand_sentences') or []:
        if isinstance(item, dict) and item.get('sentence'):
            by_sentence[_flat(item['sentence'])] = item

    # ── the unknown-statement candidate ───────────────────────────────
    statement = record.get('brand_unknown_statement')
    promoted = []
    if statement:
        label = by_sentence.get(_flat(statement))
        kind = (label or {}).get('kind')
        if kind == 'unknown_statement':
            pass                                   # stays exactly where it is
        elif kind in ('assertion',):
            record['brand_unknown_statement'] = None
            promoted.append({
                'claim': statement, 'sentence': statement,
                'kind': 'assertion', 'modality': (label or {}).get('modality'),
                'lexicon_hedged': is_hedged(statement),
                'claim_kind': claim_kind(statement),
            })
            notes.append('unknown-statement span labelled an assertion')
        elif kind in ('disclaimer', 'instruction'):
            record['brand_unknown_statement'] = None
            notes.append(f'unknown-statement span labelled a {kind}')
        # No label at all: left alone. An unlabelled candidate is not
        # evidence of anything, and moving it on a failed call is how the
        # last two rounds went wrong.

    # ── the claims ────────────────────────────────────────────────────
    claims, unknown_from_claims = [], None
    for claim in record.get('brand_claims') or []:
        if not isinstance(claim, dict):
            continue
        label = by_sentence.get(_flat(claim.get('sentence') or claim.get('claim')))
        if not label:
            claims.append(claim)
            continue
        kind, modality = label.get('kind'), label.get('modality')
        if kind == 'unknown_statement':
            # The labeller found the cannot-find sentence in the claims
            # list. Two samples had it there.
            if not record.get('brand_unknown_statement'):
                unknown_from_claims = claim.get('sentence') or claim.get('claim')
            notes.append('a claim span was labelled an unknown statement')
            continue
        if kind in ('disclaimer', 'instruction'):
            notes.append(f'a claim span was labelled a {kind}')
            continue
        claims.append({**claim, 'kind': kind, 'modality': modality,
                       'claim_kind': claim.get('kind') or claim_kind(
                           claim.get('sentence') or claim.get('claim'))})

    if unknown_from_claims:
        record['brand_unknown_statement'] = unknown_from_claims
    record['brand_claims'] = claims + promoted

    # ── other brands ──────────────────────────────────────────────────
    relations = {
        _flat(item['name']): item.get('relation')
        for item in labels.get('other_brands') or []
        if isinstance(item, dict) and item.get('name')
    }
    for entry in record.get('other_brands_named') or []:
        if isinstance(entry, dict) and entry.get('name'):
            entry['relation'] = relations.get(_flat(entry['name']))

    # ── retailers ─────────────────────────────────────────────────────
    roles = {
        _flat(item['name']): item.get('role')
        for item in labels.get('retailers') or []
        if isinstance(item, dict) and item.get('name')
    }
    record['retailer_mentions'] = [
        {'name': name, 'role': roles.get(_flat(name))}
        for name in record.get('recommended_retailers') or []
    ]
    # The old flat list keeps only what the labeller called a
    # recommendation. "Amazon listings show it currently unavailable" is
    # the opposite of one, and it drove a fabricated verdict.
    record['recommended_retailers'] = [
        m['name'] for m in record['retailer_mentions']
        if m['role'] == 'recommendation'
    ]

    disagreements = needs_review(record)
    if disagreements:
        notes.append(
            f'{len(disagreements)} sentence(s) where the lexicon and the '
            f'label disagree on modality'
        )
    record['needs_review'] = disagreements
    record['postprocess'] = notes
    return record


def asserted_claims(record) -> list:
    """
    The claims the answer actually made, by the LABEL — never by the
    lexicon.

    A claim counts when its label says kind=assertion and
    modality=asserted. An unlabelled record yields nothing rather than
    everything: a claim nobody has classified is not a claim we can act
    on, and falling back to "treat it as asserted" is how a hedge became
    a fabrication three samples running.
    """
    return [
        claim for claim in record.get('brand_claims') or []
        if isinstance(claim, dict)
        and claim.get('kind') == 'assertion'
        and claim.get('modality') == 'asserted'
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
