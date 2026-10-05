#!/usr/bin/env python3
"""
Step 1C backfill. Run once, after migration a7c3e9f1b2d4 and before the API
that reads it is deployed.

    SOA_SECRET_KEY=<the Fernet key> \\
    TRUESYNC_TENANT_TOKEN=<W&S's tenant token> \\
    SOA_ALLOW_REMOTE_MIGRATION=1 \\
        python3 scripts/backfill_customer_accounts.py \\
            --operator-email you@parleo.io [--operator-email ...]

What it does, idempotently:

  1. Finds the Wiggle & Snug org by name (--org-name). If there isn't one,
     it creates it. Today the only orgs are the staff org ('Parleo') and
     'Parleo Lead Gen', and neither is a customer.
  2. Links that org to its supply tenant (--tenant-slug, default
     wiggle-and-snug) and stores the tenant token SEALED
     (soa_shared/secret_box.py). The token is read from an environment
     variable (--token-env, default TRUESYNC_TENANT_TOKEN), never from
     argv, which shells keep in history and `ps` shows to everyone. The
     token is checked against supply first: GET /api/truesync/tenant must
     answer with --tenant-slug. --no-verify skips that, for an offline
     run.
  3. Marks every membership of each --operator-email as an operator.
  4. Stamps customer_organization_id on every generation job grounded in
     one of the tenant's merchants. Without it the scorer could only read
     those studies' catalogs through the TRUESYNC_TENANT_TOKEN fallback,
     which is about to be removed. The merchant list comes from the
     tenant's GET /tenant, or from --merchant when --no-verify is given.

It prints counts and the token's public id, never the token.

The target database is ALEMBIC_DATABASE_URL if set (a throwaway Postgres),
otherwise the deployment's Supabase database. A remote target needs
SOA_ALLOW_REMOTE_MIGRATION=1 on the command, exactly as a migration does.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

import soa_shared.config as config  # noqa: E402
from migration_target import assert_migration_target_permitted, safe_display  # noqa: E402
from soa_shared import secret_box  # noqa: E402

DEFAULT_ORG = "Wiggle & Snug"
DEFAULT_TENANT = "wiggle-and-snug"


def _target_url():
    override = os.getenv("ALEMBIC_DATABASE_URL")
    if override:
        return override
    from soa_shared.database import get_database_url

    return get_database_url(pooled=False)


def _token_id(token: str):
    # tst_<token_id>_<secret>: the middle part is public, the rest is not.
    parts = token.split("_")
    return parts[1] if len(parts) >= 3 and parts[0] == "tst" else None


def _tenant_from_supply(token: str) -> dict:
    response = httpx.get(
        f"{config.TRUESYNC_API_BASE.rstrip('/')}/api/truesync/tenant",
        headers={"X-TrueSync-Key": token},
        timeout=30,
    )
    if response.status_code in (401, 403):
        raise SystemExit("supply refused the token (403): it is not a live token for any tenant")
    response.raise_for_status()
    return response.json()


def run(args, *, conn, tenant_view=None) -> dict:
    """The backfill against one open connection; returns what it did."""
    token = os.environ.get(args.token_env, "")
    if not token:
        raise SystemExit(f"{args.token_env} is not set; the token is read from there")

    if tenant_view is not None and tenant_view.get("slug") != args.tenant_slug:
        raise SystemExit(
            f"that token belongs to tenant {tenant_view.get('slug')!r}, not {args.tenant_slug!r}"
        )

    report = {}

    # 1. The org.
    row = conn.execute(
        text("SELECT id FROM organizations WHERE name = :n"), {"n": args.org_name}
    ).fetchone()
    if row:
        org_id = row[0]
        report["org"] = f"found {args.org_name!r} (id {org_id})"
    else:
        org_id = conn.execute(
            text("INSERT INTO organizations (name) VALUES (:n) RETURNING id"),
            {"n": args.org_name},
        ).fetchone()[0]
        report["org"] = f"created {args.org_name!r} (id {org_id})"

    holder = conn.execute(
        text("SELECT id FROM organizations WHERE truesync_tenant_slug = :s AND id <> :id"),
        {"s": args.tenant_slug, "id": org_id},
    ).fetchone()
    if holder:
        raise SystemExit(f"tenant {args.tenant_slug!r} is already linked to org {holder[0]}")

    # 2. The link, sealed.
    conn.execute(
        text("""
            UPDATE organizations
            SET truesync_tenant_slug = :slug, truesync_token_sealed = :sealed,
                truesync_token_id = :tid
            WHERE id = :id
        """),
        {"id": org_id, "slug": args.tenant_slug, "sealed": secret_box.seal(token),
         "tid": _token_id(token)},
    )
    report["link"] = f"org {org_id} -> tenant {args.tenant_slug}, token id {_token_id(token)}"

    # 3. Operators.
    marked, unknown = 0, []
    for email in args.operator_email or []:
        result = conn.execute(
            text("UPDATE organization_members SET is_operator = :yes WHERE lower(email) = lower(:e)"),
            {"yes": True, "e": email},
        )
        if result.rowcount:
            marked += result.rowcount
        else:
            unknown.append(email)
    report["operators"] = f"{marked} membership(s) marked"
    if unknown:
        report["operators"] += (
            f"; no membership yet for {', '.join(unknown)} — sign in once, then re-run"
        )

    # 4. Studies.
    merchants = (
        [m["slug"] for m in tenant_view.get("merchants", [])]
        if tenant_view is not None else list(args.merchant or [])
    )
    stamped = 0
    if merchants:
        params = {"org": org_id, **{f"m{i}": slug for i, slug in enumerate(merchants)}}
        placeholders = ", ".join(f":m{i}" for i in range(len(merchants)))
        stamped = conn.execute(
            text(f"""
                UPDATE soa_query_generation_jobs SET customer_organization_id = :org
                WHERE customer_organization_id IS NULL
                  AND syndicated_merchant IN ({placeholders})
            """),
            params,
        ).rowcount
    report["studies"] = f"{stamped} generation job(s) stamped (merchants: {', '.join(merchants) or 'none'})"
    unstamped = conn.execute(text("""
        SELECT COUNT(*) FROM soa_query_generation_jobs
        WHERE syndicated_merchant IS NOT NULL AND customer_organization_id IS NULL
    """)).scalar()
    report["unstamped"] = f"{unstamped} grounded job(s) still without a customer org"
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--org-name", default=DEFAULT_ORG)
    parser.add_argument("--tenant-slug", default=DEFAULT_TENANT)
    parser.add_argument("--token-env", default="TRUESYNC_TENANT_TOKEN")
    parser.add_argument("--operator-email", action="append")
    parser.add_argument("--merchant", action="append",
                        help="with --no-verify: a merchant slug whose studies to stamp")
    parser.add_argument("--no-verify", action="store_true",
                        help="do not ask supply which tenant the token belongs to")
    args = parser.parse_args(argv)

    url = _target_url()
    assert_migration_target_permitted(url)
    token = os.environ.get(args.token_env, "")
    tenant_view = None if args.no_verify or not token else _tenant_from_supply(token)

    engine = create_engine(url)
    with engine.begin() as conn:
        report = run(args, conn=conn, tenant_view=tenant_view)
    print(f"backfill against {safe_display(url)}")
    for key, line in report.items():
        print(f"  {key:<10} {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
