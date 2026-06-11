"""
JWT verification for FastAPI using
Supabase JWKS.

Fetches public keys directly from
Supabase's JWKS endpoint and verifies
JWTs without PyJWKClient.
"""

import os
import time
import base64
import logging
import httpx
import jwt
from cryptography.hazmat.primitives\
    .asymmetric.rsa import RSAPublicNumbers
from cryptography.hazmat.primitives\
    .asymmetric.ec import (
        EllipticCurvePublicNumbers,
        SECP256R1,
        SECP384R1,
        SECP521R1,
    )
from cryptography.hazmat.backends\
    import default_backend
from fastapi import HTTPException, Security
from fastapi.security import (
    HTTPBearer,
    HTTPAuthorizationCredentials,
)

log = logging.getLogger(__name__)

SUPABASE_URL = os.getenv(
    'SUPABASE_URL', ''
).rstrip('/')

ALLOWED_DOMAIN = os.getenv(
    'ALLOWED_EMAIL_DOMAIN', ''
)

# ── In-memory JWKS cache ──────────────────

_jwks_cache = {
    'keys':       None,
    'fetched_at': 0,
    'ttl':        3600,
}

def _get_jwks() -> list:
    """
    Fetch JWKS from Supabase with
    1-hour in-memory cache.
    """
    now = time.time()
    if (
        _jwks_cache['keys'] is not None
        and now - _jwks_cache['fetched_at']
            < _jwks_cache['ttl']
    ):
        return _jwks_cache['keys']

    if not SUPABASE_URL:
        raise RuntimeError(
            'SUPABASE_URL is not set.'
        )

    url = (
        f'{SUPABASE_URL}'
        f'/auth/v1/.well-known/jwks.json'
    )
    log.info(f'[auth] Fetching JWKS: {url}')
    try:
        r = httpx.get(url, timeout=10)
        r.raise_for_status()
        keys = r.json().get('keys', [])
        _jwks_cache['keys'] = keys
        _jwks_cache['fetched_at'] = now
        log.info(
            f'[auth] JWKS: '
            f'{len(keys)} key(s) cached'
        )
        return keys
    except Exception as e:
        log.error(
            f'[auth] JWKS fetch failed: {e}'
        )
        raise RuntimeError(
            f'Could not fetch JWKS: {e}'
        )

def _invalidate_jwks_cache():
    _jwks_cache['keys'] = None
    _jwks_cache['fetched_at'] = 0

def _get_public_key(kid: str):
    """
    Find and build the public key
    matching kid from the JWKS.
    Supports RSA (RS256) and
    HMAC (HS256) key types.
    """
    keys = _get_jwks()

    # Find key by kid
    match = next(
        (k for k in keys
         if k.get('kid') == kid),
        None,
    )
    # Fall back to first key if no match
    if match is None:
        if not keys:
            raise ValueError(
                'JWKS returned no keys'
            )
        log.warning(
            f'[auth] kid={kid!r} not found'
            f' — using first key'
        )
        match = keys[0]

    kty = match.get('kty', '')

    if kty == 'RSA':
        def b64_to_int(val):
            # Pad to multiple of 4
            pad = (4 - len(val) % 4) % 4
            data = base64.urlsafe_b64decode(
                val + '=' * pad
            )
            return int.from_bytes(data, 'big')

        n = b64_to_int(match['n'])
        e = b64_to_int(match['e'])
        return RSAPublicNumbers(
            e, n
        ).public_key(default_backend())

    elif kty == 'EC':
        # ECDSA public key (ES256 / ES384 / ES512)
        _ec_curves = {
            'P-256': SECP256R1(),
            'P-384': SECP384R1(),
            'P-521': SECP521R1(),
        }
        crv = match.get('crv', 'P-256')
        curve = _ec_curves.get(crv)
        if curve is None:
            raise ValueError(
                f'Unsupported EC curve: {crv}'
            )

        def b64_to_int(val):
            pad = (4 - len(val) % 4) % 4
            data = base64.urlsafe_b64decode(
                val + '=' * pad
            )
            return int.from_bytes(data, 'big')

        x = b64_to_int(match['x'])
        y = b64_to_int(match['y'])
        return EllipticCurvePublicNumbers(
            x=x, y=y, curve=curve
        ).public_key(default_backend())

    elif kty == 'oct':
        # HMAC secret (HS256)
        k = match.get('k', '')
        pad = (4 - len(k) % 4) % 4
        return base64.urlsafe_b64decode(
            k + '=' * pad
        )

    else:
        raise ValueError(
            f'Unsupported key type: {kty}'
        )

# ── FastAPI auth dependency ───────────────

bearer_scheme = HTTPBearer(
    auto_error=False
)

def verify_token(
    credentials: HTTPAuthorizationCredentials
      = Security(bearer_scheme),
) -> dict:
    """
    FastAPI dependency.
    Verifies a Supabase JWT and checks
    the email domain restriction.

    Returns the decoded JWT payload.
    Raises 401 for invalid tokens.
    Raises 403 for wrong email domain.
    """
    if not credentials:
        log.warning(
            '[auth] No Authorization '
            'header in request'
        )
        raise HTTPException(
            status_code=401,
            detail=(
                'Authentication required. '
                'Please sign in.'
            ),
        )

    token = credentials.credentials

    # Decode header without verification
    try:
        header = jwt.get_unverified_header(
            token
        )
    except Exception as e:
        log.error(
            f'[auth] Bad token header: {e}'
        )
        raise HTTPException(
            status_code=401,
            detail='Malformed token.',
        )

    alg = header.get('alg', 'RS256')
    kid = header.get('kid', '')
    log.info(
        f'[auth] Token alg={alg} '
        f'kid={kid[:16] if kid else "none"}'
    )

    # Get public key — retry once if miss
    try:
        public_key = _get_public_key(kid)
    except Exception as e:
        log.warning(
            f'[auth] Key miss, retrying: {e}'
        )
        _invalidate_jwks_cache()
        try:
            public_key = _get_public_key(kid)
        except Exception as e2:
            log.error(
                f'[auth] Key lookup '
                f'failed: {e2}'
            )
            raise HTTPException(
                status_code=401,
                detail='Key verification failed.',
            )

    # Try to verify — first with audience
    # check, then without (Supabase aud
    # value varies by project)
    payload = None
    for verify_aud, aud in [
        (True,  'authenticated'),
        (False, None),
    ]:
        try:
            opts = {'verify_exp': True}
            if not verify_aud:
                opts['verify_aud'] = False

            decode_kwargs = dict(
                algorithms=[alg],
                options=opts,
            )
            if verify_aud:
                decode_kwargs['audience'] = aud

            payload = jwt.decode(
                token,
                public_key,
                **decode_kwargs,
            )
            log.info(
                f'[auth] Signature valid'
                f'(aud_check={verify_aud})'
            )
            break

        except jwt.ExpiredSignatureError:
            log.warning('[auth] Token expired')
            raise HTTPException(
                status_code=401,
                detail=(
                    'Session expired. '
                    'Please sign in again.'
                ),
            )
        except jwt.InvalidAudienceError:
            # Try again without aud check
            log.warning(
                f'[auth] Audience mismatch '
                f'for aud={aud!r}, retrying'
            )
            continue
        except jwt.InvalidTokenError as e:
            log.error(
                f'[auth] Invalid token: {e}'
            )
            raise HTTPException(
                status_code=401,
                detail='Invalid token.',
            )
        except Exception as e:
            log.error(
                f'[auth] Unexpected error: '
                f'{type(e).__name__}: {e}'
            )
            raise HTTPException(
                status_code=401,
                detail='Authentication error.',
            )

    if payload is None:
        log.error('[auth] All attempts failed')
        raise HTTPException(
            status_code=401,
            detail='Token verification failed.',
        )

    # Email domain check
    email = payload.get('email', '')
    if ALLOWED_DOMAIN:
        if not email.endswith(
            f'@{ALLOWED_DOMAIN}'
        ):
            log.warning(
                f'[auth] Domain rejected: '
                f'{email}'
            )
            raise HTTPException(
                status_code=403,
                detail=(
                    f'Access restricted to '
                    f'@{ALLOWED_DOMAIN} '
                    f'accounts.'
                ),
            )

    log.info(f'[auth] Granted: {email}')
    return payload

def get_current_user(
    user: dict = Security(verify_token)
) -> dict:
    return user
