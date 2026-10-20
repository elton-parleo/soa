"""
2I-9: the revenue model's public inputs and their sources, in one place.

The console's Impact screen models what wrong and missing answers cost a
merchant a year, as the console demo does (parleohq/truesync apps/console/
src/data/v2common.ts, computeRevenue):

    aiTouched = sales in scope x share of shopping through an AI answer
    driver    = aiTouched x measured share x conversion effect
    at stake  = the drivers summed; gainable = each driver x its gainable share

Sales in scope is the merchant's own figure and has no default: until it is
entered the model shows the measured shares and no dollars. The three public
parameters default to the demo's figures with the demo's source sentences,
copied verbatim from v2common.ts INFLUENCE / HORIZON / PENALTY, so the two
apps cite the same text. The win-back share of Lost defaults to 25%, the
figure the demo uses for Pampers (Elton, Oct 20); the merchant changes it on
Impact.

Sync copies to apps/api/soa_shared/, apps/pipeline/soa_shared/ and
packages/shared/soa_shared/ (the identical-copies test).
"""
from typing import Dict, Optional

#: v2common.ts INFLUENCE, verbatim
INFLUENCE = {
    'label': 'Share of shopping that runs through an AI answer',
    'value': 0.114,
    'display': '11.4%',
    'source': ('Similarweb, Sep 10 2026: an AI tool was part of 11.4% of US desktop shopping sessions, Jul to Dec 2025. '
               'Applied to all channels, since a shopper who asks an agent and then buys in store counts too.'),
}
#: v2common.ts HORIZON, verbatim
HORIZON = {
    'label': 'Same share by 2030',
    'value': 0.2,
    'display': '20%',
    'source': ('Morgan Stanley: agentic shoppers could reach $385B, about 20% of US online retail, by 2030 (bull case). '
               'Base case $190B, about 10%.'),
}
#: v2common.ts PENALTY, verbatim
PENALTY = {
    'label': 'Conversion lost when an answer is wrong or sends the shopper elsewhere',
    'value': 0.14,
    'display': '14%',
    'source': ('McKinsey research across 3,000+ e-commerce companies, via Shopify Enterprise: product-data errors cost up '
               'to 14% of conversions. In line with Similarweb (Sep 2026): shoppers visit the brand an AI names 14.2% of '
               'the time and an alternative 3.8%, about a 10 point gap.'),
}
#: The share of Lost the record can win back. The demo chooses it per tenant
#: (Pampers 25%, Petco 24%) from the questions its record answers. Here it
#: defaults to the demo's Pampers figure (Elton, Oct 20) and the merchant
#: changes it on Impact.
LOST_GAINABLE = {
    'label': 'Share of lost first picks the record can win back',
    'value': 0.25,
    'display': '25%',
    'source': ('Gainable counts all of Missed, since you own the record, plus the first picks lost on questions your '
               'record answers. 25% by default, the share the demo uses for Pampers. Change it to your own.'),
}
#: Sales in scope: the merchant's own figure, never defaulted
SCOPE = {
    'label': 'Sales in scope, all channels',
    'source': 'Enter your own annual sales for the products in scope, stores and online together.',
}

CURRENCIES = ('$', '€', 'SEK ')
DEFAULT_CURRENCY = '$'

#: field -> (low, high) on write; None is no upper bound
RANGES: Dict[str, tuple] = {
    'scope_value': (0.0, None),
    'influence': (0.0, 1.0),
    'horizon': (0.0, 1.0),
    'penalty': (0.0, 1.0),
    'lost_gainable': (0.0, 1.0),
}
SHARE_DEFAULTS = {'influence': INFLUENCE, 'horizon': HORIZON, 'penalty': PENALTY, 'lost_gainable': LOST_GAINABLE}


def out_of_range(field: str, value) -> Optional[str]:
    """Why a written value is refused, or None. A null value resets the field."""
    if value is None:
        return None
    low, high = RANGES[field]
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f'{field} must be a number'
    if v != v or v < low or (high is not None and v > high):
        return f'{field} must be between {low:g} and {high:g}' if high is not None else f'{field} must be {low:g} or more'
    return None


def display_share(value: float) -> str:
    """0.114 -> '11.4%', 0.2 -> '20%'."""
    pct = round(float(value) * 100, 1)
    return f"{pct:g}%"
