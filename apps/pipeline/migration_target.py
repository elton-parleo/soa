"""
Which database an alembic run may touch — the remote-migration guard.

The same two-key convention parleo-supply-app adopted after an `alembic
upgrade head` meant for a throwaway Postgres migrated the live database
instead (supply: modules/db_target.py). Here the default target IS the
live Supabase database — alembic/env.py assembles it from SUPABASE_* when
ALEMBIC_DATABASE_URL is unset — so the failure mode is simpler and more
likely: a developer runs `alembic upgrade head` to try something and it
lands on production, because that is where it points by default.

So a remote migration is a two-key operation:

    the target           -> ALEMBIC_DATABASE_URL, or SUPABASE_* by default
    the permission       -> SOA_ALLOW_REMOTE_MIGRATION=1, for that one run

A local target (localhost, 127.0.0.1, ::1, a Unix socket directory) needs
no permission. Anything else is refused unless the variable is set, and is
announced when it is. Deliberately an environment variable, not a prompt:
migrations are applied non-interactively, and a prompt would be either a
blocker or something answered by reflex.

The decision lives here rather than in alembic/env.py because env.py runs
its work at import and cannot be imported by a test without running it —
and a guard nothing can test is a guard nobody should rely on.

require_local() is the assertion helper for round-trips: scripts/
migration_roundtrip.py calls it before every step, so "I checked the
connection was local" is something the script does, not something a
person remembers.
"""
import os
from typing import Optional, Union

from sqlalchemy.engine import URL, make_url

ENV_ALLOW_REMOTE = "SOA_ALLOW_REMOTE_MIGRATION"

#: Hosts that are unambiguously this machine. Strict on purpose: an
#: unrecognised host is NOT local, because a false "remote" costs a flag
#: and a false "local" costs a migration against production.
LOCAL_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", ""})


class RemoteDatabaseError(RuntimeError):
    """An operation that must be local, or permitted, was pointed elsewhere."""


def _as_url(url: Union[str, URL]) -> URL:
    return url if isinstance(url, URL) else make_url(url)


def _socket_dir(url: URL) -> Optional[str]:
    """`?host=/path` — how libpq spells a Unix socket in a URL."""
    host = url.query.get("host")
    if isinstance(host, (tuple, list)):
        host = host[0] if host else None
    return host


def is_local(url: Union[str, URL]) -> bool:
    url = _as_url(url)
    host = url.host or ""
    if host.startswith("/"):
        return True
    if not host:
        socket = _socket_dir(url)
        if socket:
            return socket.startswith("/")
    return host.lower() in LOCAL_HOSTNAMES


def safe_display(url: Union[str, URL]) -> str:
    """The URL with its password masked — safe to print, log, or raise."""
    return _as_url(url).render_as_string(hide_password=True)


def require_local(url: Union[str, URL], *, operation: str = "this operation") -> URL:
    """The target, if it is local; otherwise raise naming the host refused."""
    url = _as_url(url)
    if is_local(url):
        return url
    raise RemoteDatabaseError(
        f"{operation} refused: {safe_display(url)} is not a local database "
        f"(host {url.host!r}). Point ALEMBIC_DATABASE_URL at a local Postgres — "
        f"localhost, 127.0.0.1, ::1, or a Unix socket directory — and retry."
    )


def assert_migration_target_permitted(url: Union[str, URL]) -> None:
    """
    Refuse to migrate a remote database unless it was explicitly allowed.

    Called by alembic/env.py on both the online and the offline (--sql)
    paths, before anything connects.
    """
    url = _as_url(url)
    if is_local(url):
        return
    if os.getenv(ENV_ALLOW_REMOTE) == "1":
        # Announced, not silent: an intentional production migration
        # should still say so in whatever log the operator keeps.
        print(f"alembic: migrating REMOTE database {safe_display(url)} ({ENV_ALLOW_REMOTE}=1)")
        return
    raise RemoteDatabaseError(
        f"alembic refused to migrate {safe_display(url)}: host {url.host!r} is not "
        f"local.\n"
        f"  * To migrate a throwaway local database, set ALEMBIC_DATABASE_URL to it "
        f"(localhost, 127.0.0.1, ::1, or a Unix socket directory).\n"
        f"  * To migrate this remote database on purpose, set "
        f"{ENV_ALLOW_REMOTE}=1 for that one invocation."
    )
