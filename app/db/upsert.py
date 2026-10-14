"""Insert-or-update ("upsert") that works on both SQLite and Postgres.

Both databases support INSERT ... ON CONFLICT (key) DO UPDATE. SQLAlchemy exposes
it through a dialect-specific insert(), so we pick the right one at runtime.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.db.models import Base


def upsert(
    session: Session,
    model: type[Base],
    rows: Sequence[dict[str, Any]],
    key_columns: Sequence[str],
    keep_on_conflict: Iterable[str] = (),
) -> None:
    """Insert rows, updating any existing row that has the same key.

    Args:
        session: An open session. The caller decides when to commit.
        model: The ORM model to write to, e.g. Contractor.
        rows: One dict per row, keyed by column name. Every row must have the same keys.
        key_columns: The columns that identify a row (a primary key or unique constraint).
        keep_on_conflict: Columns that are written on insert but left alone when the
            row already exists, e.g. first_seen_run.

    Note: ON CONFLICT updates skip the model's `onupdate` hooks, so include
    timestamps like updated_at in the rows yourself.
    """
    if not rows:
        return

    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        insert = sqlite.insert
    elif dialect == "postgresql":
        insert = postgresql.insert
    else:
        raise NotImplementedError(f"upsert does not support the {dialect!r} dialect")

    statement = insert(model).values(list(rows))

    # On conflict, copy the new values ("excluded") over every column except the key
    # and the columns we were asked to keep.
    not_updated = set(key_columns) | set(keep_on_conflict)
    new_values = {
        column: statement.excluded[column]
        for column in rows[0]
        if column not in not_updated
    }

    if new_values:
        statement = statement.on_conflict_do_update(index_elements=list(key_columns), set_=new_values)
    else:
        statement = statement.on_conflict_do_nothing(index_elements=list(key_columns))

    session.execute(statement)
