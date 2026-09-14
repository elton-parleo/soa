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
    QUERY_EXPECTED_INCENTIVES,
)
from soa_shared.expected_answers import (
    EXPECTATION_OUTCOMES,
    QUERY_PROVENANCES,
    QUERY_TIERS,
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
        CheckConstraint(
            f"expected_incentive IS NULL OR expected_incentive IN {_in_list(QUERY_EXPECTED_INCENTIVES)}",
            name="ck_soa_queries_expected_incentive",
        ),
        # NULL is the normal state, not a violation: it is every query
        # generated without a syndicated brand, which is every query that
        # existed before the tiers did.
        CheckConstraint(
            f"tier IS NULL OR tier IN {_in_list(QUERY_TIERS)}",
            name="ck_soa_queries_tier",
        ),
        CheckConstraint(
            f"provenance IS NULL OR provenance IN {_in_list(QUERY_PROVENANCES)}",
            name="ck_soa_queries_provenance",
        ),
        Index("ix_soa_queries_category_stage_status", "category", "stage", "status"),
        Index("ix_soa_queries_study_type", "study_type"),
        Index("ix_soa_queries_study_pattern", "study_pattern"),
        Index("ix_soa_queries_organization_id", "organization_id"),
        # The report segments by (study, tier); the study_type index
        # above cannot serve that on its own.
        Index("ix_soa_queries_study_type_tier", "study_type", "tier"),
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
    expected_incentive = Column(
        Text,
        nullable=True,
        comment="Low/Mixed/High — whether a consumer at this stage/persona expects price/promo info in a good answer. Set by curation/seed.",
    )
    new_customer = Column(
        Boolean,
        nullable=True,
        comment="True if this persona is a new/first-time customer. Null = unconstrained.",
    )

    # ─── Syndicated-brand grounding ───────────────────────────────────
    #
    # All four are NULL on every query generated without a syndicated
    # brand — which is every query that existed before these columns did.
    # NULL is the untouched state, and no backfill invents one: a query
    # written with no brand in view has no tier it belongs to, and
    # labelling it would make the report's tier segmentation a fiction.
    #
    # See docs/expected-answer-vocabulary.md and
    # soa_shared/expected_answers.py.

    tier = Column(
        Text,
        nullable=True,
        comment=(
            "Which syndicated-brand tier this question belongs to: "
            "brand_direct, catalog_accuracy, value_incentives, "
            "category_control. NULL for a study generated without a brand."
        ),
    )

    expected_answer = Column(
        JSON,
        nullable=True,
        comment=(
            "The typed expectation a correct answer must contain — one of "
            "the seven shapes in soa_shared/expected_answers.py, never free "
            "text. NULL means Layer 2 does not score this question; Layer 1 "
            "mention coding runs on it either way. category_control questions "
            "deliberately carry none."
        ),
    )

    provenance = Column(
        Text,
        nullable=True,
        comment=(
            "How this question came to exist: 'catalog' (template-built from "
            "the published record, no AI), 'ai_from_catalog' (written by AI "
            "with the catalog as context), 'ai' (written by AI, ungrounded)."
        ),
    )

    source_ref = Column(
        JSON,
        nullable=True,
        comment=(
            "What the expectation was read from: {merchant_slug, listing_id, "
            "product_id, variant_id | offer_id, published_at}. published_at is "
            "the record's, not this row's — it is what a later comparison "
            "says the claim was made against, and it is what phase 2's "
            "publish/approval markers will be plotted from without a re-run."
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
        CheckConstraint(
            "cycle_mode IN ('query','truecost')",
            name="ck_soa_cycles_cycle_mode",
        ),
        CheckConstraint(
            "prior_cycle_id IS NULL OR prior_cycle_id != id",
            name="ck_soa_cycles_prior_cycle_not_self",
        ),
        Index("ix_soa_cycles_study_type", "study_type"),
        Index("ix_soa_cycles_organization_id", "organization_id"),
        Index("ix_soa_cycles_source_lite_request_id", "source_lite_request_id"),
        Index("ix_soa_cycles_prior_cycle_id", "prior_cycle_id"),
        Index("ix_soa_cycles_study_series_id", "study_series_id"),
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

    source_lite_request_id = Column(
        Integer,
        ForeignKey("soa_lite_requests.id"),
        nullable=True,
        comment=(
            "Set when this cycle was created as the Full Analysis "
            "continuation of a SoA Lite audit run. Null for every cycle "
            "created the ordinary way — never backfilled onto old cycles."
        ),
    )
    study_series_id = Column(
        Text,
        nullable=True,
        comment=(
            "Free-text id shared by every cycle in a recurring study "
            "series (e.g. an audit and the Full Analysis cycles run off "
            "it monthly/quarterly). Null means this cycle is not part of "
            "a tracked series."
        ),
    )
    prior_cycle_id = Column(
        Integer,
        ForeignKey("soa_cycles.id"),
        nullable=True,
        comment=(
            "The cycle this one continues from in its study_series_id "
            "series — e.g. the audit's own cycle, for the first Full "
            "Analysis run off it. Null for a series' first cycle."
        ),
    )

    extraction_validation = Column(
        JSON,
        nullable=True,
        comment=(
            "Hand-validation of the Layer 2 extractor for this cycle: "
            "{sample_size, agreed, agreement_rate, validated_by, "
            "validated_at, notes}. NULL until a human records it, and the "
            "report renders it as 'not validated' rather than as a number. "
            "Never estimated and never inferred from the extractor's own "
            "confidence — a validated agreement rate nobody validated is the "
            "single most damaging number this system could print. Written by "
            "scripts/validate_extractions.py --record."
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
    findings = relationship("SoaFinding", back_populates="cycle")
    recommendations = relationship("SoaRecommendation", back_populates="cycle")


# ---------------------------------------------------------------------------
# 3b. soa_cycle_shares / soa_public_share_views — shareable Full Analysis
# report links. A dedicated table (not nullable columns on SoaCycle) so a
# cycle can carry more than one link over time (rotation) without a future
# migration, and a revoke never has to guess which of several links it's
# revoking. token uses the exact same scheme as SoaLiteRequest.token
# (uuid4 hex, unique, unguessable) — see app/services/share_tokens.py.
# ---------------------------------------------------------------------------

class SoaCycleShare(Base):
    __tablename__ = "soa_cycle_shares"
    __table_args__ = (
        Index("ix_soa_cycle_shares_cycle_id", "cycle_id"),
    )

    id = Column(Integer, primary_key=True)
    cycle_id = Column(Integer, ForeignKey("soa_cycles.id"), nullable=False)
    token = Column(
        Text,
        unique=True,
        nullable=False,
        comment="Unguessable public access key (uuid4 hex, generated app-side).",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(String, nullable=True)
    revoked_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="Null while active. Set once, never cleared — revoking is permanent; sharing again creates a new row/token.",
    )
    expires_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="Optional owner-set expiry. Null means the link never expires on its own.",
    )

    cycle = relationship("SoaCycle")


class SoaPublicShareView(Base):
    """Append-only read log for the public endpoint's own per-IP rate
    limit — mirrors SoaLiteRequest doubling as its own rate-limit log in
    public_lite.py::_enforce_rate_limits. No domain meaning beyond "this
    ip_hash read this share at this time"."""

    __tablename__ = "soa_public_share_views"
    __table_args__ = (
        Index("ix_soa_public_share_views_ip_hash_created_at", "ip_hash", "created_at"),
        Index("ix_soa_public_share_views_share_id", "share_id"),
    )

    id = Column(Integer, primary_key=True)
    share_id = Column(
        Integer, ForeignKey("soa_cycle_shares.id"), nullable=True,
        comment="Null when the token that generated this view row could not be resolved to a share.",
    )
    ip_hash = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


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
    member_value_cited = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment=(
            "Stage 16 (Part 5): true whenever the response indicates ANY "
            "member-exclusive/loyalty-program value for this entity, concrete "
            "or not — broader than deal_cited/deal_types, which deliberately "
            "exclude vague program-existence mentions. Coded independently "
            "from deal_cited by the same pass-1 LLM call (parser/prompts.py)."
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
# 6b. soa_price_observations — pass-2 output, observation grain (one row per
# extracted price/offer observation, not one per entity — a response citing
# one entity's price at three retailers yields three rows). Additive: pass
# 1's soa_coded_mentions is never touched, and pass 2 does not re-extract
# mentioned/position/strength/deal_cited at all (separate, narrower prompt —
# see parser/prompts_v2.py) so there is nothing for those fields to drift
# from, by construction. See apps/pipeline/scripts/recode_cycle_pass2.py.
#
# Supersedes an earlier, wrongly-scoped soa_coded_mentions_v2 table (one
# scalar price/merchant pair per entity per run) from the same session —
# that table is left in place, orphaned/unused, rather than dropped.
# ---------------------------------------------------------------------------

class SoaPriceObservation(Base):
    __tablename__ = "soa_price_observations"
    __table_args__ = (
        CheckConstraint(
            "attribution_status IN ('mapped','unmapped','unattributed','brand_self_reference')",
            name="ck_soa_price_observations_attribution_status",
        ),
        Index("ix_soa_price_observations_run_entity", "run_id", "entity_id"),
        Index("ix_soa_price_observations_entity_id", "entity_id"),
        Index("ix_soa_price_observations_attribution_status", "attribution_status"),
    )

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("soa_runs.id"), nullable=False, index=True)
    entity_id = Column(Integer, ForeignKey("soa_entities.id"), nullable=False, index=True)

    stated_price = Column(Float, nullable=True)
    claimed_net_price = Column(Float, nullable=True)
    claimed_discount_value = Column(Float, nullable=True)
    claimed_discount_pct = Column(Float, nullable=True)
    claimed_terms = Column(JSON, nullable=True)
    member_price_claimed = Column(Boolean, nullable=True)
    subscription_offer_claimed = Column(Boolean, nullable=True)

    merchant_name = Column(
        Text,
        nullable=True,
        comment="Retailer/seller name as stated by the agent, verbatim. Null if this observation names no seller.",
    )
    merchant_slug = Column(
        Text,
        nullable=True,
        comment="merchant_name resolved against merchants.slug. Only set when attribution_status='mapped'.",
    )
    attribution_status = Column(
        Text,
        nullable=False,
        comment=(
            "'mapped' — resolved to a known, trustworthy merchant. "
            "'unmapped' — merchant_name set but not a known merchant. "
            "'unattributed' — no merchant_name at all, no retailer signal in the response. "
            "'brand_self_reference' — merchant_name resolved to the entity's OWN brand's "
            "merchant slug (e.g. Pampers entity -> 'pampers') without an explicit D2C signal "
            "in the response — likely the coder confusing the discussed brand for a retailer. "
            "merchant_slug is null for this status; the raw merchant_name is kept for audit."
        ),
    )

    evidence = Column(Text, nullable=True)
    coding_pass_version = Column(Integer, nullable=False, default=2, server_default="2")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    run = relationship("SoaRun")
    entity = relationship("SoaEntity")


# ---------------------------------------------------------------------------
# 6c. soa_pass2_coding_log — sentinel marking a run as pass-2-processed,
# independent of whether that run produced any soa_price_observations /
# soa_citations rows. A run with zero price observations and zero
# citations is a legitimate, common result (e.g. a pure ingredient-
# comparison response) — without this marker, ResponseCoderV2's
# idempotency check has nothing to find and re-queries the API on every
# re-run of the same run_id.
# ---------------------------------------------------------------------------

class SoaPass2CodingLog(Base):
    __tablename__ = "soa_pass2_coding_log"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "coding_pass_version",
            name="uq_soa_pass2_coding_log_run_version",
        ),
    )

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("soa_runs.id"), nullable=False, index=True)
    coding_pass_version = Column(Integer, nullable=False, default=2, server_default="2")
    observations_written = Column(Integer, nullable=False, default=0, server_default="0")
    citations_written = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    run = relationship("SoaRun")


# ---------------------------------------------------------------------------
# 6d. soa_citations — per-run cited/linked sources extracted from
# raw_response text at coding time. No fetching of the cited URLs; the
# domain and context are derived from the response text alone. Raw
# material for a future VIS-02 detector.
# ---------------------------------------------------------------------------

class SoaCitation(Base):
    __tablename__ = "soa_citations"
    __table_args__ = (
        Index("ix_soa_citations_run_id", "run_id"),
        Index("ix_soa_citations_domain", "domain"),
    )

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("soa_runs.id"), nullable=False, index=True)
    url = Column(Text, nullable=False)
    domain = Column(Text, nullable=False)
    context = Column(
        Text,
        nullable=True,
        comment="Short phrase describing which claim/product this source is attached to, when the response structure supports it.",
    )
    coding_pass_version = Column(Integer, nullable=False, default=2, server_default="2")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    run = relationship("SoaRun")


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
        CheckConstraint(
            "scoring_grain IN ('legacy','observation')",
            name="ck_soa_incentive_scores_scoring_grain",
        ),
        CheckConstraint(
            "measurement_status IS NULL OR measurement_status IN ('measured','unmeasured')",
            name="ck_soa_incentive_scores_measurement_status",
        ),
        Index("ix_soa_incentive_scores_run_id", "run_id"),
        Index("ix_soa_incentive_scores_entity_id", "entity_id"),
        Index("ix_soa_incentive_scores_status", "status"),
        Index("ix_soa_incentive_scores_scoring_grain", "scoring_grain"),
        Index("ix_soa_incentive_scores_measurement_status", "measurement_status"),
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
    # No FK constraint — merchants is owned by /supply. For scoring_grain=
    # 'observation' rows this is resolved from the coded merchant_slug, not
    # defaulted from soa_entities.merchant_id (see scoring/observation_scorer.py).
    merchant_id = Column(Integer, nullable=True, index=True)

    # New for observation-grain scoring — additive, null on the 485 legacy
    # rows (scoring_grain='legacy').
    merchant_slug = Column(Text, nullable=True, comment="Real resolved retailer slug, e.g. 'target'. Null on legacy rows.")
    price_observation_id = Column(
        Integer,
        ForeignKey("soa_price_observations.id"),
        nullable=True,
        index=True,
        comment="Traces back to the coding-stage observation this row scored. Null on legacy rows.",
    )
    scoring_grain = Column(
        Text,
        nullable=False,
        default="legacy",
        server_default="legacy",
        comment="'legacy' — pre-observation-grain rows (brand x category, one per entity per run). 'observation' — one row per (entity, merchant, run, observation).",
    )

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
    ground_truth_available_deals = Column(
        JSON,
        nullable=True,
        comment="result.available_deals — the not-applied candidate deals. Together with ground_truth_applied_deals this is a complete partition of every deal the engine evaluated; both empty means the engine had none at all (see measurement_status).",
    )
    ground_truth_confidence = Column(Float, nullable=True)
    user_tier_name = Column(Text, nullable=True)

    measurement_status = Column(
        Text,
        nullable=True,
        comment=(
            "'measured' — the engine evaluated >=SOA_MEASUREMENT_MIN_DEALS_EVALUATED deals "
            "(applied_deals + available_deals) for this merchant/category, so ground_truth_true_cost "
            "carries independent signal. 'unmeasured' — the engine had no deal data at all and echoed "
            "the input price back as true_cost, which would otherwise look like a perfect 0% gap. "
            "Null on rows where status != 'scored' (no ground truth was ever fetched) and on legacy-grain "
            "rows scored before this gate existed. Net Price Accuracy / Offer Completeness and "
            "TVD-01/TVD-03 must read measured rows only — see finding_detector.py."
        ),
    )

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
    price_observation = relationship("SoaPriceObservation")
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

    # ─── The study brief ──────────────────────────────────────────────
    #
    # What the Create Study with AI modal collected. The API and the
    # pipeline share nothing but this table, so a structured input that
    # is not stored here is one the generator can never see.
    #
    # All nullable, and study_pattern doubles as the worker's path
    # discriminator: NULL means the job predates the brief (or came from
    # a client sending only name/description/target_count), and it is
    # generated exactly as it would have been when it was queued. A job
    # runs under the rules it was created under.
    study_pattern = Column(String, nullable=True)
    # Names written into question text. No roles — the
    # primary-versus-competitor decision belongs to soa_cycle_entities
    # at cycle creation, not to a generation request.
    retailer_names = Column(JSON, nullable=True)
    allowed_categories = Column(JSON, nullable=True)
    # {stage: count}. target_count above is its sum; the modal derives
    # one from the other so they cannot disagree.
    stage_targets = Column(JSON, nullable=True)
    rotate_named_retailer = Column(Boolean, nullable=True)
    naming_rule_enabled = Column(Boolean, nullable=True)
    personas = Column(JSON, nullable=True)
    specificity_mode = Column(String, nullable=True)

    # The return leg: what was generated, what was dropped automatically,
    # and what the advisory review passes flagged. Stored rather than
    # returned from POST /studies/generate because rows never reach the
    # client before persistence — that response is sent before a single
    # query exists. generation-status reads it back off this row.
    provenance = Column(JSON, nullable=True)

    # ─── Syndicated brand ─────────────────────────────────────────────
    #
    # This row IS the study's definition — there is no soa_studies table;
    # a study is a study_type, and this is the row that made one. So the
    # brand a study is grounded in, and which tiers were enabled when it
    # was generated, live here rather than on soa_cycles (a cycle is a
    # RUN of a study, and two runs of one study must not be able to
    # disagree about what the study is).
    #
    # NULL/absent means the toggle was off: an ordinary study, generated
    # exactly as it would have been before these columns existed.

    syndicated_merchant = Column(
        String,
        nullable=True,
        comment=(
            "TrueSync merchant slug the study is grounded in, e.g. "
            "'wiggle-and-snug'. NULL when the syndicated-brand toggle was off."
        ),
    )

    tier_config = Column(
        JSON,
        nullable=True,
        comment=(
            "Which tiers were enabled and how they were built: "
            "{<tier>: {enabled, count, expected_nulls, sampled_variants?}}. "
            "sampled_variants records exactly which variants the "
            "catalog_accuracy cap selected, so a regeneration can be compared "
            "against what was asked last time rather than guessed at."
        ),
    )

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


# ---------------------------------------------------------------------------
# 12. soa_playbook — curated remediation library backing the Actions feature.
# Global reference table, not organization-scoped. Seeded from
# docs/playbook_v1.md; see apps/pipeline/scripts/seed_playbook.py.
# ---------------------------------------------------------------------------

class SoaPlaybook(Base):
    __tablename__ = "soa_playbook"
    __table_args__ = (
        CheckConstraint(
            "owner IN ('brand','retailer','joint')",
            name="ck_soa_playbook_owner",
        ),
        CheckConstraint(
            "effort IN ('low','medium','high')",
            name="ck_soa_playbook_effort",
        ),
        CheckConstraint(
            "detector_status IN ('implemented','not_implemented')",
            name="ck_soa_playbook_detector_status",
        ),
        Index("ix_soa_playbook_pillar", "pillar"),
    )

    play_id = Column(
        Text,
        primary_key=True,
        comment="Stable key referenced by soa_findings/soa_recommendations. e.g. 'TVD-02'",
    )
    pillar = Column(Text, nullable=False, comment="Visibility | Accessibility | True Value Delivery | Fidelity")
    failure_mode = Column(Text, nullable=False)
    detection_trigger = Column(
        Text,
        nullable=False,
        comment="Human-readable rule from the playbook doc. The machine-enforced version lives in detector_thresholds.yaml.",
    )
    dimensions = Column(JSON, nullable=False, comment="List of SoA dimension names this play moves, e.g. ['Presence']")
    owner = Column(Text, nullable=False)
    play_text = Column(Text, nullable=False)
    mechanism_text = Column(Text, nullable=False)
    effort = Column(Text, nullable=False)
    expected_impact_text = Column(Text, nullable=False)
    evidence_spec = Column(Text, nullable=False)
    detector_status = Column(
        Text,
        nullable=False,
        default="not_implemented",
        server_default="not_implemented",
        comment="'implemented' — a detector function exists for this play_id. 'not_implemented' — seeded but skipped by the detector.",
    )
    active = Column(Boolean, nullable=False, default=True, server_default="true")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    findings = relationship("SoaFinding", back_populates="play")
    recommendations = relationship("SoaRecommendation", back_populates="play")


# ---------------------------------------------------------------------------
# 13. soa_findings — deterministic detector output for a completed cycle.
# Read-only over existing metrics/run tables; the detector only ever writes
# here. See apps/pipeline/services/finding_detector.py.
# ---------------------------------------------------------------------------

class SoaFinding(Base):
    __tablename__ = "soa_findings"
    __table_args__ = (
        CheckConstraint(
            "severity >= 0.0 AND severity <= 1.0",
            name="ck_soa_findings_severity_range",
        ),
        Index("ix_soa_findings_cycle_id", "cycle_id"),
        Index("ix_soa_findings_cycle_play", "cycle_id", "play_id"),
        Index("ix_soa_findings_entity_id", "entity_id"),
    )

    id = Column(Integer, primary_key=True)
    cycle_id = Column(Integer, ForeignKey("soa_cycles.id"), nullable=False, index=True)
    entity_id = Column(
        Integer,
        ForeignKey("soa_entities.id"),
        nullable=True,
        comment="Null for retailer-level / cycle-level findings (e.g. ACC-04).",
    )
    play_id = Column(Text, ForeignKey("soa_playbook.play_id"), nullable=False)
    dimension = Column(Text, nullable=False)
    surface = Column(Text, nullable=True, comment="Platform value, e.g. 'chatgpt'. Null when the finding is not surface-sliced.")
    persona = Column(Text, nullable=True)
    stage = Column(Text, nullable=True)
    severity = Column(Float, nullable=False, comment="Normalized distance past threshold, clamped 0-1.")
    cells_affected = Column(Integer, nullable=False, comment="Count of entity x surface x persona cells where the play fired.")
    metric_snapshot = Column(JSON, nullable=False, comment="Exact metric values that tripped the rule.")
    evidence_run_ids = Column(JSON, nullable=False, default=list, comment="Run IDs backing metric_snapshot. Empty list if no linkage exists for this metric.")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    cycle = relationship("SoaCycle", back_populates="findings")
    entity = relationship("SoaEntity")
    play = relationship("SoaPlaybook", back_populates="findings")


# ---------------------------------------------------------------------------
# 14. soa_recommendations — findings grouped and prioritized by play, one
# per (cycle, play). See apps/pipeline/services/recommendation_mapper.py.
# ---------------------------------------------------------------------------

class SoaRecommendation(Base):
    __tablename__ = "soa_recommendations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','accepted','in_progress','done','dismissed')",
            name="ck_soa_recommendations_status",
        ),
        UniqueConstraint(
            "cycle_id", "play_id",
            name="uq_soa_recommendations_cycle_play",
        ),
        Index("ix_soa_recommendations_cycle_id", "cycle_id"),
    )

    id = Column(Integer, primary_key=True)
    cycle_id = Column(Integer, ForeignKey("soa_cycles.id"), nullable=False, index=True)
    play_id = Column(Text, ForeignKey("soa_playbook.play_id"), nullable=False)
    finding_ids = Column(JSON, nullable=False, comment="List of soa_findings.id aggregated into this recommendation.")
    priority_score = Column(Float, nullable=False)
    status = Column(Text, nullable=False, default="proposed", server_default="proposed")
    suppressed = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True for composite plays (e.g. TVD-07) suppressed in favor of their constituent plays.",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    cycle = relationship("SoaCycle", back_populates="recommendations")
    play = relationship("SoaPlaybook", back_populates="recommendations")


# ---------------------------------------------------------------------------
# 15. soa_lite_requests — SoA Lite orchestration state machine and
# lead-capture record. Backs the public, unauthenticated "enter a brand,
# get a report" flow: one row per visitor submission, driving generation
# and run of a fixed-size (LITE_QUERY_COUNT) study through the existing pipeline, then gating
# the resulting report behind `token`. All rows live under the dedicated
# 'Parleo Lead Gen' organization — see soa_shared/org_helpers.py.
# ---------------------------------------------------------------------------

# Stage 14 (S2): single source of truth for soa_lite_requests.status —
# the CheckConstraint below is built FROM this tuple, and worker.py/
# public_lite.py import the named constants for every status WRITE, so
# a status the code writes but the DB constraint doesn't allow (the
# Stage 13 incident: 'identifying_competitors' shipped in code before
# the constraint was updated to match, crash-looping the same stuck
# row on every poll) fails a CI parity test instead of reaching prod.
LITE_STATUS_PENDING = "pending"
LITE_STATUS_IDENTIFYING_COMPETITORS = "identifying_competitors"
LITE_STATUS_GENERATING = "generating"
LITE_STATUS_RUNNING = "running"
LITE_STATUS_COMPLETE = "complete"
LITE_STATUS_FAILED = "failed"
LITE_STATUSES = (
    LITE_STATUS_PENDING,
    LITE_STATUS_IDENTIFYING_COMPETITORS,
    LITE_STATUS_GENERATING,
    LITE_STATUS_RUNNING,
    LITE_STATUS_COMPLETE,
    LITE_STATUS_FAILED,
)


class SoaLiteRequest(Base):
    __tablename__ = "soa_lite_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in LITE_STATUSES) + ")",
            name="ck_soa_lite_requests_status",
        ),
        Index("ix_soa_lite_requests_status", "status"),
        Index("ix_soa_lite_requests_ip_hash_created_at", "ip_hash", "created_at"),
        Index("ix_soa_lite_requests_organization_id", "organization_id"),
    )

    id = Column(Integer, primary_key=True)

    token = Column(
        Text,
        unique=True,
        nullable=False,
        comment=(
            "Unguessable public access key (uuid4 hex, generated app-side). "
            "Used to fetch the gated report with no auth."
        ),
    )

    email = Column(
        Text,
        nullable=True,
        comment=(
            "Lead capture. Null until the visitor submits their email to "
            "unlock the full report."
        ),
    )

    brand_name = Column(Text, nullable=False, comment="Raw visitor input, unresolved.")

    competitor_names = Column(
        JSON,
        nullable=True,
        comment=(
            "List of raw competitor name strings — up to 2 as entered by the "
            "visitor, topped up to 5 by Stage 13 worker-side auto-generation. "
            "See competitor_source for provenance."
        ),
    )

    competitor_source = Column(
        Text,
        nullable=True,
        comment=(
            "Stage 13: provenance of competitor_names — 'generated' (all "
            "from ChatGPT), 'manual' (all visitor-entered), 'mixed' (both), "
            "or 'none' (no competitors at all). Null until competitor "
            "generation runs (process_lite_requests, ahead of query "
            "generation)."
        ),
    )

    brand_entity_id = Column(
        Integer,
        ForeignKey("soa_entities.id"),
        nullable=True,
        comment="Resolved during processing. Null until entity resolution runs.",
    )

    competitor_entity_ids = Column(
        JSON,
        nullable=True,
        comment="List of resolved soa_entities.id values, parallel to competitor_names.",
    )

    study_type = Column(
        Text,
        nullable=True,
        comment=(
            "'lite-{first 8 chars of token}'. Stamped when generation starts; "
            "matches study_type on the generated soa_queries/soa_cycles rows."
        ),
    )

    store_url = Column(
        Text,
        nullable=True,
        comment=(
            "Visitor-supplied (or derived) storefront URL, used as input to the "
            "Agent Scan crawl. Null for submissions that don't include one — the "
            "scan is degraded/skipped in that case, never blocking the report."
        ),
    )

    cycle_id = Column(
        Integer,
        ForeignKey("soa_cycles.id"),
        nullable=True,
        comment="Set once the cycle row is created for this request.",
    )

    status = Column(
        Text,
        nullable=False,
        default="pending",
        server_default="pending",
        comment="pending -> generating -> running -> complete, or failed at any step.",
    )

    error_message = Column(Text, nullable=True)

    events = Column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
        comment=(
            "Append-only run-manifest event log: [{seq, ts, kind: "
            "'log'|'done'|'state', task, text, chips?}]. task is one of "
            "the fixed TASK registry (apps/pipeline/lite_events.py) — "
            "crawl, probe_membership, probe_revenue, probe_fetch, "
            "competitors, queries, scoring, report. Written incrementally "
            "by worker.py/run_orchestrator.py/orchestrator/pipeline.py as "
            "each stage progresses; log-kind events are capped at the "
            "most recent 200 (done/state events are never trimmed) — see "
            "lite_events.py::emit_event. Purely additive: the status "
            "endpoint (apps/api/app/routers/public_lite.py) passes this "
            "straight through, and a pre-this-stage row simply has '[]'."
        ),
    )

    report_email_sent_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "Stage 12 (E3): set once the 'your report is ready' email has "
            "been sent. Null means not sent yet — checked alongside "
            "status='complete' and email IS NOT NULL by "
            "_sweep_lite_completions on every pass, so a request that "
            "completes before an email is on file, or a transient send "
            "failure, is retried on a later pass rather than lost."
        ),
    )

    lead_notified_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "Set once the internal 'new lead' notification has been sent "
            "for the address currently in `email` (apps/api/app/services/"
            "lead_notification_email.py). Null means not notified yet. "
            "Dedupes the notification against PATCH /email retries: "
            "set_lite_email only sends when the stored email actually "
            "changed (NULL -> something, or a different address), and "
            "stamps this on a successful send — a failed send leaves it "
            "NULL rather than silently claiming the lead was reported."
        ),
    )

    ip_hash = Column(
        Text,
        nullable=True,
        comment="sha256 of the client IP, for rate limiting. Raw IP is never stored.",
    )

    organization_id = Column(
        Integer,
        ForeignKey("organizations.id"),
        nullable=False,
        comment="Always the dedicated 'Parleo Lead Gen' organization.",
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    brand_entity = relationship("SoaEntity", foreign_keys=[brand_entity_id])
    # Explicit foreign_keys: soa_cycles.source_lite_request_id now creates
    # a second FK path between these two tables (the Full Analysis
    # continuation link, the reverse direction of this one) — without
    # this, SQLAlchemy can no longer infer which FK this relationship
    # means and raises AmbiguousForeignKeysError at mapper configuration.
    cycle = relationship("SoaCycle", foreign_keys=[cycle_id])
    scan_result = relationship(
        "SoaLiteScanResult", back_populates="lite_request", uselist=False,
    )


# ---------------------------------------------------------------------------
# 16. soa_lite_scan_results — Agent Scan crawl output for a SoA Lite
# request. One row per soa_lite_requests row (1:1, optional — a request
# with no store_url never gets one). Written by the pure, self-contained
# apps/pipeline/scan/ engine (see engine.py::run_scan); nothing in this
# table blocks Lite completion — see worker.py's terminal-state handling.
# ---------------------------------------------------------------------------

class SoaLiteScanResult(Base):
    __tablename__ = "soa_lite_scan_results"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','complete','blocked','failed','skipped')",
            name="ck_soa_lite_scan_results_status",
        ),
        CheckConstraint(
            "lite_request_id IS NOT NULL OR cycle_id IS NOT NULL",
            name="ck_soa_lite_scan_results_owned",
        ),
        UniqueConstraint(
            "lite_request_id",
            name="uq_soa_lite_scan_results_lite_request_id",
        ),
    )

    id = Column(Integer, primary_key=True)

    lite_request_id = Column(
        Integer,
        ForeignKey("soa_lite_requests.id"),
        nullable=True,
        unique=True,
        index=True,
        comment=(
            "Null for a Full-Analysis-launched crawl with no owning lite "
            "request (cycle_id is set instead) — see "
            "ck_soa_lite_scan_results_owned. Always set for the lite path's "
            "own scan, exactly as before this column became nullable."
        ),
    )

    cycle_id = Column(
        Integer,
        ForeignKey("soa_cycles.id"),
        nullable=True,
        index=True,
        comment=(
            "The cycle this crawl is attached to — set for every scan "
            "going forward (both lite-owned and Full-Analysis-owned). "
            "lite_request_id remains the lite path's own FK, untouched; "
            "this column is what lets a paid cycle with no lite_request "
            "at all carry a crawl too."
        ),
    )

    input_url = Column(
        Text,
        nullable=True,
        comment="Storefront URL as submitted/derived — mirrors soa_lite_requests.store_url at scan time.",
    )

    status = Column(
        Text,
        nullable=False,
        default="pending",
        server_default="pending",
        comment=(
            "pending -> running -> complete, or blocked/failed/skipped. Terminal "
            "states are complete/blocked/failed/skipped — see engine.py::run_scan."
        ),
    )

    total_score = Column(
        Integer,
        nullable=True,
        comment="0-100. Null until status='complete'.",
    )

    integrity_capped = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True when dishonest pricing signals (fake 'was' prices) capped total_score at 59.",
    )

    dimensions = Column(
        JSON,
        nullable=True,
        comment="{code: {score, max, evidence: [...], fix}} for all 8 dimensions. Null until complete.",
    )

    pages_fetched = Column(
        JSON,
        nullable=True,
        comment="[{url, status}] — every page the scan attempted to fetch.",
    )

    membership_probe = Column(
        JSON,
        nullable=True,
        comment=(
            "Stage 16 (Part 4): {result: 'yes'|'no'|'unknown', raw_evidence: str|null} "
            "from a single out-of-band OpenAI call (apps/pipeline/generation/"
            "membership_probe.py). Metrically invisible — not one of the 12 tracked "
            "queries, excluded from every mention/citation denominator. Feeds P3's "
            "member_value applicability decision only (apps/api/app/services/"
            "lite_pillars.py::member_value_applicable)."
        ),
    )

    revenue_probe = Column(
        JSON,
        nullable=True,
        comment=(
            "Part 5 (R1/R2): {annual_revenue_usd: number|null, basis: str|null, "
            "quote: str|null} from a single out-of-band OpenAI call (apps/pipeline/"
            "generation/revenue_probe.py), same never-throw/one-retry pattern as "
            "membership_probe above. Metrically invisible — not one of the 12 "
            "tracked queries, excluded from every mention/citation denominator. "
            "Feeds ONLY the exposure calculator's default revenue seed (apps/api/"
            "app/routers/public_lite.py); never affects any score."
        ),
    )

    fetch_probe = Column(
        JSON,
        nullable=True,
        comment=(
            "Part 2 (P1/P2), kind-aware (N4): {outcome: 'quoted_price'|"
            "'opened_no_price'|'could_not_access'|'inconclusive', url: str, "
            "kind: 'product_page'|'store_root'|null, price: str|null, "
            "quote: str|null, note: str|null} from a single out-of-band OpenAI "
            "Responses-API call with the web_search tool (apps/pipeline/"
            "generation/fetch_probe.py) — ChatGPT actually opening one sampled "
            "product URL. Same never-throw, ONE-call (no retry) pattern. "
            "Metrically invisible — not one of the LITE_QUERY_COUNT tracked "
            "queries, excluded from every mention/citation denominator. Feeds "
            "Price Truth evidence and the blocked/degraded banner (apps/api/"
            "app/services/lite_pillars.py, apps/api/app/routers/public_lite.py); "
            "never affects any score."
        ),
    )

    error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    lite_request = relationship("SoaLiteRequest", back_populates="scan_result")


class SoaDemoRequest(Base):
    """Leadgen session: 'Book your walkthrough' / 'Talk to us about
    TrueSync' CTAs on the audit landing + report, replacing a bare link
    to parleo.io. Written by apps/api/app/routers/public_demo.py via
    raw SQL (INSERT ... RETURNING), same as soa_lite_requests — the
    model here is the schema source of truth for Alembic, not an ORM
    write path."""
    __tablename__ = "soa_demo_requests"
    __table_args__ = (
        Index("ix_soa_demo_requests_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True)

    name = Column(Text, nullable=False)
    email = Column(Text, nullable=False)
    company = Column(Text, nullable=False)
    message = Column(Text, nullable=True, comment="Optional — the modal's Message field has no asterisk.")

    source = Column(
        Text,
        nullable=False,
        comment=(
            "Which CTA opened the modal — full_analysis_walkthrough, "
            "truesync, or landing_truesync. See apps/api/web/src/lite/"
            "demoRequestCtas.js, the single source for the CTA-to-source "
            "mapping."
        ),
    )
    page_url = Column(Text, nullable=False, comment="window.location.href at submit time.")
    brand_name = Column(Text, nullable=True, comment="Report-context submissions only — the audited brand.")
    report_token = Column(Text, nullable=True, comment="Report-context submissions only — links the notification email to the report.")

    ip_hash = Column(Text, nullable=True, comment="sha256(ip) — same convention as soa_lite_requests.ip_hash, never the raw IP.")

    notified_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Set once the Resend notification email sends successfully. Null means either not-yet-attempted or send failed — the row is the backstop, not a queue.",
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# 6d. soa_expectation_outcomes — Layer 2 output, one row per scored
# (question x surface x sample), i.e. one per soa_runs row whose query
# carries a typed expectation.
#
# Layer 1 (soa_coded_mentions) is untouched and runs on every tier; the
# tier tag on soa_queries is what segments it. Layer 2 runs ONLY where
# soa_queries.expected_answer is non-null, and it never re-derives
# mentioned/position/strength — there is nothing here for those to drift
# from, by construction, exactly as pass 2 is separated from pass 1.
#
# The grain is soa_runs, not a copy of it. A run row already stores
# raw_response permanently and is the unique (cycle, query, platform,
# run_number) slot, so `run_id` IS "question x surface x sample" and the
# answer text reached from it can never disagree with the answer that was
# scored. Storing a second copy of a multi-kilobyte answer beside every
# outcome would buy nothing except the chance of the two differing.
# ---------------------------------------------------------------------------

class SoaExpectationOutcome(Base):
    __tablename__ = "soa_expectation_outcomes"
    __table_args__ = (
        CheckConstraint(
            f"outcome IN {_in_list(EXPECTATION_OUTCOMES)}",
            name="ck_soa_expectation_outcomes_outcome",
        ),
        # One verdict per run. A re-score replaces the row rather than
        # appending a second one, so a rate can never double-count a run
        # that was scored twice.
        UniqueConstraint(
            "run_id", name="uq_soa_expectation_outcomes_run",
        ),
        Index("ix_soa_expectation_outcomes_query_id", "query_id"),
        Index("ix_soa_expectation_outcomes_cycle_tier", "cycle_id", "tier"),
        Index("ix_soa_expectation_outcomes_outcome", "outcome"),
    )

    id = Column(Integer, primary_key=True)

    run_id = Column(
        Integer, ForeignKey("soa_runs.id"), nullable=False, index=True,
        comment="The scored answer. soa_runs.raw_response is the stored text every rate traces back to.",
    )
    # Denormalised from the run's query and cycle so the aggregation reads
    # one table. They are copies of immutable facts (a run never changes
    # which query or cycle it belongs to), which is the only kind of
    # denormalisation that cannot drift.
    query_id = Column(Integer, ForeignKey("soa_queries.id"), nullable=False)
    cycle_id = Column(Integer, ForeignKey("soa_cycles.id"), nullable=False)
    platform = Column(Text, nullable=False, comment="The surface. Copied from the run.")
    tier = Column(Text, nullable=True, comment="Copied from the query at scoring time.")

    expected_answer = Column(
        JSON,
        nullable=False,
        comment=(
            "The expectation AS IT WAS when this outcome was decided. A copy, "
            "not a join: republishing the record rewrites the question's "
            "expectation, and an outcome that then read through to the new one "
            "would silently restate what it had compared against."
        ),
    )
    extraction = Column(
        JSON,
        nullable=False,
        comment=(
            "What the extraction pass transcribed, in the fixed schema from "
            "parser/expectation_prompts.py. Contains no verdict — no "
            "'correct', no 'matches'. The comparison that follows is ordinary "
            "deterministic Python, so a stored extraction is re-checkable, not "
            "merely re-runnable."
        ),
    )

    outcome = Column(
        Text, nullable=False,
        comment=(
            "exact | stale | wrong | absent | unscoreable. unscoreable is its "
            "own bucket and is never folded into wrong: 'the assistant was "
            "incorrect' and 'we could not tell what it said' are different "
            "facts, and merging them inflates the error rate with our own "
            "extraction failures."
        ),
    )
    outcome_reason = Column(
        Text, nullable=True,
        comment="One line of why, for the drill-down. Display only; nothing branches on it.",
    )

    domain_cited = Column(
        Boolean, nullable=True,
        comment=(
            "Whether the brand's own domain was among the answer's cited "
            "sources. Kept SEPARATE from the exact/wrong decision on a "
            "brand_mention expectation — 'did it know the brand' and 'did it "
            "send the shopper to the brand's own store' are different "
            "questions, and folding the second into the first loses the "
            "source-attribution measure the report reports. NULL where the "
            "surface exposes no sources at all."
        ),
    )
    source_attribution = Column(
        Text, nullable=True,
        comment="brand_domain | retailer | none — derived from the extraction's sources_cited.",
    )

    secondary_results = Column(
        JSON,
        nullable=True,
        comment=(
            "Outcomes for expectations the question did not ask about (the "
            "GTIN riding along on a price question). A bonus signal, "
            "deliberately outside the accuracy denominator: an assistant is "
            "not wrong for failing to recite an identifier nobody asked for."
        ),
    )

    record_published_at = Column(
        DateTime(timezone=True), nullable=True,
        comment=(
            "published_at of the record the expectation was read from — what "
            "the claim was compared against. Stored so phase 2 can plot "
            "outcomes against TrueSync publish/approval markers with no re-run."
        ),
    )
    matched_published_at = Column(
        DateTime(timezone=True), nullable=True,
        comment=(
            "For a 'stale' outcome, the published_at of the PRIOR record whose "
            "value the answer actually matched. NULL for every other outcome. "
            "This is what makes staleness attributable to a specific past "
            "publication rather than a general accusation of being behind."
        ),
    )

    extraction_model = Column(Text, nullable=True)
    scored_at = Column(DateTime(timezone=True), server_default=func.now())

    run = relationship("SoaRun")
