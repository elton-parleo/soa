"""
2B §6: which tenant a console read is scoped to.

The console's read models are tenant-scoped exactly as the TrueSync proxy is
(app/customer_context.py), with one addition the brief asks for: an
operator may name another tenant with `?org=<org id>`. A member gets their
own org; a member naming another org is refused (403), never quietly
handed their own data under the other org's name. `?org=` wins over the
X-Parleo-Customer header when both are sent.

A cycle belongs to the customer its study was generated for
(soa_query_generation_jobs.customer_organization_id), falling back to the
org that created the cycle for a study with none recorded. A cycle outside
the scope is a 404 worded like a missing one, as supply words its own.
"""
from typing import Optional

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy import text

from app.auth import verify_token
from app.customer_context import HEADER, CustomerScope, _requested_org
from soa_shared import customers
from soa_shared.database import engine


def console_scope(
    org: Optional[int] = Query(None, description="Operators only: another tenant's org id"),
    x_parleo_customer: Optional[str] = Header(None, alias=HEADER),
    user: dict = Depends(verify_token),
) -> CustomerScope:
    requested = org if org is not None else _requested_org(x_parleo_customer)
    try:
        chosen = customers.resolve_selection(user.get("sub"), requested)
        return CustomerScope(org=chosen, token=customers.token_for_org(chosen.id))
    except customers.CustomerError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


def cycle_customer_org_sql() -> str:
    """SQL for a cycle's customer org, given alias c for soa_cycles."""
    return ("COALESCE((SELECT j.customer_organization_id FROM soa_query_generation_jobs j "
            "WHERE j.study_type = c.study_type), c.organization_id)")


def cycle_in_scope(cycle_code: str, scope: CustomerScope):
    """The cycle row (mapping), or 404 when it is not this tenant's."""
    with engine.connect() as conn:
        row = conn.execute(text(f"""
            SELECT c.*, {cycle_customer_org_sql()} AS customer_org_id
            FROM soa_cycles c WHERE c.cycle_code = :code
        """), {"code": cycle_code}).mappings().fetchone()
    if row is None or row["customer_org_id"] != scope.org.id:
        raise HTTPException(status_code=404, detail=f"cycle {cycle_code!r} not found")
    return row
