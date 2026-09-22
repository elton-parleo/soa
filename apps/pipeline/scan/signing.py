"""
signing.py — RFC 9421 HTTP Message Signatures, Web Bot Auth (WBA)
profile (W2/W3), for the Agent Scan's own page-fetch requests only
(never OpenAI API calls, never internal traffic — fetcher.py is the
only caller).

RFC 9421 itself is a finalized RFC and the signature-base construction
here (component identifiers, the "@signature-params" line, the
Signature-Input/Signature header wire format) follows it exactly. Web
Bot Auth is a separate, still-evolving IETF draft layered on top of
RFC 9421; the specific choices below (covered components @authority +
signature-agent, tag="web-bot-auth", keyid as a JWK thumbprint) are
this stage's best-documented understanding of that draft's profile,
not a guarantee it matches whatever the draft says by the time this
deploys — worth a manual diff against the current draft text before
relying on it for reputation purposes (the actual benefit needs the
key directory to be live and registered with verifiers like Cloudflare
regardless, per the rollout note in the stage this shipped in).

Never raises (rule 4's discipline, extended to this module): a signing
failure of any kind — missing/malformed key, an unexpected exception
mid-signature — degrades to unsigned (empty headers), logged, never a
broken fetch.
"""
import base64
import hashlib
import json
import logging
import os
import time
from typing import Optional
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .identity import KEY_DIRECTORY_URL

log = logging.getLogger(__name__)

SIGNATURE_LABEL = "sig1"
SIGNATURE_TAG = "web-bot-auth"
SIGNATURE_ALG = "ed25519"
# WBA profile (draft — see module docstring): @authority is an RFC 9421
# derived component (always present, taken straight from the request
# target, never spoofable by request content); signature-agent is our
# own header (below), covered so a MITM can't swap which key directory
# a verifier is pointed at without invalidating the signature.
COVERED_COMPONENTS = ("@authority", "signature-agent")

# The Signature-Agent header's value is a Structured-Field String — the
# literal bytes sent on the wire, quotes included — carrying the ORIGIN
# of the key directory (scheme://host, no path, no trailing slash), per
# the WBA directory draft (draft-meunier-webbotauth-httpsig-directory)
# section 4.1: verifiers append /.well-known/http-message-signatures-
# directory themselves. Derived from KEY_DIRECTORY_URL, never hardcoded,
# so the two can't disagree. Built once since it never varies per request.
_KEY_DIRECTORY = urlparse(KEY_DIRECTORY_URL)
SIGNATURE_AGENT_SF_VALUE = f'"{_KEY_DIRECTORY.scheme}://{_KEY_DIRECTORY.netloc}"'


def _b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _key_id(private_key: Ed25519PrivateKey) -> str:
    """WBA-convention keyid: an RFC 7638-style thumbprint over the
    key's OKP/Ed25519 JWK form (RFC 8037) — canonical JSON, lexically
    sorted keys, no whitespace, exactly the three required members.
    Derived fresh from whatever key is passed in (never cached against
    a DIFFERENT key than the one actually signing) so tests can swap
    _PRIVATE_KEY without a second variable going stale.

    Defined ABOVE _load_private_key/the module-level boot-log block
    below on purpose (production outage, 2026-09-22): this used to sit
    near the bottom of the file while the boot-log block called it at
    module-import time — a NameError on every import whenever
    BOT_SIGNING_KEY was set, which took down the whole scan pipeline in
    production (scan.fetcher imports scan.signing; scan.engine imports
    scan.fetcher). See test_signing_import_with_key_set in
    test_signing.py, which imports this module with a real key set and
    would have caught it."""
    raw_public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
    )
    jwk = {"crv": "Ed25519", "kty": "OKP", "x": _b64url_no_pad(raw_public)}
    canonical = json.dumps(jwk, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _b64url_no_pad(hashlib.sha256(canonical).digest())


def _load_private_key() -> Optional[Ed25519PrivateKey]:
    """BOT_SIGNING_KEY: a standard (padded or unpadded) base64 encoding
    of the raw 32-byte Ed25519 private seed. Never in the repo — env/
    secret only. Never raises: an absent or malformed value returns
    None, which is exactly the "no key" / unsigned state."""
    raw = os.environ.get("BOT_SIGNING_KEY")
    if not raw:
        return None
    try:
        padded = raw + "=" * (-len(raw) % 4)
        seed = base64.b64decode(padded)
        return Ed25519PrivateKey.from_private_bytes(seed)
    except Exception:
        log.exception("[scan.signing] BOT_SIGNING_KEY is set but unusable — falling back to unsigned")
        return None


_PRIVATE_KEY = _load_private_key()

# W2: on when a usable key is present, off otherwise — WEB_BOT_AUTH can
# still explicitly force either value (e.g. WEB_BOT_AUTH=off to disable
# signing without removing the key, for a controlled rollback).
WEB_BOT_AUTH = os.environ.get("WEB_BOT_AUTH", "on" if _PRIVATE_KEY is not None else "off").strip().lower()

if _PRIVATE_KEY is None:
    log.info("[scan.signing] BOT_SIGNING_KEY not set — page fetches will be unsigned (Web Bot Auth off)")
else:
    # The mirror of the line above: whichever state the worker booted
    # in, one INFO line says so and names the key. Without this, "which
    # key is production actually signing with right now?" was only
    # answerable by reading the environment of a running container —
    # precisely the question a rotation makes urgent.
    log.info(
        f"[scan.signing] Web Bot Auth on — keyid={_key_id(_PRIVATE_KEY)}, "
        f"directory={KEY_DIRECTORY_URL}, signature_agent={SIGNATURE_AGENT_SF_VALUE}"
    )


def is_signing_enabled() -> bool:
    """The one source of truth both fetcher.py (whether to sign a
    request) and scorer.py/W6 (which evidence wording to use) read —
    a single flag, never two independent checks that could disagree."""
    return WEB_BOT_AUTH == "on" and _PRIVATE_KEY is not None


def key_id() -> Optional[str]:
    """The keyid this process signs with, or None when signing is off.
    Public material only — a thumbprint over the PUBLIC key, the same
    value published in the key directory and sent in every
    Signature-Input, never anything derived from the seed.

    Exists so a scan row can record WHICH key signed its fetches
    (engine.py writes it to dimensions["signing_kid"]): after a rotation,
    "was this run signed with the old key or the new one?" should be a
    database question, not an archaeology exercise."""
    if not is_signing_enabled():
        return None
    return _key_id(_PRIVATE_KEY)


def public_key_jwk(private_key: Optional[Ed25519PrivateKey] = None) -> Optional[dict]:
    """W3: the one public-key JWK entry for the key directory document
    — PUBLIC material only, never the private seed. None when there's
    no signing key configured and none was explicitly passed in (the
    generator script always passes its own loaded key explicitly)."""
    key = private_key if private_key is not None else _PRIVATE_KEY
    if key is None:
        return None
    raw_public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
    )
    return {"kty": "OKP", "crv": "Ed25519", "kid": _key_id(key), "x": _b64url_no_pad(raw_public)}


def _authority(url: str) -> str:
    """RFC 9421's @authority derived component: host[:port], lowercased
    (host is case-insensitive per HTTP semantics; this is a
    normalization choice, not something RFC 9421 mandates)."""
    return (urlparse(url).netloc or "").lower()


def _signature_base(component_lines: "list[tuple[str, str]]", params_line_value: str) -> str:
    """RFC 9421 section 2.5: one quoted-component-id + value line per
    covered component, in COVERED_COMPONENTS order, followed by the
    literal "@signature-params" line carrying the exact Signature-Input
    value (sans the "sig1=" label) — no trailing newline."""
    lines = [f'"{name}": {value}' for name, value in component_lines]
    lines.append(f'"@signature-params": {params_line_value}')
    return "\n".join(lines)


def _params_line_value(created: int, keyid: str) -> str:
    covered = " ".join(f'"{c}"' for c in COVERED_COMPONENTS)
    return f'({covered});created={created};keyid="{keyid}";alg="{SIGNATURE_ALG}";tag="{SIGNATURE_TAG}"'


def sign_request(method: str, url: str) -> dict:
    """
    W2: returns {"Signature-Input", "Signature", "Signature-Agent"} to
    merge into a page-fetch request's headers, or {} when signing is
    disabled (no key, or WEB_BOT_AUTH=off) — an empty dict changes
    nothing about the request, so flag-off fetches are byte-identical
    to before this stage. `method` is accepted for API symmetry with a
    future covered-component set that includes @method; unused by
    COVERED_COMPONENTS today.
    """
    if not is_signing_enabled():
        return {}
    try:
        created = int(time.time())
        keyid = _key_id(_PRIVATE_KEY)
        params_line_value = _params_line_value(created, keyid)
        base = _signature_base(
            [("@authority", _authority(url)), ("signature-agent", SIGNATURE_AGENT_SF_VALUE)],
            params_line_value,
        )
        signature = _PRIVATE_KEY.sign(base.encode("utf-8"))
        return {
            "Signature-Input": f"{SIGNATURE_LABEL}={params_line_value}",
            "Signature": f"{SIGNATURE_LABEL}=:{base64.b64encode(signature).decode('ascii')}:",
            "Signature-Agent": SIGNATURE_AGENT_SF_VALUE,
        }
    except Exception:
        log.exception("[scan.signing] failed to sign request — falling back to unsigned")
        return {}
