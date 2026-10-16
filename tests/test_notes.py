"""The notes and rep services, against a migrated temporary database (which seeds rep 1)."""

import pytest
from sqlalchemy.orm import Session

from app.db.models import Contractor, Rep, Run
from app.services.notes import add_note, current_statuses, lead_notes, status_group
from app.services.reps import get_rep, save_preset


@pytest.fixture
def contractors(session: Session) -> None:
    """Two contractors and a second rep, rep 2, beside the seeded rep 1."""
    run = Run(territory_zip="10013", radius_miles=25)
    session.add(run)
    session.flush()
    for gaf_id in ("a", "b"):
        session.add(Contractor(gaf_id=gaf_id, name=f"Roofer {gaf_id}", first_seen_run=run.id, last_seen_run=run.id))
    session.add(Rep(id=2, name="Other Rep", territory_zip="10013", radius_miles=25))
    session.flush()


@pytest.mark.usefixtures("contractors")
def test_a_lead_with_no_notes_is_new_and_the_newest_note_sets_the_status(session: Session) -> None:
    assert current_statuses(session, 1, ["a", "b"]) == {"a": "New", "b": "New"}

    add_note(session, 1, "a", "Contacted", "Left a voicemail.")
    add_note(session, 1, "a", "Considering us", "  Asked for a quote.  ")
    session.commit()

    assert current_statuses(session, 1, ["a", "b"]) == {"a": "Considering us", "b": "New"}
    assert [(note.previous_status, note.status, note.text) for note in lead_notes(session, 1, "a")] == [
        ("Contacted", "Considering us", "Asked for a quote."),  # newest first, trimmed
        ("New", "Contacted", "Left a voicemail."),
    ]
    assert lead_notes(session, 1, "a")[0].created_at.tzinfo is not None


@pytest.mark.usefixtures("contractors")
def test_a_rep_sees_only_their_own_notes(session: Session) -> None:
    add_note(session, 2, "a", "Not a fit", "Only does commercial.")
    session.commit()

    assert current_statuses(session, 1, ["a"]) == {"a": "New"}
    assert lead_notes(session, 1, "a") == []
    assert current_statuses(session, 2, ["a"]) == {"a": "Not a fit"}


@pytest.mark.usefixtures("contractors")
def test_an_unknown_status_is_refused(session: Session) -> None:
    with pytest.raises(ValueError, match="Unknown status"):
        add_note(session, 1, "a", "Hot", "")


def test_each_status_belongs_to_one_group() -> None:
    assert [status_group(status) for status in ["New", "Contacted", "Considering us", "First order", "Not a fit"]] == [
        "To contact",
        "In progress",
        "In progress",
        "First order",
        "Not a fit",
    ]


def test_a_reps_preset_is_saved_and_read_back(session: Session) -> None:
    assert get_rep(session, 1).preset is None  # not picked yet

    save_preset(session, 1, "Quick wins")
    session.commit()

    assert get_rep(session, 1).preset == "Quick wins"
    with pytest.raises(ValueError, match="Unknown preset"):
        save_preset(session, 1, "Nope")
