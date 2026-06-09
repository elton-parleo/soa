"""
Verification script for multi-study entity support migration.

Runs all checks in sequence and prints PASS or FAIL for each.

Usage:
    cd /soa && python seeds/verify_multi_study.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from soa_shared.database import engine, session_factory
from sqlalchemy import text

failures = []


def check(label: str, passed: bool, detail: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    suffix = f" ({detail})" if detail else ""
    print(f"  {status}: {label}{suffix}")
    if not passed:
        failures.append(label)


# ---------------------------------------------------------------------------
# CHECK 1 — Schema verification
# ---------------------------------------------------------------------------
print("\n[CHECK 1] Schema verification")
with engine.connect() as conn:
    checks = {
        "soa_entities table": "SELECT COUNT(*) FROM soa_entities",
        "soa_cycle_entities table": "SELECT COUNT(*) FROM soa_cycle_entities",
        "soa_queries.study_type column": """
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name='soa_queries' AND column_name='study_type'
        """,
        "soa_queries.study_pattern column": """
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name='soa_queries' AND column_name='study_pattern'
        """,
        "soa_cycles.study_type column": """
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name='soa_cycles' AND column_name='study_type'
        """,
        "soa_coded_mentions.entity_id column": """
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name='soa_coded_mentions' AND column_name='entity_id'
        """,
    }
    for label, sql in checks.items():
        count = conn.execute(text(sql)).scalar()
        check(label, count and count > 0, f"count={count}")

# ---------------------------------------------------------------------------
# CHECK 2 — Entity seed verification
# ---------------------------------------------------------------------------
print("\n[CHECK 2] Entity seed verification")
with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT slug, entity_type, category, merchant_id IS NOT NULL AS has_merchant
        FROM soa_entities
        ORDER BY slug
    """)).fetchall()

expected_slugs = {"brand-direct", "nordstrom-beauty", "sephora", "ulta-beauty"}
found_slugs = {r[0] for r in rows}
check("All four beauty entities seeded", expected_slugs.issubset(found_slugs),
      f"found={found_slugs}")

for row in rows:
    slug, etype, cat, has_merchant = row
    check(
        f"  {slug} has correct entity_type",
        (slug == "brand-direct" and etype == "aggregate") or
        (slug != "brand-direct" and etype == "retailer"),
        f"type={etype}",
    )

print("  soa_entities contents:")
for row in rows:
    print(f"    {row[0]:<30} type={row[1]:<12} cat={row[2]:<10} merchant_linked={row[3]}")

# ---------------------------------------------------------------------------
# CHECK 3 — Cycle entity seed verification
# ---------------------------------------------------------------------------
print("\n[CHECK 3] Cycle entity configuration")
with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT
            c.cycle_code,
            c.study_type,
            c.study_pattern,
            COUNT(ce.id) AS entity_count
        FROM soa_cycles c
        LEFT JOIN soa_cycle_entities ce ON ce.cycle_id = c.id
        GROUP BY c.id, c.cycle_code, c.study_type, c.study_pattern
        ORDER BY c.cycle_code
    """)).fetchall()

for row in rows:
    check(
        f"Cycle '{row[0]}' has entities configured",
        row[3] > 0,
        f"study={row[1]} pattern={row[2]} entities={row[3]}",
    )

# ---------------------------------------------------------------------------
# CHECK 4 — Query study_type backfill
# ---------------------------------------------------------------------------
print("\n[CHECK 4] Query study_type backfill")
with engine.connect() as conn:
    null_count = conn.execute(text("""
        SELECT COUNT(*) FROM soa_queries
        WHERE study_type IS NULL OR study_pattern IS NULL
    """)).scalar()
    check("No null study_type/study_pattern in soa_queries", null_count == 0,
          f"{null_count} nulls found")

    dist = conn.execute(text("""
        SELECT study_type, study_pattern, COUNT(*) AS cnt
        FROM soa_queries
        GROUP BY study_type, study_pattern
        ORDER BY study_type
    """)).fetchall()
    total = sum(r[2] for r in dist)
    print("  Query distribution:")
    for row in dist:
        print(f"    {row[0]:<30} {row[1]:<20} {row[2]} queries")
    print(f"    Total: {total}")

# ---------------------------------------------------------------------------
# CHECK 5 — Dynamic prompt generation
# ---------------------------------------------------------------------------
print("\n[CHECK 5] Dynamic prompt generation")
try:
    from parser.prompts import build_system_prompt
    from soa_shared.models.soa_models import SoaCycleEntity
    from sqlalchemy.orm import joinedload, make_transient

    with session_factory() as session:
        ces_raw = (
            session.query(SoaCycleEntity)
            .options(joinedload(SoaCycleEntity.entity))
            .limit(4)
            .all()
        )
        # Snapshot the data we need before session closes
        cycle_entity_snapshots = [
            {
                "comparison_code": ce.comparison_code,
                "role": ce.role,
                "display_name": ce.display_name,
                "entity_name": ce.entity.name,
                "entity_aliases": ce.entity.aliases,
            }
            for ce in ces_raw
        ]

    if not cycle_entity_snapshots:
        check("Cycle entities available for prompt test", False, "no cycle entities found")
    else:
        # Build prompt manually from snapshots (mimicking build_system_prompt logic)
        from dataclasses import dataclass
        from typing import Optional, List as TList

        @dataclass
        class _FakeEntity:
            name: str
            aliases: Optional[list]

        @dataclass
        class _FakeCE:
            comparison_code: str
            role: str
            display_name: Optional[str]
            entity: _FakeEntity

        fake_ces = [
            _FakeCE(
                comparison_code=s["comparison_code"],
                role=s["role"],
                display_name=s["display_name"],
                entity=_FakeEntity(name=s["entity_name"], aliases=s["entity_aliases"]),
            )
            for s in cycle_entity_snapshots
        ]

        for pattern in ("retailer", "brand_at_retail", "brand_vs_brand"):
            prompt = build_system_prompt(cycle_entities=fake_ces, study_pattern=pattern)
            has_entities = all(ce.comparison_code in prompt for ce in fake_ces)
            has_rubric = "Primary recommendation" in prompt
            check(
                f"Prompt for '{pattern}' pattern",
                has_entities and has_rubric,
                f"entities={has_entities} rubric={has_rubric}",
            )
except Exception as exc:
    check("Dynamic prompt generation (import)", False, str(exc))

# ---------------------------------------------------------------------------
# CHECK 6 — Coded mentions FK integrity
# ---------------------------------------------------------------------------
print("\n[CHECK 6] Coded mentions FK integrity")
with engine.connect() as conn:
    null_count = conn.execute(text(
        "SELECT COUNT(*) FROM soa_coded_mentions WHERE entity_id IS NULL"
    )).scalar()
    check("soa_coded_mentions.entity_id has no nulls", null_count == 0,
          f"{null_count} nulls found")

    orphan_count = conn.execute(text("""
        SELECT COUNT(*) FROM soa_coded_mentions cm
        LEFT JOIN soa_entities e ON e.id = cm.entity_id
        WHERE e.id IS NULL AND cm.entity_id IS NOT NULL
    """)).scalar()
    check("No orphaned entity_id references", orphan_count == 0,
          f"{orphan_count} orphans found")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
if failures:
    print(f"RESULT: {len(failures)} check(s) FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    total_checks = 6
    print(f"RESULT: All checks PASSED ({total_checks} check groups)")
