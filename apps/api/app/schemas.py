from pydantic import BaseModel, field_validator, model_validator
from typing import List, Optional
from soa_shared.constants import QUERY_CONSTRAINTS

# ─── Shared constraint validator ──────────────────────────────────────────────

_CONSTRAINED_FIELDS = ('category', 'stage', 'specificity', 'persona', 'status', 'study_pattern')


def _check_constraint(field_name: str, v):
    """
    Raise ValueError if v is a non-None value not in QUERY_CONSTRAINTS[field_name].
    Used by field_validator in QueryCreate and QueryUpdate.
    """
    if v is None:
        return v
    allowed = QUERY_CONSTRAINTS.get(field_name, [])
    if allowed and v not in allowed:
        raise ValueError(
            f"'{v}' is not a valid value for {field_name}."
            f" Allowed values: {allowed}"
        )
    return v

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

class EntityUpdateRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    category: Optional[str] = None
    website_url: Optional[str] = None
    aliases: Optional[List[str]] = None

# ─── Cycles ──────────────────────────

class ComparisonEntityInput(BaseModel):
    entity_id: int
    comparison_code: str
    role: str

class CreateCycleRequest(BaseModel):
    cycle_code: str
    # 'query' (default) is the existing LLM query/coding pipeline, unchanged.
    # 'truecost' sweeps the selected entities' Measured SKUs through the Deal
    # Engine instead — study_type/platforms/runs_per_query are not required
    # for it (see the conditional validation in create_cycle()).
    cycle_mode: str = "query"
    study_type: Optional[str] = None
    platforms: Optional[List[str]] = None
    runs_per_query: Optional[int] = None
    notes: Optional[str] = None
    run_mode: str = "immediate"
    comparison_set: List[ComparisonEntityInput]
    # Tier names to sweep for cycle_mode='truecost'. A null entry means the
    # non-member baseline. Ignored for cycle_mode='query'.
    truecost_tiers: Optional[List[Optional[str]]] = None

    @field_validator("cycle_mode")
    @classmethod
    def validate_cycle_mode(cls, v):
        if v not in ("query", "truecost"):
            raise ValueError("cycle_mode must be 'query' or 'truecost'")
        return v

    @model_validator(mode="after")
    def check_mode_requirements(self):
        if self.cycle_mode == "query":
            if not self.study_type:
                raise ValueError("study_type is required for cycle_mode='query'")
            if not self.platforms:
                raise ValueError("platforms is required for cycle_mode='query'")
            if not self.runs_per_query:
                raise ValueError("runs_per_query is required for cycle_mode='query'")
        else:  # truecost
            if not self.comparison_set:
                raise ValueError("at least one entity is required for cycle_mode='truecost'")
            if not self.truecost_tiers:
                raise ValueError(
                    "at least one tier is required for cycle_mode='truecost' "
                    "(include null for the non-member baseline)"
                )
        return self

class CycleStatusResponse(BaseModel):
    cycle_code: str
    status: str
    cycle_mode: str = "query"
    study_type: Optional[str] = None
    study_pattern: Optional[str] = None
    total_runs_planned: Optional[int] = None
    completed_runs: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    platforms: Optional[List[str]] = None
    runs_per_query: Optional[int] = None
    truecost_tiers: Optional[List[Optional[str]]] = None
    id: Optional[int] = None  # soa_cycles.id — needed by scope-SKU endpoints, which key on it

class CycleCheckResponse(BaseModel):
    available: bool
    cycle_code: str

class QueryCreate(BaseModel):
    """Fields for creating a new query. query_code is auto-generated."""
    query_text:    str
    category:      Optional[str] = None
    stage:         Optional[str] = None
    specificity:   Optional[str] = None
    persona:       Optional[str] = None
    study_pattern: Optional[str] = None
    soa_focus:     Optional[str] = None
    rationale:     Optional[str] = None
    status:        str = 'Active'

    @field_validator(*_CONSTRAINED_FIELDS, mode='before')
    @classmethod
    def validate_constrained(cls, v, info):
        return _check_constraint(info.field_name, v)


class QueryUpdate(BaseModel):
    """Fields that can be updated on an existing query. All optional."""
    query_text:    Optional[str] = None
    category:      Optional[str] = None
    stage:         Optional[str] = None
    specificity:   Optional[str] = None
    persona:       Optional[str] = None
    study_pattern: Optional[str] = None
    soa_focus:     Optional[str] = None
    rationale:     Optional[str] = None
    status:        Optional[str] = None

    @field_validator(*_CONSTRAINED_FIELDS, mode='before')
    @classmethod
    def validate_constrained(cls, v, info):
        return _check_constraint(info.field_name, v)

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


class EntityPositionBreakdown(BaseModel):
    """
    Position distribution for one entity.
    top: % of mentions where position = 1
    mid: % of mentions where position = 2 or 3
    low: % of mentions where position >= 4
    All values are percentages (0-100).
    mention_count: total rows where
      mentioned = true for this entity.
    """
    top:           float
    mid:           float
    low:           float
    mention_count: int


class CyclePositionsResponse(BaseModel):
    """
    Position breakdown for all entities
    in a cycle. Key is comparison_code
    e.g. M001, M002.
    """
    cycle_code: str
    positions:  dict
    # Dict[comparison_code, EntityPositionBreakdown]


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


# ─── AI Study Generation ───────────────────────────────────────────────────────

class StudyGenerateRequest(BaseModel):
    study_name:   str
    description:  Optional[str] = None
    target_count: int = 50

    @field_validator('target_count')
    @classmethod
    def validate_count(cls, v):
        if v < 1 or v > 100:
            raise ValueError('target_count must be between 1 and 100')
        return v


class StudyGenerateResponse(BaseModel):
    study_type: str
    study_name: str
    job_id:     int
    status:     str


class GenerationStatusResponse(BaseModel):
    study_type:    str
    status:        str
    target_count:  int
    created_count: int


# ─── Scope SKUs ──────────────────────
# Additive: optional SKU-level measurement scope nested under entities.

class CreateScopeSkuRequest(BaseModel):
    """
    Accepts EITHER a picked listing (listing_id + the CatalogListing fields
    the frontend already has from the search results) OR a bare product_url
    (the server calls resolve_listing() first, then persists). entity_id is
    optional in both cases — when omitted, the row is auto-linked by brand
    match to an existing SoaEntity, else left null.
    """
    # Path A — picked listing (listing_id present; the rest are the
    # CatalogListing fields the frontend already fetched via search).
    listing_id: Optional[int] = None
    catalog_product_id: Optional[int] = None
    merchant_slug: Optional[str] = None
    merchant_sku: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    product_url: Optional[str] = None
    listed_price: Optional[float] = None
    currency: Optional[str] = None
    display_name: Optional[str] = None

    # Path B — paste a product URL; resolve_listing() fills in everything
    # above. user_tier_name only applies to this path.
    user_tier_name: Optional[str] = None

    # Common to both paths.
    entity_id: Optional[int] = None
    role: str = "target"

    @model_validator(mode="after")
    def check_one_path_provided(self):
        if self.listing_id is None and not self.product_url:
            raise ValueError(
                "Either listing_id (a picked catalog listing) or product_url must be provided."
            )
        if self.role not in ("target", "competitor"):
            raise ValueError("role must be 'target' or 'competitor'")
        return self


class ScopeSkuResponse(BaseModel):
    id: int
    cycle_id: Optional[int] = None
    entity_id: Optional[int] = None
    role: str
    dealengine_listing_id: Optional[int] = None
    dealengine_catalog_product_id: Optional[int] = None
    merchant_slug: Optional[str] = None
    merchant_sku: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    product_url: Optional[str] = None
    listed_price: Optional[float] = None
    currency: Optional[str] = None
    display_name: Optional[str] = None
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    error_message: Optional[str] = None


class CycleScopeResponse(BaseModel):
    """
    A cycle's effective scope (soa_shared.scope_resolution.get_effective_scope)
    plus enough state for the UI to render read-only vs editable:
      source: frozen | custom | inherited | materialized
      is_editable: false once scope_frozen_at is set, true otherwise
        (inherited/materialized/custom scopes are editable while the cycle
        is Planned).
    """
    cycle_id: int
    source: str
    is_editable: bool
    skus: List[ScopeSkuResponse]


# ─── Truecost sweep cycles ───────────────────────────────────────────────────

class TruecostTierResult(BaseModel):
    """One captured (or unavailable) tier cell for a scope SKU."""
    user_tier_name: Optional[str] = None  # None = non-member baseline
    listed_price: Optional[float] = None
    currency: Optional[str] = None
    true_cost: Optional[float] = None
    total_savings: Optional[float] = None
    total_points_earned: Optional[int] = None
    applied_deals: Optional[List[dict]] = None
    available_deals: Optional[List[dict]] = None
    confidence: Optional[float] = None
    price_was_refreshed: bool = False
    price_refreshed_at: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    captured_at: Optional[str] = None


class TruecostSkuRow(BaseModel):
    """One row of the SKU x retailer x tier grid."""
    scope_sku_id: int
    entity_id: Optional[int] = None
    merchant_slug: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    display_name: Optional[str] = None
    dealengine_listing_id: Optional[int] = None
    tiers: List[TruecostTierResult]
    # Per-tier true_cost delta vs the non-member baseline (baseline - tier),
    # i.e. positive means the tier is cheaper than baseline. Only populated
    # when both the baseline and that tier were captured, and only present
    # at all when more than one tier was swept for this SKU.
    member_vs_baseline_delta: dict[str, float] = {}


class CycleTruecostSnapshotsResponse(BaseModel):
    cycle_id: int
    cycle_code: str
    skus: List[TruecostSkuRow]


class TierOption(BaseModel):
    """One selectable tier in the truecost-sweep wizard's tier multi-select.
    value=None is the always-present non-member baseline option."""
    value: Optional[str] = None
    label: str


class ScopeTiersResponse(BaseModel):
    tiers: List[TierOption]


# ─── Actions (AC3 recommendation engine) ────────────────────────────────────

RECOMMENDATION_STATUSES = ('proposed', 'accepted', 'in_progress', 'done', 'dismissed')


class CoverageGap(BaseModel):
    """An (entity, merchant) cell where scoring reached the Deal Engine but
    every attempt came back unmeasured (no deal data at all for that
    merchant) — distinct from a compliant/measured cell, never 100% accuracy,
    never silently absent from the response."""
    entity_id: Optional[int] = None
    merchant_slug: str
    scored_rows: int
    measured_rows: int
    status: str


class GenerateActionsResponse(BaseModel):
    cycle_id: int
    findings_by_play: dict
    recommendations_by_play: dict
    total_findings: int
    total_recommendations: int
    coverage_gaps: List[CoverageGap] = []


class FindingResponse(BaseModel):
    id: int
    cycle_id: int
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    play_id: str
    dimension: str
    surface: Optional[str] = None
    persona: Optional[str] = None
    stage: Optional[str] = None
    severity: float
    cells_affected: int
    metric_snapshot: dict
    evidence_run_ids: List[int]
    created_at: Optional[str] = None


class RecommendationResponse(BaseModel):
    id: int
    cycle_id: int
    play_id: str
    pillar: str
    owner: str
    effort: str
    detector_status: str
    play_text: str
    mechanism_text: str
    expected_impact_text: str
    evidence_spec: str
    dimensions: List[str]
    finding_count: int
    cells_affected: int
    evidence_run_ids: List[int]
    priority_score: float
    status: str
    suppressed: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RecommendationStatusUpdate(BaseModel):
    status: str

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        if v not in RECOMMENDATION_STATUSES:
            raise ValueError(f"status must be one of {RECOMMENDATION_STATUSES}")
        return v
