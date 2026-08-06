import ipaddress
import re
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator, model_validator
from typing import List, Optional
from soa_shared.constants import QUERY_CONSTRAINTS
from soa_shared.scan_dimensions import VERDICT_AGENT_READY, VERDICT_NOT_AGENT_READY

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


# ─── SoA Lite (public, unauthenticated) ─────────────────────────────────────
# Every class below is a PUBLIC response/request shape consumed by the
# marketing-site widget (see app/routers/public_lite.py). Changing field
# names or types is a breaking change for that widget — coordinate before
# editing. None of these ever carry a DB primary key (cycle_id, entity_id,
# organization_id, soa_lite_requests.id) — token is the only key.

_URL_PATTERN = re.compile(r'(https?://|www\.)|([a-z0-9-]+\.[a-z]{2,}(/|\s|$))', re.IGNORECASE)
_EMAIL_PATTERN = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]+')
# Letters (incl. accented), digits, spaces, and the punctuation real brand
# names use. Deliberately excludes @ / < > { } ` ; and similar — the
# allowlist alone blocks most injection-shaped input; _URL_PATTERN/
# _EMAIL_PATTERN exist mainly to give a clearer, specific error message for
# those two common cases (e.g. a bare domain like "rival.com" would
# otherwise pass the allowlist since '.' is a legitimate name character).
_ALLOWED_NAME_PATTERN = re.compile(r"^[A-Za-zÀ-ÿ0-9' &.,\-]+$")


def _validate_public_name(v: str, field_name: str) -> str:
    v = (v or '').strip()
    if not (2 <= len(v) <= 80):
        raise ValueError(f"{field_name} must be 2-80 characters")
    if _EMAIL_PATTERN.search(v):
        raise ValueError(f"{field_name} must not be an email address")
    if _URL_PATTERN.search(v):
        raise ValueError(f"{field_name} must not be a URL or web address")
    if not _ALLOWED_NAME_PATTERN.match(v):
        raise ValueError(f"{field_name} contains disallowed characters")
    return v


# store_url is UX-level validation only — reject obviously-wrong input
# (IP literals, non-domain garbage) with a clear 422 before it ever
# reaches the pipeline. It is NOT the SSRF defense: apps/pipeline/scan
# resolves the hostname at fetch time and is the authoritative guard
# against a domain that merely *resolves* to a private/metadata address.
MAX_STORE_URL_LENGTH = 500
_DOMAIN_LABEL_PATTERN = re.compile(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$', re.IGNORECASE)


def _validate_store_url(v: Optional[str]) -> Optional[str]:
    v = (v or '').strip()
    if not v:
        return None
    if len(v) > MAX_STORE_URL_LENGTH:
        raise ValueError(f'store_url must be at most {MAX_STORE_URL_LENGTH} characters')

    candidate = v if '://' in v else f'https://{v}'
    parsed = urlparse(candidate)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError('store_url must use http or https')

    hostname = parsed.hostname
    if not hostname:
        raise ValueError('store_url must include a hostname')

    try:
        ipaddress.ip_address(hostname)
        is_ip_literal = True
    except ValueError:
        is_ip_literal = False
    if is_ip_literal:
        raise ValueError('store_url must be a domain name, not an IP address')

    labels = hostname.rstrip('.').split('.')
    if len(labels) < 2 or not all(_DOMAIN_LABEL_PATTERN.match(label) for label in labels):
        raise ValueError('store_url must have a valid domain, e.g. example.com')
    if labels[-1].isdigit():
        raise ValueError('store_url must have a valid domain, e.g. example.com')

    netloc = hostname if not parsed.port else f'{hostname}:{parsed.port}'
    return f'{parsed.scheme}://{netloc}'


class PublicLiteSubmitRequest(BaseModel):
    brand_name: str
    competitor_names: List[str] = []
    captcha_token: str
    store_url: Optional[str] = None

    @field_validator('brand_name')
    @classmethod
    def validate_brand_name(cls, v):
        return _validate_public_name(v, 'brand_name')

    @field_validator('competitor_names')
    @classmethod
    def validate_competitor_names(cls, v):
        if len(v) > 2:
            raise ValueError('competitor_names accepts at most 2 entries')
        return [_validate_public_name(name, 'competitor_names') for name in v]

    @field_validator('store_url')
    @classmethod
    def validate_store_url(cls, v):
        return _validate_store_url(v)

    @model_validator(mode='after')
    def check_names_distinct(self):
        seen = {self.brand_name.lower()}
        for name in self.competitor_names:
            key = name.lower()
            if key in seen:
                raise ValueError(
                    'Competitor names must be distinct from the brand and from each other.'
                )
            seen.add(key)
        return self


class PublicLiteSubmitResponse(BaseModel):
    token: str
    status: str


class PublicLiteProgress(BaseModel):
    completed_runs: int
    total_runs: int


class PublicLiteStatusResponse(BaseModel):
    status: str
    phase: str
    progress: Optional[PublicLiteProgress] = None
    scan_status: Optional[str] = None  # null until soa_lite_scan_results exists for this request
    # Stage 13 (F3): both null until competitor generation completes
    # (process_lite_requests, ahead of query generation) — not tied to
    # phase/status otherwise, so the widget can render the chips the
    # moment they're ready rather than waiting for the whole run.
    competitors: Optional[List[str]] = None
    competitor_source: Optional[str] = None
    # Stage 20: the run-manifest status page's two additive fields — both
    # sourced from data _run_lite_scan/_run_membership_probe already write
    # to soa_lite_scan_results, not new computation.
    #
    # membership_check mirrors member_value_applicable() (app.services.
    # lite_pillars — reused, not redefined): "applies" the instant the
    # probe says 'yes' (no need to wait on the scan); "na" only once the
    # scan has ALSO reached a terminal status (member_value's crawl-side
    # credit isn't known until then); "pending" otherwise, including
    # while the probe hasn't run/returned yet.
    membership_check: Optional[str] = None  # "pending" | "applies" | "na"
    # scan_pages_read: length of the scan row's pages_fetched — available
    # the instant the scan row exists, in any status (blocked/failed/
    # skipped rows still carry whatever was fetched before stopping).
    scan_pages_read: Optional[int] = None
    # Part 1 (E1): the run-manifest's append-only event log — [{seq, ts,
    # kind: 'log'|'done'|'state', task, text, chips?}], written
    # incrementally by apps/pipeline/lite_events.py as each stage
    # progresses. Passed straight through from soa_lite_requests.events;
    # a pre-this-stage row (or the DB default) is '[]', which the status
    # page's fallback view (P7) renders as the minimal pre-event page —
    # never absent/null, since the column itself is NOT NULL server_default '[]'.
    events: Optional[List[dict]] = None
    # Part 1 (P4): same shape as PublicLiteScan.degraded_reason/
    # degraded_banner_facts below, computed the SAME way
    # (_build_scan_payload) so the status page's terminal banner is
    # byte-identical to the report's — both None whenever the scan is
    # 'complete' (nothing to explain) or hasn't produced a row yet.
    degraded_reason: Optional[str] = None
    degraded_banner_facts: Optional[dict] = None


class PublicLiteEntityMetrics(BaseModel):
    """Full-report shape for one entity — reuses EntityMetrics' fields."""
    name: str
    role: str
    metrics: EntityMetrics


class PublicLiteScanFamily(BaseModel):
    subtotal: float
    max: float
    # Stage 10 (A2): sum of nominal maxes over non-'na' dimensions in
    # this family only — equal to `max` unless a dimension in this
    # family is 'na', in which case the UI renders "n/{applicable_max}
    # applicable" instead of pretending the full /35 or /65 (W2).
    applicable_max: float = 0.0


class PublicLiteScanDeferredItem(BaseModel):
    """One crawl-unverifiable item (S2) — never scored, never subtracted;
    surfaced so the report is honest about what a single crawl can't
    check rather than silently omitting it."""
    label: str
    reason: str


class PublicLiteScanDimension(BaseModel):
    """
    One Agent Scan dimension row. fix is null (with locked=True) for any
    dimension ranked below the top 3 by opportunity size (max - score) —
    the full fix list is paid-diagnostic material. linked is null unless
    apps/api/app/services/lite_crosswalk.py matched this dimension to a
    query-level signal for the primary entity.

    Stage 10: coverage is 'full' (default — also what a pre-Stage-10
    scorer_version "1" row implies), 'partial' (some of its scored basis
    is crawl-unverifiable — see deferred_items — but nothing here ever
    subtracts a point for a deferred item), or 'na' (inapplicable to this
    site type — excluded from every family/total sum, not scored as
    zero). cap_basis is populated only for V5 when integrity_capped, on
    scorer_version "1"/"2" rows.

    Stage 16 (Part 6): scorer_version "3" retired the legacy score-
    capping behavior entirely — was-price findings are now an UNSCORED
    advisory only (see engine.py's price_honesty_advisory, not exposed
    on this model). cap_basis is deprecated for v3: kept serialized
    (rule 6, additive-only) but always empty, since no v3 row's raw
    dimensions carry the old V5 code this field was populated from.
    """
    code: str
    name: str
    score: float
    max: float
    evidence: List[str] = []
    fix: Optional[str] = None
    # Part 5 (H1): plain-language rewrite of `fix` — no markup, no schema
    # vocabulary. `fix` (the exact-markup version) is now Full Diagnostic
    # deliverable material; the free report's fixes list (see `fixes` on
    # PublicLiteReportResponse) only ever serializes this field.
    fix_human: Optional[str] = None
    locked: bool = False
    linked: Optional[dict] = None  # {"reason": "..."} or None
    coverage: str = "full"  # full | partial | na
    deferred_items: List[PublicLiteScanDeferredItem] = []
    cap_basis: List[str] = []


class PublicLiteScan(BaseModel):
    """
    Agent Scan summary for the report. status mirrors
    soa_lite_scan_results.status honestly — complete/blocked/failed/
    skipped are all valid and never block the report itself (rule 7).
    foundation/value/dimensions are only populated when status='complete'.

    scorer_version defaults to "1" — the value implied for any row
    scanned before Stage 10 introduced the field (stored as a sibling
    key inside the dimensions jsonb, not a new column; see engine.py).

    Stage 16 (Part 6): integrity_capped is deprecated for scorer_version
    "3" — always False, since v3 never caps total_score (engine.py
    hardcodes it). Kept serialized only for rule 6 (additive-only); a
    v1/v2 row's historical True value still renders exactly as before.

    Sitemap-sampler stage (hotfix 5, S2/S3): degraded_reason is only
    ever populated for a non-'complete' status — "blocked" (the site
    rate-limited/refused our reader), "no_product_pages_found" (our
    sampler couldn't locate product pages this run, never the site's
    fault), or "unreachable" (total network/DNS failure, nothing
    responded at all). degraded_banner_facts carries the dynamic facts
    the report's first-person banner fills in (refusal type, attempt
    count, whether robots.txt was included, or sitemaps read, plus an
    optional `fetch_probe` sub-dict — Part 2, P4.b — merged in at
    report-build time since the probe runs after the scan writes its
    own banner facts) — the banner's own static wording lives in the
    frontend.

    Part 1 (M1-M4): agent_access_matrix is the per-agent robots.txt
    table (apps/pipeline/scan/agent_access_matrix.py) — populated for
    both 'complete' and degraded statuses (Agent Access is real-scored
    on both, see engine.py's S4/M1-M5 comments), null only when no scan
    row exists at all or under an older scorer_version. No scoring
    impact — evidence/table only.
    """
    status: str
    total_score: Optional[int] = None
    integrity_capped: bool = False
    scorer_version: str = "1"
    foundation: Optional[PublicLiteScanFamily] = None
    value: Optional[PublicLiteScanFamily] = None
    dimensions: List[PublicLiteScanDimension] = []
    pages_fetched: List[dict] = []
    degraded_reason: Optional[str] = None
    degraded_banner_facts: Optional[dict] = None
    agent_access_matrix: Optional[List[dict]] = None


class PublicLiteVisibilityMentionRate(BaseModel):
    """mentioned_queries / total_queries — how many of the 12 shopper
    questions named this entity at least once."""
    entity: str
    is_primary: bool
    mentioned_queries: int
    total_queries: int
    rate_pct: float


class PublicLiteVisibilityShare(BaseModel):
    """mentions / totals.total_mentions — this entity's share of every
    brand mention across all answers (primary + rivals combined).
    Shares across the array sum to ~100 (rounding)."""
    entity: str
    is_primary: bool
    mentions: int
    share_pct: float


class PublicLiteVisibilityTotals(BaseModel):
    total_mentions: int
    total_queries: int


class PublicLiteIncentiveCitation(BaseModel):
    """
    Stage 8 — CONDITIONAL metric, not unconditional: of the answers that
    mention this entity, the share whose mention carried a concrete,
    currently-active, attributed incentive. Powered by the existing,
    unmodified deal_cited -> deal_citation_rate pipeline (see the DEAL
    CITATION RULES in apps/pipeline/parser/prompts.py for the full pass-1
    rubric — a stated price, program-existence mention ("they have a
    rewards program"), or permanent policy ("free shipping over $50")
    does NOT qualify as a citation). cited_answers/rate_pct are null,
    never 0, when the entity has zero mentions — an undefined rate, not
    a zero one.
    """
    entity: str
    is_primary: bool
    mentions: int
    cited_answers: Optional[int] = None
    rate_pct: Optional[float] = None


class PublicLiteVisibilityBreakdown(BaseModel):
    mention_rate: List[PublicLiteVisibilityMentionRate] = []
    share_of_mentions: List[PublicLiteVisibilityShare] = []
    totals: PublicLiteVisibilityTotals
    incentive_citation: List[PublicLiteIncentiveCitation] = []


class PublicLiteCheck(BaseModel):
    """One WHAT WE CHECK/YOUR RESULT row inside a dimension's checks[]
    (Part 1, A1). label is always one of the dimension's own soa_shared.
    scan_dimensions.Dimension.how_measured strings (parity-tested) — this
    is never a second, independently-worded copy of that methodology
    text. evidence is an optional live-data detail (e.g. the price-
    honesty advisory's flagged/none-flagged note)."""
    code: str
    label: str
    state: str  # "pass" | "fail" | "na" | "advisory" | "blocked"
    evidence: Optional[str] = None


class PublicLiteSubLens(BaseModel):
    """One half (seen or said) of a True Value dimension. na=True means
    this half didn't contribute (crawl coverage='na', or said's own
    opportunity set had fewer than 2 mentions) — the dimension's earned/
    max already reflect the na-rescale onto whichever half did apply.

    blocked=True (fetch resilience stage): the seen half's underlying
    scan coverage was 'blocked' — every sampled product page terminally
    failed to fetch this run, so this half is NOT MEASURABLE rather than
    a genuine zero. Distinct from na: na means "doesn't apply here", not
    "couldn't be read this time."

    band_table_ref/your_value/your_band (Part 1, A2): only populated on
    a said sub-lens that isn't na — not new computation, just reporting
    which band soa_shared.scan_dimensions.apply_rate_band/apply_count_
    band already decided this run landed in, so the frontend can put a
    "YOU" marker on the right rung of the band ladder it already renders.
    """
    earned: float
    max: float
    na: bool = False
    blocked: bool = False
    evidence: List[str] = []
    band_table_ref: Optional[str] = None
    your_value: Optional[float] = None
    your_band: Optional[int] = None


class PublicLitePillarDimension(BaseModel):
    """
    One dimension row inside a pillar block. seen/said are only
    populated for True Value dimensions (price_truth, member_value,
    deal_citability) — null for visibility/accessibility dimensions,
    which have no seen/said split at all.

    fix/locked (Stage 19): only ever populated for the 6 crawl-derived
    dimensions (accessibility's 3 + True Value's 3) — visibility's
    mention-derived dimensions have nothing crawl-fixable to offer, so
    both stay at their defaults (None/False) there. locked=True means
    this dimension fell outside the top-3-by-gap free tier; fix is
    always None when locked (paid-diagnostic text never serialized).

    blocked (fetch resilience stage): True when this dimension's crawl
    coverage came back 'blocked' — every sampled product page terminally
    failed to fetch this run (429/403/5xx, after the scanner's own retry
    ladder already tried). earned/max are both 0 in that case — excluded
    from the pillar's applicable max the same way an na dimension is —
    and checks[] all report state='blocked' rather than a false fail.
    Distinct from na: this dimension DOES apply to this site, the scan
    just couldn't read the pages that would prove it this run.

    checks (Part 1, A1): the live WHAT WE CHECK/YOUR RESULT chips — null
    for share_of_mentions/recommendation_strength (which show a live
    meter/band ladder instead, via your_value/your_band below) and for
    an N/A True Value dimension (which shows a decision sentence + probe
    quote instead, T2).
    your_value/your_band (A2): only ever populated on share_of_mentions
    (your_value = live share %) and recommendation_strength (your_band =
    index into its 3-rung ladder) — the True Value dimensions' own band
    context lives on their `said` sub-lens instead, since that's the half
    the band is actually computed over.
    """
    code: str
    name: str
    earned: float
    max: float
    na: bool = False
    blocked: bool = False
    evidence: List[str] = []
    seen: Optional[PublicLiteSubLens] = None
    said: Optional[PublicLiteSubLens] = None
    checks: Optional[List[PublicLiteCheck]] = None
    your_value: Optional[float] = None
    your_band: Optional[int] = None
    fix: Optional[str] = None
    # Part 5 (H1): plain-language rewrite of `fix` — see the matching
    # comment on PublicLiteScanDimension.fix_human above.
    fix_human: Optional[str] = None
    locked: bool = False
    linked: Optional[dict] = None  # {"reason": "..."} or None — see public_lite.py's v3 crosswalk remap


class PublicLitePillar(BaseModel):
    """score is this pillar's own 0-100 rescale (earned / applicable_max
    * 100, na-dimensions excluded) — independent of composite, which
    blends all three pillars' raw earned points via soa_shared.
    scan_dimensions.compute_composite."""
    score: float
    max: float = 100.0
    dimensions: List[PublicLitePillarDimension] = []


class PublicLitePillarHeadline(BaseModel):
    """Part 3: one pillar's generated (or registry-default) one-line
    summary — see apps/pipeline/generation/pillar_headlines.py, which
    writes this shape verbatim onto soa_lite_scan_results.dimensions'
    generated_headlines key at completion time. source is 'generated'
    | 'default' (default covers both a failed/rejected generation and a
    not-measurable pillar — see NOT_MEASURABLE_HEADLINE in that
    module)."""
    headline: str
    source: str


class PublicLiteGeneratedHeadlines(BaseModel):
    visibility: PublicLitePillarHeadline
    accessibility: PublicLitePillarHeadline
    true_value: PublicLitePillarHeadline


class PublicLiteOfferRow(BaseModel):
    """F1: one row of the report's OfferFeed — a re-serialization of
    facts the crawl scorer already computed (see
    apps/pipeline/scan/offer_feed.py::build_offer_feed), never a new
    fetch. readable is 'seen' | 'partial' | 'invisible' | 'unmeasured' —
    'unmeasured' only, never 'invisible', when the underlying dimension
    couldn't be read this run (H1)."""
    name: str
    value: str
    channel: str
    eligibility: str
    freshness: str
    readable: str


class PublicLiteFixEntry(BaseModel):
    """One of the top-2 free fixes (Part 3, F1) — plain-language only,
    no markup (see PublicLitePillarDimension.fix_human). impact is the
    dimension's own max - earned, the same points a locked fix's slot
    would have granted."""
    code: str
    name: str
    fix_human: str
    impact: float
    # F3: "ENG" or "TRUESYNC" — see scan_dimensions.Dimension.fix_owner.
    fix_owner: str = "ENG"


class PublicLiteExposureReason(BaseModel):
    """Part 4: one run-tailored "why you're leaking value" reason — see
    app/services/exposure_reasons.py's table-driven library. text
    interpolates only run-derived numbers (never a literal). impact_weight
    is this reason's share of the SELECTED group's severity (renormalized
    among the returned reasons, not the full library) — the frontend
    multiplies it against the live, slider-driven modeled exposure total,
    the same way the pre-Part-4 static cause weights always did."""
    id: str
    text: str
    impact_weight: float
    severity_rank: int


class PublicLiteFixesSection(BaseModel):
    """
    Part 3 (F1): the free report's ranked-fixes list. `visible` never has
    more than 2 entries; everything beyond rank 2 is reduced to
    `remaining_count` — no title, dimension, or impact for a locked fix
    is ever serialized anywhere in this object. Deliberately separate
    from pillars.accessibility/true_value.dimensions, which keep
    reporting every dimension's real earned/max/evidence unconditionally
    (needed by the True Value butterfly and Accessibility tiles,
    independent of fix-lock status).
    """
    visible: List[PublicLiteFixEntry] = []
    remaining_count: int = 0


class PublicLitePillars(BaseModel):
    """
    Stage 16 (Part 7), rescaled Stage 25: the three-pillar breakdown
    behind a scan's visibility/accessibility/composite scalars.
    Additive — present on the full report only, and only when the scan
    row is at the CURRENT scorer version (older rows have no
    current-shaped crawl dimensions to build this from; see
    public_lite.py's version branch).
    """
    visibility: PublicLitePillar
    accessibility: PublicLitePillar
    true_value: PublicLitePillar
    member_value_na: bool = False
    # Part 3 (F1): additive, same current-version-only availability as
    # the rest of this object — see PublicLiteFixesSection's own
    # docstring.
    fixes: Optional[PublicLiteFixesSection] = None
    # Stage 25 (Part 5, G1): "AGENT-READY" | "NOT AGENT-READY" — a pass/
    # fail gate independent of the composite's straight-sum weighting,
    # from soa_shared.scan_dimensions.compute_verdict. Only ever set
    # alongside a real composite (state == "scored") — see the
    # model_validator below and build_pillars_payload's own docstring.
    verdict: Optional[str] = None
    # Verdict gate template branching stage (G1): was previously silently
    # dropped by validation — build_pillars_payload's return dict has
    # always had a `composite` key, but this model never declared the
    # field, so pillars.composite was undefined in every report response
    # regardless of this value. Now a real field, and the one that can
    # legitimately be None (composite_withheld/unverified), distinct from
    # the top-level PublicLiteReportResponse.composite it's sourced from.
    composite: Optional[float] = None
    # state: "scored" | "composite_withheld" | "unverified" — see
    # build_pillars_payload's docstring for the exact three-way rule.
    # Absent on a pre-this-stage cached/mocked payload; the frontend
    # treats a missing state as "scored" (rule 6, additive-only).
    state: str = "scored"
    tv_pct: Optional[float] = None
    tv_earned: float = 0.0
    tv_applicable: float = 0.0
    unmeasured_count: int = 0
    # F4: gap-area counts for the S2 fixable-hook band. gap_areas_total/
    # gap_areas_parleo_fixes are fixed framework constants (4 and 2);
    # parleo_fixable_points is this run's own measured recoverable
    # points within TrueSync's two owned dimensions.
    gap_areas_total: int = 4
    gap_areas_parleo_fixes: int = 2
    parleo_fixable_points: float = 0.0
    # Part 4: up to 3 run-tailored exposure reasons, ranked by severity —
    # see exposure_reasons.py. [] when nothing measured this run triggers
    # a reason (honest-state: never padded/repeated to reach 3).
    exposure_reasons: List[PublicLiteExposureReason] = []

    @model_validator(mode="after")
    def _verdict_requires_a_real_score(self):
        """G1's invariant, enforced at construction time: a failing (or
        passing) verdict may never be asserted from a run that couldn't
        compute its own composite — AGENT-READY/NOT AGENT-READY exist
        only in state == 'scored', which is exactly when composite is
        guaranteed non-None. Catches any future regression that
        reintroduces a fabricated verdict, not just this stage's fix."""
        if self.verdict in (VERDICT_AGENT_READY, VERDICT_NOT_AGENT_READY) and self.composite is None:
            raise ValueError(
                f"verdict={self.verdict!r} must not be asserted when composite is withheld (None)"
            )
        return self


class PublicLiteReportResponse(BaseModel):
    """
    by_stage: DEPRECATED (Stage 7) — always null. Per-stage mention data
    is now paid-diagnostic material and must never be serialized into
    this public payload; see visibility_breakdown for the stage-agnostic
    aggregates the free report shows instead. The key is kept (not
    deleted) per the additive-contract rule so an already-deployed
    widget reading `report.by_stage || {}` keeps working mid-deploy.
    visibility_breakdown: Stage 7 addition. Named _breakdown rather than
    reusing `visibility` because that field name is already taken by the
    scalar SoM subscore below — reshaping an existing field would break
    the additive-only contract. Stage 8 adds visibility_breakdown.
    incentive_citation (see PublicLiteIncentiveCitation) — same object,
    additive field, no shape change to mention_rate/share_of_mentions/
    totals. Present on the full (unlocked) report only — the teaser
    stays share-of-mentions-only, unchanged.
    pillars (Stage 16, Part 7): additive, full report only, scorer_
    version "3" only. visibility/accessibility/composite above are
    unchanged fields but — for a v3 scan — are now computed FROM this
    same pillars breakdown (build_pillars_payload, the one composite
    function) rather than the pre-Stage-16 0.6/0.4 blend; older scan
    rows keep rendering via that original formula untouched.
    """
    status: str
    locked: bool = False
    overall: List[PublicLiteEntityMetrics] = []
    by_stage: Optional[dict] = None  # DEPRECATED — always null, see docstring
    scan: Optional[PublicLiteScan] = None
    visibility: Optional[float] = None
    accessibility: Optional[float] = None
    composite: Optional[float] = None
    scan_status: Optional[str] = None
    visibility_breakdown: Optional[PublicLiteVisibilityBreakdown] = None
    pillars: Optional[PublicLitePillars] = None
    # Stage 13 (W4/W5): drives the widget's solo-comparison fallback and
    # the "auto-selected by ChatGPT" methodology stamp.
    competitor_source: Optional[str] = None
    # Part 5 (R3): annual USD estimate from the revenue probe (apps/
    # pipeline/generation/revenue_probe.py), null when the probe never
    # ran or came back unparseable/absurd. Feeds ONLY the exposure
    # calculator's default seed (annual units throughout since Report
    # redesign Part 7 — no /12 conversion) — never a score input.
    revenue_estimate_usd: Optional[float] = None
    # F1/F2: additive, current-scan-only (see engine.py's dimensions
    # dict — only ever set on a STATUS_COMPLETE run, same as `pillars`
    # above). Both null on a degraded/blocked/old run — the report's
    # parsed-page card renders its honest banner instead (H1).
    offers: Optional[List[PublicLiteOfferRow]] = None
    product_image_url: Optional[str] = None
    # 1c: schema.org Product.name, same extraction pass/gating as
    # product_image_url above — independently null-able (a product can
    # have one field without the other).
    product_name: Optional[str] = None
    # Part 3: additive, same sibling-key-on-dimensions gating as offers/
    # product_image_url above — null on any run from before this stage,
    # or when the worker's OpenAI key was unset at completion time. The
    # frontend falls back to its own hardcoded titles when null (3c).
    generated_headlines: Optional[PublicLiteGeneratedHeadlines] = None


class PublicLiteEmailRequest(BaseModel):
    email: str

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        v = (v or '').strip()
        if not _EMAIL_PATTERN.fullmatch(v):
            raise ValueError('email must be a valid email address')
        return v
