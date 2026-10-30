"""
2V-3 Q9: the Overview's first load, and what each of its panels reads cold.

Petco's first /overview load left the Share of Algorithm tile, "last full
loop" and the revenue model on "Reading..." for about 40 s. The revenue
model's /revenue read supply's /access on the raw client, so it missed the
access read the Overview had just kept (console_cache.reads) on every load,
and on a cold one it waited on supply again. It now reads through the cache.
"""
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import WS, _get, _pair
from tests.test_console_2q1_cache import cache_on  # noqa: F401  (fixture)
from tests.test_console_read_models import http, upstream  # noqa: F401  (pytest fixtures)

from app.services import console_cache


def test_revenue_reads_the_access_the_overview_kept(http, db, upstream, cache_on):  # noqa: F811
    _pair(db, http, upstream)
    console_cache.clear()
    _get(http, 'overview', merchant=WS)
    before = len(upstream.calls)
    _get(http, 'revenue', merchant=WS)
    assert not [c for c in upstream.calls[before:] if c['path'].endswith('/access')]
