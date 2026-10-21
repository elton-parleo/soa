"""
2K-1 §4: a new full-loop cycle code carries the merchant's local date.

FL12-pampers-20261020 ran on Oct 19 in Los Angeles: the code took the UTC
date. A cycle planned at 04:26 UTC on Oct 20 (21:26 PDT on Oct 19) is now
…-20261019 with the default timezone, and keeps the UTC date when the study's
tier_config.merchant.timezone says UTC. Existing codes are not renamed.
"""
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from fullloop.coordinator import Coordinator
from soa_shared import local_time
from tests.test_full_loop_coordinator import FakeSupply, db, request  # noqa: F401  (fixture)

PLANNED = datetime(2026, 10, 20, 4, 26, tzinfo=timezone.utc)


def _plan(db, tier_config=None):
    if tier_config is not None:
        with db.begin() as c:
            c.execute(text("INSERT INTO soa_query_generation_jobs (study_type, organization_id, tier_config) "
                           "VALUES ('acme', 10, :t)"), {'t': json.dumps(tier_config)})
    supply = FakeSupply('reference_done')
    co = Coordinator(engine=db, client_for=supply.client, clock=lambda: PLANNED)
    rid = request(db)
    co.tick()
    co.tick()
    row = co.get(rid)
    with db.connect() as c:
        return c.execute(text("SELECT cycle_code FROM soa_cycles WHERE id = :i"), {'i': row['cycle_id']}).scalar()


def test_04_26_utc_on_oct_20_is_oct_19_in_the_default_timezone(db, monkeypatch):
    monkeypatch.delenv(local_time.TIMEZONE_ENV, raising=False)
    assert _plan(db) == 'FL33-acme-baby-20261019'


def test_the_study_s_merchant_timezone_wins(db, monkeypatch):
    monkeypatch.delenv(local_time.TIMEZONE_ENV, raising=False)
    assert _plan(db, {'merchant': {'slug': 'acme-baby', 'timezone': 'UTC'}}) == 'FL33-acme-baby-20261020'


def test_soa_default_timezone_sets_the_default(db, monkeypatch):
    monkeypatch.setenv(local_time.TIMEZONE_ENV, 'Asia/Tokyo')
    assert _plan(db) == 'FL33-acme-baby-20261020'          # 13:26 in Tokyo


def test_the_existing_code_is_not_renamed(db, monkeypatch):
    monkeypatch.delenv(local_time.TIMEZONE_ENV, raising=False)
    _plan(db)
    with db.connect() as c:
        assert c.execute(text("SELECT cycle_code FROM soa_cycles WHERE id = 1")).scalar() == 'ACME-PRIOR'


@pytest.mark.parametrize('config, expected', [
    (None, 'America/Los_Angeles'),
    ({'merchant': {'timezone': 'Europe/Stockholm'}}, 'Europe/Stockholm'),
    ({'merchant': {'timezone': 'Not/AZone'}}, 'America/Los_Angeles'),       # an invalid zone is the default
    ('{"merchant": {"timezone": "UTC"}}', 'UTC'),                           # stored as text
])
def test_merchant_timezone(config, expected, monkeypatch):
    monkeypatch.delenv(local_time.TIMEZONE_ENV, raising=False)
    assert local_time.merchant_timezone(config) == expected


def test_local_iso_and_a_naive_stamp_is_utc():
    assert local_time.local_iso(datetime(2026, 10, 20, 4, 26), 'America/Los_Angeles') == '2026-10-19T21:26:00-07:00'
    assert local_time.local_iso('2026-10-20T04:26:00+00:00', 'America/Los_Angeles') == '2026-10-19T21:26:00-07:00'
    assert local_time.local_iso(None) is None


def test_the_generator_keeps_the_wizard_s_timezone_on_the_merchant_block():
    import os
    from unittest.mock import patch
    from clients.truesync_catalog import build_snapshot
    from generation import syndicated_study as ss

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "fixtures", "wiggle_and_snug_catalog.json")) as fh:
        payloads = json.load(fh)
    snapshot = build_snapshot(payloads["catalog"], merchants=payloads["merchants"], incentives=payloads["incentives"])
    tiers = {"category_control": {"enabled": False}, "merchant": {"timezone": "America/New_York"}}
    with patch.object(ss, "generate_and_review_study", return_value=([], {})):
        _rows, _prov, config = ss.build_syndicated_study(
            snapshot=snapshot, study_name="W&S", description="d", stage_targets={"Awareness": 1},
            allowed_categories=["Baby Care"], study_pattern="brand_at_retail", api_key="k", tier_config=tiers)
    assert config["merchant"]["timezone"] == "America/New_York" and config["merchant"]["slug"]
    assert local_time.merchant_timezone(config) == "America/New_York"
