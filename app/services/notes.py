"""Notes services: a rep's notes and statuses on leads, kept as an append-only history.

Every save adds a row to lead_notes; nothing is edited or deleted, so the history comes
free. A lead's current status is its newest row's, and a lead with no rows is New. Every
function takes the rep's id, and a rep reads and writes only their own rows.
"""

from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LeadNote

# The statuses, in ladder order. "Considering us": asked for pricing or a quote.
STATUSES = ["New", "Contacted", "Considering us", "First order", "Not a fit"]
# The groups the lead list filters by, and the statuses in each. A first order and "Not a
# fit" get a group each: one is a win and the other a dead end, so a rep looks for them apart.
STATUS_GROUPS = {
    "To contact": ["New"],
    "In progress": ["Contacted", "Considering us"],
    "First order": ["First order"],
    "Not a fit": ["Not a fit"],
}


class Note(BaseModel):
    """One saved note: the status it set, its text, and when."""

    status: str
    text: str  # empty when the rep only changed the status
    created_at: datetime  # in UTC


def status_group(status: str) -> str:
    """The group a status belongs to, e.g. "In progress" for "Contacted"."""
    return next(group for group, statuses in STATUS_GROUPS.items() if status in statuses)


def current_statuses(session: Session, rep_id: int, contractor_ids: list[str]) -> dict[str, str]:
    """Each lead's current status for this rep: its newest note's status, or New when it has none."""
    statuses = dict.fromkeys(contractor_ids, "New")
    notes = session.execute(
        select(LeadNote.contractor_id, LeadNote.status).where(LeadNote.rep_id == rep_id).order_by(LeadNote.created_at, LeadNote.id)
    )
    for contractor_id, status in notes:  # oldest first, so the newest note's status wins
        if contractor_id in statuses:
            statuses[contractor_id] = status
    return statuses


def lead_notes(session: Session, rep_id: int, contractor_id: str) -> list[Note]:
    """This rep's notes on one lead, newest first."""
    notes = session.scalars(
        select(LeadNote)
        .where(LeadNote.rep_id == rep_id, LeadNote.contractor_id == contractor_id)
        .order_by(LeadNote.created_at.desc(), LeadNote.id.desc())
    )
    return [Note(status=note.status, text=note.text, created_at=_in_utc(note.created_at)) for note in notes]


def add_note(session: Session, rep_id: int, contractor_id: str, status: str, text: str) -> None:
    """Add a note that sets the lead's status for this rep. The caller commits.

    Raises:
        ValueError: The status isn't one of STATUSES.
    """
    if status not in STATUSES:
        raise ValueError(f"Unknown status {status!r}; choose from {', '.join(STATUSES)}")
    session.add(LeadNote(rep_id=rep_id, contractor_id=contractor_id, status=status, text=text.strip()))


def _in_utc(moment: datetime) -> datetime:
    """A stored time with its timezone: SQLite hands times back without one, and they were saved in UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
