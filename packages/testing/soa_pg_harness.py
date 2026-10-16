"""
2D: the test databases, shared by apps/api/tests and apps/pipeline/tests.

Production runs Postgres, and soa's JSON columns are Postgres `json`, which,
unlike sqlite's TEXT, has no equality or ordering operator: a DISTINCT, a
UNION, a GROUP BY or an `=` that lands on one raises UndefinedFunction, on
an empty table as on a full one. 2C-3's SELECT DISTINCT over
soa_queries.expected_answer reached production because every test ran on
sqlite. So any test module can run on both:

    from soa_pg_harness import postgres_engine, sqlite_engine, model_schema

    @pytest.fixture(params=['sqlite', 'postgres'])
    def db(request):
        engine = sqlite_engine() if request.param == 'sqlite' else postgres_engine()
        ...

or take the `any_engine` fixture (both, bare) or `pg_engine` (Postgres only),
which the suites' conftests import from here.

SOA_TEST_PG_URL names the database, e.g.

    SOA_TEST_PG_URL=postgresql://postgres@127.0.0.1:55432/postgres pytest

  * unset: the Postgres runs skip, locally. Under GitHub Actions they FAIL:
    CI sets the variable (.github/workflows/ci.yml), and a CI that skips
    them is how the DISTINCT got through;
  * set to a host that is not local: fail. Each test drops and recreates
    the public schema, so it must never point at a database anyone uses;
  * set and unreachable: fail, never skip.
"""
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

PG_URL_VAR = 'SOA_TEST_PG_URL'
LOCAL_HOSTS = ('127.0.0.1', 'localhost', '::1')


def pg_url():
    return os.getenv(PG_URL_VAR) or None


def sqlite_engine():
    """In-memory sqlite, one connection shared by every session (StaticPool),
    with NOW() defined as Postgres has it."""
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _now(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())
    return engine


def postgres_engine():
    """The local Postgres SOA_TEST_PG_URL names, with an empty public schema.
    Skips when the variable is unset outside CI; fails in every other case
    it cannot be used (see the module docstring)."""
    url = pg_url()
    if not url:
        if os.getenv('GITHUB_ACTIONS') == 'true':
            pytest.fail(f'{PG_URL_VAR} is not set: CI must run the Postgres tests, not skip them')
        pytest.skip(f'{PG_URL_VAR} is not set')
    host = urlparse(url).hostname
    if host not in LOCAL_HOSTS:
        pytest.fail(f'{PG_URL_VAR} must be a local Postgres, not {host}')
    engine = create_engine(url)
    try:
        with engine.begin() as c:
            c.exec_driver_sql("DROP SCHEMA public CASCADE")
            c.exec_driver_sql("CREATE SCHEMA public")
    except OperationalError as exc:
        engine.dispose()
        pytest.fail(f'{PG_URL_VAR} is set and its database is unreachable: {exc.orig}'.strip())
    return engine


def model_schema(engine):
    """Every soa_shared model's table, with production's column types (JSON
    is Postgres json). The models declare a few indexes twice (index=True on
    the column and an Index() of the same name): one is kept."""
    import importlib
    import pkgutil

    import soa_shared.models as package
    for module in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f'soa_shared.models.{module.name}')
    from soa_shared.models.soa_models import Base

    for table in Base.metadata.tables.values():
        seen = set()
        for index in list(table.indexes):
            if index.name in seen:
                table.indexes.discard(index)
            seen.add(index.name)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def pg_engine():
    """Postgres only, empty schema."""
    engine = postgres_engine()
    yield engine
    engine.dispose()


@pytest.fixture(params=['sqlite', 'postgres'])
def any_engine(request):
    """Each test twice: sqlite, then Postgres. Empty schema on both."""
    engine = sqlite_engine() if request.param == 'sqlite' else postgres_engine()
    yield engine
    engine.dispose()
