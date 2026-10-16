"""
Per cycle: the surface names stored on the cycle, what each name means now,
and the platform and surface its run rows actually carry. READ ONLY.

    python3 scripts/report_surface_drift.py [--cycle <code> ...]

2D. Until 2D a cycle stored the name it was asked for and the orchestrator
resolved an alias only when the cycle ran: "gemini" ran as gemini_grounded.
So a cycle can say "gemini" while its rows sit on grounded_api (cycle 229),
beside an older cycle whose "gemini" rows sit on api (the pre-2B ungrounded
id). Since 2D, creation stores resolved ids and their surfaces
(soa_cycles.surfaces) and "gemini" means gemini_api.

For each stored name the script prints what it means now
(soa_shared/surfaces.resolve) and every (platform, surface, run count) the
cycle's rows carry under it: the name itself, what it means now, and what
it meant before 2D (PRE_2D_ALIASES). A row group is DRIFT when its surface
is not the surface the name means now. Rows on a platform no stored name
accounts for are listed as unclaimed.

Nothing is relabelled. Whether 229's rows should be is a separate decision;
this only shows where the drift is. One SELECT on soa_cycles and one GROUP
BY on soa_runs; on Postgres the transaction is SET READ ONLY first.
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import bindparam, inspect, text  # noqa: E402

from soa_shared import surfaces  # noqa: E402

#: What run_orchestrator.PLATFORM_ALIASES did before 2D, at run time.
PRE_2D_ALIASES = {'gemini': 'gemini_grounded'}


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _meaning(name: str):
    try:
        s = surfaces.resolve(name)
        return s.id, s.surface
    except surfaces.UnknownSurface:
        return None, None


def report(conn, cycle_codes: Optional[List[str]] = None) -> List[dict]:
    """One entry per cycle: {cycle_code, id, platforms, surfaces, names:
    [{name, now_id, now_surface, rows: [{platform, surface, runs, drift}]}],
    unclaimed: [...], drift: bool}."""
    has_surfaces = 'surfaces' in {c['name'] for c in inspect(conn).get_columns('soa_cycles')}
    columns = 'id, cycle_code, platforms' + (', surfaces' if has_surfaces else '')
    statement = f"SELECT {columns} FROM soa_cycles"
    if cycle_codes:
        statement += " WHERE cycle_code IN :codes"
    statement += " ORDER BY id"
    query = text(statement)
    if cycle_codes:
        query = query.bindparams(bindparam('codes', expanding=True))
    cycles = [dict(r) for r in conn.execute(query, {'codes': list(cycle_codes)} if cycle_codes else {}).mappings()]
    if not cycles:
        return []

    rows = defaultdict(list)
    grouped = text("""
        SELECT cycle_id, platform, surface, COUNT(*) AS runs FROM soa_runs
        WHERE cycle_id IN :ids GROUP BY cycle_id, platform, surface ORDER BY cycle_id, platform, surface
    """).bindparams(bindparam('ids', expanding=True))
    for r in conn.execute(grouped, {'ids': [c['id'] for c in cycles]}).mappings():
        rows[r['cycle_id']].append(dict(r))

    out = []
    for cycle in cycles:
        names = _json(cycle['platforms']) or []
        claimed, entries = set(), []
        for name in names:
            now_id, now_surface = _meaning(name)
            under = {name, now_id, PRE_2D_ALIASES.get(name)} - {None}
            groups = []
            for r in rows[cycle['id']]:
                if r['platform'] in under:
                    claimed.add((r['platform'], r['surface']))
                    groups.append({'platform': r['platform'], 'surface': r['surface'], 'runs': r['runs'],
                                   'drift': r['surface'] != now_surface})
            entries.append({'name': name, 'now_id': now_id, 'now_surface': now_surface, 'rows': groups})
        unclaimed = [r for r in rows[cycle['id']] if (r['platform'], r['surface']) not in claimed]
        out.append({'cycle_code': cycle['cycle_code'], 'id': cycle['id'], 'platforms': names,
                    'surfaces': _json(cycle.get('surfaces')), 'names': entries,
                    'unclaimed': [{k: r[k] for k in ('platform', 'surface', 'runs')} for r in unclaimed],
                    'drift': any(g['drift'] for e in entries for g in e['rows']) or bool(unclaimed)})
    return out


def render(entries: List[dict]) -> str:
    lines = []
    for c in entries:
        lines.append(f"cycle {c['cycle_code']} (id {c['id']}){'   DRIFT' if c['drift'] else ''}")
        lines.append(f"  stored platforms: {json.dumps(c['platforms'])}   stored surfaces: "
                     f"{json.dumps(c['surfaces']) if c['surfaces'] else '(none, created before 2D)'}")
        for e in c['names']:
            means = f"{e['now_id']} ({e['now_surface']})" if e['now_id'] else 'nothing (unknown name)'
            lines.append(f"  {e['name']:<16} means now: {means}")
            if not e['rows']:
                lines.append("      no runs")
            for g in e['rows']:
                note = (f"DRIFT: on {g['surface']}, the name now means {e['now_surface'] or 'nothing'}"
                        if g['drift'] else 'ok')
                lines.append(f"      rows: {g['platform']} on {g['surface']} x {g['runs']}   {note}")
        for u in c['unclaimed']:
            lines.append(f"  unclaimed rows: {u['platform']} on {u['surface']} x {u['runs']} "
                         f"(no stored name accounts for them)")
    return '\n'.join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Report stored surface names against the rows' surfaces. Read only.")
    parser.add_argument('--cycle', action='append', dest='cycles', help='cycle_code; repeatable; omit for every cycle')
    args = parser.parse_args(argv)

    from soa_shared.database import engine
    with engine.connect() as conn:
        if conn.dialect.name == 'postgresql':
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        entries = report(conn, args.cycles)
        conn.rollback()
    print(render(entries) if entries else 'no such cycle')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
