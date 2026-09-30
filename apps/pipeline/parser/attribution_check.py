"""
Checks a CodingResponse's entity attribution against the response text.

The coding model can file one entity's mention under another entity's key
(e.g. a Chewy recommendation recorded as Petco's). The JSON schema cannot
catch that, and nothing downstream can either, so every coded run is
checked here against the words actually in the response:

  coded_but_absent      coded as mentioned, but no form of the entity's
                        name appears anywhere in the response. It cannot
                        be a real mention, so the coder clears it.
  evidence_names_other  coded as mentioned, and the evidence names a
                        different tracked entity but not this one — the
                        signature of a swapped key.
  present_but_uncoded   the entity's name appears, as written, but it is
                        coded as not mentioned.

Matching is deliberately asymmetric. "Absent" uses a loose match (case and
punctuation ignored, so "Pet Smart" and "Wal-Mart" still count as present)
because an absent verdict deletes a mention. "Present" uses a strict,
case-sensitive match on the name as written (or its .com domain) because
some names are ordinary words: "chewy treats" is not a mention of Chewy,
and a name joined to what precedes it by "&" ("Stella & Chewy's") is part
of another name.
"""
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List

from parser.coding_response import MerchantCoding

if TYPE_CHECKING:
    from soa_shared.models.soa_models import SoaCycleEntity

CODED_BUT_ABSENT = "coded_but_absent"
EVIDENCE_NAMES_OTHER = "evidence_names_other"
PRESENT_BUT_UNCODED = "present_but_uncoded"

# Issues worth a second coding call: both mean the coding is attached to
# the wrong entity. present_but_uncoded alone is usually a passing mention
# the coder judged too slight, and is only flagged for review.
RETRY_KINDS = {CODED_BUT_ABSENT, EVIDENCE_NAMES_OTHER}

# Loose terms shorter than this match too much by accident.
_MIN_LOOSE_TERM_LEN = 4


@dataclass
class AttributionIssue:
    code: str
    kind: str
    detail: str


@dataclass
class EntityTerms:
    names: List[str]  # as written, for the strict match
    loose: List[str]  # normalized, for the loose match
    domains: List[str]  # e.g. "petco.com"


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def entity_terms(ce: "SoaCycleEntity") -> EntityTerms:
    names = [ce.entity.name, ce.display_name, *(ce.entity.aliases or [])]
    names = [n for n in dict.fromkeys(names) if isinstance(n, str) and n.strip()]
    slug = ce.entity.slug if isinstance(ce.entity.slug, str) else None

    loose = {_normalize(n) for n in names}
    if slug:
        loose.add(_normalize(slug))
    domains = {f"{_normalize(n)}.com" for n in names if _normalize(n)}

    return EntityTerms(
        names=names,
        loose=sorted(t for t in loose if len(t) >= _MIN_LOOSE_TERM_LEN),
        domains=sorted(domains),
    )


def appears_loosely(terms: EntityTerms, text: str) -> bool:
    normalized = _normalize(text or "")
    return any(t in normalized for t in terms.loose)


def appears_strictly(terms: EntityTerms, text: str) -> bool:
    text = text or ""
    for name in terms.names:
        for match in re.finditer(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", text):
            # "Stella & Chewy's", "Soft & Chewy Treats": the name is the
            # tail of some other product or brand name, not the entity.
            if re.search(r"&\s*$", text[:match.start()]):
                continue
            return True
    lowered = text.lower()
    return any(d in lowered for d in terms.domains)


def check_attribution(
    merchants: Dict[str, MerchantCoding],
    raw_response: str,
    code_to_terms: Dict[str, EntityTerms],
) -> List[AttributionIssue]:
    issues: List[AttributionIssue] = []
    for code, mc in merchants.items():
        terms = code_to_terms.get(code)
        if terms is None:
            continue

        if not mc.mentioned:
            if appears_strictly(terms, raw_response):
                issues.append(AttributionIssue(
                    code, PRESENT_BUT_UNCODED,
                    f"{terms.names[0]} appears in the response but is coded not mentioned",
                ))
            continue

        if not appears_loosely(terms, raw_response):
            issues.append(AttributionIssue(
                code, CODED_BUT_ABSENT,
                f"{terms.names[0]} is coded mentioned but does not appear in the response",
            ))
            continue

        if mc.evidence and not appears_loosely(terms, mc.evidence):
            others = [
                code_to_terms[other].names[0]
                for other in code_to_terms
                if other != code and appears_loosely(code_to_terms[other], mc.evidence)
            ]
            if others:
                issues.append(AttributionIssue(
                    code, EVIDENCE_NAMES_OTHER,
                    f"evidence for {terms.names[0]} names {', '.join(others)} instead",
                ))
    return issues


def retry_worthy(issues: List[AttributionIssue]) -> List[AttributionIssue]:
    return [i for i in issues if i.kind in RETRY_KINDS]


def clear_absent_mentions(
    merchants: Dict[str, MerchantCoding],
    issues: List[AttributionIssue],
) -> int:
    """
    Resets every coded_but_absent entity to a not-mentioned coding, in
    place. Returns how many were cleared.
    """
    cleared = 0
    for issue in issues:
        if issue.kind != CODED_BUT_ABSENT:
            continue
        mc = merchants[issue.code]
        mc.mentioned = False
        mc.position = None
        mc.strength = None
        mc.deal_cited = False
        mc.deal_types = []
        mc.member_value_cited = False
        mc.evidence = None
        mc.stated_price = None
        mc.claimed_net_price = None
        mc.claimed_discount_value = None
        mc.claimed_discount_pct = None
        mc.claimed_terms = []
        mc.member_price_claimed = None
        mc.subscription_offer_claimed = None
        cleared += 1
    return cleared


def _first_offset(terms: EntityTerms, text: str) -> float:
    offsets = [
        m.start()
        for term in [*terms.names, *terms.domains]
        for m in [re.search(re.escape(term), text or "", re.IGNORECASE)]
        if m
    ]
    return min(offsets) if offsets else float("inf")


def resolve_position_ties(
    merchants: Dict[str, MerchantCoding],
    raw_response: str,
    code_to_terms: Dict[str, EntityTerms],
) -> bool:
    """
    Breaks ties when the coder gives two mentioned entities the same
    position, in place. Position is the order of first mention, so ties
    are ordered by where each entity's name first appears in the response.
    Positions only move up, and only as far as needed to stay distinct;
    untied positions are left alone. Returns whether anything changed.
    """
    mentioned = [
        (code, mc) for code, mc in merchants.items()
        if mc.mentioned and mc.position is not None
    ]
    positions = [mc.position for _, mc in mentioned]
    if len(positions) == len(set(positions)):
        return False

    def order(item):
        code, mc = item
        terms = code_to_terms.get(code)
        return (mc.position, _first_offset(terms, raw_response) if terms else float("inf"), code)

    previous = 0
    for _, mc in sorted(mentioned, key=order):
        mc.position = max(mc.position, previous + 1)
        previous = mc.position
    return True
