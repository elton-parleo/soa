"""
Tests for Part 1 (P1/P2)'s lite-gated pass-2 wiring —
orchestrator/pipeline.py::PipelineOrchestrator._run_pass2_recode, the
live-pipeline hook that calls the exact same parser/pass2_recode_batch.py
::recode_runs the ops backfill script (scripts/recode_cycle_pass2.py, now
a thin re-export) uses.

_run_pass2_recode only ever reads self.cycle.id/self.cycle_code and
writes self._pass2_observations_written, so it's exercised directly
against a bare PipelineOrchestrator instance (object.__new__, bypassing
__init__ entirely — no CodingClient/OpenAI key needed to construct one).

Real in-memory SQLite, same schema as test_response_coder_v2.py (the
tables parser/response_coder_v2.py touches). A fake CodingClientV2
stands in for the real OpenAI-backed one, injected by monkeypatching
parser.pass2_recode_batch.CodingClientV2 (recode_runs' own import).
"""
import asyncio
import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import orchestrator.pipeline as pipeline_module
import parser.pass2_recode_batch as pass2_recode_batch
import parser.response_coder_v2 as response_coder_v2
from orchestrator.pipeline import PipelineOrchestrator
from parser.coding_response_v2 import Pass2CodingResult, PriceObservationCoding
from soa_shared.models.soa_models import SoaCodedMention, SoaCycle, SoaCycleEntity, SoaEntity, SoaRun


class FakeCodingClientV2:
    def __init__(self, result_by_run_id=None, default_result=None, raise_for_run_ids=None):
        self.result_by_run_id = result_by_run_id or {}
        self.default_result = default_result
        self.raise_for_run_ids = raise_for_run_ids or set()
        self.calls = []

    async def code_observations(self, run, mentioned_entities):
        self.calls.append(run.id)
        if run.id in self.raise_for_run_ids:
            raise RuntimeError("simulated pass-2 API failure")
        return self.result_by_run_id.get(
            run.id,
            self.default_result or Pass2CodingResult(run_id=run.id, price_observations=[], citations=[], coding_latency_ms=5),
        )


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
def patched(Session, monkeypatch):
    monkeypatch.setattr(response_coder_v2, "session_factory", Session)
    monkeypatch.setattr(pipeline_module, "session_factory", Session)
    return Session


def _seed_cycle(Session, run_specs, cycle_id=1, cycle_code="lite-abc12345"):
    """run_specs: list of (run_id, raw_response, mentioned)."""
    with Session() as session:
        session.add(SoaCycle(
            id=cycle_id, cycle_code=cycle_code, start_date=datetime.date(2026, 6, 1),
            status="running", organization_id=1, study_type=cycle_code, study_pattern="brand_vs_brand",
            scope_is_custom=False, cycle_mode="query",
        ))
        session.add(SoaEntity(id=1, name="Acme", slug="acme", entity_type="brand"))
        session.add(SoaCycleEntity(cycle_id=cycle_id, entity_id=1, comparison_code="M001", role="primary"))
        for run_id, raw_response, mentioned in run_specs:
            session.add(SoaRun(
                id=run_id, cycle_id=cycle_id, query_id=run_id, platform="chatgpt",
                run_number=1, raw_response=raw_response, status="success",
            ))
            session.add(SoaCodedMention(run_id=run_id, entity_id=1, mentioned=mentioned, coded_by="llm_auto"))
        session.commit()


def _bare_orchestrator(cycle_id=1, cycle_code="lite-abc12345"):
    orch = object.__new__(PipelineOrchestrator)
    orch.cycle_code = cycle_code
    orch.cycle = SimpleNamespace(id=cycle_id)
    orch._pass2_observations_written = 0
    return orch


def test_pass2_writes_observations_and_sentinel_for_a_price_quoting_run(patched, monkeypatch):
    Session = patched
    _seed_cycle(Session, [(1, "Acme is $80 at Target.", True)])

    result = Pass2CodingResult(
        run_id=1,
        price_observations=[PriceObservationCoding(comparison_code="M001", stated_price=80.0, merchant_name="Target")],
        citations=[],
        coding_latency_ms=5,
    )
    fake_client = FakeCodingClientV2(result_by_run_id={1: result})
    monkeypatch.setattr(pass2_recode_batch, "CodingClientV2", lambda: fake_client)

    orch = _bare_orchestrator()
    asyncio.run(orch._run_pass2_recode())

    assert orch._pass2_observations_written == 1
    with Session() as session:
        obs = session.query(response_coder_v2.SoaPriceObservation).filter_by(run_id=1).all()
        assert len(obs) == 1
        assert obs[0].entity_id == 1
        assert obs[0].stated_price == 80.0
        sentinel = session.query(response_coder_v2.SoaPass2CodingLog).filter_by(run_id=1).first()
        assert sentinel is not None
        assert sentinel.coding_pass_version == 2


def test_reprocessing_a_sentineled_run_writes_nothing_new_and_skips_the_api_call(patched, monkeypatch):
    Session = patched
    _seed_cycle(Session, [(1, "Acme is $80 at Target.", True)])

    result = Pass2CodingResult(
        run_id=1,
        price_observations=[PriceObservationCoding(comparison_code="M001", stated_price=80.0, merchant_name="Target")],
        citations=[],
        coding_latency_ms=5,
    )
    fake_client = FakeCodingClientV2(result_by_run_id={1: result})
    monkeypatch.setattr(pass2_recode_batch, "CodingClientV2", lambda: fake_client)

    orch = _bare_orchestrator()
    asyncio.run(orch._run_pass2_recode())
    assert fake_client.calls == [1]

    orch2 = _bare_orchestrator()
    asyncio.run(orch2._run_pass2_recode())

    assert fake_client.calls == [1]  # never called again
    with Session() as session:
        assert session.query(response_coder_v2.SoaPriceObservation).filter_by(run_id=1).count() == 1
        assert session.query(response_coder_v2.SoaPass2CodingLog).filter_by(run_id=1).count() == 1


def test_one_response_failure_never_fails_the_run_and_leaves_no_sentinel_for_it(patched, monkeypatch):
    Session = patched
    _seed_cycle(Session, [
        (1, "Acme is $80 at Target.", True),
        (2, "Acme is a great brand.", True),
    ])

    result_ok = Pass2CodingResult(
        run_id=2,
        price_observations=[PriceObservationCoding(comparison_code="M001", stated_price=None, merchant_name=None)],
        citations=[],
        coding_latency_ms=5,
    )
    fake_client = FakeCodingClientV2(result_by_run_id={2: result_ok}, raise_for_run_ids={1})
    monkeypatch.setattr(pass2_recode_batch, "CodingClientV2", lambda: fake_client)

    orch = _bare_orchestrator()
    asyncio.run(orch._run_pass2_recode())  # must not raise

    with Session() as session:
        sentineled = {r.run_id for r in session.query(response_coder_v2.SoaPass2CodingLog).all()}
    assert sentineled == {2}  # run 1's failure left no sentinel; run 2 still succeeded


def test_unexpected_error_in_recode_never_propagates(patched, monkeypatch):
    """Even a total blow-up (e.g. the DB query for run_ids itself failing)
    must never raise out of _run_pass2_recode — pass-2 is enrichment,
    never on the critical path to Stage 2 completing."""
    Session = patched
    _seed_cycle(Session, [(1, "Acme is $80 at Target.", True)])

    def _broken_session_factory():
        raise RuntimeError("db unreachable")
    monkeypatch.setattr(pipeline_module, "session_factory", _broken_session_factory)

    orch = _bare_orchestrator()
    asyncio.run(orch._run_pass2_recode())  # must not raise
    assert orch._pass2_observations_written == 0


def test_no_coded_runs_is_a_clean_noop(patched, monkeypatch):
    Session = patched
    _seed_cycle(Session, [])  # cycle exists, nothing coded yet

    fake_client = FakeCodingClientV2()
    monkeypatch.setattr(pass2_recode_batch, "CodingClientV2", lambda: fake_client)

    orch = _bare_orchestrator()
    asyncio.run(orch._run_pass2_recode())

    assert fake_client.calls == []
    assert orch._pass2_observations_written == 0


def test_pass2_recodes_every_pass1_coded_run_not_just_freshly_coded_ones(patched, monkeypatch):
    """A resumed cycle: run 1 was pass-1-coded in a PRIOR invocation
    (this call never re-codes it via pass 1), run 2 is freshly coded
    this call. Both must get pass-2, since _run_pass2_recode reads ALL
    of the cycle's soa_coded_mentions, not a per-call 'just coded' set."""
    Session = patched
    _seed_cycle(Session, [
        (1, "Acme is $80 at Target.", True),
        (2, "Acme is $50 direct.", True),
    ])

    result1 = Pass2CodingResult(run_id=1, price_observations=[PriceObservationCoding(comparison_code="M001", stated_price=80.0)], citations=[], coding_latency_ms=5)
    result2 = Pass2CodingResult(run_id=2, price_observations=[PriceObservationCoding(comparison_code="M001", stated_price=50.0)], citations=[], coding_latency_ms=5)
    fake_client = FakeCodingClientV2(result_by_run_id={1: result1, 2: result2})
    monkeypatch.setattr(pass2_recode_batch, "CodingClientV2", lambda: fake_client)

    orch = _bare_orchestrator()
    asyncio.run(orch._run_pass2_recode())

    assert set(fake_client.calls) == {1, 2}
    assert orch._pass2_observations_written == 2
