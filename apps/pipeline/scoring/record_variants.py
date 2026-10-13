"""
The record's variants, in the shape the §3 clash rules need.

Built from the same CatalogSnapshot the generator wrote expectations from,
and named with the generator's own naming function (catalog_tiers.
_naming_parts) so "the phrases that identify a variant" mean one thing on
both sides — the same single-definition rule the attribution hints follow.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from generation import catalog_tiers as ct
from scoring import variant_rules as vr
from soa_shared import expected_answers as ea


@dataclass
class RecordVariant:
    variant_id: str
    #: The item group: every variant of one product (listing) shares it.
    #: Rule 1's "adjacent variant" means a sibling in the same group.
    group: str
    #: Everything the record says about the variant, for marker and model-
    #: number comparison: product title, variant title, size, attributes.
    text: str
    #: The phrases a question uses to name it (empty for a single-variant
    #: product), as token sets for attributes_to-style matching.
    naming: List[set] = field(default_factory=list)
    count: Optional[int] = None
    list_price: Optional[str] = None
    member_price: Optional[str] = None
    gtin: Optional[str] = None

    @property
    def packs(self) -> set:
        """Every pack number the record states for the variant: the
        engine's packNumbers over its text ('4 oz', '3-Pack', '(84 ct)')
        plus its count. The engine compares pack numbers on BOTH sides;
        comparing a claim against the count alone read 'Bum Balm 4 oz' as
        a different item from the 4 oz Bum Balm."""
        return vr.pack_numbers(self.text) | ({self.count} if self.count else set())


def _tokens(text) -> set:
    import re
    return {t for t in re.sub(r'[^a-z0-9]+', ' ', str(text or '').lower()).split() if t}


def from_snapshot(snapshot) -> List[RecordVariant]:
    if not snapshot or not getattr(snapshot, 'available', False):
        return []
    out = []
    for product, variant in snapshot.variants():
        attrs = ' '.join(str(v) for v in (variant.attributes or {}).values())
        text = ' '.join(filter(None, [
            product.title, variant.title, variant.size, attrs,
        ]))
        out.append(RecordVariant(
            variant_id=variant.variant_id,
            group=str(product.listing_id if product.listing_id is not None else product.title),
            text=text,
            naming=[t for t in (_tokens(p) for p in ct._naming_parts(product, variant)) if t],
            count=variant.count,
            list_price=ea.normalize_money(variant.list_price),
            member_price=ea.normalize_money(variant.member_price),
            gtin=variant.gtin,
        ))
    return out


def find(variants: List[RecordVariant], variant_id) -> Optional[RecordVariant]:
    for variant in variants or []:
        if variant.variant_id == variant_id:
            return variant
    return None


def conflicts(claim: Optional[str], asked: RecordVariant, *, hints_attribute: bool) -> Optional[str]:
    """
    Rule 2: why this claim is NOT about the asked variant, or None.

    `hints_attribute` is attributes_to()'s answer for the claim against the
    generator's hints (attribution / attribution_rivals). When the hints
    say the claim names a rival, that is a conflict on its own.

    The pack-number clash is deliberately narrower than the engine's. The
    catalog-accuracy design (generation/catalog_tiers.py, _discriminators)
    rules that an answer naming the right variant and volunteering the
    WRONG count must not lose its price measurement to that count: the
    count is a secondary claim, scored on its own. So a pack number only
    moves a claim when the claim does not also carry the asked variant's
    other naming phrases.
    """
    if not claim:
        return None
    if not hints_attribute:
        return 'names a sibling variant'
    markers = vr.marker_clash(claim, asked.text)
    if markers:
        return f"variant marker {', '.join(sorted(markers))}"
    if vr.model_number_clash(claim, asked.text):
        return 'model or size number differs'
    stated = _tokens(claim)
    names_asked = any(phrase and phrase <= stated for phrase in asked.naming)
    claim_packs = vr.pack_numbers(claim)
    if claim_packs and asked.packs and not (claim_packs & asked.packs) and not names_asked:
        return f"pack count {', '.join(str(n) for n in sorted(claim_packs))}"
    return None


def named_variant(claim: Optional[str], asked: RecordVariant,
                  variants: List[RecordVariant]) -> Optional[RecordVariant]:
    """
    The one OTHER record variant this claim names, or None.

    A candidate must not clash with the claim (markers, model numbers, a
    stated pack count) and must be positively named by it: one of its own
    naming phrases present, or its count stated. Exactly one candidate, or
    none — two equally good candidates is not a variant we can score
    against, and guessing between them would be the thing this rule exists
    to stop.
    """
    if not claim:
        return None
    stated = _tokens(claim)
    claim_packs = vr.pack_numbers(claim)
    claim_markers = vr.variant_markers(claim)
    scored = []
    for variant in variants or []:
        if variant.variant_id == asked.variant_id:
            continue
        if vr.marker_clash(claim, variant.text):
            continue
        if vr.model_number_clash(claim, variant.text):
            continue
        if claim_packs and variant.packs and not (claim_packs & variant.packs):
            continue
        # Evidence the claim names THIS variant: each of its naming phrases
        # present, its count stated, a marker they share ("Overnight Size 3"
        # names the overnight Size 3).
        score = sum(1 for phrase in variant.naming if phrase and phrase <= stated)
        score += 1 if (claim_packs and variant.count and variant.count in claim_packs) else 0
        score += len(claim_markers & vr.variant_markers(variant.text))
        score += 1 if vr.model_number_match(claim, variant.text) else 0
        if score:
            scored.append((score, variant))
    if not scored:
        return None
    best = max(score for score, _v in scored)
    top = [v for score, v in scored if score == best]
    if len(top) == 1:
        return top[0]
    # A tie broken only by the asked variant's own item group, and only
    # when that leaves exactly one.
    same_group = [v for v in top if v.group == asked.group]
    return same_group[0] if len(same_group) == 1 else None
