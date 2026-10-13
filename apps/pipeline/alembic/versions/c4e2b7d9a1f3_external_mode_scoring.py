"""external_mode_scoring

Revision ID: c4e2b7d9a1f3
Revises: a7c3e9f1b2d4
Create Date: 2026-10-13

Step 2B: external/brand mode scoring, surface fidelity, the full loop.

  soa_runs
    * platform admits chatgpt_api (OpenAI, no tools), gemini_api (Gemini, no
      grounding tool), aimode and copilot (consumer surfaces via SerpApi).
    * surface (api | grounded_api | consumer_ui), collector (who collected
      it: openai, google_genai, perplexity, anthropic, serpapi) and
      answer_status (answered | no_ai_answer | sign_in_wall | blocked).
      Backfilled for existing rows from platform, which fixes both: every
      platform that existed before 2B had exactly one configuration.
  soa_cycles
    * full_loop_run_id: the supply full_loop_runs row this cycle scores.
    * reference_prices / reference_as_of: the cycle's one cached read of
      supply's retailer-prices, as of the cycle start.
  soa_expectation_outcomes
    * outcome admits partial and unverifiable.
    * flags, claim_results, source_split, reason_code, surface.
  soa_domain_checks
    * the fabricated_citation check's 24-hour cache, one row per domain.
  soa_full_loop_requests
    * one "Run full loop" press from soa: the supply run it started, the
      cycle it created, and where it stands.

Additive. Downgrade refuses while any row uses a value the narrowed
constraints would reject, rather than leaving the table half-migrated.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4e2b7d9a1f3"
down_revision: Union[str, None] = "a7c3e9f1b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Literal, not interpolated from application code: a migration records
# what the database was asked to accept on the day it ran.
PLATFORM_OLD = "platform IN ('chatgpt', 'perplexity', 'gemini', 'claude', 'gemini_grounded')"
PLATFORM_NEW = (
    "platform IN ('chatgpt', 'perplexity', 'gemini', 'claude', 'gemini_grounded', "
    "'chatgpt_api', 'gemini_api', 'aimode', 'copilot')"
)
OUTCOME_OLD = (
    "outcome IN ('exact', 'stale', 'wrong', 'absent', 'unscoreable', "
    "'grounded', 'echoed', 'misattributed', 'fabricated', "
    "'acknowledged_unknown')"
)
OUTCOME_NEW = (
    "outcome IN ('exact', 'stale', 'wrong', 'absent', 'unscoreable', "
    "'partial', 'unverifiable', "
    "'grounded', 'echoed', 'misattributed', 'fabricated', "
    "'acknowledged_unknown')"
)
SURFACE_CHECK = "surface IS NULL OR surface IN ('api', 'grounded_api', 'consumer_ui')"
ANSWER_STATUS_CHECK = (
    "answer_status IS NULL OR answer_status IN "
    "('answered', 'no_ai_answer', 'sign_in_wall', 'blocked')"
)
FULL_LOOP_STATUS_CHECK = (
    "status IN ('reference_pending', 'reference_done', 'cycle_planned', "
    "'scoring', 'scored', 'failed')"
)

# What every pre-2B platform was: one configuration each.
BACKFILL = [
    ("chatgpt", "grounded_api", "openai"),
    ("claude", "grounded_api", "anthropic"),
    ("perplexity", "grounded_api", "perplexity"),
    ("gemini_grounded", "grounded_api", "google_genai"),
    ("gemini", "api", "google_genai"),
]


def upgrade() -> None:
    op.drop_constraint("ck_soa_runs_platform", "soa_runs", type_="check")
    op.create_check_constraint("ck_soa_runs_platform", "soa_runs", PLATFORM_NEW)

    op.add_column("soa_runs", sa.Column("surface", sa.Text(), nullable=True))
    op.add_column("soa_runs", sa.Column("collector", sa.Text(), nullable=True))
    op.add_column("soa_runs", sa.Column("answer_status", sa.Text(), nullable=True))
    op.create_check_constraint("ck_soa_runs_surface", "soa_runs", SURFACE_CHECK)
    op.create_check_constraint("ck_soa_runs_answer_status", "soa_runs", ANSWER_STATUS_CHECK)

    bind = op.get_bind()
    for platform, surface, collector in BACKFILL:
        bind.execute(
            sa.text("UPDATE soa_runs SET surface = :s, collector = :c WHERE platform = :p"),
            {"s": surface, "c": collector, "p": platform},
        )
    bind.execute(sa.text(
        "UPDATE soa_runs SET answer_status = 'answered' "
        "WHERE status = 'success' AND raw_response IS NOT NULL AND raw_response <> ''"
    ))

    op.add_column("soa_cycles", sa.Column("full_loop_run_id", sa.Integer(), nullable=True))
    op.add_column("soa_cycles", sa.Column("reference_prices", sa.JSON(), nullable=True))
    op.add_column("soa_cycles", sa.Column("reference_as_of", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_soa_cycles_full_loop_run_id", "soa_cycles", ["full_loop_run_id"])

    op.drop_constraint("ck_soa_expectation_outcomes_outcome", "soa_expectation_outcomes", type_="check")
    op.create_check_constraint("ck_soa_expectation_outcomes_outcome", "soa_expectation_outcomes", OUTCOME_NEW)
    op.add_column("soa_expectation_outcomes", sa.Column("flags", sa.JSON(), nullable=True))
    op.add_column("soa_expectation_outcomes", sa.Column("claim_results", sa.JSON(), nullable=True))
    op.add_column("soa_expectation_outcomes", sa.Column("source_split", sa.JSON(), nullable=True))
    op.add_column("soa_expectation_outcomes", sa.Column("reason_code", sa.Text(), nullable=True))
    op.add_column("soa_expectation_outcomes", sa.Column("surface", sa.Text(), nullable=True))
    bind.execute(sa.text(
        "UPDATE soa_expectation_outcomes SET surface = "
        "(SELECT r.surface FROM soa_runs r WHERE r.id = soa_expectation_outcomes.run_id)"
    ))

    op.create_table(
        "soa_domain_checks",
        sa.Column("domain", sa.Text(), primary_key=True),
        sa.Column("resolves", sa.Boolean(), nullable=True),
        sa.Column("responds", sa.Boolean(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "soa_full_loop_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("merchant_slug", sa.Text(), nullable=False),
        sa.Column("study_type", sa.Text(), nullable=False),
        sa.Column("platforms", sa.JSON(), nullable=False),
        sa.Column("runs_per_query", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supply_run_id", sa.Integer(), nullable=True),
        sa.Column("supply_status", sa.Text(), nullable=True),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("soa_cycles.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="reference_pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(FULL_LOOP_STATUS_CHECK, name="ck_soa_full_loop_requests_status"),
    )
    op.create_index("ix_soa_full_loop_requests_org", "soa_full_loop_requests", ["organization_id"])
    op.create_index("ix_soa_full_loop_requests_status", "soa_full_loop_requests", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    blocking = bind.execute(sa.text(
        "SELECT (SELECT COUNT(*) FROM soa_expectation_outcomes "
        "        WHERE outcome IN ('partial', 'unverifiable')) "
        "     + (SELECT COUNT(*) FROM soa_runs "
        "        WHERE platform IN ('chatgpt_api', 'gemini_api', 'aimode', 'copilot'))"
    )).scalar()
    if blocking:
        raise RuntimeError(
            f"refusing to downgrade: {blocking} row(s) carry a 2B outcome (partial, "
            f"unverifiable) or a 2B platform (chatgpt_api, gemini_api, aimode, copilot) "
            f"that the narrowed constraints would reject. Re-score or remove them first."
        )

    op.drop_index("ix_soa_full_loop_requests_status", table_name="soa_full_loop_requests")
    op.drop_index("ix_soa_full_loop_requests_org", table_name="soa_full_loop_requests")
    op.drop_table("soa_full_loop_requests")
    op.drop_table("soa_domain_checks")

    for column in ("surface", "reason_code", "source_split", "claim_results", "flags"):
        op.drop_column("soa_expectation_outcomes", column)
    op.drop_constraint("ck_soa_expectation_outcomes_outcome", "soa_expectation_outcomes", type_="check")
    op.create_check_constraint("ck_soa_expectation_outcomes_outcome", "soa_expectation_outcomes", OUTCOME_OLD)

    op.drop_index("ix_soa_cycles_full_loop_run_id", table_name="soa_cycles")
    for column in ("reference_as_of", "reference_prices", "full_loop_run_id"):
        op.drop_column("soa_cycles", column)

    op.drop_constraint("ck_soa_runs_answer_status", "soa_runs", type_="check")
    op.drop_constraint("ck_soa_runs_surface", "soa_runs", type_="check")
    for column in ("answer_status", "collector", "surface"):
        op.drop_column("soa_runs", column)
    op.drop_constraint("ck_soa_runs_platform", "soa_runs", type_="check")
    op.create_check_constraint("ck_soa_runs_platform", "soa_runs", PLATFORM_OLD)
