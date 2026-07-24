"""
Tests for app/services/lite_visibility.py — pure fixture tests, no DB.
"""
from app.services.lite_visibility import build_visibility_payload


def _entity(name, is_primary, mentioned_queries, total_queries, mentions):
    return {
        "name": name, "is_primary": is_primary,
        "mentioned_queries": mentioned_queries, "total_queries": total_queries,
        "mentions": mentions,
    }


# ─── basic shape / one competitor ────────────────────────────────────────

def test_one_competitor_rate_and_share():
    entities = [
        _entity("Acme Co", True, 9, 12, 9),
        _entity("Rival Co", False, 3, 12, 3),
    ]
    result = build_visibility_payload(entities)

    acme_rate = next(r for r in result["mention_rate"] if r["entity"] == "Acme Co")
    assert acme_rate["rate_pct"] == 75.0
    assert acme_rate["is_primary"] is True

    rival_rate = next(r for r in result["mention_rate"] if r["entity"] == "Rival Co")
    assert rival_rate["rate_pct"] == 25.0

    acme_share = next(s for s in result["share_of_mentions"] if s["entity"] == "Acme Co")
    assert acme_share["share_pct"] == 75.0
    rival_share = next(s for s in result["share_of_mentions"] if s["entity"] == "Rival Co")
    assert rival_share["share_pct"] == 25.0

    assert result["totals"] == {"total_mentions": 12, "total_queries": 12}


# ─── two competitors ──────────────────────────────────────────────────────

def test_two_competitors_shares_sum_to_100():
    entities = [
        _entity("Acme Co", True, 6, 12, 6),
        _entity("Rival A", False, 4, 12, 4),
        _entity("Rival B", False, 2, 12, 2),
    ]
    result = build_visibility_payload(entities)

    shares = {s["entity"]: s["share_pct"] for s in result["share_of_mentions"]}
    assert shares == {"Acme Co": 50.0, "Rival A": 33.3, "Rival B": 16.7}
    # Rounding three independent 1-decimal percentages can land at
    # 99.9-100.1 — assert within that tolerance, not exact equality.
    assert 99.9 <= round(sum(shares.values()), 1) <= 100.1


# ─── zero mentions ────────────────────────────────────────────────────────

def test_zero_mentions_gives_zero_rate_and_zero_share_not_nan_or_error():
    entities = [
        _entity("Acme Co", True, 0, 12, 0),
        _entity("Rival Co", False, 0, 12, 0),
    ]
    result = build_visibility_payload(entities)

    assert all(r["rate_pct"] == 0.0 for r in result["mention_rate"])
    assert all(s["share_pct"] == 0.0 for s in result["share_of_mentions"])
    assert result["totals"] == {"total_mentions": 0, "total_queries": 12}


def test_zero_total_queries_does_not_divide_by_zero():
    entities = [_entity("Acme Co", True, 0, 0, 0)]
    result = build_visibility_payload(entities)
    assert result["mention_rate"][0]["rate_pct"] == 0.0


def test_no_entities_at_all():
    result = build_visibility_payload([])
    assert result == {
        "mention_rate": [], "share_of_mentions": [],
        "totals": {"total_mentions": 0, "total_queries": 0},
    }


# ─── mentioned_queries vs mentions: the denominators must be independent ──
# soa_coded_mentions only stores one boolean per (run, entity) today, so
# production data can never actually produce mentioned_queries != mentions
# for the same entity — but this fixture proves the function reads the
# RIGHT field for the RIGHT output regardless, so a future refactor (or a
# future data source that DOES count multiple mentions per answer) can't
# silently cross-wire rate math and share math.

def test_mentioned_once_but_counted_three_times_in_one_answer():
    entities = [
        # Mentioned in only 1 of 12 queries (mention_rate should be low),
        # but that single answer named the brand 3 times (share_of_mentions
        # should still be sizeable relative to the other entity's 1 mention).
        _entity("Acme Co", True, mentioned_queries=1, total_queries=12, mentions=3),
        _entity("Rival Co", False, mentioned_queries=1, total_queries=12, mentions=1),
    ]
    result = build_visibility_payload(entities)

    acme_rate = next(r for r in result["mention_rate"] if r["entity"] == "Acme Co")
    acme_share = next(s for s in result["share_of_mentions"] if s["entity"] == "Acme Co")

    # rate is scoped to queries (1/12), share is scoped to raw mentions (3/4) —
    # the two percentages must differ, proving they read different fields.
    assert acme_rate["rate_pct"] == round(100 * 1 / 12, 1)
    assert acme_share["share_pct"] == round(100 * 3 / 4, 1)
    assert acme_rate["rate_pct"] != acme_share["share_pct"]
    assert acme_rate["mentioned_queries"] == 1
    assert acme_share["mentions"] == 3
