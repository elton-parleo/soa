"""
Idempotent seed for Gillette brand grooming queries.

Seeds 50 Gillette queries into soa_queries with study_type='brand_gillette'.
Mix of brand_vs_brand (43) and brand_at_retail (7) study patterns.

Usage:
    cd /soa && python seeds/gillette_queries_seed.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from soa_shared.database import engine, session_factory
from soa_shared.models.soa_models import SoaQuery
from sqlalchemy import text

STUDY_TYPE = "brand_gillette"

ALLOWED_STAGES = {"Research", "Comparison", "Ready to Buy"}
ALLOWED_SPECIFICITY = {"Broad", "Mid", "Narrow"}
ALLOWED_PERSONAS = {
    "Casual / Gift Buyer",
    "Value-Conscious",
    "Beauty Enthusiast",
    "Problem-Skin Sufferer",
    "Eco-Conscious / Minimalist",
}
ALLOWED_PATTERNS = {
    "retailer",
    "brand_at_retail",
    "brand_vs_brand",
}

QUERIES = [
    # -----------------------------------------------------------------------
    # CASUAL / GIFT BUYER — 10 queries (5 Broad, 3 Mid, 2 Narrow)
    # -----------------------------------------------------------------------
    {
        "query_code": "GROOM_RES_BRD_CAS_01",
        "query_text": "What are the most popular shaving brands for men available at Target right now?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, Position Index",
        "rationale": "Tests top-of-mind organic baseline share of voice for Gillette at a major retailer.",
    },
    {
        "query_code": "GROOM_RES_BRD_CAS_02",
        "query_text": "What is a good shaving gift set to buy for a man?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "High-volume gift intent query. Tests whether agents default to Gillette for men's shaving gifts.",
    },
    {
        "query_code": "GROOM_RES_BRD_CAS_03",
        "query_text": "What razors do most men use?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Popularity-framing query. Gillette's historical market leadership makes this a key SoA signal.",
    },
    {
        "query_code": "GROOM_RES_BRD_CAS_04",
        "query_text": "What are the best men's grooming brands overall?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Broad brand category query. Tests Gillette salience against Schick, Harry's, and Dollar Shave Club.",
    },
    {
        "query_code": "GROOM_RES_BRD_CAS_05",
        "query_text": "Is Gillette still the best razor brand or have newer brands caught up?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Direct brand equity query. Measures how agents frame Gillette's competitive position.",
    },
    {
        "query_code": "GROOM_RES_MID_CAS_06",
        "query_text": "What's a good razor to buy my dad as a gift?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Occasion-specific gift research. Tests Gillette recommendation rate for father-directed purchases.",
    },
    {
        "query_code": "GROOM_RES_MID_CAS_07",
        "query_text": "What shaving cream goes best with a Gillette razor?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, Deal Citation Rate",
        "rationale": "Brand-anchored accessory query. Tests whether agents recommend Gillette shaving cream or cross-sell competitors.",
    },
    {
        "query_code": "GROOM_CMP_MID_CAS_08",
        "query_text": "Gillette vs Harry's — which razor is better for everyday use?",
        "category": "Grooming",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Head-to-head comparison between the market leader and the leading DTC challenger.",
    },
    {
        "query_code": "GROOM_BUY_NAR_CAS_09",
        "query_text": "Where can I buy a Gillette Fusion razor starter kit online?",
        "category": "Grooming",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, Deal Citation Rate",
        "rationale": "High-intent product-specific purchase query. Tests retailer recommendation for Gillette flagship product.",
    },
    {
        "query_code": "GROOM_BUY_NAR_CAS_10",
        "query_text": "Best place to buy Gillette razor blades in bulk — Amazon, Costco, or Target?",
        "category": "Grooming",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Deal Citation Rate, Mention Rate",
        "rationale": "Retailer-selection query for blade replenishment. Tests deal citation and retailer preference for Gillette consumables.",
    },
    # -----------------------------------------------------------------------
    # VALUE-CONSCIOUS — 10 queries (5 Broad, 3 Mid, 2 Narrow)
    # -----------------------------------------------------------------------
    {
        "query_code": "GROOM_RES_BRD_VAL_11",
        "query_text": "What is the cheapest good razor brand that isn't disposable?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Value-framed brand discovery. Tests whether agents recommend Gillette or position it as premium versus value alternatives.",
    },
    {
        "query_code": "GROOM_RES_BRD_VAL_12",
        "query_text": "Is Dollar Shave Club cheaper than Gillette over time?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Mention Rate",
        "rationale": "Direct cost-comparison query between Gillette and its primary subscription challenger.",
    },
    {
        "query_code": "GROOM_RES_BRD_VAL_13",
        "query_text": "Are Gillette razor blade refills worth the price or should I switch brands?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Mention Rate",
        "rationale": "Retention-risk query. Measures agent framing of Gillette blade pricing relative to competitors.",
    },
    {
        "query_code": "GROOM_RES_BRD_VAL_14",
        "query_text": "What is the best budget men's razor that still gives a close shave?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Budget-quality tradeoff query. Tests whether Gillette Mach3 or SkinGuard is recommended at the value tier.",
    },
    {
        "query_code": "GROOM_RES_BRD_VAL_15",
        "query_text": "How do I save money on shaving without sacrificing quality?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Deal Citation Rate, RSI",
        "rationale": "Value optimization query. Tests whether agents recommend Gillette products or steer toward cheaper alternatives.",
    },
    {
        "query_code": "GROOM_CMP_MID_VAL_16",
        "query_text": "Gillette Mach3 versus Schick Hydro — which is better value for money?",
        "category": "Grooming",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Value-tier head-to-head between the two legacy market leaders.",
    },
    {
        "query_code": "GROOM_CMP_BRD_VAL_17",
        "query_text": "Gillette vs Schick vs Harry's — which razor brand gives the best value?",
        "category": "Grooming",
        "stage": "Comparison",
        "specificity": "Broad",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Three-way value comparison across the top razor brands. Key metric for RSI positioning.",
    },
    {
        "query_code": "GROOM_CMP_MID_VAL_18",
        "query_text": "Are subscription razor services like Harry's or Dollar Shave Club actually cheaper than buying Gillette at the store?",
        "category": "Grooming",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Deal Citation Rate",
        "rationale": "Subscription vs retail cost comparison. Tests how agents frame total cost of ownership for Gillette.",
    },
    {
        "query_code": "GROOM_BUY_NAR_VAL_19",
        "query_text": "Where is the best deal on Gillette Fusion5 blades right now?",
        "category": "Grooming",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Deal Citation Rate, Mention Rate",
        "rationale": "Deal-seeking ready-to-buy query for the flagship blade. Critical for deal citation rate metric.",
    },
    {
        "query_code": "GROOM_BUY_NAR_VAL_20",
        "query_text": "Is there a coupon or promo code for Gillette razors at Walmart or Target?",
        "category": "Grooming",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Deal Citation Rate, Mention Rate",
        "rationale": "Promotion-seeking purchase intent. Tests agent knowledge of Gillette retailer deals.",
    },
    # -----------------------------------------------------------------------
    # BEAUTY ENTHUSIAST — 10 queries (5 Broad, 3 Mid, 2 Narrow)
    # -----------------------------------------------------------------------
    {
        "query_code": "GROOM_RES_BRD_BEA_21",
        "query_text": "What is the best multi-blade razor system for a smooth close shave with no irritation?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Beauty Enthusiast",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Mention Rate",
        "rationale": "Quality-focused research query. Tests Gillette's premium blade positioning against Schick Hydro and Harry's.",
    },
    {
        "query_code": "GROOM_RES_BRD_BEA_22",
        "query_text": "What are the differences between Gillette Fusion5, ProShield, and SkinGuard?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Beauty Enthusiast",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Intra-brand differentiation query. Tests depth of Gillette product knowledge in agent responses.",
    },
    {
        "query_code": "GROOM_RES_BRD_BEA_23",
        "query_text": "Is a safety razor or a cartridge razor like Gillette better for skin health?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Beauty Enthusiast",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Mention Rate",
        "rationale": "Format comparison query. Tests how agents position Gillette cartridges versus traditional safety razors.",
    },
    {
        "query_code": "GROOM_RES_BRD_BEA_24",
        "query_text": "What shaving products do professional barbers recommend for at-home use?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Beauty Enthusiast",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Authority-framed research. Tests whether professional endorsement contexts favor Gillette or premium alternatives.",
    },
    {
        "query_code": "GROOM_RES_BRD_BEA_25",
        "query_text": "What grooming brands are considered premium for men's shaving?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Beauty Enthusiast",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Premium positioning query. Tests whether Gillette is framed as premium or mainstream versus brands like Art of Shaving.",
    },
    {
        "query_code": "GROOM_CMP_MID_BEA_26",
        "query_text": "Gillette ProShield versus Schick Hydro 5 Sensitive — which is better for skin?",
        "category": "Grooming",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Beauty Enthusiast",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Skin-care focused head-to-head in the sensitive skin segment.",
    },
    {
        "query_code": "GROOM_CMP_MID_BEA_27",
        "query_text": "Gillette versus Braun electric razor — which gives a better shave?",
        "category": "Grooming",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Beauty Enthusiast",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Wet vs dry shave format comparison. Braun is a sister P&G brand — tests intra-P&G recommendation dynamics.",
    },
    {
        "query_code": "GROOM_CMP_MID_BEA_28",
        "query_text": "Which shaving brand has the best after-shave care products — Gillette, Nivea, or Jack Black?",
        "category": "Grooming",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Beauty Enthusiast",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Mention Rate",
        "rationale": "Post-shave care comparison. Tests Gillette's share of voice in the grooming accessories segment.",
    },
    {
        "query_code": "GROOM_BUY_NAR_BEA_29",
        "query_text": "Where can I buy the Gillette King C Gillette beard trimmer and is it worth it?",
        "category": "Grooming",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Beauty Enthusiast",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, Deal Citation Rate",
        "rationale": "Specific product discovery for Gillette's premium beard care line. Tests retailer recommendation and product familiarity.",
    },
    {
        "query_code": "GROOM_BUY_NAR_BEA_30",
        "query_text": "Gillette Heated Razor versus regular Fusion — is the heated razor worth the extra cost?",
        "category": "Grooming",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Beauty Enthusiast",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Premium product upgrade query. Tests agent recommendation of Gillette's highest-margin product.",
    },
    # -----------------------------------------------------------------------
    # PROBLEM-SKIN SUFFERER — 12 queries (5 Broad, 4 Mid, 3 Narrow)
    # -----------------------------------------------------------------------
    {
        "query_code": "GROOM_RES_BRD_SKN_31",
        "query_text": "What is the best razor brand for men with extremely sensitive skin?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Problem-Skin Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Core sensitive-skin brand discovery. Tests Gillette SkinGuard positioning against Schick Hydro Sensitive.",
    },
    {
        "query_code": "GROOM_RES_BRD_SKN_32",
        "query_text": "How do I prevent razor bumps and ingrown hairs when shaving?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Problem-Skin Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Problem-solution research. Tests whether agents recommend Gillette SkinGuard or other solutions for ingrown hair prevention.",
    },
    {
        "query_code": "GROOM_RES_BRD_SKN_33",
        "query_text": "What shaving brands are dermatologist recommended for acne-prone skin?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Problem-Skin Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Mention Rate",
        "rationale": "Authority-endorsed product query for a high-concern segment. Tests clinical framing of Gillette SkinGuard.",
    },
    {
        "query_code": "GROOM_RES_BRD_SKN_34",
        "query_text": "Is a fewer-blade razor better for sensitive skin than a 5-blade razor?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Problem-Skin Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Mention Rate",
        "rationale": "Blade-count myth-busting query. Tests how agents handle the sensitive skin vs multi-blade tradeoff affecting Gillette positioning.",
    },
    {
        "query_code": "GROOM_RES_BRD_SKN_35",
        "query_text": "What shaving routine should I follow if I have rosacea?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Problem-Skin Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Specific dermatological condition query. Tests Gillette SkinGuard recommendation in a medically sensitive context.",
    },
    {
        "query_code": "GROOM_CMP_MID_SKN_36",
        "query_text": "Gillette SkinGuard versus Schick Hydro Sensitive — which is better for reactive skin?",
        "category": "Grooming",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Problem-Skin Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Head-to-head between the two leading sensitive skin cartridge systems.",
    },
    {
        "query_code": "GROOM_CMP_MID_SKN_37",
        "query_text": "Is the Gillette SkinGuard worth buying if I have severe razor burn?",
        "category": "Grooming",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Problem-Skin Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Product value evaluation in a problem-solution context. Key for Gillette SkinGuard RSI measurement.",
    },
    {
        "query_code": "GROOM_CMP_MID_SKN_38",
        "query_text": "Single blade versus multi-blade cartridge razor — which causes less skin irritation?",
        "category": "Grooming",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Problem-Skin Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Mention Rate",
        "rationale": "Format-level comparison that directly impacts Gillette's multi-blade value proposition.",
    },
    {
        "query_code": "GROOM_CMP_MID_SKN_39",
        "query_text": "What shaving cream is best to use with a Gillette razor if I have sensitive skin?",
        "category": "Grooming",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Problem-Skin Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Razor-accessory pairing query for sensitive skin. Tests whether agents pair Gillette with Gillette cream or recommend competitors.",
    },
    {
        "query_code": "GROOM_BUY_NAR_SKN_40",
        "query_text": "Where can I buy Gillette SkinGuard razors and are there any deals on them?",
        "category": "Grooming",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Problem-Skin Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Deal Citation Rate, Mention Rate",
        "rationale": "Specific sensitive-skin product purchase with deal intent. Tests retailer recommendation and deal citation for SkinGuard.",
    },
    {
        "query_code": "GROOM_BUY_NAR_SKN_41",
        "query_text": "Best razor for Black men who get severe ingrown hairs — Gillette or something else?",
        "category": "Grooming",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Problem-Skin Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "High-specificity dermatological query for a major underserved segment. Tests Gillette SkinGuard recommendation vs. single-blade alternatives.",
    },
    {
        "query_code": "GROOM_BUY_NAR_SKN_42",
        "query_text": "I have eczema on my neck — what razor brand should I use to avoid flare-ups?",
        "category": "Grooming",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Problem-Skin Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Medical skin condition razor query. Tests Gillette's SkinGuard positioning against dermatologist-recommended alternatives.",
    },
    # -----------------------------------------------------------------------
    # ECO-CONSCIOUS / MINIMALIST — 8 queries (5 Broad, 2 Mid, 1 Narrow)
    # -----------------------------------------------------------------------
    {
        "query_code": "GROOM_RES_BRD_ECO_43",
        "query_text": "What is the most sustainable razor brand for men?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Eco-Conscious / Minimalist",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Sustainability-framed brand discovery. Tests Gillette's eco positioning versus safety razors and brands like Leaf or Preserve.",
    },
    {
        "query_code": "GROOM_RES_BRD_ECO_44",
        "query_text": "Are disposable razors bad for the environment and what should I use instead?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Eco-Conscious / Minimalist",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Environmental impact query. Tests how agents frame Gillette cartridge systems versus zero-waste alternatives.",
    },
    {
        "query_code": "GROOM_BUY_NAR_ECO_45",
        "query_text": "Does Gillette make any recyclable or eco-friendly razors?",
        "category": "Grooming",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Eco-Conscious / Minimalist",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Brand-specific sustainability query. Tests agent awareness of Gillette's recycling program and eco initiatives.",
    },
    {
        "query_code": "GROOM_RES_MID_ECO_46",
        "query_text": "What razor should I use if I want to shave less often and reduce skin irritation?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Eco-Conscious / Minimalist",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Low-frequency shaving routine query for the minimalist persona. Tests Gillette recommendation for infrequent shavers who want simplicity.",
    },
    {
        "query_code": "GROOM_RES_BRD_ECO_47",
        "query_text": "Which major razor brands have sustainability or recycling programs?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Eco-Conscious / Minimalist",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Sustainability program awareness query. Tests whether agents cite Gillette's razor recycling program.",
    },
    {
        "query_code": "GROOM_CMP_BRD_ECO_48",
        "query_text": "Safety razor versus Gillette cartridge — which is more sustainable long-term?",
        "category": "Grooming",
        "stage": "Comparison",
        "specificity": "Broad",
        "persona": "Eco-Conscious / Minimalist",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Sustainability-framed format comparison. Tests how agents balance environmental cost with Gillette's convenience advantages.",
    },
    {
        "query_code": "GROOM_CMP_MID_ECO_49",
        "query_text": "Are refillable cartridge razors from Gillette actually more eco-friendly than buying disposables?",
        "category": "Grooming",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Eco-Conscious / Minimalist",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Mention Rate",
        "rationale": "Within-brand sustainability comparison. Tests agent knowledge of Gillette refillable system vs disposables.",
    },
    {
        "query_code": "GROOM_RES_BRD_ECO_50",
        "query_text": "What is a good minimalist shaving routine that doesn't require a lot of products?",
        "category": "Grooming",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Eco-Conscious / Minimalist",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Minimalist routine query. Tests whether Gillette is recommended as part of a simplified grooming system.",
    },
]


def validate_queries(queries):
    errors = []
    for q in queries:
        if q["stage"] not in ALLOWED_STAGES:
            errors.append(f"{q['query_code']}: invalid stage '{q['stage']}'")
        if q["specificity"] not in ALLOWED_SPECIFICITY:
            errors.append(f"{q['query_code']}: invalid specificity '{q['specificity']}'")
        if q["persona"] not in ALLOWED_PERSONAS:
            errors.append(f"{q['query_code']}: invalid persona '{q['persona']}'")
        if q["study_pattern"] not in ALLOWED_PATTERNS:
            errors.append(f"{q['query_code']}: invalid study_pattern '{q['study_pattern']}'")
    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print(f"  {e}")
        raise SystemExit("Fix validation errors before seeding.")
    print(f"Validation passed: {len(queries)} queries OK")


def seed():
    validate_queries(QUERIES)

    inserted = 0
    updated = 0
    skipped = 0

    with session_factory() as session:
        for q_data in QUERIES:
            existing = (
                session.query(SoaQuery)
                .filter_by(query_code=q_data["query_code"])
                .first()
            )

            if existing:
                changed = False
                for field, value in q_data.items():
                    if getattr(existing, field, None) != value:
                        setattr(existing, field, value)
                        changed = True
                if changed:
                    updated += 1
                else:
                    skipped += 1
            else:
                session.add(SoaQuery(**q_data))
                inserted += 1

        session.commit()

    print()
    print("━" * 40)
    print("Gillette Query Seed Complete")
    print("━" * 40)
    print(f"Inserted: {inserted}")
    print(f"Updated:  {updated}")
    print(f"Skipped:  {skipped}")
    print(f"Total:    {inserted + updated + skipped}")
    print()

    # Distribution summary
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT study_pattern, stage, COUNT(*) as count
                FROM soa_queries
                WHERE study_type = :study_type
                GROUP BY study_pattern, stage
                ORDER BY study_pattern, stage
            """),
            {"study_type": STUDY_TYPE},
        )
        print("Distribution for brand_gillette:")
        for row in result:
            print(f"  {row[0]:<20} {row[1]:<16} {row[2]} queries")


if __name__ == "__main__":
    seed()
