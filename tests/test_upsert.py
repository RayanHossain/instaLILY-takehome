"""The upsert helper inserts new rows and updates existing ones in place."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Contractor, Run
from app.db.upsert import upsert


def test_upsert_inserts_then_updates_without_duplicates(session: Session) -> None:
    first_run = Run(territory_zip="10013", radius_miles=25)
    second_run = Run(territory_zip="10013", radius_miles=25)
    session.add_all([first_run, second_run])
    session.flush()

    row = {"gaf_id": "0012345", "name": "Acme", "first_seen_run": first_run.id, "last_seen_run": first_run.id}
    upsert(session, Contractor, [row], key_column="gaf_id", keep_on_conflict=["first_seen_run"])
    changed = {**row, "name": "Acme Roofing", "first_seen_run": second_run.id, "last_seen_run": second_run.id}
    upsert(session, Contractor, [changed], key_column="gaf_id", keep_on_conflict=["first_seen_run"])

    assert session.scalar(select(func.count()).select_from(Contractor)) == 1
    contractor = session.get(Contractor, "0012345")
    assert contractor.name == "Acme Roofing"
    assert contractor.first_seen_run == first_run.id  # kept from the first insert
    assert contractor.last_seen_run == second_run.id


def test_upsert_with_no_rows_does_nothing(session: Session) -> None:
    upsert(session, Contractor, [], key_column="gaf_id", keep_on_conflict=[])
    assert session.scalar(select(func.count()).select_from(Contractor)) == 0
