"""
Re-score a cycle's Layer 2 outcomes, in place, one tier at a time.

There was no entry point for this. scoring/expectation_batch.py has the
orchestration and the live pipeline calls it, but an ops re-score of a
cycle that has already run had to be typed out by hand — which is how you
end up re-scoring more than you meant to.

    python3 scripts/rescore_cycle.py --cycle <code> --tier brand_direct

What it does, in order:

  1. counts the existing outcomes per tier, and prints them;
  2. re-scores only the runs whose question is in a named tier;
  3. counts them again, prints the diff, and FAILS if a tier nobody
     asked for moved.

Step 3 is the point of the script. Re-scoring one tier is supposed to
leave the others exactly as they were, and "supposed to" is not a thing
you can put in a report. The check runs every time and costs nothing.

A re-score REPLACES each row (soa_expectation_outcomes is unique on
run_id and the scorer deletes before inserting), so running it twice is
the same as running it once. It does not touch soa_runs, soa_coded_
mentions, or anything Layer 1 produced.

It costs one extraction call per run. --dry-run prints the plan and the
current counts and makes no model call and no write.
"""
import argparse
import asyncio
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import bindparam, text  # noqa: E402

from soa_shared.database import engine  # noqa: E402
from soa_shared.expected_answers import QUERY_TIERS  # noqa: E402


def cycle_id(conn, cycle_code: str) -> int:
    row = conn.execute(
        text("SELECT id FROM soa_cycles WHERE cycle_code = :code"),
        {"code": cycle_code},
    ).fetchone()
    if not row:
        raise SystemExit(f"no cycle with code {cycle_code!r}")
    return row[0]


def outcome_counts(conn, cid: int) -> dict:
    """{tier: {outcome: n}} for everything currently stored."""
    rows = conn.execute(text("""
        SELECT tier, outcome, COUNT(*)
        FROM soa_expectation_outcomes
        WHERE cycle_id = :cid
        GROUP BY tier, outcome
    """), {"cid": cid}).fetchall()
    out = {}
    for tier, outcome, n in rows:
        out.setdefault(tier or '(untiered)', Counter())[outcome] = n
    return out


def run_ids_for(conn, cid: int, tiers) -> list:
    """
    Scoreable runs, narrowed to the named tiers.

    The expectation filter is the same one scoreable_run_ids uses and is
    not optional: a category-control question carries a tier and no
    expectation, and scoring it would write a row for a question nothing
    was ever expected of.
    """
    statement = text("""
        SELECT r.id
        FROM soa_runs r
        JOIN soa_queries q ON q.id = r.query_id
        WHERE r.cycle_id = :cid
          AND q.expected_answer IS NOT NULL
          AND q.tier IN :tiers
        ORDER BY r.id
    """).bindparams(bindparam("tiers", expanding=True))
    rows = conn.execute(statement, {"cid": cid, "tiers": list(tiers)}).fetchall()
    return [row[0] for row in rows]


def secondary_counts(conn, cid: int) -> dict:
    """
    {tier: {expectation type: {outcome: n}}} for the secondary results.

    Read apart from the primary outcomes because they move for different
    reasons and a re-score is expected to move only one of them. The
    correction that prompted this — a size read as a pack count — lands
    squarely on a pack_count secondary and must not touch the price
    outcome the secondary rides on.

    Counted in Python for the same reason tier_accuracy counts them in
    Python: secondary_results is a JSON array and the two dialects this
    runs on disagree about how to unnest one.
    """
    rows = conn.execute(text("""
        SELECT tier, secondary_results
        FROM soa_expectation_outcomes
        WHERE cycle_id = :cid AND secondary_results IS NOT NULL
    """), {"cid": cid}).fetchall()

    out = {}
    for tier, payload in rows:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        for item in payload or []:
            kind, outcome = item.get('type'), item.get('outcome')
            if not kind or not outcome:
                continue
            out.setdefault(tier or '(untiered)', {}).setdefault(kind, Counter())
            out[tier][kind][outcome] += 1
    return out


def _render_secondary(counts: dict) -> str:
    lines = []
    for tier in sorted(counts):
        for kind in sorted(counts[tier]):
            inner = counts[tier][kind]
            detail = ', '.join(f"{o} {n}" for o, n in sorted(inner.items()))
            lines.append(f"    {tier} / {kind:<12} {sum(inner.values()):>4}  ({detail})")
    return '\n'.join(lines) or '    (no secondary expectations)'


def changed_tiers(before: dict, after: dict) -> list:
    """Every tier whose primary outcome counts are not identical."""
    return [
        tier for tier in sorted(set(before) | set(after))
        if dict(before.get(tier, {})) != dict(after.get(tier, {}))
    ]


def _render(counts: dict) -> str:
    lines = []
    for tier in sorted(counts):
        inner = counts[tier]
        total = sum(inner.values())
        detail = ', '.join(f"{o} {n}" for o, n in sorted(inner.items()))
        lines.append(f"    {tier:<20} {total:>4}  ({detail})")
    return '\n'.join(lines) or '    (nothing scored yet)'


def diff_untouched(before: dict, after: dict, targeted) -> list:
    """
    Every tier that changed and was not asked to. Empty is the result
    this script exists to be able to state.
    """
    moved = []
    for tier in sorted(set(before) | set(after)):
        if tier in targeted:
            continue
        if dict(before.get(tier, {})) != dict(after.get(tier, {})):
            moved.append(tier)
    return moved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-score one or more tiers of a cycle, in place.",
    )
    parser.add_argument("--cycle", required=True, help="cycle_code, not id")
    parser.add_argument(
        "--tier", action="append", dest="tiers", choices=QUERY_TIERS,
        help="repeatable; omit to re-score every scoreable tier",
    )
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print the plan and the current counts; no model call, no write",
    )
    parser.add_argument(
        "--expect-unchanged", action="append", dest="expect_unchanged",
        default=[], metavar="TIER",
        help=(
            "repeatable; fail if this tier's PRIMARY outcome counts move. "
            "Secondary results are not covered — a correction can be meant "
            "to move a pack-count secondary while leaving the price "
            "outcome it rides on exactly where it was, and that is a "
            "distinction worth being able to assert."
        ),
    )
    args = parser.parse_args(argv)

    tiers = args.tiers or [t for t in QUERY_TIERS if t != 'category_control']

    with engine.connect() as conn:
        cid = cycle_id(conn, args.cycle)
        before = outcome_counts(conn, cid)
        before_secondary = secondary_counts(conn, cid)
        run_ids = run_ids_for(conn, cid, tiers)

    print(f"cycle {args.cycle} (id {cid})")
    print(f"re-scoring tiers: {', '.join(tiers)}")
    print(f"runs to score:    {len(run_ids)}")
    print("before:")
    print(_render(before))
    print("before (secondary):")
    print(_render_secondary(before_secondary))

    if not run_ids:
        print("\nnothing to do.")
        return 0

    if args.dry_run:
        print(f"\ndry run — no model calls, no writes. "
              f"A real run costs {len(run_ids)} extraction calls.")
        return 0

    if not os.getenv("OPEN_AI_API_KEY"):
        raise SystemExit("OPEN_AI_API_KEY is not set — extraction cannot run")

    from scoring.expectation_batch import score_runs

    summary = asyncio.run(score_runs(run_ids, concurrency=args.concurrency))

    with engine.connect() as conn:
        after = outcome_counts(conn, cid)
        after_secondary = secondary_counts(conn, cid)

    print(f"\nscored {summary.succeeded}/{summary.total} "
          f"(skipped {summary.skipped}, failed {summary.failed}, "
          f"retried {summary.retried})")
    print("after:")
    print(_render(after))
    print("after (secondary):")
    print(_render_secondary(after_secondary))

    moved_primary = changed_tiers(before, after)
    print(f"\nprimary outcomes changed in: "
          f"{', '.join(moved_primary) if moved_primary else 'nothing'}")

    for failure in summary.failures[:10]:
        print(f"    FAILED run {failure.run_id}: {failure.status} "
              f"{failure.error_message or ''}")

    problems = []

    moved = diff_untouched(before, after, set(tiers))
    if moved:
        problems.append(
            f"{', '.join(moved)} changed and {'was' if len(moved) == 1 else 'were'} "
            f"not re-scored. A re-score of one tier must leave the others alone."
        )

    # Asserted rather than eyeballed. "The price outcomes did not move" is
    # a claim somebody is going to put in a report, and it should be
    # checked by the thing that did the re-scoring.
    broke_promise = [t for t in args.expect_unchanged if t in moved_primary]
    if broke_promise:
        problems.append(
            f"{', '.join(broke_promise)} was expected to be unchanged and "
            f"its primary outcomes moved."
        )

    for problem in problems:
        print(f"\nPROBLEM: {problem}")
    if problems:
        return 1

    if args.expect_unchanged:
        print(f"unchanged, as promised: {', '.join(sorted(args.expect_unchanged))}")
    untouched = sorted(set(before) - set(tiers))
    if untouched:
        print(f"unchanged, not re-scored: {', '.join(untouched)}")
    return 0 if not summary.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
