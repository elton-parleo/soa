"""
2B §2: the retailer_price reference a price claim is scored against.

Supply's contract (parleo-supply-app docs/truesync/verification-semantics.md,
"retailer_price (2A)"):

    GET /api/truesync/merchants/{slug}/retailer-prices?as_of=<ISO 8601>

returns ONE row per variant x retailer page: the newest reference run at or
before `as_of` that read the page. It returns no history — "an older run's
price is deliberately not used as a fallback". So `stale` cannot come from
the endpoint. It comes from the PREVIOUS cycle's cached rows (the payload
the previous cycle of the same study stored on soa_cycles.reference_prices
when it was scored). A claim that matches the previous cycle's verifiable
price for the same variant x retailer, and not this cycle's, is stale.
`stale_basis` on every outcome says which cycle that was, or that there was
none (then nothing can be stale, and a mismatch is wrong).

One read per cycle, cached on the cycle (soa_cycles.reference_prices,
reference_as_of). Nothing here makes a network call: the payloads are
handed in.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

from scoring import variant_rules as vr
from soa_shared import expected_answers as ea

EXACT = 'exact'
STALE = 'stale'
PARTIAL = 'partial'
WRONG = 'wrong'
ABSENT = 'absent'
UNSCOREABLE = 'unscoreable'
UNVERIFIABLE = 'unverifiable'


def gtin14(value) -> Optional[str]:
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    if not digits or len(digits) > 14:
        return None
    return digits.zfill(14)


@dataclass
class ReferenceRow:
    retailer_domain: Optional[str]
    gtin: Optional[str]
    sku: Optional[str]
    variant_ref: Optional[str]
    variant_label: Optional[str]
    url: Optional[str]
    price: Optional[str]
    member_price: Optional[str]
    list_price: Optional[str]
    verifiable: bool
    unverifiable_reason: Optional[str]
    read_status: Optional[str]
    reference_source: Optional[str]
    method: Optional[str]
    observed_at: Optional[str]

    @classmethod
    def from_payload(cls, row: dict) -> 'ReferenceRow':
        return cls(
            retailer_domain=ea.normalize_domain(row.get('retailer_domain')),
            gtin=row.get('gtin'),
            sku=row.get('sku'),
            variant_ref=row.get('variant_ref'),
            variant_label=row.get('variant_label'),
            url=row.get('url'),
            price=ea.normalize_money(row.get('price')),
            member_price=ea.normalize_money(row.get('member_price')),
            list_price=ea.normalize_money(row.get('list_price')),
            verifiable=bool(row.get('verifiable')),
            unverifiable_reason=row.get('unverifiable_reason'),
            read_status=row.get('read_status'),
            reference_source=row.get('reference_source'),
            method=row.get('method'),
            observed_at=row.get('observed_at'),
        )

    def value(self, member: bool) -> Optional[str]:
        return self.member_price if member else self.price

    def as_dict(self) -> dict:
        return {
            'retailer_domain': self.retailer_domain, 'gtin': self.gtin,
            'variant_ref': self.variant_ref, 'url': self.url,
            'price': self.price, 'member_price': self.member_price,
            'verifiable': self.verifiable, 'unverifiable_reason': self.unverifiable_reason,
            'read_status': self.read_status, 'reference_source': self.reference_source,
            'method': self.method, 'observed_at': self.observed_at,
        }


def _index(payload: Optional[dict]) -> Dict[tuple, ReferenceRow]:
    out: Dict[tuple, ReferenceRow] = {}
    for raw in (payload or {}).get('prices') or []:
        row = ReferenceRow.from_payload(raw)
        for key in _keys(row.gtin, row.sku, row.variant_ref):
            out.setdefault((row.retailer_domain, key), row)
    return out


def _keys(gtin, sku, variant_ref) -> List[str]:
    keys = []
    g = gtin14(gtin)
    if g:
        keys.append(f'gtin:{g}')
    if sku:
        keys.append(f'sku:{str(sku).strip().lower()}')
    if variant_ref:
        keys.append(f'ref:{variant_ref}')
    return keys


class ReferenceSet:
    """
    This cycle's reference rows, plus the previous cycle's for staleness.

    `prior_cycle_code` names the cycle whose cached rows `stale` is computed
    from; None means there was none and nothing can score stale.
    """

    def __init__(self, payload: Optional[dict], *, prior_payload: Optional[dict] = None,
                 prior_cycle_code: Optional[str] = None) -> None:
        self.payload = payload or {}
        self.as_of = self.payload.get('as_of')
        self.kind = self.payload.get('kind')
        self._rows = _index(payload)
        self._prior = _index(prior_payload) if prior_payload else {}
        self.prior_cycle_code = prior_cycle_code if prior_payload else None
        self.prior_as_of = (prior_payload or {}).get('as_of')

    @property
    def stale_basis(self) -> str:
        if self.prior_cycle_code:
            return (f"previous cycle {self.prior_cycle_code}'s cached retailer-prices "
                    f"(as of {self.prior_as_of}); supply serves no history")
        return "no previous cycle's cached rows; supply serves no history, so nothing is stale"

    def _find(self, index, retailer, variant_keys) -> Optional[ReferenceRow]:
        domain = ea.normalize_domain(retailer)
        for key in variant_keys:
            row = index.get((domain, key))
            if row is not None:
                return row
        return None

    def row(self, retailer, *, gtin=None, sku=None, variant_ref=None) -> Optional[ReferenceRow]:
        return self._find(self._rows, retailer, _keys(gtin, sku, variant_ref))

    def prior_row(self, retailer, *, gtin=None, sku=None, variant_ref=None) -> Optional[ReferenceRow]:
        return self._find(self._prior, retailer, _keys(gtin, sku, variant_ref))

    def summary(self) -> dict:
        return {'as_of': self.as_of, 'rows': len(self.payload.get('prices') or []),
                'stale_basis': self.stale_basis}


def judge_claim(amount, *, row: Optional[ReferenceRow], prior: Optional[ReferenceRow],
                member: bool) -> tuple:
    """
    One price claim against one page's reference. Returns (outcome, reason).

      unscoreable   the claim is not price-shaped
      unverifiable  no reference row, or the row is verifiable=false — the
                    page blocked both reference sources (or was not read).
                    A finding, never `wrong`.
      exact         matches the row's price (member_price for a member
                    expectation) within half a cent
      stale         matches the previous cycle's verifiable price for this
                    variant x page, and not this one
      partial       whole-dollar, within fifty cents (rules 1 and 4)
      wrong         none of the above
    """
    normalized = ea.normalize_money(amount)
    if normalized is None:
        return UNSCOREABLE, f"{amount!r} is not a price"
    label = 'member price' if member else 'price'
    if row is None:
        return UNVERIFIABLE, 'no reference row for this page'
    if not row.verifiable:
        return UNVERIFIABLE, row.unverifiable_reason or f"page unreadable ({row.read_status})"
    reference = row.value(member)
    if reference is None:
        return UNVERIFIABLE, f"page read, but it states no {label} for this SKU"
    if vr.same_money(normalized, reference):
        return EXACT, f"stated {normalized}; the page said {reference}"
    if prior is not None and prior.verifiable:
        earlier = prior.value(member)
        if earlier is not None and not vr.same_money(earlier, reference) \
                and vr.same_money(normalized, earlier):
            return STALE, (f"stated {normalized}; the page said {reference} now and "
                           f"{earlier} at the previous reference read")
    if vr.rounds_to(amount, reference):
        return PARTIAL, f"stated {amount}, whole-dollar within 50 cents of {reference}"
    return WRONG, f"stated {normalized}; the page said {reference}"
