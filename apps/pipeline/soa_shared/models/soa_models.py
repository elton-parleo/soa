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
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base
from .merchant_ref import Merchant  # noqa: F401 — ensures Merchant is mapped


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
            "category IN ('Skincare','Makeup','Fragrance','Haircare','Cross-Category','Grooming','Oral Care')",
            name="ck_soa_queries_category",
        ),
        CheckConstraint(
            "stage IN ('Research','Comparison','Ready to Buy')",
            name="ck_soa_queries_stage",
        ),
        CheckConstraint(
            "specificity IN ('Broad','Mid','Narrow')",
            name="ck_soa_queries_specificity",
        ),
        CheckConstraint(
            "persona IN ('Casual / Gift Buyer','Value-Conscious','Beauty Enthusiast','Problem-Skin Sufferer','Eco-Conscious / Minimalist','Oral Health Symptom Sufferer')",
            name="ck_soa_queries_persona",
        ),
        CheckConstraint(
            "status IN ('Active','Paused','Retired')",
            name="ck_soa_queries_status",
        ),
        CheckConstraint(
            "study_pattern IN ('retailer','brand_at_retail','brand_vs_brand')",
            name="ck_soa_queries_study_pattern",
        ),
        Index("ix_soa_queries_category_stage_status", "category", "stage", "status"),
        Index("ix_soa_queries_study_type", "study_type"),
        Index("ix_soa_queries_study_pattern", "study_pattern"),
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
        Index("ix_soa_cycles_study_type", "study_type"),
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
# 5. soa_runs
# ---------------------------------------------------------------------------

class SoaRun(Base):
    __tablename__ = "soa_runs"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('chatgpt','perplexity','gemini','claude')",
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
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    cycle = relationship("SoaCycle", back_populates="runs")
    query = relationship("SoaQuery", back_populates="runs")
    coded_mentions = relationship("SoaCodedMention", back_populates="run")
    other_mentions = relationship("SoaOtherMention", back_populates="run")


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
