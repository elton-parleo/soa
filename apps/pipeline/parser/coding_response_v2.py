"""
Pass-2 coding response types — deliberately separate from
parser/coding_response.py (pass 1). Pass 2 extracts ONLY per-observation
merchant attribution and citations; it never re-derives mentioned/
position/strength/deal_cited/etc, so those fields have nothing to drift
from pass 1's values, by construction. See parser/prompts_v2.py and
parser/response_coder_v2.py.
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PriceObservationCoding:
    """
    One extracted price/offer observation. A single entity can have zero,
    one, or many of these in one response — e.g. a brand's price cited at
    three different retailers in the same answer yields three of these,
    all with the same comparison_code.
    """
    comparison_code: str  # which entity, e.g. "M001"
    stated_price: Optional[float] = None
    claimed_net_price: Optional[float] = None
    claimed_discount_value: Optional[float] = None
    claimed_discount_pct: Optional[float] = None
    claimed_terms: List[str] = field(default_factory=list)
    member_price_claimed: Optional[bool] = None
    subscription_offer_claimed: Optional[bool] = None
    # Verbatim retailer/seller name as stated by the agent for this
    # specific observation. Null if this observation names no seller.
    # Resolved against merchants.slug downstream
    # (parser/merchant_resolution.py) — never guessed here.
    merchant_name: Optional[str] = None
    evidence: Optional[str] = None


@dataclass
class CitationCoding:
    """One cited/linked source extracted from raw_response text. No
    fetching — url/domain/context all come from what the coder read."""
    url: str
    domain: str
    context: Optional[str] = None


@dataclass
class Pass2CodingResult:
    run_id: int
    price_observations: List[PriceObservationCoding]
    citations: List[CitationCoding]
    coding_latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
