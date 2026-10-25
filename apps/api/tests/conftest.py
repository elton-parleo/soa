import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)
# 2D: the shared test databases (sqlite, and the local Postgres CI runs).
sys.path.insert(0, os.path.join(_APP, '..', '..', 'packages', 'testing'))

from soa_pg_harness import any_engine, pg_engine  # noqa: E402,F401  (pytest fixtures)

import pytest  # noqa: E402

#: 2I-2: the worker's settings, never the API's. Stripped from every API test
#: so nothing here silently depends on them.
WORKER_ONLY_SETTINGS = ('SOA_CONSUMER_SURFACES_ENABLED', 'SERPAPI_API_KEY')


@pytest.fixture(autouse=True)
def _no_worker_settings_in_the_api(monkeypatch):
    for name in WORKER_ONLY_SETTINGS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _console_cache(monkeypatch):
    """2Q-1 (B3): the console's in-process cache, off unless a test turns it
    on (its fixtures edit rows and supply's answers between two reads of the
    same cycle), and empty at every test's start."""
    from app.services import console_cache
    monkeypatch.setenv('SOA_CONSOLE_CACHE', os.environ.get('SOA_TEST_CONSOLE_CACHE', '0'))
    console_cache.clear()
    yield
    console_cache.clear()
