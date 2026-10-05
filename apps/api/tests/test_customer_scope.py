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


# ─── POST /api/customers — the wizard's step 1 ─────────────────────────

NEW_MERCHANT = {"name": "Petco", "domain": "petco.com", "kind": "seller", "hosting": "external"}


def _provisioned(upstream):
    upstream.answer("POST", "/api/truesync/tenants", status=201, body={
        "tenant": {"slug": "petco", "display_name": "Petco", "soa_org_id": "?"},
        "token_id": "cccccccccccccccc", "scope": "write", "token": TOKEN_NEW,
    })
    upstream.answer("POST", "/api/truesync/tenant/merchants", by_token={
        TOKEN_NEW: (201, {**NEW_MERCHANT, "slug": "petco", "has_record": False}),
        TOKEN_A: (201, {**NEW_MERCHANT, "slug": "petco", "has_record": False}),
    })
    upstream.answer("PUT", "/api/truesync/merchants/petco/retailers", by_token={
        TOKEN_NEW: (200, {"merchant": "petco", "own_domain": "petco.com", "domains": ["petco.com"]}),
        TOKEN_A: (200, {"merchant": "petco", "own_domain": "petco.com", "domains": ["petco.com"]}),
    })


def test_only_an_operator_can_create_a_customer(http, upstream):
    _as("alice")
    response = http.post("/api/customers", json={
        "account": {"name": "Petco"}, "merchant": NEW_MERCHANT, "retailers": []})
    assert response.status_code == 403
    assert upstream.calls == []


def test_a_new_account_is_provisioned_linked_and_sealed_in_one_go(http, upstream, db):
    _as("op")
    _provisioned(upstream)

    response = http.post("/api/customers", json={
        "account": {"name": "Petco"}, "merchant": NEW_MERCHANT, "retailers": ["petco.com"]})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created_account"] is True and body["tenant_slug"] == "petco"
    assert body["merchant"]["slug"] == "petco"
    assert TOKEN_NEW not in response.text and PROVISIONING_KEY not in response.text

    # The calls, in order, each with the right credential.
    provision, merchant, retailers = upstream.calls
    assert provision["path"] == "/api/truesync/tenants"
    assert provision["headers"] == {"X-TrueSync-Provisioning-Key": PROVISIONING_KEY}
    assert provision["json"] == {"slug": "petco", "display_name": "Petco",
                                 "soa_org_id": str(body["org_id"])}
    assert merchant["headers"]["X-TrueSync-Key"] == TOKEN_NEW
    assert merchant["json"] == {"slug": "petco", **{k: NEW_MERCHANT[k] for k in NEW_MERCHANT}}
    assert retailers["json"] == {"domains": ["petco.com"]}

    # Stored sealed, and the operator can now select it.
    with db.connect() as conn:
        row = conn.execute(text(
            "SELECT truesync_tenant_slug, truesync_token_sealed, truesync_token_id "
            "FROM organizations WHERE id = :id"), {"id": body["org_id"]}).fetchone()
    assert row[0] == "petco" and row[2] == "cccccccccccccccc"
    assert TOKEN_NEW not in row[1]
    assert customers.token_for_org(body["org_id"]) == TOKEN_NEW
    assert body["org_id"] in [o.id for o in customers.selectable_orgs("op")]


def test_a_refused_provisioning_writes_no_org(http, upstream, db):
    _as("op")
    upstream.answer("POST", "/api/truesync/tenants", status=409,
                    body={"detail": "tenant 'petco' already exists"})

    response = http.post("/api/customers", json={
        "account": {"name": "Petco"}, "merchant": NEW_MERCHANT, "retailers": []})

    assert response.status_code == 409
    with db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM organizations WHERE name='Petco'")).scalar() == 0


def test_adding_to_an_existing_account_uses_its_token_and_provisions_nothing(http, upstream):
    _as("op")
    _provisioned(upstream)

    response = http.post("/api/customers", json={
        "account": {"org_id": 10}, "merchant": NEW_MERCHANT, "retailers": ["petco.com"]})

    assert response.status_code == 201, response.text
    assert response.json()["created_account"] is False
    assert [c["path"] for c in upstream.calls] == [
        "/api/truesync/tenant/merchants", "/api/truesync/merchants/petco/retailers"]
    assert upstream.tokens_sent() == [TOKEN_A, TOKEN_A]


def test_a_merchant_refused_after_a_new_account_says_which_account_exists(http, upstream):
    _as("op")
    upstream.answer("POST", "/api/truesync/tenants", status=201, body={
        "tenant": {"slug": "petco", "display_name": "Petco", "soa_org_id": "?"},
        "token_id": "cccccccccccccccc", "scope": "write", "token": TOKEN_NEW,
    })
    upstream.answer("POST", "/api/truesync/tenant/merchants", status=409,
                    body={"detail": "merchant slug 'petco' is not available"})

    response = http.post("/api/customers", json={
        "account": {"name": "Petco"}, "merchant": NEW_MERCHANT, "retailers": []})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "not available" in detail["message"]
    assert isinstance(detail["org_id"], int), "the wizard retries under this account"


def test_account_must_be_existing_or_new_not_both(http, upstream):
    _as("op")
    response = http.post("/api/customers", json={
        "account": {"org_id": 10, "name": "Petco"}, "merchant": NEW_MERCHANT})
    assert response.status_code == 422
    assert upstream.calls == []
