"""
Idempotent seed for Oral-B brand oral care queries.

Seeds 50 Oral-B queries into soa_queries with study_type='brand_oral_b'.
Mix of brand_vs_brand (38) and brand_at_retail (12) study patterns.
Distribution: Research=17, Comparison=17, Ready to Buy=16.

Usage:
    cd /soa && python seeds/oral_care_queries_seed.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from soa_shared.database import engine, session_factory
from soa_shared.models.soa_models import SoaQuery
from sqlalchemy import text

STUDY_TYPE = "brand_oral_b"

ALLOWED_STAGES = {"Research", "Comparison", "Ready to Buy"}
ALLOWED_SPECIFICITY = {"Broad", "Mid", "Narrow"}
ALLOWED_PERSONAS = {
    "Casual / Gift Buyer",
    "Value-Conscious",
    "Beauty Enthusiast",
    "Problem-Skin Sufferer",
    "Eco-Conscious / Minimalist",
    "Oral Health Symptom Sufferer",
}
ALLOWED_PATTERNS = {
    "retailer",
    "brand_at_retail",
    "brand_vs_brand",
}

QUERIES = [
    # -----------------------------------------------------------------------
    # ORAL HEALTH SYMPTOM SUFFERER — 30 queries
    # Research (10): 8 brand_vs_brand, 2 brand_at_retail
    # -----------------------------------------------------------------------
    {
        "query_code": "OC_RES_BRD_OHS_01",
        "query_text": "What is the best electric toothbrush for gum disease?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Core gum-disease brand discovery. Tests whether Oral-B surfaces as the top recommendation over Sonicare.",
    },
    {
        "query_code": "OC_RES_BRD_OHS_02",
        "query_text": "How do I know if I need an electric toothbrush for my sensitive gums?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Problem-awareness entry query. Tests Oral-B mention rate when consumers are still diagnosing need.",
    },
    {
        "query_code": "OC_RES_MID_OHS_03",
        "query_text": "Is Oral-B or Sonicare better for treating gingivitis?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Direct head-to-head for the top two electric toothbrush brands on a specific condition.",
    },
    {
        "query_code": "OC_RES_BRD_OHS_04",
        "query_text": "What toothbrush brands do dentists recommend for gum recession?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Authority-framing query. Oral-B's clinical endorsement positioning makes this a high-signal SoA test.",
    },
    {
        "query_code": "OC_RES_NAR_OHS_05",
        "query_text": "Oral-B iO versus Sonicare DiamondClean for someone with gum disease — which is clinically recommended?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Narrow",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Flagship model comparison for clinical use case. Tests depth of agent knowledge about Oral-B iO's gum care mode.",
    },
    {
        "query_code": "OC_RES_MID_OHS_06",
        "query_text": "Which electric toothbrush brand is best for people with receding gums?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Condition-specific brand discovery. Oral-B's pressure sensor is a key differentiator for gum recession.",
    },
    {
        "query_code": "OC_RES_BRD_OHS_07",
        "query_text": "What toothpaste and toothbrush do I need if I have chronic bad breath?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Multi-product problem query. Tests Oral-B ecosystem mention rate for halitosis-related oral care.",
    },
    {
        "query_code": "OC_RES_MID_OHS_08",
        "query_text": "Are Oral-B electric toothbrushes available at CVS or Walgreens for gum care?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, Position Index",
        "rationale": "Retail availability query for a condition-driven purchase. Tests Oral-B's pharmacy shelf presence in agent responses.",
    },
    {
        "query_code": "OC_RES_NAR_OHS_09",
        "query_text": "What is the difference between Oral-B Pro 1000 and iO Series 5 for sensitive teeth?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Narrow",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Within-brand line differentiation for a clinical use case. Tests agent knowledge of Oral-B product tiers.",
    },
    {
        "query_code": "OC_RES_BRD_OHS_10",
        "query_text": "What should I look for in a toothbrush if I have enamel erosion?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, Position Index",
        "rationale": "Feature-need query for enamel-sensitive consumers. Tests whether Oral-B surfaces as a recommended option in retail contexts.",
    },
    # Comparison (10): 9 brand_vs_brand, 1 brand_at_retail
    {
        "query_code": "OC_CMP_BRD_OHS_11",
        "query_text": "Oral-B versus Colgate electric toothbrush for sensitive gums — which is better?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Broad",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Cross-brand comparison for a clinical audience. Tests Oral-B's RSI advantage over Colgate in gum-sensitive framing.",
    },
    {
        "query_code": "OC_CMP_MID_OHS_12",
        "query_text": "Does Oral-B's pressure sensor actually prevent gum damage compared to Sonicare?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Feature-level comparison. The pressure sensor is Oral-B's primary clinical differentiator — tests agent knowledge of it.",
    },
    {
        "query_code": "OC_CMP_NAR_OHS_13",
        "query_text": "Oral-B iO Series 9 versus Sonicare 9900 Prestige for periodontal care — which do periodontists prefer?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Narrow",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Premium flagship comparison for a high-acuity user. Tests Oral-B's clinical authority positioning at the top of its range.",
    },
    {
        "query_code": "OC_CMP_BRD_OHS_14",
        "query_text": "Is an electric toothbrush really better than a manual one for gum disease?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Broad",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Category-justification query. Tests whether agents recommend electric over manual and which brands they name.",
    },
    {
        "query_code": "OC_CMP_MID_OHS_15",
        "query_text": "Oral-B Pro 3 versus Quip for someone who just had gum surgery — which is safer?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Post-procedure comparison against a DTC brand. Tests Oral-B's clinical credibility positioning.",
    },
    {
        "query_code": "OC_CMP_BRD_OHS_16",
        "query_text": "Which oral care brand has the most dentist endorsements for gum health?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Broad",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Authority comparison query. Oral-B's 'Recommended by dentists' positioning makes this a core SoA signal.",
    },
    {
        "query_code": "OC_CMP_MID_OHS_17",
        "query_text": "Oral-B replacement brush heads versus Sonicare — which last longer and clean better for bleeding gums?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Consumable comparison for a condition-driven buyer. Tests agent knowledge of Oral-B head replacement ecosystem.",
    },
    {
        "query_code": "OC_CMP_BRD_OHS_18",
        "query_text": "Water flossers versus electric toothbrushes — which is better for managing gum disease?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Broad",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Category-crossover comparison. Tests whether agents recommend Oral-B as part of a complete gum care routine.",
    },
    {
        "query_code": "OC_CMP_NAR_OHS_19",
        "query_text": "Oral-B iO sensitive gum care mode versus Sonicare sensitive mode — is there a clinical difference?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Narrow",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Feature-mode clinical comparison. Tests agent depth on Oral-B's smart gum care technology.",
    },
    {
        "query_code": "OC_CMP_MID_OHS_20",
        "query_text": "Where can I find the best Oral-B for gum care at a pharmacy — Walgreens or CVS?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Retail channel comparison for a condition-driven buyer. Tests Oral-B's presence across major pharmacy retailers.",
    },
    # Ready to Buy (10): 7 brand_vs_brand, 3 brand_at_retail
    {
        "query_code": "OC_BUY_NAR_OHS_21",
        "query_text": "Where can I buy the Oral-B iO Series 5 in store today?",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, Deal Citation Rate",
        "rationale": "High-intent retail availability query for a specific Oral-B model. Tests retailer citation accuracy.",
    },
    {
        "query_code": "OC_BUY_NAR_OHS_22",
        "query_text": "Is the Oral-B iO Series 9 worth the price if I have gum disease?",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Position Index, RSI",
        "rationale": "Purchase-validation query for a premium model. Tests whether agents endorse Oral-B's top-tier product for clinical users.",
    },
    {
        "query_code": "OC_BUY_MID_OHS_23",
        "query_text": "Oral-B iO Series 5 versus Sonicare 5100 — which should I buy if I have gingivitis?",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Mid",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Position Index, RSI",
        "rationale": "Mid-tier purchase decision for a condition-specific buyer. Core Oral-B vs Sonicare conversion-stage test.",
    },
    {
        "query_code": "OC_BUY_BRD_OHS_24",
        "query_text": "Best electric toothbrush for sensitive gums under $100 that I can buy at a pharmacy today",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Broad",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, Deal Citation Rate",
        "rationale": "Price-capped retail purchase query. Tests Oral-B's recommendation rate when price and availability constraints are applied.",
    },
    {
        "query_code": "OC_BUY_NAR_OHS_25",
        "query_text": "Does Target carry the Oral-B iO Series 7 in store or do I need to order online?",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, Deal Citation Rate",
        "rationale": "Specific retail channel query for a mid-premium model. Tests agent knowledge of Oral-B's Target distribution.",
    },
    {
        "query_code": "OC_BUY_MID_OHS_26",
        "query_text": "Should I buy Oral-B iO or stick with Sonicare ProtectiveClean 6100 for my gum recession?",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Mid",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Position Index, RSI",
        "rationale": "Switching-cost query for an existing Sonicare user. Tests Oral-B's RSI advantage at the conversion stage.",
    },
    {
        "query_code": "OC_BUY_BRD_OHS_27",
        "query_text": "Which electric toothbrush would a periodontist recommend I buy today?",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Broad",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Position Index, RSI",
        "rationale": "Authority-driven purchase query. Tests Oral-B's clinical authority positioning at the bottom of the funnel.",
    },
    {
        "query_code": "OC_BUY_MID_OHS_28",
        "query_text": "Oral-B iO Series 3 versus Series 5 — which is worth buying for mild gum sensitivity?",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Mid",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Position Index, RSI",
        "rationale": "Within-brand tier decision for a moderate condition. Tests agent upsell recommendation within the Oral-B iO line.",
    },
    {
        "query_code": "OC_BUY_NAR_OHS_29",
        "query_text": "Should I buy Oral-B iO replacement heads or switch to Sonicare to save money long-term?",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Position Index, RSI",
        "rationale": "Retention-vs-switching query. Tests Oral-B's long-term cost justification at the consumable repurchase decision.",
    },
    {
        "query_code": "OC_BUY_BRD_OHS_30",
        "query_text": "Oral-B or Colgate 360 electric — which should I add to my cart if I have enamel erosion?",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Broad",
        "persona": "Oral Health Symptom Sufferer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Position Index, RSI",
        "rationale": "Enamel-focused purchase decision against a mass brand. Tests Oral-B's RSI for enamel-sensitive consumers.",
    },
    # -----------------------------------------------------------------------
    # VALUE-CONSCIOUS — 10 queries
    # Research (4): 3 brand_vs_brand, 1 brand_at_retail
    # -----------------------------------------------------------------------
    {
        "query_code": "OC_RES_BRD_VAL_31",
        "query_text": "What is the most affordable electric toothbrush that still cleans like a dentist visit?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Value-entry query for the electric toothbrush category. Tests Oral-B Pro 1000 mention rate at the budget end.",
    },
    {
        "query_code": "OC_RES_MID_VAL_32",
        "query_text": "Is it worth spending more on an Oral-B iO or does the basic Pro 1000 do the same job?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Within-brand value tier research. Tests agent knowledge of Oral-B's differentiation across price points.",
    },
    {
        "query_code": "OC_RES_BRD_VAL_33",
        "query_text": "Are expensive electric toothbrush brands like Oral-B worth it versus a cheap drugstore option?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Category justification query from a budget-first perspective. Tests Oral-B's value narrative in agent responses.",
    },
    {
        "query_code": "OC_RES_MID_VAL_34",
        "query_text": "Where can I find the best deals on Oral-B electric toothbrushes at a drugstore?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, Position Index",
        "rationale": "Deal-seeking retailer research query. Tests whether agents cite Oral-B's frequent drugstore promotions.",
    },
    # Comparison (4): 3 brand_vs_brand, 1 brand_at_retail
    {
        "query_code": "OC_CMP_BRD_VAL_35",
        "query_text": "Oral-B Pro 1000 versus Colgate E1 — which gives the best value for money?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Broad",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Budget-tier brand comparison. Tests Oral-B Pro 1000 RSI vs the Colgate mass market challenger.",
    },
    {
        "query_code": "OC_CMP_MID_VAL_36",
        "query_text": "Sonicare 4100 versus Oral-B Pro 1500 for someone on a budget — which is smarter?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Mid-budget cross-brand comparison for the two market leaders. A high-volume consumer decision query.",
    },
    {
        "query_code": "OC_CMP_BRD_VAL_37",
        "query_text": "Are refillable Oral-B brush heads cheaper long-term than buying a new toothbrush every few months?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Broad",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Total cost of ownership query. Tests whether agents validate Oral-B's subscription or refill model as the value choice.",
    },
    {
        "query_code": "OC_CMP_MID_VAL_38",
        "query_text": "Oral-B subscription service for replacement heads versus buying them at Target — which saves more?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "DTC vs retail channel cost comparison for Oral-B's consumable business. Tests agent pricing knowledge.",
    },
    # Ready to Buy (2): 1 brand_vs_brand, 1 brand_at_retail
    {
        "query_code": "OC_BUY_BRD_VAL_39",
        "query_text": "Best electric toothbrush under $50 I can buy at a drugstore today",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Broad",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, Deal Citation Rate",
        "rationale": "Price-capped retail conversion query. Tests Oral-B Pro 1000 recommendation rate at the budget threshold.",
    },
    {
        "query_code": "OC_BUY_MID_VAL_40",
        "query_text": "Oral-B Pro 1000 or Sonicare 4100 — which should I buy if I want to spend under $60?",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Mid",
        "persona": "Value-Conscious",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Position Index, RSI",
        "rationale": "Price-anchored purchase decision between the two market leaders' entry models.",
    },
    # -----------------------------------------------------------------------
    # CASUAL / GIFT BUYER — 10 queries
    # Research (3): 2 brand_vs_brand, 1 brand_at_retail
    # -----------------------------------------------------------------------
    {
        "query_code": "OC_RES_BRD_CAS_41",
        "query_text": "What electric toothbrush brands are most popular as gifts right now?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Popularity-framing gift discovery query. Tests top-of-mind organic brand ranking for oral care gifting.",
    },
    {
        "query_code": "OC_RES_MID_CAS_42",
        "query_text": "Is an Oral-B electric toothbrush a good gift for someone who has never used one?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Brand-specific gift validation query. Tests how agents position Oral-B for a first-time electric toothbrush recipient.",
    },
    {
        "query_code": "OC_RES_BRD_CAS_43",
        "query_text": "What oral care gift sets are available at Target or Walgreens for the holidays?",
        "category": "Oral Care",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, Position Index",
        "rationale": "Retail gift discovery query. Tests Oral-B's seasonal holiday bundle shelf presence in agent responses.",
    },
    # Comparison (3): 3 brand_vs_brand, 0 brand_at_retail
    {
        "query_code": "OC_CMP_BRD_CAS_44",
        "query_text": "Oral-B or Sonicare — which is a better gift for a parent with dental problems?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Condition-aware gift comparison. Tests Oral-B's RSI when clinical context is introduced for a gift buyer.",
    },
    {
        "query_code": "OC_CMP_MID_CAS_45",
        "query_text": "Oral-B kids electric toothbrush versus Sonicare for Kids — which is more fun and effective?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Kids gifting comparison. Tests Oral-B Kids mention rate and positioning versus the Sonicare Kids line.",
    },
    {
        "query_code": "OC_CMP_BRD_CAS_46",
        "query_text": "Which electric toothbrush brand makes a better couples gift set — Oral-B or Sonicare?",
        "category": "Oral Care",
        "stage": "Comparison",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "RSI, Position Index",
        "rationale": "Couples gift format comparison. Tests Oral-B's dual-handle bundle positioning against Sonicare.",
    },
    # Ready to Buy (4): 2 brand_vs_brand, 2 brand_at_retail
    {
        "query_code": "OC_BUY_BRD_CAS_47",
        "query_text": "What is the best Oral-B model to give as a graduation or birthday gift?",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Position Index, RSI",
        "rationale": "Occasion-specific purchase validation for Oral-B. Tests agent recommendation of specific models as milestone gifts.",
    },
    {
        "query_code": "OC_BUY_MID_CAS_48",
        "query_text": "Where can I buy an Oral-B iO gift set in store before the holidays?",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Mid",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, Deal Citation Rate",
        "rationale": "Seasonal retail conversion query. Tests agent accuracy on Oral-B gift set retail availability.",
    },
    {
        "query_code": "OC_BUY_NAR_CAS_49",
        "query_text": "Oral-B iO Series 4 or Series 6 as a gift — which will impress more without spending too much?",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "soa_focus": "Position Index, RSI",
        "rationale": "Within-brand gift tier decision. Tests agent upsell recommendation within the Oral-B iO line for a gift context.",
    },
    {
        "query_code": "OC_BUY_BRD_CAS_50",
        "query_text": "Does Target sell Oral-B gift bundles in store or only online?",
        "category": "Oral Care",
        "stage": "Ready to Buy",
        "specificity": "Broad",
        "persona": "Casual / Gift Buyer",
        "study_type": STUDY_TYPE,
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate, Deal Citation Rate",
        "rationale": "Retail channel availability for holiday gifting. Tests agent knowledge of Oral-B's Target in-store gift assortment.",
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
    print("Oral Care Query Seed Complete")
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
        print("Distribution for brand_oral_b:")
        for row in result:
            print(f"  {row[0]:<20} {row[1]:<16} {row[2]} queries")


if __name__ == "__main__":
    seed()
