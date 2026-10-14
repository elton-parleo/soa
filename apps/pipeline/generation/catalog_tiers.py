"""
The catalog-built question tiers live in soa_shared/catalog_tiers.py (2C),
so the API's study preview runs the same code the worker does. This name is
kept as that module itself (not a copy and not a star-import), so every
`from generation import catalog_tiers` and every monkeypatch on it sees one
module.
"""
import sys

from soa_shared import catalog_tiers as _shared

sys.modules[__name__] = _shared
