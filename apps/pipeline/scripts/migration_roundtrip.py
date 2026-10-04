#!/usr/bin/env python3
"""
Round-trip a migration on a throwaway local Postgres — never anywhere else.

    ALEMBIC_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/postgres \\
        python3 scripts/migration_roundtrip.py --from <previous revision>

upgrade -> downgrade -> upgrade, with require_local() asserted before
every step, so "the connection was local" is checked by the script rather
than remembered by a person. Exercising the migration between the steps is
the caller's job: what "exercise" means is specific to the migration.

Usable as a library too:

    from scripts.migration_roundtrip import guard, alembic
    guard("stamp"); alembic("upgrade", "head")

Starting the throwaway server is out of scope on purpose — it is one
initdb away, and a helper that also managed it would need trusting with
pg_ctl stop.
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migration_target import RemoteDatabaseError, require_local, safe_display  # noqa: E402

ENV_TARGET = "ALEMBIC_DATABASE_URL"


def guard(step: str = "migration round-trip step"):
    """
    Assert ALEMBIC_DATABASE_URL is set and local, or raise.

    Unset is refused too: alembic/env.py's default is the live Supabase
    database, so "no override" means "production" here.
    """
    target = os.getenv(ENV_TARGET)
    if not target:
        raise RemoteDatabaseError(
            f"{step} refused: {ENV_TARGET} is not set, so alembic would target the "
            f"Supabase default. Point it at a local Postgres."
        )
    return require_local(target, operation=step)


def alembic(*args: str) -> subprocess.CompletedProcess:
    """One alembic command, against a target proven local first."""
    url = guard(f"alembic {' '.join(args)}")
    print(f"  -> alembic {' '.join(args)}  [{safe_display(url)}]")
    env = dict(os.environ)
    env.pop("SOA_ALLOW_REMOTE_MIGRATION", None)  # never needed, never inherited
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        check=True, capture_output=True, text=True, env=env,
    )


def roundtrip(base_revision: str, target: str = "head") -> None:
    guard("round-trip")
    print(f"round-tripping {base_revision} -> {target} on {safe_display(os.environ[ENV_TARGET])}")
    alembic("upgrade", target)
    alembic("downgrade", base_revision)
    alembic("upgrade", target)
    print("round-trip complete: upgrade, downgrade and re-upgrade all applied")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="base", required=True,
                        help="Revision to downgrade back to (the one before the new migration).")
    parser.add_argument("--to", default="head")
    args = parser.parse_args()
    try:
        roundtrip(args.base, args.to)
    except RemoteDatabaseError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"\nalembic failed:\n{exc.stderr}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
