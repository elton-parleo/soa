"""
The worker end of the syndicated path — worker.py::process_generation_jobs
into _run_syndicated_generation, and the INSERT that persists the four
grounding columns.

The claim this file exists to hold up is the one existing users care
about: a job with no syndicated_merchant writes exactly the rows it wrote
before these columns existed, with all four NULL, and never touches the
catalog client at all.

Same in-memory sqlite harness as test_briefed_generation.py.
"""
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, text

import worker

STUDY_TYPE = "wiggle_and_snug_9f8e7d"

BRIEF = {
    "study_pattern": "brand_at_retail",
    "retailer_names": [],
    "allowed_categories": ["Baby Care"],
    "stage_targets": {"Research": 2, "Ready to Buy": 2},
    "rotate_named_retailer": True,
    "naming_rule_enabled": True,
    "personas": ["Value-Conscious Parent"],
    "specificity_mode": "match_to_stage",
}


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _):
        dbapi_conn.create_function(
            "NOW", 0, lambda: datetime.now(timezone.utc).isoformat(),
        )

    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_query_generation_jobs (
                id INTEGER PRIMARY KEY, study_type TEXT UNIQUE, study_name TEXT,
                description TEXT, target_count INTEGER, created_count INTEGER DEFAULT 0,
                status TEXT, error_message TEXT, organization_id INTEGER, created_by TEXT,
                syndicated_merchant TEXT, tier_config TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP,
                study_pattern TEXT, retailer_names TEXT, allowed_categories TEXT,
                stage_targets TEXT, rotate_named_retailer BOOLEAN,
                naming_rule_enabled BOOLEAN, personas TEXT, specificity_mode TEXT,
                provenance TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_queries (
                id INTEGER PRIMARY KEY, query_code TEXT UNIQUE, query_text TEXT, category TEXT,
                stage TEXT, specificity TEXT, persona TEXT, study_type TEXT, study_pattern TEXT,
                soa_focus TEXT, rationale TEXT, status TEXT, organization_id INTEGER,
                created_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tier TEXT, expected_answer TEXT, provenance TEXT, source_ref TEXT
            )
        """)
    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setenv("OPEN_AI_API_KEY", "test-key")
    return engine


def _insert_job(conn, *, merchant=None, tier_config=None):
    conn.execute(text("""
        INSERT INTO soa_query_generation_jobs
          (study_type, study_name, description, target_count, created_count,
           status, organization_id, created_by,
           study_pattern, retailer_names, allowed_categories, stage_targets,
           rotate_named_retailer, naming_rule_enabled, personas, specificity_mode,
           syndicated_merchant, tier_config)
        VALUES
          (:st, 'Wiggle & Snug', 'Everyday diapers', 4, 0,
           'pending', 1, 'u1',
           :study_pattern, :retailer_names, :allowed_categories, :stage_targets,
           :rotate, :naming_rule, :personas, :specificity_mode,
           :merchant, :tier_config)
    """), {
        "st": STUDY_TYPE,
        "study_pattern": BRIEF["study_pattern"],
        "retailer_names": json.dumps(BRIEF["retailer_names"]),
        "allowed_categories": json.dumps(BRIEF["allowed_categories"]),
        "stage_targets": json.dumps(BRIEF["stage_targets"]),
        "rotate": BRIEF["rotate_named_retailer"],
        "naming_rule": BRIEF["naming_rule_enabled"],
        "personas": json.dumps(BRIEF["personas"]),
        "specificity_mode": BRIEF["specificity_mode"],
        "merchant": merchant,
        "tier_config": json.dumps(tier_config) if tier_config else None,
    })


def _plain_row(i):
    return {
        "query_text": f"Which diapers hold up overnight? {i}",
        "category": "Baby Care",
        "stage": "Research",
        "specificity": "Mid",
        "persona": "Value-Conscious Parent",
        "study_pattern": "brand_at_retail",
        "status": "Active",
        "soa_focus": "Mention Rate",
        "rationale": "because",
    }


def _grounded_row(i):
    return {
        **_plain_row(i),
        "stage": "Ready to Buy",
        "tier": "catalog_accuracy",
        "provenance": "catalog",
        "expected_answer": {"type": "price", "amount": "22.99", "currency": "USD"},
        "source_ref": {
            "merchant_slug": "wiggle-and-snug",
            "listing_id": 90,
            "variant_id": "snug-fit-diapers-s3-small",
            "published_at": "2026-09-04T20:49:40.991623+00:00",
        },
    }


class _AvailableSnapshot:
    available = True
    error = None


def _stored(db):
    with db.connect() as conn:
        return conn.execute(text("""
            SELECT query_text, tier, expected_answer, provenance, source_ref
            FROM soa_queries WHERE study_type = :st ORDER BY id
        """), {"st": STUDY_TYPE}).fetchall()


def _job(db):
    with db.connect() as conn:
        return conn.execute(text("""
            SELECT status, created_count, tier_config
            FROM soa_query_generation_jobs WHERE study_type = :st
        """), {"st": STUDY_TYPE}).fetchone()


# ── with no brand: today's behaviour, unchanged ───────────────────────────

def test_a_job_with_no_brand_never_reads_a_catalog(db):
    with db.begin() as conn:
        _insert_job(conn)

    with patch(
        "generation.query_generator.generate_and_review_study",
        return_value=([_plain_row(i) for i in range(4)], {}),
    ), patch("clients.truesync_catalog.TrueSyncCatalogClient") as client:
        worker.process_generation_jobs()

    client.assert_not_called()
    assert _job(db)[:2] == ("complete", 4)


def test_a_job_with_no_brand_writes_all_four_grounding_columns_null(db):
    """NULL is the untouched state. Anything else here would be a study
    silently reinterpreted under rules its requester never agreed to."""
    with db.begin() as conn:
        _insert_job(conn)

    with patch(
        "generation.query_generator.generate_and_review_study",
        return_value=([_plain_row(i) for i in range(4)], {}),
    ):
        worker.process_generation_jobs()

    rows = _stored(db)
    assert len(rows) == 4
    for _text, tier, expected, provenance, source_ref in rows:
        assert (tier, expected, provenance, source_ref) == (None, None, None, None)


def test_a_job_with_no_brand_leaves_tier_config_alone(db):
    with db.begin() as conn:
        _insert_job(conn)

    with patch(
        "generation.query_generator.generate_and_review_study",
        return_value=([_plain_row(i) for i in range(4)], {}),
    ):
        worker.process_generation_jobs()

    assert _job(db)[2] is None


# ── with a brand: the catalog is read and the columns are written ─────────

def test_a_job_with_a_brand_reads_that_brand_s_catalog(db):
    with db.begin() as conn:
        _insert_job(conn, merchant="wiggle-and-snug", tier_config={
            "catalog_accuracy": {"enabled": True},
        })

    with patch(
        "worker._run_syndicated_generation",
        return_value=([_grounded_row(i) for i in range(3)], {}, {"x": 1}),
    ) as run:
        worker.process_generation_jobs()

    run.assert_called_once()
    assert run.call_args.kwargs["syndicated_merchant"] == "wiggle-and-snug"
    assert run.call_args.kwargs["tier_config"] == {
        "catalog_accuracy": {"enabled": True},
    }


def test_the_grounding_columns_round_trip_through_the_insert(db):
    with db.begin() as conn:
        _insert_job(conn, merchant="wiggle-and-snug")

    with patch(
        "worker._run_syndicated_generation",
        return_value=([_grounded_row(0)], {}, {"catalog_accuracy": {"count": 1}}),
    ):
        worker.process_generation_jobs()

    (_text, tier, expected, provenance, source_ref), = _stored(db)
    assert tier == "catalog_accuracy"
    assert provenance == "catalog"
    assert json.loads(expected) == {
        "type": "price", "amount": "22.99", "currency": "USD",
    }
    # The record's published_at, which is what a later comparison says the
    # claim was made against.
    assert json.loads(source_ref)["published_at"] == (
        "2026-09-04T20:49:40.991623+00:00"
    )


def test_the_resolved_tier_config_replaces_what_the_modal_asked_for(db):
    """The request is not evidence of what the study contains. What the
    job row ends up holding is the result: counts actually built, and the
    variants actually sampled."""
    with db.begin() as conn:
        _insert_job(conn, merchant="wiggle-and-snug", tier_config={
            "catalog_accuracy": {"enabled": True},
        })

    resolved = {
        "catalog_accuracy": {
            "enabled": True, "count": 35,
            "sampled_variants": ["snug-fit-diapers-s3-small"],
        },
    }
    with patch(
        "worker._run_syndicated_generation",
        return_value=([_grounded_row(0)], {}, resolved),
    ):
        worker.process_generation_jobs()

    assert json.loads(_job(db)[2]) == resolved


def test_the_stage_total_is_recorded_so_the_tally_can_be_recomputed(db):
    """build_syndicated_study sees per-tier counts, never the brief — so
    the number the tally splits on is written here or nowhere."""
    with db.begin() as conn:
        _insert_job(conn, merchant="wiggle-and-snug", tier_config={
            "category_control": {"enabled": True},
        })

    with patch(
        "generation.syndicated_study.build_syndicated_study",
        return_value=(
            [_plain_row(0)], {}, {"category_control": {"enabled": True, "count": 1}},
        ),
    ), patch("clients.truesync_catalog.TrueSyncCatalogClient") as client:
        client.return_value.snapshot.return_value = _AvailableSnapshot()
        worker.process_generation_jobs()

    config = json.loads(_job(db)[2])
    assert config["category_control"]["stage_total"] == 4


def test_the_catalog_is_read_without_history(db):
    """Expectations are written against the CURRENT record; prior values
    are the scorer's business, read at scoring time."""
    with db.begin() as conn:
        _insert_job(conn, merchant="wiggle-and-snug")

    with patch(
        "generation.syndicated_study.build_syndicated_study",
        return_value=([_plain_row(0)], {}, {}),
    ), patch("clients.truesync_catalog.TrueSyncCatalogClient") as client:
        client.return_value.snapshot.return_value = _AvailableSnapshot()
        worker.process_generation_jobs()

    assert client.return_value.snapshot.call_args.kwargs["with_history"] is False
