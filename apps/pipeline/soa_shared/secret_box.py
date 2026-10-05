"""
Seal and open secrets stored in the database — today, one thing: each
customer org's TrueSync tenant token (organizations.truesync_token_sealed).

Fernet (cryptography's AES-128-CBC + HMAC-SHA256, with a timestamp), under one
key held in the environment as SOA_SECRET_KEY on both deployments that read
it: the API (Vercel), which seals a token when the setup wizard provisions a
tenant, and the pipeline worker (Railway), which opens it to read catalogs.
No scheme of this app's own: Fernet is the library's, and `cryptography` was
already a dependency of both apps.

What it protects against: the token column read by anyone with database
access but not the deployment's environment — a backup, a support query, a
leaked read-only credential. What it does not: anyone holding both. The token
is also never sent to a browser and never logged (soa_shared/customers.py).

Rotating the key: open every sealed value with the old key and seal it with
the new one (MultiFernet would let both work during the move); nothing here
does it automatically.
"""
from cryptography.fernet import Fernet, InvalidToken

import soa_shared.config as config


class SecretBoxError(RuntimeError):
    """The key is missing or wrong, or the value was not sealed with it."""


def _fernet() -> Fernet:
    key = config.SOA_SECRET_KEY
    if not key:
        raise SecretBoxError("SOA_SECRET_KEY is not set on this service")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise SecretBoxError(
            "SOA_SECRET_KEY is not a Fernet key (32 url-safe base64-encoded bytes)"
        ) from exc


def seal(plaintext: str) -> str:
    """The ciphertext to store. Never returns or logs the plaintext."""
    if not plaintext:
        raise SecretBoxError("refusing to seal an empty secret")
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def open_sealed(sealed: str) -> str:
    """The plaintext of a value seal() produced under the current key."""
    try:
        return _fernet().decrypt(sealed.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        # No detail: the ciphertext is not secret, but there is nothing in
        # it an operator can act on beyond "wrong key or corrupted".
        raise SecretBoxError(
            "a stored token could not be opened with SOA_SECRET_KEY "
            "(wrong key, or the value is corrupted)"
        ) from exc
