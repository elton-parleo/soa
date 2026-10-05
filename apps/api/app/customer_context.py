"""
Which customer a request is scoped to, and the token that reaches it.

The page sends its persisted selection as X-Parleo-Customer: <org id>
(web/src/customerSelection.js). This resolves it against the user's rights
(soa_shared/customers.py) and opens that org's tenant token, for the TrueSync
proxy to attach upstream:

  * operator      — any linked org.
  * anyone else   — only their own linked org. A header naming another org
                    is 403, never silently replaced: a page that believes it
                    shows customer A must never be handed customer B's data.
  * no header     — the user's first selectable org. That is the only org
                    a non-operator has, so a customer's pages need not send it.

The token rides on the CustomerScope into the router and from there into
TrueSyncClient's header. It is excluded from the dataclass repr, so a
logged or raised scope cannot print it, and nothing returns it in a
response.
"""
from dataclasses import dataclass, field
from typing import Optional

from fastapi import Depends, Header, HTTPException

from app.auth import verify_token
from soa_shared import customers
from soa_shared.customers import CustomerOrg

HEADER = "X-Parleo-Customer"


@dataclass(frozen=True)
class CustomerScope:
    org: CustomerOrg
    token: str = field(repr=False)


def _requested_org(raw: Optional[str]) -> Optional[int]:
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{HEADER} must be an org id")


def customer_scope(
    x_parleo_customer: Optional[str] = Header(None, alias=HEADER),
    user: dict = Depends(verify_token),
) -> CustomerScope:
    try:
        org = customers.resolve_selection(user.get("sub"), _requested_org(x_parleo_customer))
        return CustomerScope(org=org, token=customers.token_for_org(org.id))
    except customers.CustomerError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


def require_operator(user: dict = Depends(verify_token)) -> dict:
    """Operator-only routes: the setup wizard."""
    if not customers.is_operator(user.get("sub")):
        raise HTTPException(status_code=403, detail="only a Parleo operator can do this")
    return user
