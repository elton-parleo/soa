"""
2P-1 (B3): a week-over-week pair, FL14's shape as cycle 1 and cycle 2 of
the same study seven days later with controlled differences.

Cycle 1 is 229 (FL3-wiggle-and-snug-20261014) on 2N-1's FL14 shape: the
FL13 shape (2K-4's _fl13_shape, its earlier cycle 178 another study), 2L-2's
retired line (Pure, AMORE its successor), 2L-4's 20 intent questions,
2M-2's 12 cheapest-place and where-to-buy questions with supply's deals,
2M-1's 10 attribute questions judged against the cycle's truth. Cycle 2 is
230 (FL4-wiggle-and-snug-20261021): every row of 229 copied seven days on
(runs, outcomes, mentions, the cached reference, the study's comparison
set), then the differences in CHANGES applied, each to named rows.

Prices and product names are the fixtures', not production's.
"""
import copy
import json
from datetime import timedelta

from sqlalchemy import inspect, text

from tests import console_fixture_229 as f229

CYCLE_1, CYCLE_2 = f229.CYCLE_229, 'FL4-wiggle-and-snug-20261021'
ID_1, ID_2 = 229, 230
#: a copied run's id: the cycle-1 run's plus this
RUN_OFFSET = 1_000_000
DAYS = 7

#: tables keyed by run_id that a cycle's reads join through its runs
RUN_TABLES = ('soa_coded_mentions', 'soa_other_mentions', 'soa_citations', 'soa_expectation_outcomes')
#: tables keyed by cycle_id copied whole
CYCLE_TABLES = ('soa_cycle_entities', 'soa_narratives')


def _rows(c, sql, **params):
    return [dict(r) for r in c.execute(text(sql), params).mappings()]


def _columns(c, table):
    return [r for r in c.execute(text(f"SELECT * FROM {table} WHERE 1 = 0")).keys()]


def _insert(c, table, row, encode):
    row = {k: encode(v) if isinstance(v, (dict, list)) else v for k, v in row.items()}
    c.execute(text(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)})"), row)


def _next_id(c, table):
    return (c.execute(text(f"SELECT MAX(id) FROM {table}")).scalar() or 0) + 1


def _shift(value):
    """A stored date or stamp, seven days on (sqlite hands text back)."""
    if value is None:
        return None
    if isinstance(value, str):
        from datetime import date, datetime
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return value
        moved = parsed + timedelta(days=DAYS)
        return moved.date().isoformat() if len(value) == 10 else moved.isoformat()
    return value + timedelta(days=DAYS)


def clone(db, encode):
    """Cycle 230: 229 copied seven days on, nothing else changed."""
    have = set(inspect(db).get_table_names())
    with db.begin() as c:
        [cycle] = _rows(c, "SELECT * FROM soa_cycles WHERE id = :i", i=ID_1)
        cycle.update(id=ID_2, cycle_code=CYCLE_2, start_date=_shift(cycle['start_date']))
        for key in ('created_at', 'completed_at', 'reference_as_of', 'end_date'):
            if key in cycle:
                cycle[key] = _shift(cycle[key])
        for key in ('share_of_algorithm', 'share_of_algorithm_version'):
            cycle.pop(key, None)
        ref = cycle.get('reference_prices')
        if ref:
            ref = json.loads(ref) if isinstance(ref, str) else copy.deepcopy(ref)
            if ref.get('as_of'):
                ref['as_of'] = _shift(ref['as_of'])
            cycle['reference_prices'] = ref
        _insert(c, 'soa_cycles', cycle, encode)
        for table in (t for t in CYCLE_TABLES if t in have):
            for row in _rows(c, f"SELECT * FROM {table} WHERE cycle_id = :i", i=ID_1):
                row.update(id=_next_id(c, table), cycle_id=ID_2)
                _insert(c, table, row, encode)
        runs = _rows(c, "SELECT * FROM soa_runs WHERE cycle_id = :i ORDER BY id", i=ID_1)
        for run in runs:
            run = {**run, 'id': run['id'] + RUN_OFFSET, 'cycle_id': ID_2}
            for key in ('run_at', 'created_at'):
                if key in run:
                    run[key] = _shift(run[key])
            _insert(c, 'soa_runs', run, encode)
        for table in (t for t in RUN_TABLES if t in have):
            rows = _rows(c, f"SELECT t.* FROM {table} t JOIN soa_runs r ON r.id = t.run_id WHERE r.cycle_id = :i",
                         i=ID_1)
            for row in rows:
                row.update(id=_next_id(c, table), run_id=row['run_id'] + RUN_OFFSET)
                if 'cycle_id' in row:
                    row['cycle_id'] = ID_2
                if row.get('scored_at') is not None:
                    row['scored_at'] = _shift(row['scored_at'])
                _insert(c, table, row, encode)
