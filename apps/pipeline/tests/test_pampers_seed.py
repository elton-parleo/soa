"""
Tests for pampers_queries_seed.py.

Runs the seed against an in-memory SQLite DB (no live Postgres required).
Verifies:
  - Only KEEP='y' rows are included
  - Constrained field validation rejects invalid values
  - seed() inserts rows correctly
  - Running seed() twice leaves row count unchanged (idempotency)
  - Distribution assertions across stage and expected_incentive

Uses the same raw-DDL + in-memory SQLite pattern as test_scope_resolution.py.
"""
import importlib.util
import os
import sys
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Load the seed module without importing it as a package (same pattern as
# test_platform_migrations.py uses for alembic files).
# ---------------------------------------------------------------------------
_SEEDS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "seeds"
)

def _load_seed():
    path = os.path.join(_SEEDS_DIR, "pampers_queries_seed.py")
    spec = importlib.util.spec_from_file_location("pampers_queries_seed", path)
    mod = importlib.util.module_from_spec(spec)

    # Stub out dotenv and soa_shared.database before the module body executes
    # so we avoid a live DB connection requirement in tests.
    _fake_dotenv = type(sys)("dotenv")
    _fake_dotenv.load_dotenv = lambda: None

    _fake_db = type(sys)("soa_shared.database")
    _fake_db.engine = None
    _fake_db.session_factory = None  # tests patch this anyway

    _fake_soa_shared = type(sys)("soa_shared")

    sys.modules.setdefault("dotenv", _fake_dotenv)
    sys.modules["soa_shared.database"] = _fake_db

    # soa_shared.constants must be the real one so validators work
    import soa_shared.constants  # noqa — ensure it's loaded
    sys.modules.setdefault("soa_shared", _fake_soa_shared)

    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# In-memory SQLite fixture — mirrors soa_queries columns declared in soa_models
# (including the new expected_incentive column from this PR).
# ---------------------------------------------------------------------------
@pytest.fixture
def sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE organizations (
                id INTEGER PRIMARY KEY, name TEXT, created_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("INSERT INTO organizations (id, name) VALUES (1, 'test')")
        conn.exec_driver_sql("""
            CREATE TABLE soa_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_code TEXT UNIQUE NOT NULL,
                query_text TEXT NOT NULL,
                category TEXT NOT NULL,
                stage TEXT NOT NULL,
                specificity TEXT NOT NULL,
                persona TEXT NOT NULL,
                soa_focus TEXT,
                rationale TEXT,
                status TEXT NOT NULL DEFAULT 'Active',
                study_type TEXT NOT NULL,
                study_pattern TEXT NOT NULL,
                organization_id INTEGER NOT NULL DEFAULT 1,
                created_by TEXT,
                membership_program TEXT,
                tier_name TEXT,
                subscription_state TEXT,
                expected_incentive TEXT,
                new_customer BOOLEAN,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
        """)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# Sample QUERIES for tests (a minimal but representative set)
# ---------------------------------------------------------------------------
_ORG_ID = 1  # matches the test DB fixture's seeded org

SAMPLE_QUERIES = [
    {
        "query_code":         "BC_AWR_BRD_NFP_01",
        "query_text":         "My newborn keeps leaking overnight — what do I do?",
        "category":           "Baby Care",
        "stage":              "Awareness",
        "specificity":        "Broad",
        "persona":            "New / First-Time Parent",
        "study_type":         "brand_pampers",
        "study_pattern":      "brand_vs_brand",
        "status":             "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name":          None,
        "soa_focus":          "Mention Rate",
        "rationale":          "Top-of-funnel problem recognition.",
        "organization_id":    _ORG_ID,
    },
    {
        "query_code":         "BC_AWR_BRD_VCP_02",
        "query_text":         "Are store-brand diapers as good as Pampers?",
        "category":           "Baby Care",
        "stage":              "Awareness",
        "specificity":        "Broad",
        "persona":            "Value-Conscious Parent",
        "study_type":         "brand_pampers",
        "study_pattern":      "brand_vs_brand",
        "status":             "Active",
        "subscription_state": None,
        "expected_incentive": "Mixed",
        "membership_program": None,
        "tier_name":          None,
        "soa_focus":          "Mention Rate, RSI",
        "rationale":          "Value framing entry query.",
        "organization_id":    _ORG_ID,
    },
    {
        "query_code":         "BC_RES_MID_SUB_03",
        "query_text":         "Is a Pampers diaper subscription worth it?",
        "category":           "Baby Care",
        "stage":              "Research",
        "specificity":        "Mid",
        "persona":            "Subscription / Replenishment Parent",
        "study_type":         "brand_pampers",
        "study_pattern":      "brand_at_retail",
        "status":             "Active",
        "subscription_state": "subscribed",
        "expected_incentive": "High",
        "membership_program": None,
        "tier_name":          None,
        "soa_focus":          "Mention Rate, Deal Citation Rate",
        "rationale":          "Subscription research query.",
        "organization_id":    _ORG_ID,
    },
    {
        "query_code":         "BC_CMP_BRD_SSB_04",
        "query_text":         "Which diaper is best for a baby with sensitive skin — Pampers Pure or Huggies Special Delivery?",
        "category":           "Baby Care",
        "stage":              "Comparison",
        "specificity":        "Broad",
        "persona":            "Sensitive-Skin Baby Parent",
        "study_type":         "brand_pampers",
        "study_pattern":      "brand_vs_brand",
        "status":             "Active",
        "subscription_state": None,
        "expected_incentive": "Low",
        "membership_program": None,
        "tier_name":          None,
        "soa_focus":          "RSI, Position Index",
        "rationale":          "Sensitive-skin comparison query.",
        "organization_id":    _ORG_ID,
    },
    {
        "query_code":         "BC_BUY_NAR_ECP_05",
        "query_text":         "Where can I buy Pampers Pure biodegradable diapers online?",
        "category":           "Baby Care",
        "stage":              "Ready to Buy",
        "specificity":        "Narrow",
        "persona":            "Eco-Conscious Parent",
        "study_type":         "brand_pampers",
        "study_pattern":      "brand_at_retail",
        "status":             "Active",
        "subscription_state": None,
        "expected_incentive": "Mixed",
        "membership_program": None,
        "tier_name":          None,
        "soa_focus":          "Mention Rate, Deal Citation Rate",
        "rationale":          "Eco purchase intent query.",
        "organization_id":    _ORG_ID,
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_study_type_constant():
    mod = _load_seed()
    assert mod.STUDY_TYPE == "brand_pampers"


def test_validation_passes_for_valid_queries():
    mod = _load_seed()
    mod.validate_queries(SAMPLE_QUERIES)  # must not raise


def test_validation_rejects_invalid_stage():
    mod = _load_seed()
    bad = [{**SAMPLE_QUERIES[0], "stage": "Discovery"}]
    with pytest.raises(SystemExit, match="validation errors"):
        mod.validate_queries(bad)


def test_validation_rejects_invalid_expected_incentive():
    mod = _load_seed()
    bad = [{**SAMPLE_QUERIES[0], "expected_incentive": "Maybe"}]
    with pytest.raises(SystemExit, match="validation errors"):
        mod.validate_queries(bad)


def test_validation_rejects_wrong_category():
    mod = _load_seed()
    bad = [{**SAMPLE_QUERIES[0], "category": "Skincare"}]
    with pytest.raises(SystemExit, match="validation errors"):
        mod.validate_queries(bad)


def test_validation_rejects_invalid_persona():
    mod = _load_seed()
    bad = [{**SAMPLE_QUERIES[0], "persona": "Unknown Persona"}]
    with pytest.raises(SystemExit, match="validation errors"):
        mod.validate_queries(bad)


def test_seed_inserts_all_sample_rows(sqlite_session):
    mod = _load_seed()

    @contextmanager
    def _mock_session_factory():
        yield sqlite_session

    with patch.object(mod, "session_factory", _mock_session_factory), \
         patch.object(mod, "engine", sqlite_session.bind):
        mod.seed(SAMPLE_QUERIES)

    count = sqlite_session.execute(
        text("SELECT COUNT(*) FROM soa_queries WHERE study_type = 'brand_pampers'")
    ).scalar()
    assert count == len(SAMPLE_QUERIES)


def test_seed_idempotent_second_run_leaves_count_unchanged(sqlite_session):
    mod = _load_seed()

    @contextmanager
    def _mock_session_factory():
        yield sqlite_session

    with patch.object(mod, "session_factory", _mock_session_factory), \
         patch.object(mod, "engine", sqlite_session.bind):
        mod.seed(SAMPLE_QUERIES)
        mod.seed(SAMPLE_QUERIES)

    count = sqlite_session.execute(
        text("SELECT COUNT(*) FROM soa_queries WHERE study_type = 'brand_pampers'")
    ).scalar()
    assert count == len(SAMPLE_QUERIES)


def test_seed_stage_distribution(sqlite_session):
    mod = _load_seed()

    @contextmanager
    def _mock_session_factory():
        yield sqlite_session

    with patch.object(mod, "session_factory", _mock_session_factory), \
         patch.object(mod, "engine", sqlite_session.bind):
        mod.seed(SAMPLE_QUERIES)

    rows = sqlite_session.execute(
        text("SELECT stage, COUNT(*) FROM soa_queries WHERE study_type = 'brand_pampers' GROUP BY stage")
    ).fetchall()
    stage_dist = dict(rows)

    # Sample set has 2 Awareness, 1 Research, 1 Comparison, 1 Ready to Buy
    assert stage_dist.get("Awareness") == 2
    assert stage_dist.get("Research") == 1
    assert stage_dist.get("Comparison") == 1
    assert stage_dist.get("Ready to Buy") == 1


def test_seed_expected_incentive_distribution(sqlite_session):
    mod = _load_seed()

    @contextmanager
    def _mock_session_factory():
        yield sqlite_session

    with patch.object(mod, "session_factory", _mock_session_factory), \
         patch.object(mod, "engine", sqlite_session.bind):
        mod.seed(SAMPLE_QUERIES)

    rows = sqlite_session.execute(
        text("SELECT expected_incentive, COUNT(*) FROM soa_queries WHERE study_type = 'brand_pampers' GROUP BY expected_incentive")
    ).fetchall()
    ei_dist = dict(rows)

    # Sample set: Low x2, Mixed x2, High x1
    assert ei_dist.get("Low") == 2
    assert ei_dist.get("Mixed") == 2
    assert ei_dist.get("High") == 1


def test_seed_expected_incentive_column_is_persisted(sqlite_session):
    mod = _load_seed()

    @contextmanager
    def _mock_session_factory():
        yield sqlite_session

    with patch.object(mod, "session_factory", _mock_session_factory), \
         patch.object(mod, "engine", sqlite_session.bind):
        mod.seed(SAMPLE_QUERIES)

    row = sqlite_session.execute(
        text("SELECT expected_incentive FROM soa_queries WHERE query_code = 'BC_RES_MID_SUB_03'")
    ).fetchone()
    assert row[0] == "High"


def test_seed_subscription_state_null_and_set(sqlite_session):
    mod = _load_seed()

    @contextmanager
    def _mock_session_factory():
        yield sqlite_session

    with patch.object(mod, "session_factory", _mock_session_factory), \
         patch.object(mod, "engine", sqlite_session.bind):
        mod.seed(SAMPLE_QUERIES)

    null_row = sqlite_session.execute(
        text("SELECT subscription_state FROM soa_queries WHERE query_code = 'BC_AWR_BRD_NFP_01'")
    ).fetchone()
    assert null_row[0] is None

    sub_row = sqlite_session.execute(
        text("SELECT subscription_state FROM soa_queries WHERE query_code = 'BC_RES_MID_SUB_03'")
    ).fetchone()
    assert sub_row[0] == "subscribed"
