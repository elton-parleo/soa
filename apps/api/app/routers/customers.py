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

GET /api/customers/lookup?domain=&org_id=  (operator only)
    What taking a domain would mean for that account (Step 2A-0): unknown
    (create), unclaimed (claim — with what is on file), mine, unavailable.

GET /api/customers/{org_id}/merchants/{slug}/competitors  (operator only)
PUT /api/customers/{org_id}/merchants/{slug}/competitors  {competitors: [{name, domain}]}
    2I-6: the competitors a merchant's cycles track, entered once, in the
    wizard or on the customer in Command Center. One save writes, in order:
    (1) supply's comparison_domains (PUT /merchants/{slug}/comparison-domains,
    2A-4: 409 for an own or retailer domain, 422 on format), then (2) one
    soa_entities row per competitor (soa_shared.comparison_sets.upsert_competitor:
    matched by domain alias or website, else created with the name given; a
    match named by its domain is renamed). Supply refusing leaves the entities
    untouched; entities failing after supply saved says so, and saving again
    finishes it. Both answer with the read-back: supply's list joined to soa's
    entity names, "no entity yet" (name null) where a domain has none.

POST /api/customers  (operator only)
    Step 1 of the wizard, "Account & customer". A merchant's identity is its
    domain: a domain the scrapers or the audit tool already know is CLAIMED,
    never created twice — and only when the request says `claim: true`,
    i.e. the operator saw the claim card and chose it.
      * NEW account: the org is inserted and supply's POST /tenants creates
        the tenant AND its first merchant (claimed or created) in one
        supply transaction; the token is sealed onto the org; soa commits;
        THEN supply is told the org (PUT /tenant/link). If soa's commit
        fails, supply holds an unlinked, never-used tenant — and the retry's
        POST /tenants reuses it instead of failing on "already exists".
      * EXISTING account: claim (unclaimed), keep (already the account's),
        or create (unknown), with that account's token.
      * then its retailer list.
    No token is ever in the response. A failure after a new account was
    created says so, with its org id, so the wizard retries under it.
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
    # 2R-2: supply 2R-1's `mode` ('manufacturer' for a brand at retail) and what it holds
    # (`held`: total, by_channel, blocked, compiled_at, sent), only when it sends them
    entry["merchants"] = [
        {**{k: m.get(k) for k in ("slug", "name", "domain", "kind", "hosting", "has_record")},
         **{k: m[k] for k in ("mode", "held") if m.get(k)}}
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
    #: The operator saw the claim card ("<domain> is already known") and chose
    #: to claim it. Without this an unclaimed domain is refused, never taken.
    claim: bool = False


def _fail(status: int, detail: str, *, org_id: Optional[int] = None, code: Optional[str] = None):
    payload = {"message": detail}
    if org_id is not None:
        payload["org_id"] = org_id
    if code is not None:
        payload["code"] = code
    raise HTTPException(status_code=status, detail=payload)


def _merchant_spec(m: "MerchantChoice") -> dict:
    return {
        "domain": m.domain,
        "name": m.name.strip(),
        "slug": (m.slug or slugify(m.name)).strip(),
        "kind": m.kind,
        "hosting": m.hosting,
    }


async def _new_account(name: str, merchant: "MerchantChoice"):
    """
    A new org, its supply tenant and its first merchant — all, or nothing
    here. Returns (org, merchant view from supply).
    """
    name = name.strip()
    slug = slugify(name)
    if not slug:
        _fail(422, "the account needs a name with letters or digits in it")
    # One transaction here, one at supply. Any raise inside rolls the org
    # back; supply's side is then an unlinked, unused tenant, which the next
    # attempt with this name reuses (supply docs/truesync/provenance.md).
    with engine.begin() as conn:
        if conn.execute(
            text("SELECT 1 FROM organizations WHERE name = :n"), {"n": name}
        ).fetchone():
            _fail(409, f"an account named {name!r} already exists; add to it instead")
        org_id = customers.create_org(conn, name)
        status, data, error = await TrueSyncProvisioningClient().create_tenant(
            slug, name, merchant=_merchant_spec(merchant),
        )
        if error is not None:
            _fail(status if status in (409, 422, 503) else 502,
                  f"TrueSync did not create the account: {error}")
        customers.link_tenant(conn, org_id, data["tenant"]["slug"], data["token"],
                              data.get("token_id"))
        token = data["token"]
    # Committed. Only now does supply learn which org this is: until then the
    # tenant counts as a leftover a retry may take over, which is exactly
    # right while this side could still roll back.
    status, _linked, error = await TrueSyncClient(token=token).link_tenant(str(org_id))
    if error is not None:
        log.warning("[customers] org %s committed but supply link failed (%s): %s",
                    org_id, status, error)
    log.info("[customers] created org %s linked to tenant %s (%s merchant %s)", org_id, slug,
             (data.get("merchant") or {}).get("action"), (data.get("merchant") or {}).get("slug"))
    return customers.get_org(org_id), data.get("merchant")


async def _lookup(org: Optional[customers.CustomerOrg], domain: str) -> dict:
    """
    supply's lookup, as seen from `org` — or, for an account that does not
    exist yet, from any linked account: lookup needs a tenant token, and a
    new tenant can own nothing, so that account's "mine" reads as
    "unavailable" here. Operator-only, and operators may see every account.
    """
    if org is None:
        linked = customers.linked_orgs()
        if not linked:
            return {"status": "unknown", "domain": domain}
        org, mine_means = linked[0], "unavailable"
    else:
        mine_means = "mine"
    try:
        token = customers.token_for_org(org.id)
    except customers.CustomerError as exc:
        _fail(exc.status, str(exc))
    status, data, error = await TrueSyncClient(token=token).lookup_merchant(domain)
    if error is not None:
        _fail(status or 502, f"TrueSync could not look the domain up: {error}")
    if data.get("status") == "mine":
        return data if mine_means == "mine" else {"status": "unavailable", "domain": data.get("domain")}
    return data


@router.get("/customers/lookup")
async def lookup_domain(domain: str, org_id: Optional[int] = None,
                        user: dict = Depends(require_operator)):
    org = None
    if org_id is not None:
        org = customers.get_org(org_id)
        if org is None:
            _fail(404, f"account {org_id} is not a linked customer account")
    return await _lookup(org, domain)


@router.post("/customers", status_code=201)
async def create_customer(body: NewCustomerRequest, user: dict = Depends(require_operator)):
    if (body.account.org_id is None) == (body.account.name is None):
        _fail(422, "choose an existing account (org_id) or name a new one (name), not both")

    org = None
    if body.account.org_id is not None:
        org = customers.get_org(body.account.org_id)
        if org is None:
            _fail(404, f"account {body.account.org_id} is not a linked customer account")

    # Identity is the domain. Look it up first, for the account it is going
    # into; a known merchant is only ever claimed with the operator's say-so.
    found = {"status": "unknown"}
    if body.merchant.domain:
        found = await _lookup(org, body.merchant.domain)
    if found["status"] == "unavailable":
        _fail(409, f"{found.get('domain') or body.merchant.domain} is not available")
    if found["status"] == "unclaimed" and not body.claim:
        _fail(409, f"{found.get('domain')} is already known; confirm the claim to take it",
              code="claimable")

    created_account = False
    if org is None:
        org, merchant = await _new_account(body.account.name, body.merchant)
        created_account = True
        action = (merchant or {}).get("action")
    else:
        org, merchant, action = await _merchant_for_existing(org, body, found)

    def fail_after_account(status, detail):
        _fail(status, detail, org_id=org.id if created_account else None)

    token = customers.token_for_org(org.id)
    client = TrueSyncClient(token=token)
    retailers = [d.strip() for d in body.retailers if d and d.strip()]
    retailer_list = None
    if retailers:
        status, retailer_list, error = await client.put_retailers(merchant["slug"], retailers)
        if error is not None:
            fail_after_account(
                status or 502,
                f"the customer was created, but its retailer list was refused: {error}",
            )
    provenance = None
    if action == "claimed":
        _status, provenance, _error = await client.get_provenance(merchant["slug"])

    return {
        "org_id": org.id,
        "org_name": org.name,
        "tenant_slug": org.tenant_slug,
        "created_account": created_account,
        "merchant_action": action,
        "merchant": merchant,
        "provenance": provenance,
        "retailers": retailer_list,
    }


async def _merchant_for_existing(org, body, found):
    """(org, merchant view, action) in an existing account: claim, keep or create."""
    try:
        token = customers.token_for_org(org.id)
    except customers.CustomerError as exc:
        _fail(exc.status, str(exc))
    client = TrueSyncClient(token=token)
    spec = _merchant_spec(body.merchant)

    if found["status"] == "mine":
        status, tenant, error = await client.get_tenant()
        if error is not None:
            _fail(status or 502, error)
        mine = next((m for m in tenant.get("merchants", []) if m["slug"] == found.get("slug")), None)
        return org, mine, "kept"

    if found["status"] == "unclaimed":
        slug = found["merchant"]["slug"]
        status, data, error = await client.claim_merchant(
            slug, spec["kind"], spec["hosting"], display_name=spec["name"],
        )
        if error is not None:
            _fail(status or 502, f"TrueSync did not claim {slug}: {error}")
        return org, data["merchant"], "claimed"

    status, merchant, error = await client.create_merchant({
        k: spec[k] for k in ("slug", "name", "domain", "kind", "hosting")
    })
    if error is not None:
        _fail(status or 502, f"TrueSync did not create the customer: {error}")
    return org, merchant, "created"


# ─── 2I-6: competitors to track ─────────────────────────────────────────

#: supply's own rule (truesync/tenancy.py _HOSTNAME_RE): bare lowercase hostnames, at most 50 (MAX_COMPARISON_DOMAINS)
HOSTNAME_RE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$")
MAX_COMPETITORS = 50


class Competitor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    domain: str


class CompetitorList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitors: List[Competitor]


def competitor_problems(rows: List[Competitor]) -> List[str]:
    """Format, as supply checks it, before anything is written."""
    problems = []
    if len(rows) > MAX_COMPETITORS:
        problems.append(f"at most {MAX_COMPETITORS} competitors")
    domains = [r.domain for r in rows]
    bad = [d for d in domains if d.startswith("www.") or not HOSTNAME_RE.match(d)]
    if bad:
        problems.append("not bare lowercase hostnames (no scheme, path, port, uppercase or leading www.): "
                        + ", ".join(map(repr, bad)))
    repeated = sorted({d for d in domains if domains.count(d) > 1})
    if repeated:
        problems.append("listed more than once: " + ", ".join(map(repr, repeated)))
    if any(not r.name.strip() for r in rows):
        problems.append("every competitor needs a name")
    return problems


def _competitor_client(org_id: int):
    org = customers.get_org(org_id)
    if org is None:
        _fail(404, f"account {org_id} is not a linked customer account")
    try:
        return TrueSyncClient(token=customers.token_for_org(org.id))
    except customers.CustomerError as exc:
        _fail(exc.status, str(exc))


def competitors_view(slug: str, retailers: dict) -> dict:
    """supply's /retailers view, its comparison_domains joined to soa's entity names."""
    from soa_shared.comparison_sets import match_entity
    listed = list((retailers or {}).get("comparison_domains") or [])
    with engine.connect() as conn:
        known = [dict(r) for r in conn.execute(text(
            "SELECT id, name, website_url, aliases FROM soa_entities ORDER BY id")).mappings()]
        names = {e["id"]: e["name"] for e in known}
        rows = []
        for domain in listed:
            entity = match_entity(conn, domain, known)
            rows.append({"domain": domain, "entity_id": entity, "name": names.get(entity)})
    return {
        "merchant": slug,
        "own_domains": list((retailers or {}).get("own_domains") or []),
        "retailer_domains": list((retailers or {}).get("domains") or []),
        "competitors": rows,
    }


@router.get("/customers/{org_id}/merchants/{slug}/competitors")
async def get_competitors(org_id: int, slug: str, user: dict = Depends(require_operator)):
    status, retailers, error = await _competitor_client(org_id).get_retailers(slug)
    if error is not None:
        _fail(status or 502, f"TrueSync did not answer with {slug}'s competitor list: {error}")
    return competitors_view(slug, retailers)


@router.put("/customers/{org_id}/merchants/{slug}/competitors")
async def put_competitors(org_id: int, slug: str, body: CompetitorList, user: dict = Depends(require_operator)):
    from soa_shared.comparison_sets import upsert_competitor
    problems = competitor_problems(body.competitors)
    if problems:
        _fail(422, "; ".join(problems), code="invalid")
    client = _competitor_client(org_id)
    # (1) supply: the list it reads pages for and every cycle's rivals come from
    status, retailers, error = await client.put_comparison_domains(slug, [r.domain for r in body.competitors])
    if error is not None:
        _fail(status or 502, f"TrueSync refused the competitor list, so nothing was saved: {error}",
              code="supply_refused")
    # (2) soa: the entities the coder tracks, named as entered
    _status, tenant, _error = await client.get_tenant()
    record = next((m for m in (tenant or {}).get("merchants", []) if m.get("slug") == slug), {})
    entity_type = "brand" if record.get("kind") != "seller" else "retailer"
    saved = []
    try:
        with engine.begin() as conn:
            for row in body.competitors:
                entity_id, action = upsert_competitor(conn, row.name.strip(), row.domain, entity_type)
                saved.append({"domain": row.domain, "entity_id": entity_id, "action": action})
    except Exception as exc:  # noqa: BLE001 - said, with what did save
        log.exception("competitors for %s: entities not written", slug)
        _fail(500, "TrueSync saved the competitor list, but soa's entities were not written "
                   f"({exc.__class__.__name__}); save again to finish", code="entities_failed")
    return {**competitors_view(slug, retailers), "saved": saved}

