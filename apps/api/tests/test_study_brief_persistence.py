"""
Tests that the Create Study with AI brief actually reaches the database,
and that the provenance record comes back out.

The API and the pipeline share nothing but soa_query_generation_jobs, so
a structured input this route accepts and does not write down is one the
generator can never see. That was the whole gap migration 3f8e2a91c7d4
closes, and it is invisible from the endpoint's own response — which is
returned before a single query exists — so it has to be asserted against
the row.
"""
import json

import pytest
from sqlalchemy import create_engine, event, text
from datetime import datetime, timezone

import app.routers.studies as studies_router
from app.schemas import StudyGenerateRequest

CURRENT_USER = {"organization_id": 7, "user_id": "u1"}


@pytest.fixture
def patched_engine(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_query_generation_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, study_type TEXT UNIQUE,
                study_name TEXT, description TEXT, target_count INTEGER,
                created_count INTEGER DEFAULT 0, status TEXT, error_message TEXT,
                organization_id INTEGER, created_by TEXT,
                syndicated_merchant TEXT, tier_config TEXT,
                created_at TIMESTAMP, updated_at TIMESTAMP,
                study_pattern TEXT, retailer_names TEXT, allowed_categories TEXT,
                stage_targets TEXT, rotate_named_retailer BOOLEAN,
                naming_rule_enabled BOOLEAN, personas TEXT, specificity_mode TEXT,
                provenance TEXT
            )
        """)
    monkeypatch.setattr(studies_router, "engine", engine)
    return engine


FULL_BRIEF = dict(
    study_name="Prestige Beauty",
    description="Prestige skincare and fragrance",
    target_count=20,
    study_pattern="brand_at_retail",
    retailer_names=["Sephora", "Ulta Beauty"],
    allowed_categories=["Skincare", "Fragrance"],
    stage_targets={"Awareness": 5, "Research": 5, "Comparison": 5, "Ready to Buy": 5},
    rotate_named_retailer=True,
    naming_rule_enabled=False,
    personas=["Beauty Enthusiast"],
    specificity_mode="even_split",
)


def _generate(request_kwargs):
    return studies_router.generate_study(
        StudyGenerateRequest(**request_kwargs), current_user=CURRENT_USER,
    )


def _job(engine, study_type):
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT study_pattern, retailer_names, allowed_categories, stage_targets,
                   rotate_named_retailer, naming_rule_enabled, personas,
                   specificity_mode, target_count
            FROM soa_query_generation_jobs WHERE study_type = :st
        """), {"st": study_type}).fetchone()


# ─── the brief lands on the row ───────────────────────────────────────────

def test_every_brief_field_is_persisted(patched_engine):
    result = _generate(FULL_BRIEF)
    row = _job(patched_engine, result.study_type)

    assert row[0] == "brand_at_retail"
    assert json.loads(row[1]) == ["Sephora", "Ulta Beauty"]
    assert json.loads(row[2]) == ["Skincare", "Fragrance"]
    assert json.loads(row[3]) == {
        "Awareness": 5, "Research": 5, "Comparison": 5, "Ready to Buy": 5,
    }
    assert bool(row[4]) is True
    assert bool(row[5]) is False
    assert json.loads(row[6]) == ["Beauty Enthusiast"]
    assert row[7] == "even_split"
    assert row[8] == 20


def test_a_client_sending_only_the_original_three_fields_still_works(patched_engine):
    """An older client must not break — and the brief columns stay NULL,
    which is what tells the worker to run the job the way it would have
    been run when it was queued."""
    result = _generate(dict(study_name="Legacy Study", target_count=30))
    row = _job(patched_engine, result.study_type)

    assert row[0] is None            # study_pattern — the path discriminator
    assert row[1] is None
    assert row[2] is None
    assert row[3] is None
    assert row[8] == 30


def test_an_absent_list_stays_null_rather_than_becoming_an_empty_list(patched_engine):
    """NULL means "the client said nothing"; [] means "the client said
    none". The worker reads them differently — one falls back to every
    category, the other would allow none at all."""
    brief = {k: v for k, v in FULL_BRIEF.items() if k != 'allowed_categories'}
    result = _generate(brief)
    row = _job(patched_engine, result.study_type)

    assert row[2] is None


def test_an_explicitly_empty_list_is_preserved_as_empty(patched_engine):
    result = _generate({**FULL_BRIEF, 'retailer_names': []})
    row = _job(patched_engine, result.study_type)

    assert json.loads(row[1]) == []


def test_study_pattern_is_never_defaulted_on_the_clients_behalf(patched_engine):
    """Every study_pattern value changes the coding rubric, so choosing
    one here would silently decide something the requester never said —
    and it would also destroy the NULL the worker needs."""
    result = _generate(dict(study_name="No Pattern"))
    row = _job(patched_engine, result.study_type)
    assert row[0] is None


# ─── validation still bites ───────────────────────────────────────────────

def test_an_unknown_category_is_rejected_before_it_reaches_the_row():
    with pytest.raises(Exception) as exc:
        StudyGenerateRequest(study_name="S", allowed_categories=["Not A Category"])
    assert "Not A Category" in str(exc.value)


def test_an_unknown_stage_is_rejected():
    with pytest.raises(Exception) as exc:
        StudyGenerateRequest(study_name="S", stage_targets={"Nonsense": 5})
    assert "Nonsense" in str(exc.value)


def test_a_negative_stage_target_is_rejected():
    with pytest.raises(Exception) as exc:
        StudyGenerateRequest(study_name="S", stage_targets={"Awareness": -1})
    assert "negative" in str(exc.value)


def test_an_unknown_study_pattern_is_rejected():
    with pytest.raises(Exception):
        StudyGenerateRequest(study_name="S", study_pattern="not_a_pattern")


def test_an_unknown_specificity_mode_is_rejected():
    with pytest.raises(Exception):
        StudyGenerateRequest(study_name="S", specificity_mode="whatever")


def test_option_values_are_read_off_query_constraints_not_relisted():
    """constants.py documents adding a value as a constants edit plus a
    migration plus a redeploy — nothing in the schema layer should need
    touching for it."""
    from soa_shared.constants import QUERY_CONSTRAINTS
    from app.schemas import (
        QUERY_CATEGORIES, QUERY_PERSONAS, QUERY_STAGES, QUERY_STUDY_PATTERNS,
    )

    assert QUERY_CATEGORIES is QUERY_CONSTRAINTS['category']
    assert QUERY_STAGES is QUERY_CONSTRAINTS['stage']
    assert QUERY_PERSONAS is QUERY_CONSTRAINTS['persona']
    assert QUERY_STUDY_PATTERNS is QUERY_CONSTRAINTS['study_pattern']


# ─── provenance comes back out ────────────────────────────────────────────

PROVENANCE = {
    "rows_generated": 47,
    "requested_by_stage": {"Awareness": 13, "Comparison": 12},
    "delivered_by_stage": {"Awareness": 13, "Comparison": 10},
    "shortfall_by_stage": {"Comparison": 2},
    "exact_duplicates_dropped": [{"query_text": "A repeat?", "stage": "Comparison"}],
    "semantic_duplicate_groups": [],
    "coherence_findings_by_outcome": {"label_mismatch": [], "out_of_scope": []},
}


def _seed_job(engine, study_type, status, provenance=None):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO soa_query_generation_jobs
              (study_type, study_name, target_count, created_count, status,
               organization_id, provenance)
            VALUES (:st, 'S', 50, 47, :status, 7, :prov)
        """), {
            "st": study_type, "status": status,
            "prov": None if provenance is None else json.dumps(provenance),
        })


def test_generation_status_returns_the_provenance_record(patched_engine):
    _seed_job(patched_engine, "done_study", "complete", PROVENANCE)

    resp = studies_router.get_generation_status("done_study", current_user=CURRENT_USER)

    assert resp.provenance == PROVENANCE
    assert resp.provenance["shortfall_by_stage"] == {"Comparison": 2}


def test_provenance_is_none_while_the_job_is_still_running(patched_engine):
    """A poll mid-run correctly reports nothing rather than a half-built
    record."""
    _seed_job(patched_engine, "running_study", "running", None)

    resp = studies_router.get_generation_status("running_study", current_user=CURRENT_USER)

    assert resp.status == "running"
    assert resp.provenance is None


def test_provenance_is_scoped_to_the_callers_org(patched_engine):
    from fastapi import HTTPException

    _seed_job(patched_engine, "other_org_study", "complete", PROVENANCE)
    with patched_engine.begin() as conn:
        conn.execute(text(
            "UPDATE soa_query_generation_jobs SET organization_id = 99 "
            "WHERE study_type = 'other_org_study'"
        ))

    with pytest.raises(HTTPException) as exc:
        studies_router.get_generation_status("other_org_study", current_user=CURRENT_USER)
    assert exc.value.status_code == 404


# ─── unbranded studies: an empty retailer list is valid ───────────────────
#
# Reversed rule. An empty list is a fully unbranded, category-level study
# where every question describes the need without naming anyone — the
# strictest form of a share-of-mentions measurement, not a degraded one.
# The naming rule governs WHERE names may appear, so with no names its
# value cannot make the study invalid either way.

def test_an_empty_retailer_list_is_accepted_with_the_naming_rule_off(patched_engine):
    result = _generate({**FULL_BRIEF, 'retailer_names': [],
                        'naming_rule_enabled': False})
    row = _job(patched_engine, result.study_type)

    assert json.loads(row[1]) == []
    assert bool(row[5]) is False


def test_an_empty_retailer_list_is_accepted_with_the_naming_rule_on(patched_engine):
    result = _generate({**FULL_BRIEF, 'retailer_names': [],
                        'naming_rule_enabled': True})
    row = _job(patched_engine, result.study_type)

    assert json.loads(row[1]) == []
    assert bool(row[5]) is True


def test_the_schema_itself_rejects_neither_combination():
    """No cross-field validator may reintroduce the old block."""
    for rule in (True, False, None):
        req = StudyGenerateRequest(
            study_name="Unbranded", retailer_names=[], naming_rule_enabled=rule,
        )
        assert req.retailer_names == []
        assert req.naming_rule_enabled is rule


# ─── the syndicated brand lands on the row too ────────────────────────────
#
# Same reason as everything above: the API and the pipeline share nothing
# but this table, so a brand accepted here and not written down is a brand
# the generator can never ground in.

def _brand_job(engine, study_type):
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT syndicated_merchant, tier_config
            FROM soa_query_generation_jobs WHERE study_type = :st
        """), {"st": study_type}).fetchone()


TIER_CONFIG = {
    "brand_direct": {"enabled": True, "count": 12},
    "catalog_accuracy": {"enabled": True},
    "value_incentives": {"enabled": True},
    "category_control": {"enabled": False},
}


def test_the_syndicated_brand_and_tier_config_are_persisted(patched_engine):
    result = _generate({
        **FULL_BRIEF,
        "syndicated_merchant": "wiggle-and-snug",
        "tier_config": TIER_CONFIG,
    })
    merchant, tier_config = _brand_job(patched_engine, result.study_type)

    assert merchant == "wiggle-and-snug"
    assert json.loads(tier_config) == TIER_CONFIG


def test_an_untoggled_study_writes_both_columns_null(patched_engine):
    """The toggle being off is not a tier_config of all-false; it is the
    absence of one, which is exactly what every client predating the
    toggle sends."""
    result = _generate(FULL_BRIEF)
    assert _brand_job(patched_engine, result.study_type) == (None, None)


def test_a_tier_that_needs_a_catalog_is_rejected_without_a_brand():
    """Accepting it and then quietly building nothing would hand back a
    study that looks like it has tiers and does not."""
    with pytest.raises(Exception) as exc:
        StudyGenerateRequest(
            study_name="X", tier_config={"catalog_accuracy": {"enabled": True}},
        )
    assert "syndicated_merchant" in str(exc.value)


def test_the_control_tier_alone_needs_no_brand():
    """It is a tag on the study's own questions, and reads no catalog."""
    request = StudyGenerateRequest(
        study_name="X", tier_config={"category_control": {"enabled": True}},
    )
    assert request.syndicated_merchant is None


def test_an_unknown_tier_is_rejected_before_it_reaches_the_row():
    with pytest.raises(Exception) as exc:
        StudyGenerateRequest(
            study_name="X", syndicated_merchant="wiggle-and-snug",
            tier_config={"price_accuracy": {"enabled": True}},
        )
    assert "price_accuracy" in str(exc.value)


def test_the_tier_names_are_read_off_the_shared_vocabulary_not_relisted():
    """Same discipline as the constraints test above: one source of truth
    for what a tier is, shared with the model, the migration and the
    scorer."""
    from soa_shared.expected_answers import QUERY_TIERS

    for tier in QUERY_TIERS:
        StudyGenerateRequest(
            study_name="X", syndicated_merchant="wiggle-and-snug",
            tier_config={tier: {"enabled": True}},
        )


# ─── Regenerating a grounded study ────────────────────────────────────────
#
# The catalog tiers are always rebuilt; the AI tier only when asked. The
# reason is comparability: rebuilding AI-written questions produces
# different wording, and a study whose questions changed cannot be
# compared run-over-run with the one before it.

def _seed_grounded_job(engine, *, merchant="wiggle-and-snug", config=None,
                       status="complete", study_type="ws_1a2b3c", org_id=7):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO soa_query_generation_jobs
                (study_type, study_name, description, target_count, created_count,
                 status, organization_id, created_by, syndicated_merchant, tier_config)
            VALUES (:st, 'Wiggle & Snug', 'Diapers', 50, 50, :status, :org, 'u1',
                    :merchant, :config)
        """), {
            "st": study_type, "status": status, "org": org_id,
            "merchant": merchant,
            "config": json.dumps(config if config is not None else {
                "brand_direct": {"enabled": True, "count": 12},
                "catalog_accuracy": {"enabled": True},
                "value_incentives": {"enabled": True},
                "category_control": {"enabled": False},
            }),
        })
    return study_type


def _regenerate(study_type, regenerate_ai=False, user=None):
    from app.schemas import RegenerateStudyRequest

    return studies_router.regenerate_study(
        study_type, RegenerateStudyRequest(regenerate_ai=regenerate_ai),
        current_user=user or CURRENT_USER,
    )


def _job_state(engine, study_type):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT status, tier_config FROM soa_query_generation_jobs
            WHERE study_type = :st
        """), {"st": study_type}).fetchone()
    return row[0], json.loads(row[1])


def test_regenerating_rebuilds_the_catalog_tiers_by_default(patched_engine):
    study_type = _seed_grounded_job(patched_engine)
    result = _regenerate(study_type)

    assert result["tiers"] == ["catalog_accuracy", "value_incentives"]
    status, config = _job_state(patched_engine, study_type)
    assert status == "pending"
    assert config["regenerate"]["tiers"] == ["catalog_accuracy", "value_incentives"]


def test_the_ai_tier_is_rebuilt_only_when_asked(patched_engine):
    """Its wording is a model's, so rebuilding it produces different
    questions — and a study whose questions changed cannot be compared
    run-over-run with the one before it."""
    study_type = _seed_grounded_job(patched_engine)
    result = _regenerate(study_type, regenerate_ai=True)

    assert "brand_direct" in result["tiers"]


def test_a_tier_the_study_never_had_is_not_rebuilt(patched_engine):
    """Regenerating a tier the study never had would add questions to a
    study nobody asked to change the shape of."""
    study_type = _seed_grounded_job(patched_engine, config={
        "catalog_accuracy": {"enabled": True},
        "value_incentives": {"enabled": False},
        "brand_direct": {"enabled": False},
    })
    result = _regenerate(study_type, regenerate_ai=True)
    assert result["tiers"] == ["catalog_accuracy"]


def test_an_ungrounded_study_has_nothing_to_rebuild(patched_engine):
    study_type = _seed_grounded_job(patched_engine, merchant=None)
    with pytest.raises(Exception) as exc:
        _regenerate(study_type)
    assert "not grounded" in str(exc.value.detail)


def test_a_study_already_generating_is_not_restarted(patched_engine):
    study_type = _seed_grounded_job(patched_engine, status="running")
    with pytest.raises(Exception) as exc:
        _regenerate(study_type)
    assert exc.value.status_code == 409


def test_a_study_with_no_grounded_tiers_enabled_is_refused(patched_engine):
    study_type = _seed_grounded_job(patched_engine, config={
        "catalog_accuracy": {"enabled": False},
        "value_incentives": {"enabled": False},
        "brand_direct": {"enabled": False},
        "category_control": {"enabled": True},
    })
    with pytest.raises(Exception) as exc:
        _regenerate(study_type)
    assert "no grounded tiers" in str(exc.value.detail)


def test_regenerating_is_scoped_to_the_callers_org(patched_engine):
    study_type = _seed_grounded_job(patched_engine, org_id=99)
    with pytest.raises(Exception) as exc:
        _regenerate(study_type)
    assert exc.value.status_code == 404


def test_the_control_tier_is_never_in_the_rebuild_set(patched_engine):
    """It is a tag on the study's own stage-count questions, and
    rewriting those is creating a different study rather than refreshing
    this one against a record."""
    study_type = _seed_grounded_job(patched_engine, config={
        "catalog_accuracy": {"enabled": True},
        "category_control": {"enabled": True},
    })
    assert "category_control" not in _regenerate(study_type, regenerate_ai=True)["tiers"]
