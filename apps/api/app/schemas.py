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

# ─── Metrics ──────────────────────────

class EntityMetrics(BaseModel):
    """
    Metric values for one entity in one slice.
    All values normalized 0-100. None when data unavailable.
    """
    mention_rate:       Optional[float] = None
    som:                Optional[float] = None
    rsi:                Optional[float] = None
    position_index:     Optional[float] = None
    pdi:                Optional[float] = None
    deal_citation_rate: Optional[float] = None
    total_runs:         Optional[int]   = None
    total_mentions:     Optional[int]   = None

class CycleEntityInfo(BaseModel):
    """One entity in a cycle's comparison set."""
    code:        str
    name:        str
    slug:        str
    role:        str
    entity_type: str
    category:    Optional[str] = None

class CycleEntitiesResponse(BaseModel):
    cycle_code: str
    entities:   List[CycleEntityInfo]

class MetricsSlice(BaseModel):
    """All entity metrics for one slice. Key is comparison_code (M001 etc.)"""
    entities: dict  # Dict[comparison_code, EntityMetrics]

class CycleMetricsResponse(BaseModel):
    cycle_code: str
    entities:   List[CycleEntityInfo]
    slices:     dict
    # {
    #   "overall": { "M001": {...}, "M002": {...} },
    #   "by_stage": { "Research": { "M001": {...} } },
    #   "by_platform": { ... },
    #   "by_category": { ... },
    # }


# ─── Normalization helpers ─────────────
# Module-level functions for use in routers.

def normalize_metric(
    value,
    min_val: float = 0.0,
    max_val: float = 1.0,
) -> Optional[float]:
    """
    Normalize a raw DB value to 0-100.
    Input range [min_val, max_val] → output [0, 100].
    Returns None if value is None.
    """
    if value is None:
        return None
    try:
        v = float(value)
        scaled = ((v - min_val) / (max_val - min_val)) * 100
        return round(max(0.0, min(100.0, scaled)), 1)
    except (TypeError, ZeroDivisionError):
        return None


def normalize_rsi(value) -> Optional[float]:
    """
    RSI range is 0 to 3 (Option B denominator: divides by total mentions).
    Normalize to 0-100. NULL means entity had zero mentions → return None.

    NOTE: No longer used in the primary metrics path (as of the raw-RSI
    change). build_entity_metrics() now returns the raw DB value directly
    (range -1.0 to +3.0). The frontend handles display scaling and
    relative min-max normalization for chart layout.
    Kept here for ad-hoc / legacy use.
    """
    if value is None:
        return None
    return normalize_metric(value, min_val=0.0, max_val=3.0)
