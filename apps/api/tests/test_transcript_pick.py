"""
Tests for the "From the transcript" selection service
(app/services/transcript_pick.py) — the 5-tier deterministic cascade,
narrative_case <-> box-copy generation, span location, and determinism.
Mirrors the SQLite-fixture style of test_full_analysis_extras.py.
"""
import pytest
from sqlalchemy import create_engine, text

from app.services.transcript_pick import select_transcript

CYCLE_ID = 900
OTHER_CYCLE_ID = 901
PRIMARY_ID = 901
COMPETITOR_ID = 902


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_entities (id INTEGER PRIMARY KEY, name TEXT, slug TEXT, aliases TEXT)
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycle_entities (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER, role TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_queries (id INTEGER PRIMARY KEY, stage TEXT, persona TEXT, query_text TEXT)
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, query_id INTEGER, status TEXT,
                platform TEXT, raw_response TEXT, run_at TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_coded_mentions (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                mentioned BOOLEAN, position INTEGER, strength TEXT,
                deal_cited BOOLEAN, deal_types TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_price_observations (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                stated_price FLOAT, claimed_net_price FLOAT, merchant_name TEXT, attribution_status TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_incentive_scores (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                scoring_grain TEXT, status TEXT, measurement_status TEXT,
                stated_price FLOAT, ground_truth_true_cost FLOAT, net_price_accuracy BOOLEAN
            )
        """)
    return engine


def _seed_entities(conn, cycle_id=CYCLE_ID, aliases='[]'):
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (id, name, slug, aliases) VALUES (?, 'Allbirds', 'allbirds', ?)",
        (PRIMARY_ID, aliases),
    )
    conn.exec_driver_sql("INSERT INTO soa_entities (id, name, slug) VALUES (?, 'Nike', 'nike')", (COMPETITOR_ID,))
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, role) VALUES (?, ?, 'primary')",
        (cycle_id, PRIMARY_ID),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_cycle_entities (cycle_id, entity_id, role) VALUES (?, ?, 'competitor')",
        (cycle_id, COMPETITOR_ID),
    )


def _run(conn, run_id, platform="chatgpt", stage="Ready to Buy", persona="Value-Conscious",
         query_text="Best shoes?", raw_response="A generic answer about shoes.", cycle_id=CYCLE_ID,
         status="success"):
    conn.exec_driver_sql(
        "INSERT INTO soa_queries (id, stage, persona, query_text) VALUES (?, ?, ?, ?)",
        (run_id, stage, persona, query_text),
    )
    conn.exec_driver_sql(
        "INSERT INTO soa_runs (id, cycle_id, query_id, status, platform, raw_response, run_at) "
        "VALUES (?, ?, ?, ?, ?, ?, '2026-08-07T00:00:00')",
        (run_id, cycle_id, run_id, status, platform, raw_response),
    )


def _mention(conn, run_id, entity_id, mentioned=1, position=None, strength=None, deal_cited=0, deal_types="[]"):
    conn.exec_driver_sql(
        "INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, position, strength, deal_cited, deal_types) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, entity_id, mentioned, position, strength, deal_cited, deal_types),
    )


def _price_obs(conn, run_id, entity_id, stated_price, merchant_name=None, attribution_status="unattributed", claimed_net_price=None):
    conn.exec_driver_sql(
        "INSERT INTO soa_price_observations (run_id, entity_id, stated_price, claimed_net_price, merchant_name, attribution_status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, entity_id, stated_price, claimed_net_price, merchant_name, attribution_status),
    )


def _incentive(conn, run_id, entity_id, stated_price, ground_truth_true_cost, net_price_accuracy, measurement_status="measured"):
    conn.exec_driver_sql(
        "INSERT INTO soa_incentive_scores (run_id, entity_id, scoring_grain, status, measurement_status, "
        "stated_price, ground_truth_true_cost, net_price_accuracy) "
        "VALUES (?, ?, 'observation', 'scored', ?, ?, ?, ?)",
        (run_id, entity_id, measurement_status, stated_price, ground_truth_true_cost, net_price_accuracy),
    )


# ─── Tier 1: purchase-intent · mentioned · leak ────────────────────────────

def test_tier1_purchase_intent_mentioned_with_offsite_price_leak(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, stage="Ready to Buy", raw_response="Allbirds runs about $100 at Zappos.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary", position=1)
        _price_obs(conn, 1, PRIMARY_ID, stated_price=100, merchant_name="Zappos", attribution_status="mapped")
        # a non-purchase-intent run that also qualifies for tier 1 predicate
        # minus the stage filter — must NOT be picked over the real tier-1 run
        _run(conn, 2, stage="Awareness", raw_response="Allbirds are comfy shoes, found at Zappos for $50.")
        _mention(conn, 2, PRIMARY_ID, mentioned=1, strength="Primary", position=1)
        _price_obs(conn, 2, PRIMARY_ID, stated_price=50, merchant_name="Zappos", attribution_status="mapped")

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result["run_id"] == 1
    assert result["selection_tier"] == 1
    assert result["narrative_case"] == "value_gap"
    assert "Zappos" in result["leaked"]


def test_tier1_ranks_by_largest_ground_truth_delta_then_most_competitor_deals(db):
    with db.begin() as conn:
        _seed_entities(conn)
        # run 1: small gt delta (10%)
        _run(conn, 1, raw_response="Allbirds is $110 here.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary")
        _incentive(conn, 1, PRIMARY_ID, stated_price=110, ground_truth_true_cost=100, net_price_accuracy=False)
        # run 2: big gt delta (50%) — should win
        _run(conn, 2, raw_response="Allbirds is $150 here.")
        _mention(conn, 2, PRIMARY_ID, mentioned=1, strength="Primary")
        _incentive(conn, 2, PRIMARY_ID, stated_price=150, ground_truth_true_cost=100, net_price_accuracy=False)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result["run_id"] == 2
    assert result["selection_tier"] == 1


def test_tier1_leak_from_competitor_deal_cited_while_primary_is_not(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, stage="Comparison", raw_response="Nike has 25% off. Allbirds also shown.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Positive", deal_cited=0)
        _mention(conn, 1, COMPETITOR_ID, mentioned=1, deal_cited=1, deal_types='["discount_pct"]')

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result["run_id"] == 1
    assert result["narrative_case"] == "value_gap"
    assert "Nike" in result["leaked"]


# ─── Tier 3: mentioned, no leak ─────────────────────────────────────────────

def test_tier3_mentioned_no_leak_ranks_by_weakest_visibility_signal(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, raw_response="Allbirds is a fine pick, worth considering.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary", position=1)
        _run(conn, 2, raw_response="Allbirds is also mentioned, briefly, near the end.")
        _mention(conn, 2, PRIMARY_ID, mentioned=1, strength="Neutral", position=5)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result["run_id"] == 2
    assert result["selection_tier"] == 3
    assert result["narrative_case"] == "mentioned_no_leak"


# ─── Tier 4: not mentioned ──────────────────────────────────────────────────

def test_tier4_not_mentioned_ranks_purchase_intent_then_most_competitors(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, stage="Awareness", raw_response="Nike and Adidas are popular running shoes.")
        _mention(conn, 1, PRIMARY_ID, mentioned=0)
        _mention(conn, 1, COMPETITOR_ID, mentioned=1)
        _run(conn, 2, stage="Ready to Buy", raw_response="Nike is the best choice for running shoes.")
        _mention(conn, 2, PRIMARY_ID, mentioned=0)
        _mention(conn, 2, COMPETITOR_ID, mentioned=1)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result["run_id"] == 2  # purchase-intent stage wins over run 1
    assert result["selection_tier"] == 4
    assert result["narrative_case"] == "not_mentioned"
    assert "Nike" in result["leaked"]


# ─── Tier 5: uncoded fallback ───────────────────────────────────────────────

def test_tier5_uncoded_run_is_earliest_successful_run(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 5, raw_response="Some uncoded answer.")
        _run(conn, 3, raw_response="An earlier uncoded answer.")

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result["run_id"] == 3
    assert result["selection_tier"] == 5
    assert result["narrative_case"] == "uncoded"


def test_zero_successful_runs_returns_none(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, status="error", raw_response=None)

    with db.connect() as conn:
        assert select_transcript(conn, CYCLE_ID, PRIMARY_ID) is None


def test_no_runs_at_all_returns_none(db):
    with db.begin() as conn:
        _seed_entities(conn)

    with db.connect() as conn:
        assert select_transcript(conn, CYCLE_ID, PRIMARY_ID) is None


# ─── Span location ──────────────────────────────────────────────────────────

def test_spans_locate_brand_name_and_alias_and_offsite_price_range(db):
    with db.begin() as conn:
        _seed_entities(conn, aliases='["The Wool Runner"]')
        _run(conn, 1, raw_response=(
            "Allbirds is a strong pick — The Wool Runner runs about $275-$325 "
            "depending on size, per Zappos."
        ))
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary")
        _price_obs(conn, 1, PRIMARY_ID, stated_price=300, merchant_name="Zappos", attribution_status="mapped")

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    kinds = {(s["kind"]) for s in result["spans"]}
    assert "brand" in kinds
    assert "value_claim" in kinds
    brand_spans = [s for s in result["spans"] if s["kind"] == "brand"]
    assert len(brand_spans) == 2  # "Allbirds" once, "The Wool Runner" once
    for s in result["spans"]:
        assert result["response_text"][s["start"]:s["end"]]


def test_unlocatable_claim_appears_in_leaked_text_only_not_as_a_span(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, raw_response="Allbirds is a strong pick for shoes.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary")
        # price observation whose price/merchant text isn't actually in the response
        _price_obs(conn, 1, PRIMARY_ID, stated_price=999, merchant_name="SomeStore", attribution_status="mapped")

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    value_claim_spans = [s for s in result["spans"] if s["kind"] == "value_claim"]
    assert value_claim_spans == []
    assert "leaked" in result


# ─── Determinism ────────────────────────────────────────────────────────────

def test_selection_is_deterministic_across_repeated_calls(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, raw_response="Allbirds is $110 here.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary")
        _incentive(conn, 1, PRIMARY_ID, stated_price=110, ground_truth_true_cost=100, net_price_accuracy=False)
        _run(conn, 2, raw_response="Allbirds is $115 here too.")
        _mention(conn, 2, PRIMARY_ID, mentioned=1, strength="Primary")
        _incentive(conn, 2, PRIMARY_ID, stated_price=115, ground_truth_true_cost=100, net_price_accuracy=False)

    with db.connect() as conn:
        results = [select_transcript(conn, CYCLE_ID, PRIMARY_ID) for _ in range(5)]

    assert all(r["run_id"] == results[0]["run_id"] for r in results)
    assert all(r["selection_tier"] == results[0]["selection_tier"] for r in results)


# ─── Token/cycle scoping ────────────────────────────────────────────────────

def test_never_crosses_cycle_boundary(db):
    with db.begin() as conn:
        _seed_entities(conn, cycle_id=CYCLE_ID)
        conn.exec_driver_sql(
            "INSERT INTO soa_cycle_entities (cycle_id, entity_id, role) VALUES (?, ?, 'primary')",
            (OTHER_CYCLE_ID, PRIMARY_ID),
        )
        _run(conn, 1, cycle_id=OTHER_CYCLE_ID, raw_response="A different cycle's answer entirely.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary")

    with db.connect() as conn:
        assert select_transcript(conn, CYCLE_ID, PRIMARY_ID) is None
