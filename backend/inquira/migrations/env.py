"""Alembic environment. Uses the app's engine settings; works for SQLite (batch mode) and Postgres."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from inquira.core.config import get_settings
from inquira.db import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is None:  # invoked from the alembic CLI
        engine = engine_from_config({"sqlalchemy.url": get_settings().database_url}, prefix="sqlalchemy.",
                                    poolclass=pool.NullPool)
        with engine.connect() as connection:
            _run(connection)
    else:  # invoked programmatically from inquira.db.migrate()
        _run(connection)


def _run(connection) -> None:  # type: ignore[no-untyped-def]
    # render_as_batch lets ALTERs work on SQLite (copy-and-move); it is a no-op cost on Postgres.
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
