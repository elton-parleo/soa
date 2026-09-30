"""
Re-code a cycle's pass-1 coding from scratch, then recalculate its metrics.

    python3 scripts/recode_cycle.py --cycle <code> --dry-run
    python3 scripts/recode_cycle.py --cycle <code>

The coding stage skips any run that already has coded mentions, so once a
cycle has been coded badly there was no way to code it again short of
deleting rows by hand. This script does that deletion properly and then
runs the ordinary coding and metrics stages, the same ones the pipeline
runs.

What it does, in order:

  1. audits the stored coding against the response text (the same check
     the coder now runs — parser/attribution_check.py) and prints it,
     along with the current overall metrics;
  2. deletes the cycle's soa_coded_mentions, soa_other_mentions and
     soa_incentive_scores rows — everything pass-1 coding writes — in one
     transaction;
  3. codes every success run with CodingOrchestrator;
  4. recalculates metrics with MetricsOrchestrator (which also refreshes
     the dashboard materialized view);
  5. audits and prints the metrics again, next to the before numbers.

It refuses to run on a cycle that has pass-2 rows (soa_coded_mentions_v2,
soa_price_observations, soa_citations, soa_pass2_coding_log): pass 2 codes
only the entities pass 1 found, so re-coding pass 1 underneath it would
leave pass 2 describing mentions that no longer exist. Findings and
recommendations are derived from metrics and are not regenerated here;
the script says so when a cycle has them.

If coding stops partway (API outage, Ctrl-C), rerun with --resume: it
skips the delete and codes only the runs that have no coding yet.

Cost: one coding call per run, two for a run whose first coding fails
validation or the attribution check. --dry-run prints the plan and the
audit and makes no model call and no write.
"""
import argparse
import asyncio
import logging
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import joinedload  # noqa: E402

from soa_shared.database import engine, session_factory  # noqa: E402
from soa_shared.models.soa_models import SoaCycleEntity  # noqa: E402
from parser.attribution_check import check_attribution, entity_terms  # noqa: E402
from parser.coding_response import MerchantCoding  # noqa: E402

PASS1_TABLES = ("soa_coded_mentions", "soa_other_mentions", "soa_incentive_scores")
PASS2_TABLES = (
    "soa_coded_mentions_v2", "soa_price_observations",
    "soa_citations", "soa_pass2_coding_log",
)
DERIVED_TABLES = ("soa_findings", "soa_recommendations")


def load_cycle_id(conn, cycle_code: str) -> int:
    row = conn.execute(
        text("SELECT id FROM soa_cycles WHERE cycle_code = :code"),
        {"code": cycle_code},
    ).fetchone()
    if not row:
        raise SystemExit(f"no cycle with code {cycle_code!r}")
    return row[0]


def run_table_counts(conn, cid: int, tables) -> dict:
    """Rows per table for the cycle's runs. Table names are module constants."""
    return {
        table: conn.execute(text(f"""
            SELECT COUNT(*) FROM {table} t
            JOIN soa_runs r ON r.id = t.run_id
            WHERE r.cycle_id = :cid
        """), {"cid": cid}).scalar()
        for table in tables
    }


def cycle_table_counts(conn, cid: int, tables) -> dict:
    return {
        table: conn.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE cycle_id = :cid"), {"cid": cid},
        ).scalar()
        for table in tables
    }


def overall_metrics(conn, cid: int) -> dict:
    rows = conn.execute(text("""
        SELECT e.name, m.total_runs, m.mention_rate, m.soa_pct, m.deal_citation_rate
        FROM soa_metrics_results m
        JOIN soa_entities e ON e.id = m.entity_id
        WHERE m.cycle_id = :cid AND m.slice_type = 'overall'
    """), {"cid": cid}).fetchall()
    return {r[0]: r[1:] for r in rows}


def audit(conn, cid: int) -> Counter:
    """Attribution issues in the stored coding, counted by kind."""
    with session_factory() as session:
        ces = (
            session.query(SoaCycleEntity)
            .filter_by(cycle_id=cid)
            .options(joinedload(SoaCycleEntity.entity))
            .all()
        )
        entity_to_code = {ce.entity_id: ce.comparison_code for ce in ces}
        code_to_terms = {ce.comparison_code: entity_terms(ce) for ce in ces}

    rows = conn.execute(text("""
        SELECT r.id, r.raw_response, m.entity_id, m.mentioned, m.evidence
        FROM soa_coded_mentions m
        JOIN soa_runs r ON r.id = m.run_id
        WHERE r.cycle_id = :cid
    """), {"cid": cid}).fetchall()

    by_run = {}
    for run_id, raw, entity_id, mentioned, evidence in rows:
        code = entity_to_code.get(entity_id)
        if code is None:
            continue
        raw_response, merchants = by_run.setdefault(run_id, (raw, {}))
        merchants[code] = MerchantCoding(
            merchant_id=code, mentioned=bool(mentioned), position=None,
            strength=None, deal_cited=False, deal_types=[],
            member_value_cited=False, evidence=evidence, confidence=1.0,
        )

    counts = Counter()
    runs_with_issues = 0
    for raw, merchants in by_run.values():
        issues = check_attribution(merchants, raw, code_to_terms)
        counts.update(i.kind for i in issues)
        runs_with_issues += bool(issues)
    counts["coded runs"] = len(by_run)
    counts["runs with any issue"] = runs_with_issues
    return counts


def print_audit(label: str, counts: Counter) -> None:
    print(f"\n{label}")
    for key in ("coded runs", "runs with any issue", "coded_but_absent",
                "evidence_names_other", "present_but_uncoded"):
        print(f"  {key:<24} {counts.get(key, 0):>6}")


def print_metrics(before: dict, after: dict = None) -> None:
    def pct(v):
        return f"{100 * float(v):5.1f}%" if v is not None else "    —"

    print(f"\n  {'entity':<12} {'runs':>5} {'mention':>8} {'SoA':>7} {'deal':>7}")
    for name in sorted(before or after or {}, key=lambda n: -(float((before or after)[n][1] or 0))):
        b = (before or {}).get(name)
        line = f"  {name:<12}"
        if b:
            line += f" {b[0]:>5} {pct(b[1]):>8} {pct(b[2]):>7} {pct(b[3]):>7}"
        if after is not None:
            a = after.get(name)
            line += "   →  " + (
                f"{a[0]:>5} {pct(a[1]):>8} {pct(a[2]):>7} {pct(a[3]):>7}" if a else "(none)"
            )
        print(line)


def delete_pass1(cid: int) -> dict:
    deleted = {}
    with engine.begin() as conn:
        for table in PASS1_TABLES:
            result = conn.execute(text(f"""
                DELETE FROM {table}
                WHERE run_id IN (SELECT id FROM soa_runs WHERE cycle_id = :cid)
            """), {"cid": cid})
            deleted[table] = result.rowcount
    return deleted


async def recode(cycle_code: str, concurrency: int):
    from parser.coding_orchestrator import CodingOrchestrator

    orchestrator = CodingOrchestrator(cycle_code=cycle_code, max_concurrent=concurrency)
    summary = await orchestrator.code_cycle()
    summary.print_summary()
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cycle", required=True, help="cycle_code to re-code")
    parser.add_argument("--dry-run", action="store_true",
                        help="audit and print the plan; no model calls, no writes")
    parser.add_argument("--resume", action="store_true",
                        help="skip the delete and code only runs with no coding yet")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--no-metrics", action="store_true",
                        help="stop after coding; do not recalculate metrics")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    with engine.connect() as conn:
        cid = load_cycle_id(conn, args.cycle)
        pass1 = run_table_counts(conn, cid, PASS1_TABLES)
        pass2 = run_table_counts(conn, cid, PASS2_TABLES)
        derived = cycle_table_counts(conn, cid, DERIVED_TABLES)
        success_runs = conn.execute(text(
            "SELECT COUNT(*) FROM soa_runs WHERE cycle_id = :cid AND status = 'success'"
        ), {"cid": cid}).scalar()
        before_metrics = overall_metrics(conn, cid)
        before_audit = audit(conn, cid)

    print(f"Cycle {args.cycle} (id {cid}): {success_runs} success runs")
    print("Pass-1 rows that will be replaced:" if not args.resume else "Pass-1 rows (kept, --resume):")
    for table, n in pass1.items():
        print(f"  {table:<24} {n:>6}")
    print_audit("Attribution audit of the stored coding:", before_audit)
    print("\nCurrent overall metrics:")
    print_metrics(before_metrics)

    if any(pass2.values()):
        print("\nRefusing: this cycle has pass-2 rows, which depend on pass-1 coding:")
        for table, n in pass2.items():
            print(f"  {table:<24} {n:>6}")
        return 1
    if any(derived.values()):
        print("\nNote: findings/recommendations exist and will NOT be regenerated:",
              ", ".join(f"{t}={n}" for t, n in derived.items()))

    if args.dry_run:
        print("\n--dry-run: no model calls, no writes.")
        return 0

    if not args.resume:
        deleted = delete_pass1(cid)
        print("\nDeleted:", ", ".join(f"{t}={n}" for t, n in deleted.items()))

    summary = asyncio.run(recode(args.cycle, args.concurrency))

    if args.no_metrics:
        return 0

    from metrics.metrics_orchestrator import MetricsOrchestrator
    MetricsOrchestrator(cycle_code=args.cycle, export=False).run_metrics().print_summary()

    with engine.connect() as conn:
        after_metrics = overall_metrics(conn, cid)
        after_audit = audit(conn, cid)
    print_audit("Attribution audit after re-coding:", after_audit)
    print("\nOverall metrics, before → after:")
    print_metrics(before_metrics, after_metrics)

    failed = summary.validation_errors + summary.api_errors
    if failed:
        print(f"\n{failed} runs failed coding; rerun with --resume to retry them.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
