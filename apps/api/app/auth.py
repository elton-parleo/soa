"""
JWT verification middleware for FastAPI.

Verifies Supabase JWTs using JWKS (JSON Web Key Set) published by Supabase at:
  {SUPABASE_URL}/auth/v1/.well-known/jwks.json

No static secret needed — Supabase publishes public keys which FastAPI uses
to verify token signatures.

Also enforces email domain restriction via ALLOWED_EMAIL_DOMAIN env var.
"""

import os
from functools import lru_cache

import jwt as pyjwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

SUPABASE_URL   = os.getenv('SUPABASE_URL', '')
ALLOWED_DOMAIN = os.getenv('ALLOWED_EMAIL_DOMAIN', 'parleo.io')

# Algorithms supported by Supabase JWTs.
# Supabase uses ES256 (ECDSA P-256) for newer projects.
# RS256 and HS256 kept for legacy / self-hosted instances.
ALLOWED_ALGORITHMS = ["ES256", "RS256", "HS256"]

# JWKS client — fetches and caches Supabase public keys.
# PyJWT's PyJWKClient handles caching and automatic key rotation internally.
@lru_cache(maxsize=1)
def get_jwks_client() -> PyJWKClient:
    if not SUPABASE_URL:
        raise RuntimeError(
            'SUPABASE_URL environment variable is not set.'
        )
    jwks_uri = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    return PyJWKClient(
        jwks_uri,
        cache_keys=True,
        # Cache JWKS for 1 hour
        lifespan=3600,
    )


# FastAPI security scheme — extracts Bearer token from Authorization header
bearer_scheme = HTTPBearer(auto_error=False)


def verify_token(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
) -> dict:
    """
    FastAPI dependency. Verifies the Supabase JWT and checks email domain.

    Usage in route:
      @router.get("/protected")
      def protected(user = Depends(verify_token)):
          return {"email": user["email"]}

    Returns the decoded JWT payload dict.
    Raises 401 if token is missing or invalid.
    Raises 403 if email domain does not match ALLOWED_EMAIL_DOMAIN.
    """
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please sign in.",
        )

    token = credentials.credentials

    try:
        jwks_client = get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # Primary attempt — with audience validation
        try:
            payload = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=ALLOWED_ALGORITHMS,
                options={"verify_exp": True},
                audience="authenticated",
            )
        except pyjwt.InvalidAudienceError:
            # Retry without audience validation.
            # Supabase audience claim varies by project configuration.
            payload = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=ALLOWED_ALGORITHMS,
                options={"verify_exp": True, "verify_aud": False},
            )

    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Session expired. Please sign in again.",
        )
    except pyjwt.InvalidAudienceError as e:
        raise HTTPException(status_code=401, detail=f"Invalid audience: {e}")
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"Could not verify token. Error: {e}",
        )

    # Domain restriction
    email = payload.get('email', '')
    if ALLOWED_DOMAIN and not email.endswith(f'@{ALLOWED_DOMAIN}'):
        raise HTTPException(
            status_code=403,
            detail=f"Access restricted to @{ALLOWED_DOMAIN} accounts.",
        )

    return payload


def get_current_user(user: dict = Depends(verify_token)) -> dict:
    """
    Alias for verify_token.
    Use as a dependency on any route that requires authentication.
    """
    return user
