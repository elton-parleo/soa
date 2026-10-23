"""
2N-1: a per-unit price quote ("$0.33 per diaper", "$0.45 each", "$0.48/ct"),
which is not the pack's price and cannot be compared with it. Sync copies
in apps/api/soa_shared/ and apps/pipeline/soa_shared/.

Read by the scorer (scoring/expectation_comparator.py): a per-unit quote is
its own claim outcome, `per_unit`, outside scored and outside wrong; a run
whose only claims are per-unit is stored `unscoreable` with reason code
`per_unit` (the outcome column's check constraint holds no `per_unit`, and
this needs no migration). The narratives read the same rule (2L-3a's words,
moved here). Deterministic, no model.

A quote is per-unit when
  * the product it was attached to is a per-unit phrase ("per diaper",
    "each", "/ct"), or
  * the answer's words right after the amount say so, or
  * it is over nothing and under UNIT_CEILING against a pack price over PACK_FLOOR.
"""
import re
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

PER_UNIT = 'per_unit'
NOTE = 'per-diaper price, not comparable'
#: Under this, against a pack price over PACK_FLOOR, a quote is for one unit.
UNIT_CEILING = Decimal('2')
PACK_FLOOR = Decimal('10')

_UNITS = r"(?:diaper|wipe|count|ct|unit|piece|pull-?up|pant|pad|nappy|nappie)s?"
#: The words after a per-unit amount: "per diaper", "/ct", "a diaper", "each".
AFTER = re.compile(rf"^\s*(?:(?:/|per\b|a\b|an\b)\s*{_UNITS}\b|each\b)", re.I)
#: A product phrase that is a unit, not a product: "per diaper", "each", "/ct", "a wipe".
PHRASE = re.compile(rf"^\s*(?:for\s+)?(?:(?:/|per\b|a\b|an\b|one\b)\s*{_UNITS}|each|{_UNITS})\s*$", re.I)
_AMOUNT = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?")


def _money(value) -> Optional[Decimal]:
    try:
        return Decimal(str(value).replace('$', '').replace(',', '').strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _same(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) < Decimal('0.005')


def said_after(amount, texts: Iterable[str]) -> bool:
    """The answer's words right after `amount` say it is per unit."""
    want = _money(amount)
    if want is None:
        return False
    for text in texts or []:
        for m in _AMOUNT.finditer(str(text or '')):
            got = _money(m.group(1) + ('.' + m.group(2) if m.group(2) else ''))
            if got is not None and _same(got, want) and AFTER.match(text[m.end():m.end() + 30]):
                return True
    return False


def below_pack(amount, against) -> bool:
    """Over nothing and under UNIT_CEILING, against a pack price over PACK_FLOOR ($0.00 is no unit price)."""
    a, b = _money(amount), _money(against)
    return a is not None and b is not None and 0 < a < UNIT_CEILING and b > PACK_FLOOR


def is_per_unit(amount, product: Optional[str] = None, texts: Iterable[str] = (), against=None) -> bool:
    if _money(amount) is None:
        return False
    if product and PHRASE.match(product):
        return True
    return said_after(amount, texts) or below_pack(amount, against)
