"""Alembic environment: runs migrations against DATABASE_URL using the app's engine.

render_as_batch=True makes `alembic revision --autogenerate` write table changes
as op.batch_alter_table(). On SQLite, which can't alter most column properties,
that rebuilds the table (copy, drop, rename). On Postgres it's a normal ALTER TABLE.
"""

from logging.config import fileConfig

from alembic import context

from app.db.engine import make_engine
from app.db.models import Base
from app.settings import Settings

config = context.config

# Set up logging from alembic.ini without silencing loggers that already exist
# (for example pytest's, when tests run migrations).
fileConfig(config.config_file_name, disable_existing_loggers=False)

# Tests point Alembic at a temporary database with set_main_option("sqlalchemy.url").
database_url = config.get_main_option("sqlalchemy.url") or Settings().database_url
engine = make_engine(database_url)

with engine.connect() as connection:
    if connection.dialect.name == "sqlite":
        # A batch rebuild drops tables, which SQLite blocks while foreign keys point
        # at them. Turn the checks off for this migration connection only.
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()  # end the implicit transaction so Alembic starts and commits its own

    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)

    with context.begin_transaction():
        context.run_migrations()

engine.dispose()
