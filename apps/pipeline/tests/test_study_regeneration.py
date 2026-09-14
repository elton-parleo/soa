"""
Regenerating a grounded study against the catalog as it is now.

The three properties worth holding:

  * only the named tiers are rebuilt — the study's own stage-count
    questions are never touched, because rewriting those is creating a
    different study rather than refreshing this one;
  * a rebuild REPLACES rather than doubles, so a study never ends up with
    two prices for one variant;
  * a failed catalog read leaves the study exactly as it was.
"""
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, text

import worker
from clients.truesync_catalog import CatalogSnapshot, build_snapshot

FIXTURE_PATH = "tests/fixtures/wiggle_and_snug_catalog.json"
STUDY_TYPE = "wiggle_and_snug_abc123"


@pytest.fixture
def payloads():
    with open(FIXTURE_PATH) as fh:
        return json.load(fh)


@pytest.fixture
def snapshot(payloads):
    return build_snapshot(
        payloads["catalog"],
        merchants=payloads["merchants"],
        incentives=payloads["incentives"],
    )


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


TIER_CONFIG = {
    "brand_direct": {"enabled": True, "count": 12},
    "catalog_accuracy": {"enabled": True, "count": 35},
    "value_incentives": {"enabled": True, "count": 6},
    "category_control": {"enabled": False},
    "merchant": {"brand": "Wiggle & Snug"},
}


def seed(db, *, tiers, config=None):
    """A study as it stands after its first generation: stage questions,
    catalog questions, and a pending regenerate request."""
    tier_config = json.loads(json.dumps(config or TIER_CONFIG))
    tier_config["regenerate"] = {"tiers": tiers, "requested_by": "u1"}

    with db.begin() as conn:
        conn.execute(text("""
            INSERT INTO soa_query_generation_jobs
                (id, study_type, study_name, description, target_count, status,
                 organization_id, created_by, syndicated_merchant, tier_config,
                 study_pattern, allowed_categories, stage_targets, personas)
            VALUES (1, :st, 'Wiggle & Snug', 'Everyday diapers', 50, 'pending',
                    1, 'u1', 'wiggle-and-snug', :config,
                    'brand_at_retail', :cats, :stages, :personas)
        """), {
            "st": STUDY_TYPE,
            "config": json.dumps(tier_config),
            "cats": json.dumps(["Baby Care"]),
            "stages": json.dumps({"Research": 12, "Ready to Buy": 16}),
            "personas": json.dumps(["Value-Conscious Parent"]),
        })

        rows = [
            # The study's own stage questions — never rebuilt.
            ("WS_001", "Which diapers hold up overnight?", None, None),
            ("WS_002", "Best diapers for a newborn?", None, "ai"),
            # Catalog-built.
            ("WS_003", "What does the old Size 3 pack cost?", "catalog_accuracy", "catalog"),
            ("WS_004", "Any promo codes?", "value_incentives", "catalog"),
            # AI-written, catalog-grounded.
            ("WS_005", "Where can I buy Wiggle & Snug?", "brand_direct", "ai_from_catalog"),
        ]
        for code, question, tier, provenance in rows:
            conn.execute(text("""
                INSERT INTO soa_queries (query_code, query_text, category, stage,
                    specificity, persona, study_type, study_pattern, status,
                    organization_id, tier, provenance)
                VALUES (:code, :q, 'Baby Care', 'Ready to Buy', 'Narrow',
                        'Value-Conscious Parent', :st, 'brand_at_retail', 'Active',
                        1, :tier, :prov)
            """), {"code": code, "q": question, "st": STUDY_TYPE,
                   "tier": tier, "prov": provenance})


def questions(db):
    with db.connect() as conn:
        return conn.execute(text("""
            SELECT query_text, tier, provenance FROM soa_queries
            WHERE study_type = :st ORDER BY id
        """), {"st": STUDY_TYPE}).fetchall()


def job(db):
    with db.connect() as conn:
        return conn.execute(text("""
            SELECT status, tier_config, error_message
            FROM soa_query_generation_jobs WHERE study_type = :st
        """), {"st": STUDY_TYPE}).fetchone()


def run(snapshot, brand_rows=None, capture=None):
    """Runs the worker with the catalog stubbed to `snapshot` and
    brand-direct generation stubbed to `brand_rows`.

    `capture`, when given, is a dict the stubbed generate_brand_direct
    writes its kwargs into — the only way to see what the tier was told
    about the rest of the study, since the stub is what replaces the
    model call."""
    class FakeClient:
        def snapshot(self, _slug, **_kwargs):
            return snapshot

    def _fake_brand_direct(*args, **kwargs):
        if capture is not None:
            capture.update(kwargs)
        return (brand_rows if brand_rows is not None else [], {})

    with patch("clients.truesync_catalog.TrueSyncCatalogClient", FakeClient), \
         patch(
             "generation.query_generator.generate_brand_direct",
             side_effect=_fake_brand_direct,
         ):
        worker.process_generation_jobs()


# ── only the named tiers ──────────────────────────────────────────────────

def test_the_studys_own_stage_questions_are_never_touched(db, snapshot):
    """They exist with or without a brand, and rewriting them is creating
    a different study rather than refreshing this one."""
    seed(db, tiers=["catalog_accuracy", "value_incentives"])
    run(snapshot)

    kept = [q for q in questions(db) if q[1] is None]
    assert [q[0] for q in kept] == [
        "Which diapers hold up overnight?", "Best diapers for a newborn?",
    ]


def test_the_ai_tier_is_left_alone_unless_it_is_named(db, snapshot):
    seed(db, tiers=["catalog_accuracy", "value_incentives"])
    run(snapshot)

    brand_direct = [q for q in questions(db) if q[1] == "brand_direct"]
    assert [q[0] for q in brand_direct] == ["Where can I buy Wiggle & Snug?"]


def test_the_ai_tier_is_rebuilt_when_it_is_named(db, snapshot):
    seed(db, tiers=["catalog_accuracy", "brand_direct"])
    run(snapshot, brand_rows=[{
        "query_text": "Where do I get Wiggle & Snug size 4?",
        "category": "Baby Care", "stage": "Research", "specificity": "Mid",
        "persona": "Value-Conscious Parent", "status": "Active",
        "study_pattern": "brand_at_retail",
        "tier": "brand_direct", "provenance": "ai_from_catalog",
        "expected_answer": {"type": "brand_mention", "brand": "Wiggle & Snug"},
        "source_ref": {"merchant_slug": "wiggle-and-snug"},
    }])

    brand_direct = [q for q in questions(db) if q[1] == "brand_direct"]
    assert [q[0] for q in brand_direct] == ["Where do I get Wiggle & Snug size 4?"]


# ── replace, never double ─────────────────────────────────────────────────

def test_a_rebuild_replaces_the_old_catalog_questions(db, snapshot):
    """A study with two prices for one variant has no way to say which
    one it measured."""
    seed(db, tiers=["catalog_accuracy"])
    run(snapshot)

    accuracy = [q for q in questions(db) if q[1] == "catalog_accuracy"]
    assert "What does the old Size 3 pack cost?" not in [q[0] for q in accuracy]
    assert len(accuracy) == 19


def test_the_rebuilt_questions_are_asked_of_the_current_record(db, snapshot):
    seed(db, tiers=["catalog_accuracy"])
    run(snapshot)

    texts = [q[0] for q in questions(db)]
    assert (
        "What does the Wiggle & Snug Snug-Fit Diapers Size 3 small pack cost?"
        in texts
    )


def test_a_disabled_tier_is_not_rebuilt_even_if_named(db, snapshot):
    """Regenerating a tier the study never had would change its shape,
    not refresh it. The API filters on the enabled set for the same
    reason; this is the second half of that guard."""
    config = json.loads(json.dumps(TIER_CONFIG))
    config["value_incentives"]["enabled"] = False
    seed(db, tiers=["catalog_accuracy"], config=config)
    run(snapshot)

    value = [q for q in questions(db) if q[1] == "value_incentives"]
    assert [q[0] for q in value] == ["Any promo codes?"]


# ── the job row ───────────────────────────────────────────────────────────

def test_the_regenerate_marker_is_consumed(db, snapshot):
    """A worker restart must not regenerate the same study twice."""
    seed(db, tiers=["catalog_accuracy"])
    run(snapshot)

    status, tier_config, _error = job(db)
    assert status == "complete"
    assert "regenerate" not in json.loads(tier_config)


def test_the_resolved_config_records_the_catalog_it_just_read(db, snapshot):
    seed(db, tiers=["catalog_accuracy"])
    run(snapshot)

    config = json.loads(job(db)[1])
    assert config["merchant"]["variants"] == 19
    assert len(config["catalog_accuracy"]["sampled_variants"]) == 19
    assert config["catalog_accuracy"]["expected_nulls"]


# ── failure leaves the study alone ────────────────────────────────────────

def test_an_unreadable_catalog_leaves_every_question_in_place(db):
    """The rebuild happens before the delete for exactly this reason: an
    outage between them would leave a study with its catalog questions
    gone and nothing in their place."""
    seed(db, tiers=["catalog_accuracy", "value_incentives"])
    down = CatalogSnapshot(available=False, error="504 from TrueSync")
    run(down)

    assert len(questions(db)) == 5
    status, _config, error = job(db)
    assert status == "failed"
    assert "504 from TrueSync" in error
    assert "unchanged" in error


# ── brand-direct knows what the rest of the study is asking ───────────────
#
# A brand-direct-only regeneration is the common case and the one that
# fixes a study rather than replacing it: the catalog questions are not
# rebuilt, so they exist only in the database. If the tier cannot see
# them it will happily write a price question the catalog tier already
# asks, which measures one published number twice and scores the second
# copy against a brand mention.

def test_regenerating_brand_direct_alone_still_sees_the_catalog_questions(db, snapshot):
    seen = {}
    seed(db, tiers=["brand_direct"])
    run(snapshot, capture=seen)

    assert sorted(seen["catalog_texts"]) == sorted([
        "What does the old Size 3 pack cost?",
        "Any promo codes?",
    ])


def test_a_rebuilt_catalog_tier_is_what_brand_direct_sees_not_the_old_one(db, snapshot):
    """Both tiers regenerating together: the questions that will exist
    when this finishes are the new ones, and the stale row about to be
    deleted must not be what brand-direct works around."""
    seen = {}
    seed(db, tiers=["brand_direct", "catalog_accuracy"])
    run(snapshot, capture=seen)

    assert "What does the old Size 3 pack cost?" not in seen["catalog_texts"]
    # value_incentives is not being rebuilt, so its question stays and is
    # still something brand-direct has to avoid.
    assert "Any promo codes?" in seen["catalog_texts"]
    assert any("cost?" in t for t in seen["catalog_texts"])


def test_the_rebuilt_rows_carry_the_studys_own_persona(db, snapshot):
    seed(db, tiers=["catalog_accuracy", "value_incentives"])
    run(snapshot)

    with db.connect() as conn:
        personas = {
            row[0] for row in conn.execute(text("""
                SELECT DISTINCT persona FROM soa_queries WHERE study_type = :st
            """), {"st": STUDY_TYPE})
        }
    assert personas == {"Value-Conscious Parent"}


def test_with_no_personas_in_the_brief_the_existing_questions_decide(db, snapshot):
    """The C80512 shape: the brief named no personas, so a rebuilt
    catalog row has to take the persona the study's own questions already
    carry rather than a default from another vertical."""
    seed(db, tiers=["catalog_accuracy"])
    with db.begin() as conn:
        conn.execute(text("""
            UPDATE soa_query_generation_jobs SET personas = :p WHERE id = 1
        """), {"p": json.dumps([])})
        conn.execute(text("""
            UPDATE soa_queries SET persona = 'Sensitive-Skin Baby Parent'
            WHERE study_type = :st
        """), {"st": STUDY_TYPE})

    run(snapshot)

    with db.connect() as conn:
        rebuilt = {
            row[0] for row in conn.execute(text("""
                SELECT persona FROM soa_queries
                WHERE study_type = :st AND tier = 'catalog_accuracy'
            """), {"st": STUDY_TYPE})
        }
    assert rebuilt == {"Sensitive-Skin Baby Parent"}


def test_a_brand_direct_shortfall_is_recorded_on_the_tier(db, snapshot):
    seed(db, tiers=["brand_direct"])

    class FakeClient:
        def snapshot(self, _slug, **_kwargs):
            return snapshot

    with patch("clients.truesync_catalog.TrueSyncCatalogClient", FakeClient), \
         patch(
             "generation.query_generator.generate_brand_direct",
             return_value=([], {"requested": 12, "shortfall": 12,
                                "brand_missing_drops": [{"query_text": "no brand here"}]}),
         ):
        worker.process_generation_jobs()

    config = json.loads(job(db)[1])
    assert config["brand_direct"]["shortfall"] == 12
    assert config["brand_direct"]["requested"] == 12
    assert config["brand_direct"]["brand_missing_drops"] == [
        {"query_text": "no brand here"},
    ]
