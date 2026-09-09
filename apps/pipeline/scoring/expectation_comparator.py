"""
Layer 2, step 2 and 3: compare, then classify.

Given a typed expectation, a stored extraction record, and the
publication history for what the expectation was read from, decide which
of five outcomes this (question x surface x sample) is:

    exact        matches the currently published record
    stale        matches a PRIOR published value
    wrong        matches no published value, ever
    absent       the quantity was not addressed
    unscoreable  extraction could not confidently read the answer

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

logger = logging.getLogger(__name__)

EXACT = 'exact'
STALE = 'stale'
WRONG = 'wrong'
ABSENT = 'absent'
UNSCOREABLE = 'unscoreable'


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
    secondary: List[dict] = field(default_factory=list)


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

def compare(expectation: dict, extraction: dict, *, history=None,
            source_ref=None, brand_domain=None) -> Verdict:
    """
    One (question x surface x sample) -> one of five outcomes.

    `history` is [{published_at, list_price, member_price, ...}, ...] for
    the variant, oldest first, as
    GET /merchants/{slug}/price-history serves it. Absent, a mismatch is
    `wrong` rather than `stale` — the conservative direction and the
    honest one: without a record saying a value was once published we
    cannot claim it was.
    """
    source_attribution, domain_cited = classify_sources(
        extraction.get('sources_cited'), brand_domain,
    )

    def verdict(outcome, reason, matched_at=None):
        return Verdict(
            outcome=outcome, reason=reason, matched_published_at=matched_at,
            source_attribution=source_attribution, domain_cited=domain_cited,
        )

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

    if kind == 'price':
        values = _price_values(extraction, expectation, terms)
        if not values:
            return verdict(ABSENT, 'the answer stated no price for this product')
        if expectation['amount'] in values:
            return verdict(EXACT, f"stated {expectation['amount']}")
        matched_at = _prior_match(history, values)
        if matched_at:
            return verdict(
                STALE,
                f"stated {', '.join(values)}; we published that on {matched_at}",
                matched_at,
            )
        return verdict(
            WRONG,
            f"stated {', '.join(values)}; we have never published that "
            f"(current: {expectation['amount']})",
        )

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
            return verdict(
                WRONG,
                f"named {expectation['code']} but not "
                f"{ea.describe(expectation)}",
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

    if kind == 'member_price':
        right_tier, any_tier = _member_price_values(extraction, expectation, terms)
        if not any_tier:
            return verdict(ABSENT, 'the answer stated no member price for this product')
        if expectation['amount'] in right_tier:
            return verdict(EXACT, f"stated {ea.describe(expectation)}")
        matched_at = _prior_match(history, right_tier, member=True)
        if matched_at:
            return verdict(
                STALE,
                f"stated {', '.join(right_tier)} for "
                f"{expectation['tier_name']}; we published that on {matched_at}",
                matched_at,
            )
        if expectation['amount'] in any_tier:
            return verdict(
                WRONG,
                f"stated {expectation['amount']} but attributed it to another "
                f"tier, not {expectation['tier_name']}",
            )
        return verdict(
            WRONG,
            f"stated {', '.join(any_tier)}; the record says "
            f"{expectation['amount']} for {expectation['tier_name']}",
        )

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

    Secondary results never touch the outcome. They are scored only where
    the answer volunteered the quantity — an `absent` secondary is dropped
    rather than recorded, because an assistant is not wrong for failing to
    recite an identifier nobody asked it for, and a row of absents would
    read like one.
    """
    verdict = compare(expectation, extraction, **kwargs)

    for item in expectation.get('secondary') or []:
        result = compare(item, extraction, **kwargs)
        if result.outcome == ABSENT:
            continue
        verdict.secondary.append({
            'type': item.get('type'),
            'outcome': result.outcome,
            'reason': result.reason,
        })

    return verdict
