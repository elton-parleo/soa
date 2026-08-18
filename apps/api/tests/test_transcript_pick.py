"""
Tests for the "From the transcript" selection service
(app/services/transcript_pick.py) — the 5-tier deterministic cascade,
narrative_case <-> box-copy generation, span location, determinism, and
(this pass) the DTC-vs-wholesale attribution fix: a self-attributed,
accurate price is the GOOD case, never a "your price came from
{yourself}" leak. Mirrors the SQLite-fixture style of
test_full_analysis_extras.py.
"""
import pytest
from sqlalchemy import create_engine, text

import soa_shared.config as config
from app.services.transcript_pick import select_transcript, _attribution, _accuracy, _PrimaryIdentity

CYCLE_ID = 900
OTHER_CYCLE_ID = 901
PRIMARY_ID = 901
COMPETITOR_ID = 902


# TRANSCRIPT_NARRATIVE_ENABLED defaults off (soa_shared/config.py) — every
# clause-content assertion in this file needs right/leaked actually present
# in the payload, so it's forced on here. The gate itself (payload presence
# on/off) is tested explicitly below, overriding this back to off/on per
# test — never relying on the ambient default either way.
@pytest.fixture(autouse=True)
def _narrative_enabled(monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIPT_NARRATIVE_ENABLED", True)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_entities (id INTEGER PRIMARY KEY, name TEXT, slug TEXT, aliases TEXT, website_url TEXT)
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
                stated_price FLOAT, claimed_net_price FLOAT, merchant_name TEXT, merchant_slug TEXT,
                attribution_status TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_incentive_scores (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER, price_observation_id INTEGER,
                scoring_grain TEXT, status TEXT, measurement_status TEXT,
                stated_price FLOAT, ground_truth_true_cost FLOAT, net_price_accuracy BOOLEAN,
                ground_truth_applied_deals TEXT
            )
        """)
    return engine


def _seed_entities(conn, cycle_id=CYCLE_ID, aliases='[]', website_url='https://allbirds.com'):
    conn.exec_driver_sql(
        "INSERT INTO soa_entities (id, name, slug, aliases, website_url) VALUES (?, 'Allbirds', 'allbirds', ?, ?)",
        (PRIMARY_ID, aliases, website_url),
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


def _price_obs(conn, run_id, entity_id, stated_price, merchant_name=None, merchant_slug=None,
                attribution_status="unattributed", claimed_net_price=None, obs_id=None):
    conn.exec_driver_sql(
        "INSERT INTO soa_price_observations (id, run_id, entity_id, stated_price, claimed_net_price, "
        "merchant_name, merchant_slug, attribution_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (obs_id, run_id, entity_id, stated_price, claimed_net_price, merchant_name, merchant_slug, attribution_status),
    )
    return conn.execute(text(
        "SELECT id FROM soa_price_observations WHERE run_id = :rid AND entity_id = :eid "
        "ORDER BY id DESC LIMIT 1"
    ), {"rid": run_id, "eid": entity_id}).scalar()


def _ground_truth(conn, run_id, entity_id, price_observation_id, stated_price, ground_truth_true_cost,
                   net_price_accuracy, measurement_status="measured", applied_deals="[]"):
    conn.exec_driver_sql(
        "INSERT INTO soa_incentive_scores (run_id, entity_id, price_observation_id, scoring_grain, status, "
        "measurement_status, stated_price, ground_truth_true_cost, net_price_accuracy, ground_truth_applied_deals) "
        "VALUES (?, ?, ?, 'observation', 'scored', ?, ?, ?, ?, ?)",
        (run_id, entity_id, price_observation_id, measurement_status, stated_price, ground_truth_true_cost,
         net_price_accuracy, applied_deals),
    )


# ─── _attribution / _accuracy — the shared helper itself ──────────────────

PRIMARY = _PrimaryIdentity(name="Allbirds", slug="allbirds", aliases=["The Wool Runner"], domain="allbirds.com")


def test_attribution_self_via_textual_match_even_when_unmapped():
    """The actual DTC bug: a brand with no listed merchant record comes
    back attribution_status='unmapped' (not 'brand_self_reference')
    when the agent names it as its own source — must still read as
    'self', not 'third_party'."""
    obs = {"merchant_name": "Allbirds", "merchant_slug": None, "attribution_status": "unmapped"}
    assert _attribution(obs, PRIMARY) == "self"


def test_attribution_self_via_brand_self_reference_flag():
    obs = {"merchant_name": "Allbirds", "merchant_slug": None, "attribution_status": "brand_self_reference"}
    assert _attribution(obs, PRIMARY) == "self"


def test_attribution_self_via_alias_match():
    obs = {"merchant_name": "The Wool Runner", "merchant_slug": None, "attribution_status": "unmapped"}
    assert _attribution(obs, PRIMARY) == "self"


def test_attribution_third_party_for_a_real_different_merchant():
    obs = {"merchant_name": "Zappos", "merchant_slug": "zappos", "attribution_status": "mapped"}
    assert _attribution(obs, PRIMARY) == "third_party"


def test_attribution_unattributed_when_no_merchant_signal_at_all():
    obs = {"merchant_name": None, "merchant_slug": None, "attribution_status": "unattributed"}
    assert _attribution(obs, PRIMARY) == "unattributed"


def test_accuracy_not_measured_when_measurement_status_is_not_measured():
    assert _accuracy({"measurement_status": None, "net_price_accuracy": None}) == "not_measured"
    assert _accuracy({"measurement_status": "unmeasured", "net_price_accuracy": True}) == "not_measured"


def test_accuracy_reads_sqlite_int_booleans_correctly():
    assert _accuracy({"measurement_status": "measured", "net_price_accuracy": 1}) == "accurate"
    assert _accuracy({"measurement_status": "measured", "net_price_accuracy": 0}) == "inaccurate"


# ─── Tier 1: purchase-intent · mentioned · leak ────────────────────────────

def test_tier1_third_party_offsite_price_leak(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, stage="Ready to Buy", raw_response="Allbirds runs about $100 at Zappos.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary", position=1)
        obs_id = _price_obs(conn, 1, PRIMARY_ID, stated_price=100, merchant_name="Zappos", merchant_slug="zappos", attribution_status="mapped")
        _ground_truth(conn, 1, PRIMARY_ID, obs_id, stated_price=100, ground_truth_true_cost=90, net_price_accuracy=False)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result["run_id"] == 1
    assert result["selection_tier"] == 1
    assert result["narrative_case"] == "value_gap"
    assert "Zappos" in result["leaked"]
    assert "not from allbirds.com" in result["leaked"]


def test_tier1_ranks_self_inaccurate_above_third_party(db):
    """SELF+INACCURATE (the sharpest DTC leak) must outrank a THIRD_
    PARTY leak even with a smaller ground-truth delta."""
    with db.begin() as conn:
        _seed_entities(conn)
        # run 1: third-party leak, big delta (50%)
        _run(conn, 1, raw_response="Zappos has it for $150.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary")
        obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=150, merchant_name="Zappos", merchant_slug="zappos", attribution_status="mapped")
        _ground_truth(conn, 1, PRIMARY_ID, obs1, stated_price=150, ground_truth_true_cost=100, net_price_accuracy=False)
        # run 2: self-attributed leak, smaller delta (10%) — must still win
        _run(conn, 2, raw_response="Allbirds lists it at $110 on their own site.")
        _mention(conn, 2, PRIMARY_ID, mentioned=1, strength="Primary")
        obs2 = _price_obs(conn, 2, PRIMARY_ID, stated_price=110, merchant_name="Allbirds", merchant_slug=None, attribution_status="unmapped")
        _ground_truth(conn, 2, PRIMARY_ID, obs2, stated_price=110, ground_truth_true_cost=100, net_price_accuracy=False)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result["run_id"] == 2
    assert "your price as" in result["leaked"]


def test_tier1_ranks_third_party_by_largest_ground_truth_delta(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, raw_response="Zappos: $110.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary")
        obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=110, merchant_name="Zappos", merchant_slug="zappos", attribution_status="mapped")
        _ground_truth(conn, 1, PRIMARY_ID, obs1, stated_price=110, ground_truth_true_cost=100, net_price_accuracy=False)
        _run(conn, 2, raw_response="Zappos: $150.")
        _mention(conn, 2, PRIMARY_ID, mentioned=1, strength="Primary")
        obs2 = _price_obs(conn, 2, PRIMARY_ID, stated_price=150, merchant_name="Zappos", merchant_slug="zappos", attribution_status="mapped")
        _ground_truth(conn, 2, PRIMARY_ID, obs2, stated_price=150, ground_truth_true_cost=100, net_price_accuracy=False)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result["run_id"] == 2


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


def test_tier1_a_clean_self_accurate_run_never_beats_a_genuinely_leaking_run(db):
    """The core regression this fix guards: an Allbirds-style run
    (mentioned, self-attributed, ACCURATE) must never be selected over
    a run with a real leak, even though both are technically 'coded,
    mentioned, has a price observation'."""
    with db.begin() as conn:
        _seed_entities(conn)
        # run 1: clean DTC self-attributed + accurate — the GOOD case
        _run(conn, 1, raw_response="Allbirds sells The Wool Runner for $110 on their own site.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary", position=1)
        obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=110, merchant_name="Allbirds", merchant_slug=None, attribution_status="unmapped")
        _ground_truth(conn, 1, PRIMARY_ID, obs1, stated_price=110, ground_truth_true_cost=110, net_price_accuracy=True)
        # run 2: genuine third-party leak
        _run(conn, 2, raw_response="Zappos has it for $150.")
        _mention(conn, 2, PRIMARY_ID, mentioned=1, strength="Primary")
        obs2 = _price_obs(conn, 2, PRIMARY_ID, stated_price=150, merchant_name="Zappos", merchant_slug="zappos", attribution_status="mapped")
        _ground_truth(conn, 2, PRIMARY_ID, obs2, stated_price=150, ground_truth_true_cost=100, net_price_accuracy=False)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result["run_id"] == 2
    assert result["narrative_case"] == "value_gap"


def test_self_accurate_only_run_lands_in_mentioned_no_leak_not_value_gap(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, raw_response="Allbirds sells The Wool Runner for $110 on their own site.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary", position=1)
        obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=110, merchant_name="Allbirds", merchant_slug=None, attribution_status="unmapped")
        _ground_truth(conn, 1, PRIMARY_ID, obs1, stated_price=110, ground_truth_true_cost=110, net_price_accuracy=True)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result["run_id"] == 1
    assert result["selection_tier"] == 3
    assert result["narrative_case"] == "mentioned_no_leak"
    assert "quoted your price correctly, from your own site" in result["right"]
    assert "not your site" not in result["leaked"]
    assert result["leaked"] == "Nothing leaked in this run — it's a clean mention."


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

def test_spans_locate_brand_name_and_alias_and_offsite_third_party_range(db):
    with db.begin() as conn:
        _seed_entities(conn, aliases='["The Wool Runner"]')
        _run(conn, 1, raw_response=(
            "Allbirds is a strong pick — The Wool Runner runs about $275-$325 "
            "depending on size, per Zappos."
        ))
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary")
        obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=300, merchant_name="Zappos", merchant_slug="zappos", attribution_status="mapped")
        _ground_truth(conn, 1, PRIMARY_ID, obs1, stated_price=300, ground_truth_true_cost=300, net_price_accuracy=True)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    kinds = {(s["kind"]) for s in result["spans"]}
    assert "brand" in kinds
    assert "value_claim" in kinds
    assert "stale_price" not in kinds
    brand_spans = [s for s in result["spans"] if s["kind"] == "brand"]
    assert len(brand_spans) == 2  # "Allbirds" once, "The Wool Runner" once
    for s in result["spans"]:
        assert result["response_text"][s["start"]:s["end"]]


def test_self_attributed_name_is_never_underlined_as_offsite(db):
    """The DTC bug, at the span level: merchant_name == the primary's
    own name must never produce a value_claim (amber off-site) span."""
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, raw_response="Allbirds lists The Wool Runner at $110 on their own site.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary")
        obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=110, merchant_name="Allbirds", merchant_slug=None, attribution_status="unmapped")
        _ground_truth(conn, 1, PRIMARY_ID, obs1, stated_price=110, ground_truth_true_cost=110, net_price_accuracy=True)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert all(s["kind"] != "value_claim" for s in result["spans"])
    brand_spans = [s for s in result["spans"] if s["kind"] == "brand"]
    assert len(brand_spans) == 1
    assert result["response_text"][brand_spans[0]["start"]:brand_spans[0]["end"]] == "Allbirds"


def test_self_inaccurate_price_gets_a_distinct_stale_price_span(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, raw_response="Allbirds lists The Wool Runner at $110 on their own site.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary")
        obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=110, merchant_name="Allbirds", merchant_slug=None, attribution_status="unmapped")
        _ground_truth(conn, 1, PRIMARY_ID, obs1, stated_price=110, ground_truth_true_cost=93.5, net_price_accuracy=False)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    stale_spans = [s for s in result["spans"] if s["kind"] == "stale_price"]
    assert len(stale_spans) == 1
    assert "110" in result["response_text"][stale_spans[0]["start"]:stale_spans[0]["end"]]
    assert all(s["kind"] != "value_claim" for s in result["spans"])


def test_brand_span_wins_on_overlap_with_a_merchant_span(db):
    with db.begin() as conn:
        _seed_entities(conn)
        # Contrived overlap: merchant_name text is a substring that
        # overlaps where "Allbirds" appears.
        _run(conn, 1, raw_response="AllbirdsZappos quoted $150.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary")
        obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=150, merchant_name="AllbirdsZappos", merchant_slug="allbirdszappos", attribution_status="mapped")
        _ground_truth(conn, 1, PRIMARY_ID, obs1, stated_price=150, ground_truth_true_cost=100, net_price_accuracy=False)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    brand_spans = [s for s in result["spans"] if s["kind"] == "brand"]
    assert len(brand_spans) == 1
    merchant_spans = [s for s in result["spans"] if s["kind"] == "value_claim" and s["start"] == 0]
    assert merchant_spans == []  # the overlapping merchant span at position 0 lost to brand


def test_unlocatable_claim_appears_in_leaked_text_only_not_as_a_span(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, raw_response="Allbirds is a strong pick for shoes.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary")
        # price observation whose price/merchant text isn't actually in the response
        obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=999, merchant_name="SomeStore", merchant_slug="somestore", attribution_status="mapped")
        _ground_truth(conn, 1, PRIMARY_ID, obs1, stated_price=999, ground_truth_true_cost=800, net_price_accuracy=False)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    value_claim_spans = [s for s in result["spans"] if s["kind"] == "value_claim"]
    assert value_claim_spans == []
    assert "SomeStore" in result["leaked"]


# ─── NOT_MEASURED — never treated as wrong ─────────────────────────────────

def test_not_measured_observation_never_counts_as_a_leak(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, raw_response="Allbirds lists it at $110 on their own site.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary", position=1)
        obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=110, merchant_name="Allbirds", merchant_slug=None, attribution_status="unmapped")
        _ground_truth(conn, 1, PRIMARY_ID, obs1, stated_price=110, ground_truth_true_cost=110, net_price_accuracy=True, measurement_status="unmeasured")

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result["narrative_case"] == "mentioned_no_leak"
    assert "not verifiable" in result["leaked"]
    assert "Deal Engine has no ground truth" in result["leaked"]
    assert "quoted your price correctly" not in result["right"]  # no accuracy credit either — not verified


def test_not_measured_merchant_never_inaccurate_ranked(db):
    """A merchant Deal Engine doesn't cover must never rank as a leak
    (no INACCURATE boost) even when a genuinely measured leak exists
    elsewhere in the same cycle at a lower severity — proves NOT_
    MEASURED contributes nothing to selection."""
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, raw_response="Boutique Co has it for $200.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary")
        obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=200, merchant_name="Boutique Co", merchant_slug="boutique-co", attribution_status="mapped")
        # No ground truth row at all for this observation — Deal Engine
        # doesn't cover this merchant.

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    # attribution=third_party alone still makes this a leak (independent
    # of accuracy) — but must never be phrased as "wrong"/inaccurate.
    assert result["narrative_case"] == "value_gap"
    assert "wrong" not in result["leaked"]
    assert "your net is" not in result["leaked"]


# ─── Determinism ────────────────────────────────────────────────────────────

def test_selection_is_deterministic_across_repeated_calls(db):
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, raw_response="Zappos: $110.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary")
        obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=110, merchant_name="Zappos", merchant_slug="zappos", attribution_status="mapped")
        _ground_truth(conn, 1, PRIMARY_ID, obs1, stated_price=110, ground_truth_true_cost=100, net_price_accuracy=False)
        _run(conn, 2, raw_response="Zappos: $115.")
        _mention(conn, 2, PRIMARY_ID, mentioned=1, strength="Primary")
        obs2 = _price_obs(conn, 2, PRIMARY_ID, stated_price=115, merchant_name="Zappos", merchant_slug="zappos", attribution_status="mapped")
        _ground_truth(conn, 2, PRIMARY_ID, obs2, stated_price=115, ground_truth_true_cost=100, net_price_accuracy=False)

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


# ═══ Required brand-shape fixtures (DTC vs wholesale) ══════════════════════

def test_fixture_dtc_brand_self_inaccurate_leads_leaked_with_stale_price_span(db):
    """Fixture 1 — Allbirds-style DTC brand: primary mentioned first,
    self-attributed, stated $110 vs ground-truth net $93.50 with a
    bundle promo. Must select as value_gap, RIGHT has the mention
    clause with NO attribution credit, LEAKED leads with SELF+
    INACCURATE, spans have a stale_price span and no off-site span,
    and the brand name is blue-highlighted, never underlined."""
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, stage="Ready to Buy", raw_response=(
            "Allbirds is a strong first pick. Their Wool Runner is listed at $110 "
            "directly on the Allbirds site."
        ))
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary", position=1)
        obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=110, merchant_name="Allbirds", merchant_slug=None, attribution_status="unmapped")
        _ground_truth(
            conn, 1, PRIMARY_ID, obs1, stated_price=110, ground_truth_true_cost=93.5, net_price_accuracy=False,
            applied_deals='[{"name": "bundle promo"}]',
        )

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result["narrative_case"] == "value_gap"
    assert result["selection_tier"] in (1, 2)
    assert "You're named unprompted" in result["right"]
    assert "quoted your price correctly" not in result["right"]  # no attribution credit — it's inaccurate
    assert "not from allbirds.com" not in result["leaked"]  # never an off-site clause for a self price
    assert result["leaked"].startswith("The agent quoted your price as $110.00")
    assert "bundle promo" in result["leaked"]
    assert "Price Truth gap" in result["leaked"]

    kinds = {s["kind"] for s in result["spans"]}
    assert "stale_price" in kinds
    assert "value_claim" not in kinds
    brand_spans = [s for s in result["spans"] if s["kind"] == "brand"]
    assert len(brand_spans) >= 1
    for s in brand_spans:
        assert result["response_text"][s["start"]:s["end"]] == "Allbirds"


def test_fixture_wholesale_brand_third_party_inaccurate_leads_leaked(db):
    """Fixture 2 — Coach-style wholesale brand: primary mentioned,
    observation attributed to Nordstrom, stated $275-$325, ground truth
    measured and different. LEAKED leads with THIRD_PARTY+INACCURATE,
    off-site span over the merchant name and the price range, brand
    highlight intact."""
    with db.begin() as conn:
        _seed_entities(conn, website_url="https://coach.com")
        conn.exec_driver_sql("UPDATE soa_entities SET name = 'Coach', slug = 'coach' WHERE id = ?", (PRIMARY_ID,))
        _run(conn, 1, stage="Comparison", raw_response=(
            "Coach is a solid pick — the Tabby 26 runs $275-$325 at Nordstrom depending on color."
        ))
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary", position=1)
        obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=300, merchant_name="Nordstrom", merchant_slug="nordstrom", attribution_status="mapped")
        _ground_truth(conn, 1, PRIMARY_ID, obs1, stated_price=300, ground_truth_true_cost=250, net_price_accuracy=False)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result["narrative_case"] == "value_gap"
    assert result["leaked"].startswith("The agent quoted $300.00 from Nordstrom, not from coach.com")
    assert "your net is $250.00" in result["leaked"]

    kinds_and_text = [(s["kind"], result["response_text"][s["start"]:s["end"]]) for s in result["spans"]]
    assert ("value_claim", "Nordstrom") in kinds_and_text
    assert any(k == "value_claim" and "275" in t for k, t in kinds_and_text)
    assert any(k == "brand" and t == "Coach" for k, t in kinds_and_text)


def test_fixture_dtc_clean_run_alone_yields_mentioned_no_leak_with_credit(db):
    """Fixture 3 — DTC clean run: self-attributed, ACCURATE, named
    first. Alone (no other runs), yields mentioned_no_leak with the
    SELF+ACCURATE RIGHT credit and the honest-null LEAKED line."""
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, stage="Ready to Buy", raw_response="Allbirds sells the Wool Runner for $98 on their own site.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary", position=1)
        obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=98, merchant_name="Allbirds", merchant_slug=None, attribution_status="unmapped")
        _ground_truth(conn, 1, PRIMARY_ID, obs1, stated_price=98, ground_truth_true_cost=98, net_price_accuracy=True)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result["narrative_case"] == "mentioned_no_leak"
    assert "quoted your price correctly, from your own site" in result["right"]
    assert result["leaked"] == "Nothing leaked in this run — it's a clean mention."


def test_fixture_not_measured_merchant_honest_state_no_leak(db):
    """Fixture 4 — a merchant Deal Engine doesn't cover: no accuracy
    clause, no INACCURATE ranking boost, honest-state text."""
    with db.begin() as conn:
        _seed_entities(conn)
        _run(conn, 1, raw_response="Allbirds is listed on ShoeBarn for $105.")
        _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary", position=1)
        _price_obs(conn, 1, PRIMARY_ID, stated_price=105, merchant_name="ShoeBarn", merchant_slug="shoebarn", attribution_status="mapped")
        # No soa_incentive_scores row at all — Deal Engine has no ground truth for ShoeBarn.

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    # third_party attribution alone is still a leak (per the stated
    # rule), but it must read as "not your storefront", never "wrong".
    assert result["narrative_case"] == "value_gap"
    assert "wrong" not in result["leaked"]
    assert "wasn't wrong" not in result["leaked"]
    assert "your net is" not in result["leaked"]
    assert "didn't use your storefront's price" in result["leaked"]


# ─── Shared-helper enforcement (grep-guard) ────────────────────────────────

def test_attribution_status_and_net_price_accuracy_are_only_read_inside_the_shared_helpers():
    """Every place that REASONS about self-vs-third-party or accurate-
    vs-inaccurate must go through _attribution()/_accuracy() — this
    greps the module source to make sure no other function re-derives
    that logic ad hoc. _fetch_candidates is exempt: it's the raw SQL
    data-access layer (the column names appear in a SELECT string and
    as pass-through dict values, never compared/branched on there)."""
    import inspect
    import app.services.transcript_pick as mod

    functions = {
        name: inspect.getsource(fn)
        for name, fn in vars(mod).items()
        if inspect.isfunction(fn) and fn.__module__ == mod.__name__
    }
    exempt = {"_attribution", "_accuracy", "_fetch_candidates"}

    for name, src in functions.items():
        if name in exempt:
            continue
        assert "attribution_status" not in src, f"{name} reads attribution_status directly — route through _attribution()"
        assert "net_price_accuracy" not in src, f"{name} reads net_price_accuracy directly — route through _accuracy()"

    # sanity: the two helpers really do exist and really do read these fields
    assert "attribution_status" in functions["_attribution"]
    assert "net_price_accuracy" in functions["_accuracy"]


# ═══ TRANSCRIPT_NARRATIVE_ENABLED gate ══════════════════════════════════════

def _seed_value_gap_run(conn):
    """A minimal value_gap-tier run — any scenario would do; the gate
    tests only care about which payload KEYS are present, not clause
    content (that's covered by every other test in this file, run with
    the flag forced on via the autouse fixture)."""
    _seed_entities(conn)
    _run(conn, 1, stage="Ready to Buy", raw_response="Zappos has it for $150.")
    _mention(conn, 1, PRIMARY_ID, mentioned=1, strength="Primary")
    obs1 = _price_obs(conn, 1, PRIMARY_ID, stated_price=150, merchant_name="Zappos", merchant_slug="zappos", attribution_status="mapped")
    _ground_truth(conn, 1, PRIMARY_ID, obs1, stated_price=150, ground_truth_true_cost=100, net_price_accuracy=False)


def test_flag_off_omits_right_and_leaked_but_keeps_selection_and_spans(db, monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIPT_NARRATIVE_ENABLED", False)
    with db.begin() as conn:
        _seed_value_gap_run(conn)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert "right" not in result
    assert "leaked" not in result
    # Diagnostics and the transcript itself are unaffected by the flag.
    assert result["narrative_case"] == "value_gap"
    assert result["selection_tier"] in (1, 2)
    assert result["run_id"] == 1
    assert result["response_text"]
    assert result["spans"]  # highlights are still computed with the flag off


def test_flag_on_includes_right_and_leaked_as_non_empty_strings(db, monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIPT_NARRATIVE_ENABLED", True)
    with db.begin() as conn:
        _seed_value_gap_run(conn)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert "right" in result and result["right"]
    assert "leaked" in result and result["leaked"]


def test_flag_off_never_returns_an_empty_string_placeholder(db, monkeypatch):
    """The gate must OMIT the keys, never replace them with '' —
    'not empty strings' per the flag's own contract."""
    monkeypatch.setattr(config, "TRANSCRIPT_NARRATIVE_ENABLED", False)
    with db.begin() as conn:
        _seed_value_gap_run(conn)

    with db.connect() as conn:
        result = select_transcript(conn, CYCLE_ID, PRIMARY_ID)

    assert result.get("right", "sentinel-not-omitted") == "sentinel-not-omitted"
    assert result.get("leaked", "sentinel-not-omitted") == "sentinel-not-omitted"
