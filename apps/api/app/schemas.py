from pydantic import BaseModel
from typing import List, Optional

# ─── Studies ─────────────────────────

class StudyResponse(BaseModel):
    id: str
    name: str
    category: str
    patterns: List[str]
    queryCount: int
    lastRun: Optional[str] = None

class StudyQueryBreakdown(BaseModel):
    study_type: str
    total: int
    by_pattern: dict

# ─── Entities ────────────────────────

class EntityResponse(BaseModel):
    id: int
    name: str
    type: str
    category: str
    slug: str

class CreateEntityRequest(BaseModel):
    name: str
    type: str
    category: str
    website_url: Optional[str] = None
    aliases: Optional[List[str]] = None

# ─── Cycles ──────────────────────────

class ComparisonEntityInput(BaseModel):
    entity_id: int
    comparison_code: str
    role: str

class CreateCycleRequest(BaseModel):
    cycle_code: str
    study_type: str
    platforms: List[str]
    runs_per_query: int
    notes: Optional[str] = None
    run_mode: str = "immediate"
    comparison_set: List[ComparisonEntityInput]

class CycleStatusResponse(BaseModel):
    cycle_code: str
    status: str
    study_type: str
    study_pattern: str
    total_runs_planned: int
    completed_runs: int
    created_at: Optional[str] = None
    platforms: Optional[List[str]] = None
    runs_per_query: Optional[int] = None

class CycleCheckResponse(BaseModel):
    available: bool
    cycle_code: str

# ─── Type mappings ────────────────────

ENTITY_TYPE_DISPLAY = {
    "retailer":  "Retailer",
    "brand":     "Brand",
    "cpg":       "CPG",
    "service":   "Service",
    "aggregate": "Aggregate",
}

ENTITY_TYPE_INTERNAL = {
    v: k for k, v in ENTITY_TYPE_DISPLAY.items()
}

STUDY_TYPE_NAMES = {
    "retailer_sephora":          "Sephora Retailer Study",
    "brand_oral_b":              "Oral-B Brand Study",
    "brand_oral_b_100":          "Oral-B Extended Study",
    "brand_oral_b_unbranded":    "Oral-B Unbranded Study",
    "brand_oral_b_neutral":      "Oral-B Neutral Study",
    "brand_oral_b_etb_neutral":  "Oral-B ETB Neutral Study",
    "brand_gillette":            "Gillette Brand Study",
    "brand_gillette_100":        "Gillette 100 Study",
    "brand_gillette_unbranded":  "Gillette Unbranded Study",
}

PATTERN_DISPLAY = {
    "retailer":        "Retailer",
    "brand_at_retail": "Brand at Retail",
    "brand_vs_brand":  "Brand vs Brand",
    "mixed":           "Mixed",
}
