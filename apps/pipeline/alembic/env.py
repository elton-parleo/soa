"""
Alembic env.py for /soa.

Builds the Supabase connection URL using the same driver, username,
port, and env vars as /supply/modules/database.py. Passes a URL
object (not a string) directly to create_engine so the project-ref
portion of the username (postgres.epuofomhfngvkkamlfiz) is never
ambiguously re-parsed from a plain connection string.

The merchants table is referenced via ForeignKey string in the
migration only — this env.py never creates or alters it.
"""
import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from alembic import context

load_dotenv()

# Register all /soa models so autogenerate can detect them.
from soa_shared.models.base import Base
import soa_shared.models.merchant_ref  # noqa: F401
import soa_shared.models.soa_models    # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Tables exclusively owned and managed by the soa project.
# merchants is owned by supply and must never be touched by soa migrations.
SOA_TABLES = {
    "soa_queries",
    "soa_cycles",
    "soa_runs",
    "soa_coded_mentions",
    "soa_other_mentions",
    "soa_metrics_results",
    "soa_incentive_scores",
    "soa_eligibility_metrics",
}


def include_object(object, name, type_, reflected, compare_to):
    """Only manage tables that belong to the soa project."""
    if type_ == "table" and name not in SOA_TABLES:
        return False
    return True


def _make_url() -> URL:
    host = os.getenv("SUPABASE_DB_HOST_URL")
    password = os.getenv("SUPABASE_DB_PASSWORD")
    if not host or not password:
        raise RuntimeError(
            "SUPABASE_DB_HOST_URL and SUPABASE_DB_PASSWORD must be set. "
            "Copy /soa/.env.example to /soa/.env and fill in your credentials."
        )
    return URL.create(
        drivername="postgresql",
        username="postgres.epuofomhfngvkkamlfiz",
        host=host,
        database="postgres",
        port="6543",
        password=password,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_make_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_make_url(), poolclass=NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
