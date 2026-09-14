"""
The two deterministic checks a brand-direct question has to pass.

Both exist because the tier's whole premise is a question the model
wrote, and the first real brand-mode study (C80512) showed what that
premise costs when nothing checks the output: all twelve generated
questions omitted the brand name, which made their brand_mention
expectation unmeetable by construction. Every one of them would have
scored `absent` against an assistant that answered perfectly.

A prompt instruction is the fix for that in the ordinary case and is not
a guarantee in any case. These functions are the guarantee. They are
deterministic on purpose — a model checking a model's work has the same
failure mode twice, and the property being checked here ("does this
string contain that string") does not need judgement.

Neither function rewrites anything. A question that fails is rejected and
the slot is regenerated; if the retries run out, the tier reports a
shortfall. Admitting a question the tier cannot score, to hit a count, is
the one outcome worth less than admitting fewer questions.
"""
import re
from typing import Iterable, List, Optional, Set, Tuple

BRAND_MISSING = 'does not name the brand'
INTENT_DUPLICATE = 'restates a question the catalog tier already asks'

_NOISE = re.compile(r'[^a-z0-9]+')

# 'Wiggle & Snug' and 'Wiggle and Snug' are the same brand typed two
# ways, and a shopper types both. Tolerating that is not the same as
# tolerating a partial name: 'Wiggle' alone still fails, because a
# question that names half a brand is a question about something else.
_AMPERSAND = re.compile(r'\s*&\s*')


def _normalize(text) -> str:
    """Lowercased, &-expanded, punctuation-flattened, single-spaced.

    Applied to BOTH sides of every comparison, so the tolerance it grants
    is symmetric — never a rule that reads one way for the brand and
    another for the question.
    """
    lowered = _AMPERSAND.sub(' and ', str(text or '').lower())
    return _NOISE.sub(' ', lowered).strip()


def _tokens(text) -> Set[str]:
    return {t for t in _normalize(text).split() if t}


def names_brand(text, brand) -> bool:
    """
    Whether the question names the brand.

    Substring on the normalized forms, so 'Wiggle & Snug', 'wiggle and
    snug' and 'Wiggle  &  Snug' all pass and 'Wiggle' does not. Word
    boundaries are enforced by padding both sides with spaces: without
    that, a brand called 'Bum' would count itself named by the word
    'album'.
    """
    brand_text = _normalize(brand)
    if not brand_text:
        # No brand to require. The caller (generate_brand_direct) refuses
        # to run without one, so reaching here means a different caller
        # asked a question this function cannot answer — and answering
        # 'no' would reject every row it is handed.
        return True
    return f' {brand_text} ' in f' {_normalize(text)} '


# ─── Intent ────────────────────────────────────────────────────────────────
#
# The second failure this guards is subtler than a missing brand and
# harder to see in a list of fifty questions: a brand-direct question
# that is a catalog-accuracy price question with the words moved around.
# It reads as a different question, it is stamped with a different tier
# and a different expectation, and it measures the same thing twice —
# once scored against a published price and once against a brand mention.
#
# The comparison is therefore on INTENT, not on text. Two parts:
# what is being asked FOR (the ask kind) and what is being asked ABOUT
# (the content tokens). A duplicate has to match on both; matching on
# content alone would reject 'where can I buy the Size 3 small pack',
# which is exactly the kind of question this tier exists to ask.

# The ask kinds are the catalog tiers' own expectations, and no others.
# A brand-direct question that asks something the catalog tiers never
# ask cannot be duplicating one of them, whatever words it shares.
_ASK_SIGNALS = {
    'price':        {'price', 'prices', 'priced', 'pricing', 'cost', 'costs',
                     'msrp', 'rrp', 'much', 'expensive', 'cheaper'},
    'code':         {'code', 'codes', 'coupon', 'coupons', 'promo', 'voucher',
                     'discount'},
    'member_price': {'member', 'members', 'membership'},
    'points':       {'points', 'reward', 'rewards', 'loyalty'},
}

# Removed before the content comparison because they carry grammar, not
# subject. Deliberately short: a long list starts deciding which nouns
# matter, and the threshold below is what is supposed to absorb wording
# drift.
_STOPWORDS = {
    'a', 'an', 'and', 'any', 'are', 'as', 'at', 'be', 'by', 'can', 'do',
    'does', 'for', 'from', 'get', 'has', 'have', 'how', 'i', 'in', 'is',
    'it', 'me', 'much', 'of', 'on', 'or', 's', 'that', 'the', 'their',
    'there', 'they', 'this', 'to', 'what', 'when', 'where', 'which', 'who',
    'will', 'with', 'you', 'your',
}

#: How much of the subject two questions must share before the same ask
#: about it counts as the same question. 0.6 keeps 'what does X cost' and
#: 'how much is X' together — they differ only in the ask words this
#: already strips — while leaving room for a question that names the same
#: product and then asks something further about it.
DUPLICATE_THRESHOLD = 0.6


def ask_kind(text) -> Optional[str]:
    """
    What the question asks FOR, limited to the things the catalog tiers
    ask for. None means 'nothing a catalog tier asks', which is the
    common and correct answer for a brand-direct question.

    Checked in a fixed order so a question mentioning both a member
    price and a price resolves to the more specific one. A question with
    no signal at all is None rather than 'price': defaulting to the most
    common kind would make every where-to-buy question a price question
    the moment it named a product the catalog prices.
    """
    tokens = _tokens(text)
    for kind in ('member_price', 'points', 'code', 'price'):
        if tokens & _ASK_SIGNALS[kind]:
            return kind
    return None


def content_tokens(text, brand=None) -> Set[str]:
    """
    What the question is ABOUT: its tokens, less the brand, less the ask
    signals, less grammar.

    The brand comes out because every brand-direct question names it and
    no catalog question needs to — leaving it in would make the two sides
    look more alike in exactly the case where the difference is the
    point. The ask signals come out because they are already accounted
    for by ask_kind, and counting them twice would let 'cost'/'costs'
    alone drag two unrelated questions over the threshold.
    """
    tokens = _tokens(text)
    if brand:
        tokens -= _tokens(brand)
    for signals in _ASK_SIGNALS.values():
        tokens -= signals
    return tokens - _STOPWORDS


def intent_key(text, brand=None) -> Tuple[Optional[str], frozenset]:
    return ask_kind(text), frozenset(content_tokens(text, brand))


def catalog_intents(texts: Iterable[str], brand=None) -> List[Tuple[Optional[str], frozenset]]:
    """The intents already asked by the catalog tiers, in the shape
    is_intent_duplicate wants. Built once per generation rather than per
    candidate row."""
    keys = []
    for text in texts or []:
        kind, tokens = intent_key(text, brand)
        if kind is None:
            # A catalog question with no recognisable ask is not a shape
            # anything can duplicate, and keeping it would make every
            # brand-direct question compare against a bag of product
            # words with no ask to disagree with.
            continue
        keys.append((kind, tokens))
    return keys


def _overlap(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_intent_duplicate(
    text,
    catalog_keys: Iterable[Tuple[Optional[str], frozenset]],
    brand=None,
    threshold: float = DUPLICATE_THRESHOLD,
) -> bool:
    """
    Whether this question asks a catalog question's question.

    Requires the ask kinds to be EQUAL, not merely compatible. A
    brand-direct question that asks nothing a catalog tier asks is never
    a duplicate of one, however many product words it shares — which is
    the property that keeps 'where can I buy the Size 3 small pack' in
    the study.
    """
    kind, tokens = intent_key(text, brand)
    if kind is None or not tokens:
        return False
    for other_kind, other_tokens in catalog_keys:
        if other_kind == kind and _overlap(tokens, other_tokens) >= threshold:
            return True
    return False
