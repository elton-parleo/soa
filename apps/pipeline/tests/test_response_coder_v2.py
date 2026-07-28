"""
Tests for parser/response_coder_v2.py's idempotency sentinel
(soa_pass2_coding_log) — a run that legitimately produces zero
observations and zero citations must still be recognized as
"already processed" on a second call, without re-invoking the coder.

Real in-memory SQLite, matching the convention in
tests/test_truecost_snapshots_endpoint.py and
apps/pipeline/tests/test_scope_resolution.py. A fake CodingClientV2
stands in for the real OpenAI-backed one.
"""
import asyncio
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from parser.coding_response_v2 import Pass2CodingResult
from parser.response_coder_v2 import ResponseCoderV2
from soa_shared.models.soa_models import SoaCodedMention, SoaCycle, SoaCycleEntity, SoaEntity, SoaRun


class FakeCodingClientV2:
    def __init__(self, result: Pass2CodingResult):
        self.result = result
        self.call_count = 0

    async def code_observations(self, run, mentioned_entities):
        self.call_count += 1
        return self.result


@pytest.fixture
def Session():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, cycle_code TEXT UNIQUE, start_date DATE,
                end_date DATE, total_runs_planned INTEGER, completed_runs INTEGER,
                status TEXT, notes TEXT, platforms TEXT, runs_per_query INTEGER,
                study_type TEXT, study_pattern TEXT,
                scope_frozen_at TIMESTAMP, scope_is_custom BOOLEAN,
                organization_id INTEGER, created_by TEXT,
                cycle_mode TEXT DEFAULT 'query', truecost_tiers TEXT,
                created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_entities (
                id INTEGER PRIMARY KEY, name TEXT, slug TEXT, entity_type TEXT,
                category TEXT, merchant_id INTEGER, website_url TEXT, aliases TEXT,
                created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_cycle_entities (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, entity_id INTEGER,
                comparison_code TEXT, role TEXT, display_name TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, query_id INTEGER,
                platform TEXT, run_number INTEGER, run_at TIMESTAMP,
                raw_response TEXT, response_tokens INTEGER, latency_ms INTEGER,
                status TEXT, error_message TEXT, search_triggered BOOLEAN,
                retrieved_sources TEXT, created_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_coded_mentions (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                merchant_id INTEGER, mentioned BOOLEAN, position INTEGER,
                strength TEXT, deal_cited BOOLEAN, deal_types TEXT,
                member_value_cited BOOLEAN, evidence TEXT,
                coded_by TEXT, confidence FLOAT, needs_review BOOLEAN,
                reviewed_by TEXT, reviewed_at TIMESTAMP,
                created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_price_observations (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                stated_price FLOAT, claimed_net_price FLOAT, claimed_discount_value FLOAT,
                claimed_discount_pct FLOAT, claimed_terms TEXT, member_price_claimed BOOLEAN,
                subscription_offer_claimed BOOLEAN, merchant_name TEXT, merchant_slug TEXT,
                attribution_status TEXT, evidence TEXT, coding_pass_version INTEGER,
                created_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_citations (
                id INTEGER PRIMARY KEY, run_id INTEGER, url TEXT, domain TEXT,
                context TEXT, coding_pass_version INTEGER, created_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_pass2_coding_log (
                id INTEGER PRIMARY KEY, run_id INTEGER, coding_pass_version INTEGER,
                observations_written INTEGER, citations_written INTEGER, created_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE merchants (
                id INTEGER PRIMARY KEY, name TEXT, slug TEXT, url TEXT,
                created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """)
    return sessionmaker(bind=engine)


@pytest.fixture
def patched_session_factory(Session, monkeypatch):
    import parser.response_coder_v2 as response_coder_v2
    monkeypatch.setattr(response_coder_v2, "session_factory", Session)
    return Session


def _seed_run_with_no_mentions(Session, run_id=1, cycle_id=1):
    with Session() as session:
        session.add(SoaCycle(
            id=cycle_id, cycle_code="TC001", start_date=datetime.date(2026, 6, 1),
            status="complete", organization_id=1, study_type="brand_x", study_pattern="mixed",
            scope_is_custom=False, cycle_mode="query",
        ))
        session.add(SoaEntity(id=1, name="Pampers", slug="pampers", entity_type="brand"))
        session.add(SoaCycleEntity(cycle_id=cycle_id, entity_id=1, comparison_code="M001", role="primary"))
        session.add(SoaRun(
            id=run_id, cycle_id=cycle_id, query_id=1, platform="chatgpt", run_number=1,
            raw_response="A pure ingredient comparison with no prices or entity mentions.",
            status="success",
        ))
        # Pass 1 found nothing mentioned — a legitimate, common case.
        session.add(SoaCodedMention(
            run_id=run_id, entity_id=1, mentioned=False, coded_by="llm_auto",
        ))
        session.commit()


def test_zero_result_run_is_marked_processed_and_not_recoded(patched_session_factory):
    Session = patched_session_factory
    _seed_run_with_no_mentions(Session)

    empty_result = Pass2CodingResult(run_id=1, price_observations=[], citations=[], coding_latency_ms=10)
    client = FakeCodingClientV2(empty_result)
    coder = ResponseCoderV2(client)

    first = asyncio.run(coder.code_run(1))
    assert first.status == "success"
    assert client.call_count == 1

    second = asyncio.run(coder.code_run(1))
    assert second.status == "skipped — already pass-2 coded"
    assert client.call_count == 1  # not re-invoked
