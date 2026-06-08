"""
Idempotent seed for soa_queries.

Run as many times as needed — duplicate query_codes are silently
skipped via INSERT ... ON CONFLICT (query_code) DO NOTHING.

Usage:
    cd /soa && python -m seeds.soa_queries_seed
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

load_dotenv()

# ---------------------------------------------------------------------------
# 50 SoA query definitions
# (The spec listed 45 but the provided data totals 50:
#  SK×15, MK×12, FR×10, HC×8, XC×5)
# ---------------------------------------------------------------------------

QUERIES = [
    # SKINCARE
    {
        "query_code": "SK-01",
        "query_text": "Where is the best place to buy skincare products online?",
        "category": "Skincare",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "Mention Rate, Position Index",
        "rationale": (
            "Open category query that reveals default agent framing for online beauty "
            "retail. Tests whether Sephora is the default recommendation vs. Ulta, "
            "brand sites, or Amazon."
        ),
    },
    {
        "query_code": "SK-02",
        "query_text": "What skincare routine should a beginner start with?",
        "category": "Skincare",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "Mention Rate, RSI",
        "rationale": (
            "High-volume beginner query. Tests whether agents recommend Sephora as a "
            "destination for building a routine or route buyers to brand-direct sites."
        ),
    },
    {
        "query_code": "SK-03",
        "query_text": "What ingredients should I look for in a moisturizer for oily skin?",
        "category": "Skincare",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Beauty Enthusiast",
        "soa_focus": "Mention Rate, Deal Citation Rate",
        "rationale": (
            "Ingredient-focused research query. Tests whether agents connect ingredient "
            "recommendations to specific products available at Sephora."
        ),
    },
    {
        "query_code": "SK-04",
        "query_text": "Is Sephora or Ulta better for skincare?",
        "category": "Skincare",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "soa_focus": "RSI, Position Index",
        "rationale": (
            "Direct head-to-head comparison. Critical for understanding how agents "
            "frame Sephora vs. its primary competitor."
        ),
    },
    {
        "query_code": "SK-05",
        "query_text": (
            "Is it worth buying skincare at Sephora or should I buy directly from the brand?"
        ),
        "category": "Skincare",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "soa_focus": "RSI, Deal Citation Rate",
        "rationale": "Tests agent reasoning about retailer vs. brand-direct channel.",
    },
    {
        "query_code": "SK-06",
        "query_text": "Best vitamin C serum available at Sephora right now",
        "category": "Skincare",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Beauty Enthusiast",
        "soa_focus": "Deal Citation Rate, RSI",
        "rationale": (
            "Mid-specificity product category query with Sephora named. Tests depth of "
            "product knowledge and whether agents cite current pricing or promotions."
        ),
    },
    {
        "query_code": "SK-07",
        "query_text": (
            "What is the best retinol product for someone with sensitive skin who is "
            "new to retinoids?"
        ),
        "category": "Skincare",
        "stage": "Comparison",
        "specificity": "Narrow",
        "persona": "Beauty Enthusiast",
        "soa_focus": "Mention Rate, Position Index",
        "rationale": (
            "Specific formulation and skin type constraint. Tests whether agents "
            "recommend products available at Sephora by name."
        ),
    },
    {
        "query_code": "SK-08",
        "query_text": (
            "Where should I buy the Drunk Elephant C-Firma Fresh Day Serum — best "
            "price and any current deals?"
        ),
        "category": "Skincare",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious",
        "soa_focus": "Deal Citation Rate, Position Index",
        "rationale": (
            "Specific branded product with explicit deal intent. High-value test of "
            "Deal Citation Rate."
        ),
    },
    {
        "query_code": "SK-09",
        "query_text": "Best deal on La Mer moisturizer — is Sephora the cheapest option?",
        "category": "Skincare",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious",
        "soa_focus": "Deal Citation Rate, RSI",
        "rationale": (
            "Premium SKU price comparison query. Tests whether agents reference "
            "Sephora pricing accurately and loyalty points."
        ),
    },
    {
        "query_code": "SK-10",
        "query_text": "Does Sephora have any skincare sales or promotions happening right now?",
        "category": "Skincare",
        "stage": "Ready to Buy",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "soa_focus": "Deal Citation Rate",
        "rationale": (
            "Direct deal-discovery query. Most direct test of whether agents can "
            "surface Sephora current promotional activity."
        ),
    },
    {
        "query_code": "SK-11",
        "query_text": "Is the Sephora Beauty Insider program worth it for skincare purchases?",
        "category": "Skincare",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "soa_focus": "Deal Citation Rate, RSI",
        "rationale": (
            "Loyalty program evaluation query. Tests whether agents accurately "
            "represent Beauty Insider benefits."
        ),
    },
    {
        "query_code": "SK-12",
        "query_text": "What are the best skincare products under $30 I can get at Sephora?",
        "category": "Skincare",
        "stage": "Ready to Buy",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "soa_focus": "Mention Rate, Deal Citation Rate",
        "rationale": "Budget-constrained product discovery within a named retailer.",
    },
    {
        "query_code": "SK-13",
        "query_text": (
            "What is the difference between Sephora Collection skincare and high-end "
            "brands they carry?"
        ),
        "category": "Skincare",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "RSI, Mention Rate",
        "rationale": (
            "Private label vs. national brand comparison. Tests whether agents "
            "understand and recommend Sephora's own brand."
        ),
    },
    {
        "query_code": "SK-14",
        "query_text": (
            "I want to start using a peptide moisturizer — what does Sephora carry "
            "and what is the best option for anti-aging?"
        ),
        "category": "Skincare",
        "stage": "Comparison",
        "specificity": "Narrow",
        "persona": "Beauty Enthusiast",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Specific ingredient category with anti-aging intent and retailer named.",
    },
    {
        "query_code": "SK-15",
        "query_text": "When is the next Sephora sale and how much can I save on skincare?",
        "category": "Skincare",
        "stage": "Ready to Buy",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "soa_focus": "Deal Citation Rate",
        "rationale": (
            "Forward-looking deal timing query. Tests whether agents know Sephora "
            "sale calendar."
        ),
    },
    # MAKEUP
    {
        "query_code": "MK-01",
        "query_text": "What is the best foundation for a natural, no-makeup look?",
        "category": "Makeup",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "Mention Rate, Position Index",
        "rationale": (
            "High-volume makeup research query. Tests whether agents recommend "
            "products available at Sephora."
        ),
    },
    {
        "query_code": "MK-02",
        "query_text": (
            "Should I buy makeup at Sephora or Ulta — which has better brands and prices?"
        ),
        "category": "Makeup",
        "stage": "Comparison",
        "specificity": "Broad",
        "persona": "Value-Conscious",
        "soa_focus": "RSI, Position Index",
        "rationale": "Primary competitive comparison for makeup.",
    },
    {
        "query_code": "MK-03",
        "query_text": (
            "Best long-wearing lipstick at Sephora — what do beauty editors actually recommend?"
        ),
        "category": "Makeup",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Beauty Enthusiast",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Product category query with editorial authority framing.",
    },
    {
        "query_code": "MK-04",
        "query_text": (
            "Is the Charlotte Tilbury Pillow Talk lipstick worth the price — and where "
            "is the best place to buy it?"
        ),
        "category": "Makeup",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "Deal Citation Rate, Position Index",
        "rationale": (
            "Specific hero product purchase query. Charlotte Tilbury is a key "
            "Sephora brand."
        ),
    },
    {
        "query_code": "MK-05",
        "query_text": (
            "What makeup products does Sephora exclusively carry that I cannot buy "
            "anywhere else?"
        ),
        "category": "Makeup",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Beauty Enthusiast",
        "soa_focus": "RSI, Mention Rate",
        "rationale": (
            "Exclusive product discovery query. Tests whether agents accurately "
            "represent Sephora exclusive brand relationships."
        ),
    },
    {
        "query_code": "MK-06",
        "query_text": (
            "Best concealer for dark circles under $40 — what should I buy at Sephora?"
        ),
        "category": "Makeup",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious",
        "soa_focus": "Deal Citation Rate, Mention Rate",
        "rationale": "Budget-constrained specific product query within a named retailer.",
    },
    {
        "query_code": "MK-07",
        "query_text": "What is the best setting spray to make foundation last all day?",
        "category": "Makeup",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "Mention Rate, RSI",
        "rationale": (
            "Product category research without retailer named. Tests unprompted "
            "Sephora recommendation behavior."
        ),
    },
    {
        "query_code": "MK-08",
        "query_text": (
            "I want to buy the Rare Beauty blush everyone is talking about — is "
            "Sephora the only place to get it and do they ever have deals on it?"
        ),
        "category": "Makeup",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "Deal Citation Rate, RSI",
        "rationale": (
            "Viral product with exclusivity and deal intent. Rare Beauty is a "
            "Sephora-exclusive brand."
        ),
    },
    {
        "query_code": "MK-09",
        "query_text": "What are the best makeup gifts to buy from Sephora for a teenager?",
        "category": "Makeup",
        "stage": "Ready to Buy",
        "specificity": "Mid",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "Deal Citation Rate, RSI",
        "rationale": (
            "Gift-occasion query with age constraint. Tests whether agents recommend "
            "Sephora gift sets."
        ),
    },
    {
        "query_code": "MK-10",
        "query_text": "Is drugstore makeup just as good as what you buy at Sephora?",
        "category": "Makeup",
        "stage": "Comparison",
        "specificity": "Broad",
        "persona": "Value-Conscious",
        "soa_focus": "RSI, Mention Rate",
        "rationale": "Value channel comparison. Tests how agents defend prestige makeup pricing.",
    },
    {
        "query_code": "MK-11",
        "query_text": (
            "What is the best foundation shade matching service and does Sephora offer it?"
        ),
        "category": "Makeup",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "RSI, Mention Rate",
        "rationale": (
            "Service capability query. Tests whether agents represent Sephora Color IQ "
            "as a differentiator."
        ),
    },
    {
        "query_code": "MK-12",
        "query_text": (
            "NARS Sheer Glow foundation versus Charlotte Tilbury Airbrush Flawless — "
            "which should I buy and where is the best price?"
        ),
        "category": "Makeup",
        "stage": "Comparison",
        "specificity": "Narrow",
        "persona": "Beauty Enthusiast",
        "soa_focus": "Deal Citation Rate, Position Index",
        "rationale": (
            "Head-to-head premium foundation comparison with price intent. Both brands "
            "sold at Sephora."
        ),
    },
    # FRAGRANCE
    {
        "query_code": "FR-01",
        "query_text": "What is a good perfume to give as a gift for a woman in her 40s?",
        "category": "Fragrance",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "Mention Rate, RSI",
        "rationale": (
            "High-volume gift occasion fragrance query. Tests whether Sephora is "
            "recommended as a destination for fragrance gifts."
        ),
    },
    {
        "query_code": "FR-02",
        "query_text": (
            "Where is the best place to buy perfume online — Sephora, Nordstrom, or "
            "the brand website?"
        ),
        "category": "Fragrance",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "soa_focus": "RSI, Position Index",
        "rationale": (
            "Retailer comparison for fragrance. Tests Sephora positioning against "
            "department stores and brand-direct."
        ),
    },
    {
        "query_code": "FR-03",
        "query_text": (
            "What are the best long-lasting perfumes for women that are not too expensive?"
        ),
        "category": "Fragrance",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "soa_focus": "Mention Rate, Position Index",
        "rationale": "Quality and value fragrance research without retailer named.",
    },
    {
        "query_code": "FR-04",
        "query_text": "Does Sephora sell fragrance samples and how does it work?",
        "category": "Fragrance",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Beauty Enthusiast",
        "soa_focus": "RSI, Mention Rate",
        "rationale": (
            "Sephora-specific service query. Tests whether agents know about Sephora "
            "fragrance sampling program."
        ),
    },
    {
        "query_code": "FR-05",
        "query_text": (
            "Best Maison Margiela Replica fragrance — which one should I buy and where "
            "do I get the best deal?"
        ),
        "category": "Fragrance",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Beauty Enthusiast",
        "soa_focus": "Deal Citation Rate, Position Index",
        "rationale": (
            "Specific prestige fragrance brand with deal intent. Maison Margiela Replica "
            "is carried at Sephora."
        ),
    },
    {
        "query_code": "FR-06",
        "query_text": "What is a good everyday perfume for under $80?",
        "category": "Fragrance",
        "stage": "Ready to Buy",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "soa_focus": "Deal Citation Rate, Mention Rate",
        "rationale": "Budget-constrained everyday fragrance query.",
    },
    {
        "query_code": "FR-07",
        "query_text": (
            "I want to smell like a luxury hotel lobby — what perfume should I get and "
            "where should I buy it?"
        ),
        "category": "Fragrance",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Evocative purchase intent query common in conversational shopping.",
    },
    {
        "query_code": "FR-08",
        "query_text": "Does Sephora have any fragrance deals or gift sets for the holidays?",
        "category": "Fragrance",
        "stage": "Ready to Buy",
        "specificity": "Mid",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "Deal Citation Rate",
        "rationale": (
            "Seasonal deal and gift set query. Tests whether agents can surface "
            "Sephora fragrance promotional activity."
        ),
    },
    {
        "query_code": "FR-09",
        "query_text": (
            "What is the difference between eau de parfum and eau de toilette and does "
            "it affect which one I should buy at Sephora?"
        ),
        "category": "Fragrance",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "Mention Rate, RSI",
        "rationale": (
            "Education query with Sephora named. Tests whether agents use educational "
            "response to reinforce Sephora as the recommended destination."
        ),
    },
    {
        "query_code": "FR-10",
        "query_text": (
            "What are the best new perfume launches of 2026 and can I get them at Sephora?"
        ),
        "category": "Fragrance",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Beauty Enthusiast",
        "soa_focus": "Mention Rate, RSI",
        "rationale": (
            "Newness and trend query. Tests whether agents position Sephora as the "
            "destination for new fragrance launches."
        ),
    },
    # HAIRCARE
    {
        "query_code": "HC-01",
        "query_text": "What are the best shampoos for dry, damaged hair?",
        "category": "Haircare",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "Mention Rate, Position Index",
        "rationale": (
            "High-volume generic haircare research query. Tests whether Sephora is "
            "mentioned as a haircare destination."
        ),
    },
    {
        "query_code": "HC-02",
        "query_text": "Is Sephora or Ulta better for haircare products?",
        "category": "Haircare",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Beauty Enthusiast",
        "soa_focus": "RSI, Position Index",
        "rationale": (
            "Direct haircare retailer comparison. Ulta has traditionally been stronger "
            "in haircare."
        ),
    },
    {
        "query_code": "HC-03",
        "query_text": (
            "Best hair oil for frizzy hair — what does Sephora carry that actually works?"
        ),
        "category": "Haircare",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "soa_focus": "Mention Rate, RSI",
        "rationale": (
            "Product category query within a named retailer. Tests whether agents can "
            "navigate Sephora haircare catalog."
        ),
    },
    {
        "query_code": "HC-04",
        "query_text": "Is Olaplex worth the price and where is the cheapest place to buy it?",
        "category": "Haircare",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious",
        "soa_focus": "Deal Citation Rate, Position Index",
        "rationale": (
            "Specific brand value justification with price intent. Olaplex is available "
            "at Sephora and many other retailers."
        ),
    },
    {
        "query_code": "HC-05",
        "query_text": (
            "What is the best heat protectant spray before blow drying and does "
            "Sephora carry it?"
        ),
        "category": "Haircare",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "Mention Rate, Deal Citation Rate",
        "rationale": "Specific product need with Sephora named. Tests product catalog accuracy.",
    },
    {
        "query_code": "HC-06",
        "query_text": "What are the best hair products for curly hair that Sephora sells?",
        "category": "Haircare",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Beauty Enthusiast",
        "soa_focus": "Mention Rate, RSI",
        "rationale": (
            "Specific hair type query within Sephora catalog. Tests depth of product "
            "knowledge for a high-engagement segment."
        ),
    },
    {
        "query_code": "HC-07",
        "query_text": (
            "Does Sephora have good haircare brands or should I go to a salon supply store?"
        ),
        "category": "Haircare",
        "stage": "Comparison",
        "specificity": "Broad",
        "persona": "Beauty Enthusiast",
        "soa_focus": "RSI, Position Index",
        "rationale": "Channel comparison pitting Sephora against professional supply stores.",
    },
    {
        "query_code": "HC-08",
        "query_text": (
            "Best Sephora haircare products to buy with Beauty Insider points — what "
            "gives me the most value?"
        ),
        "category": "Haircare",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious",
        "soa_focus": "Deal Citation Rate, RSI",
        "rationale": (
            "Loyalty-maximization query specific to Sephora. Tests whether agents "
            "understand Beauty Insider point redemption value."
        ),
    },
    # CROSS-CATEGORY
    {
        "query_code": "XC-01",
        "query_text": (
            "I have a $200 budget to spend at Sephora — what should I buy to build a "
            "good skincare and makeup routine?"
        ),
        "category": "Cross-Category",
        "stage": "Ready to Buy",
        "specificity": "Mid",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "Deal Citation Rate, RSI",
        "rationale": (
            "Budget allocation query spanning multiple categories. Tests whether agents "
            "can build a coherent multi-category basket."
        ),
    },
    {
        "query_code": "XC-02",
        "query_text": (
            "Is Sephora's Beauty Insider loyalty program better than Ulta's "
            "Ultamate Rewards?"
        ),
        "category": "Cross-Category",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "soa_focus": "Deal Citation Rate, RSI",
        "rationale": (
            "Direct loyalty program comparison. Most important deal-related competitive "
            "query in the library."
        ),
    },
    {
        "query_code": "XC-03",
        "query_text": "What are the best things to buy at Sephora during a sale?",
        "category": "Cross-Category",
        "stage": "Ready to Buy",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "soa_focus": "Deal Citation Rate, Mention Rate",
        "rationale": (
            "Sale optimization query. Tests whether agents know which Sephora categories "
            "offer the best value during sale events."
        ),
    },
    {
        "query_code": "XC-04",
        "query_text": "What beauty products does Sephora sell that you cannot get anywhere else?",
        "category": "Cross-Category",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Beauty Enthusiast",
        "soa_focus": "RSI, Mention Rate",
        "rationale": "Exclusive product discovery query across all categories.",
    },
    {
        "query_code": "XC-05",
        "query_text": (
            "Should I shop at Sephora in store or online — is one better than the other?"
        ),
        "category": "Cross-Category",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "soa_focus": "RSI, Mention Rate",
        "rationale": "Channel preference query unique to Sephora omnichannel model.",
    },
]


INSERT_SQL = text("""
    INSERT INTO soa_queries
        (query_code, query_text, category, stage, specificity, persona,
         soa_focus, rationale, status, study_type, study_pattern)
    VALUES
        (:query_code, :query_text, :category, :stage, :specificity, :persona,
         :soa_focus, :rationale, 'Active', 'retailer_sephora', 'retailer')
    ON CONFLICT (query_code) DO UPDATE SET
        study_type    = EXCLUDED.study_type,
        study_pattern = EXCLUDED.study_pattern
""")


def _get_engine():
    host = os.getenv("SUPABASE_DB_HOST_URL")
    password = os.getenv("SUPABASE_DB_PASSWORD")
    if not host or not password:
        raise RuntimeError(
            "SUPABASE_DB_HOST_URL and SUPABASE_DB_PASSWORD must be set. "
            "Copy /soa/.env.example to /soa/.env and fill in your credentials."
        )
    db_url = URL.create(
        drivername="postgresql",
        username="postgres.epuofomhfngvkkamlfiz",
        host=host,
        database="postgres",
        port="6543",
        password=password,
    )
    return create_engine(db_url, pool_pre_ping=True)


def run_seed(engine=None):
    if engine is None:
        engine = _get_engine()

    with engine.begin() as conn:
        result = conn.execute(INSERT_SQL, QUERIES)
        inserted = result.rowcount

    print(
        f"Seed complete: {inserted} new rows inserted, "
        f"{len(QUERIES) - inserted} already existed."
    )
    return inserted


if __name__ == "__main__":
    run_seed()
