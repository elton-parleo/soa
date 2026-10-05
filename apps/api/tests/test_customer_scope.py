"""
Step 1C: which customer a request is scoped to, and whose token it carries.

Real customer_scope, real soa_shared/customers.py, real Fernet sealing, over
HTTP against an in-memory SQLite holding two linked customer orgs (A and B)
with two different tokens, plus the staff org they are not. The upstream is
a fake that records which X-TrueSync-Key each call carried, so "the selected
org's token went upstream" is asserted, not assumed.

Users:
  op     an operator (staff org)          — may select A or B
  alice  a member of A, no operator flag  — pinned to A
  nobody a member of the staff org only   — no customer at all
"""
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import StaticPool

import clients.truesync_client as truesync_client_module
import soa_shared.config as config
import soa_shared.customers as customers
from app.app import app
from app.auth import verify_token
from app.customer_context import HEADER, CustomerScope
from soa_shared import secret_box

TOKEN_A = "tst_aaaaaaaaaaaaaaaa_" + "A" * 43
TOKEN_B = "tst_bbbbbbbbbbbbbbbb_" + "B" * 43
TOKEN_NEW = "tst_cccccccccccccccc_" + "C" * 43
FALLBACK = "tst_ffffffffffffffff_" + "F" * 43
PROVISIONING_KEY = "prov-" + "p" * 40


# ─── The database ───────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(config, "SOA_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(config, "TRUESYNC_TENANT_TOKEN", "")
    monkeypatch.setattr(config, "TRUESYNC_PROVISIONING_KEY", PROVISIONING_KEY)
    monkeypatch.setattr(config, "TRUESYNC_API_BASE", "https://supply.example")

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _now(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

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
                id INTEGER PRIMARY KEY, organization_id INTEGER NOT NULL, user_id TEXT NOT NULL,
                email TEXT NOT NULL, role TEXT DEFAULT 'member',
                is_operator BOOLEAN NOT NULL DEFAULT 0, created_at TIMESTAMP
            )
        """)
        conn.exec_driver_sql("INSERT INTO organizations (id, name) VALUES (1, 'Parleo')")
        conn.exec_driver_sql("INSERT INTO organizations (id, name) VALUES (10, 'Acme Pets')")
        conn.exec_driver_sql("INSERT INTO organizations (id, name) VALUES (20, 'Brandco')")
        customers.link_tenant(conn, 10, "acme-pets", TOKEN_A, "aaaaaaaaaaaaaaaa")
        customers.link_tenant(conn, 20, "brandco", TOKEN_B, "bbbbbbbbbbbbbbbb")
        conn.exec_driver_sql("""
            INSERT INTO organization_members (organization_id, user_id, email, is_operator)
            VALUES (1, 'op', 'op@parleo.io', 1), (10, 'alice', 'alice@acme.test', 0),
                   (1, 'nobody', 'nobody@parleo.io', 0)
        """)
    monkeypatch.setattr(customers, "engine", engine)
    import app.routers.customers as customers_router
    monkeypatch.setattr(customers_router, "engine", engine)
    return engine


# ─── The upstream ───────────────────────────────────────────────────────

class Upstream:
    """Records each call; answers by (method, path) from `routes`."""

    def __init__(self):
        self.calls = []
        self.routes = {}

    def answer(self, method, path, status=200, body=None, by_token=None):
        self.routes[(method, path)] = (status, body, by_token)

    def factory(self, **_kwargs):
        upstream = self

        class Response:
            def __init__(self, status, body):
                self.status_code = status
                self._body = body
                self.text = "" if body is None else str(body)
                self.content = b""

            def json(self):
                if self._body is None:
                    raise ValueError
                return self._body

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def request(self, method, url, params=None, json=None, headers=None, files=None):
                path = url.replace("https://supply.example", "")
                upstream.calls.append({"method": method, "path": path, "json": json,
                                       "headers": dict(headers or {})})
                status, body, by_token = upstream.routes.get((method, path), (404, None, None))
                if by_token is not None:
                    token = (headers or {}).get("X-TrueSync-Key")
                    status, body = by_token.get(token, (403, {"detail": "missing or invalid"}))
                return Response(status, body)

        return Client()

    def tokens_sent(self):
        return [c["headers"].get("X-TrueSync-Key") for c in self.calls]


@pytest.fixture
def upstream(monkeypatch):
    fake = Upstream()
    monkeypatch.setattr(truesync_client_module.httpx, "AsyncClient", fake.factory)
    return fake


def _as(user_id):
    app.dependency_overrides[verify_token] = lambda: {"sub": user_id}


@pytest.fixture
def http(db, upstream):
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(verify_token, None)


def _channels(http, org=None):
    return http.get("/api/truesync/channels", headers={HEADER: str(org)} if org else {})


# ─── Linkage and token resolution ───────────────────────────────────────

def test_the_token_is_stored_sealed_and_opens_to_itself(db):
    with db.connect() as conn:
        sealed = conn.execute(text(
            "SELECT truesync_token_sealed FROM organizations WHERE id = 10")).scalar()
    assert TOKEN_A not in sealed
    assert secret_box.open_sealed(sealed) == TOKEN_A
    assert customers.token_for_org(10) == TOKEN_A
    assert customers.token_for_org(20) == TOKEN_B


def test_an_operator_switches_and_each_selection_carries_its_own_token(http, upstream):
    _as("op")
    upstream.answer("GET", "/api/truesync/channels", body=[])

    assert _channels(http, 10).status_code == 200
    assert _channels(http, 20).status_code == 200
    assert _channels(http, 10).status_code == 200

    assert upstream.tokens_sent() == [TOKEN_A, TOKEN_B, TOKEN_A]


def test_a_non_operator_is_pinned_to_their_own_customer(http, upstream):
    _as("alice")
    upstream.answer("GET", "/api/truesync/channels", body=[])

    assert _channels(http).status_code == 200            # no header: their own
    assert _channels(http, 10).status_code == 200        # their own, named
    refused = _channels(http, 20)                         # someone else's

    assert refused.status_code == 403
    assert upstream.tokens_sent() == [TOKEN_A, TOKEN_A], "B's token was never opened or sent"
    assert TOKEN_B not in refused.text


def test_the_staff_org_is_not_a_customer(http, upstream):
    _as("op")
    assert _channels(http, 1).status_code == 403
    assert upstream.calls == []


def test_a_user_with_no_customer_gets_404_not_someone_elses(http, upstream):
    _as("nobody")
    response = _channels(http)
    assert response.status_code == 404
    assert "no customer account" in response.json()["detail"]
    assert upstream.calls == []


def test_a_malformed_selection_is_422(http):
    _as("op")
    assert _channels(http, "acme").status_code == 422


def test_a_linked_org_without_a_stored_token_uses_the_fallback_then_refuses(
    http, upstream, db, monkeypatch,
):
    with db.begin() as conn:
        customers.link_tenant(conn, 20, "brandco", None, None)
    _as("op")
    upstream.answer("GET", "/api/truesync/channels", body=[])

    monkeypatch.setattr(config, "TRUESYNC_TENANT_TOKEN", FALLBACK)
    assert _channels(http, 20).status_code == 200
    assert upstream.tokens_sent() == [FALLBACK]

    monkeypatch.setattr(config, "TRUESYNC_TENANT_TOKEN", "")
    refused = _channels(http, 20)
    assert refused.status_code == 503
    assert "Brandco" in refused.json()["detail"]
    assert "TRUESYNC_TENANT_TOKEN" in refused.json()["detail"]
    assert len(upstream.calls) == 1, "nothing was sent without a credential"


def test_a_wrong_secret_key_refuses_without_leaking(http, upstream, monkeypatch):
    _as("op")
    monkeypatch.setattr(config, "SOA_SECRET_KEY", Fernet.generate_key().decode())
    response = _channels(http, 10)
    assert response.status_code == 503
    assert "SOA_SECRET_KEY" in response.json()["detail"]
    assert upstream.calls == []


def test_the_scope_never_prints_its_token():
    scope = CustomerScope(org=customers.CustomerOrg(1, "A", "a", "x", True), token=TOKEN_A)
    assert TOKEN_A not in repr(scope)
    assert TOKEN_A not in str(scope)


# ─── GET /api/customers — the switcher's list ──────────────────────────

def _tenant(slug, merchants):
    return {"slug": slug, "display_name": slug, "soa_org_id": None, "merchants": merchants}


ACME_STORE = {"slug": "acme-store", "name": "Acme Store", "domain": "acme.test",
              "kind": "seller", "hosting": "external", "has_record": True}
BRANDCO = {"slug": "brandco", "name": "Brandco", "domain": "brandco.test",
           "kind": "brand", "hosting": "external", "has_record": False}


def test_an_operator_lists_every_customer_each_read_with_its_own_token(http, upstream):
    _as("op")
    upstream.answer("GET", "/api/truesync/tenant", by_token={
        TOKEN_A: (200, _tenant("acme-pets", [ACME_STORE])),
        TOKEN_B: (200, _tenant("brandco", [BRANDCO])),
    })

    body = http.get("/api/customers").json()

    assert body["is_operator"] is True
    assert [(c["org_id"], c["name"], [m["slug"] for m in c["merchants"]])
            for c in body["customers"]] == [
        (10, "Acme Pets", ["acme-store"]), (20, "Brandco", ["brandco"]),
    ]
    assert body["customers"][1]["merchants"][0] == BRANDCO
    assert sorted(upstream.tokens_sent()) == sorted([TOKEN_A, TOKEN_B])
    assert TOKEN_A not in str(body) and TOKEN_B not in str(body)


def test_a_non_operator_lists_one_customer(http, upstream):
    _as("alice")
    upstream.answer("GET", "/api/truesync/tenant", by_token={
        TOKEN_A: (200, _tenant("acme-pets", [ACME_STORE])),
    })
    body = http.get("/api/customers").json()
    assert body["is_operator"] is False
    assert [c["org_id"] for c in body["customers"]] == [10]
    assert upstream.tokens_sent() == [TOKEN_A]


def test_a_refused_customer_stays_listed_and_says_why(http, upstream):
    _as("op")
    upstream.answer("GET", "/api/truesync/tenant", by_token={
        TOKEN_A: (200, _tenant("acme-pets", [ACME_STORE])),
    })
    body = http.get("/api/customers").json()
    brandco = next(c for c in body["customers"] if c["org_id"] == 20)
    assert brandco["merchants"] == []
    assert brandco["error"].startswith("Not authorized for this customer")


# ─── Step 1: lookup, claim or create (Step 2A-0) ───────────────────────

NEW_MERCHANT = {"name": "Petco", "domain": "petco.com", "kind": "seller", "hosting": "external"}
PETCO_VIEW = {**NEW_MERCHANT, "slug": "petco", "has_record": False}
UNCLAIMED = {"status": "unclaimed", "domain": "petco.com", "merchant": {
    "slug": "petco", "display_name": "Petco", "domain": "petco.com",
    "scraped_deals": 3, "scraped_listings": 1, "last_seen_at": "2026-10-04T12:00:00Z"}}
LOOKUP = "/api/truesync/merchants/lookup"


def _lookup_answers(upstream, **by_token):
    upstream.answer("GET", LOOKUP, by_token={t: (200, body) for t, body in by_token.items()})


def _provisioning(upstream, action="created", reused=False):
    upstream.answer("POST", "/api/truesync/tenants", status=201, body={
        "tenant": {"slug": "petco", "display_name": "Petco", "soa_org_id": None},
        "reused": reused,
        "merchant": {"action": action, **PETCO_VIEW},
        "token_id": "cccccccccccccccc", "scope": "write", "token": TOKEN_NEW,
    })
    upstream.answer("PUT", "/api/truesync/tenant/link", by_token={TOKEN_NEW: (200, {"slug": "petco"})})
    upstream.answer("PUT", "/api/truesync/merchants/petco/retailers", by_token={
        t: (200, {"merchant": "petco", "domains": ["petco.com"]}) for t in (TOKEN_NEW, TOKEN_A)})
    upstream.answer("GET", "/api/truesync/merchants/petco/provenance", by_token={
        t: (200, {"merchant_source": "scrape", "deals": {"scrape": 3, "published": 0},
                  "listings": {"scrape": 1, "published": 0}}) for t in (TOKEN_NEW, TOKEN_A)})


def _create(http, account, claim=False, merchant=NEW_MERCHANT):
    return http.post("/api/customers", json={
        "account": account, "merchant": merchant, "retailers": ["petco.com"], "claim": claim})


@pytest.mark.parametrize("status", ["unknown", "unclaimed", "mine", "unavailable"])
def test_lookup_relays_each_status_for_an_existing_account(http, upstream, status):
    _as("op")
    body = UNCLAIMED if status == "unclaimed" else {"status": status, "domain": "petco.com"}
    _lookup_answers(upstream, **{TOKEN_A: body})

    r = http.get("/api/customers/lookup", params={"domain": "petco.com", "org_id": 10})

    assert r.status_code == 200
    assert r.json() == body
    assert upstream.tokens_sent() == [TOKEN_A], "asked as that account"


def test_lookup_for_a_new_account_never_says_mine(http, upstream):
    """A new account owns nothing: another account's "mine" is "unavailable" to it."""
    _as("op")
    _lookup_answers(upstream, **{TOKEN_A: {"status": "mine", "domain": "petco.com", "slug": "acme-store"}})
    r = http.get("/api/customers/lookup", params={"domain": "petco.com"})
    assert r.json() == {"status": "unavailable", "domain": "petco.com"}


def test_lookup_is_operator_only(http, upstream):
    _as("alice")
    assert http.get("/api/customers/lookup", params={"domain": "petco.com"}).status_code == 403
    assert upstream.calls == []


def test_only_an_operator_can_create_a_customer(http, upstream):
    _as("alice")
    assert _create(http, {"name": "Petco"}).status_code == 403
    assert upstream.calls == []


def test_a_new_account_is_provisioned_atomically_then_linked_after_commit(http, upstream, db):
    _as("op")
    _lookup_answers(upstream, **{TOKEN_A: {"status": "unknown", "domain": "petco.com"}})
    _provisioning(upstream, action="created")

    r = _create(http, {"name": "Petco"})

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created_account"] is True and body["merchant_action"] == "created"
    assert TOKEN_NEW not in r.text and PROVISIONING_KEY not in r.text
    paths = [(c["method"], c["path"]) for c in upstream.calls]
    assert paths == [
        ("GET", LOOKUP),
        ("POST", "/api/truesync/tenants"),
        ("PUT", "/api/truesync/tenant/link"),
        ("PUT", "/api/truesync/merchants/petco/retailers"),
    ]
    provision, link = upstream.calls[1], upstream.calls[2]
    assert provision["headers"] == {"X-TrueSync-Provisioning-Key": PROVISIONING_KEY}
    # The merchant rides in the same supply transaction; no org id yet.
    assert provision["json"] == {"slug": "petco", "display_name": "Petco", "merchant": {
        "domain": "petco.com", "name": "Petco", "slug": "petco", "kind": "seller", "hosting": "external"}}
    assert link["json"] == {"soa_org_id": str(body["org_id"])}
    assert link["headers"]["X-TrueSync-Key"] == TOKEN_NEW
    assert customers.token_for_org(body["org_id"]) == TOKEN_NEW


def test_an_unclaimed_domain_is_refused_until_the_operator_confirms_the_claim(http, upstream, db):
    _as("op")
    _lookup_answers(upstream, **{TOKEN_A: UNCLAIMED})
    _provisioning(upstream, action="claimed")

    refused = _create(http, {"name": "Petco"})
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "claimable"
    assert [c["path"] for c in upstream.calls] == [LOOKUP], "nothing written"
    with db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM organizations WHERE name='Petco'")).scalar() == 0

    claimed = _create(http, {"name": "Petco"}, claim=True)
    assert claimed.status_code == 201, claimed.text
    assert claimed.json()["merchant_action"] == "claimed"
    assert claimed.json()["provenance"]["deals"] == {"scrape": 3, "published": 0}


def test_an_unavailable_domain_is_refused_without_a_hint(http, upstream):
    _as("op")
    _lookup_answers(upstream, **{TOKEN_A: {"status": "unavailable", "domain": "petco.com"}})
    r = _create(http, {"org_id": 10}, claim=True)
    assert r.status_code == 409
    assert r.json()["detail"]["message"] == "petco.com is not available"
    assert [c["path"] for c in upstream.calls] == [LOOKUP]


def test_claiming_into_an_existing_account_uses_its_token(http, upstream):
    _as("op")
    _lookup_answers(upstream, **{TOKEN_A: UNCLAIMED})
    _provisioning(upstream)
    upstream.answer("POST", "/api/truesync/merchants/petco/claim", by_token={
        TOKEN_A: (200, {"claimed": True, "merchant": PETCO_VIEW, "provenance": {}})})

    r = _create(http, {"org_id": 10}, claim=True)

    assert r.status_code == 201, r.text
    assert r.json()["merchant_action"] == "claimed" and r.json()["created_account"] is False
    claim = next(c for c in upstream.calls if c["path"].endswith("/claim"))
    assert claim["json"] == {"kind": "seller", "hosting": "external", "display_name": "Petco"}
    assert "/api/truesync/tenants" not in [c["path"] for c in upstream.calls]
    assert set(upstream.tokens_sent()) == {TOKEN_A}


def test_already_the_accounts_merchant_continues(http, upstream):
    _as("op")
    _lookup_answers(upstream, **{TOKEN_A: {"status": "mine", "domain": "petco.com", "slug": "petco"}})
    _provisioning(upstream)
    upstream.answer("GET", "/api/truesync/tenant", by_token={
        TOKEN_A: (200, {"slug": "acme-pets", "merchants": [PETCO_VIEW]})})

    r = _create(http, {"org_id": 10})

    assert r.status_code == 201, r.text
    assert r.json()["merchant_action"] == "kept"
    assert not any(c["method"] == "POST" for c in upstream.calls), "nothing created or claimed"


def test_a_retry_after_a_failed_soa_commit_reuses_supplys_tenant(http, upstream, db, monkeypatch):
    """
    Supply committed the tenant; soa's own commit failed (here: sealing the
    token raises). Nothing is left on this side, supply was never told the
    org, and the retry's provisioning call — the same slug — gets the
    leftover back (`reused`) instead of "already exists".
    """
    _as("op")
    _lookup_answers(upstream, **{TOKEN_A: {"status": "unknown", "domain": "petco.com"}})
    _provisioning(upstream)
    real_link = customers.link_tenant
    calls = {"n": 0}

    def flaky_link(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database went away")
        return real_link(*args, **kwargs)

    monkeypatch.setattr(customers, "link_tenant", flaky_link)

    with pytest.raises(RuntimeError):
        _create(http, {"name": "Petco"})
    with db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM organizations WHERE name='Petco'")).scalar() == 0
    assert "/api/truesync/tenant/link" not in [c["path"] for c in upstream.calls], \
        "supply never learned an org that does not exist"

    _provisioning(upstream, reused=True)
    retry = _create(http, {"name": "Petco"})

    assert retry.status_code == 201, retry.text
    provisions = [c for c in upstream.calls if c["path"] == "/api/truesync/tenants"]
    assert len(provisions) == 2 and provisions[0]["json"] == provisions[1]["json"]
    link = next(c for c in upstream.calls if c["path"] == "/api/truesync/tenant/link")
    assert link["json"] == {"soa_org_id": str(retry.json()["org_id"])}
    with db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM organizations WHERE name='Petco'")).scalar() == 1


def test_a_refused_provisioning_writes_no_org(http, upstream, db):
    _as("op")
    _lookup_answers(upstream, **{TOKEN_A: {"status": "unknown", "domain": "petco.com"}})
    upstream.answer("POST", "/api/truesync/tenants", status=409,
                    body={"detail": "tenant 'petco' already exists"})

    assert _create(http, {"name": "Petco"}).status_code == 409
    with db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM organizations WHERE name='Petco'")).scalar() == 0


def test_account_must_be_existing_or_new_not_both(http, upstream):
    _as("op")
    r = http.post("/api/customers", json={
        "account": {"org_id": 10, "name": "Petco"}, "merchant": NEW_MERCHANT})
    assert r.status_code == 422
    assert upstream.calls == []
