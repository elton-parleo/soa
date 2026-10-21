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

2K-1 (E29): brand choice. A comparison question ("Pampers vs Huggies for
newborns", tier `comparison`) names the merchant and at least one rival and
asks which to choose. It is not unprompted (it names the brand), but the
answer's first pick is still a brand choice, so the brand-choice set is the
unprompted set plus the comparison tier (is_brand_choice). Lost and the
first-pick tiles read the brand-choice set; share of mentions and the score's
Visibility dimension stay on the unprompted set (a question that names the
brand is no share-of-mentions test). is_comparison is the generator's check
that a Comparison-stage question names the brand and a rival.

No model is called.
"""
from typing import Iterable, List, Optional

from .expected_answers import names_brand, normalize_brand_text

#: The tiers whose questions name no brand by design.
UNPROMPTED_TIERS = ('category_control',)
#: 2K-1: the tier whose questions name the brand and a rival, and ask which to choose.
COMPARISON_TIER = 'comparison'


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


def is_comparison(question, brand: Iterable[str], rivals: Iterable[str]) -> bool:
    """2K-1: a question (its text, or anything with `query_text`) is a
    comparison question when it names one of the brand's terms and at
    least one rival term that is not itself a brand term (so 'Pampers
    Swaddlers vs Pampers Baby-Dry' is no comparison). Rival terms are the
    merchant's competitors, tracked or not, and whatever the caller adds;
    with no rival terms nothing is a comparison."""
    text = question.get('query_text') if isinstance(question, dict) else question
    brand = list(brand or [])
    own = {normalize_brand_text(t) for t in brand}
    rivals = [r for r in rivals or [] if normalize_brand_text(r) and normalize_brand_text(r) not in own
              and not any(normalize_brand_text(r) == b or names_brand(r, b) for b in brand)]
    return bool(names_any(text, brand)) and bool(names_any(text, rivals))


def is_brand_choice(run_or_question: dict, terms: Iterable[str] = ()) -> bool:
    """2K-1: the answer's first pick is a brand choice: an unprompted
    question, or one of the comparison tier."""
    return run_or_question.get('tier') == COMPARISON_TIER or is_unprompted(run_or_question, terms)
