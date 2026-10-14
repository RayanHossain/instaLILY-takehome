"""Alembic environment: runs migrations against DATABASE_URL using the app's engine.

render_as_batch=True makes Alembic rebuild tables for ALTERs on SQLite, which
can't alter columns in place. On Postgres it falls back to normal ALTER TABLE.
"""

from logging.config import fileConfig

from alembic import context

from app.db.engine import make_engine
from app.db.models import Base
from app.settings import get_settings

config = context.config

# Set up logging from alembic.ini without silencing loggers that already exist
# (for example pytest's, when tests run migrations).
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_database_url() -> str:
    """Use a URL set on the Alembic config if there is one (tests do this), else DATABASE_URL."""
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    """Write the migration SQL out as a script instead of running it (alembic upgrade --sql)."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database.

    Uses the app's make_engine, so SQLite gets the same foreign key and WAL settings.
    """
    engine = make_engine(get_database_url())

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()

    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
