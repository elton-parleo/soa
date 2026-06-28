"""
Entry point for the /soa application.

Usage:
    cd /soa
    python main.py pipeline --cycle 2026-05 --study-type retailer_sephora --study-pattern retailer
    python main.py pipeline --cycle 2026-05-cola --study-type brand_vs_brand_cola --study-pattern brand_vs_brand --platforms chatgpt,claude
    python main.py run-cycle --cycle 2026-05
    python main.py code-cycle --cycle 2026-05
    python main.py metrics --cycle 2026-05
    python main.py setup-cycle --cycle 2026-05-cola --study-type brand_vs_brand_cola --study-pattern brand_vs_brand
"""
import argparse
import asyncio
import datetime
import logging
import sys

from soa_shared.config import validate
from soa_shared.database import session_factory
from soa_shared.models.soa_models import SoaCycle, SoaQuery
from runners.run_orchestrator import RunOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_VALID_STUDY_PATTERNS = ("retailer", "brand_at_retail", "brand_vs_brand")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SoA measurement toolchain")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # pipeline — full end-to-end coordinator (primary entry point)
    pipeline = subparsers.add_parser("pipeline", help="Run the full measurement pipeline")
    pipeline.add_argument("--cycle", required=True, help="Cycle code, e.g. 2026-05")
    pipeline.add_argument(
        "--study-type",
        default="retailer_sephora",
        help="Study type identifier, e.g. retailer_sephora, brand_vs_brand_cola (default: retailer_sephora)",
    )
    pipeline.add_argument(
        "--study-pattern",
        default=None,
        required=False,
        help=(
            "Study pattern for this cycle. "
            "If not provided, auto-detected from the query library. "
            "Values: retailer, brand_at_retail, brand_vs_brand. "
            "Set automatically to 'mixed' when the query library "
            "contains multiple patterns."
        ),
    )
    pipeline.add_argument(
        "--platforms",
        default=None,
        help="Comma-separated list of platforms (default from config)",
    )
    pipeline.add_argument(
        "--runs",
        type=int,
        default=None,
        help="Runs per query per platform (default from config)",
    )
    pipeline.add_argument(
        "--skip-runner",
        action="store_true",
        help="Skip Stage 1 (runner) — only run coding and metrics",
    )
    pipeline.add_argument(
        "--skip-coding",
        action="store_true",
        help="Skip Stage 2 (coding) — only run runner and metrics",
    )
    pipeline.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would run without calling any APIs",
    )
    pipeline.add_argument(
        "--verbose",
        action="store_true",
        help="Set log level to DEBUG",
    )

    # run-cycle — submit queries to LLM platforms
    run = subparsers.add_parser("run-cycle", help="Run an SoA measurement cycle")
    run.add_argument("--cycle", required=True, help="Cycle code, e.g. 2026-05")
    run.add_argument(
        "--study-type",
        default="retailer_sephora",
        help="Study type identifier (default: retailer_sephora)",
    )
    run.add_argument(
        "--platforms",
        default="chatgpt,perplexity,gemini",
        help="Comma-separated list of platforms (default: chatgpt,perplexity,gemini)",
    )
    run.add_argument(
        "--runs",
        type=int,
        default=None,
        help="Runs per query per platform (default from config)",
    )

    # code-cycle — parse raw responses into coded mentions
    code = subparsers.add_parser("code-cycle", help="Code raw responses for a cycle")
    code.add_argument("--cycle", required=True, help="Cycle code, e.g. 2026-05")
    code.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Max concurrent coding calls (default from config)",
    )

    # metrics — calculate metrics from coded data and export xlsx
    metrics = subparsers.add_parser(
        "metrics", help="Calculate SoA metrics for a cycle and export xlsx"
    )
    metrics.add_argument("--cycle", required=True, help="Cycle code, e.g. 2026-05")
    metrics.add_argument(
        "--no-export",
        action="store_true",
        help="Skip xlsx export (default: export enabled)",
    )
    metrics.add_argument(
        "--export-path",
        default=None,
        help="Custom output path for the xlsx file",
    )

    # setup-cycle — interactive cycle configuration
    setup = subparsers.add_parser(
        "setup-cycle",
        help="Create a cycle and configure its entities interactively",
    )
    setup.add_argument("--cycle", required=True, help="Cycle code, e.g. 2026-05-cola")
    setup.add_argument(
        "--study-type",
        required=True,
        help="Study type identifier, e.g. brand_vs_brand_cola",
    )
    setup.add_argument(
        "--study-pattern",
        default=None,
        required=False,
        help=(
            "Study pattern for this cycle. "
            "If not provided, auto-detected from the query library. "
            "Values: retailer, brand_at_retail, brand_vs_brand. "
            "Set automatically to 'mixed' when the query library "
            "contains multiple patterns."
        ),
    )

    return parser


def _get_or_create_cycle(
    cycle_code: str,
    study_type: str,
    study_pattern: str,
    platforms: list,
    runs_per_query: int,
) -> SoaCycle:
    with session_factory() as session:
        cycle = (
            session.query(SoaCycle)
            .filter(SoaCycle.cycle_code == cycle_code)
            .first()
        )

        if cycle is None:
            active_q = (
                session.query(SoaQuery)
                .filter_by(status="Active", study_type=study_type)
                .count()
            )
            total_planned = active_q * len(platforms) * runs_per_query

            cycle = SoaCycle(
                cycle_code=cycle_code,
                start_date=datetime.date.today(),
                total_runs_planned=total_planned,
                status="planned",
                study_type=study_type,
                study_pattern=study_pattern,
            )
            session.add(cycle)
            session.commit()
            logger.info("Created cycle %s (planned %d runs)", cycle_code, total_planned)

        elif cycle.status == "complete":
            print(
                f"WARNING: Cycle {cycle_code} is already complete. "
                "Use a new cycle_code to run again."
            )
            sys.exit(0)

        else:
            logger.info("Resuming cycle %s (status=%s)", cycle_code, cycle.status)

        session.expunge(cycle)
        return cycle


async def _pipeline(args: argparse.Namespace) -> None:
    validate()
    if getattr(args, "verbose", False):
        logging.getLogger().setLevel(logging.DEBUG)

    from soa_shared.database import session_factory
    from soa_shared.models.soa_models import SoaCycle

    with session_factory() as session:
        cycle = session.query(SoaCycle).filter_by(cycle_code=args.cycle).first()
        cycle_mode = cycle.cycle_mode if cycle else "query"

    if cycle_mode == "truecost":
        from sweep.truecost_sweep import run_truecost_sweep

        summary = await run_truecost_sweep(args.cycle)
        print(
            f"\nTruecost sweep complete for {args.cycle}: "
            f"captured={summary.captured} unavailable={summary.unavailable} "
            f"skipped={summary.skipped_already_done} "
            f"({summary.sku_count} SKUs x {summary.tier_count} tiers)\n"
        )
        return

    from orchestrator.pipeline import PipelineOrchestrator

    platforms = (
        [p.strip() for p in args.platforms.split(",") if p.strip()]
        if args.platforms
        else None
    )

    try:
        orchestrator = PipelineOrchestrator(
            cycle_code=args.cycle,
            study_type=args.study_type,
            study_pattern=args.study_pattern,
            platforms=platforms,
            runs_per_query=args.runs,
            skip_runner=args.skip_runner,
            skip_coding=args.skip_coding,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(f"\nERROR: {exc}\n")
        sys.exit(1)

    report = await orchestrator.run_pipeline()
    report.print_report()

    if report.pipeline_status in ("failed", "partial"):
        sys.exit(1)


async def _run_cycle(args: argparse.Namespace) -> None:
    validate()
    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    runs_per_query = args.runs

    study_type = getattr(args, "study_type", "retailer_sephora")
    _get_or_create_cycle(
        args.cycle, study_type, "retailer", platforms, runs_per_query or 5
    )

    orchestrator = RunOrchestrator(
        cycle_code=args.cycle,
        platforms=platforms,
        runs_per_query=runs_per_query,
    )

    summary = await orchestrator.run_cycle()
    summary.print_summary()

    if summary.total_planned and (summary.errors / summary.total_planned) > 0.20:
        logger.error(
            "Error rate %.0f%% exceeds 20%% threshold.",
            100 * summary.errors / summary.total_planned,
        )
        sys.exit(1)


async def _code_cycle(args: argparse.Namespace) -> None:
    validate()
    import soa_shared.config as config
    from parser.coding_orchestrator import CodingOrchestrator

    max_concurrent = args.concurrency or config.SOA_MAX_CODING_CONCURRENT
    orchestrator = CodingOrchestrator(
        cycle_code=args.cycle,
        max_concurrent=max_concurrent,
    )

    summary = await orchestrator.code_cycle()
    summary.print_summary()

    total_attempted = summary.coded + summary.validation_errors + summary.api_errors
    if total_attempted and (
        (summary.validation_errors + summary.api_errors) / total_attempted
    ) > 0.10:
        logger.error("Error rate exceeds 10%% threshold.")
        sys.exit(1)


def _metrics(args: argparse.Namespace) -> None:
    validate()
    from metrics.metrics_orchestrator import MetricsOrchestrator

    orchestrator = MetricsOrchestrator(
        cycle_code=args.cycle,
        export=not args.no_export,
        export_path=args.export_path,
    )

    try:
        summary = orchestrator.run_metrics()
    except ValueError as exc:
        print(f"\nERROR: {exc}\n")
        sys.exit(1)

    summary.print_summary()


def _setup_cycle(args: argparse.Namespace) -> None:
    validate()
    from soa_shared.models.soa_models import SoaEntity, SoaCycleEntity

    cycle_code = args.cycle
    study_type = args.study_type
    passed_pattern = args.study_pattern

    # Auto-detect study_pattern from query library if not explicitly provided
    with session_factory() as session:
        pattern_rows = (
            session.query(SoaQuery.study_pattern)
            .filter_by(study_type=study_type, status="Active")
            .distinct()
            .all()
        )
    detected = {r[0] for r in pattern_rows if r[0] is not None}
    if passed_pattern is not None:
        study_pattern = passed_pattern
    elif len(detected) == 0:
        study_pattern = "retailer"
    elif len(detected) == 1:
        study_pattern = list(detected)[0]
    else:
        study_pattern = "mixed"

    print(f"\nSetting up cycle: {cycle_code}")
    print(f"  study_type:    {study_type}")
    print(f"  study_pattern: {study_pattern}\n")

    # Create the cycle row
    with session_factory() as session:
        existing = (
            session.query(SoaCycle)
            .filter(SoaCycle.cycle_code == cycle_code)
            .first()
        )
        if existing:
            print(f"Cycle '{cycle_code}' already exists (status={existing.status}).")
            if existing.study_type != study_type or existing.study_pattern != study_pattern:
                print(
                    f"  WARNING: Existing cycle has study_type='{existing.study_type}' "
                    f"and study_pattern='{existing.study_pattern}'.\n"
                    "  Proceeding with existing values. To change, create a new cycle_code."
                )
            cycle_id = existing.id
        else:
            cycle = SoaCycle(
                cycle_code=cycle_code,
                start_date=datetime.date.today(),
                status="planned",
                study_type=study_type,
                study_pattern=study_pattern,
            )
            session.add(cycle)
            session.commit()
            cycle_id = cycle.id
            print(f"Created cycle '{cycle_code}' (id={cycle_id})\n")

    # Show available entities
    with session_factory() as session:
        entities = session.query(SoaEntity).order_by(SoaEntity.entity_type, SoaEntity.slug).all()
        if not entities:
            print("No entities found in soa_entities. Run seeds/soa_entities_seed.py first.\n")
        else:
            print("Available entities in soa_entities:")
            print(f"  {'slug':<30} {'type':<12} {'category':<15} name")
            print("  " + "-" * 72)
            for e in entities:
                print(f"  {e.slug:<30} {e.entity_type:<12} {(e.category or ''):<15} {e.name}")
            print()

    # Check for already-configured entities
    with session_factory() as session:
        existing_ces = (
            session.query(SoaCycleEntity)
            .filter_by(cycle_id=cycle_id)
            .all()
        )
    if existing_ces:
        print("Entities already configured for this cycle:")
        for ce in existing_ces:
            with session_factory() as session:
                entity = session.get(SoaEntity, ce.entity_id)
            print(f"  {ce.comparison_code}: {entity.slug if entity else '?'} ({ce.role})")
        print()
        print("Cycle entity configuration complete. Run 'python main.py pipeline' when ready.")
        return

    # Interactive entity entry
    print("Enter entities for this cycle. Press Enter with no slug to finish.")
    print("Format: comparison_code entity_slug role (e.g. M001 sephora primary)\n")

    entries = []
    code_num = 1
    while True:
        default_code = f"M{code_num:03d}"
        default_role = "primary" if code_num == 1 else "competitor"
        raw = input(f"  [{default_code}] entity_slug (or Enter to finish): ").strip()
        if not raw:
            if code_num == 1:
                print("  No entities entered. Exiting without configuring.\n")
                return
            break

        parts = raw.split()
        if len(parts) == 1:
            slug = parts[0]
            code = default_code
            role = default_role
        elif len(parts) == 2:
            slug, code = parts
            role = default_role
        elif len(parts) >= 3:
            slug, code, role = parts[0], parts[1], parts[2]
        else:
            print("  Invalid input. Try again.\n")
            continue

        if role not in ("primary", "competitor"):
            print(f"  Invalid role '{role}'. Use 'primary' or 'competitor'.\n")
            continue

        with session_factory() as session:
            entity = session.query(SoaEntity).filter_by(slug=slug).first()
        if entity is None:
            print(f"  Entity '{slug}' not found in soa_entities. Check the slug and try again.\n")
            continue

        entries.append({"slug": slug, "entity_id": entity.id, "code": code, "role": role})
        print(f"  Added: {code} → {entity.name} ({role})")
        code_num += 1

    if not entries:
        print("\nNo entities added. Exiting.\n")
        return

    primary_count = sum(1 for e in entries if e["role"] == "primary")
    if primary_count != 1:
        print(f"\nWARNING: {primary_count} primary entities (expected exactly 1).")

    print(f"\nCreating {len(entries)} cycle entity entries...")
    with session_factory() as session:
        for entry in entries:
            ce = SoaCycleEntity(
                cycle_id=cycle_id,
                entity_id=entry["entity_id"],
                comparison_code=entry["code"],
                role=entry["role"],
            )
            session.add(ce)
        session.commit()

    print("\nCycle setup complete. Summary:")
    for entry in entries:
        print(f"  {entry['code']}: {entry['slug']} ({entry['role']})")
    print(f"\nRun the pipeline with:")
    print(
        f"  python main.py pipeline --cycle {cycle_code} "
        f"--study-type {study_type} --study-pattern {study_pattern}\n"
    )


async def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "pipeline":
        await _pipeline(args)
    elif args.command == "run-cycle":
        await _run_cycle(args)
    elif args.command == "code-cycle":
        await _code_cycle(args)
    elif args.command == "metrics":
        _metrics(args)
    elif args.command == "setup-cycle":
        _setup_cycle(args)


if __name__ == "__main__":
    asyncio.run(main())
