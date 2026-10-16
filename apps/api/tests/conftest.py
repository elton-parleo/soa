import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)
# 2D: the shared test databases (sqlite, and the local Postgres CI runs).
sys.path.insert(0, os.path.join(_APP, '..', '..', 'packages', 'testing'))

from soa_pg_harness import any_engine, pg_engine  # noqa: E402,F401  (pytest fixtures)
