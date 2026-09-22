"""
Tests for scan/signing.py — W2/W3: RFC 9421 HTTP Message Signatures,
Web Bot Auth profile.

Signature construction is verified by INDEPENDENTLY reconstructing the
signature base per RFC 9421 section 2.5 and verifying with the public
key — never trusting the module's own internal helper to grade its own
homework for the "is this a valid signature" question, even though the
reconstruction below necessarily shares the module's covered-component
list (that list itself is the WBA profile choice being tested, not an
RFC 9421 mechanic).
"""
import base64
import importlib
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scan import signing


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _seed_env(monkeypatch, key: Ed25519PrivateKey):
    monkeypatch.setenv("BOT_SIGNING_KEY", _b64(key.private_bytes_raw()))


@pytest.fixture
def test_key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def enabled_signing(monkeypatch, test_key):
    """Swaps the module's live key/flag for a fresh, known test key —
    matches the existing repo convention (fetcher.py's POLITENESS_DELAY_
    SECONDS) of tests monkeypatching module globals directly rather than
    re-importing for every case."""
    monkeypatch.setattr(signing, "_PRIVATE_KEY", test_key)
    monkeypatch.setattr(signing, "WEB_BOT_AUTH", "on")
    return test_key


def _reconstruct_and_verify(test_key: Ed25519PrivateKey, url: str, headers: dict) -> None:
    """Independent RFC 9421 signature-base reconstruction + Ed25519
    verify — raises cryptography.exceptions.InvalidSignature if the
    module's own signature doesn't validate against it."""
    sig_input = headers["Signature-Input"]
    assert sig_input.startswith("sig1=")
    params_value = sig_input[len("sig1="):]

    base = signing._signature_base(
        [("@authority", signing._authority(url)), ("signature-agent", headers["Signature-Agent"])],
        params_value,
    )

    sig_field = headers["Signature"]
    m = re.match(r"^sig1=:(.*):$", sig_field)
    assert m, f"Signature header not in the expected sig1=:...: shape: {sig_field!r}"
    signature_bytes = base64.b64decode(m.group(1))

    test_key.public_key().verify(signature_bytes, base.encode("utf-8"))


# ─── RFC 9421 signature validity ─────────────────────────────────────────

def test_sign_request_produces_a_signature_that_verifies_with_the_public_key(enabled_signing):
    headers = signing.sign_request("GET", "https://example.com/products/foo")
    _reconstruct_and_verify(enabled_signing, "https://example.com/products/foo", headers)


def test_tampering_with_the_authority_invalidates_the_signature(enabled_signing):
    headers = signing.sign_request("GET", "https://example.com/products/foo")
    tampered_base = signing._signature_base(
        [("@authority", "evil.example.com"), ("signature-agent", headers["Signature-Agent"])],
        headers["Signature-Input"][len("sig1="):],
    )
    sig_bytes = base64.b64decode(re.match(r"^sig1=:(.*):$", headers["Signature"]).group(1))
    with pytest.raises(InvalidSignature):
        enabled_signing.public_key().verify(sig_bytes, tampered_base.encode("utf-8"))


def test_signature_input_covers_authority_and_signature_agent_with_wba_params(enabled_signing):
    headers = signing.sign_request("GET", "https://example.com/")
    params_value = headers["Signature-Input"][len("sig1="):]
    assert params_value.startswith('("@authority" "signature-agent")')
    assert 'alg="ed25519"' in params_value
    assert 'tag="web-bot-auth"' in params_value
    assert re.search(r'keyid="[A-Za-z0-9_-]+"', params_value)
    assert re.search(r"created=\d+", params_value)


def test_keyid_is_a_jwk_thumbprint_matching_public_key_jwk(enabled_signing):
    headers = signing.sign_request("GET", "https://example.com/")
    keyid = re.search(r'keyid="([^"]+)"', headers["Signature-Input"]).group(1)
    jwk = signing.public_key_jwk(enabled_signing)
    assert jwk["kid"] == keyid


# ─── Signature-Agent present ──────────────────────────────────────────────

def test_signature_agent_header_present_and_carries_the_key_directory_origin(enabled_signing):
    headers = signing.sign_request("GET", "https://example.com/")
    assert headers["Signature-Agent"] == '"https://bots.parleo.io"'


def test_signature_agent_sf_value_is_the_quoted_origin_of_the_key_directory():
    """WBA directory draft section 4.1: the member value is an origin —
    verifiers append the well-known path themselves, so any path here
    would make them look up the directory at the wrong URL."""
    from urllib.parse import urlparse
    from scan.identity import KEY_DIRECTORY_URL
    parsed = urlparse(KEY_DIRECTORY_URL)
    assert signing.SIGNATURE_AGENT_SF_VALUE == '"' + f"{parsed.scheme}://{parsed.netloc}" + '"'
    unquoted = signing.SIGNATURE_AGENT_SF_VALUE[1:-1]
    assert urlparse(unquoted).path == ""
    assert not unquoted.endswith("/")
    assert "/.well-known/" not in signing.SIGNATURE_AGENT_SF_VALUE


def test_signature_base_signature_agent_line_uses_the_origin(monkeypatch):
    """Fixed key, hand-written expected signature base (not built via
    _signature_base) — the signed bytes must cover the origin value."""
    fixed_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    monkeypatch.setattr(signing, "_PRIVATE_KEY", fixed_key)
    monkeypatch.setattr(signing, "WEB_BOT_AUTH", "on")
    headers = signing.sign_request("GET", "https://example.com/products/foo")
    params_value = headers["Signature-Input"][len("sig1="):]
    expected_base = (
        '"@authority": example.com\n'
        '"signature-agent": "https://bots.parleo.io"\n'
        f'"@signature-params": {params_value}'
    )
    sig_bytes = base64.b64decode(re.match(r"^sig1=:(.*):$", headers["Signature"]).group(1))
    fixed_key.public_key().verify(sig_bytes, expected_base.encode("utf-8"))


def test_authority_component_is_host_only_lowercased(enabled_signing):
    headers = signing.sign_request("GET", "https://Example.COM:443/products/foo?x=1")
    params_value = headers["Signature-Input"]
    # Reconstructing directly against _authority is the real assertion
    # (above tests); this just locks in the lowercasing behavior.
    assert signing._authority("https://Example.COM:443/x") == "example.com:443"


# ─── Flag-off: byte-identical to unsigned ────────────────────────────────

def test_sign_request_returns_empty_dict_when_flag_off(monkeypatch, test_key):
    monkeypatch.setattr(signing, "_PRIVATE_KEY", test_key)
    monkeypatch.setattr(signing, "WEB_BOT_AUTH", "off")
    assert signing.sign_request("GET", "https://example.com/") == {}
    assert signing.is_signing_enabled() is False


def test_fetcher_headers_are_byte_identical_with_signing_off(monkeypatch, test_key):
    from scan import fetcher
    monkeypatch.setattr(signing, "_PRIVATE_KEY", test_key)
    monkeypatch.setattr(signing, "WEB_BOT_AUTH", "off")
    headers = fetcher._request_headers("https://example.com/")
    assert set(headers.keys()) == {"User-Agent", "Accept", "Accept-Language"}


def test_fetcher_headers_gain_signing_keys_only_when_enabled(monkeypatch, test_key):
    from scan import fetcher
    monkeypatch.setattr(signing, "_PRIVATE_KEY", test_key)
    monkeypatch.setattr(signing, "WEB_BOT_AUTH", "on")
    headers = fetcher._request_headers("https://example.com/")
    assert set(headers.keys()) == {
        "User-Agent", "Accept", "Accept-Language", "Signature-Input", "Signature", "Signature-Agent",
    }


# ─── Key-absent degradation ───────────────────────────────────────────────

def test_no_key_env_var_is_signing_disabled(monkeypatch):
    monkeypatch.setattr(signing, "_PRIVATE_KEY", None)
    monkeypatch.setattr(signing, "WEB_BOT_AUTH", "off")
    assert signing.is_signing_enabled() is False
    assert signing.sign_request("GET", "https://example.com/") == {}


def test_load_private_key_returns_none_when_env_var_absent(monkeypatch):
    monkeypatch.delenv("BOT_SIGNING_KEY", raising=False)
    assert signing._load_private_key() is None


def test_load_private_key_returns_none_and_never_raises_when_malformed(monkeypatch):
    monkeypatch.setenv("BOT_SIGNING_KEY", "not-valid-base64-key-material!!!")
    assert signing._load_private_key() is None


def test_key_absent_degrades_to_unsigned_with_a_single_startup_log_line(monkeypatch, caplog):
    """Reload the module with BOT_SIGNING_KEY unset — exactly one
    startup log line announces the unsigned degradation, never a raise,
    never silence."""
    monkeypatch.delenv("BOT_SIGNING_KEY", raising=False)
    monkeypatch.delenv("WEB_BOT_AUTH", raising=False)
    with caplog.at_level(logging.INFO, logger="scan.signing"):
        reloaded = importlib.reload(signing)
    try:
        assert reloaded._PRIVATE_KEY is None
        assert reloaded.WEB_BOT_AUTH == "off"
        startup_lines = [r for r in caplog.records if "unsigned" in r.getMessage().lower()]
        assert len(startup_lines) == 1
    finally:
        importlib.reload(signing)  # restore whatever state later tests expect


# ─── Production outage (2026-09-22): fresh-process import ────────────────
#
# _key_id was defined BELOW the module-level boot-log block that called
# it, so importing scan.signing with BOT_SIGNING_KEY set raised
# NameError — which took down the whole scan pipeline in production
# (scan.fetcher imports scan.signing; scan.engine imports scan.fetcher;
# worker.py's `from scan.engine import run_scan` is the first thing a
# lite scan does). Every other test above uses importlib.reload() or
# monkeypatches module globals directly — both REUSE the module's
# existing __dict__, which by the time any of those tests run already
# has _key_id bound in it from some earlier, unrelated, no-key import
# elsewhere in the suite. That's exactly why CI passed: reload doesn't
# re-create the namespace, so the same ordering bug that crashed a real
# (genuinely first-time) worker process was invisible to every test
# that only ever reloads. A real subprocess is the only way to observe
# what a fresh interpreter actually sees on its first import.
PIPELINE_ROOT = Path(__file__).resolve().parents[2]

_IMPORT_AND_REPORT_SCRIPT = """
import json
from scan.engine import run_scan  # noqa: F401 -- worker.py's own import chain
from scan import signing
print(json.dumps({
    "signing_enabled": signing.is_signing_enabled(),
    "key_id": signing.key_id(),
}))
"""


def _run_fresh_import(bot_signing_key):
    """Runs _IMPORT_AND_REPORT_SCRIPT in a brand-new interpreter — never
    importlib.reload(), see module comment above. bot_signing_key=None
    means BOT_SIGNING_KEY is unset for the subprocess regardless of
    whatever this test process's own environment happens to carry."""
    env = dict(os.environ)
    if bot_signing_key is None:
        env.pop("BOT_SIGNING_KEY", None)
    else:
        env["BOT_SIGNING_KEY"] = bot_signing_key
    proc = subprocess.run(
        [sys.executable, "-c", _IMPORT_AND_REPORT_SCRIPT],
        cwd=str(PIPELINE_ROOT), env=env, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, (
        f"fresh-process import failed (returncode={proc.returncode})\n"
        f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_fresh_process_import_succeeds_with_a_signing_key_set():
    """The regression test for the outage: a genuinely fresh process
    importing scan.engine with BOT_SIGNING_KEY set must succeed, with
    signing actually enabled and a real keyid — not crash on
    NameError('_key_id')."""
    key = base64.b64encode(os.urandom(32)).decode()
    result = _run_fresh_import(key)
    assert result["signing_enabled"] is True
    assert isinstance(result["key_id"], str) and result["key_id"]


def test_fresh_process_import_succeeds_with_no_signing_key():
    """The mirror negative case — signing off, import still clean."""
    result = _run_fresh_import(None)
    assert result["signing_enabled"] is False
    assert result["key_id"] is None


# ─── public_key_jwk ────────────────────────────────────────────────────────

def test_public_key_jwk_never_includes_private_material(enabled_signing):
    jwk = signing.public_key_jwk(enabled_signing)
    assert set(jwk.keys()) == {"kty", "crv", "kid", "x"}
    assert jwk["kty"] == "OKP"
    assert jwk["crv"] == "Ed25519"
    # The public x-coordinate round-trips to the same key's own public bytes.
    import base64 as b64
    raw_public = enabled_signing.public_key().public_bytes_raw()
    padded = jwk["x"] + "=" * (-len(jwk["x"]) % 4)
    assert b64.urlsafe_b64decode(padded) == raw_public


def test_public_key_jwk_is_none_with_no_key(monkeypatch):
    monkeypatch.setattr(signing, "_PRIVATE_KEY", None)
    assert signing.public_key_jwk(None) is None


# ─── key_id(): which key signed this run ───────────────────────────────────

def test_key_id_matches_the_published_directory_entry(enabled_signing):
    """The kid recorded on a scan row has to be the same string a
    verifier sees in the key directory, or it answers nothing."""
    assert signing.key_id() == signing.public_key_jwk(enabled_signing)["kid"]


def test_key_id_matches_the_keyid_sent_in_signature_input(enabled_signing):
    headers = signing.sign_request("GET", "https://example.com/products/foo")
    keyid_in_header = re.search(r'keyid="([^"]+)"', headers["Signature-Input"]).group(1)
    assert signing.key_id() == keyid_in_header


def test_key_id_is_none_when_the_flag_is_off(monkeypatch, test_key):
    monkeypatch.setattr(signing, "_PRIVATE_KEY", test_key)
    monkeypatch.setattr(signing, "WEB_BOT_AUTH", "off")
    assert signing.key_id() is None


def test_key_id_is_none_when_no_key_is_set(monkeypatch):
    monkeypatch.setattr(signing, "_PRIVATE_KEY", None)
    monkeypatch.setattr(signing, "WEB_BOT_AUTH", "on")
    assert signing.key_id() is None


def test_key_id_never_exposes_private_material(enabled_signing):
    seed_b64 = _b64(enabled_signing.private_bytes_raw())
    kid = signing.key_id()
    assert seed_b64 not in kid
    assert signing._b64url_no_pad(enabled_signing.private_bytes_raw()) not in kid


def test_key_present_announces_the_keyid_and_directory_in_one_startup_line(monkeypatch, caplog, test_key):
    """The mirror of test_key_absent_degrades_to_unsigned_with_a_single_
    startup_log_line: whichever state the worker boots in, exactly one
    INFO line says so — and the enabled one names the key, so "which key
    is production signing with?" is answerable from the Railway log."""
    _seed_env(monkeypatch, test_key)
    monkeypatch.delenv("WEB_BOT_AUTH", raising=False)
    with caplog.at_level(logging.INFO, logger="scan.signing"):
        reloaded = importlib.reload(signing)
    try:
        assert reloaded._PRIVATE_KEY is not None
        startup_lines = [r for r in caplog.records if "Web Bot Auth on" in r.getMessage()]
        assert len(startup_lines) == 1
        message = startup_lines[0].getMessage()
        assert reloaded.key_id() in message
        assert reloaded.KEY_DIRECTORY_URL in message
        assert f"signature_agent={reloaded.SIGNATURE_AGENT_SF_VALUE}" in message
        # Never the seed, not even partially.
        assert _b64(test_key.private_bytes_raw()) not in message
    finally:
        # The env var must go BEFORE the restoring reload: monkeypatch
        # only undoes it after this function returns, so reloading first
        # would leave signing globally ENABLED for every later test in
        # the session — which silently flips _reader_phrase()'s
        # signed/unsigned evidence wording elsewhere in the suite.
        monkeypatch.delenv("BOT_SIGNING_KEY", raising=False)
        importlib.reload(signing)  # restore whatever state later tests expect
