"""
Idempotent seed for Pampers Baby Care queries (brand_pampers study).

This is the first non-beauty vertical in the SoA platform.

QUERIES is embedded from the reviewed workbook at:
  apps/pipeline/seeds/data/pampers_query_set.xlsx  (Sheet: "Queries", header row 1)
Only rows where KEEP == 'y' (case-insensitive) are included.

To regenerate QUERIES from an updated workbook, run:
  python seeds/pampers_queries_seed.py --regenerate

Usage (seed):
  cd /soa && python seeds/pampers_queries_seed.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from soa_shared.constants import (
    QUERY_CATEGORIES,
    QUERY_STAGES,
    QUERY_SPECIFICITIES,
    QUERY_PERSONAS,
    QUERY_STUDY_PATTERNS,
    QUERY_SUBSCRIPTION_STATES,
    QUERY_EXPECTED_INCENTIVES,
)
from soa_shared.database import engine, session_factory
from soa_shared.models.soa_models import SoaQuery
from sqlalchemy import text

STUDY_TYPE = "brand_pampers"

XLSX_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data", "pampers_query_set.xlsx",
)

# ---------------------------------------------------------------------------
# QUERIES — embedded from pampers_query_set.xlsx (KEEP='y' rows only).
# Regenerate with: python seeds/pampers_queries_seed.py --regenerate
# ---------------------------------------------------------------------------
QUERIES = [
    {
        "query_code": "BC_AWA_BRD_NFP_01",
        "query_text": "my newborn keeps soaking through his diaper every night, what am I doing wrong?",
        "category": "Baby Care",
        "stage": "Awareness",
        "specificity": "Broad",
        "persona": "New / First-Time Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, SoA%",
        "rationale": "Problem-recognition entry; tests whether Pampers surfaces unprompted before any brand or price intent.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_AWA_BRD_NFP_02",
        "query_text": "how do I figure out what diaper size my baby actually needs?",
        "category": "Baby Care",
        "stage": "Awareness",
        "specificity": "Broad",
        "persona": "New / First-Time Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate",
        "rationale": "Sizing-help query; educational intent, no price expected — calibration for the Low flag.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_AWA_BRD_NFP_03",
        "query_text": "first-time dad here — what diapers do I even need for a newborn?",
        "category": "Baby Care",
        "stage": "Awareness",
        "specificity": "Broad",
        "persona": "New / First-Time Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Zero-knowledge stage; tests the agent's default brand recommendation.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_AWA_BRD_SSP_01",
        "query_text": "my baby gets a red rash from her diapers, is that normal?",
        "category": "Baby Care",
        "stage": "Awareness",
        "specificity": "Broad",
        "persona": "Sensitive-Skin Baby Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, SoA%",
        "rationale": "Symptom-driven; whether Pampers (Sensitive/Pure) surfaces as a solution unprompted.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_AWA_BRD_NFP_04",
        "query_text": "how many diapers a day does a newborn go through?",
        "category": "Baby Care",
        "stage": "Awareness",
        "specificity": "Broad",
        "persona": "New / First-Time Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate",
        "rationale": "Pure info; price here would be out of place — a clean expectation-Low control.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_AWA_BRD_ECP_01",
        "query_text": "are disposable diapers bad for the environment?",
        "category": "Baby Care",
        "stage": "Awareness",
        "specificity": "Broad",
        "persona": "Eco-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, SoA%",
        "rationale": "Values-driven entry; whether eco framing pulls in Pampers Pure vs Honest/Coterie.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_AWA_BRD_NFP_05",
        "query_text": "what's the difference between newborn and size 1 diapers?",
        "category": "Baby Care",
        "stage": "Awareness",
        "specificity": "Broad",
        "persona": "New / First-Time Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate",
        "rationale": "Educational; tests brand mention inside a purely informational answer.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_AWA_BRD_SSP_02",
        "query_text": "diaper blowouts every morning — how do people deal with this?",
        "category": "Baby Care",
        "stage": "Awareness",
        "specificity": "Broad",
        "persona": "Sensitive-Skin Baby Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Fit/absorbency problem-solving; no price expected.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RES_BRD_SSP_03",
        "query_text": "what are the gentlest diapers for a baby with really sensitive skin?",
        "category": "Baby Care",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Sensitive-Skin Baby Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Core attribute discovery; Pampers Pure/Sensitive vs Huggies Special Delivery/Honest.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RES_MID_SSP_04",
        "query_text": "are 'sensitive' diapers actually different or just marketing?",
        "category": "Baby Care",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Sensitive-Skin Baby Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, SoA%",
        "rationale": "Skeptical research; tests whether Pampers Pure/Sensitive is named and defended.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RES_BRD_ECP_02",
        "query_text": "what are the most eco-friendly disposable diapers?",
        "category": "Baby Care",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Eco-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, SoA%",
        "rationale": "Eco share-of-voice; where Pampers Pure competes with Honest/Coterie/Bambo.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RES_MID_ECP_03",
        "query_text": "which diaper brands are actually free of fragrances and lotions?",
        "category": "Baby Care",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Eco-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Ingredient-driven; attribute accuracy for Pampers Pure.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RES_BRD_NFP_06",
        "query_text": "what are the best diaper brands for a new baby?",
        "category": "Baby Care",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "New / First-Time Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, SoA%, RSI",
        "rationale": "Canonical top-of-research brand discovery; Pampers rank vs Huggies.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RES_MID_NFP_07",
        "query_text": "how do I choose between all the diaper brands out there?",
        "category": "Baby Care",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "New / First-Time Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Decision-framework query; which brands the agent anchors on.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RES_MID_VCP_01",
        "query_text": "are name-brand diapers worth it or should I just buy store brand?",
        "category": "Baby Care",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Mixed",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, Net-Price presence",
        "rationale": "First value-vs-cost query; may invite price/value — expectation starts rising.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RES_MID_VCP_02",
        "query_text": "how much should I actually expect to spend on diapers each month?",
        "category": "Baby Care",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Mixed",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence, Deal Citation",
        "rationale": "Budget framing; does the agent volunteer price / cost-per-diaper.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RES_MID_SSP_05",
        "query_text": "best overnight diapers for a heavy wetter?",
        "category": "Baby Care",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Sensitive-Skin Baby Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Use-case attribute; Pampers Baby-Dry/Overnights vs Huggies Overnites.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RES_BRD_ECP_04",
        "query_text": "are there diapers that are better for babies with allergies?",
        "category": "Baby Care",
        "stage": "Research",
        "specificity": "Broad",
        "persona": "Eco-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, SoA%",
        "rationale": "Health-attribute overlapping eco/sensitive; tests Pampers Pure surfacing.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RES_MID_NFP_08",
        "query_text": "what should I look for when comparing diaper brands?",
        "category": "Baby Care",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "New / First-Time Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Criteria query; whether price/value is even named as a criterion by the agent.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RES_MID_VCP_03",
        "query_text": "is it cheaper to use cloth or disposable diapers in the long run?",
        "category": "Baby Care",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Mixed",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence",
        "rationale": "Cost-framing research; expectation of cost math rising.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_SSP_06",
        "query_text": "Pampers Swaddlers vs Pampers Pure for sensitive skin — is the upgrade worth it?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Sensitive-Skin Baby Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Mixed",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "RSI, Net-Price presence",
        "rationale": "Sub-line comparison with an implicit value question ('worth it').",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_VCP_04",
        "query_text": "are Pampers or Huggies a better deal for the money?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence, Deal Citation",
        "rationale": "Explicit value head-to-head — the core money-zone query.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_SSP_07",
        "query_text": "Pampers vs Huggies for a baby with sensitive skin and frequent rashes?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Sensitive-Skin Baby Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Mixed",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "RSI, Mention Rate",
        "rationale": "Attribute head-to-head; does price sneak in or stay attribute-only.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_VCP_05",
        "query_text": "which diaper brand gives you the most diapers for your money?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence",
        "rationale": "Value-per-unit; clearly expects cost-per-diaper math.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_NFP_09",
        "query_text": "Pampers Swaddlers vs Huggies Little Snugglers — which do parents prefer?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "New / First-Time Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Mixed",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "RSI, SoA%",
        "rationale": "Classic preference head-to-head; value optional.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_ECP_05",
        "query_text": "Pampers Pure vs Honest Company diapers — which is better and cheaper?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Eco-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence, RSI",
        "rationale": "Eco head-to-head with an explicit 'cheaper' — price expected.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_SRP_01",
        "query_text": "is it worth subscribing to diapers or just buying them as I go?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Subscription / Replenishment Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": "not_subscribed",
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Subscription-offer presence, Net-Price presence",
        "rationale": "Subscription-value question; expects S&S / auto-ship economics.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_VCP_06",
        "query_text": "are the big Costco boxes of diapers actually cheaper than Pampers on Amazon?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence, Deal Citation",
        "rationale": "Cross-retailer value; expects a real price comparison.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_SSP_08",
        "query_text": "Pampers Sensitive vs Huggies Special Delivery for eczema-prone skin?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Sensitive-Skin Baby Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Mixed",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "RSI, Mention Rate",
        "rationale": "Premium-sensitive head-to-head; attribute-led, value secondary.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_NFP_10",
        "query_text": "what's the difference between Pampers Swaddlers, Baby-Dry, and Cruisers?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "New / First-Time Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Mention Rate, RSI",
        "rationale": "Within-brand line education; expectation-Low even at Comparison — a calibration point.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_VCP_07",
        "query_text": "generic vs Pampers diapers — is the price difference worth the quality?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence, RSI",
        "rationale": "Value-vs-quality; explicitly invokes the price difference.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_ECP_06",
        "query_text": "which is the better value, Pampers Pure or Coterie?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Eco-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence",
        "rationale": "Premium-eco value comparison; expects price context.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_SRP_02",
        "query_text": "is Amazon Subscribe & Save or Target's diaper deals a better way to save on Pampers?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Subscription / Replenishment Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": "not_subscribed",
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Subscription-offer presence, Deal Citation, Member-price presence",
        "rationale": "Program-vs-program value; directly targets incentive surfacing.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_SSP_09",
        "query_text": "do more expensive diapers actually prevent diaper rash better?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Sensitive-Skin Baby Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Mixed",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "RSI, Net-Price presence",
        "rationale": "Price-quality attribute; genuinely mixed expectation.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_VCP_08",
        "query_text": "how do I compare the real cost per diaper between brands?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence",
        "rationale": "Cost-per-unit method; strongly expects price math.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_NFP_11",
        "query_text": "everyone recommends Pampers or Huggies — how do I actually pick?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "New / First-Time Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "Mixed",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "RSI, SoA%",
        "rationale": "Tie-breaker; whether value is offered as the deciding factor.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_ECP_07",
        "query_text": "are eco-friendly diapers like Pampers Pure a lot more expensive than regular ones?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Eco-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_vs_brand",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence",
        "rationale": "Eco price-premium; expects a price delta.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_CMP_MID_SRP_03",
        "query_text": "if I set up auto-delivery for Pampers, do I actually save money?",
        "category": "Baby Care",
        "stage": "Comparison",
        "specificity": "Mid",
        "persona": "Subscription / Replenishment Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": "not_subscribed",
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Subscription-offer presence, Net-Price presence",
        "rationale": "Subscription payoff; expects the S&S discount surfaced.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_VCP_09",
        "query_text": "cheapest place to buy Pampers Swaddlers size 3 right now?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence, Deal Citation",
        "rationale": "Canonical price-seeking; expects retailer + price.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_SRP_04",
        "query_text": "is it cheaper to subscribe to Pampers on Amazon or just buy them at Target?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Subscription / Replenishment Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": "not_subscribed",
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Subscription-offer presence, Net-Price presence, Member-price presence",
        "rationale": "Cross-retailer subscription value — the exact gap from the case study.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_VCP_10",
        "query_text": "any good deals or coupons on Pampers Swaddlers this week?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Deal Citation, Net-Price presence",
        "rationale": "Coupon-seeking; directly tests deal_cited.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_SRP_05",
        "query_text": "how much do I save with Subscribe & Save on Pampers Pure?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Subscription / Replenishment Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": "subscribed",
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Subscription-offer presence, Net-Price presence",
        "rationale": "Quantified S&S expectation.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_VCP_11",
        "query_text": "where can I get the best price on a big box of Pampers size 4?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence, Deal Citation",
        "rationale": "Bulk price-seeking; expects retailer + per-unit.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_SRP_06",
        "query_text": "does Target Circle or Walmart give a better deal on Pampers?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Subscription / Replenishment Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Member-price presence, Deal Citation",
        "rationale": "Loyalty-program value — tests member-price surfacing (the layer agents miss).",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_VCP_12",
        "query_text": "is there a discount if I buy Pampers in bulk?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Deal Citation, Net-Price presence",
        "rationale": "Basket/bulk discount; tests basket-deal surfacing (the Target $30-GC type).",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_SSP_10",
        "query_text": "cheapest place to buy Pampers Sensitive size 2?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Sensitive-Skin Baby Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence",
        "rationale": "Sensitive-SKU price-seeking; attribute + price combined.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_VCP_13",
        "query_text": "what's the current price of Pampers Swaddlers 164 count at Walmart?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence",
        "rationale": "Exact-SKU price lookup — the Walmart control case (should surface correctly).",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_SRP_07",
        "query_text": "set me up with the cheapest recurring diaper delivery for Pampers",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Subscription / Replenishment Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": "not_subscribed",
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Subscription-offer presence, Net-Price presence",
        "rationale": "Action-oriented subscription; expects auto-ship pricing.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_VCP_14",
        "query_text": "are Pampers cheaper on Amazon or at Target today?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence",
        "rationale": "Cross-retailer spot price; expects a live comparison.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_ECP_08",
        "query_text": "best price on Pampers Pure size 1?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Eco-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence, Deal Citation",
        "rationale": "Eco-SKU price-seeking.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_VCP_15",
        "query_text": "how much is a month's supply of Pampers for a size 3 baby?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Net-Price presence",
        "rationale": "Cost-to-replenish; expects total / monthly math.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_SRP_08",
        "query_text": "if I subscribe to Pampers, can I still use coupons on top?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Subscription / Replenishment Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": "subscribed",
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Deal Citation, Subscription-offer presence",
        "rationale": "Stacking question; tests whether the agent understands combined incentives.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_VCP_16",
        "query_text": "which store has Pampers on sale right now?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Deal Citation",
        "rationale": "Promo-seeking; tests real-time deal surfacing.",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_SRP_09",
        "query_text": "best Prime Day deals on Pampers diapers?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Subscription / Replenishment Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Deal Citation, Net-Price presence",
        "rationale": "Tent-pole event query (the small event block Bryan flagged).",
        "organization_id": 1,
    },
    {
        "query_code": "BC_RTB_NAR_VCP_17",
        "query_text": "any Black Friday deals coming up on Pampers?",
        "category": "Baby Care",
        "stage": "Ready to Buy",
        "specificity": "Narrow",
        "persona": "Value-Conscious Parent",
        "study_type": "brand_pampers",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "subscription_state": None,
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name": None,
        "soa_focus": "Deal Citation",
        "rationale": "Second tent-pole query; event-window promo expectation.",
        "organization_id": 1,
    },
]


# ---------------------------------------------------------------------------
# Xlsx loader — used by --regenerate and (optionally) at runtime if QUERIES is
# empty and the workbook is present.
# ---------------------------------------------------------------------------

def _load_from_xlsx(path: str) -> list[dict]:
    """
    Parse the pampers workbook and return a list of query dicts for KEEP='y' rows.
    Validates every constrained field before returning; fails loudly on any error.
    """
    try:
        import openpyxl
    except ImportError:
        raise SystemExit("openpyxl is required to load the workbook: pip install openpyxl")

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Queries"]

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise SystemExit(f"Workbook sheet 'Queries' in {path} is empty.")

    header = [str(c).strip() if c is not None else "" for c in rows[0]]

    def col(row, name):
        idx = header.index(name)
        v = row[idx]
        return str(v).strip() if v is not None else ""

    queries = []
    errors = []

    for i, row in enumerate(rows[1:], start=2):
        keep = col(row, "KEEP")
        if keep.lower() != "y":
            continue

        query_code = col(row, "query_code")
        if not query_code:
            errors.append(f"Row {i}: missing query_code")
            continue

        category = col(row, "category")
        if category != "Baby Care":
            errors.append(f"{query_code}: category must be 'Baby Care', got '{category}'")

        stage = col(row, "stage")
        if stage not in QUERY_STAGES:
            errors.append(f"{query_code}: invalid stage '{stage}'")

        specificity = col(row, "specificity")
        if specificity not in QUERY_SPECIFICITIES:
            errors.append(f"{query_code}: invalid specificity '{specificity}'")

        persona = col(row, "persona")
        if persona not in QUERY_PERSONAS:
            errors.append(f"{query_code}: invalid persona '{persona}'")

        study_pattern = col(row, "study_pattern")
        if study_pattern not in QUERY_STUDY_PATTERNS:
            errors.append(f"{query_code}: invalid study_pattern '{study_pattern}'")

        raw_sub = col(row, "subscription_state")
        subscription_state = raw_sub if raw_sub else None
        if subscription_state is not None and subscription_state not in QUERY_SUBSCRIPTION_STATES:
            errors.append(f"{query_code}: invalid subscription_state '{subscription_state}'")

        expected_incentive = col(row, "expected_incentive")
        if expected_incentive not in QUERY_EXPECTED_INCENTIVES:
            errors.append(f"{query_code}: invalid expected_incentive '{expected_incentive}'")

        queries.append({
            "query_code":          query_code,
            "query_text":          col(row, "query_text"),
            "category":            "Baby Care",
            "stage":               stage,
            "specificity":         specificity,
            "persona":             persona,
            "study_type":          STUDY_TYPE,
            "study_pattern":       study_pattern,
            "status":              "Active",
            "subscription_state":  subscription_state,
            "expected_incentive":  expected_incentive,
            "membership_program":  None,
            "tier_name":           None,
            "soa_focus":           col(row, "soa_focus") or None,
            "rationale":           col(row, "rationale") or None,
            "organization_id":     1,
        })

    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print(f"  {e}")
        raise SystemExit("Fix validation errors before seeding.")

    return queries


def _resolve_queries() -> list[dict]:
    """
    Return the embedded QUERIES list, or fall back to reading the xlsx if
    QUERIES is empty and the workbook is present.
    """
    if QUERIES:
        return QUERIES
    if os.path.exists(XLSX_PATH):
        print(f"QUERIES list is empty — loading from workbook at {XLSX_PATH}")
        return _load_from_xlsx(XLSX_PATH)
    return []


# ---------------------------------------------------------------------------
# Validation (runs against the embedded/loaded QUERIES list)
# ---------------------------------------------------------------------------

def validate_queries(queries: list[dict]) -> None:
    errors = []
    for q in queries:
        qc = q.get("query_code", "<unknown>")
        if q.get("category") != "Baby Care":
            errors.append(f"{qc}: category must be 'Baby Care'")
        if q.get("stage") not in QUERY_STAGES:
            errors.append(f"{qc}: invalid stage '{q.get('stage')}'")
        if q.get("specificity") not in QUERY_SPECIFICITIES:
            errors.append(f"{qc}: invalid specificity '{q.get('specificity')}'")
        if q.get("persona") not in QUERY_PERSONAS:
            errors.append(f"{qc}: invalid persona '{q.get('persona')}'")
        if q.get("study_pattern") not in QUERY_STUDY_PATTERNS:
            errors.append(f"{qc}: invalid study_pattern '{q.get('study_pattern')}'")
        sub = q.get("subscription_state")
        if sub is not None and sub not in QUERY_SUBSCRIPTION_STATES:
            errors.append(f"{qc}: invalid subscription_state '{sub}'")
        ei = q.get("expected_incentive")
        if ei not in QUERY_EXPECTED_INCENTIVES:
            errors.append(f"{qc}: invalid expected_incentive '{ei}'")

    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print(f"  {e}")
        raise SystemExit("Fix validation errors before seeding.")
    print(f"Validation passed: {len(queries)} queries OK")


# ---------------------------------------------------------------------------
# Seed (idempotent upsert keyed on query_code)
# ---------------------------------------------------------------------------

def seed(queries: list[dict] | None = None) -> None:
    if queries is None:
        queries = _resolve_queries()

    if not queries:
        print("No queries to seed. Place the workbook at:")
        print(f"  {XLSX_PATH}")
        print("Then re-run, or run with --regenerate to embed the rows.")
        return

    validate_queries(queries)

    inserted = 0
    updated = 0
    skipped = 0

    with session_factory() as session:
        for q_data in queries:
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
    print("━" * 44)
    print("Pampers Baby Care Query Seed Complete")
    print("━" * 44)
    print(f"Inserted: {inserted}")
    print(f"Updated:  {updated}")
    print(f"Skipped:  {skipped}")
    print(f"Total:    {inserted + updated + skipped}")
    print()

    # Distribution summary
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT stage, expected_incentive, COUNT(*) AS count
                FROM soa_queries
                WHERE study_type = :study_type
                GROUP BY stage, expected_incentive
                ORDER BY stage, expected_incentive
            """),
            {"study_type": STUDY_TYPE},
        )
        print(f"Distribution for {STUDY_TYPE}:")
        for row in result:
            ei = row[1] or "None"
            print(f"  {row[0]:<16} expected_incentive={ei:<6}  {row[2]} queries")


# ---------------------------------------------------------------------------
# --regenerate: rewrite this file's QUERIES list from the workbook in place
# ---------------------------------------------------------------------------

def _regenerate() -> None:
    if not os.path.exists(XLSX_PATH):
        raise SystemExit(f"Workbook not found at {XLSX_PATH}")

    rows = _load_from_xlsx(XLSX_PATH)
    print(f"Loaded {len(rows)} KEEP='y' rows from workbook.")

    # Render QUERIES as a Python literal
    lines = ["QUERIES = ["]
    for q in rows:
        lines.append("    {")
        for k, v in q.items():
            if v is None:
                lines.append(f'        "{k}": None,')
            elif isinstance(v, (int, float, bool)):
                lines.append(f'        "{k}": {v},')
            else:
                escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'        "{k}": "{escaped}",')
        lines.append("    },")
    lines.append("]")
    new_block = "\n".join(lines)

    this_file = os.path.abspath(__file__)
    with open(this_file) as f:
        src = f.read()

    # Replace between the sentinel comments
    start_marker = "QUERIES = ["
    end_marker = "]"
    start_idx = src.index(start_marker)
    # find the matching closing bracket
    bracket_depth = 0
    end_idx = start_idx
    for i, ch in enumerate(src[start_idx:], start=start_idx):
        if ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth -= 1
            if bracket_depth == 0:
                end_idx = i
                break

    new_src = src[:start_idx] + new_block + src[end_idx + 1:]
    with open(this_file, "w") as f:
        f.write(new_src)

    print(f"Rewrote QUERIES in {this_file} with {len(rows)} rows.")
    print("Review the diff, then commit.")


if __name__ == "__main__":
    if "--regenerate" in sys.argv:
        _regenerate()
    else:
        seed()
