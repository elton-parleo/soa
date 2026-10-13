"""
2B §4: accuracy per surface, split by `surface` and never pooled.

`api`, `grounded_api` and `consumer_ui` answers come from different kinds of
surface, and an accuracy averaged across them describes none of them. So
this returns one entry per surface kind, each with its platforms, and NO
cross-surface total — the absence of that number is the point.

Within a surface the rules are the report's usual ones (app/services/
tier_accuracy.py): accuracy = exact / scored, where scored = exact +
partial + stale + wrong; partial is reported apart from exact; absent,
unscoreable and unverifiable stay out of the denominator and in the counts.
Coverage comes from the runs: a wall or an empty consumer answer is a
result (counted), a failed call is not.

Pure aggregation over rows; rows_for_cycle() is the SQL that feeds it.
Sync copies to apps/api/soa_shared/ and apps/pipeline/soa_shared/.
"""
from typing import Iterable, List

from sqlalchemy import text

from soa_shared import surfaces

SCORED = ('exact', 'partial', 'stale', 'wrong')
VALUE = SCORED + ('absent', 'unscoreable', 'unverifiable')


def _rate(n, d):
    return round(n / d, 4) if d else None


def _summary(counts: dict) -> dict:
    scored = sum(counts.get(o, 0) for o in SCORED)
    return {
        'counts': dict(counts),
        'scored': scored,
        'accuracy': _rate(counts.get('exact', 0), scored),
        'partial_rate': _rate(counts.get('partial', 0), scored),
        'stale_rate': _rate(counts.get('stale', 0), scored),
        'wrong_rate': _rate(counts.get('wrong', 0), scored),
        'unverifiable': counts.get('unverifiable', 0),
    }


def summarise(outcome_rows: Iterable, run_rows: Iterable) -> List[dict]:
    """
    outcome_rows: (surface, platform, outcome, n) for value-tier outcomes.
    run_rows:     (surface, platform, status, answer_status, n) for runs.
    A row whose surface is NULL (a run written before 2B's backfill) is
    placed by its platform; one no catalogue entry knows is reported
    under 'unlabelled', never folded into a labelled surface.
    """
    out = {}

    def entry(surface, platform):
        surface = surface or surfaces.surface_of(platform) or 'unlabelled'
        e = out.setdefault(surface, {
            'surface': surface, 'label': surfaces.SURFACE_LABELS.get(surface, surface),
            'counts': {}, 'platforms': {},
            'coverage': {'runs': 0, 'results': 0, 'answered': 0, 'no_ai_answer': 0,
                         'sign_in_wall': 0, 'blocked': 0, 'failed': 0},
        })
        p = e['platforms'].setdefault(platform, {
            'platform': platform, 'collector': surfaces.collector_of(platform),
            'agent': surfaces.agent_of(platform), 'counts': {},
            'coverage': {'runs': 0, 'results': 0, 'answered': 0, 'no_ai_answer': 0,
                         'sign_in_wall': 0, 'blocked': 0, 'failed': 0},
        })
        return e, p

    for surface, platform, outcome, n in outcome_rows:
        if outcome not in VALUE:
            continue
        e, p = entry(surface, platform)
        for bucket in (e['counts'], p['counts']):
            bucket[outcome] = bucket.get(outcome, 0) + n

    for surface, platform, status, answer_status, n in run_rows:
        e, p = entry(surface, platform)
        for cov in (e['coverage'], p['coverage']):
            cov['runs'] += n
            if answer_status in surfaces.ANSWER_STATUSES:
                cov['results'] += n
                cov[answer_status] += n
            elif status not in ('success',):
                cov['failed'] += n

    result = []
    for surface in [s for s in surfaces.SURFACE_KINDS if s in out] + \
            sorted(s for s in out if s not in surfaces.SURFACE_KINDS):
        e = out[surface]
        e.update(_summary(e['counts']))
        e['platforms'] = [
            {**p, **_summary(p['counts'])}
            for _k, p in sorted(e['platforms'].items())
        ]
        result.append(e)
    return result


def rows_for_cycle(conn, cycle_id: int) -> tuple:
    outcome_rows = conn.execute(text("""
        SELECT COALESCE(o.surface, r.surface), o.platform, o.outcome, COUNT(*)
        FROM soa_expectation_outcomes o
        JOIN soa_runs r ON r.id = o.run_id
        WHERE o.cycle_id = :cid AND (o.tier IS NULL OR o.tier <> 'brand_direct')
        GROUP BY COALESCE(o.surface, r.surface), o.platform, o.outcome
    """), {"cid": cycle_id}).fetchall()
    run_rows = conn.execute(text("""
        SELECT surface, platform, status, answer_status, COUNT(*)
        FROM soa_runs WHERE cycle_id = :cid
        GROUP BY surface, platform, status, answer_status
    """), {"cid": cycle_id}).fetchall()
    return outcome_rows, run_rows


def for_cycle(conn, cycle_id: int) -> List[dict]:
    return summarise(*rows_for_cycle(conn, cycle_id))
