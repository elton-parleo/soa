"""
The remote-migration guard (migration_target.py) and the round-trip
helper's local assertion (scripts/migration_roundtrip.py).

alembic/env.py runs at import and cannot be imported by a test, which is
why the decision lives in migration_target.py; the wiring is asserted by
reading env.py's source, the same way supply tests its guard.
"""
import os

import pytest

import migration_target as mt

SUPABASE = (
    "postgresql://postgres.epuofomhfngvkkamlfiz:secret@"
    "aws-0-us-west-2.pooler.supabase.com:6543/postgres"
)


@pytest.mark.parametrize("url", [
    "postgresql://postgres@localhost/postgres",
    "postgresql://postgres@127.0.0.1:55432/postgres",
    "postgresql://postgres@[::1]/postgres",
    "postgresql://postgres@/postgres?host=/tmp/pg_sock",
])
def test_local_targets_are_local(url):
    assert mt.is_local(url)


@pytest.mark.parametrize("url", [
    SUPABASE,
    "postgresql://u:p@db.example.com/postgres",
    "postgresql://u:p@10.0.0.5/postgres",       # private is not local
    "postgresql://u:p@localhost.evil.com/postgres",
])
def test_everything_else_is_remote(url):
    assert not mt.is_local(url)


def test_a_remote_migration_is_refused_without_the_flag(monkeypatch):
    monkeypatch.delenv(mt.ENV_ALLOW_REMOTE, raising=False)
    with pytest.raises(mt.RemoteDatabaseError) as exc:
        mt.assert_migration_target_permitted(SUPABASE)
    message = str(exc.value)
    assert "pooler.supabase.com" in message
    assert mt.ENV_ALLOW_REMOTE in message
    assert "secret" not in message            # the password is masked


@pytest.mark.parametrize("value", ["", "0", "true", "yes"])
def test_only_the_exact_flag_value_opens_it(monkeypatch, value):
    monkeypatch.setenv(mt.ENV_ALLOW_REMOTE, value)
    with pytest.raises(mt.RemoteDatabaseError):
        mt.assert_migration_target_permitted(SUPABASE)


def test_the_flag_permits_and_announces_it(monkeypatch, capsys):
    monkeypatch.setenv(mt.ENV_ALLOW_REMOTE, "1")
    mt.assert_migration_target_permitted(SUPABASE)
    out = capsys.readouterr().out
    assert "REMOTE" in out and "secret" not in out


def test_a_local_migration_needs_no_flag(monkeypatch):
    monkeypatch.delenv(mt.ENV_ALLOW_REMOTE, raising=False)
    mt.assert_migration_target_permitted("postgresql://postgres@127.0.0.1:55432/postgres")


def test_require_local_refuses_remote_even_with_the_flag(monkeypatch):
    """The round-trip helper's assertion is stricter than the guard: no override."""
    monkeypatch.setenv(mt.ENV_ALLOW_REMOTE, "1")
    with pytest.raises(mt.RemoteDatabaseError):
        mt.require_local(SUPABASE, operation="round-trip")


def test_env_py_calls_the_guard_on_both_paths():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source = open(os.path.join(here, "alembic", "env.py")).read()
    online = source.split("def run_migrations_online")[1]
    offline = source.split("def run_migrations_offline")[1].split("def run_migrations_online")[0]
    for body in (online, offline):
        assert "assert_migration_target_permitted(url)" in body
        # Before anything connects or configures.
        assert body.index("assert_migration_target_permitted") < body.index("context.configure")


def test_the_round_trip_helper_refuses_an_unset_target(monkeypatch):
    """Unset means the Supabase default, i.e. production."""
    from scripts.migration_roundtrip import guard

    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    with pytest.raises(mt.RemoteDatabaseError, match="not set"):
        guard("upgrade")


def test_the_round_trip_helper_refuses_a_remote_target(monkeypatch):
    from scripts.migration_roundtrip import guard

    monkeypatch.setenv("ALEMBIC_DATABASE_URL", SUPABASE)
    with pytest.raises(mt.RemoteDatabaseError):
        guard("upgrade")


def test_the_round_trip_helper_accepts_a_local_target(monkeypatch):
    from scripts.migration_roundtrip import guard

    monkeypatch.setenv("ALEMBIC_DATABASE_URL", "postgresql://postgres@127.0.0.1:55432/postgres")
    assert guard("upgrade").host == "127.0.0.1"
