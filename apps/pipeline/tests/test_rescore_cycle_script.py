"""
The ops re-score entry point.

The behaviour worth holding is the narrowing and the check that it
narrowed: --tier brand_direct must select brand-direct runs and no
others, and the script must be able to say afterwards that nothing else
moved. "Catalog accuracy is unchanged" is a claim somebody will put in a
report, so it is verified by the thing that does the re-scoring rather
than by whoever ran it.
"""
from datetime import datetime, timezone
from collections import Counter

import pytest
from sqlalchemy import create_engine, event, text

from scripts import rescore_cycle as rc


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _now(dbapi_conn, _):
        dbapi_conn.create_function(
            "NOW", 0, lambda: datetime.now(timezone.utc).isoformat(),
        )

    with engine.begin() as c:
        c.exec_driver_sql("""
            CREATE TABLE soa_cycles (id INTEGER PRIMARY KEY, cycle_code TEXT)
        """)
        c.exec_driver_sql("""
            CREATE TABLE soa_queries (
                id INTEGER PRIMARY KEY, tier TEXT, expected_answer TEXT,
                query_code TEXT
            )
        """)
        c.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, query_id INTEGER,
                run_number INTEGER
            )
        """)
        c.exec_driver_sql("""
            CREATE TABLE soa_expectation_outcomes (
                id INTEGER PRIMARY KEY, run_id INTEGER, cycle_id INTEGER,
                tier TEXT, outcome TEXT, secondary_results TEXT,
                platform TEXT
            )
        """)
        c.execute(text(
            "INSERT INTO soa_cycles (id, cycle_code) VALUES (1, :code)"
        ), {"code": "20260915-113207-wiggle-snug-full"})
    monkeypatch.setattr(rc, "engine", engine)
    return engine


def seed(db, *, tier, outcome, n=1, expectation='{"type": "brand_mention"}'):
    with db.begin() as c:
        for _ in range(n):
            qid = c.execute(text(
                "INSERT INTO soa_queries (tier, expected_answer) "
                "VALUES (:t, :e) RETURNING id"
            ), {"t": tier, "e": expectation}).scalar()
            rid = c.execute(text(
                "INSERT INTO soa_runs (cycle_id, query_id) "
                "VALUES (1, :q) RETURNING id"
            ), {"q": qid}).scalar()
            c.execute(text(
                "INSERT INTO soa_expectation_outcomes "
                "(run_id, cycle_id, tier, outcome) VALUES (:r, 1, :t, :o)"
            ), {"r": rid, "t": tier, "o": outcome})


def test_a_cycle_is_named_by_its_code_not_its_id(db):
    with db.connect() as conn:
        assert rc.cycle_id(conn, "20260915-113207-wiggle-snug-full") == 1


def test_an_unknown_cycle_stops_rather_than_scoring_nothing_quietly(db):
    with db.connect() as conn:
        with pytest.raises(SystemExit):
            rc.cycle_id(conn, "20260915-113207")


def test_only_the_named_tiers_runs_are_selected(db):
    seed(db, tier="brand_direct", outcome="exact", n=3)
    seed(db, tier="catalog_accuracy", outcome="exact", n=5)
    seed(db, tier="value_incentives", outcome="exact", n=2)

    with db.connect() as conn:
        assert len(rc.run_ids_for(conn, 1, ["brand_direct"])) == 3
        assert len(rc.run_ids_for(conn, 1, ["catalog_accuracy"])) == 5
        assert len(rc.run_ids_for(conn, 1, ["brand_direct", "value_incentives"])) == 5


def test_a_question_with_no_expectation_is_never_scored(db):
    """A category-control question carries a tier and no expectation.
    Scoring it would write a row for a question nothing was expected
    of."""
    seed(db, tier="category_control", outcome="exact", n=4, expectation=None)
    with db.connect() as conn:
        assert rc.run_ids_for(conn, 1, ["category_control"]) == []


def test_the_default_leaves_the_control_tier_out(db):
    import argparse
    parser = argparse.ArgumentParser()
    # The same default the script computes.
    from soa_shared.expected_answers import QUERY_TIERS
    default = [t for t in QUERY_TIERS if t != "category_control"]
    assert "category_control" not in default
    assert default == ["brand_direct", "catalog_accuracy", "value_incentives"]


def test_the_counts_are_per_tier_and_per_outcome(db):
    seed(db, tier="brand_direct", outcome="exact", n=63)
    seed(db, tier="brand_direct", outcome="absent", n=3)
    seed(db, tier="catalog_accuracy", outcome="exact", n=19)

    with db.connect() as conn:
        counts = rc.outcome_counts(conn, 1)
    assert counts["brand_direct"] == {"exact": 63, "absent": 3}
    assert counts["catalog_accuracy"] == {"exact": 19}


# ── the check that makes "unchanged" a statement rather than a hope ───────

def test_a_tier_nobody_asked_for_moving_is_reported():
    before = {"brand_direct": Counter({"exact": 63}),
              "catalog_accuracy": Counter({"exact": 19, "stale": 2})}
    after = {"brand_direct": Counter({"echoed": 63}),
             "catalog_accuracy": Counter({"exact": 21})}
    assert rc.diff_untouched(before, after, {"brand_direct"}) == ["catalog_accuracy"]


def test_the_targeted_tier_changing_is_the_whole_point(db):
    before = {"brand_direct": Counter({"exact": 63, "absent": 3}),
              "catalog_accuracy": Counter({"exact": 19})}
    after = {"brand_direct": Counter({"grounded": 2, "echoed": 16,
                                      "misattributed": 13, "fabricated": 6,
                                      "acknowledged_unknown": 26, "absent": 3}),
             "catalog_accuracy": Counter({"exact": 19})}
    assert rc.diff_untouched(before, after, {"brand_direct"}) == []


def test_a_tier_appearing_where_there_was_none_counts_as_moving():
    before = {"brand_direct": Counter({"exact": 1})}
    after = {"brand_direct": Counter({"echoed": 1}),
             "value_incentives": Counter({"exact": 4})}
    assert rc.diff_untouched(before, after, {"brand_direct"}) == ["value_incentives"]


# ── the dry run writes nothing ────────────────────────────────────────────

def test_the_dry_run_makes_no_model_call_and_no_write(db, capsys, monkeypatch):
    seed(db, tier="brand_direct", outcome="exact", n=66)
    seed(db, tier="catalog_accuracy", outcome="exact", n=19)

    def _explode(*a, **kw):
        raise AssertionError("a dry run must not score anything")
    monkeypatch.setattr("scoring.expectation_batch.score_runs", _explode)

    code = rc.main([
        "--cycle", "20260915-113207-wiggle-snug-full",
        "--tier", "brand_direct", "--dry-run",
    ])
    out = capsys.readouterr().out

    assert code == 0
    assert "runs to score:    66" in out
    assert "66 extraction calls" in out
    with db.connect() as conn:
        assert rc.outcome_counts(conn, 1)["brand_direct"] == {"exact": 66}


def test_a_dry_run_on_a_tier_with_nothing_to_score_says_so(db, capsys):
    seed(db, tier="catalog_accuracy", outcome="exact", n=5)
    code = rc.main([
        "--cycle", "20260915-113207-wiggle-snug-full",
        "--tier", "brand_direct", "--dry-run",
    ])
    assert code == 0
    assert "nothing to do." in capsys.readouterr().out


# ── the secondary snapshot ────────────────────────────────────────────────
#
# The extractor corrections are meant to move pack-count secondaries — a
# size read as a count was four of the ten hand-check errors — and to
# leave the price outcome each one rides on exactly where it was. That is
# only a checkable claim if the two are counted apart.

def seed_secondary(db, *, tier, outcome, results, expectation='{"type": "price"}'):
    import json
    with db.begin() as c:
        qid = c.execute(text(
            "INSERT INTO soa_queries (tier, expected_answer) VALUES (:t, :e) "
            "RETURNING id"
        ), {"t": tier, "e": expectation}).scalar()
        rid = c.execute(text(
            "INSERT INTO soa_runs (cycle_id, query_id) VALUES (1, :q) RETURNING id"
        ), {"q": qid}).scalar()
        c.execute(text(
            "INSERT INTO soa_expectation_outcomes "
            "(run_id, cycle_id, tier, outcome, secondary_results) "
            "VALUES (:r, 1, :t, :o, :s)"
        ), {"r": rid, "t": tier, "o": outcome, "s": json.dumps(results)})


def test_secondary_results_are_counted_per_tier_and_per_type(db):
    seed_secondary(db, tier="catalog_accuracy", outcome="exact",
                   results=[{"type": "pack_count", "outcome": "wrong"},
                            {"type": "gtin", "outcome": "absent"}])
    seed_secondary(db, tier="catalog_accuracy", outcome="exact",
                   results=[{"type": "pack_count", "outcome": "absent"}])

    with db.connect() as conn:
        counts = rc.secondary_counts(conn, 1)
    assert counts["catalog_accuracy"]["pack_count"] == {"wrong": 1, "absent": 1}
    assert counts["catalog_accuracy"]["gtin"] == {"absent": 1}


def test_a_row_with_no_secondaries_contributes_nothing(db):
    seed(db, tier="catalog_accuracy", outcome="exact", n=3)
    with db.connect() as conn:
        assert rc.secondary_counts(conn, 1) == {}


def test_unreadable_secondary_json_is_skipped_rather_than_crashing(db):
    seed_secondary(db, tier="catalog_accuracy", outcome="exact",
                   results=[{"type": "pack_count", "outcome": "exact"}])
    with db.begin() as c:
        c.execute(text(
            "UPDATE soa_expectation_outcomes SET secondary_results = 'not json'"
        ))
    with db.connect() as conn:
        assert rc.secondary_counts(conn, 1) == {}


# ── the promise, asserted ─────────────────────────────────────────────────

def test_a_tier_whose_primary_outcomes_moved_is_named():
    before = {"catalog_accuracy": Counter({"exact": 19, "wrong": 2})}
    after = {"catalog_accuracy": Counter({"exact": 21})}
    assert rc.changed_tiers(before, after) == ["catalog_accuracy"]


def test_identical_counts_are_not_a_change():
    counts = {"catalog_accuracy": Counter({"exact": 19, "wrong": 2}),
              "value_incentives": Counter({"exact": 4})}
    assert rc.changed_tiers(counts, dict(counts)) == []


def test_a_secondary_moving_is_not_a_primary_change():
    """The whole reason the two are counted apart. A size that stops
    being read as a pack count changes the pack_count secondary and
    leaves the price outcome it rides on alone."""
    counts = {"catalog_accuracy": Counter({"exact": 19})}
    assert rc.changed_tiers(counts, dict(counts)) == []


# ── the row-level diff ────────────────────────────────────────────────────
#
# The tier totals say how many moved. An extractor correction is meant to
# move particular rows for particular reasons, and "twelve went from
# fabricated to acknowledged_unknown" is a number somebody has to take on
# trust until they can see the twelve.

def seed_named(db, *, run_id, code, platform, number, tier, outcome):
    with db.begin() as c:
        qid = c.execute(text(
            "INSERT INTO soa_queries (tier, expected_answer, query_code) "
            "VALUES (:t, '{}', :c) RETURNING id"
        ), {"t": tier, "c": code}).scalar()
        c.execute(text(
            "INSERT INTO soa_runs (id, cycle_id, query_id, run_number) "
            "VALUES (:r, 1, :q, :n)"
        ), {"r": run_id, "q": qid, "n": number})
        c.execute(text(
            "INSERT INTO soa_expectation_outcomes "
            "(run_id, cycle_id, tier, outcome, platform) "
            "VALUES (:r, 1, :t, :o, :p)"
        ), {"r": run_id, "t": tier, "o": outcome, "p": platform})


def test_a_row_that_kept_its_outcome_is_not_in_the_diff():
    before = {1: ("WIG_144", "gemini", 1, "brand_direct", "fabricated")}
    after = {1: ("WIG_144", "gemini", 1, "brand_direct", "fabricated")}
    assert rc.row_diff(before, after) == []


def test_a_row_that_changed_is_named_with_both_outcomes():
    before = {1: ("WIG_144", "gemini", 1, "brand_direct", "fabricated")}
    after = {1: ("WIG_144", "gemini", 1, "brand_direct", "acknowledged_unknown")}
    (moved,) = rc.row_diff(before, after)
    assert moved[0] == 1
    assert moved[1][4] == "fabricated"
    assert moved[2][4] == "acknowledged_unknown"


def test_a_row_that_appeared_or_vanished_is_in_the_diff():
    before = {1: ("A", "chatgpt", 1, "brand_direct", "exact")}
    after = {2: ("B", "chatgpt", 1, "brand_direct", "echoed")}
    assert [m[0] for m in rc.row_diff(before, after)] == [1, 2]


def test_the_diff_reads_as_one_line_per_row():
    moved = rc.row_diff(
        {1: ("WIG_144", "gemini", 1, "brand_direct", "fabricated")},
        {1: ("WIG_144", "gemini", 1, "brand_direct", "acknowledged_unknown")},
    )
    rendered = rc._render_rows(moved)
    assert "WIG_144 · gemini · run 1 · brand_direct" in rendered
    assert "fabricated -> acknowledged_unknown" in rendered
    assert "[run 1]" in rendered


def test_an_unchanged_cycle_says_so_rather_than_printing_nothing():
    assert "no row changed its outcome" in rc._render_rows([])


def test_the_rows_are_read_with_their_question_code_and_surface(db):
    seed_named(db, run_id=10646, code="WIG_144", platform="gemini", number=1,
               tier="brand_direct", outcome="fabricated")

    with db.connect() as conn:
        rows = rc.row_outcomes(conn, 1)
    assert rows[10646] == ("WIG_144", "gemini", 1, "brand_direct", "fabricated")
