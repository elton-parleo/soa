"""
Step 1C in the pipeline: a study's catalog is read with ITS customer's token,
and a refusal fails the cycle instead of scoring without the catalog.

In-memory SQLite with two linked customer orgs holding different sealed
tokens, and generation jobs pointing at each. Nothing reaches the network:
httpx.get is replaced by a recorder.
"""
import argparse
import asyncio
import datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import clients.truesync_catalog as tc
import soa_shared.config as config
import soa_shared.customers as customers

TOKEN_A = "tst_aaaaaaaaaaaaaaaa_" + "A" * 43
TOKEN_B = "tst_bbbbbbbbbbbbbbbb_" + "B" * 43
FALLBACK = "tst_ffffffffffffffff_" + "F" * 43


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(config, "SOA_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(config, "TRUESYNC_TENANT_TOKEN", "")
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE organizations (
                id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, created_at TIMESTAMP,
                truesync_tenant_slug TEXT UNIQUE, truesync_token_sealed TEXT,
                truesync_token_id TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE organization_members (
                id INTEGER PRIMARY KEY, organization_id INTEGER, user_id TEXT, email TEXT,
                role TEXT DEFAULT 'member', is_operator BOOLEAN NOT NULL DEFAULT 0
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE soa_query_generation_jobs (
                id INTEGER PRIMARY KEY, study_type TEXT UNIQUE, study_name TEXT,
                target_count INTEGER, organization_id INTEGER,
                syndicated_merchant TEXT, customer_organization_id INTEGER
            )
        """)
        conn.exec_driver_sql("INSERT INTO organizations (id, name) VALUES (1, 'Parleo')")
        conn.exec_driver_sql("INSERT INTO organizations (id, name) VALUES (10, 'Acme Pets')")
        conn.exec_driver_sql("INSERT INTO organizations (id, name) VALUES (20, 'Brandco')")
        customers.link_tenant(conn, 10, "acme-pets", TOKEN_A, "aaaaaaaaaaaaaaaa")
        customers.link_tenant(conn, 20, "brandco", TOKEN_B, "bbbbbbbbbbbbbbbb")
        conn.exec_driver_sql("""
            INSERT INTO soa_query_generation_jobs
              (study_type, study_name, target_count, organization_id,
               syndicated_merchant, customer_organization_id)
            VALUES ('acme-study', 'A', 1, 1, 'acme-store', 10),
                   ('brandco-study', 'B', 1, 1, 'brandco', 20),
                   ('legacy-study', 'L', 1, 1, 'wiggle-and-snug', NULL)
        """)
    monkeypatch.setattr(customers, "engine", engine)
    return engine


class _Response:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


@pytest.fixture
def sent(monkeypatch):
    """Every X-TrueSync-Key a catalog read carried; answers 200 empty."""
    seen = []

    def get(url, params=None, timeout=None, headers=None):
        seen.append((headers or {}).get("X-TrueSync-Key"))
        return _Response(200, [] if url.endswith("/merchants") else {"listings": []})

    monkeypatch.setattr(tc.httpx, "get", get)
    return seen


# ─── Token per study ────────────────────────────────────────────────────

def test_each_study_is_read_with_its_own_customers_token(db, sent):
    tc.TrueSyncCatalogClient.for_study("acme-study", base_url="https://x.invalid") \
        .snapshot("acme-store", with_history=False)
    tc.TrueSyncCatalogClient.for_study("brandco-study", base_url="https://x.invalid") \
        .snapshot("brandco", with_history=False)

    assert set(sent[:3]) == {TOKEN_A} and set(sent[3:]) == {TOKEN_B}


def test_a_pre_1c_study_uses_the_fallback_while_it_exists(db, sent, monkeypatch):
    monkeypatch.setattr(config, "TRUESYNC_TENANT_TOKEN", FALLBACK)
    client = tc.TrueSyncCatalogClient.for_study("legacy-study")
    assert client.token == FALLBACK
    assert "TRUESYNC_TENANT_TOKEN" in client.token_source


def test_with_no_org_and_no_fallback_nothing_is_read(db, sent):
    with pytest.raises(tc.TrueSyncNotAuthorized) as exc:
        tc.TrueSyncCatalogClient.for_study("legacy-study")
    assert "legacy-study" in str(exc.value)
    assert "TRUESYNC_TENANT_TOKEN" in str(exc.value)
    assert sent == []


def test_a_refusal_names_the_customer_whose_token_it_was(db, monkeypatch):
    monkeypatch.setattr(tc.httpx, "get", lambda *a, **k: _Response(403, {"detail": "no"}))
    client = tc.TrueSyncCatalogClient.for_study("acme-study", base_url="https://x.invalid")

    with pytest.raises(tc.TrueSyncNotAuthorized) as exc:
        client.snapshot("acme-store", with_history=True)

    message = str(exc.value)
    assert "Acme Pets (org 10)" in message
    assert TOKEN_A not in message


def test_an_unopenable_token_is_a_refusal_naming_the_key(db, monkeypatch):
    monkeypatch.setattr(config, "SOA_SECRET_KEY", Fernet.generate_key().decode())
    with pytest.raises(tc.TrueSyncNotAuthorized, match="SOA_SECRET_KEY"):
        tc.TrueSyncCatalogClient.for_study("acme-study")


# ─── Scoring fails on a refusal ─────────────────────────────────────────

def test_the_batch_stops_and_raises_on_a_refusal():
    from scoring import expectation_batch

    started = []

    class Scorer:
        async def score_run(self, run_id):
            started.append(run_id)
            if run_id == 1:
                raise tc.TrueSyncNotAuthorized("Not authorized for this customer: refused")
            await asyncio.sleep(10)   # would still be running; must be cancelled

    with pytest.raises(tc.TrueSyncNotAuthorized):
        asyncio.run(asyncio.wait_for(
            expectation_batch.score_runs([1, 2, 3], concurrency=3, scorer=Scorer()),
            timeout=5,
        ))


def _orchestrator():
    from orchestrator.pipeline import PipelineOrchestrator

    orch = PipelineOrchestrator.__new__(PipelineOrchestrator)
    orch.cycle = type("Cycle", (), {"id": 5})()
    orch.cycle_code = "c-5"
    orch.notes = []
    orch._append_cycle_note = orch.notes.append
    return orch


def test_a_refusal_fails_stage_2c_with_the_reason_on_the_cycle(monkeypatch):
    from orchestrator.pipeline import PipelineStageError
    import scoring.expectation_batch as batch

    async def refused(*_a, **_k):
        raise tc.TrueSyncNotAuthorized(
            "Not authorized for this customer: TrueSync refused the token stored for "
            "Acme Pets (org 10)"
        )

    monkeypatch.setattr(batch, "score_cycle", refused)
    orch = _orchestrator()

    with pytest.raises(PipelineStageError) as exc:
        asyncio.run(orch._run_expectation_scoring())

    assert exc.value.stage == "expectation_scoring"
    assert "Acme Pets (org 10)" in exc.value.reason
    assert orch.notes and "Acme Pets (org 10)" in orch.notes[0]


def test_any_other_scoring_bug_still_never_fails_the_cycle(monkeypatch):
    import scoring.expectation_batch as batch

    async def broken(*_a, **_k):
        raise RuntimeError("a bug")

    monkeypatch.setattr(batch, "score_cycle", broken)
    orch = _orchestrator()
    asyncio.run(orch._run_expectation_scoring())   # no raise
    assert orch.notes == []


def test_the_coding_stage_turns_it_into_a_failed_cycle(monkeypatch):
    """End to end through run_pipeline's stage handling: status 'failed'."""
    from orchestrator import pipeline as pipeline_module
    from orchestrator.pipeline import PipelineOrchestrator, PipelineStageError

    orch = _orchestrator()
    orch.dry_run = False
    statuses = []
    orch._update_cycle_status = statuses.append
    orch._preflight_check = lambda: None

    async def runner():
        return None

    async def coding():
        raise PipelineStageError(stage="expectation_scoring", reason="refused for Acme Pets")

    orch._run_stage_runner = runner
    orch._run_stage_coding = coding
    orch._estimate_costs = lambda *a: (None, None)

    report = asyncio.run(PipelineOrchestrator.run_pipeline(orch))

    assert statuses[-1] == "failed"
    assert report.pipeline_status == "failed"
    assert report.failure_stage == "expectation_scoring"


# ─── The backfill ───────────────────────────────────────────────────────

def test_the_backfill_links_seals_marks_and_stamps_idempotently(db, monkeypatch, capsys):
    from scripts import backfill_customer_accounts as backfill

    with db.begin() as conn:
        conn.execute(text("UPDATE organizations SET truesync_tenant_slug = NULL, "
                          "truesync_token_sealed = NULL WHERE id = 10"))
        conn.exec_driver_sql(
            "INSERT INTO organization_members (organization_id, user_id, email) "
            "VALUES (1, 'u-elton', 'Elton@parleo.io'), (1, 'u-x', 'x@parleo.io')"
        )
    monkeypatch.setenv("TRUESYNC_TENANT_TOKEN", FALLBACK)
    args = argparse.Namespace(
        org_name="Wiggle & Snug", tenant_slug="wiggle-and-snug",
        token_env="TRUESYNC_TENANT_TOKEN", operator_email=["elton@parleo.io", "gone@parleo.io"],
        merchant=["wiggle-and-snug"], no_verify=True,
    )

    with db.begin() as conn:
        first = backfill.run(args, conn=conn)
    with db.begin() as conn:
        second = backfill.run(args, conn=conn)

    assert first["org"].startswith("created") and second["org"].startswith("found")
    assert "1 generation job(s) stamped" in first["studies"]
    assert "0 generation job(s) stamped" in second["studies"]
    assert "gone@parleo.io" in first["operators"]
    with db.connect() as conn:
        org_id, sealed = conn.execute(text(
            "SELECT id, truesync_token_sealed FROM organizations WHERE name = 'Wiggle & Snug'"
        )).fetchone()
        operators = conn.execute(text(
            "SELECT email FROM organization_members WHERE is_operator")).scalars().all()
        stamped = conn.execute(text(
            "SELECT customer_organization_id FROM soa_query_generation_jobs "
            "WHERE study_type = 'legacy-study'")).scalar()
    assert FALLBACK not in sealed
    assert customers.token_for_org(org_id) == FALLBACK
    assert operators == ["Elton@parleo.io"]
    assert stamped == org_id
    assert FALLBACK not in str(first) + str(second) + capsys.readouterr().out


def test_the_backfill_refuses_a_token_from_another_tenant(db, monkeypatch):
    from scripts import backfill_customer_accounts as backfill

    monkeypatch.setenv("TRUESYNC_TENANT_TOKEN", FALLBACK)
    args = argparse.Namespace(
        org_name="Wiggle & Snug", tenant_slug="wiggle-and-snug",
        token_env="TRUESYNC_TENANT_TOKEN", operator_email=None, merchant=None, no_verify=False,
    )
    with db.begin() as conn, pytest.raises(SystemExit, match="belongs to tenant 'acme-pets'"):
        backfill.run(args, conn=conn, tenant_view={"slug": "acme-pets", "merchants": []})


def test_the_backfill_is_refused_against_a_remote_database(monkeypatch):
    from migration_target import RemoteDatabaseError
    from scripts import backfill_customer_accounts as backfill

    monkeypatch.setenv("ALEMBIC_DATABASE_URL", "postgresql://u:p@db.example.com:5432/postgres")
    monkeypatch.delenv("SOA_ALLOW_REMOTE_MIGRATION", raising=False)
    with pytest.raises(RemoteDatabaseError):
        backfill.main(["--no-verify"])
