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
    record['brand_mentioned'] = bool(
        answer_text and ea.names_brand(answer_text, brand)
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
        claim['hedged'] = is_hedged(sentence)
        claims.append(claim)
    claims = _dedupe(claims, lambda c: _flat(c['claim']))
    hedged = sum(1 for c in claims if c['hedged'])
    if hedged:
        notes.append(f'{hedged} claim(s) hedged, not counted as asserted')
    record['brand_claims'] = claims

    # ── cannot-find, or an assertion wearing its clothes ──────────────
    statement = record.get('brand_unknown_statement')
    if statement and not looks_unknown(statement):
        record['brand_unknown_statement'] = None
        if is_disclaimer(statement):
            notes.append('unknown statement was a disclaimer about our reach')
        else:
            # An assertion about the brand, filed in the wrong place. It
            # is still an assertion, and dropping it would lose the
            # finding entirely — row 26 said the brand runs no rewards
            # programme, which is false and is exactly the kind of thing
            # this tier exists to catch.
            record['brand_claims'].append({
                'claim': statement,
                'sentence': statement,
                'kind': claim_kind(statement),
                'hedged': is_hedged(statement),
            })
            notes.append('unknown statement was an assertion, moved to claims')

    # ── other brands ──────────────────────────────────────────────────
    others, dropped = [], []
    brand_tokens = set(_flat(brand).split())
    own_root = _domain_root(brand_domain)
    for entry in record.get('other_brands_named') or []:
        if not isinstance(entry, dict) or not entry.get('name'):
            continue
        name = entry['name']
        tokens = set(_flat(name).split())
        if tokens and tokens <= brand_tokens:
            dropped.append(f'{name} (is the brand)')
            continue
        if own_root and own_root in _flat(name):
            dropped.append(f'{name} (is the brand\'s own site)')
            continue
        if entry.get('presented_as') == 'closest_match' and not attributes_something_to(name, record):
            dropped.append(f'{name} (offered as a spelling, describes nothing)')
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


def asserted_claims(record) -> list:
    """The claims the answer actually made. Hedged ones are recorded and
    are not claims."""
    return [
        claim for claim in record.get('brand_claims') or []
        if isinstance(claim, dict) and not claim.get('hedged')
    ]
