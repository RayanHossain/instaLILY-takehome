"""The initial migration builds every table and seeds one rep."""

import pytest
from sqlalchemy import Engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import RawResponse, Rep


def test_upgrade_head_creates_tables_and_seeds_a_rep(engine: Engine, session: Session) -> None:
    tables = set(inspect(engine).get_table_names())
    assert {"runs", "contractors", "raw_responses", "reps"} <= tables

    reps = session.scalars(select(Rep)).all()
    assert len(reps) == 1
    assert reps[0].territory_zip == "10013"
    assert reps[0].radius_miles == 25


def test_sqlite_enforces_foreign_keys(session: Session) -> None:
    # Run 999 doesn't exist, so this insert must fail.
    session.add(
        RawResponse(run_id=999, source="test", url="https://example.com", body="{}", content_hash="0" * 64)
    )
    with pytest.raises(IntegrityError):
        session.flush()
