"""
Tests for the add_syndicated_brand_tiers migration.

Same mock-based shape as test_expected_incentive_migration.py: no live DB,
assert what op.* was called with. That is the limit of what these can
prove — that the migration ASKS for the right things. Whether Postgres
then does them, and undoes them, was checked by actually running
upgrade -> downgrade -> upgrade against a scratch Postgres 18 cluster;
see the ALEMBIC_DATABASE_URL note in alembic/env.py for how.

The round-trip assertion that matters here is symmetry: every column and
constraint the upgrade adds, the downgrade drops, and nothing else.
"""
import importlib.util
import os

import sqlalchemy as sa
from unittest.mock import patch

_VERSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic", "versions",
)

_MODULE = "a9f3c21b7e40_add_syndicated_brand_tiers"


def _load_migration(module_name=_MODULE):
    path = os.path.join(_VERSIONS_DIR, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _upgrade_calls():
    mod = _load_migration()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()
    return mock_op


def _downgrade_calls():
    mod = _load_migration()
    with patch.object(mod, "op") as mock_op:
        mod.downgrade()
    return mock_op


# ── revision metadata ─────────────────────────────────────────────────────

def test_chains_off_the_study_brief_migration():
    mod = _load_migration()
    assert mod.revision == "a9f3c21b7e40"
    assert mod.down_revision == "3f8e2a91c7d4"


def test_is_the_single_head():
    """A second head is a merge waiting to happen, and alembic will not
    say so until someone tries to upgrade."""
    import re

    revisions, down_revisions = set(), set()
    for name in os.listdir(_VERSIONS_DIR):
        if not name.endswith(".py"):
            continue
        text = open(os.path.join(_VERSIONS_DIR, name)).read()
        rev = re.search(r'^revision(?::\s*str)?\s*=\s*["\']([^"\']+)', text, re.M)
        down = re.search(
            r'^down_revision(?::\s*[^=]+)?\s*=\s*["\']([^"\']+)', text, re.M,
        )
        if rev:
            revisions.add(rev.group(1))
        if down:
            down_revisions.add(down.group(1))

    assert revisions - down_revisions == {"a9f3c21b7e40"}


# ── upgrade: soa_queries ──────────────────────────────────────────────────

def test_upgrade_adds_four_nullable_query_columns():
    mock_op = _upgrade_calls()

    added = {
        call.args[1].name: call.args
        for call in mock_op.add_column.call_args_list
        if call.args[0] == "soa_queries"
    }
    assert set(added) == {"tier", "expected_answer", "provenance", "source_ref"}

    for name, (_table, column) in added.items():
        # Every one nullable with no server default: an existing row is
        # byte-identical after this migration to what it was before.
        assert column.nullable is True, name
        assert column.server_default is None, name

    assert isinstance(added["tier"][1].type, sa.Text)
    assert isinstance(added["provenance"][1].type, sa.Text)
    assert isinstance(added["expected_answer"][1].type, sa.JSON)
    assert isinstance(added["source_ref"][1].type, sa.JSON)


def test_tier_constraint_allows_null_and_names_all_four_tiers():
    mock_op = _upgrade_calls()

    conditions = {
        call.args[0]: call.args[2]
        for call in mock_op.create_check_constraint.call_args_list
    }
    tier = conditions["ck_soa_queries_tier"]

    # NULL is the untouched state of every existing row, not a violation.
    assert "tier IS NULL OR" in tier
    for value in (
        "brand_direct", "catalog_accuracy", "value_incentives", "category_control",
    ):
        assert f"'{value}'" in tier


def test_provenance_constraint_allows_null_and_names_all_three_values():
    mock_op = _upgrade_calls()
    conditions = {
        call.args[0]: call.args[2]
        for call in mock_op.create_check_constraint.call_args_list
    }
    provenance = conditions["ck_soa_queries_provenance"]

    assert "provenance IS NULL OR" in provenance
    for value in ("catalog", "ai_from_catalog", "ai"):
        assert f"'{value}'" in provenance


def test_constraint_text_matches_the_shared_vocabulary():
    """
    The migration spells its constraints as literals on purpose — a
    replayed migration must mean the same thing in two years. This test
    is the tripwire that keeps the literal and the Python constant from
    diverging without anyone noticing.
    """
    from soa_shared.expected_answers import (
        EXPECTATION_OUTCOMES, QUERY_PROVENANCES, QUERY_TIERS,
    )

    mock_op = _upgrade_calls()
    conditions = {
        call.args[0]: call.args[2]
        for call in mock_op.create_check_constraint.call_args_list
    }

    for value in QUERY_TIERS:
        assert f"'{value}'" in conditions["ck_soa_queries_tier"]
    for value in QUERY_PROVENANCES:
        assert f"'{value}'" in conditions["ck_soa_queries_provenance"]

    table_call = mock_op.create_table.call_args
    outcome_constraint = next(
        arg for arg in table_call.args[1:]
        if getattr(arg, "name", None) == "ck_soa_expectation_outcomes_outcome"
    )
    for value in EXPECTATION_OUTCOMES:
        assert f"'{value}'" in str(outcome_constraint.sqltext)


# ── upgrade: the study definition row and the cycle ───────────────────────

def test_upgrade_adds_study_columns_to_the_generation_job():
    """The generation job row IS a study's definition — there is no
    soa_studies table — so the brand and tier config belong there, not on
    soa_cycles, where two runs of one study could disagree."""
    mock_op = _upgrade_calls()

    added = {
        call.args[1].name: call.args[1]
        for call in mock_op.add_column.call_args_list
        if call.args[0] == "soa_query_generation_jobs"
    }
    assert set(added) == {"syndicated_merchant", "tier_config"}
    assert isinstance(added["syndicated_merchant"].type, sa.String)
    assert isinstance(added["tier_config"].type, sa.JSON)
    assert all(col.nullable for col in added.values())


def test_upgrade_adds_extraction_validation_to_cycles():
    mock_op = _upgrade_calls()
    added = [
        call.args[1]
        for call in mock_op.add_column.call_args_list
        if call.args[0] == "soa_cycles"
    ]
    assert [col.name for col in added] == ["extraction_validation"]
    # Nullable and no default: blank until a human records one. A
    # validated agreement rate nobody validated is the single most
    # damaging number this system could print.
    assert added[0].nullable is True
    assert added[0].server_default is None


# ── upgrade: the outcomes table ───────────────────────────────────────────

def test_creates_the_outcomes_table_keyed_on_run():
    mock_op = _upgrade_calls()
    mock_op.create_table.assert_called_once()

    args = mock_op.create_table.call_args.args
    assert args[0] == "soa_expectation_outcomes"

    columns = {a.name: a for a in args[1:] if isinstance(a, sa.Column)}
    # The grain IS soa_runs: (cycle, query, platform, run_number) is the
    # unique slot, so run_id alone is "question x surface x sample" and
    # the answer text reached from it cannot disagree with what was
    # scored.
    assert "run_id" in columns
    assert columns["run_id"].nullable is False

    for required in ("expected_answer", "extraction", "outcome", "platform"):
        assert columns[required].nullable is False, required

    for stored in (
        "record_published_at", "matched_published_at", "domain_cited",
        "source_attribution", "secondary_results", "outcome_reason",
    ):
        assert stored in columns, stored


def test_one_verdict_per_run():
    """A re-score replaces the row rather than appending a second one, so
    a rate cannot double-count a twice-scored run."""
    mock_op = _upgrade_calls()
    args = mock_op.create_table.call_args.args
    unique = [
        a for a in args[1:]
        if getattr(a, "name", None) == "uq_soa_expectation_outcomes_run"
    ]
    assert len(unique) == 1
    # An unbound UniqueConstraint has not resolved its column names into
    # .columns yet — they are still the strings it was constructed with.
    named = list(unique[0].columns.keys()) or list(unique[0]._pending_colargs)
    assert named == ["run_id"]


# ── downgrade: exact inverse ──────────────────────────────────────────────

def test_downgrade_drops_every_column_the_upgrade_added():
    up, down = _upgrade_calls(), _downgrade_calls()

    added = {(c.args[0], c.args[1].name) for c in up.add_column.call_args_list}
    dropped = {(c.args[0], c.args[1]) for c in down.drop_column.call_args_list}
    assert added == dropped


def test_downgrade_drops_every_constraint_and_index_the_upgrade_added():
    up, down = _upgrade_calls(), _downgrade_calls()

    added_constraints = {c.args[0] for c in up.create_check_constraint.call_args_list}
    dropped_constraints = {c.args[0] for c in down.drop_constraint.call_args_list}
    assert added_constraints == dropped_constraints

    added_indexes = {c.args[0] for c in up.create_index.call_args_list}
    dropped_indexes = {c.args[0] for c in down.drop_index.call_args_list}
    assert added_indexes == dropped_indexes


def test_downgrade_drops_the_outcomes_table():
    down = _downgrade_calls()
    down.drop_table.assert_called_once_with("soa_expectation_outcomes")


def test_downgrade_drops_the_table_before_the_columns_it_references():
    """soa_expectation_outcomes carries foreign keys into soa_queries and
    soa_cycles. Dropping their columns first is fine on those particular
    columns, but the ordering is load-bearing in general and cheap to
    keep, so it is asserted rather than left to luck."""
    mod = _load_migration()
    order = []
    with patch.object(mod, "op") as mock_op:
        mock_op.drop_table.side_effect = lambda *a, **k: order.append("drop_table")
        mock_op.drop_column.side_effect = lambda *a, **k: order.append("drop_column")
        mock_op.drop_index.side_effect = lambda *a, **k: order.append("drop_index")
        mock_op.drop_constraint.side_effect = lambda *a, **k: order.append("drop_constraint")
        mod.downgrade()

    assert order.index("drop_table") < order.index("drop_column")
