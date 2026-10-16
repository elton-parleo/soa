"""
2H: one org, several merchants.

An org (a TrueSync tenant) can hold several supply merchants: Wiggle & Snug's
store (`wiggle-and-snug`, a seller hosted on Parleo, trueshopstore.com) and
its brand (`wiggle-and-snug-brand`, customer-hosted, wiggleandsnug.com). The
console picks one, and every read it makes names it with `?merchant=`.

The org's merchants come from supply's `/tenant`, in the order the Command
Center lists them, read once per request with the org's own token. The first
is the org's **primary** merchant, the one 2C-0 used for everything, so a call
that names no merchant behaves as it did before 2H.

A merchant slug that is not one of the org's is a 404, worded like a
cross-tenant one. When the tenant cannot be read (an outage, a refused token)
a named merchant is passed through unverified: supply refuses one that is not
the token's, and the read degrades as it did before.

A cycle belongs to one merchant: the one its study was generated for
(soa_query_generation_jobs.syndicated_merchant, else the merchant in its
tier_config). A cycle whose study names none predates 2H and belongs to the
primary merchant.
"""
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from fastapi import Depends, HTTPException, Query
from sqlalchemy import text

from app.console_scope import console_scope, cycle_customer_org_sql
from app.customer_context import CustomerScope


@dataclass
class MerchantScope:
    """The org scope, and the merchant a console call reads."""
    scope: CustomerScope
    slug: Optional[str]                  # the named merchant, else the primary; None when neither is known
    primary: Optional[str]
    merchants: List[dict] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def is_primary(self) -> bool:
        return self.slug is None or self.slug == self.primary

    def owns(self, merchant_slug: Optional[str]) -> bool:
        """Whether a record tagged with `merchant_slug` (None: before 2H) is this merchant's."""
        if self.slug is None:
            return True
        return merchant_slug == self.slug or (merchant_slug is None and self.is_primary)


async def org_merchants(org) -> tuple:
    """(the org's merchants from supply's /tenant, error). Imported here, not
    at the top: the customers router imports the console scope."""
    from app.routers.customers import _tenant_view
    view = await _tenant_view(org)
    return list(view.get('merchants') or []), view.get('error')


def resolve(scope: CustomerScope, merchants: List[dict], error: Optional[str], merchant: Optional[str]) -> MerchantScope:
    slugs = [m.get('slug') for m in merchants if m.get('slug')]
    primary = slugs[0] if slugs else None
    if merchant and slugs and merchant not in slugs:
        raise HTTPException(status_code=404, detail=f"merchant {merchant!r} not found")
    return MerchantScope(scope=scope, slug=merchant or primary, primary=primary, merchants=merchants, error=error)


async def merchant_scope(merchant: Optional[str] = Query(None, description="2H: one of the org's merchants; absent, the primary"),
                         scope: CustomerScope = Depends(console_scope)) -> MerchantScope:
    merchants, error = await org_merchants(scope.org)
    return resolve(scope, merchants, error, merchant)


def _json(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def study_merchants(conn, org_id: int) -> Dict[str, Optional[str]]:
    """{study_type: the merchant it was generated for, or None} for the org's studies."""
    out: Dict[str, Optional[str]] = {}
    for row in conn.execute(text("""
        SELECT study_type, syndicated_merchant, tier_config FROM soa_query_generation_jobs
        WHERE COALESCE(customer_organization_id, organization_id) = :org
    """), {"org": org_id}).mappings():
        tier = _json(row['tier_config']) or {}
        out[row['study_type']] = row['syndicated_merchant'] or (tier.get('merchant') or {}).get('slug')
    return out


def merchant_cycles(conn, ms: MerchantScope) -> List[dict]:
    """The org's cycles that belong to the scope's merchant, newest first."""
    studies = study_merchants(conn, ms.scope.org.id)
    rows = [dict(c) for c in conn.execute(text(f"""
        SELECT c.* FROM soa_cycles c
        WHERE {cycle_customer_org_sql()} = :org
        ORDER BY c.start_date DESC, c.id DESC
    """), {"org": ms.scope.org.id}).mappings()]
    return [c for c in rows if ms.owns(studies.get(c['study_type']))]


async def check_merchant(scope: CustomerScope, merchant: Optional[str]) -> MerchantScope:
    """For an endpoint that already takes `merchant`: the same 404 for a slug
    that is not the org's (or the primary, when it is optional and absent)."""
    merchants, error = await org_merchants(scope.org)
    return resolve(scope, merchants, error, merchant)


async def with_domains(client, merchants: List[dict]) -> List[dict]:
    """The switcher's merchants: slug, name, kind, hosting, the own domain, and
    `primary` on the first, in /tenant's order. The own domain is the first of
    the merchant's own_domains (#20) from /merchants/{slug}/retailers, else its
    own_domain, else the tenant record's domain."""
    import asyncio

    async def own_of(m):
        _status, body, error = await client.get_retailers(m['slug'])
        if error is None and isinstance(body, dict):
            return ((body.get('own_domains') or [None])[0]) or body.get('own_domain')
        return None

    listed = [m for m in merchants if m.get('slug')]
    owns = await asyncio.gather(*(own_of(m) for m in listed))
    out = []
    for i, (m, own) in enumerate(zip(listed, owns)):
        out.append({'slug': m['slug'], 'name': m.get('name') or m['slug'],
                    'kind': m.get('kind') if m.get('kind') in ('seller', 'brand') else None,
                    'hosting': m.get('hosting') if m.get('hosting') in ('parleo', 'external') else None,
                    'domain': own or m.get('domain'), 'primary': i == 0})
    return out
