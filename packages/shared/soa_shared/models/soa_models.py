"""
SoA (Share of Algorithm) SQLAlchemy models.

Six original tables plus two new tables (soa_entities, soa_cycle_entities)
that extend the shared PostgreSQL database. The supply app's models.py is
never imported or modified.
"""
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base
from .merchant_ref import Merchant  # noqa: F401 — ensures Merchant is mapped
from soa_shared.constants import (
    QUERY_CATEGORIES,
    QUERY_STAGES,
    QUERY_SPECIFICITIES,
    QUERY_PERSONAS,
    QUERY_STATUSES,
    QUERY_STUDY_PATTERNS,
    QUERY_SUBSCRIPTION_STATES,
)


def _in_list(values: list) -> str:
    """
    Build SQL IN clause value list from a Python list.
    e.g. ['a', 'b'] → "('a', 'b')"
    """
    quoted = ', '.join(f"'{v}'" for v in values)
    return f"({quoted})"


# ---------------------------------------------------------------------------
# 1. soa_entities — named entity registry for any SoA study subject
# ---------------------------------------------------------------------------

class SoaEntity(Base):
    __tablename__ = "soa_entities"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('retailer','brand','cpg','service','aggregate')",
            name="ck_soa_entities_entity_type",
        ),
        Index("ix_soa_entities_entity_type", "entity_type"),
        Index("ix_soa_entities_category", "category"),
    )

    id = Column(Integer, primary_key=True)

    name = Column(
        Text,
        nullable=False,
        comment=(
            "Display name as used in coding prompts and reports. Must match "
            "how the entity is commonly named in agent responses. "
            "e.g. 'Coca-Cola', 'Sephora', 'Drunk Elephant'"
        ),
    )

    slug = Column(
        Text,
        unique=True,
        nullable=False,
        comment=(
            "URL-safe identifier. Lowercase, hyphens only. Used as internal "
            "reference key. e.g. 'coca-cola', 'sephora', 'drunk-elephant'"
        ),
    )

    entity_type = Column(
        Text,
        nullable=False,
        default="retailer",
        comment=(
            "The type of entity. Values: retailer, brand, cpg, service, aggregate."
        ),
    )

    category = Column(
        Text,
        nullable=True,
        comment=(
            "The market category this entity operates in. "
            "e.g. 'beauty', 'beverage', 'automotive', 'streaming'"
        ),
    )

    merchant_id = Column(
        Integer,
        ForeignKey("merchants.id"),
        nullable=True,
        index=True,
        comment=(
            "Optional link to supply app merchants table. Populated when this "
            "entity has a presence in the supply app. NULL for entities with no "
            "supply app presence such as CPG brands."
        ),
    )

    website_url = Column(Text, nullable=True, comment="Primary website URL")

    aliases = Column(
        JSON,
        nullable=True,
        comment=(
            "Alternative names this entity may be referred to in agent responses. "
            "Used by the coder to improve mention detection. "
            "e.g. ['Coke', 'Coca Cola'] for entity named 'Coca-Cola'"
        ),
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    merchant = relationship("Merchant", foreign_keys=[merchant_id])
    cycle_entities = relationship(
        "SoaCycleEntity",
        back_populates="entity",
    )
    coded_mentions = relationship("SoaCodedMention", back_populates="entity")
    metrics_results = relationship("SoaMetricsResult", back_populates="entity")


# ---------------------------------------------------------------------------
# 2. soa_queries
# ---------------------------------------------------------------------------

class SoaQuery(Base):
    __tablename__ = "soa_queries"
    __table_args__ = (
        CheckConstraint(
            f"category IN {_in_list(QUERY_CATEGORIES)}",
            name="ck_soa_queries_category",
        ),
        CheckConstraint(
            f"stage IN {_in_list(QUERY_STAGES)}",
            name="ck_soa_queries_stage",
        ),
        CheckConstraint(
            f"specificity IN {_in_list(QUERY_SPECIFICITIES)}",
            name="ck_soa_queries_specificity",
        ),
        CheckConstraint(
            f"persona IN {_in_list(QUERY_PERSONAS)}",
            name="ck_soa_queries_persona",
        ),
        CheckConstraint(
            f"status IN {_in_list(QUERY_STATUSES)}",
            name="ck_soa_queries_status",
        ),
        CheckConstraint(
            f"study_pattern IN {_in_list(QUERY_STUDY_PATTERNS)}",
            name="ck_soa_queries_study_pattern",
        ),
        CheckConstraint(
            f"subscription_state IS NULL OR subscription_state IN {_in_list(QUERY_SUBSCRIPTION_STATES)}",
            name="ck_soa_queries_subscription_state",
        ),
        Index("ix_soa_queries_category_stage_status", "category", "stage", "status"),
        Index("ix_soa_queries_study_type", "study_type"),
        Index("ix_soa_queries_study_pattern", "study_pattern"),
        Index("ix_soa_queries_organization_id", "organization_id"),
    )

    id = Column(Integer, primary_key=True)
    query_code = Column(Text, unique=True, nullable=False)
    query_text = Column(Text, nullable=False)
    category = Column(Text, nullable=False)
    stage = Column(Text, nullable=False)
    specificity = Column(Text, nullable=False)
    persona = Column(Text, nullable=False)
    soa_focus = Column(Text)
    rationale = Column(Text)
    status = Column(Text, nullable=False, default="Active", server_default="Active")

    study_type = Column(
        Text,
        nullable=False,
        default="retailer_sephora",
        index=True,
        comment=(
            "Identifies which study this query belongs to. Matches study_type on "
            "soa_cycles to determine which queries are loaded for a cycle. "
            "e.g. 'retailer_sephora', 'brand_drunk_elephant', 'brand_vs_brand_cola'"
        ),
    )

    study_pattern = Column(
        Text,
        nullable=False,
        default="retailer",
        index=True,
        comment=(
            "The structural pattern of this study. Determines how the coding rubric "
            "is applied and how metrics are labeled in reports. "
            "retailer: retailer vs retailer. "
            "brand_at_retail: brand vs stockists. "
            "brand_vs_brand: brand vs competing brands."
        ),
    )

    organization_id = Column(
        Integer,
        ForeignKey('organizations.id'),
        nullable=False,
    )
    created_by = Column(String, nullable=True)

    # Persona eligibility state — additive, optional. Null on all four (the
    # default) means "no eligibility constraint", i.e. today's behavior.
    # Used only when ELIGIBILITY_CONDITIONING_ENABLED is true, to resolve
    # whether a live deal is eligible for the persona running this query.
    membership_program = Column(
        Text,
        nullable=True,
        comment="Merchant-specific loyalty program name, e.g. 'Beauty Insider'. Free text.",
    )
    tier_name = Column(
        Text,
        nullable=True,
        comment="Merchant-specific tier within the program, e.g. 'Rouge', 'VIB'. Free text.",
    )
    subscription_state = Column(
        Text,
        nullable=True,
        comment="subscribed/not_subscribed for subscribe-and-save eligibility. Null = unconstrained.",
    )
    new_customer = Column(
        Boolean,
        nullable=True,
        comment="True if this persona is a new/first-time customer. Null = unconstrained.",
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    runs = relationship("SoaRun", back_populates="query")


# ---------------------------------------------------------------------------
# 3. soa_cycles
# ---------------------------------------------------------------------------

class SoaCycle(Base):
    __tablename__ = "soa_cycles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planned','running','complete','failed')",
            name="ck_soa_cycles_status",
        ),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_soa_cycles_end_date_gte_start",
        ),
        CheckConstraint(
            "study_pattern IN ('retailer','brand_at_retail','brand_vs_brand','mixed')",
            name="ck_soa_cycles_study_pattern",
        ),
        CheckConstraint(
            "cycle_mode IN ('query','truecost')",
            name="ck_soa_cycles_cycle_mode",
        ),
        Index("ix_soa_cycles_study_type", "study_type"),
        Index("ix_soa_cycles_organization_id", "organization_id"),
    )

    id = Column(Integer, primary_key=True)
    cycle_code = Column(Text, unique=True, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    total_runs_planned = Column(Integer)
    completed_runs = Column(Integer, default=0, server_default="0")
    status = Column(Text, nullable=False, default="planned", server_default="planned")
    notes = Column(Text)

    platforms = Column(
        JSON,
        nullable=True,
        comment='List of platform ids e.g. ["chatgpt", "gemini"]',
    )
    runs_per_query = Column(
        Integer,
        nullable=True,
        default=5,
        comment='Runs per query per platform',
    )

    study_type = Column(
        Text,
        nullable=False,
        default="retailer_sephora",
        index=True,
        comment="Identifies which study this cycle runs. Must match study_type in soa_queries.",
    )

    study_pattern = Column(
        Text,
        nullable=False,
        default="retailer",
        comment=(
            "The structural pattern of this cycle. Must match the study_pattern of "
            "the queries loaded for it. Drives coding rubric and report labeling."
        ),
    )

    scope_frozen_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "Set when this cycle's SKU-level scope (soa_scope_skus rows with "
            "cycle_id=this) was materialized and frozen — at run start. Once set, "
            "the scope is read-only; see soa_shared/scope_resolution.py."
        ),
    )
    scope_is_custom = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment=(
            "True once a user has explicitly edited this cycle's scope while "
            "Planned — the cycle then stops resyncing from entity templates "
            "even if PLANNED_CYCLE_SCOPE_RESYNC is on."
        ),
    )

    organization_id = Column(
        Integer,
        ForeignKey('organizations.id'),
        nullable=False,
    )
    created_by = Column(String, nullable=True)

    cycle_mode = Column(
        String,
        nullable=False,
        default="query",
        server_default="query",
        comment=(
            "'query' — the existing LLM query/coding pipeline. "
            "'truecost' — sweeps the cycle's scoped SKUs through the Deal "
            "Engine instead of running LLM queries; see "
            "apps/pipeline/sweep/truecost_sweep.py."
        ),
    )
    truecost_tiers = Column(
        JSON,
        nullable=True,
        comment=(
            "List of loyalty tier names to sweep for a 'truecost' cycle. "
            "A null entry in the list means the non-member baseline. "
            "Ignored for cycle_mode='query'. Defaults to [null] (baseline "
            "only) at sweep time when empty/None."
        ),
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    runs = relationship("SoaRun", back_populates="cycle")
    metrics_results = relationship("SoaMetricsResult", back_populates="cycle")
    cycle_entities = relationship(
        "SoaCycleEntity",
        back_populates="cycle",
        order_by="SoaCycleEntity.comparison_code",
        cascade="all, delete-orphan",
    )
    scope_skus = relationship("SoaScopeSku", back_populates="cycle")
    truecost_snapshots = relationship("SoaTruecostSnapshot", back_populates="cycle")


# ---------------------------------------------------------------------------
# 4. soa_cycle_entities — comparison set for a specific cycle
# ---------------------------------------------------------------------------

class SoaCycleEntity(Base):
    __tablename__ = "soa_cycle_entities"
    __table_args__ = (
        CheckConstraint(
            "role IN ('primary','competitor')",
            name="ck_soa_cycle_entities_role",
        ),
        UniqueConstraint(
            "cycle_id", "comparison_code",
            name="uq_soa_cycle_entities_cycle_code",
        ),
        UniqueConstraint(
            "cycle_id", "entity_id",
            name="uq_soa_cycle_entities_cycle_entity",
        ),
        Index("ix_soa_cycle_entities_cycle_id", "cycle_id"),
        Index("ix_soa_cycle_entities_entity_id", "entity_id"),
    )

    id = Column(Integer, primary_key=True)

    cycle_id = Column(
        Integer,
        ForeignKey("soa_cycles.id"),
        nullable=False,
        index=True,
    )

    entity_id = Column(
        Integer,
        ForeignKey("soa_entities.id"),
        nullable=False,
        index=True,
    )

    comparison_code = Column(
        Text,
        nullable=False,
        comment=(
            "The label used in the coding prompt and in soa_coded_mentions for this "
            "entity in this cycle. e.g. M001, M002, M003, M004. Must be unique per "
            "cycle. The primary entity is always M001."
        ),
    )

    role = Column(
        Text,
        nullable=False,
        comment=(
            "primary — the entity being measured. Always M001. "
            "competitor — entities in the comparison set."
        ),
    )

    display_name = Column(
        Text,
        nullable=True,
        comment=(
            "Optional override for the entity name shown in the coding prompt. "
            "If null, uses soa_entities.name."
        ),
    )

    cycle = relationship("SoaCycle", back_populates="cycle_entities")
    entity = relationship("SoaEntity", back_populates="cycle_entities")


# ---------------------------------------------------------------------------
# 4b. soa_scope_skus — optional SKU-level measurement scope, nested under
# entities. When a cycle has no scope SKUs, coding/scoring behave exactly
# as they did before this table existed.
# ---------------------------------------------------------------------------

class SoaScopeSku(Base):
    __tablename__ = "soa_scope_skus"
    __table_args__ = (
        CheckConstraint(
            "role IN ('target','competitor')",
            name="ck_soa_scope_skus_role",
        ),
        Index("ix_soa_scope_skus_cycle_id", "cycle_id"),
        Index("ix_soa_scope_skus_entity_id", "entity_id"),
    )

    id = Column(Integer, primary_key=True)

    cycle_id = Column(
        Integer,
        ForeignKey("soa_cycles.id"),
        nullable=True,
        index=True,
        comment="Cycle this scope SKU applies to. Nullable so a SKU can be authored before being attached to a cycle.",
    )

    entity_id = Column(
        Integer,
        ForeignKey("soa_entities.id"),
        nullable=True,
        index=True,
        comment="The brand/merchant entity this SKU belongs to. Null if not auto-linked or manually set.",
    )

    role = Column(
        Text,
        nullable=False,
        default="target",
        server_default="target",
        comment="target — the SKU being measured. competitor — a comparison SKU.",
    )

    # Deal Engine reference BY VALUE — mirrors the merchant_ref.py pattern.
    # No cross-DB FK to the supply app's catalog tables; these are a
    # point-in-time snapshot of what the Deal Engine returned when the SKU
    # was added to scope. All nullable.
    dealengine_listing_id = Column(Integer, nullable=True, index=True)
    dealengine_catalog_product_id = Column(Integer, nullable=True)
    merchant_slug = Column(Text, nullable=True)
    merchant_sku = Column(Text, nullable=True)
    brand = Column(Text, nullable=True)
    category = Column(Text, nullable=True)
    product_url = Column(Text, nullable=True)
    listed_price = Column(Numeric(10, 2), nullable=True)
    currency = Column(Text, nullable=True)
    display_name = Column(
        Text,
        nullable=True,
        comment="Name shown in the coding prompt and UI. Falls back to brand + merchant_sku if null.",
    )

    is_active = Column(Boolean, nullable=False, default=True, server_default="true")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    cycle = relationship("SoaCycle", back_populates="scope_skus")
    entity = relationship("SoaEntity")
    incentive_scores = relationship("SoaIncentiveScore", back_populates="scope_sku")
    truecost_snapshots = relationship("SoaTruecostSnapshot", back_populates="scope_sku")


# ---------------------------------------------------------------------------
# 4c. soa_truecost_snapshots — one row per (scope SKU x tier) captured by a
# 'truecost' cycle's Deal Engine sweep. Additive; never populated by the
# query pipeline.
# ---------------------------------------------------------------------------

class SoaTruecostSnapshot(Base):
    __tablename__ = "soa_truecost_snapshots"
    __table_args__ = (
        CheckConstraint(
            "status IN ('captured','ground_truth_unavailable')",
            name="ck_soa_truecost_snapshots_status",
        ),
        Index("ix_soa_truecost_snapshots_cycle_id", "cycle_id"),
        Index("ix_soa_truecost_snapshots_scope_sku_id", "scope_sku_id"),
    )

    id = Column(Integer, primary_key=True)

    cycle_id = Column(
        Integer,
        ForeignKey("soa_cycles.id"),
        nullable=False,
        index=True,
    )
    scope_sku_id = Column(
        Integer,
        ForeignKey("soa_scope_skus.id"),
        nullable=False,
        index=True,
    )
    entity_id = Column(Integer, ForeignKey("soa_entities.id"), nullable=True)

    # Deal Engine reference / response fields — mirrors scope_sku at sweep
    # time, by value (no cross-DB FK).
    dealengine_listing_id = Column(Integer, nullable=True, index=True)
    merchant_slug = Column(Text, nullable=True)
    brand = Column(Text, nullable=True)
    category = Column(Text, nullable=True)

    user_tier_name = Column(
        Text,
        nullable=True,
        comment="Loyalty tier swept for this row. Null means the non-member baseline.",
    )

    listed_price = Column(Numeric(10, 2), nullable=True)
    currency = Column(Text, nullable=True)
    true_cost = Column(Numeric(10, 2), nullable=True)
    total_savings = Column(Numeric(10, 2), nullable=True)
    total_points_earned = Column(Integer, nullable=True)
    applied_deals = Column(JSON, nullable=True)
    available_deals = Column(JSON, nullable=True)
    confidence = Column(Float, nullable=True)

    price_was_refreshed = Column(Boolean, nullable=False, default=False, server_default="false")
    price_refreshed_at = Column(DateTime(timezone=True), nullable=True)

    status = Column(
        Text,
        nullable=False,
        default="captured",
        server_default="captured",
        comment="'captured' — true-cost computed. 'ground_truth_unavailable' — Deal Engine call failed.",
    )
    error_message = Column(Text, nullable=True)

    captured_at = Column(DateTime(timezone=True), server_default=func.now())

    cycle = relationship("SoaCycle", back_populates="truecost_snapshots")
    scope_sku = relationship("SoaScopeSku", back_populates="truecost_snapshots")
    entity = relationship("SoaEntity")


# ---------------------------------------------------------------------------
# 5. soa_runs
# ---------------------------------------------------------------------------

class SoaRun(Base):
    __tablename__ = "soa_runs"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('chatgpt','perplexity','gemini','claude','gemini_grounded')",
            name="ck_soa_runs_platform",
        ),
        CheckConstraint(
            "status IN ('pending','success','error','timeout')",
            name="ck_soa_runs_status",
        ),
        CheckConstraint(
            "run_number BETWEEN 1 AND 10",
            name="ck_soa_runs_run_number_range",
        ),
        UniqueConstraint(
            "cycle_id", "query_id", "platform", "run_number",
            name="uq_soa_runs_slot",
        ),
        Index("ix_soa_runs_cycle_platform_status", "cycle_id", "platform", "status"),
        Index("ix_soa_runs_query_platform", "query_id", "platform"),
    )

    id = Column(Integer, primary_key=True)
    cycle_id = Column(Integer, ForeignKey("soa_cycles.id"), nullable=False, index=True)
    query_id = Column(Integer, ForeignKey("soa_queries.id"), nullable=False, index=True)
    platform = Column(Text, nullable=False)
    run_number = Column(Integer, nullable=False)
    run_at = Column(DateTime(timezone=True), server_default=func.now())
    raw_response = Column(Text)
    response_tokens = Column(Integer)
    latency_ms = Column(Integer)
    status = Column(Text, nullable=False, default="pending", server_default="pending")
    error_message = Column(Text)
    search_triggered = Column(
        Boolean,
        nullable=True,
        comment=(
            "Whether the LLM triggered a web search for this run. "
            "True/False for OpenAI Responses API runs. "
            "NULL for platforms that do not expose this signal."
        ),
    )
    retrieved_sources = Column(
        JSON,
        nullable=True,
        comment=(
            "Grounding/search source URLs where the platform exposes them — "
            "OpenAI web_search items, Gemini grounding metadata, Perplexity "
            "citations. NULL when not exposed or not used. Seeds M26."
        ),
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    cycle = relationship("SoaCycle", back_populates="runs")
    query = relationship("SoaQuery", back_populates="runs")
    coded_mentions = relationship("SoaCodedMention", back_populates="run")
    other_mentions = relationship("SoaOtherMention", back_populates="run")
    incentive_scores = relationship("SoaIncentiveScore", back_populates="run")


# ---------------------------------------------------------------------------
# 6. soa_coded_mentions
# ---------------------------------------------------------------------------

class SoaCodedMention(Base):
    __tablename__ = "soa_coded_mentions"
    __table_args__ = (
        CheckConstraint(
            "strength IS NULL OR strength IN ('Primary','Positive','Neutral','Negative')",
            name="ck_soa_coded_mentions_strength",
        ),
        CheckConstraint(
            "mentioned = TRUE OR position IS NULL",
            name="ck_soa_coded_mentions_position_requires_mention",
        ),
        CheckConstraint(
            "mentioned = TRUE OR strength IS NULL",
            name="ck_soa_coded_mentions_strength_requires_mention",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="ck_soa_coded_mentions_confidence_range",
        ),
        UniqueConstraint(
            "run_id", "entity_id",
            name="uq_soa_coded_mentions_run_entity",
        ),
        Index("ix_soa_coded_mentions_run_entity", "run_id", "entity_id"),
        Index("ix_soa_coded_mentions_entity_id", "entity_id"),
        Index("ix_soa_coded_mentions_entity_mentioned", "entity_id", "mentioned"),
        Index("ix_soa_coded_mentions_needs_review", "needs_review"),
    )

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("soa_runs.id"), nullable=False, index=True)

    entity_id = Column(
        Integer,
        ForeignKey("soa_entities.id"),
        nullable=False,
        index=True,
        comment=(
            "FK to soa_entities. References the SoA entity registry, not the "
            "supply app merchants table directly."
        ),
    )

    # Kept for backward compatibility with metrics/calculator.py and metrics/writer.py.
    # Populated when entity.merchant_id is not null. No FK constraint.
    merchant_id = Column(Integer, nullable=True, index=True)

    mentioned = Column(Boolean, nullable=False, default=False, server_default="false")
    position = Column(Integer, nullable=True)
    strength = Column(Text, nullable=True)
    deal_cited = Column(Boolean, nullable=False, default=False, server_default="false")
    deal_types = Column(
        JSON,
        nullable=True,
        comment=(
            "Array of deal type strings. "
            "Valid values: discount_pct, "
            "promo_name, loyalty_points, "
            "member_price, free_shipping, "
            "gift_with_purchase. "
            "price_point and price_comparison "
            "are NOT valid — price information "
            "alone does not constitute a deal."
        ),
    )
    evidence = Column(Text, nullable=True)
    coded_by = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    needs_review = Column(Boolean, nullable=False, default=False, server_default="false")
    reviewed_by = Column(Text, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    run = relationship("SoaRun", back_populates="coded_mentions")
    entity = relationship("SoaEntity", back_populates="coded_mentions")


# ---------------------------------------------------------------------------
# 7. soa_other_mentions
# ---------------------------------------------------------------------------

class SoaOtherMention(Base):
    __tablename__ = "soa_other_mentions"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("soa_runs.id"), nullable=False, index=True)
    merchant_name = Column(Text, nullable=False)
    position = Column(Integer, nullable=True)
    strength = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    run = relationship("SoaRun", back_populates="other_mentions")


# ---------------------------------------------------------------------------
# 8. soa_metrics_results
# ---------------------------------------------------------------------------

class SoaMetricsResult(Base):
    __tablename__ = "soa_metrics_results"
    __table_args__ = (
        CheckConstraint(
            "slice_type IN ('overall','category','stage','specificity','persona','platform')",
            name="ck_soa_metrics_results_slice_type",
        ),
        UniqueConstraint(
            "cycle_id", "entity_id", "slice_type", "slice_value",
            name="uq_soa_metrics_results_slice",
        ),
        Index(
            "ix_soa_metrics_results_cycle_entity_slice_type",
            "cycle_id", "entity_id", "slice_type",
        ),
        Index(
            "ix_soa_metrics_results_entity_slice_type_value",
            "entity_id", "slice_type", "slice_value",
        ),
    )

    id = Column(Integer, primary_key=True)
    cycle_id = Column(Integer, ForeignKey("soa_cycles.id"), nullable=False, index=True)
    entity_id = Column(Integer, ForeignKey("soa_entities.id"), nullable=False, index=True)
    slice_type = Column(Text, nullable=False)
    slice_value = Column(Text, nullable=False)
    total_runs = Column(Integer, nullable=False)
    total_mentions = Column(Integer, nullable=False)
    mention_rate = Column(Float)
    soa_pct = Column(Float)
    position_index = Column(Float)
    rsi_score = Column(Float)
    deal_citation_rate = Column(Float)
    platform_dist_index = Column(Float)
    calculated_at = Column(DateTime(timezone=True), server_default=func.now())

    cycle = relationship("SoaCycle", back_populates="metrics_results")
    entity = relationship("SoaEntity", back_populates="metrics_results")


# ---------------------------------------------------------------------------
# 8a. soa_eligibility_metrics — eligibility-conditioned Rung-0 metrics
# ---------------------------------------------------------------------------

class SoaEligibilityMetricsResult(Base):
    """
    M1 (incentive_consideration_rate) and M3 (eligible_surfacing_rate),
    conditioned on the Deal Engine's "live AND eligible" deal set for the
    persona running each query. Additive — does not touch
    soa_metrics_results or any existing metric.
    """
    __tablename__ = "soa_eligibility_metrics"
    __table_args__ = (
        CheckConstraint(
            "slice_type IN ('overall','category','stage','specificity','persona','platform')",
            name="ck_soa_eligibility_metrics_slice_type",
        ),
        UniqueConstraint(
            "cycle_id", "entity_id", "slice_type", "slice_value",
            name="uq_soa_eligibility_metrics_slice",
        ),
        Index(
            "ix_soa_eligibility_metrics_cycle_entity_slice_type",
            "cycle_id", "entity_id", "slice_type",
        ),
    )

    id = Column(Integer, primary_key=True)
    cycle_id = Column(Integer, ForeignKey("soa_cycles.id"), nullable=False, index=True)
    entity_id = Column(Integer, ForeignKey("soa_entities.id"), nullable=False, index=True)
    slice_type = Column(Text, nullable=False)
    slice_value = Column(Text, nullable=False)

    total_eligible_runs = Column(
        Integer,
        nullable=False,
        comment="Denominator: runs where this entity had a live AND eligible deal.",
    )
    surfaced_eligible_count = Column(
        Integer,
        nullable=False,
        comment="Numerator for M3: eligible runs where the entity was also mentioned.",
    )
    considered_eligible_count = Column(
        Integer,
        nullable=False,
        comment="Numerator for M1: eligible runs where deal_cited was also true.",
    )
    eligible_surfacing_rate = Column(Float, nullable=True, comment="M3")
    incentive_consideration_rate = Column(Float, nullable=True, comment="M1")

    calculated_at = Column(DateTime(timezone=True), server_default=func.now())

    cycle = relationship("SoaCycle")
    entity = relationship("SoaEntity")


# ---------------------------------------------------------------------------
# 8b. soa_incentive_scores — Rung-0 incentive fidelity scoring vs Deal Engine
# ---------------------------------------------------------------------------

class SoaIncentiveScore(Base):
    __tablename__ = "soa_incentive_scores"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scored','ground_truth_unavailable','no_merchant_mapping','skipped')",
            name="ck_soa_incentive_scores_status",
        ),
        Index("ix_soa_incentive_scores_run_id", "run_id"),
        Index("ix_soa_incentive_scores_entity_id", "entity_id"),
        Index("ix_soa_incentive_scores_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("soa_runs.id"), nullable=False, index=True)

    entity_id = Column(
        Integer,
        ForeignKey("soa_entities.id"),
        nullable=True,
        index=True,
        comment="FK to soa_entities. Null if the merchant could not be resolved.",
    )

    # Kept for read convenience, mirrors soa_coded_mentions.merchant_id pattern.
    # No FK constraint — merchants is owned by /supply.
    merchant_id = Column(Integer, nullable=True, index=True)

    scope_sku_id = Column(
        Integer,
        ForeignKey("soa_scope_skus.id"),
        nullable=True,
        index=True,
        comment="Set when this row scores a SKU-level scope coding instead of a brand x category one.",
    )
    dealengine_listing_id = Column(
        Integer,
        nullable=True,
        index=True,
        comment="Deal Engine listing id used for the true-cost call. Mirrors soa_scope_skus.dealengine_listing_id by value.",
    )

    # Extracted from the agent's response by the coder (parser/coding_response.py).
    stated_price = Column(Float, nullable=True)
    claimed_net_price = Column(Float, nullable=True)
    claimed_discount_value = Column(Float, nullable=True)
    claimed_discount_pct = Column(Float, nullable=True)
    claimed_terms = Column(JSON, nullable=True)
    member_price_claimed = Column(Boolean, nullable=True)
    subscription_offer_claimed = Column(Boolean, nullable=True)

    # Ground truth from the Deal Engine.
    ground_truth_true_cost = Column(Float, nullable=True)
    ground_truth_applied_deals = Column(JSON, nullable=True)
    ground_truth_confidence = Column(Float, nullable=True)
    user_tier_name = Column(Text, nullable=True)

    # Computed Rung-0 fidelity metrics.
    net_price_reflected = Column(Boolean, nullable=True, comment="M2")
    net_price_accuracy = Column(Boolean, nullable=True, comment="M12")
    term_fidelity = Column(Float, nullable=True, comment="M13")
    member_price_reflected = Column(Boolean, nullable=True, comment="M16")

    status = Column(Text, nullable=False, default="scored", server_default="scored")
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    run = relationship("SoaRun", back_populates="incentive_scores")
    entity = relationship("SoaEntity")
    scope_sku = relationship("SoaScopeSku", back_populates="incentive_scores")


# ---------------------------------------------------------------------------
# 9. soa_query_generation_jobs — AI-powered study generation jobs
# ---------------------------------------------------------------------------

class SoaQueryGenerationJob(Base):
    __tablename__ = 'soa_query_generation_jobs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    study_type = Column(String, nullable=False, unique=True)
    study_name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    target_count = Column(Integer, nullable=False)
    created_count = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default='pending')
    error_message = Column(Text, nullable=True)
    organization_id = Column(
        Integer,
        ForeignKey('organizations.id'),
        nullable=False,
    )
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'complete', 'failed')",
            name='ck_generation_jobs_status',
        ),
        Index('ix_generation_jobs_status', 'status'),
        Index('ix_soa_query_generation_jobs_organization_id', 'organization_id'),
    )


# ---------------------------------------------------------------------------
# 10. organizations — multi-tenant organization registry
# ---------------------------------------------------------------------------

class Organization(Base):
    __tablename__ = 'organizations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# 11. organization_members — membership mapping (user_id → organization)
# ---------------------------------------------------------------------------

class OrganizationMember(Base):
    __tablename__ = 'organization_members'

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(
        Integer,
        ForeignKey('organizations.id'),
        nullable=False,
    )
    user_id = Column(String, nullable=False)
    email = Column(String, nullable=False)
    role = Column(String, nullable=False, default='member')
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'member')",
            name='ck_org_members_role',
        ),
        UniqueConstraint(
            'organization_id', 'user_id',
            name='uq_org_members_org_user',
        ),
        Index('ix_org_members_user_id', 'user_id'),
    )
