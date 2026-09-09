"""
The catalog-built question tiers.

Two of the four tiers are built here, from the published record and with
no model call at all:

  catalog_accuracy   price per sampled variant, GTIN riding along as a
                     secondary expectation, pack count where the variant
                     has one to ask about
  value_incentives   one question per mechanic the record actually has —
                     coupon code, member price, points

The other two are elsewhere because they are model work:
brand_direct is the existing generator prompt extended with this catalog
as context (generation/query_generator.py), and category_control is a tag
applied to the study's ordinary stage-count questions rather than any new
generation at all.

Why templates and not a model. These questions exist so an answer can be
compared to a published number. A model asked to write them would
paraphrase — "roughly what does the size 3 pack run?" — and a paraphrase
moves the goalposts between one run of a study and the next, which is
exactly what a longitudinal measure cannot afford. Fixed wording also
means the question text itself is evidence: read it back in six months
and it still says which variant it asked about.

WORDING IS FROZEN. The templates below are mirrored, deliberately and by
hand, in apps/api/web/src/components/catalogTiers.js so the Create Study
modal can show true examples for the selected brand before anything is
generated. Both sides assert the same literal strings against the same
Wiggle & Snug fixture (tests/test_catalog_tiers.py and
CreateStudyModal.brand.test.jsx), so an edit to one that is not made to
the other fails a test rather than drifting quietly into a study.
"""
import logging
from typing import List, Optional

from soa_shared import expected_answers as ea

logger = logging.getLogger(__name__)

# The catalog-accuracy tier's ceiling, counted in VARIANTS sampled, not
# in questions emitted. The brief says "cap the tier at 20 questions; if
# the catalog has more variants, sample..." — two sentences that only
# agree if the thing being sampled and capped is the variant, which is
# also what makes the cap stable when a second template (pack count)
# applies to some variants and not others. tier_config records both the
# sampled variants and the resulting question count, so the reading is
# visible in the data rather than only in this comment.
DEFAULT_VARIANT_CAP = 20

# What the brand-direct tier asks for when the caller does not say.
DEFAULT_BRAND_DIRECT_COUNT = 12

# Catalog-built questions are all bottom-of-funnel by construction: a
# price, a code, a pack count and a member price are the things a shopper
# asks when they have decided what to buy and are deciding whether to buy
# it here.
CATALOG_STAGE = 'Ready to Buy'
CATALOG_SPECIFICITY = 'Narrow'


# ─── Naming ────────────────────────────────────────────────────────────────

def variant_display(product, variant) -> str:
    """
    The words that distinguish this variant from its siblings.

    Built from the record's structured fields rather than by chipping the
    product title off the front of the variant title. Both would work on
    Wiggle & Snug; only this one keeps working on a merchant whose
    variant titles are not prefixed with the product name.

    Empty string for a single-variant product, which is the point of the
    function: a variant display exists to distinguish variants, and with
    one variant there is nothing to distinguish. "What does the Wiggle &
    Snug Cloud Wipes 3-Pack cost?" is the question; "...Cloud Wipes
    3-Pack 3 packs (216 ct) cost?" is a machine talking.

    The count is part of the display, and that is a deliberate cost: it
    is what makes "Size 3 small pack (84 ct)" unambiguous to an
    assistant, and it is also why the pack-count secondary riding on this
    question is weak evidence on a multi-variant product. See
    build_catalog_accuracy's KNOWN WEAKNESS note.
    """
    if len(product.variants) <= 1:
        return ''

    parts = []
    if variant.size:
        parts.append(str(variant.size).strip())

    # The record's own shopper-facing attribute, lower-cased: 'Small Pack'
    # is a label in a catalog, 'small pack' is how it is said out loud,
    # and these questions are meant to read like something typed into an
    # assistant.
    pack = (variant.attributes or {}).get('pack')
    if pack:
        parts.append(str(pack).strip().lower())

    if variant.count and variant.count > 1:
        parts.append(f"({variant.count} ct)")

    return ' '.join(parts)


def _subject(brand: Optional[str], product, variant) -> str:
    """'Wiggle & Snug Snug-Fit Diapers Size 3 small pack (84 ct)'"""
    words = [w for w in (brand, product.title) if w]
    display = variant_display(product, variant)
    if display:
        words.append(display)
    return ' '.join(words)


# ─── Sampling ──────────────────────────────────────────────────────────────

def _price_spread_order(variants: List) -> List:
    """
    A product's variants ordered so that taking the first N spans its
    price range: cheapest, dearest, second-cheapest, second-dearest, ...

    Taking the first N of a plain price sort would sample only the bottom
    of the range, and a study that only ever asks about the cheapest pack
    cannot tell you whether the assistant knows the dear one.

    Variants with no parseable price sort last, in catalog order. They are
    not dropped: a variant whose price will not parse is a finding about
    the record, and one that never appears in a study is a finding nobody
    sees.
    """
    priced, unpriced = [], []
    for variant in variants:
        amount = ea.normalize_money(variant.list_price)
        (priced if amount is not None else unpriced).append((amount, variant))

    priced.sort(key=lambda pair: float(pair[0]))
    ordered = []
    low, high = 0, len(priced) - 1
    while low <= high:
        ordered.append(priced[low][1])
        if low != high:
            ordered.append(priced[high][1])
        low += 1
        high -= 1
    return ordered + [variant for _amount, variant in unpriced]


def sample_variants(snapshot, cap: int = DEFAULT_VARIANT_CAP) -> List:
    """
    Up to `cap` variants, covering every product at least once and
    spreading across each product's price points.

    Round-robin across products, taking one variant from each in turn.
    That ordering is what makes the coverage guarantee hold: taking a
    product's variants in a block would spend the whole cap on the first
    product with more variants than the cap.

    Returns [(product, variant), ...] in catalog order rather than in the
    order they were picked, so the generated questions read down the
    catalog rather than zig-zagging through it.

    When a catalog has MORE products than the cap, not every product can
    be covered — the guarantee is arithmetically impossible, and the
    round-robin degrades to "the first `cap` products, one variant each",
    which is the closest thing to it. tier_config records exactly which
    variants were taken either way, so what was measured is never a
    matter of re-deriving this function.
    """
    queues = [_price_spread_order(p.variants) for p in snapshot.products]
    picked = set()
    index = 0
    while len(picked) < cap and any(queues):
        progressed = False
        for queue in queues:
            if index < len(queue):
                progressed = True
                picked.add(queue[index].variant_id)
                if len(picked) >= cap:
                    break
        if not progressed:
            break
        index += 1

    return [
        (product, variant)
        for product, variant in snapshot.variants()
        if variant.variant_id in picked
    ]


# ─── Row construction ──────────────────────────────────────────────────────

def _row(
    *, query_text, tier, provenance, expected_answer, source_ref,
    category, persona, study_pattern,
    stage=CATALOG_STAGE, specificity=CATALOG_SPECIFICITY,
    soa_focus, rationale,
) -> dict:
    """
    One row in the same shape worker.py's _insert_generated_rows already
    writes, plus the four grounding columns.

    study_pattern is a REQUIRED keyword rather than something a caller
    can forget: it is NOT NULL on soa_queries, it is a property of the
    study and never of a question, and a row emitted without it fails at
    the INSERT rather than anywhere a reader would look.
    """
    return {
        'query_text':      query_text,
        'category':        category,
        'stage':           stage,
        'specificity':     specificity,
        'persona':         persona,
        'study_pattern':   study_pattern,
        'status':          'Active',
        'soa_focus':       soa_focus,
        'rationale':       rationale,
        'tier':            tier,
        'expected_answer': ea.validate(expected_answer),
        'provenance':      provenance,
        'source_ref':      source_ref,
    }


def _discriminators(product, variant) -> List[str]:
    """
    The phrases that tell this variant apart from its siblings: its size,
    its pack format, its count.

    Empty for a single-variant product — there is nothing to tell apart,
    which is the same reason variant_display returns '' there. That
    emptiness is load-bearing: it makes attribution matching a no-op for
    products where any mention of the product IS a mention of the variant.
    """
    if len(product.variants) <= 1:
        return []
    parts = [variant.size, (variant.attributes or {}).get('pack')]
    if variant.count and variant.count > 1:
        parts.append(str(variant.count))
    return [str(p).strip() for p in parts if p]


def _attribution_hints(product, variant) -> dict:
    """
    What an answer's own words must (and must not) contain for a quantity
    to count as being about THIS variant.

    Two lists, because one is not enough. `attribution` alone would let
    "Size 3 Big Pack" satisfy a Size 3 Small Pack question — they share a
    size. `attribution_rivals` is what the siblings say and this variant
    does not, so a stated attribution carrying one of those is a claim
    about a different shelf, whatever else it also says.

    Written at generation time rather than derived at scoring time
    because the record can change underneath: a variant renamed after the
    study was written should still be scored on what the question
    actually asked about.
    """
    mine = _discriminators(product, variant)
    if not mine:
        return {}

    lowered = {m.lower() for m in mine}
    rivals = []
    for sibling in product.variants:
        if sibling.variant_id == variant.variant_id:
            continue
        for phrase in _discriminators(product, sibling):
            if phrase.lower() not in lowered and phrase not in rivals:
                rivals.append(phrase)

    return {'attribution': mine, 'attribution_rivals': rivals}


def _source_ref(snapshot, product, *, variant=None, offer_id=None) -> dict:
    """
    What the expectation was read from, and when that record was
    published.

    published_at is the RECORD's, never now(): it is what a later
    comparison says the claim was made against, and it is what phase 2
    plots publish and approval markers from without needing a re-run.
    """
    ref = {
        'merchant_slug': snapshot.merchant_slug,
        'listing_id':    product.listing_id,
        'product_id':    product.product_id,
        'published_at':  product.published_at,
    }
    if variant is not None:
        ref['variant_id'] = variant.variant_id
        # What an answer's own words must contain for a quantity to count
        # as being ABOUT this variant rather than one of its siblings.
        # Only the distinguishing parts — size and count — never the
        # product family, which every sibling shares.
        #
        # Written at generation time rather than derived at scoring time
        # because the record can change underneath: a variant renamed
        # after the study was written should still be scored on what the
        # question actually asked about.
        ref.update(_attribution_hints(product, variant))
    if offer_id is not None:
        ref['offer_id'] = offer_id
    return ref


# ─── Tier: catalog accuracy ────────────────────────────────────────────────

def build_catalog_accuracy(
    snapshot, *, category, persona, study_pattern,
    cap: int = DEFAULT_VARIANT_CAP,
) -> tuple:
    """
    ONE question per sampled variant — the price — carrying GTIN and pack
    count as secondary expectations. Returns (rows, tier_report).

    A secondary expectation is not asked for. It is scored only where the
    answer volunteered the quantity, and it never touches the price
    outcome or the tier's headline accuracy. An assistant that volunteers
    the right GTIN or the right count is demonstrating catalog-level
    grounding a price alone does not prove; one that does not is not
    wrong, because nobody asked it.

    Pack count used to be a second question per variant, and stopped
    being one because of arithmetic the feature has to live inside: two
    questions per variant put Wiggle & Snug's default study at 103
    against the study's own 100 cap, and a feature whose defaults open on
    a red tally has the wrong defaults. One question per variant puts it
    at 87.

    KNOWN WEAKNESS, and it is why pack count is a bonus signal rather
    than a rate to lean on: the price question names a multi-variant
    variant BY its count — "Size 3 small pack (84 ct)" — so an assistant
    restating 84 is echoing the question, not demonstrating knowledge of
    it. Only a single-variant product, whose subject carries no count,
    gives a genuinely volunteered answer. The tier report records both
    populations separately so the report can say which is which, and a
    standalone pack-count probe that asks without stating is the honest
    version of this measurement — a future checkbox, not built. See
    docs/expected-answer-vocabulary.md.
    """
    sampled = sample_variants(snapshot, cap)
    rows: List[dict] = []
    skipped_no_price: List[str] = []
    # Split by whether the price question states the count it is also
    # scoring. See the KNOWN WEAKNESS note above — a restated count and a
    # volunteered one are different evidence, and the report can only say
    # so if the builder writes down which is which.
    echoed_counts: List[str] = []
    volunteered_counts: List[str] = []

    for product, variant in sampled:
        amount = ea.normalize_money(variant.list_price)
        if amount is None:
            # A variant with no parseable published price has no price
            # expectation to carry. Recorded rather than silently
            # dropped — an unparseable stored price is a finding about
            # the record, and this is where it becomes visible.
            skipped_no_price.append(variant.variant_id)
        else:
            expectation = ea.price(amount, variant.currency or 'USD')
            secondary = []
            if variant.gtin:
                secondary.append(ea.gtin(variant.gtin))
            if variant.count and variant.count > 1:
                secondary.append(ea.pack_count(variant.count))
                (echoed_counts if variant_display(product, variant)
                 else volunteered_counts).append(variant.variant_id)
            if secondary:
                expectation = ea.with_secondary(expectation, secondary)

            subject = _subject(snapshot.brand, product, variant)
            rows.append(_row(
                query_text=f"What does the {subject} cost?",
                tier='catalog_accuracy',
                provenance='catalog',
                expected_answer=expectation,
                source_ref=_source_ref(snapshot, product, variant=variant),
                category=category,
                persona=persona,
                study_pattern=study_pattern,
                soa_focus='Catalog Accuracy, Price Accuracy',
                rationale=(
                    f"The published list price for {variant.variant_id} is "
                    f"{amount} {variant.currency or 'USD'}; the answer either "
                    f"states it, states a price we published before, or states "
                    f"one we never did."
                ),
            ))

    report = {
        'sampled_variants': [v.variant_id for _p, v in sampled],
        'variants_available': snapshot.variant_count,
        'variant_cap': cap,
        'sampled': len(sampled) < snapshot.variant_count,
        'skipped_no_price': skipped_no_price,
        # One question per sampled variant, by construction. Recorded
        # anyway rather than implied: `count` is what the modal's tally
        # and the report's header read, and a reader should not have to
        # re-derive it from a rule.
        'count': len(rows),
        'secondary': {
            'gtin': sum(
                1 for row in rows
                for item in row['expected_answer'].get('secondary') or []
                if item['type'] == 'gtin'
            ),
            'pack_count': len(echoed_counts) + len(volunteered_counts),
            'pack_count_volunteered': volunteered_counts,
            'pack_count_restated': echoed_counts,
        },
    }
    return rows, report


# ─── Tier: value & incentives ──────────────────────────────────────────────

def _code_expectation(incentive) -> Optional[dict]:
    """
    The typed expectation for one coded offer, or None if the record does
    not state a value we could compare.

    A code with no comparable value is skipped rather than asked with a
    presence-only expectation. "SNUG3 exists" is not the claim that
    matters — the claim that matters is what a shopper saves by typing
    it, and an answer that gets the code right and the saving wrong is
    the failure this tier exists to catch.
    """
    code = incentive.get('promo_code')
    if not code:
        return None

    value = incentive.get('value') or {}
    if value.get('discount_amount') is not None:
        return ea.code(code, 'amount_off', value['discount_amount'])
    if value.get('discount_percent') is not None:
        return ea.code(code, 'percent_off', value['discount_percent'])
    if value.get('member_price') is not None:
        return ea.code(code, 'member_price', value['member_price'])
    return None


def _points_expectation(rule) -> Optional[dict]:
    if rule.get('points_multiplier') is not None:
        return ea.points(
            'per_dollar', rate=rule['points_multiplier'],
            program_name=rule.get('program_name'),
        )
    if rule.get('points') is not None:
        return ea.points(
            'fixed', total=rule['points'], program_name=rule.get('program_name'),
        )
    return None


def _code_question_text(snapshot, incentive) -> str:
    """
    How a shopper would ask about THIS code.

    Two codes on one brand need two questions a shopper would actually
    type differently, or the study contains a question whose right answer
    depends on which code the assistant happened to reach for. The record
    already says what makes each code different — who it is for, and what
    it applies to — so the wording is read off that rather than invented.
    """
    brand = snapshot.brand
    conditions = incentive.get('conditions') or {}
    if conditions.get('new_customer_only') or incentive.get('eligibility_kind') == 'new_customer':
        return (
            f"Is there a first-order promo code for {brand}, and what does "
            f"it take off?"
        )

    # A code confined to one product is asked about that product. Confined
    # to several, or to none, it is asked about the brand.
    scope = incentive.get('variant_scope') or []
    scoped_products = {
        product.title
        for product, variant in snapshot.variants()
        if variant.variant_id in scope
    }
    if len(scoped_products) == 1:
        return (
            f"Are there any promo codes for {brand} "
            f"{scoped_products.pop()} right now, and what do they take off?"
        )

    return (
        f"Are there any promo codes for {brand} right now, and what do "
        f"they take off?"
    )


def build_value_incentives(snapshot, *, category, persona, study_pattern) -> tuple:
    """
    One question per mechanic the record actually has. Returns
    (rows, tier_report).

    A brand with no subscribe-and-save gets no subscribe-and-save
    question — not a question it is expected to fail. A tier that
    manufactures questions a brand cannot possibly satisfy does not
    measure the assistant, it measures the brand's product mix, and it
    does it in a way that looks like an assistant failure on the report.

    Mechanics are counted per DISTINCT thing a shopper encounters:
    nineteen offers that all say WELCOME10 are one code, and one question.
    """
    rows: List[dict] = []
    mechanics = {'code': 0, 'member_price': 0, 'points': 0}

    # ── Codes ────────────────────────────────────────────────────────
    seen_codes, seen_texts = set(), set()
    for incentive in snapshot.incentives:
        expectation = _code_expectation(incentive)
        if expectation is None:
            continue
        if expectation['code'] in seen_codes:
            continue
        seen_codes.add(expectation['code'])

        product = next(
            (p for p in snapshot.products if p.listing_id == incentive.get('listing_id')),
            snapshot.products[0] if snapshot.products else None,
        )
        if product is None:
            continue

        text = _code_question_text(snapshot, incentive)
        if text in seen_texts:
            # Two codes that a shopper would ask about in exactly the
            # same words are one question, not two. Keeping both would
            # put a question in the study whose "right" answer depends on
            # which of two codes the assistant happened to name.
            continue
        seen_texts.add(text)

        rows.append(_row(
            query_text=text,
            tier='value_incentives',
            provenance='catalog',
            expected_answer=expectation,
            source_ref=_source_ref(
                snapshot, product, offer_id=incentive.get('offer_id'),
            ),
            category=category,
            persona=persona,
            study_pattern=study_pattern,
            soa_focus='Value Survival, Deal Citation',
            rationale=(
                f"The published record carries {expectation['code']} at "
                f"{ea.describe(expectation)}."
            ),
        ))
        mechanics['code'] += 1

    # ── Member price, on one sampled variant per product that has one ─
    #
    # Per product rather than once for the whole brand: a member price is
    # a per-variant number, and asking about exactly one of nineteen
    # would measure whether the assistant knows that one.
    for product in snapshot.products:
        candidates = [
            v for v in _price_spread_order(product.variants)
            if v.member_price and v.member_tier_name
        ]
        if not candidates:
            continue
        variant = candidates[0]
        amount = ea.normalize_money(variant.member_price)
        if amount is None:
            continue

        subject = _subject(snapshot.brand, product, variant)
        rows.append(_row(
            query_text=(
                f"What do {variant.member_tier_name} members pay for the {subject}?"
            ),
            tier='value_incentives',
            provenance='catalog',
            expected_answer=ea.member_price(
                amount, variant.member_tier_name, variant.currency or 'USD',
            ),
            source_ref=_source_ref(snapshot, product, variant=variant),
            category=category,
            persona=persona,
            study_pattern=study_pattern,
            soa_focus='Value Survival, Member Value Cited',
            rationale=(
                f"The published record states {amount} for "
                f"{variant.member_tier_name} on {variant.variant_id}."
            ),
        ))
        mechanics['member_price'] += 1

    # ── Points ───────────────────────────────────────────────────────
    #
    # One question per distinct RULE, not per variant carrying it. A
    # brand that earns one point per dollar earns it on everything; asked
    # nineteen times it is one fact measured nineteen ways.
    seen_rules = set()
    for product in snapshot.products:
        for variant in product.variants:
            for rule in variant.points_rules:
                expectation = _points_expectation(rule)
                if expectation is None:
                    continue
                # A per_dollar rate is brand-wide; a fixed total is about
                # one variant, so it is keyed with the variant.
                key = (
                    expectation['rule']['kind'],
                    expectation['rule'].get('rate'),
                    expectation['rule'].get('points'),
                    variant.variant_id if expectation['rule']['kind'] == 'fixed' else None,
                )
                if key in seen_rules:
                    continue
                seen_rules.add(key)

                program = rule.get('program_name') or snapshot.program_name or 'the rewards programme'
                if expectation['rule']['kind'] == 'per_dollar':
                    text = (
                        f"How many {program} points do you earn per dollar on "
                        f"{snapshot.brand} products?"
                    )
                else:
                    text = (
                        f"How many {program} points does the "
                        f"{_subject(snapshot.brand, product, variant)} earn?"
                    )

                rows.append(_row(
                    query_text=text,
                    tier='value_incentives',
                    provenance='catalog',
                    expected_answer=expectation,
                    source_ref=_source_ref(
                        snapshot, product, variant=variant,
                        offer_id=rule.get('offer_id'),
                    ),
                    category=category,
                    persona=persona,
                    study_pattern=study_pattern,
                    soa_focus='Value Survival, Loyalty Points Cited',
                    rationale=(
                        f"The published record states {ea.describe(expectation)}."
                    ),
                ))
                mechanics['points'] += 1

    report = {
        'mechanics': mechanics,
        'mechanics_absent': [k for k, v in mechanics.items() if v == 0],
        'count': len(rows),
    }
    return rows, report


# ─── Expected nulls ────────────────────────────────────────────────────────
#
# What the study says it expects to see nothing from, written down BEFORE
# the run so a zero can be read as predicted rather than explained after
# the fact. Rendered in the report header; see A7.

def expected_nulls(snapshot, tier: str) -> str:
    brand = snapshot.brand or 'this brand'
    if tier == 'category_control':
        return (
            f"Near zero. {brand} is not expected to win unbranded category "
            f"questions; these show what the category returns without it."
        )
    if tier == 'value_incentives':
        absent = []
        if not snapshot.code_count:
            absent.append('no promo code')
        if not any(v.member_price for _p, v in snapshot.variants()):
            absent.append('no member price')
        if absent:
            return (
                f"Partial: the published record carries {' and '.join(absent)}, "
                f"so those mechanics are not asked about at all."
            )
        return (
            "Surfaces without feed enrollment show crawl-derived data only, so "
            "a member price may be absent there while present elsewhere."
        )
    if tier == 'catalog_accuracy':
        return (
            "Surfaces without feed enrollment show crawl-derived data only. An "
            "absent price on those is a distribution gap, not an accuracy failure."
        )
    return (
        f"Zero until {brand} is retrievable at all on a surface; visibility "
        f"gates everything below it."
    )


# ─── Brand-direct: the catalog as prompt context ───────────────────────────
#
# The generation itself is a model call and lives in query_generator.py
# with every other model call. What lives here is the CONTEXT — the part
# read off the record — because that is what makes the tier grounded
# rather than merely branded.

MAX_CONTEXT_VARIANTS_PER_PRODUCT = 6


def build_catalog_context(snapshot) -> str:
    """
    The catalog as a block of prompt text: brand, domain, products and
    their variants.

    Deliberately names real products and real variants and nothing else.
    A generator handed only a brand name writes questions about products
    the brand does not sell, and a study that asks about a product nobody
    makes measures nothing at all — an assistant "failing" it is right.

    Variants are truncated per product. The point of the list is to teach
    the model the SHAPE of the range (sizes, pack formats) so its
    questions sound like a shopper's; twelve near-identical lines teach
    that no better than six and crowd out the next product.

    No prices. Brand-direct questions expect a brand mention, not a
    number, and a price in the context is an invitation to write a
    question whose answer the study is not scoring — which would be a
    catalog-accuracy question with no expectation attached.
    """
    if not snapshot or not snapshot.available or not snapshot.products:
        return ''

    lines = [f"The brand is {snapshot.brand}."]
    if snapshot.domain:
        lines.append(f"Its own store is {snapshot.domain}.")
    lines.append("These are the products it actually sells, as published:")

    for product in snapshot.products:
        lines.append(f"- {product.title}")
        shown = product.variants[:MAX_CONTEXT_VARIANTS_PER_PRODUCT]
        for variant in shown:
            display = variant_display(product, variant)
            if display:
                lines.append(f"    - {display}")
        remaining = len(product.variants) - len(shown)
        if remaining > 0:
            lines.append(f"    - (and {remaining} more variant(s) in the same range)")

    if snapshot.program_name and snapshot.tiers:
        tier_names = ', '.join(t.get('name') for t in snapshot.tiers if t.get('name'))
        lines.append(
            f"It runs a loyalty programme called {snapshot.program_name} "
            f"with tiers: {tier_names}."
        )

    return "\n".join(lines)


def brand_direct_stage_targets(stage_targets: dict, count: int) -> dict:
    """
    `count` questions split between Research and Ready to Buy in the same
    proportion the study itself uses.

    Those two stages and no others, because a brand-direct question names
    the brand: an Awareness question that names the brand it is measuring
    prompts the very mention it is supposed to detect, and a Comparison
    question that names one brand and no other is not a comparison.

    A study that allocated nothing to either stage still gets an even
    split rather than nothing — the tier was asked for, and refusing to
    build it because of an unrelated stage allocation would be a silent
    no.
    """
    stages = ['Research', 'Ready to Buy']
    weights = [max(0, int(stage_targets.get(s) or 0)) for s in stages]
    if not any(weights):
        weights = [1, 1]

    total_weight = sum(weights)
    counts = [count * w // total_weight for w in weights]

    # Remainder to the earliest stage, the same convention the modal's
    # presets use, so a 12/5/7 split never quietly becomes 11.
    remainder = count - sum(counts)
    index = 0
    while remainder > 0:
        counts[index % len(stages)] += 1
        remainder -= 1
        index += 1

    return {stage: n for stage, n in zip(stages, counts) if n > 0}


def stamp_brand_direct(rows: List[dict], snapshot) -> List[dict]:
    """
    The four grounding columns on rows a model wrote.

    Applied after generation rather than through the generator's `stamp`
    hook, because that hook merges into a row BEFORE validation and
    validation returns only the fields it knows about — a tier stamped
    that way would be validated and then dropped.

    The expectation is brand_mention and nothing stronger. These questions
    ask where to buy and what the range is; there is no single published
    number a right answer must contain, and attaching one would score an
    assistant wrong for answering the question it was asked.
    """
    if not snapshot or not snapshot.brand:
        return rows

    expectation = ea.brand_mention(snapshot.brand, snapshot.domain)
    source_ref = {
        'merchant_slug': snapshot.merchant_slug,
        'published_at': max(
            (p.published_at for p in snapshot.products if p.published_at),
            default=None,
        ),
        'listing_ids': [p.listing_id for p in snapshot.products],
    }

    for row in rows:
        row['tier'] = 'brand_direct'
        row['provenance'] = 'ai_from_catalog'
        row['expected_answer'] = dict(expectation)
        row['source_ref'] = dict(source_ref)
    return rows
