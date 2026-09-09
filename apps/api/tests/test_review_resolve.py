"""
Tests for POST /studies/{study_type}/review/resolve — the reviewer's
decisions about the advisory findings the worker recorded in provenance.

Two properties carry most of the weight.

Deactivation flips soa_queries.status rather than deleting the row.
Cycles select `status = 'Active'` (routers/cycles.py), so a non-Active
query stops being run while staying visible on the study page and
restorable. A DELETE would achieve the first half and destroy the other
two.

Resolutions live inside the existing provenance JSON — no new columns —
and every one stores the values it overwrote, because undo has to restore
what was actually there rather than a guess. The whole document is read,
mutated and written back, which is why the column being `json` rather
than `jsonb` makes no difference: nothing here does a partial update.
"""
import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text

import app.routers.studies as studies_router
from app.schemas import (
    REVIEW_DEACTIVATED,
    REVIEW_DISMISSED,
    REVIEW_INACTIVE_STATUS,
    REVIEW_LABEL_APPLIED,
    ReviewResolveRequest,
)

CURRENT_USER = {"organization_id": 7, "user_id": "reviewer@example.com"}
STUDY = "prestige_beauty_a1b2c3"

BASE_PROVENANCE = {
    "rows_generated": 4,
    "requested_by_stage": {"Awareness": 2, "Comparison": 2},
    "delivered_by_stage": {"Awareness": 2, "Comparison": 2},
    "shortfall_by_stage": {},
    "exact_duplicates_dropped": [],
    "category_drops": [],
    "semantic_duplicate_groups": [
        {"members": [0, 1], "keep": 0,
         "member_texts": ["Best vitamin C serum?", "Which vitamin C serum is best?"],
         "keep_text": "Best vitamin C serum?",
         "reason": "Same question, different wording."},
    ],
    "coherence_findings_by_outcome": {
        "label_mismatch": [
            {"index": 2, "query_text": "Which fragrance notes last longest?",
             "category": "Skincare", "verdict": "label_mismatch",
             "field": "category", "proposed_value": "Fragrance", "reason": ""},
        ],
        "out_of_scope": [
            {"index": 3, "query_text": "Best price on a Dyson Airwrap?",
             "category": "Skincare", "verdict": "out_of_scope",
             "reason": "Not a prestige beauty product."},
        ],
    },
}

QUERIES = [
    ("PRE_001", "Best vitamin C serum?", "Skincare", "Awareness", "Active"),
    ("PRE_002", "Which vitamin C serum is best?", "Skincare", "Awareness", "Active"),
    ("PRE_003", "Which fragrance notes last longest?", "Skincare", "Comparison", "Active"),
    ("PRE_004", "Best price on a Dyson Airwrap?", "Skincare", "Comparison", "Active"),
]


@pytest.fixture
def db(monkeypatch):
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
        conn.exec_driver_sql("""
            CREATE TABLE soa_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, query_code TEXT UNIQUE,
                query_text TEXT, category TEXT, stage TEXT, specificity TEXT,
                persona TEXT, study_type TEXT, study_pattern TEXT, status TEXT,
                subscription_state TEXT, soa_focus TEXT, rationale TEXT,
                organization_id INTEGER, created_by TEXT, created_at TIMESTAMP,
                tier TEXT, expected_answer TEXT, provenance TEXT, source_ref TEXT
            )
        """)
        conn.execute(text("""
            INSERT INTO soa_query_generation_jobs
              (study_type, study_name, target_count, created_count, status,
               organization_id, provenance)
            VALUES (:st, 'Prestige Beauty', 4, 4, 'complete', 7, :prov)
        """), {"st": STUDY, "prov": json.dumps(BASE_PROVENANCE)})
        for code, text_value, category, stage, status in QUERIES:
            conn.execute(text("""
                INSERT INTO soa_queries
                  (query_code, query_text, category, stage, specificity, persona,
                   study_type, study_pattern, status, organization_id)
                VALUES (:c, :t, :cat, :s, 'Mid', 'Beauty Enthusiast',
                        :st, 'retailer', :status, 7)
            """), {"c": code, "t": text_value, "cat": category, "s": stage,
                   "st": STUDY, "status": status})
    monkeypatch.setattr(studies_router, "engine", engine)
    return engine


def _resolve(**kwargs):
    return studies_router.resolve_review_finding(
        STUDY, ReviewResolveRequest(**kwargs), current_user=CURRENT_USER,
    )


def _stored_provenance(db):
    with db.connect() as conn:
        raw = conn.execute(text(
            "SELECT provenance FROM soa_query_generation_jobs WHERE study_type = :st"
        ), {"st": STUDY}).scalar()
    return json.loads(raw)


def _query(db, code):
    with db.connect() as conn:
        return conn.execute(text("""
            SELECT query_code, status, category, stage
            FROM soa_queries WHERE query_code = :c
        """), {"c": code}).fetchone()


def _row_count(db):
    with db.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM soa_queries")).scalar()


# ─── deactivation ─────────────────────────────────────────────────────────

def test_deactivation_sets_status_and_never_deletes(db):
    before = _row_count(db)

    _resolve(finding_id="dup:0", action="deactivate",
             query_codes=["PRE_002"], keep_query_code="PRE_001")

    assert _row_count(db) == before                 # the row is still there
    assert _query(db, "PRE_002")[1] == REVIEW_INACTIVE_STATUS
    assert _query(db, "PRE_001")[1] == "Active"     # the kept one is untouched


def test_the_inactive_status_is_one_cycles_will_not_select(db):
    """Cycles select `status = 'Active'`, so anything else takes the query
    out of every future cycle."""
    _resolve(finding_id="dup:0", action="deactivate", query_codes=["PRE_002"])
    assert REVIEW_INACTIVE_STATUS != "Active"
    assert _query(db, "PRE_002")[1] != "Active"


def test_deactivation_records_the_prior_status_for_undo(db):
    _resolve(finding_id="dup:0", action="deactivate",
             query_codes=["PRE_002"], keep_query_code="PRE_001")

    record = _stored_provenance(db)["review_resolutions"]["dup:0"]
    assert record["action"] == REVIEW_DEACTIVATED
    assert record["queries"] == [{"query_code": "PRE_002", "prior_status": "Active"}]
    assert record["kept"] == "PRE_001"
    assert record["by"] == "reviewer@example.com"
    assert record["at"]


def test_deactivating_several_members_at_once(db):
    _resolve(finding_id="dup:0", action="deactivate",
             query_codes=["PRE_002", "PRE_003"], keep_query_code="PRE_001")

    assert _query(db, "PRE_002")[1] == REVIEW_INACTIVE_STATUS
    assert _query(db, "PRE_003")[1] == REVIEW_INACTIVE_STATUS


def test_a_different_member_can_be_kept_instead_of_the_models_pick(db):
    """The model's recommendation is a default, not a decision."""
    _resolve(finding_id="dup:0", action="deactivate",
             query_codes=["PRE_001"], keep_query_code="PRE_002")

    assert _query(db, "PRE_001")[1] == REVIEW_INACTIVE_STATUS
    assert _query(db, "PRE_002")[1] == "Active"
    assert _stored_provenance(db)["review_resolutions"]["dup:0"]["kept"] == "PRE_002"


# ─── label correction ─────────────────────────────────────────────────────

def test_a_label_correction_writes_only_the_named_field(db):
    before = _query(db, "PRE_003")

    _resolve(finding_id="coh:label_mismatch:0", action="apply_label",
             query_code="PRE_003", field="category", proposed_value="Fragrance")

    after = _query(db, "PRE_003")
    assert after[2] == "Fragrance"      # category changed
    assert after[3] == before[3]        # stage did not
    assert after[1] == before[1]        # status did not


def test_a_label_correction_records_the_prior_value(db):
    _resolve(finding_id="coh:label_mismatch:0", action="apply_label",
             query_code="PRE_003", field="category", proposed_value="Fragrance")

    record = _stored_provenance(db)["review_resolutions"]["coh:label_mismatch:0"]
    assert record["action"] == REVIEW_LABEL_APPLIED
    assert record["field"] == "category"
    assert record["prior_value"] == "Skincare"
    assert record["applied_value"] == "Fragrance"


def test_a_value_outside_the_constraint_is_rejected_before_any_write():
    with pytest.raises(Exception) as exc:
        ReviewResolveRequest(finding_id="x", action="apply_label",
                             query_code="PRE_003", field="category",
                             proposed_value="Not A Category")
    assert "not valid" in str(exc.value)


def test_status_is_not_a_correctable_field():
    """Changing status is what deactivate is for. Letting a 'correction'
    reach it would make the two actions overlap in a way the undo record
    could not tell apart."""
    with pytest.raises(Exception):
        ReviewResolveRequest(finding_id="x", action="apply_label",
                             query_code="PRE_003", field="status",
                             proposed_value="Paused")


def test_an_unknown_field_is_rejected():
    with pytest.raises(Exception):
        ReviewResolveRequest(finding_id="x", action="apply_label",
                             query_code="PRE_003", field="query_text; DROP TABLE",
                             proposed_value="x")


# ─── dismissal ────────────────────────────────────────────────────────────

def test_dismissal_changes_no_query_at_all(db):
    _resolve(finding_id="coh:out_of_scope:0", action="dismiss")

    assert _query(db, "PRE_004")[1] == "Active"
    assert _query(db, "PRE_004")[2] == "Skincare"


def test_a_dismissed_finding_is_distinguishable_from_an_unreviewed_one(db):
    """The whole reason a dismissal is stored rather than dropped: 'a
    human looked and disagreed' is different information from 'nobody has
    read this yet'."""
    provenance = _stored_provenance(db)
    assert "review_resolutions" not in provenance     # unreviewed: absent

    _resolve(finding_id="coh:out_of_scope:0", action="dismiss")

    resolutions = _stored_provenance(db)["review_resolutions"]
    assert resolutions["coh:out_of_scope:0"]["action"] == REVIEW_DISMISSED
    assert "dup:0" not in resolutions                 # still unreviewed
    assert resolutions["coh:out_of_scope:0"]["by"] == "reviewer@example.com"


# ─── persistence ──────────────────────────────────────────────────────────

def test_resolutions_survive_and_accumulate(db):
    _resolve(finding_id="dup:0", action="deactivate", query_codes=["PRE_002"])
    _resolve(finding_id="coh:out_of_scope:0", action="dismiss")
    _resolve(finding_id="coh:label_mismatch:0", action="apply_label",
             query_code="PRE_003", field="category", proposed_value="Fragrance")

    resolutions = _stored_provenance(db)["review_resolutions"]
    assert set(resolutions) == {"dup:0", "coh:out_of_scope:0", "coh:label_mismatch:0"}


def test_resolving_never_destroys_the_rest_of_the_record(db):
    """Whole-document read-modify-write: everything the worker wrote has
    to still be there afterwards."""
    _resolve(finding_id="dup:0", action="dismiss")

    provenance = _stored_provenance(db)
    for key in BASE_PROVENANCE:
        assert provenance[key] == BASE_PROVENANCE[key]


def test_the_response_returns_the_stored_record(db):
    result = _resolve(finding_id="dup:0", action="dismiss")
    assert result.provenance == _stored_provenance(db)
    assert result.study_type == STUDY


# ─── undo ─────────────────────────────────────────────────────────────────

def test_undo_restores_the_prior_status(db):
    _resolve(finding_id="dup:0", action="deactivate", query_codes=["PRE_002"])
    assert _query(db, "PRE_002")[1] == REVIEW_INACTIVE_STATUS

    _resolve(finding_id="dup:0", action="undo")

    assert _query(db, "PRE_002")[1] == "Active"
    assert "dup:0" not in _stored_provenance(db)["review_resolutions"]


def test_undo_restores_a_prior_status_that_was_not_active(db):
    """The record, not a guessed default. A query deactivated from
    'Retired' must not come back 'Active'."""
    with db.begin() as conn:
        conn.execute(text(
            "UPDATE soa_queries SET status = 'Retired' WHERE query_code = 'PRE_002'"
        ))

    _resolve(finding_id="dup:0", action="deactivate", query_codes=["PRE_002"])
    _resolve(finding_id="dup:0", action="undo")

    assert _query(db, "PRE_002")[1] == "Retired"


def test_undo_restores_the_prior_label(db):
    _resolve(finding_id="coh:label_mismatch:0", action="apply_label",
             query_code="PRE_003", field="category", proposed_value="Fragrance")
    assert _query(db, "PRE_003")[2] == "Fragrance"

    _resolve(finding_id="coh:label_mismatch:0", action="undo")

    assert _query(db, "PRE_003")[2] == "Skincare"
    assert "coh:label_mismatch:0" not in _stored_provenance(db)["review_resolutions"]


def test_undoing_a_dismissal_returns_it_to_unreviewed(db):
    _resolve(finding_id="coh:out_of_scope:0", action="dismiss")
    _resolve(finding_id="coh:out_of_scope:0", action="undo")

    assert "coh:out_of_scope:0" not in _stored_provenance(db)["review_resolutions"]


def test_undo_of_an_unresolved_finding_is_a_404(db):
    with pytest.raises(HTTPException) as exc:
        _resolve(finding_id="dup:0", action="undo")
    assert exc.value.status_code == 404


def test_undo_leaves_other_resolutions_alone(db):
    _resolve(finding_id="dup:0", action="deactivate", query_codes=["PRE_002"])
    _resolve(finding_id="coh:out_of_scope:0", action="dismiss")

    _resolve(finding_id="dup:0", action="undo")

    resolutions = _stored_provenance(db)["review_resolutions"]
    assert set(resolutions) == {"coh:out_of_scope:0"}
    assert _query(db, "PRE_002")[1] == "Active"


# ─── scoping and errors ───────────────────────────────────────────────────

def test_a_study_in_another_org_is_a_404(db):
    with pytest.raises(HTTPException) as exc:
        studies_router.resolve_review_finding(
            STUDY, ReviewResolveRequest(finding_id="dup:0", action="dismiss"),
            current_user={"organization_id": 99, "user_id": "other"},
        )
    assert exc.value.status_code == 404


def test_a_query_from_another_study_cannot_be_touched(db):
    with pytest.raises(HTTPException) as exc:
        _resolve(finding_id="dup:0", action="deactivate", query_codes=["NOPE_001"])
    assert exc.value.status_code == 404


def test_deactivate_requires_query_codes():
    with pytest.raises(Exception) as exc:
        ReviewResolveRequest(finding_id="dup:0", action="deactivate")
    assert "query_codes" in str(exc.value)


def test_an_unknown_action_is_rejected():
    with pytest.raises(Exception):
        ReviewResolveRequest(finding_id="dup:0", action="obliterate")
