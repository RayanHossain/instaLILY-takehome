"""Database engine setup.

SQLite gets two settings on every new connection: foreign keys on (SQLite ignores
them by default) and WAL journaling (readers don't block the writer). Postgres
needs neither.
"""

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url


def make_engine(database_url: str) -> Engine:
    """Create an engine for a database URL such as sqlite:///data/leads.db."""
    url = make_url(database_url)
    engine = create_engine(url)

    if url.get_backend_name() == "sqlite":
        # SQLite creates the database file but not its folder (e.g. data/).
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        event.listen(engine, "connect", _set_sqlite_pragmas)

    return engine


def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    """Turn on foreign keys and WAL for a new SQLite connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
