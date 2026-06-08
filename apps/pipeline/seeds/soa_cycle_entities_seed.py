"""
Idempotent seed for soa_cycle_entities.

For each existing cycle with study_type='retailer_sephora' that has no entries
in soa_cycle_entities, creates four entries for the original Sephora comparison set.

Safe to run multiple times.

Usage:
    cd /soa && python seeds/soa_cycle_entities_seed.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from soa_shared.database import session_factory
from soa_shared.models.soa_models import SoaCycle, SoaCycleEntity, SoaEntity

RETAILER_SEPHORA_MAPPING = [
    {"comparison_code": "M001", "slug": "sephora",          "role": "primary"},
    {"comparison_code": "M002", "slug": "ulta-beauty",      "role": "competitor"},
    {"comparison_code": "M003", "slug": "nordstrom-beauty", "role": "competitor"},
    {"comparison_code": "M004", "slug": "brand-direct",     "role": "competitor"},
]


def run_seed():
    with session_factory() as session:
        # Load entity slug → id mapping
        entity_map = {
            e.slug: e.id
            for e in session.query(SoaEntity).all()
        }

        missing_slugs = [
            m["slug"] for m in RETAILER_SEPHORA_MAPPING
            if m["slug"] not in entity_map
        ]
        if missing_slugs:
            print(f"ERROR: Missing entities in soa_entities: {missing_slugs}")
            print("Run seeds/soa_entities_seed.py first.")
            return

        cycles = (
            session.query(SoaCycle)
            .filter_by(study_type="retailer_sephora")
            .all()
        )

        if not cycles:
            print("No retailer_sephora cycles found in soa_cycles.")
            return

        total_created = 0

        for cycle in cycles:
            existing_count = (
                session.query(SoaCycleEntity)
                .filter_by(cycle_id=cycle.id)
                .count()
            )
            if existing_count > 0:
                print(
                    f"  SKIPPED  {cycle.cycle_code:<25} "
                    f"({existing_count} entries already exist)"
                )
                continue

            created = 0
            for mapping in RETAILER_SEPHORA_MAPPING:
                entity_id = entity_map[mapping["slug"]]
                ce = SoaCycleEntity(
                    cycle_id=cycle.id,
                    entity_id=entity_id,
                    comparison_code=mapping["comparison_code"],
                    role=mapping["role"],
                )
                session.add(ce)
                created += 1

            print(
                f"  CREATED  {cycle.cycle_code:<25} "
                f"({created} entries created)"
            )
            total_created += created

        session.commit()
        print(f"\nCycle entity seed complete: {total_created} total entries created.")


if __name__ == "__main__":
    run_seed()
