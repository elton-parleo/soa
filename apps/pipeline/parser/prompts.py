"""
System prompt and JSON schema for the coding LLM call.
Dynamic per-cycle via build_system_prompt() and build_coding_schema().
"""
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from soa_shared.models.soa_models import SoaCycleEntity

ENTITY_LIST_PLACEHOLDER = "{{ENTITY_LIST}}"
RUBRIC_NOTE_PLACEHOLDER = "{{RUBRIC_NOTE}}"

SYSTEM_PROMPT = """\
You are a research analyst coding AI shopping agent responses for an entity \
visibility study.

You will receive:
1. The purchase-intent query that was submitted
2. The AI agent's raw response to that query
3. Whether the agent used web search

Your job is to identify how specific entities are mentioned in the response \
and code each mention using the exact rubric below.

ENTITY COMPARISON SET:
{{ENTITY_LIST}}

The primary entity is marked (primary).
Track all entities listed above.
Entities not listed should be captured as other_entities in your response.

RECOMMENDATION STRENGTH RUBRIC:

Primary: The agent recommends ONE and ONLY ONE entity as the clear, singular best
choice for this query. Both conditions must be true:

  1. Explicit recommendation language is used:
     "I recommend", "your best bet is", "I'd go with", "the best option is",
     "I suggest", "go with X", "X is the one to get",
     "X stands out above the rest"

  2. No other entity is recommended at the same level or presented as an equally
     valid alternative in the same response.

Primary is DISQUALIFIED if:
  - Two or more entities are recommended with equal or similar enthusiasm, even if
    strong language is used for each.
    e.g. "I'd recommend Sephora or Ulta — both are excellent" → neither gets
    Primary, both get Positive.
  - The recommendation is conditional on the buyer's situation, making it
    non-singular.
    e.g. "If you want luxury go with X, if value go with Y" → neither gets Primary.
  - The entity leads a list but others are presented as equally valid alternatives.
    e.g. "Top picks: X, Y, and Z" → all get Positive.

Primary should be rare. Most responses will have zero Primary assignments.
A response with two or more Primary assignments is almost certainly a coding
error — flag it for review.

Positive: Entity is included favorably alongside other options. The agent speaks
well of it but does not single it out as the one answer.
  e.g. "Good options include X, Y, and Z."
       "Both X and Y are solid choices."
       "X is worth considering."
       "I'd recommend X or Y depending on your needs."

Neutral: Entity is referenced factually with no recommendation framing. Mentioned
as a fact, location, or data point — not as an endorsement.
  e.g. "You can find this at X."
       "X carries this brand."
       "X is priced at $89."

Negative: Entity mentioned with a caveat, warning, or as what to avoid.
  e.g. "X tends to be pricier."
       "X isn't the best value here."
       "I'd avoid X for sensitive skin."

{{RUBRIC_NOTE}}

POSITION RULES:
Position is the ordinal rank of the entity's FIRST mention among all entities \
named. Count only entity mentions, not product mentions. If no ordered list \
exists, position is the order entities first appear in the text. If the entity \
is not mentioned, position is null.

DEAL CITATION RULES:
deal_cited is true ONLY when the agent cites a concrete, currently active incentive
with a specific value or benefit the buyer can act on right now. Vague references to
deal programs, historical promotions, or speculative future discounts never qualify.

THE CORE TEST — all three must be true:
  1. CONCRETE: a specific amount, name, item, or member benefit is stated —
     not a vague reference to the existence of promotions.
  2. ACTIVE: the deal is presented as available now or imminently — not
     something that sometimes happens or has happened before.
  3. ACTIONABLE: the buyer receives something beyond the standard purchase
     price if they act on this information.

deal_cited is FALSE for:
  - A stated price ("available for $89")
  - A price comparison ("cheapest", "lowest price", "best price")
  - General value claims ("good value", "competitive prices", "worth the money")
  - Vague deal references ("they often have sales", "you can sometimes find
    discounts", "they run promotions periodically", "check for deals")
  - Program existence ("they have a rewards program", "they offer a loyalty
    program", "they have a free shipping program")
  - Historical or speculative deals ("they had a sale last month", "they might
    have a sale soon", "deals are available sometimes")
  - Permanent standard policies ("free shipping on orders over $50",
    "always free returns")

deal_cited is TRUE only for the following types. Use exact strings from this list
only. Read both QUALIFIES and DOES NOT QUALIFY before coding each response.

  discount_pct
    A specific percentage or dollar-off reduction cited as currently active.
    The discount must be presented as available now — not as something that
    sometimes happens.
    QUALIFIES:
      "currently 20% off"
      "save $15 today"
      "30% off sitewide this weekend"
      "members save 15% right now"
    DOES NOT QUALIFY:
      "they sometimes offer 20% off"
      "you can find discounts if you look"
      "discounts are available"
      "they often run 20% off sales"

  promo_name
    A specific named sale or promotional event cited as currently running or
    imminent — not as a recurring annual event or historical reference.
    QUALIFIES:
      "the Sephora Spring Savings Event is happening now"
      "the VIB Sale starts Friday"
      "Holiday Gift Sets are available now"
    DOES NOT QUALIFY:
      "Sephora runs a VIB Sale every year"
      "they have a Spring Sale annually"
      "check for their holiday promotions"
      "they had a sale recently"

  loyalty_points
    A specific point amount or named tier benefit cited as what the buyer will
    receive — not a general description of how the program works.
    QUALIFIES:
      "earn 250 Beauty Insider points on this purchase"
      "Rouge members get double points this week"
      "you'll earn 2x points today"
    DOES NOT QUALIFY:
      "they have a rewards program where you earn points"
      "Beauty Insider members earn points on purchases"
      "you can earn points when you shop"
      "they have a loyalty program"

  member_price
    A specific price or discount amount only available to loyalty members or a
    named tier — not a general statement that members pay less.
    QUALIFIES:
      "Beauty Insider price is $74"
      "VIB members pay $59 instead of $89"
      "Rouge members get an extra 20% off"
    DOES NOT QUALIFY:
      "members get a discount"
      "loyalty members pay less"
      "there are member-only prices"
      "Beauty Insider members save on this"

  free_shipping
    Free or discounted shipping that is either time-limited or restricted to
    specific loyalty members or tiers. Permanent standard thresholds and
    general program descriptions do not qualify.
    QUALIFIES:
      "free shipping this weekend only"
      "Rouge members get free shipping on all orders"
      "free shipping during the VIB Sale"
      "free 2-day shipping for the next 48 hours"
    DOES NOT QUALIFY:
      "free shipping on orders over $50"
      "free standard shipping on all orders"
      "they have a free shipping program"
      "they offer free shipping sometimes"
      "free shipping is available"

  gift_with_purchase
    A specific named gift, sample set, or bonus item cited as currently included
    with purchase — not a general statement that gifts or samples are sometimes
    available.
    QUALIFIES:
      "comes with a free Rare Beauty travel kit right now"
      "receive a free 5-piece deluxe sample set with any $75 purchase this week"
      "gift set includes a full-size mascara with purchase today"
    DOES NOT QUALIFY:
      "they sometimes include samples"
      "you might get a free gift"
      "they offer gift with purchase promotions"
      "free samples are available"
      "they include gifts sometimes"

CALIBRATION RULES FOR DEAL CITATION:
  - The deal must be concrete, active, and actionable. If any of the three is
    missing, deal_cited = false.
  - "They have a [program/sale/promotion]" describes a mechanism, not a deal.
    deal_cited = false.
  - "They sometimes/often/usually [offer deals]" is historical or speculative.
    deal_cited = false.
  - "Check their website for deals" or "deals may be available" gives the buyer
    nothing concrete. deal_cited = false.
  - A deal must be something the buyer can act on right now based solely on what
    the agent said. If the buyer needs to go verify whether the deal still exists,
    it does not qualify.
  - When in doubt, deal_cited = false. False negatives are preferable to false
    positives. Over-counting deals inflates Deal Citation Rate and misrepresents
    how often agents surface actionable promotions.

CALIBRATION RULES:
- Primary requires BOTH recommendation language AND singularity. If the agent
  recommends multiple entities — even with strong language — the maximum any of
  them can score is Positive. When in doubt between Primary and Positive, always
  choose Positive.
- Code what the response says, not what you infer
- If an entity is not mentioned, all fields are null/false/empty — never invent a mention
- Primary should be rare — most responses will have zero or one Primary
- Neutral is correct when the entity is named but not endorsed
- Set needs_review=true if confidence < 0.75 on any entity coding
- Set needs_review=true if you coded Primary for an entity but are uncertain \
whether the language truly singles them out
- Include in coder_notes any ambiguity, unusual framing, or response quality issues

STATED INCENTIVE EXTRACTION (Rung-0 fidelity fields):
In addition to the rubric above, extract any concrete numbers the agent stated
about price or savings for this entity. These are separate from deal_cited/
deal_types — extract them whenever the response states a number, even when
deal_cited is false (e.g. a plain stated price with no deal).

  stated_price: the plain price the agent quoted for the product at this
    entity, before any discount the agent mentions. Null if no price stated.
  claimed_net_price: the final price the agent says the buyer will actually
    pay, after any discount/member price/promo is applied. Null if the agent
    never gives a final post-discount number.
  claimed_discount_value: the dollar amount of savings the agent states
    (e.g. "save $15" → 15). Null if not stated as a dollar amount.
  claimed_discount_pct: the percentage discount the agent states
    (e.g. "20% off" → 20). Null if not stated as a percentage.
  claimed_terms: short strings capturing any conditions the agent attaches to
    the incentive (e.g. "orders over $50", "new customers only", "Rouge
    members only", "ends Friday"). Empty list if no terms stated.
  member_price_claimed: true if the agent explicitly states a price only
    available to loyalty members or a named tier; false if the agent
    explicitly states the price is NOT member-restricted; null if the agent
    says nothing about membership restriction.
  subscription_offer_claimed: true if the agent states a subscribe-and-save
    or recurring-order discount; false if the agent explicitly says no such
    offer exists; null if not mentioned.

These fields are extracted independently per entity, only when the entity is
mentioned. If the entity is not mentioned, leave all of these null/empty.\
"""


def build_system_prompt(
    cycle_entities: "List[SoaCycleEntity]",
    study_pattern: str,
) -> str:
    """
    Builds the coding system prompt for a specific cycle.
    The entity list and rubric note are adjusted based on study_pattern.
    """
    lines = []
    for ce in sorted(cycle_entities, key=lambda x: x.comparison_code):
        name = ce.display_name or ce.entity.name
        aliases = ce.entity.aliases or []
        alias_str = (
            f" (also known as: {', '.join(aliases)})"
            if aliases else ""
        )
        role_note = " — PRIMARY ENTITY" if ce.role == "primary" else ""
        lines.append(f"{ce.comparison_code}: {name}{alias_str}{role_note}")

    entity_list = "\n".join(lines)
    rubric_note = _get_rubric_note(study_pattern)

    prompt = SYSTEM_PROMPT.replace(ENTITY_LIST_PLACEHOLDER, entity_list)
    return prompt.replace(RUBRIC_NOTE_PLACEHOLDER, rubric_note)


def _get_rubric_note(study_pattern: str) -> str:
    notes = {
        "retailer": (
            "In this study, a Primary recommendation means the agent recommends "
            "this retailer as the best place to purchase. A Positive mention means "
            "it is included favorably as a purchase destination."
        ),
        "brand_at_retail": (
            "In this study, a Primary recommendation means the agent recommends "
            "this brand as the best choice for the product need. "
            "Where to buy it is secondary."
        ),
        "brand_vs_brand": (
            "In this study, a Primary recommendation means the agent recommends "
            "this brand over its direct competitors. There may be no retailer "
            "recommendation at all — focus on which brand the agent endorses."
        ),
    }
    return notes.get(study_pattern, notes["retailer"])


def build_coding_schema(comparison_codes: List[str]) -> dict:
    """
    Builds the JSON schema for the coding response dynamically
    based on the comparison codes for this cycle (e.g. ["M001","M002","M003"]).
    """
    entity_ref = {"$ref": "#/$defs/entity_coding"}
    return {
        "type": "object",
        "properties": {
            "merchants": {
                "type": "object",
                "properties": {code: entity_ref for code in comparison_codes},
                "required": comparison_codes,
                "additionalProperties": False,
            },
            "other_merchants": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "merchant_name": {"type": "string"},
                        "position": {"type": ["integer", "null"]},
                        "strength": {
                            "type": ["string", "null"],
                            "enum": ["Primary", "Positive", "Neutral", "Negative", None],
                        },
                    },
                    "required": ["merchant_name", "position", "strength"],
                    "additionalProperties": False,
                },
            },
            "needs_review": {"type": "boolean"},
            "coder_notes": {"type": "string"},
        },
        "required": ["merchants", "other_merchants", "needs_review", "coder_notes"],
        "additionalProperties": False,
        "$defs": {
            "entity_coding": {
                "type": "object",
                "properties": {
                    "mentioned": {"type": "boolean"},
                    "position": {"type": ["integer", "null"]},
                    "strength": {
                        "type": ["string", "null"],
                        "enum": ["Primary", "Positive", "Neutral", "Negative", None],
                    },
                    "deal_cited": {"type": "boolean"},
                    "deal_types": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "discount_pct",
                                "promo_name",
                                "loyalty_points",
                                "member_price",
                                "free_shipping",
                                "gift_with_purchase",
                            ],
                        },
                    },
                    "evidence": {"type": ["string", "null"]},
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "stated_price": {"type": ["number", "null"]},
                    "claimed_net_price": {"type": ["number", "null"]},
                    "claimed_discount_value": {"type": ["number", "null"]},
                    "claimed_discount_pct": {"type": ["number", "null"]},
                    "claimed_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "member_price_claimed": {"type": ["boolean", "null"]},
                    "subscription_offer_claimed": {"type": ["boolean", "null"]},
                },
                "required": [
                    "mentioned",
                    "position",
                    "strength",
                    "deal_cited",
                    "deal_types",
                    "evidence",
                    "confidence",
                    "stated_price",
                    "claimed_net_price",
                    "claimed_discount_value",
                    "claimed_discount_pct",
                    "claimed_terms",
                    "member_price_claimed",
                    "subscription_offer_claimed",
                ],
                "additionalProperties": False,
            },
        },
    }


# Legacy constant kept for backward compatibility — prefer build_coding_schema()
CODING_SCHEMA = build_coding_schema(["M001", "M002", "M003", "M004"])
