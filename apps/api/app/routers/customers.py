"""
/api/customers: the customer switcher's list, and the setup wizard's first
step (operators only).

GET /api/customers
    Every org this user may select (soa_shared/customers.py decides which),
    each with its tenant's merchants: name, kind, hosting, and whether a
    record exists yet. The merchants come from supply's GET /tenant,
    read with that org's own token, so the list says what each tenant
    actually holds, not what this app remembers. An org whose read fails
    is still listed, carrying the error, rather than vanishing from the
    switcher: a customer whose token was revoked should look broken, not
    absent.

POST /api/customers  (operator only)
    Step 1 of the wizard, "Account & customer". In order:
      1. the account: an existing linked org, or a NEW org plus its supply
         tenant. The tenant is created and its first token issued
         server-side (supply POST /tenants, with the provisioning key), and
         the token is sealed onto the org in the same transaction that
         creates it. If supply refuses, nothing is written here.
      2. the merchant, in that tenant (supply POST /tenant/merchants), with
         its kind and hosting;
      3. its retailer list (supply PUT /merchants/{slug}/retailers).
    No token is ever in the response. A failure after step 1 created an
    account says so, with the new org's id, so the wizard can retry the
    merchant under "add to existing" instead of creating a second account.
"""
import asyncio
import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.auth import verify_token
from app.customer_context import require_operator
from clients.truesync_client import TrueSyncClient, TrueSyncProvisioningClient
from soa_shared import customers
from soa_shared.database import engine

log = logging.getLogger(__name__)
router = APIRouter()


def slugify(name: str) -> str:
    """'P&G Baby Care' -> 'p-g-baby-care': supply's slug rule."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


async def _tenant_view(org: customers.CustomerOrg) -> dict:
    entry = {
        "org_id": org.id,
        "name": org.name,
        "tenant_slug": org.tenant_slug,
        "merchants": [],
        "error": None,
    }
    try:
        token = customers.token_for_org(org.id)
    except customers.CustomerError as exc:
        entry["error"] = str(exc)
        return entry
    status, data, error = await TrueSyncClient(token=token).get_tenant()
    if error is not None:
        entry["error"] = (
            f"Not authorized for this customer — TrueSync refused its token ({error})"
            if status == 403 else error
        )
        return entry
    entry["merchants"] = [
        {k: m.get(k) for k in ("slug", "name", "domain", "kind", "hosting", "has_record")}
        for m in (data or {}).get("merchants", [])
    ]
    return entry


@router.get("/customers")
async def list_customers(user: dict = Depends(verify_token)):
    user_id = user.get("sub")
    orgs = customers.selectable_orgs(user_id)
    views = await asyncio.gather(*(_tenant_view(org) for org in orgs))
    return {"is_operator": customers.is_operator(user_id), "customers": list(views)}


# ─── The wizard's step 1 ────────────────────────────────────────────────

class AccountChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: An existing linked org, or —
    org_id: Optional[int] = None
    #: — the name of a new one.
    name: Optional[str] = None


class MerchantChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    domain: Optional[str] = None
    kind: str
    hosting: str
    slug: Optional[str] = None


class NewCustomerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account: AccountChoice
    merchant: MerchantChoice
    retailers: List[str] = []


def _fail(status: int, detail: str, *, org_id: Optional[int] = None):
    payload = {"message": detail}
    if org_id is not None:
        payload["org_id"] = org_id
    raise HTTPException(status_code=status, detail=payload)


async def _new_account(name: str) -> customers.CustomerOrg:
    """A new org and its supply tenant, linked, token sealed — or nothing."""
    name = name.strip()
    slug = slugify(name)
    if not slug:
        _fail(422, "the account needs a name with letters or digits in it")
    # One transaction: the org row exists only if supply created the tenant
    # and the token was sealed onto it. Any raise inside rolls it back.
    with engine.begin() as conn:
        if conn.execute(
            text("SELECT 1 FROM organizations WHERE name = :n"), {"n": name}
        ).fetchone():
            _fail(409, f"an account named {name!r} already exists; add to it instead")
        org_id = customers.create_org(conn, name)
        status, data, error = await TrueSyncProvisioningClient().create_tenant(
            slug, name, str(org_id),
        )
        if error is not None:
            _fail(status if status in (409, 422, 503) else 502,
                  f"TrueSync did not create the account: {error}")
        customers.link_tenant(conn, org_id, data["tenant"]["slug"], data["token"],
                              data.get("token_id"))
    log.info("[customers] created org %s linked to tenant %s", org_id, slug)
    return customers.get_org(org_id)


@router.post("/customers", status_code=201)
async def create_customer(body: NewCustomerRequest, user: dict = Depends(require_operator)):
    if (body.account.org_id is None) == (body.account.name is None):
        _fail(422, "choose an existing account (org_id) or name a new one (name), not both")

    created_account = False
    if body.account.org_id is not None:
        org = customers.get_org(body.account.org_id)
        if org is None:
            _fail(404, f"account {body.account.org_id} is not a linked customer account")
    else:
        org = await _new_account(body.account.name)
        created_account = True

    def fail_after_account(status, detail):
        _fail(status, detail, org_id=org.id if created_account else None)

    try:
        token = customers.token_for_org(org.id)
    except customers.CustomerError as exc:
        fail_after_account(exc.status, str(exc))
    client = TrueSyncClient(token=token)

    merchant_slug = (body.merchant.slug or slugify(body.merchant.name)).strip()
    status, merchant, error = await client.create_merchant({
        "slug": merchant_slug,
        "name": body.merchant.name.strip(),
        "domain": body.merchant.domain,
        "kind": body.merchant.kind,
        "hosting": body.merchant.hosting,
    })
    if error is not None:
        fail_after_account(status or 502, f"TrueSync did not create the customer: {error}")

    retailers = [d.strip() for d in body.retailers if d and d.strip()]
    retailer_list = None
    if retailers:
        status, retailer_list, error = await client.put_retailers(merchant_slug, retailers)
        if error is not None:
            fail_after_account(
                status or 502,
                f"the customer was created, but its retailer list was refused: {error}",
            )

    return {
        "org_id": org.id,
        "org_name": org.name,
        "tenant_slug": org.tenant_slug,
        "created_account": created_account,
        "merchant": merchant,
        "retailers": retailer_list,
    }
