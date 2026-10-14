"""Database engine setup.

SQLite gets two settings on every new connection: foreign keys on (SQLite ignores
them by default) and WAL journaling (readers don't block the writer). Other
databases, such as Postgres, need neither.
"""

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url

from app.settings import get_settings


def make_engine(database_url: str | None = None) -> Engine:
    """Create an engine for the given URL, or for DATABASE_URL from settings."""
    url = make_url(database_url or get_settings().database_url)

    if url.get_backend_name() == "sqlite":
        _create_sqlite_folder(url.database)

    engine = create_engine(url)

    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _set_sqlite_pragmas)

    return engine


def _create_sqlite_folder(database: str | None) -> None:
    """Make sure the folder for a SQLite file exists (e.g. data/ for data/leads.db)."""
    if database and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)


def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    """Turn on foreign keys and WAL for a new SQLite connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
