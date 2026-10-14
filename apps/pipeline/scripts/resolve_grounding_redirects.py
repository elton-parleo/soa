"""
Recover the destination site of a cycle's stored grounding redirects.

Gemini's grounding chunks are vertexaisearch.cloud.google.com redirect
URLs, and before soa_runs.grounding existed only those URLs were stored
(soa_runs.retrieved_sources): the chunk titles that name the site, and the
supports that say which answer span each chunk backs, were dropped. This
script recovers the one of those that can still be recovered without a
model: where each redirect goes.

    python3 scripts/resolve_grounding_redirects.py --cycle <code> [--tier brand_direct] [--dry-run]

For every run in the cycle with retrieved_sources:

  1. builds soa_runs.grounding from retrieved_sources when the run has none
     ({uri, title: null, domain} per URL, no supports — none were stored);
  2. for each source with no domain at a redirect host, one HEAD request
     with the pipeline's declared bot UA (scan.fetcher.USER_AGENT), redirects
     followed, no body read, and stores the destination's domain beside the
     URI with `resolved_url` and `resolved_at`;
  3. writes the run's grounding back (not with --dry-run).

The 24-hour cache is the stored `resolved_at`: a source resolved within 24
hours is not requested again. A URI that fails (a block, a timeout, an
expired redirect) is stored with `resolve_error` and no domain, so it
grounds nothing; it is retried after 24 hours like any other.

It never re-asks a model and never touches soa_expectation_outcomes:
re-classify afterwards with scripts/rescore_cycle.py --classify-only.
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runners import grounding as gr  # noqa: E402

CACHE_TTL = timedelta(hours=24)
TIMEOUT_SECONDS = 8.0
MAX_REDIRECTS = 5


def default_resolver(uri: str) -> dict:
    """One HEAD, redirects followed, with the declared bot UA.
    {'resolved_url', 'status'} or {'error'}."""
    import httpx

    from scan.fetcher import USER_AGENT

    try:
        with httpx.Client(follow_redirects=True, max_redirects=MAX_REDIRECTS,
                          timeout=TIMEOUT_SECONDS, headers={'User-Agent': USER_AGENT}) as client:
            response = client.head(uri)
    except httpx.TooManyRedirects as exc:
        return {'error': f'too many redirects ({exc})'}
    except Exception as exc:  # noqa: BLE001 - recorded, never raised
        return {'error': type(exc).__name__}
    hops = [str(r.url) for r in response.history]
    # A destination that refuses HEAD (405) or a bot (403) still named
    # itself by redirecting there: the last hop's URL is the site.
    return {'resolved_url': str(response.url), 'status': response.status_code,
            'hops': len(hops)}


def _fresh(source: dict, now: datetime) -> bool:
    at = source.get('resolved_at')
    if not at:
        return False
    try:
        when = datetime.fromisoformat(str(at).replace('Z', '+00:00'))
    except ValueError:
        return False
    return now - when < CACHE_TTL


def is_redirect(uri) -> bool:
    from soa_shared.expected_answers import normalize_domain
    return normalize_domain(uri) in gr.REDIRECT_HOSTS


def resolve_run(retrieved_sources, grounding, *, resolver: Callable[[str], dict],
                now: datetime, memo: Optional[dict] = None) -> tuple:
    """(grounding, counts) for one run. Pure but for `resolver`."""
    memo = memo if memo is not None else {}
    counts = Counter()
    if not isinstance(grounding, dict) or not grounding.get('sources'):
        grounding = gr.build([gr.source(uri) for uri in retrieved_sources or [] if uri]) or {}
        if grounding:
            counts['built'] += 1
    for source in grounding.get('sources') or []:
        uri = source.get('uri')
        if source.get('domain') or not is_redirect(uri):
            continue
        if _fresh(source, now):
            counts['cached'] += 1
            continue
        if uri not in memo:
            memo[uri] = resolver(uri)
            counts['requested'] += 1
        result = memo[uri]
        domain = gr.domain_of(result.get('resolved_url'))
        source.update({'resolved_at': now.isoformat(), 'resolved_url': result.get('resolved_url'),
                       'domain': domain})
        if domain:
            source.pop('resolve_error', None)
            counts['resolved'] += 1
        else:
            source['resolve_error'] = result.get('error') or (
                f"no site at {result.get('resolved_url')!r} (status {result.get('status')})")
            counts['failed'] += 1
    return grounding, counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--cycle', required=True, help='cycle_code')
    parser.add_argument('--tier', action='append', dest='tiers',
                        help="only runs whose question is in this tier (repeatable)")
    parser.add_argument('--dry-run', action='store_true', help='resolve and print; write nothing')
    args = parser.parse_args(argv)

    from sqlalchemy import text

    from soa_shared.database import engine

    with engine.connect() as conn:
        row = conn.execute(text("SELECT id FROM soa_cycles WHERE cycle_code = :c"),
                           {'c': args.cycle}).fetchone()
        if not row:
            raise SystemExit(f"no cycle with code {args.cycle!r}")
        runs = conn.execute(text("""
            SELECT r.id, r.platform, r.retrieved_sources, r.grounding, q.tier
            FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id
            WHERE r.cycle_id = :cid AND r.retrieved_sources IS NOT NULL ORDER BY r.id
        """), {'cid': row[0]}).fetchall()
    if args.tiers:
        runs = [r for r in runs if r[4] in args.tiers]

    now = datetime.now(timezone.utc)
    memo, total, domains, updates = {}, Counter(), Counter(), []
    for run_id, _platform, retrieved, grounding, _tier in runs:
        retrieved = json.loads(retrieved) if isinstance(retrieved, str) else retrieved
        grounding = json.loads(grounding) if isinstance(grounding, str) else grounding
        result, counts = resolve_run(retrieved, grounding, resolver=default_resolver,
                                     now=now, memo=memo)
        total.update(counts)
        for source in result.get('sources') or []:
            domains[source.get('domain') or f"(unresolved: {source.get('resolve_error')})"] += 1
        if counts['built'] or counts['requested'] or counts['resolved'] or counts['failed']:
            updates.append((run_id, result))

    print(f"cycle {args.cycle}: {len(runs)} runs with retrieved_sources, "
          f"{len(memo)} distinct redirect URIs requested")
    print('  ' + ', '.join(f"{k}={v}" for k, v in sorted(total.items())))
    print('  destination domains:')
    for domain, n in domains.most_common():
        print(f"    {n:4d}  {domain}")
    if args.dry_run:
        print(f"\ndry run — {len(updates)} runs would be written; nothing written.")
        return 0
    with engine.begin() as conn:
        for run_id, result in updates:
            conn.execute(text("UPDATE soa_runs SET grounding = :g WHERE id = :id"),
                         {'g': json.dumps(result), 'id': run_id})
    print(f"\nwrote soa_runs.grounding on {len(updates)} runs.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
