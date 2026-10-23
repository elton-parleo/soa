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
    #: The product's NAME as tokens: its title's words, without numbers or
    #: units ('Bum Balm 4 oz' -> {bum, balm}). With `brand`, what
    #: names_our_product() looks for.
    product_name: set = field(default_factory=set)
    brand: set = field(default_factory=set)

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


#: Words a title carries for its size, not its name.
_UNIT_WORDS = {'oz', 'fl', 'ml', 'l', 'g', 'kg', 'lb', 'ct', 'count', 'pack', 'pk', 'packs'}


def name_tokens(title) -> set:
    return {t for t in _tokens(title) if t.isalpha() and t not in _UNIT_WORDS}


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
            product_name=name_tokens(product.title),
            brand=_tokens(product.brand or snapshot.brand),
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


def names_our_product(claim: Optional[str], variants: List[RecordVariant],
                      brand_facts: Optional[dict] = None) -> bool:
    """
    Whether a claim's attributed_product names OUR product at all: the
    brand, or one of the record's product names, present in full. From the
    record (and the brand facts the scorer already holds), so it is
    deterministic and makes no model call. Layer 1's mention coding is per
    answer, not per claim, so it cannot say which thing a price was for.

    "eligible purchases made at Costco", "an $11.00 pack" and another
    brand's diapers name none of ours.
    """
    stated = _tokens(claim)
    if not stated:
        return False
    facts = brand_facts or {}
    names = [v.brand for v in variants or []] + [v.product_name for v in variants or []]
    names += [_tokens(facts.get('brand'))] + [name_tokens(t) for t in facts.get('product_titles') or []]
    return any(name and name <= stated for name in names)


def carries_descriptor(claim: Optional[str], asked: RecordVariant, rivals) -> bool:
    """
    Whether the claim states a variant descriptor of its own: a marker,
    model/size number or pack count that conflicts with the asked variant
    (rule 2's engine checks), or a sibling's naming phrase. A bare product
    name ("Snug-Fit Overnight Diapers") carries none.
    """
    if not claim:
        return False
    if conflicts(claim, asked, hints_attribute=True):
        return True
    stated = _tokens(claim)
    return any(rival and rival <= stated for rival in rivals or [])


# ─── 2N-1: a description of ours, and the retailer's own title ─────────────

#: Words that name nothing: pronouns, articles, the generic nouns an answer
#: puts around a size or count ("the NB 84-count option", "this one").
GENERIC = frozenset({
    'the', 'a', 'an', 'this', 'that', 'these', 'those', 'it', 'its', 'one', 'ones', 'them', 'they',
    'option', 'options', 'version', 'variant', 'listing', 'product', 'item', 'pack', 'package', 'box',
    'size', 'count', 'ct', 'of', 'for', 'with', 'in', 'on', 'and', 'or', 'at',
}) | vr.DESCRIPTORS
#: The ways an answer writes a size the record writes otherwise.
SIZE_ALIASES = {'nb': 'newborn', 'n': 'newborn', 'p': 'preemie'}


def _words(text) -> set:
    return {SIZE_ALIASES.get(t, t) for t in _tokens(str(text or '').replace("'", ''))}


def describes_asked(claim: Optional[str], asked: RecordVariant) -> bool:
    """
    Whether a claim with no product name of its own describes the ASKED
    variant: every word is a generic one, a descriptor, a number, or a word
    of the asked variant's record, and at least one is positive evidence for
    it (its count stated, a size word of its record: "NB" for Newborn).
    "the NB 84-count option" on the Newborn 84 ct question does; "an
    $11.00 pack" names nothing of the asked variant and does not.
    """
    if not claim:
        return False
    stated = _words(claim)
    record = _words(asked.text) | {SIZE_ALIASES.get(w, w) for w in _words(asked.text)}
    named = {w for w in stated if not w.isdigit() and w not in GENERIC}
    if not named <= record:
        return False
    counted = bool(asked.count and asked.count in vr.pack_numbers(claim))
    sized = bool(named & record - GENERIC)
    return counted or sized


def is_pronoun(claim: Optional[str]) -> bool:
    """A claim attached to a pronoun or a bare generic phrase ("it", "this one"): no product named."""
    stated = _words(claim)
    return bool(stated) and all(w in GENERIC and w not in vr.DESCRIPTORS for w in stated)


def in_title(claim: Optional[str], title: Optional[str]) -> bool:
    """
    The quoted name is contained in the retailer page's own title for the
    variant: every word of it, the generic ones aside, is a word of the
    title, so it is that variant ("Pampers Swaddlers Fragrance-Free Baby
    Diapers, Size 1, 96 Count" against Walmart's title for it).
    """
    if not claim or not title:
        return False
    stated = {w for w in _words(claim) if w not in GENERIC or w in vr.DESCRIPTORS}
    page = _words(title) | {'ct' if w == 'count' else w for w in _words(title)}
    stated = {'ct' if w == 'count' else w for w in stated}
    return bool(stated) and stated <= page
