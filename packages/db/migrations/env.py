"""Alembic environment: connects as scheduling_owner and keeps its version table in `app`."""

import os

from alembic import context
from sqlalchemy import create_engine, pool

from db.models import SCHEMA, Base

target_metadata = Base.metadata


def _url() -> str:
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        raise SystemExit("Set MIGRATION_DATABASE_URL (a scheduling_owner connection string).")
    return url


def run_migrations_online() -> None:
    # scheduling_owner's search_path is `app`. Override it when the connection opens, so
    # SQLAlchemy sees `app` as a named schema (matching the models), not as the default one.
    # A later `SET search_path` is too late: the default schema is read at connect time.
    engine = create_engine(
        _url(), poolclass=pool.NullPool, connect_args={"options": "-c search_path=public"}
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=SCHEMA,
            include_schemas=True,
            include_name=lambda name, type_, _parent: type_ != "schema" or name == SCHEMA,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
