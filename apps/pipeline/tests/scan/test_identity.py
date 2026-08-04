"""
Tests for scan/identity.py — W1's identity constants (single source)
and W5's UA_POLICY knob.
"""
import importlib
from pathlib import Path

import pytest

from scan import identity


# ─── W1: single source + grep-kill ───────────────────────────────────────

def test_bot_name_and_ua_are_the_specified_literals():
    assert identity.BOT_NAME == "ParleoAuditBot"
    assert identity.BOT_UA == (
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); "
        "compatible; ParleoAuditBot/1.0; +https://www.parleo.io/bots"
    )
    assert "ParleoAuditBot/1.0" in identity.BOT_UA
    assert "compatible;" in identity.BOT_UA


def test_key_directory_url_is_the_specified_literal():
    assert identity.KEY_DIRECTORY_URL == "https://bots.parleo.io/.well-known/http-message-signatures-directory"


_OLD_BOT_NAME = "".join(["Parleo", "Scan", "Bot"])  # W1: never spelled literally, even here


def test_grep_kill_old_bot_name_absent_repo_wide():
    """W1: the old bot name must not survive anywhere — code, tests,
    docs, evidence templates. Scoped to the whole monorepo (minus
    node_modules/.git/build output, which can't contain source we
    wrote). Deliberately never spells the retired name as a literal
    string constant in this file either (see _OLD_BOT_NAME above) —
    a plain literal here would itself be a leftover reference and
    self-defeating for a grep-kill test."""
    repo_root = Path(__file__).resolve().parents[4]
    assert (repo_root / "apps").is_dir(), f"unexpected repo root guess: {repo_root}"

    skip_dir_names = {"node_modules", ".git", "__pycache__", "dist", "build", ".vite"}
    text_suffixes = {".py", ".js", ".jsx", ".md", ".txt", ".json"}
    offenders = []
    for path in repo_root.rglob("*"):
        if not path.is_file() or path.suffix not in text_suffixes:
            continue
        if any(part in skip_dir_names for part in path.parts):
            continue
        if path == Path(__file__):
            continue  # this file's own _OLD_BOT_NAME construction, not a real reference
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue
        if _OLD_BOT_NAME in text:
            offenders.append(str(path.relative_to(repo_root)))
    assert offenders == []


# ─── W5: UA_POLICY knob ──────────────────────────────────────────────────

def test_ua_policy_defaults_to_declared_always():
    assert identity.UA_POLICY == identity.UA_POLICY_DECLARED_ALWAYS


def test_resolve_user_agent_always_returns_bot_ua_under_default_policy():
    assert identity.resolve_user_agent() == identity.BOT_UA
    # Even an (incorrect, since public intake never does this) True
    # claim of authorization is ignored under the default policy.
    assert identity.resolve_user_agent(client_authorized_for_browser_ua=True) == identity.BOT_UA


def test_resolve_user_agent_never_activates_browser_mode_without_explicit_authorization(monkeypatch):
    monkeypatch.setattr(identity, "UA_POLICY", identity.UA_POLICY_BROWSER_WHEN_AUTHORIZED)
    # policy alone isn't enough — the caller must ALSO pass True.
    assert identity.resolve_user_agent() == identity.BOT_UA
    assert identity.resolve_user_agent(client_authorized_for_browser_ua=False) == identity.BOT_UA


def test_resolve_user_agent_uses_browser_ua_only_with_policy_and_explicit_authorization(monkeypatch):
    monkeypatch.setattr(identity, "UA_POLICY", identity.UA_POLICY_BROWSER_WHEN_AUTHORIZED)
    assert identity.resolve_user_agent(client_authorized_for_browser_ua=True) == identity.BROWSER_TEST_UA


def test_ua_policy_env_var_respected_at_import_time(monkeypatch):
    monkeypatch.setenv("UA_POLICY", identity.UA_POLICY_BROWSER_WHEN_AUTHORIZED)
    reloaded = importlib.reload(identity)
    try:
        assert reloaded.UA_POLICY == identity.UA_POLICY_BROWSER_WHEN_AUTHORIZED
    finally:
        monkeypatch.delenv("UA_POLICY", raising=False)
        importlib.reload(identity)  # restore module state for later tests
