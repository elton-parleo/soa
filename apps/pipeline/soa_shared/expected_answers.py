"""
The typed expected-answer vocabulary — the executable form of
docs/expected-answer-vocabulary.md.

`soa_queries.expected_answer` holds what a correct answer must contain.
It is JSON, and JSON holds anything, so this module is the thing that
says what it may hold: seven types, each naming exactly which fields
carry meaning, each with a deterministic comparison rule (the comparison
itself lives in the pipeline's scoring layer — see
scoring/expectation_comparator.py).

Never free text. A free-text expectation can only be scored by asking a
model whether an answer matches it, which makes the scorer a second
opinion rather than a comparison, and it fails in the flattering
direction: a generous judge scores a wrong answer as right.

Money is a decimal STRING, never a float. Canonical records serialise
Decimal to a string, the comparison is string-exact after normalising to
two places, and a round trip through binary floating point is a silent
way to make two identical published prices differ.

Lives in soa_shared rather than in the pipeline because three callers
need it and none of them is upstream of the others: the generator writes
expectations, the API validates and renders them, and the scorer compares
them.

Sync copies to apps/api/soa_shared/ and apps/pipeline/soa_shared/.
"""
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

# ─── The vocabulary ────────────────────────────────────────────────────────

EXPECTED_ANSWER_TYPES = [
    'price',
    'gtin',
    'pack_count',
    'code',
    'member_price',
    'points',
    'brand_mention',
]

# What a `code` expectation's value means. Dollars for amount_off and
# member_price; percent for percent_off ('10.0', never '0.10').
CODE_VALUE_KINDS = ['amount_off', 'percent_off', 'member_price']

# A points rule either carries a rate the record stated (per_dollar) or a
# total the engine computed for this variant at its published price
# (fixed). They are different claims and are compared differently.
POINTS_RULE_KINDS = ['per_dollar', 'fixed']

# The five outcomes a scored (question x surface x sample) lands in when
# the expectation names a published VALUE — a price, a code, a count.
# `unscoreable` is its own bucket and is never folded into `wrong`: they
# are different facts, and merging them inflates the error rate with our
# own extraction failures.
VALUE_OUTCOMES = ['exact', 'stale', 'wrong', 'absent', 'unscoreable']

# Brand-direct answers are classified on a different axis, because there
# is no published number for them to match. The old arrangement scored
# them on presence alone — `exact` if the brand was named, `absent` if
# not — and that turned out to score the worst answer in the study as a
# success: Gemini replying that Wiggle & Snug "is not a real or widely
# recognized brand" names the brand, so it counted as exact.
#
# Presence was never the measurement. What a brand-direct question asks
# is whether an assistant knows this brand, and there are at least four
# distinguishable ways for the answer to be about it:
#
#   grounded             it cited the brand's own domain. The strongest
#                        result the tier can produce, and the only one
#                        where the answer shows where it got what it
#                        said.
#   echoed               it named the brand and said nothing checkable.
#                        Not a failure, not a success — this is what
#                        "visibility" was actually measuring all along,
#                        which is why the report now calls it that
#                        instead of visibility.
#   misattributed        it named the brand and then described a
#                        different one: Huggies Snug & Dry, Bc Babycare,
#                        Beezpro, offered as "the closest match". The
#                        brand appears and everything specific about it
#                        belongs to somebody else.
#   fabricated           it stated brand-specific facts that are not in
#                        the record and cited nothing — a private label
#                        at Aldi, an exclusive at Kohl's, loyalty tiers
#                        called Snuggle Friend, Pal and Bestie.
#   acknowledged_unknown it said it could not find, verify or recognise
#                        the brand or the product. The honest answer, and
#                        the one most worth telling apart from the rest:
#                        an assistant that says it does not know is a
#                        very different result from one that invents.
#
# `absent` (the brand never came up at all) and `unscoreable` (we could
# not read the answer) mean here what they mean everywhere else.
BRAND_ASSESSMENTS = [
    'grounded', 'echoed', 'misattributed', 'fabricated', 'acknowledged_unknown',
]

BRAND_OUTCOMES = BRAND_ASSESSMENTS + ['absent', 'unscoreable']

# Every value the outcome column may hold, across both vocabularies. A
# row's tier says which of the two applies; nothing reads this union
# except the schema constraint and the tests that keep it honest.
EXPECTATION_OUTCOMES = VALUE_OUTCOMES + BRAND_ASSESSMENTS


def outcomes_for_tier(tier):
    """Which vocabulary a tier's rows are classified in.

    brand_direct and nothing else: catalog accuracy and value both
    compare against a published number, and a question with no number
    behind it is the only thing the brand axis can describe.
    """
    return BRAND_OUTCOMES if tier == 'brand_direct' else VALUE_OUTCOMES

# The four question tiers. `null` on a query means it was generated
# without a syndicated brand — which is every query that existed before
# this vocabulary did.
QUERY_TIERS = [
    'brand_direct',
    'catalog_accuracy',
    'value_incentives',
    'category_control',
]

# How a question came to exist. `catalog` and `ai_from_catalog` both
# imply a source_ref; `ai` does not.
QUERY_PROVENANCES = [
    'catalog',           # template-built from the published record, no AI
    'ai_from_catalog',   # written by AI, grounded in the published record
    'ai',                # written by AI with no catalog grounding
]


class ExpectedAnswerError(ValueError):
    """An expectation that nothing could score. Raised at write time
    rather than tolerated, because a question carrying an unscoreable
    expectation is worse than one carrying none: it is counted in an
    accuracy denominator it can never contribute to."""


# ─── Normalisation ─────────────────────────────────────────────────────────

def normalize_money(value: Any) -> Optional[str]:
    """
    A money value as a two-decimal string, or None when it will not parse.

    Accepts what the published records and the extractor actually emit:
    '22.99', '$22.99', '22.99 USD', Decimal('22.99'), 22.99. Returns None
    rather than raising — an unparseable amount from a model is an
    `unscoreable` outcome, not a crash, and an unparseable amount from a
    record is a finding the endpoint reports verbatim.

    Two decimal places always, so '18.9' and '18.90' are the same price
    and '18.995' is not silently truncated into agreement with either
    (it rounds half-up, which is what a price is written with).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None

    text = str(value).strip()
    if not text:
        return None

    # Strip currency ornament, thousands separators and a trailing code.
    for token in ('$', '£', '€', 'USD', 'usd', 'CAD', 'GBP', 'EUR'):
        text = text.replace(token, '')
    text = text.replace(',', '').strip()
    if not text:
        return None

    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return f"{amount.quantize(Decimal('0.01'))}"


# What a shopping answer writes a currency as, and the ISO-4217 code it
# means. A table rather than a guess: an extractor asked to "use the code"
# returned "Rs." on one run and "INR" on another for the same answer, and
# a scorer comparing "Rs." against "INR" finds a mismatch that is not one.
#
# Deliberately short. Every entry here is a symbol seen in a real answer;
# a symbol nobody has seen is better refused than guessed at, because a
# wrong guess is a price comparison that silently means nothing.
CURRENCY_SYMBOLS = {
    '$': 'USD', 'US$': 'USD', 'USD': 'USD', 'DOLLARS': 'USD',
    '£': 'GBP', 'GBP': 'GBP', 'POUNDS': 'GBP',
    '€': 'EUR', 'EUR': 'EUR', 'EUROS': 'EUR',
    '₹': 'INR', 'RS': 'INR', 'INR': 'INR', 'RUPEES': 'INR',
}


def normalize_currency(value: Any) -> Optional[str]:
    """
    ISO-4217, uppercase, via the symbol table.

    '$22.99' and 'CA$22.99' are still not the same answer — 'CA$' is not
    in the table and comes back as itself, which is_currency_code then
    refuses. Currency is compared, never assumed.
    """
    if not value:
        return None
    raw = str(value).strip()
    mapped = (
        CURRENCY_SYMBOLS.get(raw)
        or CURRENCY_SYMBOLS.get(raw.upper().rstrip('.'))
    )
    if mapped:
        return mapped
    return raw.upper() or None


def is_currency_code(value: Any) -> bool:
    """
    Whether a normalized currency is something a comparison can use.

    Three letters, because that is what ISO-4217 is — so 'CAD' and 'AUD'
    pass without being in the table above, and 'RS.' and 'CA$' do not.
    The caller decides what to do about a false; the scorer records the
    run as unscoreable rather than comparing a price whose currency it
    cannot read, which is the only honest option: treating it as a match
    and treating it as a mismatch are both claims about the assistant
    made on the strength of our own confusion.
    """
    text = str(value or '').strip()
    return len(text) == 3 and text.isalpha()


def normalize_gtin(value: Any) -> Optional[str]:
    """A GTIN with its human-readable separators removed. An identifier's
    near-miss is a different product, so nothing else is normalised —
    leading zeros are significant and are kept."""
    if value is None:
        return None
    text = ''.join(ch for ch in str(value) if ch.isdigit())
    return text or None


def normalize_code(value: Any) -> Optional[str]:
    """A promo code, upper-cased and stripped. Codes are typed by humans
    and every checkout upper-cases them, so comparing case would measure
    an assistant's shift key."""
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def normalize_tier_name(value: Any) -> Optional[str]:
    """A loyalty tier name, folded for comparison. Compared (unlike
    program_name) because a shopper told the entry tier gets the top
    tier's price has been misinformed about the thing the tier signals."""
    if value is None:
        return None
    text = ' '.join(str(value).split()).strip().lower()
    return text or None


def normalize_count(value: Any) -> Optional[int]:
    """An integer unit count, or None. '84 ct' and '84' are the same
    count; '84.5' is not a count at all."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    digits = ''.join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


# ─── Constructors ──────────────────────────────────────────────────────────
#
# Every expectation written into soa_queries goes through one of these,
# so a malformed one cannot reach the column. They normalise on the way
# in: an expectation stored un-normalised would have to be normalised on
# every comparison instead, and the day one comparison forgets is the day
# a correct answer scores wrong.

def price(amount: Any, currency: Any = 'USD') -> dict:
    normalized = normalize_money(amount)
    if normalized is None:
        raise ExpectedAnswerError(f"price amount {amount!r} is not a money value")
    code = normalize_currency(currency)
    if not code:
        raise ExpectedAnswerError("price expectation needs a currency")
    return {'type': 'price', 'amount': normalized, 'currency': code}


def gtin(value: Any) -> dict:
    normalized = normalize_gtin(value)
    if not normalized:
        raise ExpectedAnswerError(f"gtin {value!r} has no digits in it")
    return {'type': 'gtin', 'value': normalized}


def pack_count(value: Any) -> dict:
    normalized = normalize_count(value)
    if normalized is None:
        raise ExpectedAnswerError(f"pack_count {value!r} is not a count")
    return {'type': 'pack_count', 'value': normalized}


def code(value: Any, value_kind: str, amount: Any) -> dict:
    normalized_code = normalize_code(value)
    if not normalized_code:
        raise ExpectedAnswerError("code expectation needs a code")
    if value_kind not in CODE_VALUE_KINDS:
        raise ExpectedAnswerError(
            f"value_kind must be one of {', '.join(CODE_VALUE_KINDS)}, got {value_kind!r}"
        )
    normalized_value = normalize_money(amount)
    if normalized_value is None:
        raise ExpectedAnswerError(
            f"code value {amount!r} is not a number — a right code with an "
            f"unknown discount cannot be scored"
        )
    return {
        'type': 'code',
        'code': normalized_code,
        'value_kind': value_kind,
        'value': normalized_value,
    }


def member_price(amount: Any, tier_name: Any, currency: Any = 'USD') -> dict:
    normalized = normalize_money(amount)
    if normalized is None:
        raise ExpectedAnswerError(f"member_price amount {amount!r} is not a money value")
    if not tier_name or not str(tier_name).strip():
        raise ExpectedAnswerError(
            "member_price expectation needs a tier_name — a member price with "
            "no tier names no entitlement, and is not a claim about anything"
        )
    currency_code = normalize_currency(currency)
    if not currency_code:
        raise ExpectedAnswerError("member_price expectation needs a currency")
    return {
        'type': 'member_price',
        'amount': normalized,
        'currency': currency_code,
        'tier_name': str(tier_name).strip(),
    }


def points(kind: str, *, rate: Any = None, total: Any = None,
           program_name: Any = None) -> dict:
    if kind not in POINTS_RULE_KINDS:
        raise ExpectedAnswerError(
            f"points kind must be one of {', '.join(POINTS_RULE_KINDS)}, got {kind!r}"
        )
    rule: dict = {'kind': kind}
    if kind == 'per_dollar':
        normalized = normalize_money(rate)
        if normalized is None:
            raise ExpectedAnswerError(f"per_dollar points rate {rate!r} is not a number")
        rule['rate'] = normalized
    else:
        normalized_total = normalize_count(total)
        if normalized_total is None:
            raise ExpectedAnswerError(f"fixed points total {total!r} is not a count")
        rule['points'] = normalized_total
    if program_name:
        # Carried for display, never compared — see the vocabulary doc.
        rule['program_name'] = str(program_name).strip()
    return {'type': 'points', 'rule': rule}


def brand_mention(brand: Any, domain: Any = None) -> dict:
    if not brand or not str(brand).strip():
        raise ExpectedAnswerError("brand_mention expectation needs a brand")
    out = {'type': 'brand_mention', 'brand': str(brand).strip()}
    if domain:
        out['domain'] = str(domain).strip().lower()
    return out


def with_secondary(primary: dict, secondary: list) -> dict:
    """
    Attaches expectations the question does NOT ask about.

    They are scored only where the answer volunteered the quantity and
    are reported as a bonus signal — never in the accuracy denominator.
    An assistant is not wrong for failing to recite an identifier nobody
    asked for; it is demonstrating catalog-level grounding when it does.
    """
    validated = [validate(item) for item in secondary]
    if not validated:
        return dict(primary)
    return {**primary, 'secondary': validated}


# ─── Naming a brand ────────────────────────────────────────────────────────

_BRAND_NOISE = re.compile(r'[^a-z0-9]+')
_AMPERSAND = re.compile(r'\s*&\s*')


def normalize_brand_text(text) -> str:
    """Lowercased, &-expanded, punctuation-flattened, single-spaced.

    Applied to BOTH sides of every comparison, so the tolerance it grants
    is symmetric — never a rule that reads one way for the brand and
    another for the text being checked.
    """
    lowered = _AMPERSAND.sub(' and ', str(text or '').lower())
    return _BRAND_NOISE.sub(' ', lowered).strip()


def names_brand(text, brand) -> bool:
    """
    Whether a piece of text names this brand.

    ONE definition, used in two places that must not disagree: the
    generator's guard, which rejects a brand-direct question that does
    not name the brand, and the extraction, which records whether the
    ANSWER did. If those two drifted apart, a question could pass the
    guard and then be scored against a different idea of what naming is.

    Substring on the normalized forms, so 'Wiggle & Snug', 'wiggle and
    snug' and 'Wiggle  &  Snug' all pass and 'Wiggle' does not — the
    tolerance is for typography, never for identity. Word boundaries come
    from padding both sides with spaces: without that, a brand called
    'Bum' would count itself named by the word 'album'.

    Deterministic on purpose. This used to be a field the extraction
    model filled in, and on one cycle it got it wrong in both directions:
    false on an answer reading "on eligible Wiggle & Snug products", true
    on one that only ever said "Wonder" and "The Wiggles". A string is in
    a string or it is not, and that is not a judgement anyone needs a
    model for.
    """
    brand_text = normalize_brand_text(brand)
    if not brand_text:
        # No brand to look for. Callers that require one refuse to run
        # without it; reaching here means a caller asked a question this
        # function cannot answer, and answering 'no' would mark every
        # answer as not naming a brand nobody named.
        return True
    return f' {brand_text} ' in f' {normalize_brand_text(text)} '


# ─── Validation ────────────────────────────────────────────────────────────

_REQUIRED_FIELDS = {
    'price':         ('amount', 'currency'),
    'gtin':          ('value',),
    'pack_count':    ('value',),
    'code':          ('code', 'value_kind', 'value'),
    'member_price':  ('amount', 'currency', 'tier_name'),
    'points':        ('rule',),
    'brand_mention': ('brand',),
}


def validate(expectation: Any) -> dict:
    """
    Returns the expectation unchanged if it is one this system can score;
    raises ExpectedAnswerError otherwise.

    Used on every write path — the generator, the API's manual question
    editor, and the CSV import — because the one thing that must not
    happen is an unscoreable expectation reaching the column and then a
    denominator.
    """
    if not isinstance(expectation, dict):
        raise ExpectedAnswerError(
            f"expected_answer must be an object, got {type(expectation).__name__}"
        )

    kind = expectation.get('type')
    if kind not in EXPECTED_ANSWER_TYPES:
        raise ExpectedAnswerError(
            f"unknown expected_answer type {kind!r}; must be one of "
            f"{', '.join(EXPECTED_ANSWER_TYPES)}"
        )

    missing = [f for f in _REQUIRED_FIELDS[kind] if expectation.get(f) in (None, '')]
    if missing:
        raise ExpectedAnswerError(
            f"{kind} expectation is missing {', '.join(missing)}"
        )

    if kind == 'code' and expectation['value_kind'] not in CODE_VALUE_KINDS:
        raise ExpectedAnswerError(
            f"code value_kind must be one of {', '.join(CODE_VALUE_KINDS)}"
        )

    if kind == 'points':
        rule = expectation['rule']
        if not isinstance(rule, dict) or rule.get('kind') not in POINTS_RULE_KINDS:
            raise ExpectedAnswerError(
                f"points rule kind must be one of {', '.join(POINTS_RULE_KINDS)}"
            )
        if rule['kind'] == 'per_dollar' and rule.get('rate') in (None, ''):
            raise ExpectedAnswerError("per_dollar points rule needs a rate")
        if rule['kind'] == 'fixed' and rule.get('points') is None:
            raise ExpectedAnswerError("fixed points rule needs a points total")

    for item in expectation.get('secondary') or []:
        validate(item)

    return expectation


def is_scoreable(expectation: Any) -> bool:
    """Whether Layer 2 runs for a question at all. Layer 1 (mention
    coding) runs on every question regardless — the tier tag is what
    segments it."""
    try:
        validate(expectation)
    except ExpectedAnswerError:
        return False
    return True


# Values an assistant can land on without knowing anything about this
# brand, because they are the category default. One point per dollar is
# what almost every loyalty programme in the world does; an answer that
# says so has not demonstrated that it read our record, and counting it
# as a success inflates the one rate the tier exists to produce.
#
# Judged on the RULE, never on the answer: this is a property of what we
# published, decided before anything is scored, so it cannot be applied
# selectively to results somebody dislikes.
# Normalised, so '1', '1.0' and '1.00' are one value rather than three
# spellings the check has to remember.
GUESSABLE_POINTS_RATES = {'1.00'}


def is_low_information(expectation: Any) -> bool:
    """
    Whether a correct answer to this expectation proves nothing.

    Such an expectation is still asked, still scored, and still reported
    — with its own sample count, in its own column. What it does not do
    is enter the value-survival headline, because a headline that moves
    when an assistant guesses the industry default is measuring the
    industry rather than the assistant.
    """
    if not isinstance(expectation, dict):
        return False
    if expectation.get('type') != 'points':
        return False
    rule = expectation.get('rule')
    if not isinstance(rule, dict) or rule.get('kind') != 'per_dollar':
        return False
    return normalize_money(rule.get('rate')) in GUESSABLE_POINTS_RATES


def describe(expectation: dict) -> str:
    """
    A one-line human rendering, for the modal's examples and the report's
    drill-down. Display only — nothing branches on this string.
    """
    kind = expectation.get('type')
    if kind == 'price':
        return f"{expectation['amount']} {expectation['currency']}"
    if kind == 'gtin':
        return f"GTIN {expectation['value']}"
    if kind == 'pack_count':
        return f"{expectation['value']} count"
    if kind == 'code':
        value = expectation['value']
        if expectation['value_kind'] == 'percent_off':
            return f"{expectation['code']}, {value}% off"
        if expectation['value_kind'] == 'member_price':
            return f"{expectation['code']}, member price {value}"
        return f"{expectation['code']}, {value} off"
    if kind == 'member_price':
        return f"{expectation['amount']} {expectation['currency']} ({expectation['tier_name']})"
    if kind == 'points':
        rule = expectation['rule']
        if rule['kind'] == 'per_dollar':
            return f"{rule['rate']} points per dollar"
        return f"{rule['points']} points"
    if kind == 'brand_mention':
        domain = expectation.get('domain')
        return (
            f"brand named, {domain} cited" if domain else "brand named"
        )
    return str(expectation)
