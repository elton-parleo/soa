"""
Canonical allowed values for soa_queries constrained fields.

Single source of truth for:
  - SQLAlchemy CheckConstraints (soa_models.py)
  - Pydantic validators (schemas.py)
  - API constraints endpoint (routers/studies.py)
  - React frontend dropdowns
    (via GET /api/studies/constraints)

To add or remove a value:
  1. Update the relevant list here
  2. Write an Alembic migration to update the CHECK constraint in the database
  3. Sync copies to apps/api/soa_shared/ and apps/pipeline/soa_shared/
  4. Redeploy — the frontend updates automatically via the API
"""

QUERY_CATEGORIES = [
    'Skincare',
    'Makeup',
    'Fragrance',
    'Haircare',
    'Cross-Category',
    'Grooming',
    'Oral Care',
]

QUERY_STAGES = [
    'Research',
    'Comparison',
    'Ready to Buy',
]

QUERY_SPECIFICITIES = [
    'Broad',
    'Mid',
    'Narrow',
]

QUERY_PERSONAS = [
    'Casual / Gift Buyer',
    'Value-Conscious',
    'Beauty Enthusiast',
    'Problem-Skin Sufferer',
    'Eco-Conscious / Minimalist',
    'Oral Health Symptom Sufferer',
]

QUERY_STATUSES = [
    'Active',
    'Paused',
    'Retired',
]

QUERY_STUDY_PATTERNS = [
    'retailer',
    'brand_at_retail',
    'brand_vs_brand',
]

# Convenience dict used by the API endpoint and Pydantic validators
QUERY_CONSTRAINTS = {
    'category':      QUERY_CATEGORIES,
    'stage':         QUERY_STAGES,
    'specificity':   QUERY_SPECIFICITIES,
    'persona':       QUERY_PERSONAS,
    'status':        QUERY_STATUSES,
    'study_pattern': QUERY_STUDY_PATTERNS,
}
