"""
Tests for app/services/lite_incentive_citation.py — pure fixture tests,
no DB.
"""
from app.services.lite_incentive_citation import build_incentive_citation_payload


def _entity(name, is_primary, mentions, raw):
    return {"name": name, "is_primary": is_primary, "mentions": mentions, "deal_citation_rate_raw": raw}


# ─── A1: cited_answers rounding is exact at lite's <=12-mentions scale ──
# Mirrors apps/pipeline/metrics/calculator.py Metric 5 exactly:
# deal_citation_rate = round(deal_cited_count / total_mentions, 4).

def test_cited_answers_recovers_deal_cited_count_exactly_for_every_combination():
    for mentions in range(1, 13):
        for cited in range(0, mentions + 1):
            raw = round(cited / mentions, 4)
            result = build_incentive_citation_payload([_entity("Acme Co", True, mentions, raw)])
            assert result[0]["cited_answers"] == cited, (
                f"mentions={mentions} cited={cited} raw={raw} -> "
                f"got {result[0]['cited_answers']}"
            )


def test_rate_pct_matches_normalize_metric_style_rounding():
    result = build_incentive_citation_payload([_entity("Acme Co", True, 3, round(1 / 3, 4))])
    assert result[0]["rate_pct"] == 33.3


# ─── zero mentions -> null rate, not 0 ────────────────────────────────

def test_zero_mentions_yields_null_rate_and_null_cited_answers():
    result = build_incentive_citation_payload([_entity("Rival Co", False, 0, None)])
    assert result[0]["rate_pct"] is None
    assert result[0]["cited_answers"] is None
    assert result[0]["mentions"] == 0


# ─── shape / ordering ──────────────────────────────────────────────────

def test_preserves_input_order_and_is_primary_flag():
    entities = [
        _entity("Acme Co", True, 6, 0.5),
        _entity("Rival A", False, 4, 0.25),
        _entity("Rival B", False, 0, None),
    ]
    result = build_incentive_citation_payload(entities)
    assert [r["entity"] for r in result] == ["Acme Co", "Rival A", "Rival B"]
    assert [r["is_primary"] for r in result] == [True, False, False]


def test_no_entities():
    assert build_incentive_citation_payload([]) == []
