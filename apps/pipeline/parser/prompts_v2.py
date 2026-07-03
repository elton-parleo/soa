"""
Pass-2 coding prompt/schema — deliberately separate from parser/prompts.py
(pass 1's SYSTEM_PROMPT / build_system_prompt / build_coding_schema, all
untouched). Pass 2 extracts ONLY per-observation merchant attribution and
citations, from raw_response text already known to mention a given set of
entities (passed in as context, not re-derived) — see
parser/response_coder_v2.py for how the mentioned-entity list is sourced
from pass 1's soa_coded_mentions.
"""
from typing import List

ENTITY_LIST_PLACEHOLDER = "{{ENTITY_LIST}}"

PASS2_SYSTEM_PROMPT = f"""You are a research analyst extracting price/offer observations and cited
sources from an AI shopping agent's response, for entities already
confirmed present in this response.

Entities confirmed mentioned in this response (extract observations only
for these; ignore any other brand or product named in passing):
{ENTITY_LIST_PLACEHOLDER}

PRICE/OFFER OBSERVATION EXTRACTION:
For each entity above, list every distinct price or offer the response
states for it — not just one. If the response quotes the same entity's
price at three different retailers, that is three separate observations,
each with its own merchant_name. If the response quotes only one price
for an entity, that is one observation. If the response states no price
or offer for an entity at all, it gets zero observations.

For each observation, extract:
  comparison_code: which entity this observation is for (from the list
    above).
  stated_price: the plain price quoted, before any discount. Null if no
    price stated for this observation.
  claimed_net_price: the final price after any discount/member
    price/promo. Null if the agent never gives a post-discount number
    for this observation.
  claimed_discount_value: the dollar amount of savings stated (e.g.
    "save $15" -> 15). Null if not stated as a dollar amount.
  claimed_discount_pct: the percentage discount stated (e.g. "20% off"
    -> 20). Null if not stated as a percentage.
  claimed_terms: short strings capturing any conditions attached (e.g.
    "orders over $50", "ends Friday"). Empty list if none.
  member_price_claimed: true if this observation is explicitly a
    loyalty-member-only price; false if explicitly stated as NOT
    member-restricted; null if not addressed.
  subscription_offer_claimed: true if this observation is a
    subscribe-and-save/recurring-order price; false if explicitly stated
    as not such an offer; null if not addressed.
  merchant_name: the retailer or seller this SPECIFIC observation's price
    is attributed to, exactly as named in the response (e.g. "Amazon",
    "Target", "Walmart's Pampers Size 3 listing" -> "Walmart").

    CRITICAL — brand vs. retailer: the entity under discussion is a
    BRAND (e.g. "Pampers"), not a retailer. If the response explicitly
    names a retailer as the source of a price (e.g. "Target lists
    Pampers Pure at $47.99", or a table with a "Source" / "Sold at"
    column naming a store), merchant_name MUST be that retailer
    ("Target") — never the brand itself, even if the brand's name
    appears right next to the price. Only use the brand's own name as
    merchant_name when the response explicitly signals the brand's own
    website as the seller (e.g. "on Pampers.com", "Pampers' official
    site", a pampers.com URL) — not merely because the brand is what's
    being discussed. If the response states a price with no named
    seller at all, merchant_name is null — never guess, and never
    default to the entity's own brand as a fallback seller.

CITED SOURCE EXTRACTION:
Separately, list every source the response cites or links to — a URL in
parentheses, a markdown link, an inline citation marker, or an
explicitly named source with a recognizable web address. For each one:
  url: the exact URL as it appears in the response. Do not construct,
    guess, or complete a partial URL — only include ones written out in
    full in the text.
  domain: the bare domain the url resolves to (e.g. "walmart.com").
  context: a short phrase describing what claim, product, or price this
    source is attached to, if clear from where it appears. Null
    otherwise.

If the response cites no sources, return an empty list — do not invent
one. If an entity has no price/offer observations, it simply has none in
the price_observations list — do not invent a placeholder.\
"""


def build_pass2_system_prompt(mentioned_entities: List[dict]) -> str:
    """
    mentioned_entities: list of {"comparison_code": str, "name": str} for
    entities pass 1 already confirmed as mentioned in this run. Only
    these are eligible for observation extraction. May be empty — a
    response can cite real third-party sources (VIS-02 material) while
    mentioning none of the tracked entities; citation extraction still
    runs, price_observations is just necessarily empty.
    """
    if mentioned_entities:
        lines = [f"{e['comparison_code']}: {e['name']}" for e in mentioned_entities]
    else:
        lines = ["(none — no tracked entity was mentioned in this response; "
                  "price_observations must be empty. Still extract citations below.)"]
    return PASS2_SYSTEM_PROMPT.replace(ENTITY_LIST_PLACEHOLDER, "\n".join(lines))


def build_pass2_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "price_observations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "comparison_code": {"type": "string"},
                        "stated_price": {"type": ["number", "null"]},
                        "claimed_net_price": {"type": ["number", "null"]},
                        "claimed_discount_value": {"type": ["number", "null"]},
                        "claimed_discount_pct": {"type": ["number", "null"]},
                        "claimed_terms": {"type": "array", "items": {"type": "string"}},
                        "member_price_claimed": {"type": ["boolean", "null"]},
                        "subscription_offer_claimed": {"type": ["boolean", "null"]},
                        "merchant_name": {"type": ["string", "null"]},
                        "evidence": {"type": ["string", "null"]},
                    },
                    "required": [
                        "comparison_code",
                        "stated_price",
                        "claimed_net_price",
                        "claimed_discount_value",
                        "claimed_discount_pct",
                        "claimed_terms",
                        "member_price_claimed",
                        "subscription_offer_claimed",
                        "merchant_name",
                        "evidence",
                    ],
                    "additionalProperties": False,
                },
            },
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "domain": {"type": "string"},
                        "context": {"type": ["string", "null"]},
                    },
                    "required": ["url", "domain", "context"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["price_observations", "citations"],
        "additionalProperties": False,
    }
