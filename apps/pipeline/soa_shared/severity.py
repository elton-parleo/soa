"""
2T-4 (2): an answer's severity, by its verdict, never by its question group.

FL15's Answers read "395 shown, worst first" with well over 100 High: exact
prices ("stated 27.97, the page said 27.97 · High"), cheapest-place answers
"with no deal live for this SKU that day · High", "no reference row for this
page · High", and every where-to-buy answer naming fewer than two retailers.
The demo flags 11 of 180. Each of those was High because of a flag
(fabricated_availability, raised for a store off the question's list, 2T-4
(1)) that overrode whatever the answer's own verdict said. Severity is now one
function of the verdict, read by Answers, the Overview's flagged counts and
the narratives' flag rule, sync copies in apps/api and apps/pipeline.

  high    a wrong price (wrong, stale, a variant clash); a wrong fact (a weight
          range off the brand's chart, a size list, a count: the brand-claim
          verdict `fabricated`, and `misattributed`); a retired line called
          current (when coded) or its successor not named on the direct
          question; a club-only line sent to a store that is not a club; the
          brand left out of first place on a comparison question it is in, a
          rival first; a fabricated claim (a cited source that does not exist,
          and for a seller a store off its own list).
  medium  a live deal on the SKU not named; one of the feed's retailers named
          (or none) where two or more could be; no weight given when asked; a
          partial price (whole-dollar).
  ok      right: an exact price, a grounded brand claim (the demo's "Confirmed
          right"), the weight range matching, the successor named, the deal
          named, two or more of the brand's retailers named.
  low     not flagged, the rest: no deal live to name, an unverified claim, an
          echo, an answer that did not name the brand, a per-unit quote. A page
          we could not check ("no reference row for this page", a page
          walled) is our gap, not the answer's: it is low and listed under
          "Could not be checked" (`could_not_check`).

`classify` returns {severity, rule, could_not_check}; `rule` names the bullet,
the tests' one case per bullet. Flagged is high or medium.
"""
from collections import Counter
from typing import Iterable, Optional

HIGH, MEDIUM, LOW, OK = 'high', 'medium', 'low', 'ok'
SEVERITIES = (HIGH, MEDIUM, LOW, OK)
FLAGGED = (HIGH, MEDIUM)
#: worst first, the Answers list's order
ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2, OK: 3}

VALUE_TIERS = ('catalog_accuracy', 'value_incentives')
BRAND_TIER = 'brand_direct'
COMPARISON_TIER = 'comparison'

# rules, by the bullet they are
WRONG_PRICE = 'wrong_price'
WRONG_FACT = 'wrong_fact'
RETIRED_CURRENT = 'retired_called_current'
NO_SUCCESSOR = 'successor_not_named'
CLUB_ELSEWHERE = 'club_only_elsewhere'
BRAND_NOT_FIRST = 'brand_not_first'
FABRICATED = 'fabricated_claim'
MISSED_DEAL = 'missed_deal'
FEWER_RETAILERS = 'fewer_retailers'
NO_WEIGHT = 'no_weight'
PARTIAL_PRICE = 'partial_price'
RIGHT = 'right'
NO_DEAL_LIVE = 'no_deal_live'
UNCHECKED = 'could_not_check'
UNVERIFIED = 'unverified'
NOT_FLAGGED = 'not_flagged'

#: Warehouse clubs: a line the feed lists only there is club only.
CLUB_DOMAINS = ('costco.com', 'samsclub.com', 'bjs.com')

#: the answer flags that are a fabricated claim
FABRICATED_FLAGS = ('fabricated_citation', 'fabricated_availability')


def counted_flags(flags, merchant_kind: Optional[str] = None) -> list:
    """The answer's flags that count. 2T-4 (1): `fabricated_availability`
    counts for a seller only. A brand's retailer list is its feed's, where
    it is sold and not where it isn't, so a store off it is unverified; a
    row stored before coder 8 may still carry the flag, and it is not read."""
    out = []
    for f in flags or []:
        name = f.get('flag') if isinstance(f, dict) else f
        if name == 'fabricated_availability' and merchant_kind != 'seller':
            continue
        if name:
            out.append(f)
    return out


def _flag_names(flags) -> set:
    return {f.get('flag') if isinstance(f, dict) else f for f in flags or []}


def _out(severity, rule, could_not_check=None) -> dict:
    return {'severity': severity, 'rule': rule, 'could_not_check': could_not_check}


def classify(*, tier: Optional[str], outcome: Optional[str], reason_code: Optional[str] = None,
             flags: Iterable = (), merchant_kind: Optional[str] = None, intent: Optional[str] = None,
             intent_verdict: Optional[str] = None, listed: Optional[int] = None, club_only: bool = False,
             first_store_club: Optional[bool] = None, retired_called_current: bool = False,
             brand_in_question: bool = False, brand_first: Optional[bool] = None) -> dict:
    """
    One answer's severity. `outcome` the answer's own outcome as the console
    reads it (read_outcome: `unverified` and `per_unit` apart), `intent` and
    `intent_verdict` a catalog-built brand-direct question's own verdict
    (console_read_models.catalog_verdict), `listed` how many retailers the
    brand's feed lists for it, `club_only` the asked variant is sold only at
    warehouse clubs and `first_store_club` whether the first store the answer
    named is one, `brand_in_question` and `brand_first` for a comparison
    answer. See the module docstring.
    """
    names = _flag_names(counted_flags(flags, merchant_kind))
    if names & set(FABRICATED_FLAGS):
        return _out(HIGH, FABRICATED)
    if club_only and first_store_club is False:
        return _out(HIGH, CLUB_ELSEWHERE)

    if tier in VALUE_TIERS:
        if outcome in ('wrong', 'stale'):
            return _out(HIGH, WRONG_PRICE)
        if outcome == 'partial':
            return _out(MEDIUM, PARTIAL_PRICE)
        if outcome == 'exact':
            return _out(OK, RIGHT)
        if outcome == 'unverifiable':
            # the scorer's reason says which ("no reference row for this page", a walled page)
            return _out(LOW, UNCHECKED, 'unverifiable')
        return _out(LOW, NOT_FLAGGED)

    if tier == BRAND_TIER and intent:
        if intent == 'retired':
            if retired_called_current:
                return _out(HIGH, RETIRED_CURRENT)
            if intent_verdict == 'no_successor':
                return _out(HIGH, NO_SUCCESSOR)
            return _out(OK, RIGHT) if intent_verdict == 'grounded' else _out(LOW, NOT_FLAGGED)
        if intent == 'attribute':
            if intent_verdict == 'mismatch':
                return _out(HIGH, WRONG_FACT)
            if intent_verdict == 'absent':
                return _out(MEDIUM, NO_WEIGHT)
            return _out(OK, RIGHT) if intent_verdict == 'match' else _out(LOW, NOT_FLAGGED)
        if intent == 'cheapest_place':
            if intent_verdict == 'missed_deal':
                return _out(MEDIUM, MISSED_DEAL)
            if intent_verdict == 'named_deal':
                return _out(OK, RIGHT)
            return _out(LOW, NO_DEAL_LIVE if intent_verdict == 'no_deal_live' else NOT_FLAGGED)
        if intent == 'where_to_buy':
            if intent_verdict == 'covered':
                return _out(OK, RIGHT)
            if intent_verdict in ('partial', 'no_store') and (listed is None or listed >= 2):
                return _out(MEDIUM, FEWER_RETAILERS)
            return _out(LOW, NOT_FLAGGED)
        return _out(LOW, NOT_FLAGGED)

    if tier == BRAND_TIER:
        if outcome in ('fabricated', 'misattributed'):
            return _out(HIGH, WRONG_FACT)
        if outcome == 'grounded':
            return _out(OK, RIGHT)
        if outcome == UNVERIFIED:
            return _out(LOW, UNVERIFIED)
        return _out(LOW, NOT_FLAGGED)

    if tier == COMPARISON_TIER and brand_in_question and brand_first is False:
        return _out(HIGH, BRAND_NOT_FIRST)
    return _out(LOW, NOT_FLAGGED)


def severity(**kw) -> str:
    return classify(**kw)['severity']


def is_flagged(value: str) -> bool:
    return value in FLAGGED


def tally(answers: Iterable[dict]) -> dict:
    """{shown, high, medium, right, low, flagged, could_not_check} over answers
    carrying `severity` (and `could_not_check`), the Answers list's and the
    Overview's one count."""
    rows = list(answers or [])
    by = Counter(a.get('severity') for a in rows)
    return {'shown': len(rows), 'high': by.get(HIGH, 0), 'medium': by.get(MEDIUM, 0), 'right': by.get(OK, 0),
            'low': by.get(LOW, 0), 'flagged': by.get(HIGH, 0) + by.get(MEDIUM, 0),
            'could_not_check': sum(1 for a in rows if a.get('could_not_check'))}
