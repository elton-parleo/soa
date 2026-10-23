"""
Layer 2, step 2 and 3: compare, then classify.

Given a typed expectation, a stored extraction record, and the
publication history for what the expectation was read from, decide what
this (question x surface x sample) is.

For an expectation naming a published VALUE — a price, a code, a count —
one of five:

    exact        matches the currently published record
    stale        matches a PRIOR published value
    wrong        matches no published value, ever
    absent       the quantity was not addressed
    unscoreable  extraction could not confidently read the answer

For a brand-direct question, which names no value at all, one of the
brand assessments in scoring/brand_direct_classifier.py. Scoring those on
presence is what let an answer reading "not a real or widely recognized
brand" count as a success.

Deterministic. No model, no network, no clock. The same stored extraction
produces the same verdict today and in six months, which is what makes a
stored outcome re-checkable rather than merely re-runnable — and it is why
the validation harness can hand a human the extraction and the answer and
have them check the only judgement in the loop.

`unscoreable` is its own bucket and is never folded into `wrong`. "The
assistant was incorrect" and "we could not tell what it said" are
different facts; merging them inflates the error rate with our own
extraction failures and hides a degrading extractor behind a falling
accuracy number nobody can attribute.

See docs/expected-answer-vocabulary.md, which this module is the
executable form of.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from soa_shared import expected_answers as ea
from soa_shared import per_unit as pu
from scoring import answer_flags as af
from scoring import brand_direct_classifier as bdc
from scoring import record_variants as rv
from scoring import retailer_reference as rr
from scoring import variant_rules as vr

logger = logging.getLogger(__name__)

EXACT = 'exact'
STALE = 'stale'
WRONG = 'wrong'
ABSENT = 'absent'
UNSCOREABLE = 'unscoreable'
#: 2B. See soa_shared/expected_answers.py VALUE_OUTCOMES.
PARTIAL = 'partial'
UNVERIFIABLE = 'unverifiable'

#: Which claim decides a question when an answer makes several. A match
#: to something we published beats an approximation, an approximation
#: beats a miss, and a miss beats "we could not check" — the same order
#: the engine's checkQuote keeps (exact > partial > wrong > none), with
#: stale placed beside exact because it IS an exact match, to an earlier
#: publication.
#: 2N-1: a per-unit quote's own claim outcome, outside scored and outside
#: wrong (soa_shared/per_unit.py); a run of nothing else is unscoreable,
#: reason per_unit.
PER_UNIT = pu.PER_UNIT
_RANK = {EXACT: 6, STALE: 5, PARTIAL: 4, WRONG: 3, UNVERIFIABLE: 2, UNSCOREABLE: 1, PER_UNIT: 0}

#: Reason codes the 2B rules write, for the drill-down and the console.
REASON_PRODUCT_INFERRED = 'product_inferred'
REASON_VARIANT_CLASH = 'variant_clash'
REASON_VARIANT_SWAP = 'variant_swap'
REASON_NOT_OUR_PRODUCT = 'not_our_product'
REASON_PER_UNIT = pu.PER_UNIT
REASON_OTHER_BRAND = 'other_brand'


@dataclass
class Verdict:
    outcome: str
    reason: str
    #: For a STALE outcome, when the value it matched was published.
    matched_published_at: Optional[str] = None
    #: brand_domain | retailer | none — derived from sources_cited.
    source_attribution: Optional[str] = None
    #: Whether the brand's own domain was among the cited sources. Kept
    #: separate from the outcome on a brand_mention expectation: "did it
    #: know the brand" and "did it send the shopper to the brand's own
    #: store" are different questions.
    domain_cited: Optional[bool] = None
    #: The right promotion code, the wrong terms. Wrong, but a different
    #: kind of wrong from a code that does not exist, and counted apart
    #: from it — see the `code` branch of compare().
    near_miss: bool = False
    secondary: List[dict] = field(default_factory=list)
    #: 2B: answer-level flags (ea.ANSWER_FLAGS) with their evidence, e.g.
    #: {'flag': 'fabricated_citation', 'domains': [...]}. Never change the
    #: outcome.
    flags: List[dict] = field(default_factory=list)
    #: 2B: every price claim and what it was judged against, for the
    #: drill-down and the console's checks. Empty for non-price types.
    claims: List[dict] = field(default_factory=list)
    #: 2B: cited domains split own_domain / listed_retailer / other.
    source_split: Optional[dict] = None
    #: 2B: a short reason code ('product_inferred', 'variant_clash',
    #: 'variant_swap', 'not_our_product', 'other_brand') when a rule decided
    #: the outcome.
    reason_code: Optional[str] = None

    @property
    def flag_names(self) -> List[str]:
        return [f['flag'] for f in self.flags]


# ─── Attribution ───────────────────────────────────────────────────────────

_NOISE = re.compile(r'[^a-z0-9]+')


def _tokens(text) -> set:
    if not text:
        return set()
    return {t for t in _NOISE.sub(' ', str(text).lower()).split() if t}


def _phrase_present(phrase_tokens, stated_tokens) -> bool:
    """A phrase is present when every one of its tokens is. 'Size 1' is
    not present in 'Size 3 small pack' merely because 'size' is."""
    return bool(phrase_tokens) and phrase_tokens <= stated_tokens


def attributes_to(stated_product, hints) -> bool:
    """
    Whether an extracted quantity was attributed to the variant the
    question asked about.

    `hints` is (mine, rivals): the phrases that distinguish this variant,
    and the phrases its siblings use that it does not.

    Loose on wording, strict on identity. The extracted string is whatever
    the answer called the product — "the 84 count pack", "Size 3 Small
    Pack", "Snug-Fit Size 3" — so exact matching would fail on almost
    every real answer. The rule is instead:

      * at least one of THIS variant's distinguishing phrases is present,
      * and none of its siblings' are.

    Both halves are needed. Without the first, any mention of the product
    family would satisfy a question about one variant of twelve, each at
    a different price. Without the second, "Size 3 Big Pack" would satisfy
    a Size 3 Small Pack question — they share a size — which is exactly
    the wrong-product-attribution case this exists to catch.

    An unattributed quantity counts as attributed: a response about one
    product that says "it costs $22.99" has attributed that price by
    context, and refusing to score it would throw away the commonest
    shape of a correct answer.

    No hints at all is also a match. That covers a single-variant product,
    where there is nothing to tell apart, and a source_ref written before
    hints existed — which must not make every answer wrong for a reason
    nobody recorded.
    """
    mine, rivals = hints
    if not stated_product or not mine:
        return True

    stated = _tokens(stated_product)
    if any(_phrase_present(rival, stated) for rival in rivals):
        return False
    return any(_phrase_present(phrase, stated) for phrase in mine)


def variant_terms_from(source_ref: Optional[dict], expectation: dict) -> tuple:
    """
    (mine, rivals) as token sets, from the hints the generator wrote onto
    source_ref. ([], []) when it wrote none, which makes attribution
    matching a no-op rather than a guess.
    """
    ref = source_ref or {}
    mine = [_tokens(h) for h in (ref.get('attribution') or []) if h]
    rivals = [_tokens(h) for h in (ref.get('attribution_rivals') or []) if h]
    return [m for m in mine if m], [r for r in rivals if r]


# ─── Source attribution ────────────────────────────────────────────────────

def classify_sources(sources_cited, brand_domain) -> tuple:
    """
    (source_attribution, domain_cited) from the domains an answer cited.

    'brand_domain' whenever the brand's own store is among them, even
    alongside retailers: the question the report asks is whether the
    brand's own surface reached the answer at all, and a brand cited
    beside three retailers did.
    """
    domains = {str(d).strip().lower().lstrip('.') for d in (sources_cited or []) if d}
    domains = {d[4:] if d.startswith('www.') else d for d in domains}

    if not domains:
        return 'none', (False if brand_domain else None)

    if not brand_domain:
        # Nothing to compare against — say 'retailer' for the sources
        # that exist, and leave domain_cited NULL rather than False: we
        # did not fail to find the brand domain, we never had one.
        return 'retailer', None

    target = str(brand_domain).strip().lower().lstrip('.')
    target = target[4:] if target.startswith('www.') else target
    cited = any(d == target or d.endswith('.' + target) for d in domains)
    return ('brand_domain' if cited else 'retailer'), cited


# ─── Per-type comparison ───────────────────────────────────────────────────
#
# Each returns (matched_current, stated_values) where stated_values is
# every value the answer stated for this quantity, normalised. The
# classifier uses the second half to decide stale-versus-wrong, so a
# comparison that returned only a boolean would have thrown away exactly
# what staleness needs.

def _price_values(extraction, expectation, terms) -> List[str]:
    out = []
    for entry in extraction.get('prices') or []:
        if not attributes_to(entry.get('attributed_product'), terms):
            continue
        amount = ea.normalize_money(entry.get('amount'))
        if amount is None:
            continue
        stated_currency = ea.normalize_currency(entry.get('currency'))
        # A currency the answer did not state is not a mismatch: a bare
        # "$22.99" in a USD study is the ordinary way to write it, and
        # failing it would measure punctuation.
        if stated_currency and stated_currency != expectation['currency']:
            continue
        out.append(amount)
    return out


def _pack_count_values(extraction, _expectation, terms) -> List[int]:
    out = []
    for entry in extraction.get('pack_counts') or []:
        if not attributes_to(entry.get('attributed_product'), terms):
            continue
        value = ea.normalize_count(entry.get('value'))
        if value is not None:
            out.append(value)
    return out


def _member_price_values(extraction, expectation, terms) -> tuple:
    """
    (values at the right tier, values at any tier).

    Both, because they classify differently. A correct amount at the
    wrong tier is `wrong` — a shopper told the entry tier gets the top
    tier's price has been misinformed about the thing the tier exists to
    signal — but it is not `absent`, and calling it absent would hide a
    real error.
    """
    wanted_tier = ea.normalize_tier_name(expectation.get('tier_name'))
    right_tier, any_tier = [], []

    for entry in extraction.get('member_prices') or []:
        if not attributes_to(entry.get('attributed_product'), terms):
            continue
        amount = ea.normalize_money(entry.get('amount'))
        if amount is None:
            continue
        any_tier.append(amount)
        stated = ea.normalize_tier_name(entry.get('tier'))
        # A tier the answer did not name is accepted: "members pay
        # $16.84" on a brand with one paying tier is a correct answer,
        # and there is nothing to disagree with.
        if stated is None or stated == wanted_tier:
            right_tier.append(amount)

    return right_tier, any_tier


def _code_match(extraction, expectation) -> tuple:
    """
    (code_seen, value_matched).

    Split, because a right code with a wrong value is `wrong` and not
    `absent`: an answer that sends a shopper to checkout expecting the
    wrong saving has failed in the way that costs the merchant, and it is
    a different failure from never mentioning the code.
    """
    wanted_code = expectation['code']
    wanted_value = expectation['value']
    wanted_kind = expectation['value_kind']

    code_seen = False
    for entry in extraction.get('codes') or []:
        if ea.normalize_code(entry.get('code')) != wanted_code:
            continue
        code_seen = True

        stated_kind = entry.get('value_kind')
        # A kind the answer did not state is not a mismatch on its own;
        # a kind it stated differently is.
        if stated_kind and stated_kind != wanted_kind:
            continue
        stated_value = ea.normalize_money(entry.get('value'))
        if stated_value is not None and stated_value == wanted_value:
            return True, True

    return code_seen, False


def _points_match(extraction, expectation) -> tuple:
    """(rule_seen, matched). program_name is never compared — see the
    vocabulary doc: programmes are paraphrased far more freely than tiers
    are, and failing a correct rate over "the rewards programme" would
    measure paraphrase, not accuracy."""
    rule = expectation['rule']
    seen = False

    for entry in extraction.get('points') or []:
        value = entry.get('value')
        if value is None:
            continue
        seen = True
        per_dollar = entry.get('per_dollar')

        if rule['kind'] == 'per_dollar':
            if per_dollar is False:
                continue
            if ea.normalize_money(value) == rule['rate']:
                return True, True
        else:
            if per_dollar is True:
                continue
            if ea.normalize_count(value) == rule['points']:
                return True, True

    return seen, False


# ─── Publication history ───────────────────────────────────────────────────

def _prior_match(history, values, *, member: bool = False) -> Optional[str]:
    """
    The published_at of the newest PRIOR publication whose value is among
    `values`, or None.

    Prior means "not the current record": history is oldest-first, so
    everything but the last entry is prior. A value matching only the
    current record is `exact` and never reaches here.

    Newest-first among the matches, because "it is showing last week's
    price" is a more useful and more likely reading than "it is showing
    the price from March", and the row records which one so the claim is
    checkable either way.
    """
    if not history or not values:
        return None

    wanted = set(values)
    prior = list(history)[:-1] if len(history) > 1 else []
    for point in reversed(prior):
        value = point.get('member_price') if member else point.get('list_price')
        normalized = ea.normalize_money(value)
        if normalized is not None and normalized in wanted:
            return point.get('published_at')
    return None


# ─── The classifier ────────────────────────────────────────────────────────

# ─── 2B: price claims ──────────────────────────────────────────────────────

def _price_claims(extraction, expectation, *, member: bool, terms) -> tuple:
    """
    (claims, any_tier_amounts). A claim is one stated price this question
    could be about: {raw, amount, product, tier}. Currency is filtered
    exactly as it always was; a member price at a NAMED other tier is not a
    claim about this one, but its amount is kept so the legacy
    "right amount, wrong tier" verdict survives.

    any_tier keeps main's _member_price_values filter exactly: only an
    amount attributed to the asked variant. Without it, "2% reward on
    eligible purchases made at Costco" scored a Member+ price wrong.
    """
    claims, any_tier = [], []
    if member:
        wanted_tier = ea.normalize_tier_name(expectation.get('tier_name'))
        for entry in extraction.get('member_prices') or []:
            amount = ea.normalize_money(entry.get('amount'))
            if amount is not None and attributes_to(entry.get('attributed_product'), terms):
                any_tier.append(amount)
            stated = ea.normalize_tier_name(entry.get('tier'))
            if stated is not None and stated != wanted_tier:
                continue
            claims.append({'raw': entry.get('amount'), 'amount': amount,
                           'product': entry.get('attributed_product'), 'tier': entry.get('tier')})
        return claims, any_tier
    for entry in extraction.get('prices') or []:
        stated_currency = ea.normalize_currency(entry.get('currency'))
        if stated_currency and stated_currency != expectation['currency']:
            continue
        claims.append({'raw': entry.get('amount'),
                       'amount': ea.normalize_money(entry.get('amount')),
                       'product': entry.get('attributed_product'), 'tier': None})
    return claims, any_tier


def _judge_record(claim, *, current, history, member) -> tuple:
    """One claim against the RECORD. (outcome, matched_published_at)."""
    amount = claim['amount']
    if current is not None and amount == current:
        return EXACT, None
    matched_at = _prior_match(history, [amount], member=member)
    if matched_at:
        return STALE, matched_at
    # Rules 1 and 4: whole-dollar, within fifty cents of the current value.
    if current is not None and vr.rounds_to(claim['raw'], current):
        return PARTIAL, None
    return WRONG, None


def _judge_price_like(expectation, extraction, *, member, terms, history, history_for,
                      source_ref, record_variants, reference, brand_facts=None):
    """
    The price and member_price comparison, with the 2B rules.

    Returns (outcome, reason, matched_at, claims, swapped, reason_code).

    Each claim is first assigned to a variant:

      asked     no conflict with the asked variant (the generator's hints
                and, with the record supplied, rule 2's clash checks)
      swap      it conflicts, and names exactly one other record variant
      clash     it conflicts, and names no variant in the record: OUR
                product, with a variant descriptor the record lacks
      not_ours  it conflicts, names no record variant, and
                does not name our product at all: absent, as on main
      ignored   it conflicts and there is no record to say which variant
                it names — the legacy filter, unchanged

    then judged against that variant's reference: the record (hosted), or
    the retailer page the expectation is attributed_to (2B external).
    """
    ref = source_ref or {}
    attributed_to = expectation.get('attributed_to')
    claims, any_tier = _price_claims(extraction, expectation, member=member, terms=terms)
    asked = rv.find(record_variants, ref.get('variant_id')) if record_variants else None
    out = []

    def judge_retailer(claim, variant_id, gtin):
        if reference is None:
            return UNVERIFIABLE, 'no retailer-prices reference was read for this cycle', None
        keys = {'gtin': gtin or variant_id, 'variant_ref': ref.get('variant_ref')}
        row = reference.row(attributed_to, **keys)
        prior = reference.prior_row(attributed_to, **keys)
        outcome, why = rr.judge_claim(claim['raw'], row=row, prior=prior, member=member)
        reference_row = row.as_dict() if row else None
        if reference_row is not None:
            reference_row['against'] = row.value(member)
            # 2K-1: the brand's own page sets no price; the claim is not scored
            if outcome == UNSCOREABLE and rr.brand_sets_no_price(row):
                reference_row['reason_code'] = rr.REASON_BRAND_SETS_NO_PRICE
        return outcome, why, reference_row

    spans = [str(sp.get('text') or '') for sp in extraction.get('spans') or [] if isinstance(sp, dict)]
    asked_row = reference.row(attributed_to, gtin=ref.get('gtin') or ref.get('variant_id'),
                              variant_ref=ref.get('variant_ref')) if attributed_to and reference is not None else None
    against = (asked_row.value(member) if asked_row is not None and asked_row.verifiable else None) \
        if attributed_to else expectation.get('amount')
    for claim in claims:
        product = claim['product']
        if claim['amount'] is None and not attributed_to:
            continue  # legacy: a non-price amount was never a claim
        entry = {'stated': claim['raw'], 'amount': claim['amount'], 'product': product,
                 'tier': claim['tier']}
        # 2N-1: a per-unit quote ("$0.33 per diaper") is not the pack's price: its own outcome
        if pu.is_per_unit(claim['raw'], product, spans, against):
            entry.update(target='asked', variant_id=ref.get('variant_id'), outcome=PER_UNIT, reason=pu.NOTE,
                         reason_code=REASON_PER_UNIT)
            out.append(entry)
            continue
        # 2N-1: a pronoun names no product (rule 3's inferred product); a
        # description of ours ("the NB 84-count option") names the asked variant
        if rv.is_pronoun(product):
            product = None
        attributed = attributes_to(product, terms) or (
            asked is not None and rv.describes_asked(product, asked))
        if asked is not None and product:
            why = rv.conflicts(product, asked, hints_attribute=attributed)
            # 2N-1: the retailer page's own title for the variant names it
            if why is not None and asked_row is not None and rv.in_title(product, asked_row.title):
                why = None
        else:
            why = None if attributed else 'names a sibling variant'

        if why is None:
            entry['target'] = 'asked'
            entry['variant_id'] = ref.get('variant_id')
            if attributed_to:
                outcome, reason, row = judge_retailer(
                    claim, ref.get('variant_id'), ref.get('gtin'))
                entry.update(outcome=outcome, reason=reason, reference=row, matched_at=None)
                if row and row.get('reason_code'):
                    entry['reason_code'] = row.pop('reason_code')
            else:
                outcome, matched_at = _judge_record(
                    claim, current=expectation['amount'], history=history, member=member)
                entry.update(outcome=outcome, matched_at=matched_at, against=expectation['amount'])
            # Rule 3: a claim attached to no product can never be wrong.
            if entry['outcome'] == WRONG and not product:
                entry.update(outcome=UNSCOREABLE, reason_code=REASON_PRODUCT_INFERRED,
                             reason='the answer attached this price to no product; '
                                    'a mismatch on an inferred product is not scored wrong')
        elif asked is None:
            continue  # legacy: no record to say which variant it names
        else:
            named = rv.named_variant(product, asked, record_variants)
            entry['conflict'] = why
            if named is None and not rv.names_our_product(
                    product, record_variants, brand_facts):
                # Rule 2 narrowed: a retailer program, an unnamed "pack" or
                # another brand is not a variant of ours to clash with.
                entry.update(target='not_ours', outcome=ABSENT, reason_code=REASON_NOT_OUR_PRODUCT,
                             reason=f"{product!r} is not our product")
            elif named is None and not rv.carries_descriptor(
                    product, asked, terms[1]):
                continue  # our product, no variant stated: dropped, as on main
            elif named is None:
                entry.update(target='clash', outcome=WRONG, reason_code=REASON_VARIANT_CLASH,
                             reason=f"{why}, and the record has no such variant")
            else:
                entry.update(target='swap', variant_id=named.variant_id,
                             same_group=named.group == asked.group)
                if attributed_to:
                    outcome, reason, row = judge_retailer(claim, named.variant_id, named.gtin)
                    entry.update(outcome=outcome, reason=reason, reference=row)
                else:
                    current = named.member_price if member else named.list_price
                    sibling_history = history_for(named.variant_id) if history_for else None
                    outcome, matched_at = _judge_record(
                        claim, current=current, history=sibling_history, member=member)
                    entry.update(outcome=outcome, matched_at=matched_at, against=current)
                # Rule 2: a swapped claim is never exact. Whether it is the
                # named variant's price is kept beside the outcome; the
                # outcome is what it says about the variant ASKED about.
                # Right for a sibling variant of the same product: partial.
                # Right for a different product: still wrong.
                priced_as_named = entry['outcome'] in (EXACT, STALE, PARTIAL)
                entry['priced_as_named'] = priced_as_named
                if priced_as_named:
                    entry['outcome'] = PARTIAL if entry['same_group'] else WRONG
        out.append(entry)

    swapped = any(c['target'] == 'swap' for c in out)
    asked_claims = [c for c in out if c['target'] == 'asked']

    if asked_claims:
        best = max(asked_claims, key=lambda c: _RANK[c['outcome']])
        outcome = best['outcome']
        stated = [str(c['stated']) for c in asked_claims]
        label = expectation['amount'] if not member else ea.describe(expectation)
        if outcome == PER_UNIT:
            return UNSCOREABLE, pu.NOTE, None, out, swapped, REASON_PER_UNIT
        if outcome == EXACT:
            reason = best.get('reason') or (
                f"stated {expectation['amount']}" if not member
                else f"stated {ea.describe(expectation)}")
            return EXACT, reason, None, out, swapped, None
        if outcome == STALE:
            matched = [c for c in asked_claims if c['outcome'] == STALE]
            if attributed_to:
                return STALE, best['reason'], None, out, swapped, None
            matched_at = _prior_match(history, [c['amount'] for c in matched], member=member)
            joined = ', '.join(str(c['amount']) for c in matched)
            reason = (f"stated {joined}; we published that on {matched_at}" if not member else
                      f"stated {joined} for {expectation['tier_name']}; we published that on {matched_at}")
            return STALE, reason, matched_at, out, swapped, None
        if outcome == PARTIAL:
            return PARTIAL, best.get('reason') or (
                f"stated {best['stated']}, whole-dollar within 50 cents of {label}"), \
                None, out, swapped, None
        if outcome == WRONG:
            if attributed_to:
                return WRONG, best['reason'], None, out, swapped, None
            values = ', '.join(str(c['amount']) for c in asked_claims
                               if c['outcome'] == WRONG and c['amount'] is not None)
            if member:
                return WRONG, (f"stated {values}; the record says "
                               f"{expectation['amount']} for {expectation['tier_name']}"), \
                    None, out, swapped, None
            return WRONG, (f"stated {values}; we have never published that "
                           f"(current: {expectation['amount']})"), None, out, swapped, None
        # UNVERIFIABLE or UNSCOREABLE: say why, with the code when a rule decided it.
        return outcome, best.get('reason') or f"stated {', '.join(stated)}", None, out, swapped, \
            best.get('reason_code')

    swaps = [c for c in out if c['target'] in ('swap', 'clash')]
    if swaps:
        best = max(swaps, key=lambda c: _RANK[c['outcome']])
        code = REASON_VARIANT_CLASH if best['target'] == 'clash' else REASON_VARIANT_SWAP
        if best['target'] == 'clash':
            reason = f"stated {best['stated']} for {best['product']!r}: {best['reason']}"
        else:
            if not best['priced_as_named']:
                verdict = 'not its price either'
            elif best['same_group']:
                verdict = "its price, a sibling variant of the same product"
            else:
                verdict = 'its price, a different product'
            reason = (f"stated {best['stated']} for {best['product']!r}, which is "
                      f"{best['variant_id']} ({best['conflict']}): {verdict}")
        return best['outcome'], reason, None, out, swapped, code

    if member and any_tier:
        if expectation['amount'] in any_tier:
            return WRONG, (f"stated {expectation['amount']} but attributed it to another "
                           f"tier, not {expectation['tier_name']}"), None, out, swapped, None
        return WRONG, (f"stated {', '.join(any_tier)}; the record says "
                       f"{expectation['amount']} for {expectation['tier_name']}"), \
            None, out, swapped, None
    not_ours = [c for c in out if c['target'] == 'not_ours']
    if not_ours:
        label = 'member price' if member else 'price'
        return ABSENT, (f"the answer stated no {label} for this product; "
                        f"{', '.join(repr(c['product']) for c in not_ours)} is not our product"), \
            None, out, swapped, REASON_NOT_OUR_PRODUCT
    if attributed_to and claims and all(c['amount'] is None for c in claims):
        return UNSCOREABLE, 'the answer stated a price this could not read as one', \
            None, out, swapped, None
    label = 'member price' if member else 'price'
    return ABSENT, f'the answer stated no {label} for this product', None, out, swapped, None


# ─── Other brands ──────────────────────────────────────────────────────────

def _drop_other_brand_claims(extraction, brand_facts) -> tuple:
    """
    (extraction without other brands' prices, the attributed_products
    dropped). A price or member price whose attributed_product names a
    brand from the stored Layer 2 `other_brands_named` (the full name,
    whatever its relation) is that brand's, never ours, whatever size or
    count phrase it carries: "Huggies Size 3" is not our Size 3. A claim
    that ALSO names our brand or one of our product names keeps its
    ordinary path. Deterministic; reads only what Layer 2 stored.
    """
    facts = brand_facts or {}
    ours = [_tokens(facts.get('brand'))] + [
        {t for t in _tokens(title) if t.isalpha()} for title in facts.get('product_titles') or []]
    ours = [name for name in ours if name]
    others = [_tokens(e.get('name')) for e in extraction.get('other_brands_named') or []
              if isinstance(e, dict) and e.get('relation') != 'not_a_brand']
    others = [name for name in others if name and name not in ours]
    if not others:
        return extraction, []

    def is_other(entry):
        stated = _tokens(entry.get('attributed_product'))
        return (any(name <= stated for name in others)
                and not any(name <= stated for name in ours))

    dropped, kept = [], dict(extraction)
    for key in ('prices', 'member_prices'):
        entries = extraction.get(key) or []
        kept[key] = [e for e in entries if not (isinstance(e, dict) and is_other(e))]
        dropped += [e.get('attributed_product') for e in entries if isinstance(e, dict) and is_other(e)]
    return kept, dropped


# ─── The classifier ────────────────────────────────────────────────────────

def compare(expectation: dict, extraction: dict, *, history=None,
            source_ref=None, brand_domain=None, tier=None,
            brand_facts=None, record_variants=None, history_for=None,
            reference=None, retrieved_sources=None, dead_domains=None,
            grounding=None) -> Verdict:
    """
    One (question x surface x sample) -> one outcome.

    Which vocabulary the outcome comes from depends on the tier. A
    catalog or value question names a published number and lands in
    exact/stale/partial/wrong/absent/unscoreable/unverifiable. A
    brand-direct question names no number at all, and landing it in the
    same buckets is what produced a 95% success rate on a brand two of 66
    answers had actually read: see scoring/brand_direct_classifier.py.

    `history` is [{published_at, list_price, member_price, ...}, ...] for
    the variant, oldest first, as
    GET /merchants/{slug}/price-history serves it. Absent, a mismatch is
    `wrong` rather than `stale` — the conservative direction and the
    honest one: without a record saying a value was once published we
    cannot claim it was.

    2B additions, all keyword-only and all optional, so a caller that
    passes none of them gets the pre-2B verdict except where rules 1 and
    3 apply (they need nothing but the claim):

      record_variants  [RecordVariant] from the snapshot — enables rule 2
      history_for      variant_id -> history, for a swapped claim's variant
      reference        retailer_reference.ReferenceSet, for an expectation
                       carrying attributed_to
      retrieved_sources the run's grounding URLs, for the source split
      dead_domains     {domain: check} from citation_check, already run
      grounding        the run's soa_runs.grounding (runners/grounding.py),
                       for a brand-direct claim backed by a platform source
    """
    verdict = _compare_core(
        expectation, extraction, history=history, source_ref=source_ref,
        brand_domain=brand_domain, tier=tier, brand_facts=brand_facts,
        record_variants=record_variants, history_for=history_for, reference=reference,
        grounding=grounding,
    )
    _decorate(verdict, expectation, extraction, source_ref=source_ref,
              brand_domain=brand_domain, retrieved_sources=retrieved_sources,
              dead_domains=dead_domains, brand_facts=brand_facts, grounding=grounding)
    return verdict


def _retrieved(retrieved_sources, grounding) -> list:
    """The run's sources for the split. Where grounding names a source's
    site, that site; a redirect URL's own host names Google, not the page,
    so an unresolved redirect is left out rather than counted as 'other'."""
    sources = (grounding or {}).get('sources') if isinstance(grounding, dict) else None
    if not sources:
        return list(retrieved_sources or [])
    return [s['domain'] for s in sources if isinstance(s, dict) and s.get('domain')]


def _decorate(verdict, expectation, extraction, *, source_ref, brand_domain,
              retrieved_sources, dead_domains, brand_facts=None, grounding=None) -> None:
    """The answer-level 2B results: source split, and the flags."""
    ref = source_ref or {}
    own_domain = ref.get('own_domain') or expectation.get('domain') or brand_domain
    owned = [own_domain] + [d for d in ((brand_facts or {}).get('own_domains') or [])
                            + ((brand_facts or {}).get('tenant_own_domains') or []) if d != own_domain]
    retailer_list = ref.get('retailer_list') or []
    domains = af.cited_domains(extraction.get('sources_cited'),
                               _retrieved(retrieved_sources, grounding))
    if domains:
        verdict.source_split = af.source_split(
            domains, own_domain=owned, retailer_list=retailer_list)

    if 'retailer_list' in ref:
        availability = af.fabricated_availability(
            extraction.get('retailer_mentions') or [
                {'name': n, 'role': None} for n in extraction.get('recommended_retailers') or []
            ],
            retailer_list=retailer_list, own_domain=ref.get('own_domain'),
            merchant_kind=ref.get('merchant_kind'),
        )
        if availability['fabricated']:
            verdict.flags.append({'flag': 'fabricated_availability',
                                  'retailers': availability['fabricated'],
                                  'unrecognised': availability['unrecognised']})

    dead = [dead_domains[d] for d in af.cited_domains(extraction.get('sources_cited'))
            if dead_domains and d in dead_domains]
    if dead:
        verdict.flags.append({'flag': 'fabricated_citation', 'domains': dead})

    if any(c.get('target') == 'swap' for c in verdict.claims):
        verdict.flags.append({'flag': 'variant_swap', 'variants': sorted({
            c['variant_id'] for c in verdict.claims if c.get('target') == 'swap'})})


def _compare_core(expectation, extraction, *, history, source_ref, brand_domain, tier,
                  brand_facts, record_variants, history_for, reference,
                  grounding=None) -> Verdict:
    source_attribution, domain_cited = classify_sources(
        extraction.get('sources_cited'), brand_domain,
    )

    def verdict(outcome, reason, matched_at=None, near_miss=False):
        return Verdict(
            outcome=outcome, reason=reason, matched_published_at=matched_at,
            source_attribution=source_attribution, domain_cited=domain_cited,
            near_miss=near_miss,
        )

    # The brand axis, for the one tier that has no number behind it.
    # Placed before the unscoreable check rather than after because the
    # classifier makes that call itself, in the same order and for the
    # same reason — our failure to read an answer is never a result about
    # the assistant.
    if bdc.is_brand_direct(tier, expectation):
        outcome, reason, code = bdc.classify_with_code(
            extraction, expectation, brand_facts=brand_facts, grounding=grounding,
        )
        result = verdict(outcome, reason)
        result.reason_code = code
        return result

    # An extraction that could not read the answer decides nothing else.
    # Checked FIRST, before any comparison: a garbled answer that happens
    # to contain no price would otherwise be recorded as `absent`, which
    # is a claim about the assistant made on the strength of our own
    # failure to read it.
    if extraction.get('extraction_confident') is False:
        return verdict(
            UNSCOREABLE,
            extraction.get('extraction_note')
            or 'extraction could not confidently read the answer',
        )

    kind = expectation.get('type')
    terms = variant_terms_from(source_ref, expectation)

    if kind in ('price', 'member_price'):
        extraction, other_brand = _drop_other_brand_claims(extraction, brand_facts)
        outcome, reason, matched_at, claims, _swapped, code = _judge_price_like(
            expectation, extraction, member=(kind == 'member_price'), terms=terms,
            history=history, history_for=history_for, source_ref=source_ref,
            record_variants=record_variants, reference=reference, brand_facts=brand_facts,
        )
        if other_brand and outcome == ABSENT and code is None:
            label = 'member price' if kind == 'member_price' else 'price'
            reason, code = (f"the answer stated no {label} for this product; "
                            f"{', '.join(repr(c) for c in other_brand)} is another brand's"), \
                REASON_OTHER_BRAND
        result = verdict(outcome, reason, matched_at)
        result.claims = claims
        result.reason_code = code
        return result

    if kind == 'pack_count':
        values = _pack_count_values(extraction, expectation, terms)
        if not values:
            return verdict(ABSENT, 'the answer stated no pack count for this product')
        if expectation['value'] in values:
            return verdict(EXACT, f"stated {expectation['value']}")
        # No history for counts: price-history carries prices, not pack
        # sizes, so a wrong count cannot be shown to have once been right.
        # Saying `wrong` is the honest limit of what we can know.
        return verdict(
            WRONG,
            f"stated {', '.join(str(v) for v in values)}; "
            f"the record says {expectation['value']}",
        )

    if kind == 'gtin':
        stated = {
            ea.normalize_gtin(entry.get('value'))
            for entry in extraction.get('gtins') or []
        } - {None}
        if not stated:
            return verdict(ABSENT, 'the answer stated no GTIN')
        if expectation['value'] in stated:
            return verdict(EXACT, f"stated {expectation['value']}")
        return verdict(WRONG, f"stated {', '.join(sorted(stated))}")

    if kind == 'code':
        code_seen, value_matched = _code_match(extraction, expectation)
        if value_matched:
            return verdict(EXACT, f"stated {ea.describe(expectation)}")
        if code_seen:
            # The right code, the wrong value. Still wrong — the shopper
            # is told they will save an amount they will not save — but a
            # different KIND of wrong from naming a code that does not
            # exist, and one worth counting on its own: it says the code
            # reached the assistant and its terms did not. Recorded as a
            # flag beside the outcome rather than as a sixth outcome, so
            # the accuracy denominator does not move.
            return verdict(
                WRONG,
                f"named {expectation['code']} but not "
                f"{ea.describe(expectation)}",
                near_miss=True,
            )
        if extraction.get('codes'):
            others = ', '.join(
                ea.normalize_code(c.get('code')) or '?'
                for c in extraction['codes']
            )
            return verdict(
                WRONG,
                f"named {others} rather than {expectation['code']}",
            )
        return verdict(ABSENT, 'the answer named no promotion code')

    if kind == 'points':
        seen, matched = _points_match(extraction, expectation)
        if matched:
            return verdict(EXACT, f"stated {ea.describe(expectation)}")
        if seen:
            return verdict(WRONG, f"stated a points rule other than {ea.describe(expectation)}")
        return verdict(ABSENT, 'the answer stated no points rule')

    if kind == 'brand_mention':
        # Presence only. Whether the brand's own domain was cited is kept
        # on the row as its own bit and is NOT part of this decision:
        # folding it in would lose the source-attribution measure the
        # report reports.
        if extraction.get('brand_mentioned'):
            return verdict(EXACT, f"named {expectation['brand']}")
        return verdict(ABSENT, f"the answer did not name {expectation['brand']}")

    logger.warning("[expectation] unknown expectation type %r", kind)
    return verdict(UNSCOREABLE, f"unknown expectation type {kind!r}")


def compare_with_secondary(expectation: dict, extraction: dict, **kwargs) -> Verdict:
    """
    The primary verdict, plus results for expectations the question did
    NOT ask about.

    Secondary results NEVER touch the primary outcome. A wrong GTIN on a
    correct price is a correct price; an absent count on a correct price
    is a correct price. That separation is the whole reason they are
    secondary.

    Every secondary outcome is recorded, `absent` included. It used to be
    dropped, on the argument that an assistant is not wrong for failing
    to recite an identifier nobody asked for and a row of absents would
    read like one — but that was an argument about how to REPORT it, and
    it was answered in the wrong place. The report now gives each
    secondary its own column with the same rate rules as everything else
    (absent outside the denominator, inside the sample count), and it
    cannot do that without a denominator. Dropping the absents left the
    reader unable to tell "volunteered and got it right nine times out of
    ten" from "volunteered nine times out of a thousand".
    """
    verdict = compare(expectation, extraction, **kwargs)

    for item in expectation.get('secondary') or []:
        result = compare(item, extraction, **kwargs)
        verdict.secondary.append({
            'type': item.get('type'),
            'outcome': result.outcome,
            'reason': result.reason,
        })

    return verdict
