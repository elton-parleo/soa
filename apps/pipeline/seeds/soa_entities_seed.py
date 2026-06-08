"""
Idempotent seed for soa_entities.

Seeds the four original Sephora retailer entities. Safe to run multiple times.

Usage:
    cd /soa && python seeds/soa_entities_seed.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from soa_shared.database import session_factory
from soa_shared.models.soa_models import SoaEntity
from soa_shared.models.merchant_ref import Merchant

ENTITIES = [
    {
        "name": "Sephora",
        "slug": "sephora",
        "entity_type": "retailer",
        "category": "beauty",
        "website_url": "https://www.sephora.com",
        "aliases": ["Sephora.com"],
        "merchant_slug": "sephora",
    },
    {
        "name": "Ulta Beauty",
        "slug": "ulta-beauty",
        "entity_type": "retailer",
        "category": "beauty",
        "website_url": "https://www.ulta.com",
        "aliases": ["Ulta", "Ulta.com"],
        "merchant_slug": "ulta-beauty",
    },
    {
        "name": "Nordstrom Beauty",
        "slug": "nordstrom-beauty",
        "entity_type": "retailer",
        "category": "beauty",
        "website_url": "https://www.nordstrom.com/browse/beauty",
        "aliases": ["Nordstrom"],
        "merchant_slug": "nordstrom",  # merchant slug is 'nordstrom', entity slug is 'nordstrom-beauty'
    },
    {
        "name": "Brand Direct (Aggregate)",
        "slug": "brand-direct",
        "entity_type": "aggregate",
        "category": "beauty",
        "website_url": None,
        "aliases": [
            "brand's own website",
            "brand website",
            "official website",
        ],
        "merchant_slug": "brand-direct",
    },
]


def run_seed():
    inserted = updated = skipped = 0

    with session_factory() as session:
        for data in ENTITIES:
            merchant_slug = data.pop("merchant_slug")

            # Look up merchant_id (nullable — don't fail if not found)
            merchant = (
                session.query(Merchant)
                .filter_by(slug=merchant_slug)
                .first()
            )
            merchant_id = merchant.id if merchant else None

            existing = session.query(SoaEntity).filter_by(slug=data["slug"]).first()

            if existing is None:
                entity = SoaEntity(**data, merchant_id=merchant_id)
                session.add(entity)
                print(f"  INSERTED  {data['slug']:<30} merchant_linked={merchant_id is not None}")
                inserted += 1
            else:
                changed = False
                for k, v in data.items():
                    if getattr(existing, k) != v:
                        setattr(existing, k, v)
                        changed = True
                if existing.merchant_id != merchant_id:
                    existing.merchant_id = merchant_id
                    changed = True

                if changed:
                    print(f"  UPDATED   {data['slug']:<30} merchant_linked={merchant_id is not None}")
                    updated += 1
                else:
                    print(f"  SKIPPED   {data['slug']:<30} (no changes)")
                    skipped += 1

        session.commit()

    print(f"\nEntity seed complete: {inserted} inserted, {updated} updated, {skipped} skipped.")


if __name__ == "__main__":
    run_seed()
