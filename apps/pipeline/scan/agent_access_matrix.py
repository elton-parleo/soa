"""
agent_access_matrix.py — Agent Access Matrix (Part 1, M1-M5): per-agent
robots.txt evaluation for the six named AI shopping/crawling agents,
evidence-only (M4: NO scoring impact — score_f1_agent_access's existing
robots check is unchanged).

Reuses urllib.robotparser.RobotFileParser for PARSING robots.txt into
per-agent groups (Entry objects) — that part already does the right
thing: a UA with its own "User-agent:" group is matched via
parser.entries and NEVER falls through to the "*" default group at all
(see RobotFileParser.can_fetch's own entries-then-default_entry order).

What the stdlib does NOT do correctly, confirmed by reading its source
(cpython Lib/urllib/robotparser.py):
  - RuleLine.__init__ passes the declared path through urllib.parse.
    quote(), which silently percent-encodes literal '*' and '$'
    (quote("*") == "%2A") — a bare "Disallow: *" for a named agent
    becomes a rule that matches nothing at all, and any embedded
    wildcard in a real Disallow line is mangled the same way. We
    recover the original text with unquote() before matching.
  - Entry.allowance() returns the FIRST ruleline (in file-declaration
    order) that matches, not the most specific one, and has no
    Allow-vs-Disallow tie-break at all.
This module's _evaluate_path replaces ONLY that matching step —
longest-match-wins, Allow beats Disallow on an exact tie — operating on
the same parsed Entry/RuleLine objects RobotFileParser already built.
Per rule 8's "don't add a second parser": nothing here re-parses
robots.txt text; it only re-evaluates already-parsed rules correctly.
"""
import re
from urllib.parse import unquote, urlparse

AGENT_CRAWLERS = (
    {"user_agent": "GPTBot", "platform": "OpenAI", "role": "Model training"},
    {"user_agent": "OAI-SearchBot", "platform": "OpenAI", "role": "ChatGPT search index"},
    {"user_agent": "ChatGPT-User", "platform": "OpenAI", "role": "On-demand user fetches"},
    {"user_agent": "ClaudeBot", "platform": "Anthropic", "role": "Crawling"},
    {"user_agent": "PerplexityBot", "platform": "Perplexity", "role": "Search index"},
    {"user_agent": "Google-Extended", "platform": "Google", "role": "Gemini/AI training control"},
)

_STATE_UNKNOWN = "unknown"
_STATE_ALLOWED = "allowed"
_STATE_BLOCKED = "blocked"
_STATE_PARTIAL = "partial"


def _pattern_to_regex(pattern: str):
    """De facto robots.txt wildcard syntax: '*' matches any run of
    characters, a trailing (unescaped-by-us) '$' anchors the end,
    otherwise the pattern is an implicit prefix. Never raises — every
    pattern is built from re.escape'd literal segments."""
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    parts = body.split("*")
    escaped = ".*".join(re.escape(p) for p in parts)
    return re.compile("^" + escaped + ("$" if anchored else ""))


def _rule_matches(pattern: str, path: str) -> bool:
    try:
        return bool(_pattern_to_regex(pattern).match(path))
    except re.error:
        return path.startswith(pattern.rstrip("$"))


def _find_entry(parser, agent_token: str):
    """Mirrors RobotFileParser.can_fetch's own lookup order: a named
    group matching this agent wins outright (per-group override, S1's
    already-correct behavior); otherwise the '*' default group; None if
    robots.txt declares no rules applicable to anyone."""
    if parser is None:
        return None
    for entry in parser.entries:
        if entry.applies_to(agent_token):
            return entry
    return parser.default_entry


def _evaluate_path(entry, path: str):
    """Longest-match-wins over entry.rulelines, Allow beating Disallow
    on an exact specificity tie (RFC 9309 precedence) — the correction
    over Entry.allowance() described in the module docstring. Returns
    (allowed: bool, rule_text: Optional[str]); rule_text is None only
    when no rule in the entry matched this path at all (default-allow)."""
    if entry is None:
        return True, None
    best = None  # (specificity, allowance, original_pattern)
    for rl in entry.rulelines:
        original = unquote(rl.path)
        if not _rule_matches(original, path):
            continue
        specificity = len(original)
        if best is None or specificity > best[0] or (specificity == best[0] and rl.allowance and not best[1]):
            best = (specificity, rl.allowance, original)
    if best is None:
        return True, None
    _specificity, allowance, original = best
    return allowance, f"{'Allow' if allowance else 'Disallow'}: {original}"


def _evaluate_agent(parser, agent_ua: str, root_path: str, product_paths: list):
    entry = _find_entry(parser, agent_ua)
    root_allowed, root_rule = _evaluate_path(entry, root_path)

    if not product_paths:
        return root_allowed, root_rule, None, None

    results = [_evaluate_path(entry, p) for p in product_paths]
    allowed_flags = [r[0] for r in results]
    if all(allowed_flags):
        product_state, product_rule = _STATE_ALLOWED, next((r[1] for r in results if r[1]), None)
    elif not any(allowed_flags):
        product_state, product_rule = _STATE_BLOCKED, next((r[1] for r in results if r[1]), None)
    else:
        product_state, product_rule = _STATE_PARTIAL, None
    return root_allowed, root_rule, product_state, product_rule


def build_agent_access_matrix(discovery, product_urls: list):
    """
    M1-M5: returns (matrix, divergence_evidence).

    matrix is a list of {agent, platform, role, root, product_pages,
    rule} dicts, one per AGENT_CRAWLERS entry, in that fixed order.
    root/product_pages are 'allowed'|'blocked'|'partial'|'unknown' —
    'unknown' means robots.txt itself couldn't be read (S4's Sephora
    shape) or, for product_pages only, that no product URL was ever
    sampled to evaluate (never a guess either way).

    divergence_evidence (M5) is a list of Agent Access evidence lines —
    one per agent whose OWN named group disagrees with the '*' default
    group's decision for the same path(s); empty when nothing diverges.
    """
    robots_readable = (
        discovery.robots_fetch.status == "fetched" and discovery.robot_parser is not None
    )
    parser = discovery.robot_parser
    product_paths = [urlparse(u).path or "/" for u in product_urls]

    matrix = []
    divergence_evidence = []

    default_entry = parser.default_entry if parser is not None else None
    star_root_allowed, _ = _evaluate_path(default_entry, "/") if robots_readable else (True, None)
    star_product_flags = (
        [_evaluate_path(default_entry, p)[0] for p in product_paths]
        if robots_readable and product_paths else []
    )
    star_product_allowed = all(star_product_flags) if star_product_flags else True

    for agent in AGENT_CRAWLERS:
        ua = agent["user_agent"]
        if not robots_readable:
            matrix.append({
                "agent": ua, "platform": agent["platform"], "role": agent["role"],
                "root": _STATE_UNKNOWN, "product_pages": _STATE_UNKNOWN, "rule": None,
            })
            continue

        root_allowed, root_rule, product_state, product_rule = _evaluate_agent(
            parser, ua, "/", product_paths,
        )
        matrix.append({
            "agent": ua, "platform": agent["platform"], "role": agent["role"],
            "root": _STATE_ALLOWED if root_allowed else _STATE_BLOCKED,
            "product_pages": product_state or _STATE_UNKNOWN,
            "rule": root_rule or product_rule,
        })

        own_entry = _find_entry(parser, ua)
        if own_entry is None or own_entry is default_entry:
            continue  # inherits '*' outright — nothing to diverge from

        agent_product_allowed = product_state != _STATE_BLOCKED if product_state else True
        restrictive = (
            (not root_allowed and star_root_allowed)
            or (product_state == _STATE_BLOCKED and star_product_allowed)
        )
        permissive = (
            (root_allowed and not star_root_allowed)
            or (product_state == _STATE_ALLOWED and not star_product_allowed)
        )
        if restrictive:
            divergence_evidence.append(f"robots.txt blocks {ua} specifically — the general '*' rule allows it")
        elif permissive:
            divergence_evidence.append(f"robots.txt allows {ua} specifically — the general '*' rule blocks it")

    return matrix, divergence_evidence
