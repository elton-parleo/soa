"""
JWT verification for FastAPI.
Supports RS256 (RSA via JWKS), ES256
(ECDSA via JWKS), and HS256 (JWT secret
fallback when JWKS is empty).
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
from fastapi import (
    HTTPException, Security, Depends,
)
from fastapi.security import (
    HTTPBearer,
    HTTPAuthorizationCredentials,
)

log = logging.getLogger(__name__)

SUPABASE_PROJECT_URL = os.getenv(
    'SUPABASE_PROJECT_URL', ''
).rstrip('/')

SUPABASE_JWT_SECRET = os.getenv(
    'SUPABASE_JWT_SECRET', ''
)

ALLOWED_DOMAIN = os.getenv(
    'ALLOWED_EMAIL_DOMAIN', ''
)

# ── JWKS cache ────────────────────────────

_jwks_cache = {
    'keys':       None,
    'fetched_at': 0,
    'ttl':        3600,
}

def _get_jwks() -> list:
    now = time.time()
    if (
        _jwks_cache['keys'] is not None
        and now - _jwks_cache['fetched_at']
            < _jwks_cache['ttl']
    ):
        return _jwks_cache['keys']

    if not SUPABASE_PROJECT_URL:
        raise RuntimeError(
            'SUPABASE_PROJECT_URL is not set.'
        )

    url = (
        f'{SUPABASE_PROJECT_URL}'
        f'/auth/v1/.well-known/jwks.json'
    )
    try:
        r = httpx.get(url, timeout=10)
        r.raise_for_status()
        keys = r.json().get('keys', [])
        _jwks_cache['keys'] = keys
        _jwks_cache['fetched_at'] = now
        log.info(
            f'[auth] JWKS: {len(keys)} key(s)'
        )
        return keys
    except Exception as e:
        log.error(
            f'[auth] JWKS fetch error: {e}'
        )
        # Cache empty list briefly so we do
        # not hammer the endpoint on every req
        _jwks_cache['keys'] = []
        _jwks_cache['fetched_at'] = now
        return []

def _invalidate_jwks_cache():
    _jwks_cache['keys'] = None
    _jwks_cache['fetched_at'] = 0

# ── Key builders ──────────────────────────

def _build_rsa_key(jwk: dict):
    """Build RSA public key from JWK n/e."""
    def b64_to_int(val):
        pad = (4 - len(val) % 4) % 4
        data = base64.urlsafe_b64decode(
            val + '=' * pad
        )
        return int.from_bytes(data, 'big')

    n = b64_to_int(jwk['n'])
    e = b64_to_int(jwk['e'])
    return RSAPublicNumbers(
        e, n
    ).public_key(default_backend())

_EC_CURVES = {
    'P-256': SECP256R1(),
    'P-384': SECP384R1(),
    'P-521': SECP521R1(),
}

def _build_ec_key(jwk: dict):
    """Build ECDSA public key from JWK x/y."""
    crv = jwk.get('crv', 'P-256')
    curve = _EC_CURVES.get(crv)
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

    x = b64_to_int(jwk['x'])
    y = b64_to_int(jwk['y'])
    return EllipticCurvePublicNumbers(
        x=x, y=y, curve=curve
    ).public_key(default_backend())

# ── Key selection ─────────────────────────

def _get_signing_key(kid: str, alg: str):
    """
    Return (key, algorithms) for JWT decode.

    Priority:
    1. EC public key from JWKS  (ES256)
    2. RSA public key from JWKS (RS256)
    3. HMAC oct key from JWKS   (HS256)
    4. SUPABASE_JWT_SECRET      (HS256 fallback)
       — used when JWKS returns no keys,
       common with newer Supabase projects
       that use symmetric signing.
    """
    keys = _get_jwks()

    if keys:
        # Find by kid, fall back to first key
        match = next(
            (k for k in keys
             if k.get('kid') == kid),
            keys[0],
        )
        kty = match.get('kty', '')

        if kty == 'EC':
            return _build_ec_key(match), ['ES256']

        elif kty == 'RSA':
            return _build_rsa_key(match), ['RS256']

        elif kty == 'oct':
            k = match.get('k', '')
            pad = (4 - len(k) % 4) % 4
            secret = base64.urlsafe_b64decode(
                k + '=' * pad
            )
            return secret, ['HS256']

        else:
            raise ValueError(
                f'Unsupported JWK kty: {kty}'
            )

    # JWKS empty — use JWT secret (HS256)
    if SUPABASE_JWT_SECRET:
        log.info(
            '[auth] Using JWT secret '
            '(JWKS empty)'
        )
        return (
            SUPABASE_JWT_SECRET.encode('utf-8'),
            ['HS256'],
        )

    raise ValueError(
        'No signing key available: '
        'JWKS returned no keys and '
        'SUPABASE_JWT_SECRET is not set. '
        'Add SUPABASE_JWT_SECRET to your '
        '.env — find it in Supabase '
        'dashboard → Settings → API → '
        'JWT Settings.'
    )

# ── FastAPI dependency ────────────────────

bearer_scheme = HTTPBearer(auto_error=False)

def verify_token(
    credentials: HTTPAuthorizationCredentials
      = Security(bearer_scheme),
) -> dict:
    """
    FastAPI dependency.
    Verifies a Supabase JWT and checks
    the email domain restriction.

    Returns the decoded JWT payload.
    Raises 401 for invalid/missing tokens.
    Raises 403 for wrong email domain.
    """
    if not credentials:
        log.warning(
            '[auth] No Authorization header'
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
        header = jwt.get_unverified_header(token)
    except Exception as e:
        log.error(f'[auth] Bad token header: {e}')
        raise HTTPException(
            status_code=401,
            detail='Malformed token.',
        )

    alg = header.get('alg', 'RS256')
    kid = header.get('kid', '')
    log.info(
        f'[auth] alg={alg} '
        f'kid={kid[:16] if kid else "none"}'
    )

    # Get signing key (retry once on failure)
    try:
        signing_key, algorithms = \
            _get_signing_key(kid, alg)
    except ValueError as e:
        log.error(f'[auth] No key: {e}')
        raise HTTPException(
            status_code=401, detail=str(e),
        )
    except Exception as e:
        log.warning(
            f'[auth] Key lookup failed, '
            f'invalidating cache: {e}'
        )
        _invalidate_jwks_cache()
        try:
            signing_key, algorithms = \
                _get_signing_key(kid, alg)
        except Exception as e2:
            log.error(f'[auth] Key error: {e2}')
            raise HTTPException(
                status_code=401,
                detail='Key lookup failed.',
            )

    # Verify — try with audience check first,
    # then retry without (Supabase aud claim
    # varies by project configuration)
    payload = None
    for verify_aud, aud_val in [
        (True,  'authenticated'),
        (False, None),
    ]:
        try:
            opts = {'verify_exp': True}
            if not verify_aud:
                opts['verify_aud'] = False

            kw = dict(
                algorithms=algorithms,
                options=opts,
            )
            if verify_aud:
                kw['audience'] = aud_val

            payload = jwt.decode(
                token, signing_key, **kw
            )
            log.info(
                f'[auth] Token valid '
                f'aud_check={verify_aud}'
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
            log.warning(
                f'[auth] Audience mismatch '
                f'({aud_val!r}), retrying'
            )
            continue
        except jwt.InvalidTokenError as e:
            log.error(
                f'[auth] Token error: {e}'
            )
            raise HTTPException(
                status_code=401,
                detail='Invalid token.',
            )
        except Exception as e:
            log.error(
                f'[auth] Error: '
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

    # Email domain restriction
    email = payload.get('email', '')
    if ALLOWED_DOMAIN:
        if not email.endswith(
            f'@{ALLOWED_DOMAIN}'
        ):
            log.warning(
                f'[auth] Rejected: {email}'
            )
            raise HTTPException(
                status_code=403,
                detail=(
                    f'Access restricted to '
                    f'@{ALLOWED_DOMAIN}.'
                ),
            )

    log.info(f'[auth] Granted: {email}')
    return payload

def get_current_user(
    user: dict = Depends(verify_token)
) -> dict:
    return user
