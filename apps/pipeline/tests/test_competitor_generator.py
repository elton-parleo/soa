"""
Tests for competitor_generator.py — Stage 13 (G1-G4) worker-side
competitor auto-generation.

generate_competitors' one-attempt-plus-one-retry, never-throw contract
is tested by mocking _call_once (the actual OpenAI call) so no real API
call is made — same idiom as test_generate_lite_queries.py mocking
_call_openai_and_validate. select_competitors is pure and tested
directly with CompetitorCandidate fixtures.

Logo feature, Part 2a: select_competitors' `final` entries are now
{"name", "domain"} dicts, not bare strings — _names() strips the
comparison back down to just the name list for every pre-existing test
below that only ever cared about names/dedupe/ordering; the domain-
specific behavior gets its own dedicated tests further down.
"""
from unittest.mock import patch

from generation.competitor_generator import (
    CompetitorCandidate,
    MAX_CANDIDATES,
    generate_competitors,
    select_competitors,
)


def _cands(*names):
    return [CompetitorCandidate(name=n) for n in names]


def _names(final):
    return [c["name"] for c in final]


# ── generate_competitors: retry / never-throw ───────────────────────────

def test_returns_candidates_from_first_successful_attempt():
    with patch("generation.competitor_generator._call_once") as mock_call:
        mock_call.return_value = _cands("Rival A", "Rival B")
        result = generate_competitors("Acme", "key")

    assert mock_call.call_count == 1
    assert [c.name for c in result] == ["Rival A", "Rival B"]


def test_retries_once_after_first_attempt_fails():
    with patch("generation.competitor_generator._call_once") as mock_call:
        mock_call.side_effect = [RuntimeError("boom"), _cands("Rival A")]
        result = generate_competitors("Acme", "key")

    assert mock_call.call_count == 2
    assert [c.name for c in result] == ["Rival A"]


def test_both_attempts_failing_returns_empty_list_never_raises():
    with patch("generation.competitor_generator._call_once") as mock_call:
        mock_call.side_effect = [RuntimeError("boom"), RuntimeError("boom again")]
        result = generate_competitors("Acme", "key")

    assert mock_call.call_count == 2
    assert result == []


# ── select_competitors: dedupe, brand-echo, cap, source classification ──

def test_clean_five_generated_candidates_yields_generated_source():
    final, source = select_competitors([], _cands("Aa", "Bb", "Cc", "Dd", "Ee"), "Acme")
    assert _names(final) == ["Aa", "Bb", "Cc", "Dd", "Ee"]
    assert source == "generated"


def test_retailer_and_marketplace_names_are_not_filtered_here():
    """
    G2's retailer/marketplace exclusion is a prompt-level instruction to
    the model (there's no reliable code-side signal to distinguish a
    retailer name from a brand name) — select_competitors' own job is
    strictly dedupe/brand-echo/cap, so it must not drop a plausible-
    looking name on its own. This test documents that boundary rather
    than asserting behavior select_competitors doesn't own.
    """
    final, source = select_competitors([], _cands("Amazon"), "Acme")
    assert _names(final) == ["Amazon"]
    assert source == "generated"


def test_primary_brand_echo_is_dropped_case_insensitively():
    final, source = select_competitors([], _cands("acme", "Rival"), "Acme")
    assert _names(final) == ["Rival"]
    assert source == "generated"


def test_manual_competitors_kept_first_and_topped_up_to_five():
    final, source = select_competitors(
        ["Manual One", "Manual Two"], _cands("Gen A", "Gen B", "Gen C", "Gen D"), "Acme",
    )
    assert _names(final) == ["Manual One", "Manual Two", "Gen A", "Gen B", "Gen C"]
    assert len(final) == MAX_CANDIDATES
    assert source == "mixed"


def test_manual_only_no_generated_candidates_yields_manual_source():
    final, source = select_competitors(["Manual One"], [], "Acme")
    assert _names(final) == ["Manual One"]
    assert source == "manual"


def test_manual_present_but_nothing_generated_added_stays_manual_source():
    # Every generated candidate collides with the manual set (or the
    # brand) — nothing new gets added, so this is still a manual-only
    # outcome, not 'mixed'.
    final, source = select_competitors(["Rival"], _cands("rival", "Acme"), "Acme")
    assert _names(final) == ["Rival"]
    assert source == "manual"


def test_no_manual_and_generation_fails_yields_none_source():
    final, source = select_competitors([], [], "Acme")
    assert _names(final) == []
    assert source == "none"


def test_thin_category_returns_fewer_than_five_without_padding():
    final, source = select_competitors([], _cands("Only One", "Only Two"), "Acme")
    assert _names(final) == ["Only One", "Only Two"]
    assert source == "generated"


def test_dedupe_is_case_insensitive_across_manual_and_generated_sets():
    final, source = select_competitors(["Rival"], _cands("RIVAL", "New One"), "Acme")
    assert _names(final) == ["Rival", "New One"]
    assert source == "mixed"


def test_empty_and_absurdly_long_names_are_dropped():
    long_name = "x" * 200
    final, source = select_competitors([], _cands("", "   ", long_name, "Good Name"), "Acme")
    assert _names(final) == ["Good Name"]
    assert source == "generated"


def test_cap_stops_at_five_even_with_more_candidates_available():
    final, source = select_competitors(
        [], _cands("Aa", "Bb", "Cc", "Dd", "Ee", "Ff", "Gg"), "Acme",
    )
    assert _names(final) == ["Aa", "Bb", "Cc", "Dd", "Ee"]
    assert len(final) == MAX_CANDIDATES
    assert source == "generated"


# ── Logo feature, Part 2a: domain passthrough ────────────────────────────

def test_generated_candidates_domain_is_carried_through():
    candidates = [CompetitorCandidate(name="Vuori", domain="vuoriclothing.com")]
    final, _source = select_competitors([], candidates, "Acme")
    assert final == [{"name": "Vuori", "domain": "vuoriclothing.com"}]


def test_generated_candidate_with_no_domain_carries_none():
    candidates = [CompetitorCandidate(name="Vuori", domain=None)]
    final, _source = select_competitors([], candidates, "Acme")
    assert final == [{"name": "Vuori", "domain": None}]


def test_manual_competitor_always_carries_a_null_domain():
    # A visitor-typed name has no domain signal at all — never guessed,
    # never inherited from a same-named generated candidate.
    final, _source = select_competitors(["Rival"], [], "Acme")
    assert final == [{"name": "Rival", "domain": None}]


def test_manual_and_generated_domains_stay_independent_per_entry():
    candidates = [CompetitorCandidate(name="Gen Co", domain="genco.com")]
    final, _source = select_competitors(["Manual Co"], candidates, "Acme")
    assert final == [
        {"name": "Manual Co", "domain": None},
        {"name": "Gen Co", "domain": "genco.com"},
    ]
