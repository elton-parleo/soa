"""
SQLAlchemy engine and session factory for soa_shared.

Supports two connection modes:
  - Direct (pipeline/Railway): uses SUPABASE_DB_HOST_URL + SUPABASE_DB_PASSWORD
    to construct a URL, or DATABASE_URL if provided directly.
  - Pooled (API/Vercel): uses DATABASE_URL_POOLED for serverless environments.

Set USE_POOLED_DB=true to switch to pooled mode.
"""
import functools
import os
import time

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import scoped_session, sessionmaker

load_dotenv()

from soa_shared.models.base import Base
import soa_shared.models.merchant_ref  # noqa: F401 — register Merchant mirror
import soa_shared.models.soa_models    # noqa: F401 — register all SoA tables


def get_database_url(pooled: bool = False):
    """
    Returns the appropriate database URL.
    Pipeline uses direct connection.
    API/Vercel uses pooled connection.
    """
    if pooled:
        url = os.getenv(
            'DATABASE_URL_POOLED',
            os.getenv('DATABASE_URL')
        )
    else:
        url = os.getenv('DATABASE_URL')

    # Fall back to constructing URL from Supabase env vars
    if not url:
        host = os.getenv("SUPABASE_DB_HOST_URL")
        password = os.getenv("SUPABASE_DB_PASSWORD")
        if host and password:
            return URL.create(
                drivername="postgresql",
                username="postgres.epuofomhfngvkkamlfiz",
                host=host,
                database="postgres",
                port="6543",
                password=password,
            )
        raise ValueError(
            'DATABASE_URL environment variable is not set. '
            'Set DATABASE_URL or SUPABASE_DB_HOST_URL + SUPABASE_DB_PASSWORD.'
        )
    return url


_USE_POOLED = os.getenv('USE_POOLED_DB', 'false').lower() == 'true'

_pool_size_str = os.getenv("DATABASE_POOL_SIZE")
_pool_size = int(_pool_size_str) if _pool_size_str else 5

_db_url = get_database_url(_USE_POOLED)

# SQLite (used in tests) does not support QueuePool args
_is_sqlite = (
    isinstance(_db_url, str) and _db_url.startswith("sqlite")
) or (
    hasattr(_db_url, 'drivername') and 'sqlite' in str(_db_url.drivername)
)

_pool_kwargs = {} if _is_sqlite else (
    {"pool_size": 1, "max_overflow": 0}
    if _USE_POOLED else
    {"pool_size": _pool_size, "max_overflow": 2}
)

engine = create_engine(
    _db_url,
    pool_pre_ping=not _is_sqlite,
    pool_recycle=240 if not _is_sqlite else -1,
    **_pool_kwargs,
)

# DATABASE_URL exposed for backward compat (config.py references it)
DATABASE_URL = engine.url

session_factory = sessionmaker(expire_on_commit=False, bind=engine)
Session = scoped_session(session_factory)


def get_session():
    return Session()


def retry_db_operation(retries=3, delay=1, backoff=2):
    """
    Retries a DB operation on OperationalError and disposes the engine
    so SQLAlchemy recreates fresh connections.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            wait = delay
            while attempt < retries:
                try:
                    return func(*args, **kwargs)
                except OperationalError as e:
                    attempt += 1
                    try:
                        engine.dispose()
                        print("[DB] Disposing engine due to OperationalError")
                    except Exception:
                        pass
                    if attempt >= retries:
                        raise
                    print(
                        f"[DB RETRY] Attempt {attempt}/{retries} failed: {e}. "
                        f"Retrying in {wait}s..."
                    )
                    time.sleep(wait)
                    wait *= backoff
        return wrapper
    return decorator
