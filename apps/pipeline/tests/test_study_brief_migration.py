"""
Tests for the study-brief migration (3f8e2a91c7d4) — the columns that
carry the Create Study with AI brief across to the pipeline worker, and
the provenance record back.

Mirrors the pattern in test_general_category_migration.py: the migration
module is loaded directly and op is mocked, so this asserts on the SQL
the migration would emit without needing a database.

The properties that matter beyond "it runs": every column is nullable
(existing pending rows must survive the migration and keep running), the
SQLAlchemy model and the migration agree on the column set, and downgrade
undoes exactly what upgrade did.
"""
import importlib.util
import os
from unittest.mock import patch

import sqlalchemy as sa

from soa_shared.models.soa_models import SoaQueryGenerationJob

_VERSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic", "versions",
)

_MODULE = "3f8e2a91c7d4_add_study_brief_to_generation_jobs"

_EXPECTED_COLUMNS = {
    "study_pattern",
    "retailer_names",
    "allowed_categories",
    "stage_targets",
    "rotate_named_retailer",
    "naming_rule_enabled",
    "personas",
    "specificity_mode",
    "provenance",
}


def _load_migration():
    path = os.path.join(_VERSIONS_DIR, f"{_MODULE}.py")
    spec = importlib.util.spec_from_file_location(_MODULE, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── revision metadata ──────────────────────────────────────────────────────

def test_chains_off_the_previous_head():
    mod = _load_migration()
    assert mod.revision == "3f8e2a91c7d4"
    assert mod.down_revision == "467a91c32dd8"


# ── upgrade ────────────────────────────────────────────────────────────────

def test_upgrade_adds_every_brief_column_to_the_jobs_table():
    mod = _load_migration()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    tables = {call.args[0] for call in mock_op.add_column.call_args_list}
    assert tables == {"soa_query_generation_jobs"}

    added = {call.args[1].name for call in mock_op.add_column.call_args_list}
    assert added == _EXPECTED_COLUMNS


def test_every_added_column_is_nullable():
    """A pending job queued before this migration has to survive it and
    keep running. A NOT NULL column with no server default would either
    fail the migration outright or need a backfill value invented on
    behalf of requests nobody made."""
    mod = _load_migration()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    for call in mock_op.add_column.call_args_list:
        column = call.args[1]
        assert column.nullable is True, column.name


def test_the_structured_columns_are_json_and_the_scalars_are_not():
    mod = _load_migration()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    types = {c.args[1].name: type(c.args[1].type) for c in mock_op.add_column.call_args_list}

    for name in ("retailer_names", "allowed_categories", "stage_targets",
                 "personas", "provenance"):
        assert types[name] is sa.JSON, name
    for name in ("study_pattern", "specificity_mode"):
        assert types[name] is sa.String, name
    for name in ("rotate_named_retailer", "naming_rule_enabled"):
        assert types[name] is sa.Boolean, name


def test_no_check_constraints_are_added():
    """constants.py documents adding an allowed value as one migration
    for the CHECK. A CHECK on study_pattern here would quietly make that
    two, forever. These values are validated by StudyGenerateRequest on
    the way in, and again by soa_queries' own CHECK when study_pattern is
    stamped onto rows — this table stores a request, not a record of
    truth."""
    mod = _load_migration()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    mock_op.create_check_constraint.assert_not_called()


# ── downgrade ──────────────────────────────────────────────────────────────

def test_downgrade_drops_exactly_what_upgrade_added():
    mod = _load_migration()

    with patch.object(mod, "op") as up_op:
        mod.upgrade()
    with patch.object(mod, "op") as down_op:
        mod.downgrade()

    added = {c.args[1].name for c in up_op.add_column.call_args_list}
    dropped = {c.args[1] for c in down_op.drop_column.call_args_list}
    assert dropped == added

    tables = {c.args[0] for c in down_op.drop_column.call_args_list}
    assert tables == {"soa_query_generation_jobs"}


# ── model / migration agreement ────────────────────────────────────────────

def test_the_model_declares_the_same_columns_the_migration_adds():
    """The two drift silently otherwise: the worker reads these columns by
    name in raw SQL, so a model that disagrees with the table is only
    noticed at runtime."""
    model_columns = {c.name for c in SoaQueryGenerationJob.__table__.columns}
    assert _EXPECTED_COLUMNS.issubset(model_columns)


def test_the_model_keeps_every_brief_column_nullable():
    model_columns = {c.name: c for c in SoaQueryGenerationJob.__table__.columns}
    for name in _EXPECTED_COLUMNS:
        assert model_columns[name].nullable is True, name
