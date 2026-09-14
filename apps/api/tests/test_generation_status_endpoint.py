"""
Tests for GET /studies/{study_type}/generation-status
(app/routers/studies.py::get_generation_status) — specifically that
error_message actually reaches the caller. GenerationStatusResponse
didn't declare that field even though the router always passed it to
the constructor; Pydantic silently drops unknown kwargs by default, so
every generation-status response silently omitted it regardless of
whether the job actually recorded one. StudyDetail.jsx already reads
status.error_message and has always gotten undefined as a result — this
is a pre-existing gap this fix closes, not new behavior.

The fixture's CREATE TABLE mirrors the real soa_query_generation_jobs,
study-brief columns included (migration 3f8e2a91c7d4), because the router
selects provenance off the row. Only the DDL grew — every assertion below
is unchanged.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine

import app.routers.studies as studies_router

CURRENT_USER = {"organization_id": 1, "user_id": "u1"}


@pytest.fixture
def patched_engine(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_query_generation_jobs (
                id INTEGER PRIMARY KEY, study_type TEXT UNIQUE, study_name TEXT,
                description TEXT, target_count INTEGER, created_count INTEGER DEFAULT 0,
                status TEXT, error_message TEXT, organization_id INTEGER, created_by TEXT,
                study_pattern TEXT, retailer_names TEXT, allowed_categories TEXT,
                stage_targets TEXT, rotate_named_retailer BOOLEAN,
                naming_rule_enabled BOOLEAN, personas TEXT, specificity_mode TEXT,
                provenance TEXT,
                syndicated_merchant TEXT, tier_config TEXT
            )
        """)
    monkeypatch.setattr(studies_router, "engine", engine)
    return engine


def test_generation_status_reports_the_recorded_error_message(patched_engine):
    with patched_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_query_generation_jobs "
            "(study_type, study_name, target_count, created_count, status, error_message, organization_id) "
            "VALUES ('acme_full_1a2b3c', 'Acme Full', 50, 0, 'failed', 'OpenAI request timed out', 1)"
        )

    result = studies_router.get_generation_status("acme_full_1a2b3c", current_user=CURRENT_USER)

    assert result.status == "failed"
    assert result.error_message == "OpenAI request timed out"


def test_generation_status_error_message_defaults_to_none_when_not_recorded(patched_engine):
    with patched_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_query_generation_jobs "
            "(study_type, study_name, target_count, created_count, status, organization_id) "
            "VALUES ('acme_full_2b3c4d', 'Acme Full', 50, 12, 'running', 1)"
        )

    result = studies_router.get_generation_status("acme_full_2b3c4d", current_user=CURRENT_USER)

    assert result.status == "running"
    assert result.error_message is None


def test_generation_status_created_count_reflects_committed_rows_at_complete(patched_engine):
    """The signal the frontend needs to tell a genuine success apart from
    a job that reached 'complete' without ever producing a row (e.g. the
    generator returned zero rows on both attempts of the first batch,
    worker.py's early-break path) is already here — created_count is
    updated in the SAME commit as each batch of soa_queries inserts, so
    a 'complete' status with created_count == 0 is a real, honestly
    representable state, not one requiring a new field."""
    with patched_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO soa_query_generation_jobs "
            "(study_type, study_name, target_count, created_count, status, organization_id) "
            "VALUES ('acme_full_3c4d5e', 'Acme Full', 50, 0, 'complete', 1)"
        )

    result = studies_router.get_generation_status("acme_full_3c4d5e", current_user=CURRENT_USER)

    assert result.status == "complete"
    assert result.created_count == 0


def test_generation_status_404_for_unknown_study_type(patched_engine):
    with pytest.raises(HTTPException) as exc_info:
        studies_router.get_generation_status("nope", current_user=CURRENT_USER)
    assert exc_info.value.status_code == 404
