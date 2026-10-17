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
