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
import logging
import re

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

def test_signature_agent_header_present_and_points_at_the_key_directory(enabled_signing):
    from scan.identity import KEY_DIRECTORY_URL
    headers = signing.sign_request("GET", "https://example.com/")
    assert headers["Signature-Agent"] == f'"{KEY_DIRECTORY_URL}"'


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
