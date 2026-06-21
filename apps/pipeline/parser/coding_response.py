from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class MerchantCoding:
    merchant_id: str
    mentioned: bool
    position: Optional[int]
    strength: Optional[str]
    deal_cited: bool
    deal_types: List[str]
    evidence: Optional[str]
    confidence: float
    # Rung-0 incentive fields — additive, default empty/None when not stated.
    stated_price: Optional[float] = None
    claimed_net_price: Optional[float] = None
    claimed_discount_value: Optional[float] = None
    claimed_discount_pct: Optional[float] = None
    claimed_terms: List[str] = field(default_factory=list)
    member_price_claimed: Optional[bool] = None
    subscription_offer_claimed: Optional[bool] = None


@dataclass
class OtherMerchantCoding:
    merchant_name: str
    position: Optional[int]
    strength: Optional[str]


@dataclass
class CodingResponse:
    run_id: int
    merchants: Dict[str, MerchantCoding]
    other_merchants: List[OtherMerchantCoding]
    needs_review: bool
    coder_notes: str
    coding_latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
