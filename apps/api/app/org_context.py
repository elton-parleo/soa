"""
Resolves the organization a verified user belongs to. Auto-provisions
membership in the default 'Parleo' organization on first request for
any verified @parleo.io user — there is currently only one organization,
so this requires no admin action.

When multiple organizations exist in the future, auto-provisioning should
be replaced with an explicit invite/signup flow — this function will
then only RESOLVE existing membership, not create it.
"""

from sqlalchemy import text
from soa_shared.database import engine


def get_or_create_organization_id(
    user_id: str,
    email: str,
) -> int:
    """
    Returns the organization_id for the given Supabase user_id.
    If no membership row exists, creates one in the default
    'Parleo' organization.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT organization_id
                FROM organization_members
                WHERE user_id = :uid
            """),
            {"uid": user_id},
        ).fetchone()

        if row:
            return row[0]

        # First time seeing this user — provision into Parleo
        parleo = conn.execute(
            text("""
                SELECT id FROM organizations
                WHERE name = 'Parleo'
            """)
        ).fetchone()

        if not parleo:
            raise RuntimeError(
                "Default 'Parleo' organization not found — run migrations."
            )

        org_id = parleo[0]

        conn.execute(
            text("""
                INSERT INTO organization_members
                  (organization_id, user_id, email, role, created_at)
                VALUES
                  (:org_id, :uid, :email, 'member', NOW())
            """),
            {
                "org_id": org_id,
                "uid": user_id,
                "email": email,
            },
        )
        conn.commit()

        return org_id
