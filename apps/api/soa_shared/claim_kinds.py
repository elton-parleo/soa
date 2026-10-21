"""
2K-1 (A9): whether a brand-direct answer stated an attribute of the brand
or only recommended it. Read by the console (apps/api) over the extraction
stored on soa_expectation_outcomes, so a cycle scored before this reads the
same as one scored after. Sync copies to apps/api/soa_shared/ and
apps/pipeline/soa_shared/ (beside retailers.py, which it reads).

The brand-direct classifier's `fabricated` (scoring/brand_direct_classifier.py)
counts an asserted claim stated with no source, and the extractor's labels
are frozen (Layer 2 at 85c2cfe): "For a newborn, you should buy Pampers
Swaddlers. They are widely considered the gold standard" is an asserted
claim with no source, so it is `fabricated`, but it states nothing a record
could publish or contradict. This module does not change the outcome. It
derives a second axis beside it, from what the extraction already carries:

  attribute            the answer stated something checkable about the
                       brand: a price, size, weight, count or pack, a GTIN,
                       a code or points, a retailer or site, a program,
                       its availability, an ingredient or material, or
                       who owns or makes it.
  recommendation_only  every labelled span is free of all of those, and so
                       is every structured field: it recommended the brand
                       (or praised it) without stating a fact.
  None                 the extraction carries no labelled span and no
                       transcribed claim, so there is nothing to decide on.
                       Never guessed.

The rule is deterministic and conservative: ANY attribute anywhere (any
structured value, any labelled span, hedged or not) makes the answer
`attribute`. The transcription's own per-claim `claim_kind`
(parser/extraction_postprocess.claim_kind: loyalty | retail | ownership |
other) is NOT read: its `retail` words include "buy" and "store", so "you
should buy Pampers Swaddlers", the recommendation this module exists to tell
apart, would read as a retail claim. The span lexicon below names
retailers, availability, programs and ownership on its own. A word list misses some attribute phrasing; it is tuned to
miss toward `attribute`, which keeps a real fabrication in the headline
count rather than moving it out.

No model is called.
"""
import re
from typing import Iterable, List, Optional

ATTRIBUTE = 'attribute'
RECOMMENDATION_ONLY = 'recommendation_only'
CLAIM_KINDS = (ATTRIBUTE, RECOMMENDATION_ONLY)

#: Structured extraction fields that hold a stated value. Any entry in one
#: is an attribute claim.
VALUE_FIELDS = ('prices', 'member_prices', 'pack_counts', 'gtins', 'sizes', 'codes', 'points',
                'loyalty_tiers_named')
#: Fields that name a retailer the answer sent the reader to.
RETAILER_FIELDS = ('retailer_mentions', 'recommended_retailers')

#: One pattern per attribute the brief names, matched case-insensitively
#: on word boundaries in every labelled span.
LEXICON = {
    'price': r"[$£€]|\b(?:price[sd]?|pricing|cost[s]?|costing|cheap(?:er|est)?|expensive|afford\w*|"
             r"discount\w*|coupon\w*|deal[s]?|on sale|promo\w*|per (?:diaper|wipe|count|unit))\b",
    'size': r"\b(?:size[sd]?|sizing|fits? up to|newborn size|preemie size)\b",
    'weight': r"\b\d+(?:\.\d+)?\s?(?:-\s?\d+(?:\.\d+)?\s?)?(?:lb|lbs|pound[s]?|oz|ounce[s]?|kg|g|gram[s]?)\b|"
              r"\bweigh\w*\b",
    'count': r"\b\d+\s?(?:ct|count|pack|pk|pcs|pieces|diapers|wipes)\b|\bcount\b",
    'pack': r"\b(?:pack[s]?|box(?:es)?|bulk|bundle[s]?|jumbo|mega|giant|super pack)\b",
    'program': r"\b(?:reward[s]?|loyalty|points?|member(?:ship)?s?|subscri\w+|auto-?deliver\w*|"
               r"subscribe\s*&\s*save|program[s]?|club)\b",
    'availability': r"\b(?:available|availability|in stock|out of stock|stock(?:ed|s)?|discontinued|"
                    r"sold|sells?|selling|carr(?:y|ies|ied)|exclusive(?:ly)?|ships?|shipping|launch(?:ed)?)\b",
    'ingredient': r"\b(?:ingredient[s]?|made (?:with|from|of)|contain[s]?|free (?:of|from)|\w+-free|"
                  r"fragrance\w*|scent\w*|chlorine|latex|paraben\w*|lotion|aloe|petrolatum|phthalate\w*|"
                  r"dye[s]?|plant-?based|organic|hypoallergenic|vitamin \w)\b",
    'material': r"\b(?:material[s]?|cotton|bamboo|fabric|cloth|polymer|pulp|liner)\b",
    'ownership': r"\b(?:owned|owns|made by|manufactur\w+|parent compan\w+|private label|subsidiar\w+|"
                 r"official (?:site|website|store))\b",
}
_COMPILED = {k: re.compile(v, re.IGNORECASE) for k, v in LEXICON.items()}


def labelled_texts(extraction: dict) -> List[str]:
    """Every labelled span's text (span_labels), else every transcribed
    claim's (brand_claims, an extraction from before the segmenter)."""
    spans = [s.get('text') for s in extraction.get('span_labels') or [] if isinstance(s, dict) and s.get('text')]
    if spans:
        return spans
    return [c.get('claim') or c.get('sentence') for c in extraction.get('brand_claims') or []
            if isinstance(c, dict) and (c.get('claim') or c.get('sentence'))]


def span_attributes(text: Optional[str]) -> List[str]:
    """The attributes one span names, in LEXICON order, then 'retailer'."""
    found = [k for k, rx in _COMPILED.items() if rx.search(text or '')]
    from soa_shared.retailers import retailers_named
    if retailers_named(text or ''):
        found.append('retailer')
    return found


def answer_attributes(extraction: Optional[dict]) -> List[str]:
    """Every attribute the stored extraction carries, each once: the
    structured fields first, then the spans' words."""
    x = extraction or {}
    found: List[str] = [f for f in VALUE_FIELDS if x.get(f)]
    if any(x.get(f) for f in RETAILER_FIELDS):
        found.append('retailer')
    for text in labelled_texts(x):
        for a in span_attributes(text):
            if a not in found:
                found.append(a)
    return found


def claim_kind(extraction: Optional[dict]) -> Optional[str]:
    """attribute | recommendation_only | None (nothing labelled to decide on)."""
    x = extraction or {}
    if answer_attributes(x):
        return ATTRIBUTE
    if not labelled_texts(x):
        return None
    return RECOMMENDATION_ONLY


def counts(extractions: Iterable[Optional[dict]]) -> dict:
    """{attribute, recommendation_only, undecided} over several answers."""
    out = {ATTRIBUTE: 0, RECOMMENDATION_ONLY: 0, 'undecided': 0}
    for x in extractions:
        out[claim_kind(x) or 'undecided'] += 1
    return out
