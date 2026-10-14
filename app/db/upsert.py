"""Insert-or-update ("upsert") that works on both SQLite and Postgres.

Both databases support INSERT ... ON CONFLICT (key) DO UPDATE. SQLAlchemy exposes
it through a dialect-specific insert(), so we pick the right one at runtime.
"""

from typing import Any

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.db.models import Base


def upsert(
    session: Session,
    model: type[Base],
    rows: list[dict[str, Any]],
    key_column: str,
    keep_on_conflict: list[str],
) -> None:
    """Insert rows, updating any existing row that has the same key.

    Args:
        session: An open session. The caller decides when to commit.
        model: The ORM model to write to, e.g. Contractor.
        rows: One dict per row, keyed by column name. Every row must have the same keys.
        key_column: The primary key column that identifies a row, e.g. "gaf_id".
        keep_on_conflict: Columns written on insert but left alone when the row
            already exists, e.g. ["first_seen_run"].
    """
    if not rows:
        return

    # Postgres refuses to update the same row twice in one statement, so if a key
    # appears more than once, keep only its last row.
    rows = list({row[key_column]: row for row in rows}.values())

    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        insert = sqlite.insert
    elif dialect == "postgresql":
        insert = postgresql.insert
    else:
        raise NotImplementedError(f"upsert does not support the {dialect!r} dialect")

    statement = insert(model).values(rows)

    # On conflict, copy the new values ("excluded") over every column except the
    # key and the columns we were asked to keep.
    new_values = {
        column: statement.excluded[column]
        for column in rows[0]
        if column != key_column and column not in keep_on_conflict
    }
    statement = statement.on_conflict_do_update(index_elements=[key_column], set_=new_values)
    session.execute(statement)
