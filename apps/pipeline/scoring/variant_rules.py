"""
2B §3: the clash and rounding rules, ported from the console-demo engine.

Source: parleohq/truesync, branch console-demo, services/engine/src/checks.ts
(`packNumbers`, `modelNumberClash`, `VARIANT_MARKERS`, `compareQuote`,
`canBeWrong`). The RULES are ported; the code is not. The engine compares a
quoted price against shelf reads; here a claim is compared against the
variant a question asked about and its siblings in the record, so the
callers differ even where a function body is a line-for-line port.

Deterministic, no network, no model. Nothing here reads Layer 2 or changes
it: it reads the `attributed_product` string Layer 2 already stored.

The four rules (docs/console-read-models.md and the 2B report list them
with the verdicts they moved):

  1. partial   a whole-dollar claim within 50 cents of the reference ("about
               $18" for 17.99), or the right price for an adjacent variant
               of the same item group. Never folded into exact.
  2. clash     a claim whose pack number, model/size token or variant marker
               conflicts with the asked variant is scored against the variant
               it names when that variant is in the record (flag
               variant_swap), else it is wrong with reason variant_clash.
  3. inferred  a claim attached to no product can never be wrong: a mismatch
               is unscoreable, reason product_inferred.
  4. member    the whole-dollar rounding in rule 1 applies to member prices.
"""
import re
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional, Set

#: Engine: PRICE_TOLERANCE. Two money values within half a cent are equal.
PRICE_TOLERANCE = Decimal('0.005')

#: Engine: compareQuote's `rounded`. A whole-dollar claim within fifty cents
#: of the reference is a rounding, not a miss ("$241" for 240.99).
WHOLE_DOLLAR_WINDOW = Decimal('0.50')


def _decimal(value) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace('$', '').replace(',', '').strip())
    except (InvalidOperation, ValueError):
        return None


def same_money(a, b) -> bool:
    """Engine `near`: equal within PRICE_TOLERANCE."""
    left, right = _decimal(a), _decimal(b)
    if left is None or right is None:
        return False
    return abs(left - right) < PRICE_TOLERANCE


def is_whole_dollar(value) -> bool:
    """Engine: Number.isInteger(quoted). '18', '18.00' and 18 are whole."""
    amount = _decimal(value)
    return amount is not None and amount == amount.to_integral_value()


def rounds_to(claim, reference) -> bool:
    """
    Rule 1 / rule 4: a whole-dollar claim strictly within fifty cents of the
    reference. Strict, as the engine's `< 0.5` is, so "$18" is partial
    against 17.51 and not against 17.50.
    """
    if not is_whole_dollar(claim):
        return False
    left, right = _decimal(claim), _decimal(reference)
    if left is None or right is None:
        return False
    return abs(left - right) < WHOLE_DOLLAR_WINDOW


# ─── Pack numbers ──────────────────────────────────────────────────────────

# Engine: packNumbers. Weight bands ("33.1-66 lbs") are left out on purpose:
# they describe the dog, not the pack.
_PACK_RE = re.compile(
    r'(\d{1,4})\s*(?:-?\s*)?(?:count|ct\b|counts|pack\b|pk\b|rolls?\b|mega rolls?|'
    r'boxes\b|box\b|tissues\b|oz\b|fl\.? oz|sheets\b|wipes\b|diapers\b|ea\b|'
    r'months?\b|mos?\b|tablets\b|chews?\b|doses\b|pods\b|pacs\b|loads\b)',
    re.IGNORECASE,
)


def pack_numbers(text: Optional[str]) -> Set[int]:
    """Pack sizes in a product string: '84 ct', '3-Pack', '24 Mega Rolls'."""
    out: Set[int] = set()
    if not text:
        return out
    for match in _PACK_RE.finditer(str(text)):
        try:
            out.add(int(match.group(1)))
        except ValueError:
            continue
    return out


# ─── Model numbers ─────────────────────────────────────────────────────────

_MODEL_CONNECTORS = {'series', 'model', 'gen', 'generation', 'version', 'no', 'number', 'style'}


def _model_numbers(text: Optional[str]) -> dict:
    """Engine: modelNumbers. 'iO9' reads as 'io 9'; 'iO Series 7' pairs io
    with 7 as well as series with 7."""
    out: dict = {}
    if not text:
        return out
    lowered = re.sub(r'([a-z])(\d)', r'\1 \2', str(text).lower())
    words = [w for w in re.split(r'[^a-z0-9.]+', lowered) if w]
    words = [w.strip('.') for w in words if w.strip('.')]

    def is_number(token: str) -> bool:
        return re.fullmatch(r'\d+(?:\.\d+)?', token) is not None

    for i in range(len(words) - 1):
        word = words[i]
        if not re.fullmatch(r'[a-z]{2,}', word):
            continue
        j = i + 1
        while j < len(words) and words[j] in _MODEL_CONNECTORS and word not in _MODEL_CONNECTORS:
            j += 1
        nxt = words[j] if j < len(words) else ''
        if not is_number(nxt):
            continue
        out.setdefault(word, set()).add(nxt)
    return out


def strip_pack_phrases(text: Optional[str]) -> str:
    """The text with every pack-count phrase ('(84 ct)', '3-Pack') removed."""
    return _PACK_RE.sub(' ', str(text or ''))


def model_number_clash(a: Optional[str], b: Optional[str]) -> bool:
    """Engine: modelNumberClash. A word followed by a number on both sides
    with different numbers ('Size 1' against 'Size 3', 'Speedgoat 6' against
    'Speedgoat 7') means a different item.

    One deviation from the engine: pack-count phrases are removed first.
    In 'Small Pack (84 ct)' the engine's reading pairs 'pack' with 84 and
    turns a count into a model number; counts are pack_numbers' job, and
    here a wrong count on a correctly named variant is a secondary claim
    (generation/catalog_tiers.py, _discriminators), not a different item."""
    left, right = _model_numbers(strip_pack_phrases(a)), _model_numbers(strip_pack_phrases(b))
    for word, numbers in left.items():
        other = right.get(word)
        if other and not (numbers & other):
            return True
    return False


def model_number_match(a: Optional[str], b: Optional[str]) -> bool:
    """Positive evidence: a word followed by the SAME number on both sides
    ('iO9' and 'iO Series 9'). The counterpart of model_number_clash, used
    to say which variant a claim names."""
    left, right = _model_numbers(strip_pack_phrases(a)), _model_numbers(strip_pack_phrases(b))
    return any(numbers & right.get(word, set()) for word, numbers in left.items())


# ─── Variant markers ───────────────────────────────────────────────────────
#
# VENDORED. The first block is the engine's VARIANT_MARKERS verbatim (with
# its normalisation of 'womens'/'woman' to 'women' and 'Worn Wear' to
# 'used'). The second block is 2B's addition for the categories soa studies
# today, named in the brief: words that turn a diaper, a wipe or a balm into
# a different offer.
#
# Every entry is a word that, present in a claim and absent from the asked
# variant's record text, means the claim is about another item. Adding a
# word here can move verdicts, so it is a deliberate act with a golden row.

ENGINE_VARIANT_MARKERS = frozenset({
    'gtx', 'goretex', 'lt', 'women', 'womens', 'woman', 'kids', 'kid', 'youth',
    'junior', 'girls', 'boys', 'used', 'preowned', 'refurbished', 'renewed',
    'secondhand', 'resale',
})

SOA_VARIANT_MARKERS = frozenset({
    'overnight', 'nighttime', 'sensitive', 'unscented', 'scented', 'fragrancefree',
    'preemie', 'refill', 'travel', 'trial',
})

VARIANT_MARKERS = ENGINE_VARIANT_MARKERS | SOA_VARIANT_MARKERS


def variant_markers(text: Optional[str]) -> Set[str]:
    out: Set[str] = set()
    if not text:
        return out
    flattened = str(text).lower().replace('’', '').replace("'", '').replace('-', '')
    for word in re.split(r'[^a-z0-9]+', flattened):
        if word in VARIANT_MARKERS:
            out.add('women' if word in ('womens', 'woman') else word)
    if re.search(r'worn\s*wear', str(text), re.IGNORECASE):
        out.add('used')
    return out


def marker_clash(claim: Optional[str], record_text: Optional[str]) -> Set[str]:
    """
    The markers the CLAIM carries that the record's variant does not.

    One-sided, unlike the engine's variantClash, which compares two shelf
    strings symmetrically. Here one side is our record and the other an
    answer, and an answer that omits "overnight" while naming the overnight
    Size 3 has omitted a word, not named a different product.
    """
    return variant_markers(claim) - variant_markers(record_text)


def any_overlap(left: Iterable, right: Iterable) -> bool:
    return bool(set(left) & set(right))
