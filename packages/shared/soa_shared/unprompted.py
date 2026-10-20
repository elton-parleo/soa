"""
2I-7: which questions are unprompted. One rule, read by the console's score
and its read models (apps/api) and by the study generator's category-control
check (apps/pipeline), so a question the generator kept is one the score
counts and the screens show. Sync copies to apps/api/soa_shared/,
apps/pipeline/soa_shared/ and packages/shared/soa_shared/.

A question is unprompted when both hold:

  its tier is category_control, or it has none. A study generated with the
  syndicated-brand box on tags its stage questions category_control
  (generation/syndicated_study.py); one generated with the box off leaves
  them untiered. They are the same questions, so both count.

  its text names none of the brand's terms: the cycle's primary entity's
  name and aliases, and the brand's product names from its catalog
  (brand_terms). Matched by expected_answers.names_brand, case-insensitive
  and as whole words, so 'Pampers' is named by 'pampers swaddlers' and a
  brand called 'Bum' is not named by 'album'.

A category-control question that names the brand is not a share-of-mentions
measurement: the question put the brand in the answer. FL12 (Oct 19, the
Pampers first loop) asked 13 of them in its first 25.

No model is called.
"""
from typing import Iterable, List, Optional

from .expected_answers import names_brand, normalize_brand_text

#: The tiers whose questions name no brand by design.
UNPROMPTED_TIERS = ('category_control',)


def brand_terms(name: Optional[str] = None, aliases: Optional[Iterable] = None,
                product_names: Optional[Iterable] = None) -> List[str]:
    """Every term that counts as naming the brand, in order, each once
    (by its normalized form), blanks left out."""
    out, seen = [], set()
    for term in [name, *(aliases or []), *(product_names or [])]:
        key = normalize_brand_text(term) if isinstance(term, str) else ''
        if key and key not in seen:
            seen.add(key)
            out.append(term.strip())
    return out


def names_any(text: Optional[str], terms: Iterable[str]) -> List[str]:
    """The terms the text names, in the order given."""
    return [t for t in terms or [] if normalize_brand_text(t) and names_brand(text or '', t)]


def is_unprompted_tier(tier: Optional[str]) -> bool:
    return not tier or tier in UNPROMPTED_TIERS


def is_unprompted(run_or_question: dict, terms: Iterable[str] = ()) -> bool:
    """A run or a question (anything with `tier` and `query_text`) is
    unprompted when its tier is category_control or absent and its text
    names none of `terms`. With no terms the text cannot be checked and the
    tier decides alone."""
    if not is_unprompted_tier(run_or_question.get('tier')):
        return False
    return not names_any(run_or_question.get('query_text'), terms)
