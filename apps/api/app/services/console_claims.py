"""
2K-3 (B4): claim_kind with the fact lexicon extended, still deterministic and
still at read time. 2K-1 §3's rule (soa_shared/claim_kinds.py) read "a
wetness indicator" and "the most popular newborn diaper in US hospitals" as
recommendation-only: neither names a word on its list, and both state
something a reader could check. Two more kinds of fact make an answer
`attribute` here:

  feature      a product feature from the merchant's own record: the
               attribute names and values its published catalog carries
               (wetness indicator, hypoallergenic, fragrance free, 12-hour,
               stretchy waistband, the sizes and weight ranges), loaded per
               merchant as the brand terms are (feature_terms).
  endorsement  a reputation or endorsement claim: hospitals, pediatricians,
               "#1", "most popular", "best-selling", an award, "clinically",
               dermatologists.

The ingredient and material words stay claim_kinds.LEXICON's. Like 2K-1's,
the rule only adds attributes: an answer 2K-1 read as `attribute` reads the
same here, and a miss still errs toward `attribute`.

API only: claim_kinds.py and its pipeline copy are unchanged, and nothing in
the pipeline reads this. A caller that passes no `features` (None) gets
2K-1's rule exactly, which is what the score's rows read
(console_parity.load_overview_rows' default), so no score moves.

No model is called.
"""
import re
from typing import Iterable, List, Optional

from soa_shared import claim_kinds

ATTRIBUTE = claim_kinds.ATTRIBUTE
RECOMMENDATION_ONLY = claim_kinds.RECOMMENDATION_ONLY

#: reputation and endorsement claims, matched case-insensitively
ENDORSEMENT = re.compile(
    r"#\s?1\b|\b(?:hospitals?|p(?:a)?ediatrician\w*|number one|no\.\s?1|most popular|best-?sell\w*|"
    r"best sellers?|awards?|award-winning|clinically|dermatologist\w*)\b", re.IGNORECASE)

#: catalog attribute keys that name the product, never a feature of it
NAME_KEYS = {'brand', 'brand_name', 'label', 'title', 'name', 'product_name', 'line', 'product_line', 'sub_brand',
             'collection', 'gtin', 'gtin14', 'sku', 'url', 'image', 'image_url', 'description', 'color', 'colour'}
#: catalog attribute keys whose value is a size
SIZE_KEYS = {'size', 'sizes', 'diaper_size'}


def _words(text: str) -> str:
    return ' '.join(str(text).replace('_', ' ').split()).strip()


def _size_terms(value: str) -> List[str]:
    """A size with a number is itself ("Size 3", "8-14 lb"); a bare word
    ("Newborn") is a fact only as a size ("newborn size", "size newborn"),
    so "for a newborn" stays a recommendation."""
    value = _words(value)
    if not value:
        return []
    if any(ch.isdigit() for ch in value):
        return [value]
    return [f"size {value}", f"{value} size"]


def feature_terms(catalog: Optional[dict], brand_terms: Iterable[str] = ()) -> List[str]:
    """The feature words of a merchant's published catalog (supply's GET
    /merchants/{slug}/catalog): each variant's attribute names (a true flag)
    and values (text, or a list of text), its size, and a listing's
    `features`. A term that names the product (the brand, a product name, a
    NAME_KEYS attribute) is left out, as is one with fewer than three
    letters (two beside a number: "8-14 lb"). Lower-case, each once,
    longest first."""
    brands = [t.lower() for t in brand_terms if t]
    out: List[str] = []

    def add(term) -> None:
        term = _words(term).lower()
        letters = sum(ch.isalpha() for ch in term)
        if letters < (2 if any(ch.isdigit() for ch in term) else 3) or term in out:
            return
        if any(b and (b in term or term in b) for b in brands):
            return
        out.append(term)

    for listing in (catalog or {}).get('listings') or []:
        for f in listing.get('features') or []:
            if isinstance(f, str):
                add(f)
        for v in listing.get('variants') or []:
            if v.get('size'):
                for t in _size_terms(v['size']):
                    add(t)
            for key, value in (v.get('attributes') or {}).items():
                key = str(key)
                if key.lower() in NAME_KEYS:
                    continue
                values = value if isinstance(value, list) else [value]
                for item in values:
                    if item is True:
                        add(key)
                    elif isinstance(item, str) and item.strip():
                        for t in (_size_terms(item) if key.lower() in SIZE_KEYS else [item]):
                            add(t)
    return sorted(out, key=lambda t: (-len(t), t))


def _pattern(term: str) -> re.Pattern:
    """Word-bounded, a space or hyphen between tokens either way:
    "fragrance free" matches "fragrance-free", "12-hour" "12 hour"."""
    tokens = [re.escape(t) for t in re.split(r"[\s\-]+", term) if t]
    body = r"[\s\-]*".join(tokens)
    return re.compile((r"\b" if term[:1].isalnum() else '') + body + (r"\b" if term[-1:].isalnum() else ''),
                      re.IGNORECASE)


def answer_attributes(extraction: Optional[dict], features: Iterable[str] = ()) -> List[str]:
    """claim_kinds.answer_attributes, then 'feature' and 'endorsement' when
    a labelled span names one."""
    x = extraction or {}
    found = claim_kinds.answer_attributes(x)
    texts = claim_kinds.labelled_texts(x)
    patterns = [_pattern(t) for t in features]
    if patterns and any(p.search(t or '') for t in texts for p in patterns):
        found.append('feature')
    if any(ENDORSEMENT.search(t or '') for t in texts):
        found.append('endorsement')
    return found


def claim_kind(extraction: Optional[dict], features: Optional[Iterable[str]] = None) -> Optional[str]:
    """attribute | recommendation_only | None. With `features` None, 2K-1's
    rule exactly (claim_kinds.claim_kind)."""
    if features is None:
        return claim_kinds.claim_kind(extraction)
    x = extraction or {}
    if answer_attributes(x, list(features)):
        return ATTRIBUTE
    if not claim_kinds.labelled_texts(x):
        return None
    return RECOMMENDATION_ONLY


def counts(extractions: Iterable[Optional[dict]], features: Optional[Iterable[str]] = None) -> dict:
    """{attribute, recommendation_only, undecided} over several answers."""
    features = None if features is None else list(features)
    out = {ATTRIBUTE: 0, RECOMMENDATION_ONLY: 0, 'undecided': 0}
    for x in extractions:
        out[claim_kind(x, features) or 'undecided'] += 1
    return out
