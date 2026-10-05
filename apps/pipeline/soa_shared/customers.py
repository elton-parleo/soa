"""
Customer orgs: which soa org is which supply tenant, who may select it, and
the token that reaches it.

THE MODEL (Step 1C). One concept: a soa org IS a supply tenant. An org is
linked by `organizations.truesync_tenant_slug`, and holds that tenant's
service token sealed in `truesync_token_sealed` (soa_shared/secret_box.py).
An org with no link — the Parleo staff org, Lead Gen — is not a customer and
is never offered for selection.

WHO MAY SELECT WHAT. A Parleo operator is a user with any membership flagged
`organization_members.is_operator`; operators may select every linked org.
Anyone else is pinned to the linked orgs they are a member of. Customer
logins later are exactly that second case: an org member without the flag,
seeing one entry.

THE TOKEN. token_for_org() opens the org's sealed token. An org with no
stored token falls back to TRUESYNC_TENANT_TOKEN — Wiggle & Snug's, until
the backfill stores it — and once every linked org has its own, that
variable is removed and the fallback is dead code that refuses loudly. The
token never leaves the server: nothing here returns it to a route, and the
error messages name the org and the variable, never the value.

Raw SQL through soa_shared.database.engine, like app/org_context.py. Tests
swap `engine` for an in-memory one.
"""
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import text

import soa_shared.config as config
from soa_shared import secret_box
from soa_shared.database import engine

#: The fallback's name, for every message that has to say what to set.
FALLBACK_TOKEN_VARIABLE = "TRUESYNC_TENANT_TOKEN"


class CustomerError(RuntimeError):
    """Base for the refusals below; each carries an HTTP status for the API."""

    status = 500


class NotSelectable(CustomerError):
    """The user may not select this org (or it is not a customer at all)."""

    status = 403


class NoCustomer(CustomerError):
    """The user has no customer org to select."""

    status = 404


class NoTenantToken(CustomerError):
    """The org is linked but there is no token to reach its tenant with."""

    status = 503


@dataclass(frozen=True)
class CustomerOrg:
    id: int
    name: str
    tenant_slug: str
    token_id: Optional[str]
    #: False when the org relies on the TRUESYNC_TENANT_TOKEN fallback.
    has_stored_token: bool


def _row_to_org(row) -> CustomerOrg:
    return CustomerOrg(
        id=row.id,
        name=row.name,
        tenant_slug=row.truesync_tenant_slug,
        token_id=row.truesync_token_id,
        has_stored_token=bool(row.truesync_token_sealed),
    )


_ORG_COLUMNS = (
    "o.id, o.name, o.truesync_tenant_slug, o.truesync_token_id, o.truesync_token_sealed"
)


# ─── Who the user is ────────────────────────────────────────────────────

def is_operator(user_id: str) -> bool:
    if not user_id:
        return False
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT 1 FROM organization_members
                WHERE user_id = :uid AND is_operator = :yes
                LIMIT 1
            """),
            {"uid": user_id, "yes": True},
        ).fetchone()
    return row is not None


def selectable_orgs(user_id: str) -> List[CustomerOrg]:
    """Every customer org this user may select, by name."""
    operator = is_operator(user_id)
    with engine.connect() as conn:
        if operator:
            rows = conn.execute(text(f"""
                SELECT {_ORG_COLUMNS} FROM organizations o
                WHERE o.truesync_tenant_slug IS NOT NULL
                ORDER BY o.name
            """)).fetchall()
        else:
            rows = conn.execute(text(f"""
                SELECT {_ORG_COLUMNS} FROM organizations o
                JOIN organization_members m ON m.organization_id = o.id
                WHERE m.user_id = :uid AND o.truesync_tenant_slug IS NOT NULL
                ORDER BY o.name
            """), {"uid": user_id}).fetchall()
    return [_row_to_org(r) for r in rows]


def resolve_selection(user_id: str, requested_org_id: Optional[int]) -> CustomerOrg:
    """
    The org a request is scoped to.

    `requested_org_id` is what the page sent (its persisted selection).
    Absent, the user's first selectable org is used — a non-operator has
    exactly one, so their pages need never send it. Present and not theirs
    to select, it is refused rather than quietly replaced: a page that
    believes it shows customer A must never be handed customer B's data.
    """
    orgs = selectable_orgs(user_id)
    if requested_org_id is None:
        if not orgs:
            raise NoCustomer("no customer account is linked to your login")
        return orgs[0]
    for org in orgs:
        if org.id == requested_org_id:
            return org
    raise NotSelectable(f"customer {requested_org_id} is not one you can select")


def get_org(org_id: int) -> Optional[CustomerOrg]:
    with engine.connect() as conn:
        row = conn.execute(
            text(f"SELECT {_ORG_COLUMNS} FROM organizations o WHERE o.id = :id"),
            {"id": org_id},
        ).fetchone()
    if row is None or row.truesync_tenant_slug is None:
        return None
    return _row_to_org(row)


# ─── The token ──────────────────────────────────────────────────────────

def token_for_org(org_id: int) -> str:
    """
    The tenant token for a linked org. Server-side only.

    Raises NoTenantToken (naming the org and what to set) rather than
    returning "", so no caller can send an empty credential and report the
    upstream's refusal as the problem.
    """
    return token_and_source_for_org(org_id)[0]


def token_and_source_for_org(org_id: int):
    """
    (token, source): source says where the token came from, in words an
    operator can act on when it is refused — which org's stored token, or
    the fallback variable on behalf of which org. Never the token.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(f"SELECT {_ORG_COLUMNS} FROM organizations o WHERE o.id = :id"),
            {"id": org_id},
        ).fetchone()
    if row is None or row.truesync_tenant_slug is None:
        raise NoTenantToken(f"org {org_id} is not linked to a TrueSync tenant")
    if row.truesync_token_sealed:
        try:
            token = secret_box.open_sealed(row.truesync_token_sealed)
        except secret_box.SecretBoxError as exc:
            raise NoTenantToken(f"{row.name} (org {row.id}): {exc}") from exc
        return token, f"the token stored for {row.name} (org {row.id})"
    if config.TRUESYNC_TENANT_TOKEN:
        return (
            config.TRUESYNC_TENANT_TOKEN,
            f"{FALLBACK_TOKEN_VARIABLE} (the fallback, for {row.name}, org {row.id})",
        )
    raise NoTenantToken(
        f"{row.name} (org {row.id}, tenant {row.truesync_tenant_slug}) has no stored "
        f"TrueSync token and {FALLBACK_TOKEN_VARIABLE} is not set"
    )


# ─── Writing ────────────────────────────────────────────────────────────

def create_org(conn, name: str) -> int:
    """A new org row; the caller's transaction commits it."""
    row = conn.execute(
        text("INSERT INTO organizations (name) VALUES (:name) RETURNING id"),
        {"name": name},
    ).fetchone()
    return row[0]


def link_tenant(conn, org_id: int, tenant_slug: str, token: Optional[str], token_id: Optional[str]):
    """
    Point an org at its tenant and store the token sealed. The caller's
    transaction commits. token=None links without a token (the fallback
    then applies).
    """
    conn.execute(
        text("""
            UPDATE organizations
            SET truesync_tenant_slug = :slug,
                truesync_token_sealed = :sealed,
                truesync_token_id = :token_id
            WHERE id = :id
        """),
        {
            "id": org_id,
            "slug": tenant_slug,
            "sealed": secret_box.seal(token) if token else None,
            "token_id": token_id,
        },
    )


# ─── Studies ────────────────────────────────────────────────────────────

def customer_org_for_study(study_type: str) -> Optional[int]:
    """
    The customer org a study was generated for, from its generation job.
    None for a study generated before Step 1C that the backfill did not
    stamp, or an ungrounded one.
    """
    if not study_type:
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT customer_organization_id FROM soa_query_generation_jobs
                WHERE study_type = :st
            """),
            {"st": study_type},
        ).fetchone()
    return row[0] if row else None


def token_for_study(study_type: str) -> str:
    return token_and_source_for_study(study_type)[0]


def token_and_source_for_study(study_type: str):
    """
    (token, source) a study's catalog is read with: its customer org's, or —
    for a study with no org recorded — the TRUESYNC_TENANT_TOKEN fallback
    while it exists. Raises NoTenantToken naming the study otherwise.
    """
    org_id = customer_org_for_study(study_type)
    if org_id is not None:
        return token_and_source_for_org(org_id)
    if config.TRUESYNC_TENANT_TOKEN:
        return (
            config.TRUESYNC_TENANT_TOKEN,
            f"{FALLBACK_TOKEN_VARIABLE} (the fallback; study {study_type!r} records no customer org)",
        )
    raise NoTenantToken(
        f"study {study_type!r} records no customer org and {FALLBACK_TOKEN_VARIABLE} "
        f"is not set; run scripts/backfill_customer_accounts.py"
    )
