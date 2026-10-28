"""
2Q-1 (B3): what a console read computes per cycle, and supply's reads,
cached in the process.

`/overview?cycle=FL15…` took 15.7 s on a warm API, and the console's first
load gave up ("Failed to fetch"). One read made eleven supply calls in six
rounds (the merchant's kind four times, /reference and /deals twice) and
read the previous cycle in full (its rows, its Visibility, its deals) on
every request, though neither changes between two reads of the same pair.

Two caches, one store (bounded, least recently used first out):

  supply   reads(scope) wraps the supply client the console reads with
           (full_loop._client): get_reference, get_retailers, get_deals,
           get_access, get_merchant_catalog, and the merchant's kind
           (supply's /tenant). A result is kept SUPPLY_TTL seconds per org,
           method and arguments; a failed read is never kept (the next read
           tries again, as the score's errors are never stored).
  cycles   cycle_read(conn, cycle, name, compute, *parts): one cycle's read
           (its overview rows, its Visibility), kept under the cycle's
           stamp (cycle_stamp: its runs, outcomes and mentions, counted
           with their newest id and scored_at, and its reference's
           refreshed_at), so a rescore, a recode or a reference refresh is
           a new key, never a stale read; and CYCLE_TTL as a backstop. A
           pair's read is its two cycles' entries.

Every hit is a deep copy: the routers add to what they read.

On by default; SOA_CONSOLE_CACHE=0 turns it off (the API's tests do, since
their fixtures edit rows and supply's answers between two reads; the 2Q-1
tests turn it on).
"""
import asyncio
import copy
import hashlib
import json
import os
import threading
import time
import weakref
from collections import Counter, OrderedDict
from typing import Any, Callable, Optional

from sqlalchemy import text

SUPPLY_TTL = 300.0
CYCLE_TTL = 1800.0
MAX_ENTRIES = 256
#: The supply client's reads the console caches.
SUPPLY_READS = ('get_reference', 'get_retailers', 'get_deals', 'get_access', 'get_merchant_catalog')

_lock = threading.Lock()
_entries: 'OrderedDict[tuple, tuple]' = OrderedDict()
stats: Counter = Counter()
#: Reads under way, by (event loop, key): a second asker awaits the first's.
_inflight: dict = {}
#: Each connection's cycle stamps, for the life of the connection (one read).
_stamps: 'weakref.WeakKeyDictionary' = weakref.WeakKeyDictionary()


def enabled() -> bool:
    return os.environ.get('SOA_CONSOLE_CACHE', '1').strip().lower() not in ('0', 'false', 'off', 'no')


def clear() -> None:
    with _lock:
        _entries.clear()
        stats.clear()
        _stamps.clear()


def forget_org(org) -> int:
    """2U-5 (B1): drop every supply read kept for the org (and the merchant's
    kind, read from its /tenant): a compile or a stated send changes what
    supply serves, and a read kept from before it must not outlive it. The
    number of entries dropped."""
    with _lock:
        stale = [k for k in _entries if (k[0] == 'supply' and k[1] == org)
                 or (k[:2] == ('value', 'kind') and len(k) > 2 and k[2] == org)]
        for k in stale:
            del _entries[k]
    return len(stale)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _get(key: tuple):
    with _lock:
        hit = _entries.get(key)
        if hit is None or hit[0] < time.monotonic():
            if hit is not None:
                del _entries[key]
            stats['miss'] += 1
            return None
        _entries.move_to_end(key)
        stats['hit'] += 1
        return hit


def _put(key: tuple, value: Any, ttl: float) -> None:
    with _lock:
        _entries[key] = (time.monotonic() + ttl, value)
        _entries.move_to_end(key)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)


async def _once(key: tuple, make: Callable):
    """make()'s result, made once while it is under way: a read asked twice at
    once (the merchant's kind by the routing and the deals reads of one
    overview) is one supply call. Each asker gets its own copy."""
    loop = asyncio.get_running_loop()
    at = (id(loop), key)
    task = _inflight.get(at)
    if task is None:
        task = loop.create_task(make())
        _inflight[at] = task
        task.add_done_callback(lambda _t: _inflight.pop(at, None))
    return copy.deepcopy(await task)


# ─── supply ───────────────────────────────────────────────────────────────

class _Reads:
    """The supply client, its reads cached (see the module docstring)."""

    def __init__(self, client, org) -> None:
        self._client, self._org = client, org

    def __getattr__(self, name):
        target = getattr(self._client, name)
        if name not in SUPPLY_READS:
            return target

        async def read(*args, **kwargs):
            key = ('supply', self._org, name, args, tuple(sorted(kwargs.items())))
            hit = _get(key)
            if hit is not None:
                return copy.deepcopy(hit[1])

            async def fetch():
                result = await target(*args, **kwargs)
                if isinstance(result, tuple) and len(result) == 3 and result[2] is None:
                    _put(key, copy.deepcopy(result), SUPPLY_TTL)
                return result
            return await _once(key, fetch)
        return read


def reads(client, org):
    """The supply client `client` for the org (its id), its reads cached; the
    client itself when the cache is off."""
    return _Reads(client, org) if enabled() else client


async def cached(key: tuple, compute: Callable, ttl: float = SUPPLY_TTL):
    """An awaited value kept under `key` (None is never kept)."""
    if not enabled():
        return await compute()
    hit = _get(('value',) + key)
    if hit is not None:
        return copy.deepcopy(hit[1])

    async def fetch():
        value = await compute()
        if value is not None:
            _put(('value',) + key, copy.deepcopy(value), ttl)
        return value
    return await _once(('value',) + key, fetch)


# ─── one cycle's read ─────────────────────────────────────────────────────

def _scalar_row(conn, sql: str, cycle_id: int) -> tuple:
    try:
        row = conn.execute(text(sql), {'c': cycle_id}).fetchone()
    except Exception:  # noqa: BLE001 - a schema without the column (a test's): counted without it
        conn.rollback()
        return ()
    return tuple(str(v) if v is not None and not isinstance(v, (int, float)) else v for v in (row or ()))


def cycle_stamp(conn, cycle: dict) -> tuple:
    """What a cycle's read depends on that a rescore, a recode or a refresh
    changes: its runs, outcomes and Layer 1 mentions (how many, the newest
    id, the newest scored_at) and its cached reference's refreshed_at. Read
    once per connection."""
    cid = cycle['id']
    memo = _stamps.setdefault(conn, {})
    if cid not in memo:
        memo[cid] = _stamp(conn, cycle)
    return memo[cid]


def _stamp(conn, cycle: dict) -> tuple:
    cid = cycle['id']
    ref = cycle.get('reference_prices')
    if isinstance(ref, str):
        try:
            ref = json.loads(ref)
        except ValueError:
            ref = None
    refreshed = ref.get('refreshed_at') if isinstance(ref, dict) else None
    runs = _scalar_row(conn, "SELECT COUNT(*), MAX(id) FROM soa_runs WHERE cycle_id = :c", cid)
    outcomes = _scalar_row(conn, "SELECT COUNT(*), MAX(id), MAX(scored_at) FROM soa_expectation_outcomes "
                                 "WHERE cycle_id = :c", cid) or \
        _scalar_row(conn, "SELECT COUNT(*), MAX(id) FROM soa_expectation_outcomes WHERE cycle_id = :c", cid)
    mentions = _scalar_row(conn, "SELECT COUNT(*), MAX(cm.id) FROM soa_coded_mentions cm "
                                 "JOIN soa_runs r ON r.id = cm.run_id WHERE r.cycle_id = :c", cid)
    return (cid, cycle.get('status'), refreshed, runs, outcomes, mentions)


def cycle_read(conn, cycle: dict, name: str, compute: Callable[[], Any], *parts) -> Any:
    """`compute()`, one cycle's read named `name`, kept under the cycle's
    stamp and `parts` (the inputs beside the cycle it reads: the merchant's
    facts, the catalog's features)."""
    if not enabled():
        return compute()
    key = ('cycle', name, cycle_stamp(conn, cycle), digest(parts))
    hit = _get(key)
    if hit is not None:
        return copy.deepcopy(hit[1])
    value = compute()
    _put(key, copy.deepcopy(value), CYCLE_TTL)
    return value


def lookup(key: tuple) -> Any:
    """A copy of what keep() kept under `key`, or None."""
    hit = _get(('value',) + key) if enabled() else None
    return None if hit is None else copy.deepcopy(hit[1])


def keep(key: tuple, value: Any, ttl: float = CYCLE_TTL) -> None:
    """`value` under `key` (a read that answered in full: the caller keeps nothing a failed read made)."""
    if enabled() and value is not None:
        _put(('value',) + key, copy.deepcopy(value), ttl)


async def cycle_value(conn, cycle: dict, name: str, compute: Callable, *parts) -> Any:
    """cycle_read for an awaited read (2T-11, B1: a cycle's charter tiles,
    its baseline rows): kept under the cycle's stamp and `parts`, None never
    kept. The stamp is read on `conn` before `compute` runs."""
    if not enabled():
        return await compute()
    return await cached(('cycle', name, cycle_stamp(conn, cycle), digest(parts)), compute, ttl=CYCLE_TTL)


def size() -> int:
    with _lock:
        return len(_entries)


def describe(key_prefix: Optional[str] = None) -> dict:
    """{entries, hit, miss}: for the logs and the tests."""
    with _lock:
        n = sum(1 for k in _entries if key_prefix is None or k[0] == key_prefix)
    return {'entries': n, 'hit': stats['hit'], 'miss': stats['miss']}
