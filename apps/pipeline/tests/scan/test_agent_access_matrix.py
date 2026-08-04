"""
Tests for the Agent Access Matrix (Part 1, M1-M5): per-agent robots.txt
evaluation, table-driven. build_agent_access_matrix is pure (no network
calls — it only re-evaluates an already-parsed robots.txt), so these
tests build DiscoveryResult-shaped stand-ins directly rather than going
through fetch()/discover_pages().
"""
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Optional

import pytest

from scan.agent_access_matrix import AGENT_CRAWLERS, build_agent_access_matrix
from scan.fetcher import FetchResult


@dataclass
class _FakeDiscovery:
    robots_fetch: FetchResult
    robot_parser: Optional[urllib.robotparser.RobotFileParser]
    sitemap_sampling: dict = field(default_factory=lambda: {"robots_excluded": 0})


def _parsed(robots_txt: str) -> _FakeDiscovery:
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url("https://example.com/robots.txt")
    rp.parse(robots_txt.splitlines())
    return _FakeDiscovery(
        robots_fetch=FetchResult(url="https://example.com/robots.txt", status="fetched", html=robots_txt),
        robot_parser=rp,
    )


def _row(matrix, agent):
    return next(r for r in matrix if r["agent"] == agent)


def test_matrix_covers_all_six_agents_in_declared_order():
    discovery = _parsed("User-agent: *\nAllow: /\n")
    matrix, _ = build_agent_access_matrix(discovery, [])
    assert [r["agent"] for r in matrix] == [a["user_agent"] for a in AGENT_CRAWLERS]
    for row in matrix:
        assert set(row.keys()) == {"agent", "platform", "role", "root", "product_pages", "rule"}


def test_agent_absent_from_robots_inherits_star():
    discovery = _parsed("User-agent: *\nDisallow: /private/\n")
    matrix, divergence = build_agent_access_matrix(discovery, ["https://example.com/products/x"])
    for row in matrix:
        assert row["root"] == "allowed"
        assert row["product_pages"] == "allowed"
    assert divergence == []


def test_named_group_overrides_star_entirely_chewy_shape():
    """The Chewy incident shape: a named agent (here GPTBot, standing in
    for the fixture's Amazonbot) is fully disallowed while '*' allows
    /dp/ — the named group must win outright, never blend with '*'."""
    robots_txt = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\nDisallow: /dp/\nAllow: /dp/allowed-item\n"
    discovery = _parsed(robots_txt)
    product_urls = ["https://example.com/dp/foo", "https://example.com/dp/allowed-item"]
    matrix, divergence = build_agent_access_matrix(discovery, product_urls)

    gptbot = _row(matrix, "GPTBot")
    assert gptbot["root"] == "blocked"
    assert gptbot["product_pages"] == "blocked"
    assert gptbot["rule"] == "Disallow: /"

    claudebot = _row(matrix, "ClaudeBot")  # inherits '*'
    assert claudebot["root"] == "allowed"
    assert claudebot["product_pages"] == "partial"  # one /dp/ blocked, one allowed

    assert divergence == ["robots.txt blocks GPTBot specifically — the general '*' rule allows it"]


def test_wildcard_longest_match_and_allow_over_disallow_tie():
    """/dp/allowed-item is disallowed by the shorter /dp/ rule but
    allowed by the longer, more specific Allow — longest match must
    win regardless of declaration order (Allow declared before
    Disallow here, so order-based logic would get this wrong too)."""
    robots_txt = "User-agent: *\nAllow: /dp/allowed-item\nDisallow: /dp/\n"
    discovery = _parsed(robots_txt)
    matrix, _ = build_agent_access_matrix(discovery, ["https://example.com/dp/allowed-item"])
    row = _row(matrix, "GPTBot")
    assert row["product_pages"] == "allowed"
    assert row["rule"] == "Allow: /dp/allowed-item"


def test_stdlib_quoting_bug_worked_around_disallow_star_for_named_agent():
    """Regression for the exact stdlib footgun this module exists to
    fix: urllib.parse.quote() mangles a literal '*' Disallow value into
    '%2A', which RobotFileParser.can_fetch then silently ignores (see
    module docstring) — the matrix must NOT inherit that bug."""
    robots_txt = "User-agent: ClaudeBot\nDisallow: *\n\nUser-agent: *\nAllow: /\n"
    discovery = _parsed(robots_txt)
    matrix, divergence = build_agent_access_matrix(discovery, [])

    claudebot = _row(matrix, "ClaudeBot")
    assert claudebot["root"] == "blocked"
    assert claudebot["rule"] == "Disallow: *"
    assert divergence == ["robots.txt blocks ClaudeBot specifically — the general '*' rule allows it"]

    # Sanity: confirms the stdlib bug this guards against is real.
    rp = discovery.robot_parser
    assert rp.can_fetch("ClaudeBot", "https://example.com/") is True


def test_allow_beats_disallow_on_exact_specificity_tie():
    robots_txt = "User-agent: *\nDisallow: /secret\nAllow: /secret\n"
    discovery = _parsed(robots_txt)
    matrix, _ = build_agent_access_matrix(discovery, ["https://example.com/secret"])
    row = _row(matrix, "GPTBot")
    assert row["product_pages"] == "allowed"


def test_robots_unreadable_is_unknown_never_a_guess_sephora_shape():
    discovery = _FakeDiscovery(
        robots_fetch=FetchResult(url="https://example.com/robots.txt", status="blocked", http_status=403),
        robot_parser=None,
    )
    matrix, divergence = build_agent_access_matrix(discovery, ["https://example.com/products/x"])
    for row in matrix:
        assert row["root"] == "unknown"
        assert row["product_pages"] == "unknown"
        assert row["rule"] is None
    assert divergence == []


def test_no_product_pages_sampled_product_state_is_unknown_root_still_scored():
    discovery = _parsed("User-agent: *\nAllow: /\n")
    matrix, _ = build_agent_access_matrix(discovery, [])
    for row in matrix:
        assert row["root"] == "allowed"
        assert row["product_pages"] == "unknown"


def test_divergence_evidence_fires_only_on_actual_divergence():
    """Every agent here either has no group of its own or matches '*'
    exactly — no divergence line should ever fire."""
    robots_txt = "User-agent: GPTBot\nAllow: /\n\nUser-agent: *\nAllow: /\n"
    discovery = _parsed(robots_txt)
    _matrix, divergence = build_agent_access_matrix(discovery, [])
    assert divergence == []


def test_divergence_permissive_direction_agent_allowed_star_blocked():
    robots_txt = "User-agent: PerplexityBot\nAllow: /\n\nUser-agent: *\nDisallow: /\n"
    discovery = _parsed(robots_txt)
    _matrix, divergence = build_agent_access_matrix(discovery, [])
    assert divergence == ["robots.txt allows PerplexityBot specifically — the general '*' rule blocks it"]


def test_no_default_group_at_all_defaults_to_allowed():
    """No '*' group and no matching named group -> open access (a
    robots.txt that only ever addresses irrelevant agents)."""
    discovery = _parsed("User-agent: SomeOtherBot\nDisallow: /\n")
    matrix, divergence = build_agent_access_matrix(discovery, ["https://example.com/products/x"])
    for row in matrix:
        assert row["root"] == "allowed"
        assert row["product_pages"] == "allowed"
    assert divergence == []
