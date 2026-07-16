"""
Idempotent seed for soa_playbook.

Upserts the 22 plays transcribed from docs/playbook_v1.md (playbook_v1.json,
same directory). Safe to run multiple times — matches by play_id.

Usage:
    cd apps/pipeline && python seeds/soa_playbook_seed.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from soa_shared.database import session_factory
from soa_shared.models.soa_models import SoaPlaybook

PLAYBOOK_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playbook_v1.json")


def seed_playbook():
    with open(PLAYBOOK_JSON) as f:
        plays = json.load(f)

    session = session_factory()
    try:
        for play in plays:
            existing = session.get(SoaPlaybook, play["play_id"])
            if existing:
                for key, value in play.items():
                    setattr(existing, key, value)
            else:
                session.add(SoaPlaybook(**play))
        session.commit()
        print(f"Seeded {len(plays)} plays.")
    finally:
        session.close()


if __name__ == "__main__":
    seed_playbook()
